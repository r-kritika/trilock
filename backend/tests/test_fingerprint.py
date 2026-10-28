"""Fingerprint module on SYNTHETIC prints (see app/evaluation/synthetic.py). Proves the plumbing
and geometry handling; says nothing about accuracy on real fingerprints."""
import cv2
import numpy as np
import pytest

from app.biometrics.calibration import DEFAULTS
from app.biometrics.fingerprint import FingerprintModule
from app.biometrics.types import BiometricInputError, VerificationStatus
from app.evaluation.synthetic import impression, to_png


@pytest.fixture(scope="module")
def mod():
    return FingerprintModule(DEFAULTS["fingerprint"])


def test_genuine_matches_and_impostor_does_not(mod):
    tpl, q, n = mod.enroll([to_png(impression(1, 0))])
    assert n == 1 and q > 0.3
    genuine = mod.verify(tpl, to_png(impression(1, 1)))
    impostor = mod.verify(tpl, to_png(impression(2, 1)))
    assert genuine.status == VerificationStatus.MATCH and genuine.raw_score > 3 * impostor.raw_score
    assert impostor.status == VerificationStatus.NO_MATCH and impostor.usable


def test_rotation_and_shift_tolerated(mod):
    tpl, _, _ = mod.enroll([to_png(impression(3, 0))])
    rot = cv2.warpAffine(impression(3, 5), cv2.getRotationMatrix2D((160, 160), 25, 1.0), (320, 320), borderValue=235)
    assert mod.verify(tpl, to_png(rot)).status == VerificationStatus.MATCH


@pytest.mark.parametrize("data,code", [
    (b"", "empty_input"),
    (b"not an image", "invalid_image"),
])
def test_invalid_input_is_not_evaluated(mod, data, code):
    tpl, _, _ = mod.enroll([to_png(impression(1, 0))])
    r = mod.verify(tpl, data)
    assert r.status == VerificationStatus.NOT_EVALUATED and r.reason_code == code and not r.usable
    assert r.calibrated is None


def test_blank_and_tiny_images_rejected(mod):
    tpl, _, _ = mod.enroll([to_png(impression(1, 0))])
    blank = to_png(np.full((300, 300), 200, np.uint8))
    assert mod.verify(tpl, blank).reason_code == "poor_fingerprint"
    assert mod.verify(tpl, to_png(np.zeros((40, 40), np.uint8))).reason_code == "image_too_small"


def test_photo_like_noise_is_not_a_fingerprint(mod):
    rng = np.random.default_rng(0)
    tpl, _, _ = mod.enroll([to_png(impression(1, 0))])
    r = mod.verify(tpl, to_png(rng.integers(0, 255, (300, 300), dtype=np.uint8)))
    assert r.status != VerificationStatus.MATCH


def test_enroll_rejects_bad_sample_with_position(mod):
    with pytest.raises(BiometricInputError) as e:
        mod.enroll([to_png(impression(1, 0)), b"junk"])
    assert "Sample 2" in e.value.message
    with pytest.raises(BiometricInputError):
        mod.enroll([])
