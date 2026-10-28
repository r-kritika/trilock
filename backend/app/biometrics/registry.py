from __future__ import annotations

from ..config import Settings
from .calibration import load_calibrators
from .face import FaceModule
from .fingerprint import FingerprintModule
from .types import BiometricModule
from .voice import VoiceModule

ORDER = ["face", "fingerprint", "voice"]


class BiometricRegistry:
    def __init__(self, modules: dict[str, BiometricModule]):
        self.modules = modules

    def get(self, modality: str) -> BiometricModule:
        try:
            return self.modules[modality]
        except KeyError:
            raise KeyError(f"unknown modality '{modality}'")

    def statuses(self) -> dict:
        out = {}
        for name in ORDER:
            m = self.modules[name]
            s = m.status()
            out[name] = {"available": s.available, "detail": s.detail, "method": m.method,
                         "calibration": getattr(getattr(m, "cal", None), "source", None)}
        return out


def build_registry(settings: Settings) -> BiometricRegistry:
    cals = load_calibrators(settings.data_dir)
    return BiometricRegistry({
        "face": FaceModule(settings.models_dir, cals["face"], settings.max_image_bytes),
        "fingerprint": FingerprintModule(cals["fingerprint"], settings.max_image_bytes),
        "voice": VoiceModule(settings.models_dir, cals["voice"], settings.max_audio_bytes,
                             settings.voice_min_seconds, settings.voice_max_seconds),
    })
