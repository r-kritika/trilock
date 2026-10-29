"""Active liveness check for the face: a random head-turn challenge, judged from facial landmarks.

WHAT IT IS. The server asks for a turn to a random side (left or right). The browser sends a short burst
of frames. From YuNet's five landmarks per frame the check requires:

  1. a face in most frames,
  2. the nose moving relative to the eyes (a "yaw proxy") by at least `yaw_min` in the requested
     direction, so the wrong side or no movement fails,
  3. parallax: after mapping the eyes and mouth corners from the first frame to the turned frame with a
     homography, the nose must land away from where a FLAT face would put it (`parallax_min`). A tilted
     photo moves all landmarks as one plane; a real head does not,
  4. no abrupt jump in yaw between consecutive frames (swapping between two different photos looks like
     a jump; people turn over a second or two),
  5. the face before and after the turn still has the same identity (cosine of SFace embeddings).

WHAT IT IS NOT. It does not stop a video of the owner turning to the requested side (a replay or a
deepfake face puppet), and a printed photo shown with a real 3D mask would pass. The thresholds come
from a geometric simulation on LFW photos (see docs/EVALUATION.md), not from a spoofing dataset such as
CASIA-FASD or Replay-Attack, which I could not download. Not tested with a real webcam.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .face import FaceModule

# Frames are the raw (not mirrored) camera image. When a person turns to THEIR left, their nose moves
# toward the right edge of the unmirrored frame, so the yaw proxy increases.
SIGN = {"left": +1.0, "right": -1.0}


@dataclass
class LivenessConfig:
    min_frames: int = 6
    max_frames: int = 16
    min_detect_fraction: float = 0.7
    yaw_min: float = 0.25          # nose shift needed, in units of eye distance
    parallax_min: float = 0.15     # nose deviation from a flat-face prediction, in units of eye distance
    max_step_fraction: float = 0.7  # largest single-frame yaw jump as a share of the whole movement
    identity_min_cos: float = 0.25  # relaxed because the pose differs between the two frames


@dataclass
class LivenessResult:
    ok: bool
    code: str | None = None
    message: str | None = None
    frame_index: int | None = None     # index of the frame to use for identity verification
    details: dict = field(default_factory=dict)


def yaw_proxy(p: np.ndarray) -> float:
    eye_dist = float(np.linalg.norm(p[0] - p[1]))
    return float((p[2, 0] - (p[0, 0] + p[1, 0]) / 2.0) / max(eye_dist, 1e-6))


def parallax_residual(a: np.ndarray, b: np.ndarray) -> float:
    """Where would the nose of frame B be if the face were a flat plane moving between A and B?
    The four non-nose landmarks define a homography exactly; the residual is how far the real nose
    is from that prediction, divided by the eye distance in B."""
    src = a[[0, 1, 3, 4]].astype(np.float32)
    dst = b[[0, 1, 3, 4]].astype(np.float32)
    try:
        h = cv2.getPerspectiveTransform(src, dst)
    except cv2.error:
        return 0.0
    pred = cv2.perspectiveTransform(a[2].reshape(1, 1, 2).astype(np.float32), h).reshape(2)
    return float(np.linalg.norm(pred - b[2]) / max(np.linalg.norm(b[0] - b[1]), 1e-6))


def _fail(code: str, message: str, **details) -> LivenessResult:
    return LivenessResult(False, code, message, None, details)


class FaceLiveness:
    def __init__(self, face: FaceModule, cfg: LivenessConfig | None = None):
        self.face, self.cfg = face, cfg or LivenessConfig()

    def check(self, frames: list[bytes], direction: str) -> LivenessResult:
        c = self.cfg
        if direction not in SIGN:
            return _fail("bad_challenge", "Unknown challenge direction.")
        if not (c.min_frames <= len(frames) <= c.max_frames):
            return _fail("frame_count", f"Send between {c.min_frames} and {c.max_frames} frames of the turn.",
                         frames=len(frames))
        dets = [self.face.landmarks(f) for f in frames]
        valid = [i for i, d in enumerate(dets) if d is not None]
        if len(valid) < max(c.min_frames, int(c.min_detect_fraction * len(frames))):
            return _fail("face_lost", "Your face was not clearly visible in enough frames.", detected=len(valid), frames=len(frames))

        yaws = {i: yaw_proxy(dets[i][0]) for i in valid}
        base_i = valid[0]
        d = {i: SIGN[direction] * (yaws[i] - yaws[base_i]) for i in valid}
        ext_i = max(valid, key=lambda i: d[i])
        movement = d[ext_i]
        details = {"frames": len(frames), "detected": len(valid), "yaw_change": round(movement, 3),
                   "yaw_needed": c.yaw_min}
        if movement < c.yaw_min:
            if min(d.values()) <= -c.yaw_min:
                return _fail("wrong_direction", f"You turned the other way. Turn to your {direction}.", **details)
            return _fail("no_head_turn", f"No clear head turn to your {direction} was seen.", **details)

        # smoothness: a real turn passes through intermediate poses
        steps = []
        for a_i, b_i in zip(valid, valid[1:]):
            steps.append(abs(yaws[b_i] - yaws[a_i]) / (b_i - a_i))
        worst = max(steps) if steps else 0.0
        details["largest_step"] = round(worst, 3)
        if worst > c.max_step_fraction * max(movement, c.yaw_min):
            return _fail("abrupt_change", "The head position jumped between frames. Turn slowly and smoothly.", **details)

        resid = parallax_residual(dets[base_i][0], dets[ext_i][0])
        details.update(parallax=round(resid, 3), parallax_needed=c.parallax_min)
        if resid < c.parallax_min:
            return _fail("flat_face_suspected", "The face moved like a flat picture, not a head.", **details)

        e0 = self.face.embedding_for(dets[base_i][2], dets[base_i][1])
        e1 = self.face.embedding_for(dets[ext_i][2], dets[ext_i][1])
        cos = float(np.dot(e0, e1) / (np.linalg.norm(e0) * np.linalg.norm(e1) + 1e-9))
        details["identity_consistency"] = round(cos, 3)
        if cos < c.identity_min_cos:
            return _fail("face_changed", "The face changed during the challenge.", **details)
        return LivenessResult(True, None, None, base_i, details)
