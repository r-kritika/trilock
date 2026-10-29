"""Sign-in with password, then live face AND voice.

Rules
* Accounts that have BOTH face and voice enrolled: the password only opens a "preauth" session that can do nothing
  except answer a liveness challenge. The full session is issued only if the face and the voice both pass the
  liveness check (head turn, spoken words) and both match the enrolled references.
* Accounts missing face or voice get a "limited" session: just the enrollment pages, until both are enrolled.
* Administrators have no biometrics and sign in with the password only.
* Fingerprint plays no part in signing in. It is an optional extra.
Face and voice must both MATCH. There is no weighting that lets one make up for the other."""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from ..models import Enrollment, User

CORE = ("face", "voice")


def enrolled_modalities(db: DbSession, user_id: int) -> set[str]:
    return {e.modality for e in db.query(Enrollment).filter_by(user_id=user_id)}


def missing_core(db: DbSession, user_id: int) -> list[str]:
    have = enrolled_modalities(db, user_id)
    return [m for m in CORE if m not in have]


def challenge_payload(ch, settings, liveness) -> dict:
    return {"challenge_id": ch.id, "expires_in": settings.liveness_ttl_seconds,
            "face": {"direction": ch.direction, "instruction": f"Turn your head slowly to YOUR {ch.direction}, then hold."},
            "voice": {"phrase": ch.phrase, "instruction": f"Say these words: {' '.join(ch.phrase)}"},
            "required_from": settings.liveness_required_from, "services": liveness.status()}


def needs_biometric_login(db: DbSession, user: User, settings) -> bool:
    return settings.login_biometrics == "required" and user.role != "admin" and not missing_core(db, user.id)


def needs_enrollment(db: DbSession, user: User, settings) -> bool:
    return settings.login_biometrics == "required" and user.role != "admin" and bool(missing_core(db, user.id))
