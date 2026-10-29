"""Recovery for users who cannot provide their enrolled biometrics (new face, broken microphone).

There is deliberately no path where one administrator can wipe someone's biometrics on a whim:

1. The signed-in owner files a request with their password.
2. The request is visible to the owner (banner at sign-in) and can be cancelled by them while pending.
3. An administrator can approve only after a cooling-off period, and should check with the owner by
   another channel first (this project has no mail service, so that step is manual).
4. Approval deletes the references (it cannot add any) and starts a probation period in which high and
   critical transactions are disabled, whoever re-enrolls next.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from ..deps import get_db
from ..errors import ApiError
from ..models import Enrollment, RecoveryRequest, User, utcnow
from ..security import admin_user, current_user_for_recovery, verify_password
from ..services import abuse
from ..services.events import log_event
from ..services.privacy import reset_biometrics

router = APIRouter(prefix="/recovery", tags=["recovery"])


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def out(r: RecoveryRequest, user: User | None = None) -> dict:
    d = {"id": r.id, "user_id": r.user_id, "status": r.status, "reason": r.reason, "created_at": r.created_at,
         "earliest_at": r.earliest_at, "decided_at": r.decided_at, "note": r.note,
         "can_approve": r.status == "pending" and _aware(r.earliest_at) <= utcnow()}
    if user is not None:
        d["user_name"], d["user_email"] = user.full_name, user.email
    return d


def _password(user: User, password: str | None, db: Session) -> None:
    if not password or not verify_password(password, user.password_hash):
        log_event(db, "stepup_failed", user.id)
        raise ApiError(403, "password_required", "Enter your account password.")


@router.post("", status_code=201)
def request_recovery(request: Request, reason: str = Form(..., min_length=3, max_length=300), password: str = Form(None),
                     me: User = Depends(current_user_for_recovery), db: Session = Depends(get_db)):
    s = request.app.state.settings
    if me.role == "admin":
        raise ApiError(403, "forbidden", "Administrator accounts have no biometrics.")
    _password(me, password, db)
    if not db.query(Enrollment).filter_by(user_id=me.id).count():
        raise ApiError(409, "nothing_to_recover", "This account has no enrolled biometrics. Just enroll with your password.")
    if db.query(RecoveryRequest).filter_by(user_id=me.id, status="pending").count():
        raise ApiError(409, "already_pending", "A recovery request is already waiting.")
    r = RecoveryRequest(user_id=me.id, reason=reason.strip(), earliest_at=utcnow() + timedelta(hours=s.recovery_cooling_hours),
                        device_hash=abuse.client_ctx(request).device_hash)
    db.add(r)
    db.commit()
    log_event(db, "recovery_requested", me.id, ctx=abuse.client_ctx(request))
    return out(r)


@router.get("/mine")
def my_requests(me: User = Depends(current_user_for_recovery), db: Session = Depends(get_db)):
    rows = db.query(RecoveryRequest).filter_by(user_id=me.id).order_by(RecoveryRequest.id.desc()).limit(10).all()
    return [out(r) for r in rows]


@router.post("/{rid}/cancel")
def cancel(rid: int, password: str = Form(None), me: User = Depends(current_user_for_recovery), db: Session = Depends(get_db)):
    r = db.get(RecoveryRequest, rid)
    if r is None or r.user_id != me.id:
        raise ApiError(404, "not_found", "No such recovery request.")
    _password(me, password, db)
    if r.status != "pending":
        raise ApiError(409, "not_pending", f"Request is already {r.status}.")
    r.status, r.decided_at = "cancelled", utcnow()
    db.commit()
    log_event(db, "recovery_cancelled", me.id)
    return out(r)


@router.get("")
def list_requests(status: str | None = None, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = db.query(RecoveryRequest)
    if status:
        q = q.filter_by(status=status)
    return [out(r, db.get(User, r.user_id)) for r in q.order_by(RecoveryRequest.id.desc()).limit(100)]


@router.post("/{rid}/approve")
def approve(rid: int, request: Request, note: str = Form(None, max_length=300), admin: User = Depends(admin_user),
            db: Session = Depends(get_db)):
    s = request.app.state
    r = db.get(RecoveryRequest, rid)
    if r is None:
        raise ApiError(404, "not_found", "No such recovery request.")
    if r.status != "pending":
        raise ApiError(409, "not_pending", f"Request is already {r.status}.")
    if _aware(r.earliest_at) > utcnow():
        raise ApiError(409, "cooling_off", f"Too early. This request can be approved after {_aware(r.earliest_at):%Y-%m-%d %H:%M} UTC.")
    user = db.get(User, r.user_id)
    reset_biometrics(db, s.templates, user, admin.id, s.settings.probation_hours)
    r.status, r.decided_at, r.decided_by, r.note = "approved", utcnow(), admin.id, note
    db.commit()
    return out(r, user)


@router.post("/{rid}/deny")
def deny(rid: int, note: str = Form(None, max_length=300), admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    r = db.get(RecoveryRequest, rid)
    if r is None:
        raise ApiError(404, "not_found", "No such recovery request.")
    if r.status != "pending":
        raise ApiError(409, "not_pending", f"Request is already {r.status}.")
    r.status, r.decided_at, r.decided_by, r.note = "denied", utcnow(), admin.id, note
    db.commit()
    log_event(db, "recovery_denied", r.user_id, admin_id=admin.id)
    return out(r, db.get(User, r.user_id))
