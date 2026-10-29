"""Data deletion and retention."""
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import AuthAttempt, Device, Enrollment, Event, RecoveryRequest, Session as Sess, Transaction, User, utcnow
from .templates import TemplateStore


def erase_user(db: Session, store: TemplateStore, user: User) -> None:
    """Remove everything tied to an account, including the encrypted template files."""
    uid = user.id
    for m in ("face", "fingerprint", "voice"):
        store.delete(uid, m)
    db.query(Event).filter_by(user_id=uid).delete()
    for t in db.query(Transaction).filter_by(user_id=uid):
        db.delete(t)               # cascades to attempts
    db.query(Sess).filter_by(user_id=uid).delete()
    db.query(Device).filter_by(user_id=uid).delete()
    db.query(RecoveryRequest).filter_by(user_id=uid).delete()
    db.query(Enrollment).filter_by(user_id=uid).delete()
    db.delete(user)
    db.commit()


def purge_old(db: Session, days: int) -> dict:
    """Retention: delete events and authentication attempts older than `days`.
    Transactions stay (they carry no biometric data) but lose their attempt detail."""
    cutoff = utcnow() - timedelta(days=days)
    ev = db.query(Event).filter(Event.created_at < cutoff).delete()
    at = db.query(AuthAttempt).filter(AuthAttempt.created_at < cutoff).delete()
    ss = db.query(Sess).filter((Sess.expires_at < utcnow()) | (Sess.revoked == True)).delete()  # noqa: E712
    db.commit()
    return {"events": ev, "attempts": at, "sessions": ss}


def reset_biometrics(db: Session, store: TemplateStore, user: User, by_admin_id: int, probation_hours: int) -> int:
    """Delete every biometric reference of a user and start a probation period. Cannot add any reference.
    Only called when an administrator approves a recovery request (see routes_recovery)."""
    from datetime import timedelta
    from .events import log_event
    rows = db.query(Enrollment).filter_by(user_id=user.id).all()
    for r in rows:
        store.delete(user.id, r.modality)
        db.delete(r)
    user.probation_until = utcnow() + timedelta(hours=probation_hours)
    db.commit()
    log_event(db, "biometrics_reset_by_admin", user.id, admin_id=by_admin_id, modalities=[r.modality for r in rows],
              probation_until=user.probation_until.isoformat())
    return len(rows)
