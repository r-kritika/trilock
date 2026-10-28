"""Score calibration.

Face cosine similarity, ECAPA cosine similarity and fingerprint inlier counts live on
different scales, so none of them can be averaged directly. Each module gets a logistic map

    p = 1 / (1 + exp(-(raw - center) / scale))

where p is an estimate of "this is the enrolled person". `center` is also the module's
decision threshold (p = 0.5). The built-in defaults are starting points taken from the
model documentation, NOT fitted on our data. `fit_logistic` fits center/scale from labelled
genuine/impostor scores, and the evaluation CLI writes the result to data/calibration.json,
which is then picked up automatically.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Calibrator:
    center: float
    scale: float
    source: str = "default"

    def __call__(self, raw: float) -> float:
        z = (raw - self.center) / self.scale
        z = max(-40.0, min(40.0, z))
        return 1.0 / (1.0 + math.exp(-z))


DEFAULTS = {
    # SFace: OpenCV docs use 0.363 as the cosine threshold.
    "face": Calibrator(center=0.363, scale=0.06),
    # ECAPA-TDNN (SpeechBrain VoxCeleb): their verification example uses 0.25.
    "voice": Calibrator(center=0.25, scale=0.07),
    # SIFT + RANSAC inlier count. Starting guess tuned only on synthetic prints.
    "fingerprint": Calibrator(center=14.0, scale=3.0),
}


def load_calibrators(data_dir: Path) -> dict[str, Calibrator]:
    cals = dict(DEFAULTS)
    path = Path(data_dir) / "calibration.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            for name, v in raw.items():
                if name in cals:
                    cals[name] = Calibrator(float(v["center"]), float(v["scale"]), v.get("source", str(path)))
        except (ValueError, KeyError, TypeError):
            # a broken calibration file must not silently change behaviour, so fail loudly
            raise RuntimeError(f"{path} is not valid calibration JSON")
    return cals


def fit_logistic(genuine: list[float], impostor: list[float], iters: int = 100) -> tuple[float, float]:
    """1-D logistic regression (Newton's method, tiny ridge). Returns (center, scale)."""
    x = np.asarray(list(genuine) + list(impostor), dtype=float)
    y = np.asarray([1.0] * len(genuine) + [0.0] * len(impostor))
    if len(genuine) < 5 or len(impostor) < 5:
        raise ValueError("need at least 5 genuine and 5 impostor scores to calibrate")
    mu, sd = x.mean(), x.std() or 1.0
    z = (x - mu) / sd
    X = np.stack([z, np.ones_like(z)], axis=1)
    w = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (p - y) + 1e-3 * w
        H = (X.T * (p * (1 - p))) @ X + 1e-3 * np.eye(2)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    a, b = w
    if a <= 0:
        raise ValueError("scores are not separable in the expected direction (genuine should score higher)")
    # p = sigmoid(a*(x-mu)/sd + b)  ->  center = mu - b*sd/a, scale = sd/a
    center, scale = float(mu - b * sd / a), float(sd / a)
    # If the classes do not overlap, the likelihood keeps improving as the scale shrinks and the
    # fit collapses into a step function (every score becomes exactly 0 or 1). Floor the scale at
    # 10% of the genuine/impostor mean separation so the output stays a graded confidence.
    separation = abs(float(np.mean(genuine)) - float(np.mean(impostor)))
    return center, max(scale, 0.1 * separation)
