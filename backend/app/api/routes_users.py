from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from ..deps import get_db, read_upload
from ..errors import ApiError
from ..models import Enrollment, User
from ..schemas import EnrollmentStatus, UserDetail, UserOut
from ..security import admin_user, current_user, current_user_any, owner_only, owner_or_admin, verify_password
from ..services import abuse
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
    from ..api.routes_recovery import out as recovery_out
    from ..models import RecoveryRequest
    rec = db.query(RecoveryRequest).filter_by(user_id=u.id).order_by(RecoveryRequest.id.desc()).limit(3).all()
    return {**UserOut.model_validate(u).model_dump(), "probation_until": u.probation_until,
            "enrollments": enr.enrollment_status(db, u, request.app.state.registry),
            "recovery": [recovery_out(r) for r in rec if r.status in ("pending", "approved")]}


def _check_password(user: User, password: str | None, db: Session) -> None:
    if not password or not verify_password(password, user.password_hash):
        log_event(db, "stepup_failed", user.id)
        raise ApiError(403, "password_required", "Enter your account password to change biometric enrollment.")


async def _stepup(request: Request, db: Session, user: User, password: str | None,
                  face: UploadFile | None, fingerprint: UploadFile | None, voice: UploadFile | None) -> None:
    """Password first, then (if biometrics already exist) matching proof samples."""
    _check_password(user, password, db)
    s = request.app.state
    proofs = {"face": await read_upload(face, s.settings.max_image_bytes),
              "fingerprint": await read_upload(fingerprint, s.settings.max_image_bytes),
              "voice": await read_upload(voice, s.settings.max_audio_bytes)}
    enr.require_proof(db, s.templates, s.registry, user, proofs, s.settings, abuse.client_ctx(request))


def _upgrade_if_complete(db: Session, request: Request, user: User) -> None:
    """A limited session becomes a full one as soon as face and voice are both enrolled. Enrolling the second
    of the two needed proof of the first (see require_proof), so this never grants more than that proof did."""
    from ..models import Session as Sess
    from ..services import login as login_svc
    if getattr(request.state, "session_scope", None) == "limited" and not login_svc.missing_core(db, user.id):
        db.query(Sess).filter_by(id=request.state.session_id).update({"scope": "full"})
        db.commit()


@router.get("", response_model=list[UserDetail])
def list_users(request: Request, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    return [_detail(db, request, u) for u in db.query(User).order_by(User.id)]


@router.get("/{user_id}", response_model=UserDetail)
def get_user(user_id: int, request: Request, me: User = Depends(current_user_any), db: Session = Depends(get_db)):
    owner_or_admin(me, user_id)
    return _detail(db, request, _user(db, user_id))


@router.get("/{user_id}/enrollments", response_model=list[EnrollmentStatus])
def get_enrollments(user_id: int, request: Request, me: User = Depends(current_user_any), db: Session = Depends(get_db)):
    owner_or_admin(me, user_id)
    return enr.enrollment_status(db, _user(db, user_id), request.app.state.registry)


@router.post("/{user_id}/enrollments/{modality}", response_model=list[EnrollmentStatus])
async def enroll(user_id: int, modality: str, request: Request, files: list[UploadFile] = File(...),
                 password: str = Form(None), proof_face: UploadFile | None = File(None),
                 proof_fingerprint: UploadFile | None = File(None), proof_voice: UploadFile | None = File(None),
                 me: User = Depends(current_user_any), db: Session = Depends(get_db)):
    owner_only(me, user_id)
    await _stepup(request, db, me, password, proof_face, proof_fingerprint, proof_voice)
    s = request.app.state
    limit = s.settings.max_audio_bytes if modality == "voice" else s.settings.max_image_bytes
    samples = [d for d in [await read_upload(f, limit) for f in files] if d is not None]
    enr.enroll(db, s.templates, s.registry, me, modality, samples)
    _upgrade_if_complete(db, request, me)
    return enr.enrollment_status(db, me, s.registry)


@router.delete("/{user_id}/enrollments/{modality}", response_model=list[EnrollmentStatus])
async def delete_enrollment(user_id: int, modality: str, request: Request, password: str = Form(None),
                            proof_face: UploadFile | None = File(None), proof_fingerprint: UploadFile | None = File(None),
                            proof_voice: UploadFile | None = File(None),
                            me: User = Depends(current_user_any), db: Session = Depends(get_db)):
    owner_only(me, user_id)
    await _stepup(request, db, me, password, proof_face, proof_fingerprint, proof_voice)
    s = request.app.state
    row = db.query(Enrollment).filter_by(user_id=user_id, modality=modality).one_or_none()
    if row is None:
        raise ApiError(404, "not_enrolled", "Nothing enrolled for this modality.")
    db.delete(row)
    db.commit()
    s.templates.delete(user_id, modality)
    log_event(db, "enrollment_deleted", user_id, modality=modality)
    log_event(db, "biometrics_changed", user_id, modality=modality, change="removed")
    return enr.enrollment_status(db, me, s.registry)


@router.delete("/{user_id}", status_code=204)
async def delete_account(user_id: int, request: Request, password: str = Form(None),
                         proof_face: UploadFile | None = File(None), proof_fingerprint: UploadFile | None = File(None),
                         proof_voice: UploadFile | None = File(None),
                         me: User = Depends(current_user_any), db: Session = Depends(get_db)):
    """Erase an account: templates, enrollments, sessions, transactions, attempts and events."""
    owner_only(me, user_id)
    await _stepup(request, db, me, password, proof_face, proof_fingerprint, proof_voice)
    erase_user(db, request.app.state.templates, me)
