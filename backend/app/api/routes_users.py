from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from ..deps import get_db, read_upload
from ..errors import ApiError
from ..models import Enrollment, User
from ..schemas import EnrollmentStatus, UserDetail, UserOut
from ..security import admin_user, current_user, owner_only, owner_or_admin, verify_password
from ..services import enrollment as enr
from ..services.events import log_event
from ..services.privacy import erase_user

router = APIRouter(prefix="/users", tags=["users"])


def _user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise ApiError(404, "user_not_found", f"User {user_id} does not exist.")
    return u


def _detail(db: Session, request: Request, u: User) -> dict:
    return {**UserOut.model_validate(u).model_dump(),
            "enrollments": enr.enrollment_status(db, u, request.app.state.registry)}


def _check_password(user: User, password: str | None, db: Session) -> None:
    """Changing biometric references needs the password again (step-up), so a stolen session
    token alone cannot swap in an attacker's face or voice."""
    if not password or not verify_password(password, user.password_hash):
        log_event(db, "stepup_failed", user.id)
        raise ApiError(403, "password_required", "Enter your account password to change biometric enrollment.")


@router.get("", response_model=list[UserDetail])
def list_users(request: Request, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    return [_detail(db, request, u) for u in db.query(User).order_by(User.id)]


@router.get("/{user_id}", response_model=UserDetail)
def get_user(user_id: int, request: Request, me: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_or_admin(me, user_id)
    return _detail(db, request, _user(db, user_id))


@router.get("/{user_id}/enrollments", response_model=list[EnrollmentStatus])
def get_enrollments(user_id: int, request: Request, me: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_or_admin(me, user_id)
    return enr.enrollment_status(db, _user(db, user_id), request.app.state.registry)


@router.post("/{user_id}/enrollments/{modality}", response_model=list[EnrollmentStatus])
async def enroll(user_id: int, modality: str, request: Request, files: list[UploadFile] = File(...),
                 password: str = Form(None), me: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_only(me, user_id)
    _check_password(me, password, db)
    s = request.app.state
    limit = s.settings.max_audio_bytes if modality == "voice" else s.settings.max_image_bytes
    samples = [d for d in [await read_upload(f, limit) for f in files] if d is not None]
    enr.enroll(db, s.templates, s.registry, me, modality, samples)
    return enr.enrollment_status(db, me, s.registry)


@router.delete("/{user_id}/enrollments/{modality}", response_model=list[EnrollmentStatus])
def delete_enrollment(user_id: int, modality: str, request: Request, password: str = Form(None),
                      me: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_only(me, user_id)
    _check_password(me, password, db)
    s = request.app.state
    row = db.query(Enrollment).filter_by(user_id=user_id, modality=modality).one_or_none()
    if row is None:
        raise ApiError(404, "not_enrolled", "Nothing enrolled for this modality.")
    db.delete(row)
    db.commit()
    s.templates.delete(user_id, modality)
    log_event(db, "enrollment_deleted", user_id, modality=modality)
    return enr.enrollment_status(db, me, s.registry)


@router.delete("/{user_id}", status_code=204)
def delete_account(user_id: int, request: Request, password: str = Form(None),
                   me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Erase an account: templates, enrollments, sessions, transactions, attempts and events."""
    owner_only(me, user_id)
    _check_password(me, password, db)
    erase_user(db, request.app.state.templates, me)
