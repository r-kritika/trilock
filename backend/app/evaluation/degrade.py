"""Input degradations used to test robustness. Each takes encoded bytes and returns encoded bytes."""
from __future__ import annotations

import io

import cv2
import numpy as np
import soundfile as sf


def _img(b: bytes, flag=cv2.IMREAD_COLOR):
    return cv2.imdecode(np.frombuffer(b, np.uint8), flag)


def _png(a) -> bytes:
    return cv2.imencode(".png", a)[1].tobytes()


def blur(sigma):
    return lambda b: _png(cv2.GaussianBlur(_img(b), (0, 0), sigma))


def dim(factor):
    return lambda b: _png((_img(b).astype(np.float32) * factor).astype(np.uint8))


def low_res_jpeg(div, quality):
    def fn(b: bytes) -> bytes:
        a = _img(b)
        h, w = a.shape[:2]
        small = cv2.resize(a, (max(1, w // div), max(1, h // div)))
        return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()
    return fn


def half_occluded(b: bytes) -> bytes:
    a = _img(b, cv2.IMREAD_GRAYSCALE).copy()
    a[:, a.shape[1] // 2:] = 235
    return _png(a)


def heavy_noise(b: bytes) -> bytes:
    a = _img(b, cv2.IMREAD_GRAYSCALE).astype(np.float32)
    rng = np.random.default_rng(0)
    return _png(np.clip(a + rng.normal(0, 40, a.shape), 0, 255).astype(np.uint8))


def _audio(b: bytes):
    x, sr = sf.read(io.BytesIO(b), dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


def _wav(x, sr) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV")
    return buf.getvalue()


def noise_10db(b: bytes) -> bytes:
    x, sr = _audio(b)
    rng = np.random.default_rng(0)
    p = np.mean(x ** 2) + 1e-12
    return _wav(x + rng.normal(0, np.sqrt(p / 10), x.shape).astype(np.float32), sr)


def noise_0db(b: bytes) -> bytes:
    x, sr = _audio(b)
    rng = np.random.default_rng(0)
    p = np.mean(x ** 2) + 1e-12
    return _wav(x + rng.normal(0, np.sqrt(p), x.shape).astype(np.float32), sr)


def clipped_1s(b: bytes) -> bytes:
    x, sr = _audio(b)
    return _wav(x[: sr], sr)


DEGRADATIONS = {
    "face": {
        "mild blur (sigma 1.5)": blur(1.5), "strong blur (sigma 4)": blur(4.0),
        "dim light (x0.4)": dim(0.4), "very dark (x0.18)": dim(0.18),
        "half resolution, JPEG q30": low_res_jpeg(2, 30), "1/5 resolution, JPEG q15": low_res_jpeg(5, 15)},
    "fingerprint": {"half occluded": half_occluded, "heavy noise (sigma 40)": heavy_noise},
    "voice": {"noise SNR 10 dB": noise_10db, "noise SNR 0 dB": noise_0db, "only 1 s of audio": clipped_1s},
}
