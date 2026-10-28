from sqlalchemy.orm import Session

from ..models import Event


def log_event(db: Session, kind: str, user_id: int | None = None, transaction_id: int | None = None,
              **detail) -> Event:
    ev = Event(kind=kind, user_id=user_id, transaction_id=transaction_id, detail=detail)
    db.add(ev)
    db.commit()
    return ev
