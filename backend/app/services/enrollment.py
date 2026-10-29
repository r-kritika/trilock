from sqlalchemy.orm import Session

from ..biometrics.registry import BiometricRegistry
from ..biometrics.types import BiometricInputError, ModelUnavailableError
from ..errors import ApiError
from ..config import Settings
from ..models import Enrollment, User
from .events import log_event
from . import abuse
from . import authentication as auth
from .templates import TemplateStore

MODALITIES = ("face", "fingerprint", "voice")


def enrollment_status(db: Session, user: User, registry: BiometricRegistry) -> list[dict]:
    """Per modality: enrolled / not_enrolled, and whether the module could even run right now."""
    rows = {e.modality: e for e in db.query(Enrollment).filter_by(user_id=user.id)}
    out = []
    statuses = registry.statuses()
    for m in MODALITIES:
        e = rows.get(m)
        out.append({
            "modality": m,
            "required": m in ("face", "voice"),
            "state": "enrolled" if e else "not_enrolled",
            "method": e.method if e else None,
            "sample_count": e.sample_count if e else 0,
            "quality": e.quality if e else None,
            "enrolled_at": e.created_at if e else None,
            "module_available": statuses[m]["available"],
            "module_detail": statuses[m]["detail"],
        })
    return out


def enroll(db: Session, store: TemplateStore, registry: BiometricRegistry, user: User,
           modality: str, samples: list[bytes]) -> Enrollment:
    if modality not in MODALITIES:
        raise ApiError(404, "unknown_modality", f"Unknown modality '{modality}'.")
    module = registry.get(modality)
    try:
        template, quality, n = module.enroll(samples)
    except BiometricInputError as e:
        log_event(db, "enrollment_rejected", user.id, modality=modality, code=e.code)
        raise ApiError(422, e.code, e.message)
    except ModelUnavailableError as e:
        log_event(db, "enrollment_failed", user.id, modality=modality, code=e.code)
        raise ApiError(503, e.code, e.message)
    replacing = db.query(Enrollment).filter_by(user_id=user.id, modality=modality).count() > 0
    fname = store.save(user.id, modality, template)
    row = db.query(Enrollment).filter_by(user_id=user.id, modality=modality).one_or_none()
    if row is None:
        row = Enrollment(user_id=user.id, modality=modality, method=module.method, sample_count=n,
                         quality=round(quality, 3), template_file=fname)
        db.add(row)
    else:
        row.method, row.sample_count, row.quality, row.template_file = module.method, n, round(quality, 3), fname
    db.commit()
    log_event(db, "enrolled", user.id, modality=modality, samples=n, quality=round(quality, 3))
    if replacing:   # adding another modality is normal onboarding; REPLACING a reference is the risk signal
        log_event(db, "biometrics_changed", user.id, modality=modality, change="replaced")
    return row


def require_proof(db: Session, store: TemplateStore, registry: BiometricRegistry, user: User,
                  proofs: dict[str, bytes | None], settings: Settings, ctx=None) -> None:
    """Step-up for changing biometrics. If the account already has enrolled modalities, the caller must
    present fresh samples that MATCH enough of them. A stolen password alone is not enough to replace the
    owner's references with an attacker's. A first enrollment on an empty account needs only the password.

    Failed proofs count toward the same lockout as failed authentication attempts."""
    enrolled = [e.modality for e in db.query(Enrollment).filter_by(user_id=user.id)]
    if not enrolled:
        return
    abuse.check_biometric_allowed(db, settings, user.id, ctx)
    needed = min(settings.enrollment_proof_modalities, len(enrolled))
    matched, mismatched = [], []
    for m in enrolled:
        sample = proofs.get(m)
        if sample is None:
            continue
        r = auth.run_modality(registry.get(m), m, store.load(user.id, m), sample, db, user.id)
        (matched if r.status.value == "match" else mismatched).append(m)
    if len(matched) >= needed:
        return
    if mismatched:
        log_event(db, "biometric_failure", user.id, ctx=ctx, via="enrollment_proof", modalities=mismatched)
    log_event(db, "enrollment_proof_failed", user.id, matched=matched, needed=needed)
    raise ApiError(403, "biometric_proof_required",
                   f"Changing biometrics needs a matching sample from {needed} of your enrolled modalities "
                   f"({', '.join(enrolled)}), plus your password. Matched: {len(matched)}.")
