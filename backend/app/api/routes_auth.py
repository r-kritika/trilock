import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import get_db
from ..errors import ApiError
from ..models import User, utcnow
from ..schemas import UserCreate
from ..security import (_aware, create_session, current_user, hash_password, revoke_all, verify_password)
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
    return {**UserOut.model_validate(u).model_dump(), "role": u.role,
            "enrollments": enr.enrollment_status(db, u, request.app.state.registry)}


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


@router.post("/login")
def login(body: Login, request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    u = db.query(User).filter_by(email=body.email.lower()).one_or_none()
    if u and u.locked_until and _aware(u.locked_until) > utcnow():
        verify_password(body.password, u.password_hash)   # keep timing similar
        raise ApiError(429, "account_locked", "Too many failed sign-ins. Try again later.")
    ok = verify_password(body.password, u.password_hash if u else None)
    if not u or not ok:
        if u:
            u.failed_logins = (u.failed_logins or 0) + 1
            if u.failed_logins >= s.max_failed_logins:
                u.locked_until = utcnow() + timedelta(minutes=s.login_lock_minutes)
                u.failed_logins = 0
                log_event(db, "login_locked", u.id)
            db.commit()
            log_event(db, "login_failed", u.id)
        # same answer for unknown email and wrong password
        raise ApiError(401, "bad_credentials", "Email or password is incorrect.")
    u.failed_logins, u.locked_until = 0, None
    db.commit()
    token, exp = create_session(db, u, s.session_hours)
    log_event(db, "login", u.id)
    return {"token": token, "expires_at": exp, "user": _detail(db, request, u)}


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..models import Session as Sess
    db.query(Sess).filter_by(token_hash=request.state.token_hash).update({"revoked": True})
    db.commit()


@router.get("/me", response_model=UserDetail)
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, request, user)
