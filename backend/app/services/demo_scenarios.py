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
    ("Critical transfer, face and voice match (no fingerprint needed)", "critical", [_r("face", 0.95), _r("fingerprint", None), _r("voice", 0.93)]),
    ("Critical transfer, face and fingerprint match but no voice", "critical", [_r("face", 0.95), _r("fingerprint", 0.95), _r("voice", None)]),
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


def run_risk_scenarios(cfg) -> list[dict]:
    """The same payment under different timing, run through the real risk engine. Illustrative, not data."""
    from .risk import RiskInput, assess_risk
    base = dict(amount=1200.0)
    cases = [
        ("Baseline: 1,200 USD at 2 pm, settled account", dict(local_hour=14, typical_hour=14.0, account_age_hours=900, history_count=12, history_mean_amount=900)),
        ("Same payment at 3 am (user normally pays around 2 pm)", dict(local_hour=3, typical_hour=14.0, account_age_hours=900, history_count=12, history_mean_amount=900)),
        ("Same payment at 3 am for a night-shift worker", dict(local_hour=3, typical_hour=2.0, account_age_hours=900, history_count=12, history_mean_amount=900)),
        ("Third payment in ten minutes", dict(local_hour=14, typical_hour=14.0, recent_count=2, account_age_hours=900, history_count=12, history_mean_amount=900)),
        ("Fifth payment in ten minutes", dict(local_hour=14, typical_hour=14.0, recent_count=4, account_age_hours=900, history_count=12, history_mean_amount=900)),
        ("Account created three hours ago", dict(local_hour=14, account_age_hours=3)),
        ("First payment in 90 days", dict(local_hour=14, typical_hour=14.0, hours_since_last_txn=90 * 24, account_age_hours=3000, history_count=12, history_mean_amount=900)),
        ("Face reference replaced two hours ago", dict(local_hour=14, typical_hour=14.0, biometric_changed_hours_ago=2, account_age_hours=900, history_count=12, history_mean_amount=900)),
        ("Everything at once: 3 am, rush, new account, face just replaced", dict(local_hour=3, recent_count=4, account_age_hours=3, biometric_changed_hours_ago=2)),
    ]
    out = []
    for name, extra in cases:
        r = assess_risk(RiskInput(**base, **extra), cfg)
        out.append({"name": name, "score": r.score, "category": r.category.value,
                    "factors": [{"name": f.name, "points": f.points, "description": f.description} for f in r.factors]})
    return out
