import secrets
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import get_db, read_upload
from ..errors import ApiError
from ..models import Session, User
from ..schemas import UserCreate
from ..security import create_session, current_user_any, hash_password, preauth_user, verify_password
from ..services import abuse
from ..services import authentication as auth
from ..services import login as login_svc
from ..services import enrollment as enr
from ..services.events import log_event
from ..schemas import UserDetail, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


class Register(UserCreate):
    password: str = Field(min_length=1, max_length=200)


class Login(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


def _detail(db, request, u):
    from .routes_users import _detail as base
    return base(db, request, u)


@router.post("/register", status_code=201)
def register(body: Register, request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    if not s.allow_registration:
        raise ApiError(403, "registration_closed", "Self-registration is disabled.")
    email = body.email.lower()
    if len(body.password) < s.min_password_length:
        raise ApiError(422, "weak_password", f"Password must be at least {s.min_password_length} characters.")
    if body.password.lower() in (email, email.split("@")[0], body.full_name.lower()):
        raise ApiError(422, "weak_password", "Password must not be your name or email.")
    if db.query(User).filter_by(email=email).first():
        raise ApiError(409, "email_taken", "A user with this email already exists.")
    u = User(full_name=body.full_name, email=email, account_number="TL" + secrets.token_hex(5).upper(),
             password_hash=hash_password(body.password), role="user")
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "conflict", "Could not create the account (duplicate).")
    log_event(db, "user_created", u.id)
    return _detail(db, request, u)


def _full_login(db, request, s, u, ctx) -> dict:
    abuse.register_device(db, s, u, ctx)
    token, exp = create_session(db, u, s.session_hours, "full")
    log_event(db, "login", u.id, ctx=ctx)
    return {"status": "ok", "token": token, "expires_at": exp, "user": _detail(db, request, u)}


@router.post("/login")
def login(body: Login, request: Request, db: Session = Depends(get_db)):
    st = request.app.state
    s = st.settings
    ctx = abuse.client_ctx(request)
    u = db.query(User).filter_by(email=body.email.lower()).one_or_none()
    abuse.check_login_allowed(db, s, u, ctx)               # scoped to this source, not the whole account
    ok = verify_password(body.password, u.password_hash if u else None)
    if not u or not ok:
        abuse.record_login_failure(db, u, ctx)
        # same answer for unknown email and wrong password
        raise ApiError(401, "bad_credentials", "Email or password is incorrect.")
    if login_svc.needs_biometric_login(db, u, s):
        # password accepted; the face and voice step comes next. This token opens nothing else.
        token, _ = create_session(db, u, s.preauth_minutes / 60, "preauth")
        ch = st.challenges.issue(u.id)
        log_event(db, "login_password_ok", u.id, ctx=ctx)
        return {"status": "biometric_required", "preauth_token": token, "expires_in": s.preauth_minutes * 60,
                "liveness_required": s.login_liveness, "name": u.full_name,
                "challenge": login_svc.challenge_payload(ch, s, st.liveness)}
    if login_svc.needs_enrollment(db, u, s):
        abuse.register_device(db, s, u, ctx)
        token, exp = create_session(db, u, s.session_hours, "limited")
        log_event(db, "login_limited", u.id, ctx=ctx, missing=login_svc.missing_core(db, u.id))
        return {"status": "enrollment_required", "token": token, "expires_at": exp, "missing": login_svc.missing_core(db, u.id),
                "user": _detail(db, request, u)}
    return _full_login(db, request, s, u, ctx)


@router.post("/login/challenge")
def login_challenge(request: Request, u: User = Depends(preauth_user)):
    """A fresh challenge for the biometric step (each attempt uses one up)."""
    st = request.app.state
    return login_svc.challenge_payload(st.challenges.issue(u.id), st.settings, st.liveness)


@router.post("/login/biometric")
async def login_biometric(request: Request, challenge_id: str | None = Form(None),
                          face_frames: list[UploadFile] = File(default_factory=list),
                          voice: UploadFile | None = File(None), u: User = Depends(preauth_user),
                          db: Session = Depends(get_db)):
    """Second step of sign-in: live face and voice. Both must pass liveness AND match the enrolled references."""
    st = request.app.state
    s = st.settings
    ctx = abuse.client_ctx(request)
    sess = db.query(Session).filter_by(id=request.state.session_id).one()
    if sess.attempts >= s.preauth_max_attempts:
        sess.revoked = True
        db.commit()
        raise ApiError(401, "start_over", "Too many tries for this sign-in. Enter your password again.")
    abuse.check_biometric_allowed(db, s, u.id, ctx)
    abuse.check_liveness_allowed(db, s, u.id, ctx)
    sess.attempts += 1
    db.commit()

    frames = [d for d in [await read_upload(f, s.max_image_bytes) for f in face_frames] if d is not None]
    voice_bytes = await read_upload(voice, s.max_audio_bytes)
    if s.login_liveness:
        live = auth.LiveInput(challenge=st.challenges.consume(challenge_id, u.id), challenge_sent=True, face_frames=frames)
        samples = {"face": None, "voice": voice_bytes}
    else:                                       # liveness switched off: one photo and one recording are judged on identity only
        live = auth.LiveInput(None, False, [])
        samples = {"face": frames[0] if frames else None, "voice": voice_bytes}
    results, live_failed = [], 0
    for name in login_svc.CORE:
        r, failed = auth.evaluate_modality(db, st.templates, u.id, st.registry.get(name), name, samples[name], live, st.liveness,
                                           s.login_liveness, "Signing in")
        results.append(r)
        live_failed += failed
    if live_failed:
        log_event(db, "liveness_failure", u.id, ctx=ctx, failed=live_failed, via="login")
    if all(r.status.value == "match" for r in results):
        sess.revoked = True
        db.commit()
        return _full_login(db, request, s, u, ctx)

    if any(r.status.value == "no_match" for r in results):
        log_event(db, "biometric_failure", u.id, ctx=ctx, via="login")
    log_event(db, "login_biometric_failed", u.id, ctx=ctx, results={r.modality: r.status.value for r in results})
    left = s.preauth_max_attempts - sess.attempts
    raise ApiError(401, "biometric_login_failed", "Your face and voice could not both be confirmed.",
                   {"attempts_left": left, "modalities": [
                       {"modality": r.modality, "status": r.status.value, "reason_code": r.reason_code,
                        "reason": r.reason or ("Does not match the enrolled reference." if r.status.value == "no_match" else None)}
                       for r in results]})


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user_any), db: Session = Depends(get_db)):
    from ..models import Session as Sess
    db.query(Sess).filter_by(token_hash=request.state.token_hash).update({"revoked": True})
    db.commit()


@router.get("/me", response_model=UserDetail)
def me(request: Request, user: User = Depends(current_user_any), db: Session = Depends(get_db)):
    return {**_detail(db, request, user), "session_scope": request.state.session_scope}
