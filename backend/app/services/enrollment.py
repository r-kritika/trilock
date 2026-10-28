from sqlalchemy.orm import Session

from ..biometrics.registry import BiometricRegistry
from ..biometrics.types import BiometricInputError, ModelUnavailableError
from ..errors import ApiError
from ..models import Enrollment, User
from .events import log_event
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
    return row
