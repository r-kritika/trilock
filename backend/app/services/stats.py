from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AuthAttempt, EvaluationRun, Event, Transaction, User


def dashboard(db: Session, registry, user_id: int | None = None) -> dict:
    """Dashboard numbers. user_id=None means all users (administrators only)."""
    def scoped(q, model):
        return q.filter(model.user_id == user_id) if user_id else q

    total = scoped(db.query(func.count(Transaction.id)), Transaction).scalar()
    by_decision = dict(scoped(db.query(Transaction.decision, func.count()), Transaction).group_by(Transaction.decision).all())
    by_risk = dict(scoped(db.query(Transaction.risk_category, func.count()), Transaction).group_by(Transaction.risk_category).all())
    by_attempt = dict(scoped(db.query(AuthAttempt.decision, func.count()), AuthAttempt).group_by(AuthAttempt.decision).all())
    attempts = scoped(db.query(AuthAttempt), AuthAttempt).all()

    # how often each modality actually produced usable evidence
    mod = {m: {"match": 0, "no_match": 0, "not_evaluated": 0} for m in ("face", "fingerprint", "voice")}
    lat = []
    for a in attempts:
        lat.append(a.latency_ms)
        for r in a.modality_results:
            if r["reason_code"] == "not_provided":
                continue
            mod[r["modality"]][r["status"]] += 1

    def row(t: Transaction):
        return {"id": t.id, "user_name": t.user.full_name, "amount": t.amount, "currency": t.currency,
                "recipient_name": t.recipient_name, "risk_category": t.risk_category,
                "risk_score": t.risk_score, "decision": t.decision, "created_at": t.created_at}

    recent = scoped(db.query(Transaction), Transaction).order_by(Transaction.id.desc()).limit(8).all()
    suspicious = (scoped(db.query(Transaction), Transaction).filter(Transaction.decision == "rejected")
                  .order_by(Transaction.id.desc()).limit(6).all())
    return {
        "total_transactions": total,
        "pending": by_decision.get("pending", 0),
        "approved": by_decision.get("approved", 0),
        "rejected": by_decision.get("rejected", 0),
        "additional_verification": by_decision.get("additional_verification_required", 0),
        "risk_distribution": {k: by_risk.get(k, 0) for k in ("low", "medium", "high", "critical")},
        "attempts": {"total": len(attempts), "approved": by_attempt.get("approved", 0),
                     "rejected": by_attempt.get("rejected", 0),
                     "additional": by_attempt.get("additional_verification_required", 0)},
        "mean_attempt_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
        "modality_outcomes": mod,
        "modules": registry.statuses(),
        "user_count": db.query(func.count(User.id)).scalar() if not user_id else 1,
        "scope": "user" if user_id else "all",
        "recent_transactions": [row(t) for t in recent],
        "suspicious": [row(t) for t in suspicious],
        "evaluation_runs": db.query(func.count(EvaluationRun.id)).scalar(),
    }
