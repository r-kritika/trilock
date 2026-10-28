"""Test doubles for the biometric modules.

They let API / workflow tests control exactly what a module reports, without models. The sample
bytes pick the behaviour:  b"match" -> strong match, b"nomatch" -> clear mismatch, b"weak" -> in
between, b"bad" -> unusable input, b"crash" -> the model raises.
"""
import numpy as np

from app.biometrics.registry import BiometricRegistry
from app.biometrics.types import (BiometricInputError, BiometricModule, Modality, ModalityResult, ModuleStatus,
                                  VerificationStatus)

SCORES = {b"match": 0.95, b"nomatch": 0.04, b"weak": 0.55}


class FakeModule(BiometricModule):
    method = "fake test module"

    def __init__(self, modality: str, available: bool = True):
        self.modality = Modality(modality)
        self.available = available

    def status(self):
        return ModuleStatus(self.available, "fake")

    def enroll(self, samples):
        if any(s == b"bad" for s in samples):
            raise BiometricInputError("no_face", "unusable sample")
        return {"embeddings": np.ones((len(samples), 4), dtype=np.float32)}, 0.9, len(samples)

    def verify(self, template, sample):
        name = self.modality.value
        if sample == b"crash":
            raise RuntimeError("model blew up")
        if sample == b"bad":
            return ModalityResult.not_evaluated(name, self.method, "no_face", "unusable sample")
        p = SCORES[sample]
        return ModalityResult(modality=name, status=VerificationStatus.MATCH if p >= 0.5 else VerificationStatus.NO_MATCH,
                              method=self.method, raw_score=p, calibrated=p, quality=0.9, threshold=0.5)


def fake_registry() -> BiometricRegistry:
    return BiometricRegistry({m: FakeModule(m) for m in ("face", "fingerprint", "voice")})
