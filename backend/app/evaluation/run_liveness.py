"""Measure the two liveness checks as far as the available data allows.

  python -m app.evaluation.run_liveness --lfw data/datasets/lfw/lfw_funneled \
         --speech data/datasets/librispeech/LibriSpeech/dev-clean-2

WHAT IS MEASURED, AND WHAT IS NOT. No spoofing dataset (CASIA-FASD, Replay-Attack, ASVspoof) could be
downloaded, so nothing here is a measurement against real attacks. Instead:

Face (real detector, real LFW photos, SIMULATED attacks)
  * flat-photo tilt: one photo, warped as a flat sheet turning about a vertical axis (perspective), as
    a smooth frame sequence, run through the real FaceLiveness.check.
  * photo swap: two real photos of the same person (frontal, then turned the requested way) shown one
    after the other, run through the same check.
  * real-turn proxy: pairs of DIFFERENT photos of the same person stand in for a real head turn. Only
    the parallax part of the check is measured this way (a smooth real turn cannot be built from stills),
    so this is not a measured false-reject rate for the whole check.

Voice (real recognizer, real speech, content check only)
  * pass rate when the challenge words are actually said (words taken from the utterance's transcript)
  * pass rate under added noise
  * pass rate when the audio is a DIFFERENT utterance (replay of unrelated recording)
  * chance that unrelated speech contains three random challenge words from our vocabulary
This measures the recognizer-based content check. It says nothing about voice cloning, and the challenge
words here are LibriSpeech words rather than the project's vocabulary, because I cannot record people.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np

from ..biometrics.calibration import DEFAULTS
from ..biometrics.face import FaceModule
from ..biometrics.liveness import FaceLiveness, LivenessConfig, SIGN, parallax_residual, yaw_proxy
from ..biometrics.voice_liveness import WORDS, SpokenChallenge, match_words, normalize
from ..config import get_settings
from .common import provenance, rate, store_run, wilson_ci
from .degrade import noise_0db, noise_10db


def jpeg(img) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def tilt_warp(img, deg: float):
    """A flat photo turned `deg` degrees about its vertical axis, seen by a pinhole camera."""
    h, w = img.shape[:2]
    th, f, d = np.deg2rad(deg), 1.2 * w, 1.6 * w
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float64) - [w / 2, h / 2]
    q = [[f * x * np.cos(th) / (d + x * np.sin(th)) + w / 2, f * y / (d + x * np.sin(th)) + h / 2] for x, y in corners]
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(q))
    return cv2.warpPerspective(img, H, (w, h), borderValue=(128, 128, 128))


def rate_ci(k: int, n: int) -> dict:
    lo, hi = wilson_ci(k, n)
    return {"k": k, "n": n, "rate": rate(k / n) if n else None, "ci95": [lo, hi]}


def face_part(root: Path, seed: int, n_people: int, cfg: LivenessConfig, log=print) -> dict:
    settings = get_settings()
    fm = FaceModule(settings.models_dir, DEFAULTS["face"])
    if not fm.status().available:
        raise SystemExit("face models unavailable")
    live = FaceLiveness(fm, cfg)
    rng = random.Random(seed)
    people = [p for p in sorted(Path(root).iterdir()) if p.is_dir() and len(list(p.glob("*.jpg"))) >= 4]
    rng.shuffle(people)
    people = people[:n_people]

    tilt_pass = tilt_total = 0
    tilt_codes: dict[str, int] = {}
    swap_pass = swap_total = 0
    swap_codes: dict[str, int] = {}
    pair_total = pair_ok = 0
    for p in people:
        imgs = [cv2.imread(str(f)) for f in sorted(p.glob("*.jpg"))[:6]]
        det = [fm.landmarks(jpeg(i)) for i in imgs]
        ok = [(i, d[0]) for i, d in zip(imgs, det) if d is not None]
        if not ok:
            continue
        # flat-photo tilt attacks, smooth ramp over 10 frames, challenged direction random
        base_img = ok[0][0]
        for ang in (10, 20, 30, 40):
            direction = rng.choice(["left", "right"])
            sign = rng.choice([-1, 1])
            frames = [jpeg(tilt_warp(base_img, sign * ang * k / 9)) for k in range(10)]
            r = live.check(frames, direction)
            tilt_total += 1
            tilt_pass += r.ok
            tilt_codes[r.code or "passed"] = tilt_codes.get(r.code or "passed", 0) + 1
        # photo swap: two real photos, second one turned the requested way
        for (i1, p1), (i2, p2) in zip(ok, ok[1:]):
            for direction in ("left", "right"):
                if SIGN[direction] * (yaw_proxy(p2) - yaw_proxy(p1)) >= cfg.yaw_min:
                    r = live.check([jpeg(i1)] * 5 + [jpeg(i2)] * 5, direction)
                    swap_total += 1
                    swap_pass += r.ok
                    swap_codes[r.code or "passed"] = swap_codes.get(r.code or "passed", 0) + 1
        # real-turn proxy: the parallax test on pairs that differ by a clear turn
        for (i1, p1), (i2, p2) in zip(ok, ok[1:]):
            if abs(yaw_proxy(p2) - yaw_proxy(p1)) >= cfg.yaw_min:
                pair_total += 1
                pair_ok += parallax_residual(p1, p2) >= cfg.parallax_min
    log(f"face: {len(people)} people; tilt {tilt_pass}/{tilt_total}; swap {swap_pass}/{swap_total}; turn-pairs {pair_ok}/{pair_total}")
    return {"people": len(people), "thresholds": {"yaw_min": cfg.yaw_min, "parallax_min": cfg.parallax_min,
                                                  "max_step_fraction": cfg.max_step_fraction},
            "flat_photo_tilt_attack_passes": rate_ci(tilt_pass, tilt_total), "flat_photo_result_codes": tilt_codes,
            "photo_swap_attack_passes": rate_ci(swap_pass, swap_total), "photo_swap_result_codes": swap_codes,
            "real_turn_proxy_parallax_pass": rate_ci(pair_ok, pair_total),
            "note": "attacks are geometric simulations on stills; turn proxy uses different photos of one person"}


def read_transcripts(root: Path):
    out = []
    for tf in sorted(Path(root).rglob("*.trans.txt")):
        for line in tf.read_text().splitlines():
            uid, text = line.split(" ", 1)
            f = tf.parent / f"{uid}.flac"
            if f.exists():
                out.append((uid.split("-")[0], f, text.lower()))
    return out


def voice_part(root: Path, seed: int, per_speaker: int, log=print) -> dict:
    settings = get_settings()
    sc = SpokenChallenge(settings.models_dir)
    ok, detail = sc.status()
    if not ok:
        raise SystemExit(f"speech recognizer unavailable: {detail}")
    rng = random.Random(seed)
    by_spk: dict[str, list] = {}
    for spk, f, text in read_transcripts(root):
        by_spk.setdefault(spk, []).append((f, text))
    items = []
    for spk, lst in sorted(by_spk.items()):
        rng.shuffle(lst)
        items += [(spk, f, t) for f, t in lst[:per_speaker]]
    log(f"voice: {len(items)} utterances from {len(by_spk)} speakers")

    import io
    import soundfile as sf

    def transcribe(data: bytes) -> str:
        wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        wav = wav.mean(axis=1)
        if sr != 16000:
            from math import gcd
            from scipy.signal import resample_poly
            g = gcd(16000, sr)
            wav = resample_poly(wav, 16000 // g, sr // g).astype(np.float32)
        return sc.transcribe(wav)

    rows = []
    for spk, f, text in items:
        words = sorted({w for w in normalize(text) if len(w) >= 5})
        if len(words) < 3:
            continue
        challenge = rng.sample(words, 3)
        data = f.read_bytes()
        rows.append({"spk": spk, "challenge": challenge, "clean": transcribe(data),
                     "n10": transcribe(noise_10db(_wav_bytes(data))), "n0": transcribe(noise_0db(_wav_bytes(data)))})
    n = len(rows)

    def passes(transcript, ch, need):
        return len(match_words(transcript, ch)) >= need

    res = {"utterances": n, "speakers": len(by_spk)}
    for need in (3, 2):
        res[f"said_words_pass_{need}of3"] = {c: rate_ci(sum(passes(r[c], r["challenge"], need) for r in rows), n)
                                            for c in ("clean", "n10", "n0")}
        # content replay: the challenge words are checked against a different speaker's utterance
        other = [(r, rng.choice([x for x in rows if x["spk"] != r["spk"]])) for r in rows for _ in range(5)]
        res[f"unrelated_audio_pass_{need}of3"] = rate_ci(sum(passes(o["clean"], r["challenge"], need) for r, o in other), len(other))
    # the project's own vocabulary against unrelated speech
    draws = [rng.sample(WORDS, 3) for _ in range(3000)]
    pool = [r["clean"] for r in rows]
    hits = sum(passes(rng.choice(pool), ch, 3) for ch in draws)
    res["project_vocabulary_chance_pass_3of3"] = rate_ci(hits, len(draws))
    log(f"voice: said clean 3of3 {res['said_words_pass_3of3']['clean']['rate']}, 2of3 {res['said_words_pass_2of3']['clean']['rate']}; "
        f"unrelated 3of3 {res['unrelated_audio_pass_3of3']['rate']}")
    res["note"] = "content check only; challenge words come from the utterance transcript; no voice cloning tested"
    return res


def _wav_bytes(flac: bytes) -> bytes:
    import io
    import soundfile as sf
    x, sr = sf.read(io.BytesIO(flac), dtype="float32", always_2d=True)
    b = io.BytesIO()
    sf.write(b, x.mean(axis=1), sr, format="WAV")
    return b.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lfw", type=Path)
    ap.add_argument("--speech", type=Path)
    ap.add_argument("--people", type=int, default=250)
    ap.add_argument("--per-speaker", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    settings = get_settings()
    metrics = {"reproducibility": provenance(sys.argv, a.seed)}
    sources = []
    if a.lfw:
        metrics["face"] = face_part(a.lfw, a.seed, a.people, LivenessConfig())
        sources.append(f"face: {a.lfw} (simulated attacks)")
    if a.speech:
        metrics["voice"] = voice_part(a.speech, a.seed, a.per_speaker)
        sources.append(f"voice: {a.speech}")
    rid = store_run(settings, "liveness", "liveness checks", "; ".join(sources), True, metrics)
    print(f"saved run {rid}")


if __name__ == "__main__":
    main()
