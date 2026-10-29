"""Integration tests with REAL models on tiny real fixtures.

Fixtures: three LFW photos (two of one person, one of another) and three LibriSpeech
utterances (two of one speaker, one of another). The tests are skipped, with the reason shown,
when a model or dependency is missing; they never pass silently without running the model.
Run just these with:  pytest -m integration -rs
"""
from pathlib import Path

import pytest

from app.biometrics.calibration import DEFAULTS
from app.biometrics.face import FaceModule
from app.biometrics.types import VerificationStatus
from app.biometrics.voice import VoiceModule
from app.config import Settings

FIX = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.integration
settings = Settings(_env_file=None)


@pytest.fixture(scope="module")
def face():
    m = FaceModule(settings.models_dir, DEFAULTS["face"])
    st = m.status()
    if not st.available:
        pytest.skip(f"face model unavailable: {st.detail}")
    return m


@pytest.fixture(scope="module")
def voice():
    m = VoiceModule(settings.models_dir, DEFAULTS["voice"], 10**7, 2, 20)
    st = m.status()
    if not st.available:
        pytest.skip(f"voice model unavailable: {st.detail}")
    return m


def test_face_genuine_vs_impostor(face):
    tpl, q, _ = face.enroll([(FIX / "face_a1.jpg").read_bytes()])
    gen = face.verify(tpl, (FIX / "face_a2.jpg").read_bytes())
    imp = face.verify(tpl, (FIX / "face_b1.jpg").read_bytes())
    assert gen.status == VerificationStatus.MATCH, gen
    assert imp.status == VerificationStatus.NO_MATCH, imp
    assert gen.raw_score > imp.raw_score + 0.2


def test_face_rejects_non_face_and_blur(face):
    import cv2
    import numpy as np
    tpl, _, _ = face.enroll([(FIX / "face_a1.jpg").read_bytes()])
    blank = cv2.imencode(".png", np.full((300, 300, 3), 127, np.uint8))[1].tobytes()
    r = face.verify(tpl, blank)
    assert r.status == VerificationStatus.NOT_EVALUATED and r.reason_code == "no_face"
    img = cv2.imread(str(FIX / "face_a2.jpg"))
    blurry = cv2.imencode(".png", cv2.GaussianBlur(img, (0, 0), 12))[1].tobytes()
    r = face.verify(tpl, blurry)
    assert r.status == VerificationStatus.NOT_EVALUATED and r.reason_code in ("blurry", "no_face", "low_face_confidence")


def test_voice_same_speaker_vs_other(voice):
    tpl, _, _ = voice.enroll([(FIX / "voice_a1.flac").read_bytes()])
    gen = voice.verify(tpl, (FIX / "voice_a2.flac").read_bytes())
    imp = voice.verify(tpl, (FIX / "voice_b1.flac").read_bytes())
    assert gen.status == VerificationStatus.MATCH, gen
    assert imp.status == VerificationStatus.NO_MATCH, imp
    assert gen.raw_score > imp.raw_score + 0.2


# ---- liveness with the real detector and the real speech recognizer ----
@pytest.fixture(scope="module")
def spoken():
    from app.biometrics.voice_liveness import SpokenChallenge
    sc = SpokenChallenge(settings.models_dir)
    ok, detail = sc.status()
    if not ok:
        pytest.skip(f"speech recognizer unavailable: {detail}")
    return sc


def test_spoken_challenge_hears_words_that_were_said_and_rejects_other_audio(spoken):
    # voice_a1 transcript: "because you were sleeping instead of conquering the lovely rose princess ..."
    said = spoken.check((FIX / "voice_a1.flac").read_bytes(), ["sleeping", "conquering", "princess"])
    assert said.ok, said.details
    other = spoken.check((FIX / "voice_b1.flac").read_bytes(), ["sleeping", "conquering", "princess"])
    assert not other.ok and other.code == "phrase_not_heard"
    assert not spoken.check((FIX / "voice_a1.flac").read_bytes(), ["river", "window", "orange"]).ok


def test_spoken_challenge_rejects_garbage_audio(spoken):
    assert spoken.check(b"not audio", ["river", "window", "orange"]).code == "unsupported_audio"


def test_head_turn_challenge_rejects_a_static_photo_and_a_tilted_flat_photo(face):
    import cv2
    from app.biometrics.liveness import FaceLiveness
    from app.evaluation.run_liveness import jpeg, tilt_warp
    live = FaceLiveness(face)
    img = cv2.imread(str(FIX / "face_a1.jpg"))
    static = live.check([jpeg(img)] * 10, "left")
    assert not static.ok and static.code == "no_head_turn"
    for direction in ("left", "right"):
        tilted = live.check([jpeg(tilt_warp(img, 40 * k / 9)) for k in range(10)], direction)
        assert not tilted.ok, tilted
    assert live.check([jpeg(img)] * 3, "left").code == "frame_count"
