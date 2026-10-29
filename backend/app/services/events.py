from sqlalchemy.orm import Session

from ..models import Event


def log_event(db: Session, kind: str, user_id: int | None = None, transaction_id: int | None = None,
              ctx=None, trusted: bool | None = None, **detail) -> Event:
    """Append to the audit log. `ctx` (a ClientCtx) adds hashed device/network identifiers so lockouts
    can be scoped to whoever caused them."""
    ev = Event(kind=kind, user_id=user_id, transaction_id=transaction_id, detail=detail, trusted=trusted,
               device_hash=getattr(ctx, "device_hash", None), ip_hash=getattr(ctx, "ip_hash", None))
    db.add(ev)
    db.commit()
    return ev
