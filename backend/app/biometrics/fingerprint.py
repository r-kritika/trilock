"""Experimental fingerprint matching on fingerprint IMAGES (dataset or scanner export).

Browsers cannot read a laptop fingerprint reader, so this module works on image files: for
example impressions from a public dataset (SOCOFing, FVC-style) or an image exported from a
scanner. It is NOT a minutiae-standard matcher and has not been validated on real fingerprint
data in this repo; see docs/LIMITATIONS.md.

Pipeline
  1. decode grayscale, resize to a fixed height
  2. quality check: block-wise ridge/contrast coverage must be large enough
  3. enhance: foreground mask, local normalisation, CLAHE
  4. SIFT keypoints inside the mask
  5. match: Lowe ratio test, then RANSAC similarity transform (rotation + translation + scale)
     score = number of geometrically consistent inliers

Only keypoint coordinates and descriptors are stored as the template, not the image.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .calibration import Calibrator
from .types import (BiometricInputError, BiometricModule, Modality, ModalityResult, ModuleStatus,
                    VerificationStatus)

TARGET_H = 360
BLOCK = 16
MIN_FOREGROUND = 0.30
MAX_KEYPOINTS = 600
RATIO = 0.7
RANSAC_PX = 3.0


def _enhance(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    g = gray.astype(np.float32)
    # local mean/std per block -> foreground where ridges give contrast
    h, w = g.shape
    mean = cv2.blur(g, (BLOCK * 2 + 1,) * 2)
    var = cv2.blur((g - mean) ** 2, (BLOCK * 2 + 1,) * 2)
    std = np.sqrt(var)
    mask = (std > 12).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    coverage = float(mask.mean())
    norm = (g - mean) / (std + 10.0)
    norm = cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    norm = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(norm)
    return norm, mask, coverage


class FingerprintModule(BiometricModule):
    modality = Modality.FINGERPRINT
    method = "SIFT keypoints + ratio test + RANSAC inlier count (experimental, image based)"

    def __init__(self, calibrator: Calibrator, max_image_bytes: int = 8 * 1024 * 1024):
        self.cal = calibrator
        self.max_image_bytes = max_image_bytes

    def status(self) -> ModuleStatus:
        return ModuleStatus(True, "Image-based matcher ready (no scanner access; dataset / exported images only)")

    def extract(self, data: bytes) -> tuple[dict, float, dict]:
        if not data:
            raise BiometricInputError("empty_input", "The fingerprint image is empty.")
        if len(data) > self.max_image_bytes:
            raise BiometricInputError("file_too_large", "The image is larger than the upload limit.")
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise BiometricInputError("invalid_image", "The file is not a readable image (use PNG, JPEG or BMP).")
        h, w = img.shape
        if min(h, w) < 90:
            raise BiometricInputError("image_too_small", "The fingerprint image is too small (minimum 90 px).")
        scale = TARGET_H / h
        img = cv2.resize(img, (max(1, int(w * scale)), TARGET_H), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        enhanced, mask, coverage = _enhance(img)
        if coverage < MIN_FOREGROUND:
            raise BiometricInputError("poor_fingerprint",
                                      f"Not enough fingerprint ridge area found ({coverage:.0%}, need {MIN_FOREGROUND:.0%}). "
                                      "This does not look like a fingerprint image.")
        sift = cv2.SIFT_create(nfeatures=MAX_KEYPOINTS, contrastThreshold=0.02)
        inner = cv2.erode(mask, np.ones((9, 9), np.uint8))
        kps, desc = sift.detectAndCompute(enhanced, inner)
        if desc is None or len(kps) < 20:
            raise BiometricInputError("too_few_features", "Too few distinct ridge features were found in the image.")
        pts = np.array([k.pt for k in kps], dtype=np.float32)
        quality = round(min(1.0, 0.5 * min(1.0, coverage / 0.7) + 0.5 * min(1.0, len(kps) / 250.0)), 3)
        return {"points": pts, "descriptors": desc.astype(np.float32)}, quality, {
            "foreground": round(coverage, 2), "keypoints": len(kps)}

    @staticmethod
    def match_score(a: dict, b: dict) -> int:
        """Inlier count of the best similarity transform between two keypoint sets."""
        if len(a["points"]) < 8 or len(b["points"]) < 8:
            return 0
        bf = cv2.BFMatcher(cv2.NORM_L2)
        knn = bf.knnMatch(a["descriptors"], b["descriptors"], k=2)
        good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < RATIO * n.distance]
        if len(good) < 4:
            return 0
        src = a["points"][[m.queryIdx for m in good]]
        dst = b["points"][[m.trainIdx for m in good]]
        _, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_PX,
                                             maxIters=2000, confidence=0.99,
                                             refineIters=10)
        return 0 if inl is None else int(inl.sum())

    def enroll(self, samples: list[bytes]) -> tuple[dict, float, int]:
        if not samples:
            raise BiometricInputError("no_samples", "Provide at least one fingerprint image.")
        tpl, quals = {}, []
        for i, s in enumerate(samples[:4]):
            try:
                t, q, _ = self.extract(s)
            except BiometricInputError as err:
                raise BiometricInputError(err.code, f"Sample {i + 1}: {err.message}") from err
            tpl[f"points{i}"], tpl[f"descriptors{i}"] = t["points"], t["descriptors"]
            quals.append(q)
        return tpl, float(np.mean(quals)), len(quals)

    def verify(self, template: dict, sample: bytes) -> ModalityResult:
        t0 = time.perf_counter()
        try:
            probe, quality, details = self.extract(sample)
        except BiometricInputError as e:
            return ModalityResult.not_evaluated(self.modality.value, self.method, e.code, e.message,
                                                (time.perf_counter() - t0) * 1000)
        n = len([k for k in template if k.startswith("points")])
        raw = max(self.match_score({"points": template[f"points{i}"], "descriptors": template[f"descriptors{i}"]}, probe)
                  for i in range(n))
        p = self.cal(float(raw))
        return ModalityResult(
            modality=self.modality.value,
            status=VerificationStatus.MATCH if p >= 0.5 else VerificationStatus.NO_MATCH,
            method=self.method, raw_score=float(raw), calibrated=round(p, 4), quality=quality,
            threshold=self.cal.center, calibration_source=self.cal.source,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1), details=details)
