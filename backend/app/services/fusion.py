"""Multimodal fusion and decision policies.

Two policies are implemented and both are deterministic functions of (module results, risk
category, config):

A. Fixed-threshold fusion (baseline)
   fused = weighted mean of calibrated scores over the modalities that could be evaluated.
   Approve if fused >= one global threshold, otherwise reject. Ignores transaction risk and
   input quality. If nothing could be evaluated the baseline asks for another verification
   instead of guessing.

B. Risk-aware fusion (proposed)
   1. Each usable modality gets a reliability weight  w_i * (0.4 + 0.6 * quality_i).
   2. fused = reliability-weighted mean of calibrated scores.
   3. coverage = sum of reliability weights of usable modalities / sum of base weights. This
      measures how much of the full three-modality evidence we actually have.
   4. The transaction's risk category selects a policy band with its own approve threshold,
      reject threshold, minimum number of usable modalities, minimum coverage and a
      "conflict floor" (no usable modality may score below it for an approval).
   5. Decision:
        - fused < reject_threshold                       -> REJECTED   (clear mismatch)
        - fused >= approve_threshold AND enough evidence
          AND no conflicting modality                    -> APPROVED
        - anything else                                  -> ADDITIONAL_VERIFICATION
   Missing or unevaluable modalities never add to the score. They lower coverage, so a
   high-risk transaction with only one modality cannot be approved however good that score is.

All thresholds below are experimental starting values. They have not been tuned on real
transaction data and need calibration before any serious claim is made.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from ..biometrics.types import ModalityResult, VerificationStatus
from .risk import RiskCategory


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ADDITIONAL = "additional_verification_required"


@dataclass
class Band:
    approve: float
    reject: float
    min_modalities: int
    min_coverage: float
    conflict_floor: float


@dataclass
class FusionConfig:
    weights: dict[str, float] = field(default_factory=lambda: {"face": 1.0, "fingerprint": 1.0, "voice": 1.0})
    fixed_threshold: float = 0.70
    bands: dict[str, Band] = field(default_factory=lambda: {
        "low":      Band(approve=0.60, reject=0.30, min_modalities=1, min_coverage=0.30, conflict_floor=0.00),
        "medium":   Band(approve=0.70, reject=0.35, min_modalities=2, min_coverage=0.50, conflict_floor=0.15),
        "high":     Band(approve=0.80, reject=0.40, min_modalities=2, min_coverage=0.60, conflict_floor=0.25),
        "critical": Band(approve=0.88, reject=0.45, min_modalities=3, min_coverage=0.70, conflict_floor=0.35),
    })


@dataclass
class FusionOutcome:
    policy: str
    decision: Decision
    fused_score: float | None
    approve_threshold: float
    reject_threshold: float | None
    risk_category: str
    usable: list[str]
    unusable: dict[str, str]          # modality -> reason it could not be used
    coverage: float
    unmet: list[str]                  # human-readable unmet requirements
    explanation: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


def _split(results: list[ModalityResult]):
    usable = [r for r in results if r.usable]
    unusable = {r.modality: (r.reason or "could not be evaluated") for r in results if not r.usable}
    return usable, unusable


def _fmt(names: list[str]) -> str:
    return ", ".join(names) if names else "none"


def fixed_threshold_fusion(results: list[ModalityResult], risk_category: RiskCategory | str,
                           cfg: FusionConfig | None = None) -> FusionOutcome:
    cfg = cfg or FusionConfig()
    cat = RiskCategory(risk_category).value
    usable, unusable = _split(results)
    common = dict(policy="fixed", approve_threshold=cfg.fixed_threshold, reject_threshold=None,
                  risk_category=cat, unusable=unusable)
    if not usable:
        return FusionOutcome(decision=Decision.ADDITIONAL, fused_score=None, usable=[], coverage=0.0,
                             unmet=["no biometric input could be evaluated"],
                             explanation="No biometric sample could be evaluated, so there is nothing to decide on. "
                                         "Another verification step is needed.", **common)
    wsum = sum(cfg.weights[r.modality] for r in usable)
    fused = sum(cfg.weights[r.modality] * r.calibrated for r in usable) / wsum
    cov = wsum / sum(cfg.weights.values())
    names = [r.modality for r in usable]
    if fused >= cfg.fixed_threshold:
        dec, text = Decision.APPROVED, (f"Fused score {fused:.2f} from {_fmt(names)} reached the fixed threshold "
                                        f"{cfg.fixed_threshold:.2f}.")
    else:
        dec, text = Decision.REJECTED, (f"Fused score {fused:.2f} from {_fmt(names)} is below the fixed threshold "
                                        f"{cfg.fixed_threshold:.2f}.")
    return FusionOutcome(decision=dec, fused_score=round(fused, 4), usable=names, coverage=round(cov, 4),
                         unmet=[], explanation=text, **common)


def reliability(r: ModalityResult, base_weight: float) -> float:
    q = 1.0 if r.quality is None else max(0.0, min(1.0, r.quality))
    return base_weight * (0.4 + 0.6 * q)


def risk_aware_fusion(results: list[ModalityResult], risk_category: RiskCategory | str,
                      cfg: FusionConfig | None = None) -> FusionOutcome:
    cfg = cfg or FusionConfig()
    cat = RiskCategory(risk_category).value
    band = cfg.bands[cat]
    usable, unusable = _split(results)
    common = dict(policy="risk_aware", approve_threshold=band.approve, reject_threshold=band.reject,
                  risk_category=cat, unusable=unusable)

    if not usable:
        return FusionOutcome(decision=Decision.ADDITIONAL, fused_score=None, usable=[], coverage=0.0,
                             unmet=["no biometric input could be evaluated"],
                             explanation=f"This is a {cat}-risk transaction and no biometric sample could be "
                                         "evaluated. This is not treated as a mismatch; another verification step "
                                         "is required.", **common)

    rel = {r.modality: reliability(r, cfg.weights[r.modality]) for r in usable}
    rsum = sum(rel.values())
    fused = sum(rel[r.modality] * r.calibrated for r in usable) / rsum
    cov = rsum / sum(cfg.weights.values())
    names = [r.modality for r in usable]

    unmet: list[str] = []
    if len(usable) < band.min_modalities:
        unmet.append(f"{cat}-risk transactions need at least {band.min_modalities} evaluated modalities "
                     f"(got {len(usable)})")
    if cov < band.min_coverage:
        unmet.append(f"evidence coverage {cov:.2f} is below the required {band.min_coverage:.2f}")
    weak = [r.modality for r in usable if r.calibrated < band.conflict_floor]
    if weak:
        unmet.append(f"{_fmt(weak)} scored below the conflict floor {band.conflict_floor:.2f}")

    fused_r = round(fused, 4)
    if fused < band.reject:
        dec = Decision.REJECTED
        text = (f"Fused score {fused:.2f} is below the {cat}-risk reject threshold {band.reject:.2f}. "
                f"The evaluated biometrics ({_fmt(names)}) do not match the enrolled user.")
        unmet = []
    elif fused >= band.approve and not unmet:
        dec = Decision.APPROVED
        text = (f"Fused score {fused:.2f} from {_fmt(names)} reached the {cat}-risk approve threshold "
                f"{band.approve:.2f} with enough evidence (coverage {cov:.2f}).")
    else:
        dec = Decision.ADDITIONAL
        if fused >= band.approve:
            text = (f"Fused score {fused:.2f} would pass the {cat}-risk threshold {band.approve:.2f}, but "
                    + "; ".join(unmet) + ". More evidence is required before approving.")
        else:
            text = (f"Fused score {fused:.2f} is between the reject threshold {band.reject:.2f} and the "
                    f"{cat}-risk approve threshold {band.approve:.2f}, which is not enough to approve or reject.")
            if unmet:
                text += " Also: " + "; ".join(unmet) + "."
    if unusable:
        text += " Not evaluated: " + "; ".join(f"{m} ({why})" for m, why in unusable.items()) + "."
    return FusionOutcome(decision=dec, fused_score=fused_r, usable=names, coverage=round(cov, 4),
                         unmet=unmet, explanation=text, **common)


def fixed_min_modalities_fusion(results: list[ModalityResult], risk_category: RiskCategory | str,
                                cfg: FusionConfig | None = None, min_modalities: int = 2) -> FusionOutcome:
    """Ablation baseline used only in the evaluation: the fixed threshold plus ONE static rule,
    "at least `min_modalities` evaluated modalities for an approval", whatever the risk. It answers
    whether risk-aware fusion adds anything beyond simply requiring two modalities every time."""
    out = fixed_threshold_fusion(results, risk_category, cfg)
    if out.decision == Decision.APPROVED and len(out.usable) < min_modalities:
        out.decision = Decision.ADDITIONAL
        out.unmet = [f"at least {min_modalities} evaluated modalities are required (got {len(out.usable)})"]
        out.explanation += f" But only {len(out.usable)} modality was evaluated and {min_modalities} are required."
    out.policy = "fixed_min2"
    return out


POLICIES = {"fixed": fixed_threshold_fusion, "risk_aware": risk_aware_fusion}


def load_policy_config(path) -> tuple:
    """Build (RiskConfig, FusionConfig) from an optional JSON file; defaults for anything missing."""
    import json
    from .risk import RiskConfig
    risk, fusion = RiskConfig(), FusionConfig()
    if not path:
        return risk, fusion
    raw = json.loads(open(path).read())
    for k, v in raw.get("risk", {}).items():
        if not hasattr(risk, k):
            raise ValueError(f"unknown risk setting '{k}'")
        setattr(risk, k, v)
    fz = raw.get("fusion", {})
    for k, v in fz.items():
        if k == "bands":
            for name, b in v.items():
                fusion.bands[name] = Band(**{**asdict(fusion.bands[name]), **b})
        elif hasattr(fusion, k):
            setattr(fusion, k, v)
        else:
            raise ValueError(f"unknown fusion setting '{k}'")
    return risk, fusion
