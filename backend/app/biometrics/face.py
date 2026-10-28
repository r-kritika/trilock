"""Face verification: YuNet detector + SFace embedding (both via OpenCV's DNN module).

SFace gives a 128-d embedding; two faces are compared with cosine similarity. This is genuine
1:1 verification, not just detection. There is NO liveness / anti-spoofing: a printed photo
or a screen replay of the enrolled person will score like the real face.

Model files (ONNX, from the OpenCV Zoo) are expected in the models directory; see
scripts/download_models.py.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
import numpy as np

from .calibration import Calibrator
from .types import (BiometricInputError, BiometricModule, Modality, ModalityResult, ModelUnavailableError,
                    ModuleStatus, VerificationStatus)

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"

MAX_SIDE = 960
MIN_DET_SCORE = 0.85
MIN_FACE_PX = 80
MIN_SHARPNESS = 25.0       # variance of Laplacian on the 112x112 aligned crop


class FaceModule(BiometricModule):
    modality = Modality.FACE
    method = "YuNet detection + SFace embedding, cosine similarity"

    def __init__(self, models_dir: Path, calibrator: Calibrator, max_image_bytes: int = 8 * 1024 * 1024):
        self.models_dir = Path(models_dir)
        self.cal = calibrator
        self.max_image_bytes = max_image_bytes
        self._lock = threading.Lock()
        self._det = None
        self._rec = None

    # ---- model loading -------------------------------------------------
    def _load(self):
        if self._det is not None:
            return
        det_p, rec_p = self.models_dir / DETECTOR_FILE, self.models_dir / RECOGNIZER_FILE
        missing = [p.name for p in (det_p, rec_p) if not p.exists()]
        if missing:
            raise ModelUnavailableError(
                f"Face model file(s) missing: {', '.join(missing)}. Run `python scripts/download_models.py`.")
        try:
            self._det = cv2.FaceDetectorYN.create(str(det_p), "", (320, 320), 0.7, 0.3, 5000)
            self._rec = cv2.FaceRecognizerSF.create(str(rec_p), "")
        except cv2.error as e:
            self._det = self._rec = None
            raise ModelUnavailableError(f"Face models failed to load: {e}") from e

    def model_files(self) -> list[Path]:
        return [self.models_dir / DETECTOR_FILE, self.models_dir / RECOGNIZER_FILE]

    def status(self) -> ModuleStatus:
        try:
            self._load()
            return ModuleStatus(True, "YuNet + SFace loaded")
        except ModelUnavailableError as e:
            return ModuleStatus(False, e.message)

    # ---- sample processing --------------------------------------------
    def _decode(self, data: bytes) -> np.ndarray:
        if not data:
            raise BiometricInputError("empty_input", "The image file is empty.")
        if len(data) > self.max_image_bytes:
            raise BiometricInputError("file_too_large", "The image is larger than the upload limit.")
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise BiometricInputError("invalid_image", "The file is not a readable image (use JPEG or PNG).")
        h, w = img.shape[:2]
        if min(h, w) < 160:
            raise BiometricInputError("image_too_small", "The image is too small (minimum 160 px on the short side).")
        scale = MAX_SIDE / max(h, w)
        if scale < 1:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        return img

    def extract(self, data: bytes) -> tuple[np.ndarray, float, dict]:
        """Returns (embedding, quality 0..1, details). Raises BiometricInputError / ModelUnavailableError."""
        self._load()
        img = self._decode(data)
        h, w = img.shape[:2]
        with self._lock:
            self._det.setInputSize((w, h))
            _, faces = self._det.detect(img)
            if faces is None or len(faces) == 0:
                raise BiometricInputError("no_face", "No face was detected. Face the camera in good light.")
            faces = faces[np.argsort(-(faces[:, 2] * faces[:, 3]))]
            best = faces[0]
            if len(faces) > 1 and faces[1][2] * faces[1][3] > 0.5 * best[2] * best[3]:
                raise BiometricInputError("multiple_faces", "More than one face is visible. Only the user should be in frame.")
            if best[-1] < MIN_DET_SCORE:
                raise BiometricInputError("low_face_confidence", "The face is unclear (low detector confidence).")
            if min(best[2], best[3]) < MIN_FACE_PX:
                raise BiometricInputError("face_too_small", "The face is too small in the frame. Move closer.")
            aligned = self._rec.alignCrop(img, best)
            emb = self._rec.feature(aligned).astype(np.float32).ravel()

        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if sharp < MIN_SHARPNESS:
            raise BiometricInputError("blurry", f"The face image is too blurry (sharpness {sharp:.0f}, need {MIN_SHARPNESS:.0f}).")
        bright = float(gray.mean())
        if bright < 40 or bright > 225:
            raise BiometricInputError("bad_lighting", "The face is too dark or too bright.")
        q = (0.5 * min(1.0, sharp / 150.0)
             + 0.3 * min(1.0, min(best[2], best[3]) / 160.0)
             + 0.2 * (1.0 - abs(bright - 128.0) / 128.0))
        details = {"sharpness": round(sharp, 1), "face_px": int(min(best[2], best[3])),
                   "brightness": round(bright, 1), "detector_score": round(float(best[-1]), 3)}
        return emb, round(float(q), 3), details

    # ---- BiometricModule API ------------------------------------------
    def enroll(self, samples: list[bytes]) -> tuple[dict, float, int]:
        if not samples:
            raise BiometricInputError("no_samples", "Provide at least one face image.")
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
        except BiometricInputError as e:
            return ModalityResult.not_evaluated(self.modality.value, self.method, e.code, e.message,
                                                (time.perf_counter() - t0) * 1000)
        except ModelUnavailableError as e:
            return ModalityResult.not_evaluated(self.modality.value, self.method, e.code, e.message,
                                                (time.perf_counter() - t0) * 1000)
        ref = template["embeddings"]
        # cosine against each enrolled embedding; best one counts
        a = emb / (np.linalg.norm(emb) + 1e-9)
        b = ref / (np.linalg.norm(ref, axis=1, keepdims=True) + 1e-9)
        raw = float(np.max(b @ a))
        p = self.cal(raw)
        return ModalityResult(
            modality=self.modality.value,
            status=VerificationStatus.MATCH if p >= 0.5 else VerificationStatus.NO_MATCH,
            method=self.method, raw_score=round(raw, 4), calibrated=round(p, 4), quality=quality,
            threshold=self.cal.center, calibration_source=self.cal.source,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1), details=details)
