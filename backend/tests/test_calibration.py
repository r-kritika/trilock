import numpy as np
import pytest

from app.biometrics.calibration import Calibrator, fit_logistic, load_calibrators


def test_center_is_half_and_monotonic():
    c = Calibrator(0.4, 0.05)
    assert c(0.4) == pytest.approx(0.5)
    assert c(0.2) < c(0.4) < c(0.6)
    assert 0 <= c(-1e9) <= c(1e9) <= 1


def test_fit_recovers_separating_point():
    rng = np.random.default_rng(0)
    g, i = rng.normal(0.6, 0.1, 400), rng.normal(0.1, 0.1, 400)
    center, scale = fit_logistic(list(g), list(i))
    assert 0.3 < center < 0.4 and scale > 0
    cal = Calibrator(center, scale)
    assert cal(0.6) > 0.9 and cal(0.1) < 0.1


def test_fit_rejects_inverted_or_tiny_data():
    with pytest.raises(ValueError):
        fit_logistic([0.1] * 10, [0.9] * 10)
    with pytest.raises(ValueError):
        fit_logistic([1, 2], [0, 0])


def test_load_calibration_file(tmp_path):
    (tmp_path / "calibration.json").write_text('{"face": {"center": 0.5, "scale": 0.1, "source": "unit-test"}}')
    cals = load_calibrators(tmp_path)
    assert cals["face"].center == 0.5 and cals["face"].source == "unit-test"
    assert cals["voice"].source == "default"


def test_broken_calibration_file_fails_loudly(tmp_path):
    (tmp_path / "calibration.json").write_text("{not json")
    with pytest.raises(RuntimeError):
        load_calibrators(tmp_path)


def test_separable_data_does_not_collapse_to_a_step():
    # no overlap at all: unregularised logistic scale would tend to zero
    g, i = list(np.linspace(0.6, 0.8, 50)), list(np.linspace(0.0, 0.2, 50))
    center, scale = fit_logistic(g, i)
    assert 0.2 < center < 0.6
    assert scale >= 0.1 * (0.7 - 0.1) - 1e-9
    assert 0.01 < Calibrator(center, scale)(0.55) < 0.99
