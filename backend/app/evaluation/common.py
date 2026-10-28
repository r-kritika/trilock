"""Dataset loading, trial construction, metrics and reproducibility helpers for the evaluation scripts."""
from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".pgm"}
AUDIO_EXT = {".wav", ".flac", ".ogg"}


# ---------------------------------------------------------------- datasets
def load_identity_dataset(root: Path, exts: set[str]) -> dict[str, list[Path]]:
    """Layout: <root>/<subject>/**/<sample>. Subject = first directory under root."""
    out: dict[str, list[Path]] = {}
    for sub in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        files = sorted(f for f in sub.rglob("*") if f.suffix.lower() in exts)
        if files:
            out[sub.name] = files
    return out


def group_of(ref) -> str:
    """Capture-session proxy: the sample's parent directory (a LibriSpeech chapter, for example)."""
    return str(Path(str(ref)).parent) if isinstance(ref, Path) else str(ref).rsplit("/", 1)[0]


# ---------------------------------------------------------------- trials
@dataclass(frozen=True)
class Trial:
    enrolled: str        # whose template is used
    probe_subject: str   # whose sample is presented
    ref: object          # file path or in-memory key
    label: int           # 1 genuine, 0 impostor
    cross_group: bool    # genuine only: probe from a different session/folder than enrollment


def construct_trials(subjects: dict[str, list], enroll_k: int, max_gen: int, n_imp: int, rng: random.Random):
    """Build enrollment sets and trials.

    * Only subjects with at least enroll_k + 1 samples are used.
    * Enrollment = first enroll_k samples (sorted order). Genuine probes never include them.
    * Genuine probes prefer samples from a different folder than the enrollment samples, so
      same-session consecutive recordings do not dominate; `cross_group` records which it was.
    * Impostor probes are random samples of OTHER subjects.
    Returns (enroll_sets, trials).
    """
    usable = {s: f for s, f in subjects.items() if len(f) >= enroll_k + 1}
    names = sorted(usable)
    enroll_sets = {s: usable[s][:enroll_k] for s in names}
    trials: list[Trial] = []
    for s in names:
        enrolled_groups = {group_of(f) for f in enroll_sets[s]}
        rest = usable[s][enroll_k:]
        rest = sorted(rest, key=lambda f: (group_of(f) in enrolled_groups, str(f)))   # other sessions first
        for f in rest[:max_gen]:
            trials.append(Trial(s, s, f, 1, group_of(f) not in enrolled_groups))
        others = [o for o in names if o != s]
        for o in rng.sample(others, min(n_imp, len(others))):
            trials.append(Trial(s, o, rng.choice(usable[o]), 0, False))
    return enroll_sets, trials


def split_subjects(names: list[str], seed: int) -> set[str]:
    """Calibration half. The remaining subjects are the evaluation half; the two never overlap."""
    r = random.Random(seed)
    shuffled = sorted(names)
    r.shuffle(shuffled)
    return set(shuffled[: len(shuffled) // 2])


def select_in_half(records: list[dict], half: set[str]) -> list[dict]:
    """Trials whose template owner AND probe owner both belong to `half`.
    A trial that crosses halves would leak calibration-half identities into evaluation."""
    return [r for r in records if r["enrolled"] in half and r["probe_subject"] in half]


def manifest_hash(trials: list[Trial]) -> str:
    rows = sorted(f"{t.enrolled}|{t.probe_subject}|{t.ref}|{t.label}" for t in trials)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- metrics
def rate(x: float) -> float | None:
    """Round a rate; NaN (no trials) becomes None so the JSON stays valid."""
    x = float(x)
    return None if x != x else round(x, 5)


def far_frr(genuine: np.ndarray, impostor: np.ndarray, thr: float) -> tuple[float, float]:
    """A probe is accepted when score >= thr. FAR = impostors accepted, FRR = genuines not accepted."""
    far = float(np.mean(impostor >= thr)) if len(impostor) else float("nan")
    frr = float(np.mean(genuine < thr)) if len(genuine) else float("nan")
    return far, frr


def eer(genuine: np.ndarray, impostor: np.ndarray) -> tuple[float, float]:
    """Equal error rate and its threshold: scan every observed score as a threshold and take the
    one where FAR and FRR are closest; report their average."""
    if len(genuine) == 0 or len(impostor) == 0:
        return float("nan"), float("nan")
    best = (3.0, 0.0, 0.0)
    for t in np.unique(np.concatenate([genuine, impostor])):
        far, frr = far_frr(genuine, impostor, t)
        gap = abs(far - frr)
        if gap < best[0] - 1e-12:
            best = (gap, (far + frr) / 2, float(t))
    return best[1], best[2]


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """95% Wilson score interval for a proportion k/n. Assumes independent trials."""
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 5), round(min(1.0, c + h), 5)


def mean_sd(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None and x == x]
    if not xs:
        return {"mean": None, "sd": None, "n": 0}
    return {"mean": rate(np.mean(xs)), "sd": rate(np.std(xs, ddof=1)) if len(xs) > 1 else 0.0, "n": len(xs)}


# ---------------------------------------------------------------- io / provenance
def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, allow_nan=False))


def seeded(seed: int) -> random.Random:
    return random.Random(seed)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def provenance(argv: list[str], seed: int, extra: dict | None = None) -> dict:
    versions = {"python": platform.python_version(), "numpy": np.__version__}
    for mod in ("cv2", "torch", "speechbrain", "scipy"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:
            pass
    return {"command": " ".join(argv), "seed": seed, "versions": versions, "platform": platform.platform(), **(extra or {})}


def store_run(settings, kind: str, name: str, data_source: str, is_synthetic: bool, metrics: dict) -> int:
    from ..database import init_db, make_engine, make_session_factory
    from ..models import EvaluationRun
    json.dumps(metrics, allow_nan=False)      # fail early rather than store NaN
    engine = make_engine(settings.db_url)
    init_db(engine)
    with make_session_factory(engine)() as db:
        run = EvaluationRun(kind=kind, name=name, data_source=data_source, is_synthetic=is_synthetic, metrics=metrics)
        db.add(run)
        db.commit()
        return run.id
