"""Passwords, sessions and access-control dependencies.

Passwords: scrypt (stdlib hashlib) with a random 16-byte salt, stored as one string. Sessions:
random 256-bit bearer tokens; the database keeps only their SHA-256, so a leaked database
cannot be replayed as logins. Tokens expire and can be revoked.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session as DbSession

from .deps import get_db
from .errors import ApiError
from .models import Session, User, utcnow

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b = lambda x: base64.b64encode(x).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b(salt)}${b(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Unknown/empty hashes still burn the same work."""
    try:
        _, n, r, p, salt, dk = (stored or "").split("$")
        expected = base64.b64decode(dk)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        hashlib.scrypt(password.encode(), salt=b"x" * 16, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: DbSession, user: User, hours: float, scope: str = "full") -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    exp = utcnow() + timedelta(hours=hours)
    db.add(Session(token_hash=_digest(token), user_id=user.id, expires_at=exp, scope=scope))
    db.commit()
    return token, exp


def revoke_all(db: DbSession, user_id: int) -> None:
    db.query(Session).filter_by(user_id=user_id, revoked=False).update({"revoked": True})
    db.commit()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _resolve(request: Request, db: DbSession, scopes: set[str]) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "not_authenticated", "Sign in first.")
    sess = db.query(Session).filter_by(token_hash=_digest(token.strip())).one_or_none()
    if sess is None or sess.revoked or _aware(sess.expires_at) < utcnow():
        raise ApiError(401, "session_invalid", "Your session is missing or expired. Sign in again.")
    if sess.scope not in scopes:
        if sess.scope == "preauth":
            raise ApiError(401, "biometric_login_required", "Finish signing in with your face and voice.")
        raise ApiError(403, "enrollment_incomplete", "Enroll your face and voice first. Until then only the enrollment pages are available.")
    user = db.get(User, sess.user_id)
    if user is None:
        raise ApiError(401, "session_invalid", "Account no longer exists.")
    request.state.token_hash, request.state.session_id, request.state.session_scope = sess.token_hash, sess.id, sess.scope
    return user


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    """A fully signed-in user. Limited and half-finished sessions are refused."""
    return _resolve(request, db, {"full"})


def current_user_any(request: Request, db: DbSession = Depends(get_db)) -> User:
    """Full or limited session (an account that still has to enroll face and voice)."""
    return _resolve(request, db, {"full", "limited"})


def current_user_for_recovery(request: Request, db: DbSession = Depends(get_db)) -> User:
    """Recovery requests must work for someone who cannot pass the biometric step of signing in, so the
    'password accepted, biometrics pending' session is allowed here. Each action still asks for the password."""
    return _resolve(request, db, {"full", "limited", "preauth"})


def preauth_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    """Only the 'password accepted, biometrics pending' session."""
    return _resolve(request, db, {"preauth"})


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Administrator access required.")
    return user


def owner_or_admin(user: User, target_id: int) -> None:
    if user.role != "admin" and user.id != target_id:
        # 404 rather than 403 so ids of other accounts are not confirmed to exist
        raise ApiError(404, "user_not_found", f"User {target_id} does not exist.")


def owner_only(user: User, target_id: int) -> None:
    if user.id != target_id:
        if user.role == "admin":
            raise ApiError(403, "owner_only", "Only the account owner can do this. Administrators have read-only access.")
        raise ApiError(404, "user_not_found", f"User {target_id} does not exist.")
