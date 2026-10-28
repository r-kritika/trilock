"""Transaction creation and the multimodal authentication workflow."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..biometrics.registry import ORDER, BiometricRegistry
from ..biometrics.types import ModalityResult
from ..config import Settings
from ..errors import ApiError
from ..models import AuthAttempt, Event, Transaction, User, utcnow
from .events import log_event
from .fusion import POLICIES, Decision, FusionConfig, risk_aware_fusion, fixed_threshold_fusion
from .risk import RiskConfig, RiskInput, assess_risk
from .templates import TemplateStore

log = logging.getLogger("trilock")


def create_transaction(db: Session, user: User, data: dict, risk_cfg: RiskConfig) -> Transaction:
    count, mean = db.query(func.count(Transaction.id), func.avg(Transaction.amount)).filter(
        Transaction.user_id == user.id, Transaction.decision == Decision.APPROVED.value).one()
    risk = assess_risk(RiskInput(
        amount=data["amount"], transaction_type=data["transaction_type"],
        recipient_is_new=data["recipient_is_new"], is_international=data["is_international"],
        new_device=data["new_device"], history_count=count or 0, history_mean_amount=float(mean or 0)), risk_cfg)
    txn = Transaction(risk_score=risk.score, risk_category=risk.category.value,
                      risk_factors=risk.to_dict()["factors"], decision="pending", **data)
    db.add(txn)
    db.commit()
    log_event(db, "transaction_created", user.id, txn.id, amount=txn.amount, risk=risk.category.value)
    return txn


def check_biometric_lockout(db: Session, user_id: int, settings: Settings) -> None:
    """Too many failed biometric tries in a window pauses further tries. This slows down both
    guessing and score-probing (hill climbing) against the matcher."""
    since = utcnow() - timedelta(minutes=settings.biometric_window_minutes)
    n = db.query(func.count(Event.id)).filter(Event.user_id == user_id, Event.kind == "biometric_failure",
                                              Event.created_at >= since).scalar()
    if n >= settings.biometric_failure_limit:
        raise ApiError(429, "too_many_failures",
                       f"Too many failed biometric attempts. Try again in {settings.biometric_window_minutes} minutes.")


def run_modality(module, modality: str, template: dict | None, sample: bytes | None, db: Session,
                 user_id: int) -> ModalityResult:
    """Evaluate one modality. Every failure path yields NOT_EVALUATED, never a match."""
    if sample is None:
        return ModalityResult.not_evaluated(modality, module.method, "not_provided", "No sample was submitted.")
    if template is None:
        return ModalityResult.not_evaluated(modality, module.method, "not_enrolled",
                                            "This user has no enrolled reference for this modality.")
    try:
        return module.verify(template, sample)
    except Exception as e:  # a model crash must not look like a match or a mismatch
        log.exception("verification crashed: %s", modality)
        log_event(db, "verification_error", user_id, modality=modality, error=f"{type(e).__name__}: {e}")
        return ModalityResult.not_evaluated(modality, module.method, "inference_failed",
                                            "The verification model failed on this input.")


def authenticate(db: Session, txn: Transaction, samples: dict[str, bytes | None], registry: BiometricRegistry,
                 store: TemplateStore, fusion_cfg: FusionConfig, settings: Settings) -> AuthAttempt:
    if txn.decision in (Decision.APPROVED.value, Decision.REJECTED.value):
        raise ApiError(409, "transaction_closed", f"Transaction already {txn.decision}.")
    if len(txn.attempts) >= settings.max_auth_attempts:
        raise ApiError(409, "attempt_limit", "Maximum authentication attempts reached.")
    check_biometric_lockout(db, txn.user_id, settings)

    t0 = time.perf_counter()
    results = []
    for name in ORDER:
        sample = samples.get(name)
        template = store.load(txn.user_id, name) if sample is not None else None
        results.append(run_modality(registry.get(name), name, template, sample, db, txn.user_id))

    fixed = fixed_threshold_fusion(results, txn.risk_category, fusion_cfg)
    aware = risk_aware_fusion(results, txn.risk_category, fusion_cfg)
    active = {"fixed": fixed, "risk_aware": aware}[settings.active_policy]
    decision, explanation = active.decision, active.explanation

    attempt_no = len(txn.attempts) + 1
    if decision == Decision.ADDITIONAL and attempt_no >= settings.max_auth_attempts:
        decision = Decision.REJECTED
        explanation += (f" The limit of {settings.max_auth_attempts} attempts was reached without approval, "
                        "so the transaction was rejected.")

    # An attempt with usable evidence that ends in a rejection counts toward the lockout.
    # "Could not evaluate" outcomes do not (a broken camera is not an attack).
    counts_as_failure = decision == Decision.REJECTED and any(r.usable for r in results)

    attempt = AuthAttempt(
        transaction_id=txn.id, user_id=txn.user_id, modality_results=[r.to_dict() for r in results],
        fixed_outcome=fixed.to_dict(), risk_aware_outcome=aware.to_dict(), active_policy=settings.active_policy,
        decision=decision.value, explanation=explanation, latency_ms=round((time.perf_counter() - t0) * 1000, 1))
    db.add(attempt)
    txn.decision, txn.decision_reason = decision.value, explanation
    if decision != Decision.ADDITIONAL:
        txn.decided_at = datetime.now(timezone.utc)
    # Close the transaction only if nobody else closed it meanwhile (two concurrent requests).
    closed = db.query(Transaction).filter(
        Transaction.id == txn.id, Transaction.decision.in_(["pending", Decision.ADDITIONAL.value])
    ).update({"decision": decision.value, "decision_reason": explanation,
              "decided_at": txn.decided_at}, synchronize_session=False)
    if not closed:
        db.rollback()
        raise ApiError(409, "transaction_closed", "Transaction was decided by another request.")
    db.commit()
    if counts_as_failure:
        log_event(db, "biometric_failure", txn.user_id, txn.id, via="authenticate")
    log_event(db, "authentication", txn.user_id, txn.id, decision=decision.value, policy=settings.active_policy,
              fused=active.fused_score, attempt=attempt_no)
    return attempt
