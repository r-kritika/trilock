"""Shared types for all biometric modules."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum


class Modality(str, Enum):
    FACE = "face"
    FINGERPRINT = "fingerprint"
    VOICE = "voice"


class VerificationStatus(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    # The input could not be evaluated (bad image, model down, nothing enrolled...).
    # This is NOT a mismatch and must never be treated as a match.
    NOT_EVALUATED = "not_evaluated"


class BiometricInputError(Exception):
    """The submitted sample is unusable. `code` is stable and shown in the UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ModelUnavailableError(Exception):
    """A required model or native dependency is missing or failed to load."""

    def __init__(self, message: str, code: str = "model_unavailable"):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ModalityResult:
    modality: str
    status: VerificationStatus
    method: str
    raw_score: float | None = None          # native score of the model (cosine, inlier count)
    calibrated: float | None = None         # estimated match probability in [0, 1]
    quality: float | None = None            # input quality in [0, 1]
    threshold: float | None = None          # raw-score threshold where calibrated == 0.5
    reason_code: str | None = None
    reason: str | None = None
    latency_ms: float = 0.0
    calibration_source: str | None = None   # "default" or the file/dataset it was fitted on
    details: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """Can this result be used as evidence (for or against)?"""
        return self.status != VerificationStatus.NOT_EVALUATED and self.calibrated is not None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ModalityResult":
        d = dict(d)
        d["status"] = VerificationStatus(d["status"])
        return cls(**d)

    @classmethod
    def not_evaluated(cls, modality: str, method: str, code: str, reason: str, latency_ms: float = 0.0):
        return cls(modality=modality, status=VerificationStatus.NOT_EVALUATED, method=method,
                   reason_code=code, reason=reason, latency_ms=latency_ms)


@dataclass
class ModuleStatus:
    available: bool
    detail: str


class BiometricModule(ABC):
    modality: Modality
    method: str

    @abstractmethod
    def status(self) -> ModuleStatus: ...

    @abstractmethod
    def enroll(self, samples: list[bytes]) -> tuple[dict, float, int]:
        """Build a template (dict of numpy arrays) from raw samples.
        Returns (template, mean_quality, number_of_samples_used).
        Raises BiometricInputError / ModelUnavailableError."""

    @abstractmethod
    def verify(self, template: dict, sample: bytes) -> ModalityResult:
        """Never raises for bad input; returns NOT_EVALUATED with a reason instead."""
