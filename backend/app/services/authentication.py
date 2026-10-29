"""Transaction creation and the multimodal authentication workflow."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..biometrics.registry import ORDER, BiometricRegistry
from ..biometrics.types import ModalityResult
from .challenges import Challenge
from ..config import Settings
from ..errors import ApiError
from ..models import AuthAttempt, Transaction, User, utcnow
from . import abuse
from .events import log_event
from .fusion import POLICIES, Decision, FusionConfig, risk_aware_fusion, fixed_threshold_fusion
from .risk import RiskConfig, RiskInput, assess_risk
from .templates import TemplateStore

log = logging.getLogger("trilock")


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def typical_hour(hours: list[int]) -> float | None:
    """Circular mean of the hours of day. None if the hours are spread around the clock (no usual time)."""
    import math
    if not hours:
        return None
    x = sum(math.cos(h / 24 * 2 * math.pi) for h in hours) / len(hours)
    y = sum(math.sin(h / 24 * 2 * math.pi) for h in hours) / len(hours)
    if math.hypot(x, y) < 0.3:
        return None
    return (math.atan2(y, x) / (2 * math.pi) * 24) % 24


def build_risk_input(db: Session, user: User, data: dict, cfg: RiskConfig) -> RiskInput:
    """Everything the risk engine needs to know about this user's recent past, read from the database."""
    from datetime import timedelta
    from ..models import Event
    now = utcnow()
    approved = db.query(Transaction).filter(Transaction.user_id == user.id, Transaction.decision == Decision.APPROVED.value)
    count, mean = approved.with_entities(func.count(Transaction.id), func.avg(Transaction.amount)).one()
    hours = [h for (h,) in approved.with_entities(Transaction.local_hour).filter(Transaction.local_hour.isnot(None))]
    mine = db.query(Transaction).filter(Transaction.user_id == user.id)
    recent = mine.filter(Transaction.created_at >= now - timedelta(minutes=cfg.velocity_window_minutes)).count()
    day = mine.filter(Transaction.created_at >= now - timedelta(hours=24)).with_entities(func.sum(Transaction.amount)).scalar() or 0.0
    last = mine.with_entities(func.max(Transaction.created_at)).scalar()
    changed = (db.query(func.max(Event.created_at))
               .filter(Event.user_id == user.id, Event.kind == "biometrics_changed").scalar())

    def hours_ago(dt):
        return None if dt is None else (now - _aware(dt)).total_seconds() / 3600

    return RiskInput(
        amount=data["amount"], transaction_type=data["transaction_type"],
        recipient_is_new=data["recipient_is_new"], is_international=data["is_international"],
        new_device=data["new_device"], history_count=count or 0, history_mean_amount=float(mean or 0),
        local_hour=data.get("local_hour"), recent_count=recent, amount_24h=float(day),
        account_age_hours=hours_ago(user.created_at), hours_since_last_txn=hours_ago(last),
        typical_hour=typical_hour(hours) if len(hours) >= cfg.usual_hour_min_history else None,
        biometric_changed_hours_ago=hours_ago(changed))


def create_transaction(db: Session, user: User, data: dict, risk_cfg: RiskConfig) -> Transaction:
    risk = assess_risk(build_risk_input(db, user, data, risk_cfg), risk_cfg)
    txn = Transaction(risk_score=risk.score, risk_category=risk.category.value,
                      risk_factors=risk.to_dict()["factors"], decision="pending", **data)
    # A recently recovered account (biometrics wiped and re-enrolled) cannot move high-value money yet.
    # That gives the real owner time to notice if the recovery was not theirs.
    if (user.probation_until and _aware(user.probation_until) > utcnow()
            and risk.category.value in ("high", "critical")):
        txn.decision = Decision.REJECTED.value
        txn.decided_at = datetime.now(timezone.utc)
        txn.decision_reason = (f"This account's biometrics were recently reset, so {risk.category.value}-risk transactions "
                               f"are disabled until {_aware(user.probation_until):%Y-%m-%d %H:%M} UTC. Smaller transactions still work.")
    db.add(txn)
    db.commit()
    log_event(db, "transaction_created", user.id, txn.id, amount=txn.amount, risk=risk.category.value)
    return txn


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


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class LiveInput:
    """Liveness material that came with the request."""
    challenge: Challenge | None            # None if the id was missing, unknown, expired or someone else's
    challenge_sent: bool                   # did the client send a challenge id at all
    face_frames: list[bytes]


def liveness_required(txn: Transaction, settings: Settings) -> bool:
    return (settings.liveness_required_from != "never"
            and RISK_ORDER[txn.risk_category] >= RISK_ORDER[settings.liveness_required_from])


def _liveness_fail(module, name: str, code: str, reason: str, details: dict | None = None) -> ModalityResult:
    r = ModalityResult.not_evaluated(name, module.method, code, reason)
    r.details = {"liveness": {"passed": False, **(details or {})}}
    return r


def evaluate_modality(db: Session, store: TemplateStore, user_id: int, module, name: str, sample: bytes | None,
                      live: LiveInput, liveness, need_live: bool, what: str) -> tuple[ModalityResult, int]:
    """One modality, with liveness handled. Used by transaction authentication AND by biometric login so both
    apply exactly the same rules. Returns (result, number of liveness checks that FAILED).

    * A challenge was answered: judge it (face: head-turn frames, voice: spoken words) and verify identity on
      the frontal frame / the same audio.
    * No challenge but one is required: the modality is "not evaluated" (a still photo is not enough).
    * A checker that is missing or a challenge that is stale also yields "not evaluated". Nothing here can
      turn a failure into a match."""
    info = None
    if name == "face" and (live.face_frames or live.challenge_sent):
        if live.challenge is None:
            return _liveness_fail(module, name, "liveness_failed", "The liveness challenge is missing, expired or already used. Start again."), 1
        if liveness is None or liveness.face is None:
            return _liveness_fail(module, name, "liveness_unavailable", "Liveness checking is not available on this server."), 0
        if not live.face_frames:
            return _liveness_fail(module, name, "liveness_failed", "No frames of the head turn were sent."), 1
        lr = liveness.face.check(live.face_frames, live.challenge.direction)
        if not lr.ok:
            return _liveness_fail(module, name, "liveness_failed", lr.message, {"kind": "head_turn", "code": lr.code, **lr.details}), 1
        sample = live.face_frames[lr.frame_index]          # verify identity on the frontal frame
        info = {"passed": True, "kind": "head_turn", "direction": live.challenge.direction, **lr.details}
    elif name == "face" and sample is not None and need_live:
        return _liveness_fail(module, name, "liveness_required", f"{what} need a live head-turn challenge, not a still photo."), 0
    if name == "voice" and sample is not None and live.challenge_sent:
        if live.challenge is None:
            return _liveness_fail(module, name, "liveness_failed", "The liveness challenge is missing, expired or already used. Start again."), 1
        if liveness is None or liveness.spoken is None:
            return _liveness_fail(module, name, "liveness_unavailable", "Spoken-challenge checking is not available on this server."), 0
        sr = liveness.spoken.check(sample, live.challenge.phrase)
        if not sr.ok and sr.code == "asr_unavailable":     # a missing recognizer is not an attack and must not count as one
            return _liveness_fail(module, name, "liveness_unavailable", sr.message), 0
        if not sr.ok:
            return _liveness_fail(module, name, "liveness_failed", sr.message, {"kind": "spoken_phrase", "code": sr.code, **sr.details}), 1
        info = {"passed": True, "kind": "spoken_phrase", **sr.details}
    elif name == "voice" and sample is not None and need_live:
        return _liveness_fail(module, name, "liveness_required", f"{what} need a spoken challenge, not a free recording."), 0
    template = store.load(user_id, name) if sample is not None else None
    r = run_modality(module, name, template, sample, db, user_id)
    if info is not None:
        r.details = {**r.details, "liveness": info}
    return r, 0


def authenticate(db: Session, txn: Transaction, samples: dict[str, bytes | None], registry: BiometricRegistry,
                 store: TemplateStore, fusion_cfg: FusionConfig, settings: Settings, ctx=None,
                 live: LiveInput | None = None, liveness=None) -> AuthAttempt:
    if txn.decision in (Decision.APPROVED.value, Decision.REJECTED.value):
        raise ApiError(409, "transaction_closed", f"Transaction already {txn.decision}.")
    if len(txn.attempts) >= settings.max_auth_attempts:
        raise ApiError(409, "attempt_limit", "Maximum authentication attempts reached.")
    abuse.check_biometric_allowed(db, settings, txn.user_id, ctx)

    abuse.check_liveness_allowed(db, settings, txn.user_id, ctx)
    t0 = time.perf_counter()
    need_live = liveness_required(txn, settings)
    live = live or LiveInput(None, False, [])
    results, live_failed = [], 0
    for name in ORDER:
        r, failed = evaluate_modality(db, store, txn.user_id, registry.get(name), name, samples.get(name), live,
                                      liveness, need_live, f"{txn.risk_category}-risk transactions")
        results.append(r)
        live_failed += failed
    if live_failed:
        log_event(db, "liveness_failure", txn.user_id, txn.id, ctx=ctx, failed=live_failed)

    fixed = fixed_threshold_fusion(results, txn.risk_category, fusion_cfg)
    aware = risk_aware_fusion(results, txn.risk_category, fusion_cfg)
    active = {"fixed": fixed, "risk_aware": aware}[settings.active_policy]
    decision, explanation = active.decision, active.explanation

    # A liveness check that FAILED (as opposed to one that could not run) looks like a presentation attack.
    # Other modalities must not carry the transaction through on the same attempt.
    if live_failed and decision == Decision.APPROVED:
        decision = Decision.ADDITIONAL
        explanation += (" A liveness check failed on this attempt, so it cannot be approved even though other "
                        "evidence matched. Try again with a fresh challenge.")

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
        log_event(db, "biometric_failure", txn.user_id, txn.id, ctx=ctx, via="authenticate")
    log_event(db, "authentication", txn.user_id, txn.id, decision=decision.value, policy=settings.active_policy,
              fused=active.fused_score, attempt=attempt_no)
    return attempt
