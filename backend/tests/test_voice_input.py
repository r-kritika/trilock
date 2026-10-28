"""Voice input validation. These tests need no model: they cover decoding and quality gates."""
import io

import numpy as np
import pytest
import soundfile as sf

from app.biometrics.types import BiometricInputError, ModalityResult, VerificationStatus
from app.biometrics.voice import SR, VoiceModule, audio_quality, load_audio
from app.biometrics.calibration import DEFAULTS


def wav_bytes(x, sr=SR, fmt="WAV"):
    b = io.BytesIO()
    sf.write(b, x, sr, format=fmt)
    return b.getvalue()


def speechlike(seconds=4.0, sr=SR, seed=0):
    """Syllable-like bursts of a harmonic tone over low noise. Synthetic, only for gating tests."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    env = (np.sin(2 * np.pi * 3 * t) > 0).astype(float) * 0.5 + 0.0
    tone = sum(np.sin(2 * np.pi * 140 * k * t) / k for k in range(1, 6))
    return (0.15 * env * tone + 0.002 * rng.standard_normal(len(t))).astype(np.float32)


def test_valid_audio_passes_gates():
    wav = load_audio(wav_bytes(speechlike()), 10**7, 2, 20)
    q, stats = audio_quality(wav)
    assert 0 < q <= 1 and stats["snr_db"] > 8


def test_resamples_and_mixes_to_mono():
    stereo = np.stack([speechlike(3, 44100), speechlike(3, 44100)], axis=1)
    wav = load_audio(wav_bytes(stereo, 44100), 10**7, 2, 20)
    assert wav.ndim == 1 and abs(len(wav) - 3 * SR) < 5


def test_long_audio_is_cropped():
    assert len(load_audio(wav_bytes(speechlike(30)), 10**7, 2, 10)) == 10 * SR


@pytest.mark.parametrize("data,code", [
    (b"", "empty_input"),
    (b"RIFFnotreallyawav", "unsupported_audio"),
    (wav_bytes(speechlike(0.5)), "too_short"),
])
def test_load_errors(data, code):
    with pytest.raises(BiometricInputError) as e:
        load_audio(data, 10**7, 2, 20)
    assert e.value.code == code


def test_too_large():
    with pytest.raises(BiometricInputError) as e:
        load_audio(b"x" * 100, 50, 2, 20)
    assert e.value.code == "file_too_large"


def test_silence_noise_and_clipping_rejected():
    with pytest.raises(BiometricInputError) as e:
        audio_quality(np.zeros(SR * 3, np.float32))
    assert e.value.code == "silent"
    noise = (0.05 * np.random.default_rng(1).standard_normal(SR * 3)).astype(np.float32)
    with pytest.raises(BiometricInputError) as e:
        audio_quality(noise)
    assert e.value.code == "no_speech"
    clipped = np.clip(speechlike(3) * 100, -1, 1)
    with pytest.raises(BiometricInputError) as e:
        audio_quality(clipped)
    assert e.value.code == "clipping"


def test_verify_bad_input_never_matches(tmp_path):
    m = VoiceModule(tmp_path, DEFAULTS["voice"], 10**7, 2, 20)
    tpl = {"embeddings": np.ones((1, 192), np.float32)}
    for data in (b"", b"junk", wav_bytes(np.zeros(SR * 3, np.float32))):
        r = m.verify(tpl, data)
        assert r.status == VerificationStatus.NOT_EVALUATED and r.calibrated is None


def test_model_unavailable_is_reported_not_faked(tmp_path, monkeypatch):
    """With the model loader failing, a perfectly good recording must come back NOT_EVALUATED."""
    import app.biometrics.voice as v
    m = VoiceModule(tmp_path, DEFAULTS["voice"], 10**7, 2, 20)
    def boom(self): raise v.ModelUnavailableError("no model here")
    monkeypatch.setattr(VoiceModule, "_load", boom)
    r = m.verify({"embeddings": np.ones((1, 192), np.float32)}, wav_bytes(speechlike()))
    assert r.status == VerificationStatus.NOT_EVALUATED and r.reason_code == "model_unavailable"
    assert not m.status().available
