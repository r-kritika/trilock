"""Speaker verification with SpeechBrain's ECAPA-TDNN (VoxCeleb) embeddings.

This compares *who* is speaking, not what is said. Audio is decoded with libsndfile (WAV, FLAC,
OGG), mixed to mono and resampled to 16 kHz. The browser UI records and converts to WAV itself,
because the server has no ffmpeg dependency.

No liveness / replay detection. A recording of the enrolled speaker will be accepted.
The model needs torch + speechbrain and a one-time download of the weights from Hugging Face.
"""
from __future__ import annotations

import io
import threading
import time
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .calibration import Calibrator
from .types import (BiometricInputError, BiometricModule, Modality, ModalityResult, ModelUnavailableError,
                    ModuleStatus, VerificationStatus)

SR = 16000
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
MIN_RMS = 0.005            # below this the recording is effectively silent
MIN_SPEECH_FRACTION = 0.25
MAX_CLIPPING = 0.05
MIN_SNR_DB = 8.0


def load_audio(data: bytes, max_bytes: int, min_s: float, max_s: float) -> np.ndarray:
    if not data:
        raise BiometricInputError("empty_input", "The audio file is empty.")
    if len(data) > max_bytes:
        raise BiometricInputError("file_too_large", "The audio file is larger than the upload limit.")
    try:
        wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception:
        raise BiometricInputError("unsupported_audio",
                                  "Could not decode the audio. Use WAV, FLAC or OGG (the in-browser recorder produces WAV).")
    wav = wav.mean(axis=1)
    if sr != SR:
        g = gcd(SR, sr)
        wav = resample_poly(wav, SR // g, sr // g).astype(np.float32)
    dur = len(wav) / SR
    if dur < min_s:
        raise BiometricInputError("too_short", f"The recording is {dur:.1f}s long; at least {min_s:.0f}s of speech is needed.")
    if dur > max_s:
        wav = wav[: int(max_s * SR)]
    return wav


def audio_quality(wav: np.ndarray) -> tuple[float, dict]:
    """Returns (quality 0..1, stats) or raises BiometricInputError for unusable audio."""
    rms = float(np.sqrt(np.mean(wav ** 2)))
    if rms < MIN_RMS or not np.isfinite(rms):
        raise BiometricInputError("silent", "The recording is silent or far too quiet.")
    clip = float(np.mean(np.abs(wav) > 0.99))
    if clip > MAX_CLIPPING:
        raise BiometricInputError("clipping", "The recording is heavily clipped. Move away from the microphone.")
    frame = 400  # 25 ms
    n = len(wav) // frame
    energy = np.log10(np.mean(wav[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-10) * 10
    noise_floor, peak = np.percentile(energy, 10), np.percentile(energy, 95)
    snr = float(peak - noise_floor)           # crude: loud frames vs quiet frames
    speech_frac = float(np.mean(energy > noise_floor + 0.5 * snr)) if snr > 3 else 0.0
    if snr < MIN_SNR_DB or speech_frac < MIN_SPEECH_FRACTION:
        raise BiometricInputError("no_speech", "No clear speech was found in the recording (too noisy or no voice).")
    q = 0.6 * min(1.0, snr / 30.0) + 0.2 * min(1.0, speech_frac / 0.6) + 0.2 * (1.0 - clip / MAX_CLIPPING)
    return round(float(q), 3), {"rms": round(rms, 4), "snr_db": round(snr, 1),
                                "speech_fraction": round(speech_frac, 2), "clipping": round(clip, 4)}


class VoiceModule(BiometricModule):
    modality = Modality.VOICE
    method = "SpeechBrain ECAPA-TDNN (VoxCeleb) speaker embedding, cosine similarity"

    def __init__(self, models_dir: Path, calibrator: Calibrator, max_audio_bytes: int,
                 min_seconds: float, max_seconds: float):
        self.models_dir = Path(models_dir)
        self.cal = calibrator
        self.max_bytes = max_audio_bytes
        self.min_s, self.max_s = min_seconds, max_seconds
        self._clf = None
        self._torch = None
        self._lock = threading.Lock()
        self._last_fail: tuple[float, str] | None = None

    def _load(self):
        if self._clf is not None:
            return
        if self._last_fail and time.time() - self._last_fail[0] < 30:
            raise ModelUnavailableError(self._last_fail[1])
        try:
            import torch
            try:
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError:  # speechbrain < 1.0
                from speechbrain.pretrained import EncoderClassifier
        except ImportError as e:
            msg = f"Voice model dependencies are missing ({e.name}). Install requirements-ml.txt (see README)."
            self._last_fail = (time.time(), msg)
            raise ModelUnavailableError(msg) from e
        try:
            self._clf = EncoderClassifier.from_hparams(
                source=MODEL_SOURCE, savedir=str(self.models_dir / "ecapa"), run_opts={"device": "cpu"})
            self._torch = torch
        except Exception as e:  # network / disk / format problems
            msg = ("The ECAPA voice model could not be loaded. It is downloaded from Hugging Face on first use; "
                   f"check the network or run scripts/download_models.py. ({type(e).__name__}: {e})")
            self._last_fail = (time.time(), msg)
            raise ModelUnavailableError(msg) from e

    def status(self) -> ModuleStatus:
        try:
            self._load()
            return ModuleStatus(True, "ECAPA-TDNN loaded")
        except ModelUnavailableError as e:
            return ModuleStatus(False, e.message)

    def embed(self, wav: np.ndarray) -> np.ndarray:
        self._load()
        with self._lock, self._torch.no_grad():
            t = self._torch.from_numpy(wav).unsqueeze(0)
            e = self._clf.encode_batch(t).squeeze().cpu().numpy()
        if not np.all(np.isfinite(e)):
            raise ModelUnavailableError("The voice model produced an invalid embedding.", "inference_failed")
        return e.astype(np.float32)

    def extract(self, data: bytes) -> tuple[np.ndarray, float, dict]:
        wav = load_audio(data, self.max_bytes, self.min_s, self.max_s)
        q, stats = audio_quality(wav)
        stats["duration_s"] = round(len(wav) / SR, 1)
        return self.embed(wav), q, stats

    def enroll(self, samples: list[bytes]) -> tuple[dict, float, int]:
        if not samples:
            raise BiometricInputError("no_samples", "Provide at least one voice recording.")
        embs, quals = [], []
        for i, s in enumerate(samples[:5]):
            try:
                e, q, _ = self.extract(s)
            except BiometricInputError as err:
                raise BiometricInputError(err.code, f"Sample {i + 1}: {err.message}") from err
            embs.append(e)
            quals.append(q)
        return {"embeddings": np.stack(embs)}, float(np.mean(quals)), len(embs)

    def verify(self, template: dict, sample: bytes) -> ModalityResult:
        t0 = time.perf_counter()
        try:
            emb, quality, details = self.extract(sample)
        except (BiometricInputError, ModelUnavailableError) as e:
            return ModalityResult.not_evaluated(self.modality.value, self.method, e.code, e.message,
                                                (time.perf_counter() - t0) * 1000)
        ref = template["embeddings"].mean(axis=0)
        raw = float(np.dot(emb, ref) / (np.linalg.norm(emb) * np.linalg.norm(ref) + 1e-9))
        p = self.cal(raw)
        return ModalityResult(
            modality=self.modality.value,
            status=VerificationStatus.MATCH if p >= 0.5 else VerificationStatus.NO_MATCH,
            method=self.method, raw_score=round(raw, 4), calibrated=round(p, 4), quality=quality,
            threshold=self.cal.center, calibration_source=self.cal.source,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1), details=details)
