"""Data deletion and retention."""
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import AuthAttempt, Enrollment, Event, Session as Sess, Transaction, User, utcnow
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
