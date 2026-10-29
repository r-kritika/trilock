"""Spoken challenge for the voice: the server picks three random words, the user must say them.

A recording made earlier cannot contain words that were chosen a moment ago, so pre-recorded audio of
the owner reading something else fails the content check. The check uses a small speech recognizer
(faster-whisper "tiny.en") only to see whether the requested words were said. Who is speaking is still
decided by the speaker-verification model, on the same audio.

Measured on real speech (docs/EVALUATION.md): requiring all three words rejected 22% of honest speakers,
so by default two of the three must be recognised.

LIMITS. It does not stop live voice cloning or text-to-speech in the owner's voice (the attacker types
the three words). It does not stop someone who has recordings of the owner saying each word from the
vocabulary. Recognition errors will also reject honest users, more so in noise or with accents.
"""
from __future__ import annotations

import difflib
import io
import re
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .types import ModelUnavailableError

# Distinct, easy to say, not homophones of each other.
WORDS = ["river", "window", "garden", "orange", "silver", "marble", "candle", "forest", "planet", "bridge",
         "button", "falcon", "harbor", "lantern", "meadow", "pepper", "rocket", "saddle", "thunder", "velvet",
         "wallet", "yellow", "zipper", "anchor", "basket", "copper", "dragon", "engine", "guitar", "hammer",
         "island", "jacket", "kitten", "ladder", "mirror", "napkin", "oyster", "pillow", "ribbon", "spider",
         "tunnel", "violin", "walnut", "cherry", "desert", "pocket", "castle", "turtle"]


def new_phrase(n: int = 3) -> list[str]:
    pool = list(WORDS)
    return [pool.pop(secrets.randbelow(len(pool))) for _ in range(n)]


def normalize(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def match_words(transcript: str, phrase: list[str], fuzzy: float = 0.85) -> list[str]:
    """Which challenge words appear in the transcript (exact, or a near spelling such as a plural)."""
    heard = normalize(transcript)
    found = []
    for w in phrase:
        if any(h == w or difflib.SequenceMatcher(None, h, w).ratio() >= fuzzy for h in heard):
            found.append(w)
    return found


@dataclass
class SpokenResult:
    ok: bool
    code: str | None = None
    message: str | None = None
    details: dict = field(default_factory=dict)


class SpokenChallenge:
    def __init__(self, models_dir: Path, words_needed: int = 2):
        self.models_dir = Path(models_dir)
        self.words_needed = words_needed
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ModelUnavailableError("Speech recognition is not installed (faster-whisper). See requirements-ml.txt.",
                                        "asr_unavailable") from e
        try:
            self._model = WhisperModel("tiny.en", device="cpu", compute_type="int8",
                                       download_root=str(self.models_dir / "whisper"))
        except Exception as e:
            raise ModelUnavailableError(f"The speech recognizer could not be loaded ({type(e).__name__}: {e}).",
                                        "asr_unavailable") from e

    def status(self) -> tuple[bool, str]:
        """Cheap check for dashboards: installed, and the model files already downloaded."""
        import importlib.util
        if importlib.util.find_spec("faster_whisper") is None:
            return False, "faster-whisper is not installed (see requirements-ml.txt)"
        if not list((self.models_dir / "whisper").rglob("model.bin")):
            return False, "recognizer model not downloaded yet (run scripts/download_models.py)"
        return True, "faster-whisper tiny.en ready"

    def available(self) -> tuple[bool, str]:
        try:
            self._load()
            return True, "faster-whisper tiny.en loaded"
        except ModelUnavailableError as e:
            return False, e.message

    def transcribe(self, wav: np.ndarray) -> str:
        self._load()
        with self._lock:
            segs, _ = self._model.transcribe(wav, language="en", beam_size=1, vad_filter=False,
                                             condition_on_previous_text=False)
            return " ".join(s.text for s in segs).strip()

    def check(self, audio: bytes, phrase: list[str]) -> SpokenResult:
        try:
            wav, sr = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
        except Exception:
            return SpokenResult(False, "unsupported_audio", "Could not decode the audio.")
        wav = wav.mean(axis=1)
        if sr != 16000:
            from math import gcd
            g = gcd(16000, sr)
            wav = resample_poly(wav, 16000 // g, sr // g).astype(np.float32)
        try:
            text = self.transcribe(wav)
        except ModelUnavailableError as e:
            return SpokenResult(False, e.code, e.message)
        found = match_words(text, phrase)
        details = {"phrase": phrase, "transcript": text[:200], "words_matched": len(found), "words_needed": self.words_needed}
        if len(found) < self.words_needed:
            missing = [w for w in phrase if w not in found]
            return SpokenResult(False, "phrase_not_heard", f"Say the words clearly. At least {self.words_needed} of {len(phrase)} must be heard. Not heard: {', '.join(missing)}.", details)
        return SpokenResult(True, None, None, details)
