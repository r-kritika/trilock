"""Hand-written scenarios that show how the two policies differ. Illustrative only."""
from ..biometrics.types import ModalityResult, VerificationStatus
from .fusion import FusionConfig, fixed_threshold_fusion, risk_aware_fusion


def _r(mod: str, p: float | None, q: float = 0.9, reason: str | None = None) -> ModalityResult:
    if p is None:
        return ModalityResult.not_evaluated(mod, "demo", "not_provided", reason or "not provided")
    return ModalityResult(modality=mod, status=VerificationStatus.MATCH if p >= 0.5 else VerificationStatus.NO_MATCH,
                          method="demo", raw_score=None, calibrated=p, quality=q)


SCENARIOS = [
    ("Small payment, face only, good match", "low", [_r("face", 0.92), _r("fingerprint", None), _r("voice", None)]),
    ("Small payment, all three clearly match", "low", [_r("face", 0.95), _r("fingerprint", 0.9), _r("voice", 0.93)]),
    ("Large new-payee transfer, face only", "high", [_r("face", 0.97), _r("fingerprint", None), _r("voice", None)]),
    ("Large transfer, face + voice match", "high", [_r("face", 0.94), _r("fingerprint", None), _r("voice", 0.9)]),
    ("Critical transfer, two of three match", "critical", [_r("face", 0.95), _r("fingerprint", None), _r("voice", 0.93)]),
    ("Critical transfer, all three match", "critical", [_r("face", 0.97), _r("fingerprint", 0.95), _r("voice", 0.96)]),
    ("Medium transfer, one modality contradicts", "medium", [_r("face", 0.95), _r("fingerprint", 0.9), _r("voice", 0.08)]),
    ("Impostor on all three modalities", "medium", [_r("face", 0.05), _r("fingerprint", 0.03), _r("voice", 0.1)]),
    ("Nothing could be evaluated (camera denied, no mic)", "high", [_r("face", None), _r("fingerprint", None), _r("voice", None)]),
]


def run_scenarios(cfg: FusionConfig) -> list[dict]:
    out = []
    for name, cat, results in SCENARIOS:
        out.append({
            "name": name, "risk_category": cat,
            "inputs": {r.modality: r.calibrated for r in results},
            "fixed": fixed_threshold_fusion(results, cat, cfg).to_dict(),
            "risk_aware": risk_aware_fusion(results, cat, cfg).to_dict(),
        })
    return out
