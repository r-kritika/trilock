"""Lockouts and rate limits, scoped to who is failing.

The first version locked the whole account after 5 failures, which lets anyone who knows an email
lock the real owner out. Here a failure is attributed to a source: a device (a random id the browser
keeps, sent as X-Device-Id; only its hash is stored) and a network address (hashed). Rules:

* The owner's known device (it has signed in successfully before) has its own, higher allowance and is
  never affected by other people's failures.
* An unknown source is blocked after a few failures against one account, or after many failures across
  accounts from one network address.
* If many unknown sources hammer one account, all unknown sources are blocked, but established devices
  (older than established_device_hours) keep working.
* A device identifier is free to invent, so new devices are limited per account per day, and a freshly
  made device does not count as established.

A source that is blocked gets a 429. Nothing here is a security boundary against a determined attacker
with many addresses; it removes the cheap denial-of-service against the owner and slows guessing.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ApiError
from ..models import Device, Event, User, utcnow

_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@dataclass(frozen=True)
class ClientCtx:
    device_hash: str | None
    ip_hash: str


def _h(value: str, n: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:n]


def client_ctx(request: Request) -> ClientCtx:
    settings: Settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            ip = fwd.split(",")[0].strip() or ip
    dev = request.headers.get("x-device-id", "")
    return ClientCtx(device_hash=_h(dev, 32) if _DEVICE_RE.match(dev) else None, ip_hash=_h(ip, 16))


def _since(minutes: int):
    return utcnow() - timedelta(minutes=minutes)


def _count(db: Session, kind: str, since, *filters) -> int:
    return db.query(func.count(Event.id)).filter(Event.kind == kind, Event.created_at >= since, *filters).scalar()


def known_device(db: Session, user_id: int, ctx: ClientCtx) -> Device | None:
    if not ctx.device_hash:
        return None
    return db.query(Device).filter_by(user_id=user_id, device_hash=ctx.device_hash).one_or_none()


def is_established(db: Session, user_id: int, ctx: ClientCtx, settings: Settings) -> bool:
    d = known_device(db, user_id, ctx)
    if d is None:
        return False
    created = d.created_at if d.created_at.tzinfo else d.created_at.replace(tzinfo=utcnow().tzinfo)
    return created <= utcnow() - timedelta(hours=settings.established_device_hours)


def _same_source(ctx: ClientCtx):
    """SQL filter: events from this device OR this network address."""
    from sqlalchemy import or_
    conds = [Event.ip_hash == ctx.ip_hash]
    if ctx.device_hash:
        conds.append(Event.device_hash == ctx.device_hash)
    return or_(*conds)


# ---------------------------------------------------------------- login
def check_login_allowed(db: Session, settings: Settings, user: User | None, ctx: ClientCtx) -> None:
    since = _since(settings.login_lock_minutes)
    blocked = ApiError(429, "too_many_attempts", "Too many failed sign-ins from here. Try again later.")
    # one network address hammering many accounts
    if _count(db, "login_failed", since, Event.ip_hash == ctx.ip_hash) >= settings.ip_failed_logins:
        raise blocked
    if user is None:
        return
    if known_device(db, user.id, ctx):
        # the owner's own browser: only their own typos count against it
        n = _count(db, "login_failed", since, Event.user_id == user.id, Event.device_hash == ctx.device_hash)
        if n >= settings.trusted_device_failed_logins:
            raise blocked
        return
    n = _count(db, "login_failed", since, Event.user_id == user.id, _same_source(ctx))
    if n >= settings.max_failed_logins:
        raise blocked
    # many different unknown sources against this account: block unknown sources, never known devices
    total = _count(db, "login_failed", since, Event.user_id == user.id, Event.trusted.is_(False))
    if total >= settings.account_untrusted_failed_logins:
        raise blocked


def record_login_failure(db: Session, user: User | None, ctx: ClientCtx) -> None:
    from .events import log_event
    trusted = bool(user and known_device(db, user.id, ctx))
    log_event(db, "login_failed", user.id if user else None, ctx=ctx, trusted=trusted)


def register_device(db: Session, settings: Settings, user: User, ctx: ClientCtx) -> None:
    """Call only after the password was correct."""
    if not ctx.device_hash:
        return
    d = known_device(db, user.id, ctx)
    if d:
        d.last_seen = utcnow()
        db.commit()
        return
    day_ago = utcnow() - timedelta(hours=24)
    new_today = db.query(func.count(Device.id)).filter(Device.user_id == user.id, Device.created_at >= day_ago).scalar()
    if new_today >= settings.max_new_devices_per_day:
        raise ApiError(429, "too_many_new_devices", "Too many new devices signed in to this account today. Try again tomorrow.")
    db.add(Device(user_id=user.id, device_hash=ctx.device_hash))
    db.commit()


# ---------------------------------------------------------------- biometric attempts
def check_biometric_allowed(db: Session, settings: Settings, user_id: int, ctx: ClientCtx) -> None:
    since = _since(settings.biometric_window_minutes)
    blocked = ApiError(429, "too_many_failures",
                       f"Too many failed biometric attempts from this device. Try again in {settings.biometric_window_minutes} minutes.")
    mine = _count(db, "biometric_failure", since, Event.user_id == user_id, _same_source(ctx))
    if mine >= settings.biometric_failure_limit:
        raise blocked
    total = _count(db, "biometric_failure", since, Event.user_id == user_id)
    if total >= settings.biometric_user_failure_limit and not is_established(db, user_id, ctx, settings):
        raise blocked


def check_liveness_allowed(db: Session, settings: Settings, user_id: int, ctx: ClientCtx) -> None:
    """Failed liveness challenges have their own, looser limit: a bad webcam or a clumsy head turn is
    common, and should not use up the biometric-failure allowance."""
    since = _since(settings.biometric_window_minutes)
    if _count(db, "liveness_failure", since, Event.user_id == user_id, _same_source(ctx)) >= settings.liveness_failure_limit:
        raise ApiError(429, "too_many_failures", "Too many failed liveness challenges from this device. Try again later.")
