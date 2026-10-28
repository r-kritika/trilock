"""Evaluate one biometric module on a labelled identity dataset.

  python -m app.evaluation.run_modality --modality face --root data/datasets/lfw/lfw_funneled
  python -m app.evaluation.run_modality --modality voice --root data/datasets/librispeech/LibriSpeech/dev-clean-2
  python -m app.evaluation.run_modality --modality fingerprint --synthetic

Protocol
  * Dataset layout <root>/<subject>/**/<sample>. See common.construct_trials for how enrollment,
    genuine and impostor trials are built (no sample is both enrolled and probed; genuine probes
    prefer a different folder/session than enrollment; impostor probes belong to other subjects).
  * Every trial runs through the real module once. Scores do not depend on the calibration.
  * The subjects are split into a calibration half and an evaluation half. A trial is used only if
    BOTH the template owner and the probe owner are in the same half, so no calibration identity
    ever appears in the evaluation set. The split is repeated --splits times with different seeds.
  * Per split: fit the logistic calibration on the calibration half, then report FAR/FRR at the
    fitted threshold, EER and the not-evaluable rate on the evaluation half.
  * Split 0 is the "primary" split: its fit and evaluation trials are stored for the fusion
    experiments, and the degraded-input tests run on its evaluation trials.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from ..biometrics.calibration import Calibrator, fit_logistic
from ..biometrics.registry import build_registry
from ..config import get_settings
from . import synthetic
from .common import (AUDIO_EXT, IMAGE_EXT, construct_trials, eer, far_frr, load_identity_dataset, manifest_hash,
                     mean_sd, provenance, rate, save_json, select_in_half, seeded, sha256_file, split_subjects,
                     store_run, wilson_ci)
from .degrade import DEGRADATIONS


def read(x) -> bytes:
    return x if isinstance(x, (bytes, bytearray)) else Path(x).read_bytes()


def synthetic_fingerprint_subjects(n_subjects: int, per_subject: int = 4) -> dict[str, list[str]]:
    # references like "syn3/imp1" are rendered on demand (deterministic)
    return {f"syn{s}": [f"syn{s}/imp{k}" for k in range(per_subject)] for s in range(n_subjects)}


def load_sample(ref) -> bytes:
    if isinstance(ref, str) and ref.startswith("syn"):
        s, k = ref[3:].split("/imp")
        return synthetic.to_png(synthetic.impression(int(s), int(k)))
    return read(ref)


def evaluate_split(base: list[dict], names: list[str], seed: int, configured_thr: float) -> dict:
    """One calibration/evaluation split over already-scored trials."""
    cal_set = split_subjects(names, seed)
    eval_set = set(names) - cal_set
    cal = [r for r in select_in_half(base, cal_set) if r["status"] != "not_evaluated"]
    ev = select_in_half(base, eval_set)
    ev_ok = [r for r in ev if r["status"] != "not_evaluated"]
    out = {"seed": seed, "calibration_subjects": len(cal_set), "evaluation_subjects": len(eval_set),
           "genuine_trials": sum(r["label"] == 1 for r in ev), "impostor_trials": sum(r["label"] == 0 for r in ev),
           "cross_group_genuine": sum(r["label"] == 1 and r.get("cross_group", False) for r in ev), "fit": None}
    try:
        c, s = fit_logistic([r["raw"] for r in cal if r["label"] == 1], [r["raw"] for r in cal if r["label"] == 0])
        out["fit"] = {"center": round(c, 4), "scale": round(s, 4)}
    except ValueError as e:
        out["fit_error"] = str(e)
    thr = out["fit"]["center"] if out["fit"] else configured_thr
    g = np.array([r["raw"] for r in ev_ok if r["label"] == 1])
    i = np.array([r["raw"] for r in ev_ok if r["label"] == 0])
    far, frr = far_frr(g, i, thr)
    cfar, cfrr = far_frr(g, i, configured_thr)
    e, et = eer(g, i)
    out.update(threshold=rate(thr), far=rate(far), frr=rate(frr), eer=rate(e), eer_threshold=rate(et),
               far_at_configured=rate(cfar), frr_at_configured=rate(cfrr), configured_threshold=configured_thr,
               not_evaluable_rate=rate(1 - len(ev_ok) / len(ev)) if ev else None,
               genuine_evaluated=int(len(g)), impostor_evaluated=int(len(i)),
               far_ci=wilson_ci(int(round(far * len(i))), len(i)) if len(i) else None,
               frr_ci=wilson_ci(int(round(frr * len(g))), len(g)) if len(g) else None,
               genuine_mean=rate(g.mean()) if len(g) else None, impostor_mean=rate(i.mean()) if len(i) else None)
    out["_ev"] = ev
    return out


def summarize_degraded(recs: list[dict], thr: float) -> dict:
    ev = [r for r in recs if r["status"] != "not_evaluated"]
    g = np.array([r["raw"] for r in ev if r["label"] == 1])
    i = np.array([r["raw"] for r in ev if r["label"] == 0])
    far, frr = far_frr(g, i, thr)
    return {"far": rate(far), "frr": rate(frr), "not_evaluable_rate": rate(1 - len(ev) / len(recs)) if recs else None,
            "genuine_evaluated": int(len(g)), "impostor_evaluated": int(len(i))}


def run_evaluation(mod, subjects: dict, enroll_k: int, max_gen: int, n_imp: int, seed: int, splits: int,
                   degraded_trials: int, synthetic_data: bool, log=print) -> tuple[dict, dict]:
    """Core of the experiment, separated from argument parsing so tests can call it."""
    rng = seeded(seed)
    enroll_sets, trials = construct_trials(subjects, enroll_k, max_gen, n_imp, rng)
    names = sorted(enroll_sets)
    if len(names) < 8:
        raise SystemExit("not enough subjects with enough samples (need at least 8)")
    templates, failures = {}, []
    for s in names:
        try:
            templates[s] = mod.enroll([load_sample(f) for f in enroll_sets[s]])[0]
        except Exception as e:
            failures.append((s, getattr(e, "code", type(e).__name__)))
    names = sorted(templates)
    trials = [t for t in trials if t.enrolled in templates and (t.probe_subject in templates or t.label == 1)]
    log(f"{mod.modality.value}: {len(names)} enrolled subjects ({len(failures)} could not be enrolled), {len(trials)} trials")

    def score(tr, fn=None):
        data = load_sample(tr.ref)
        if fn:
            data = fn(data)
        t0 = time.perf_counter()
        r = mod.verify(templates[tr.enrolled], data)
        return {"enrolled": tr.enrolled, "probe_subject": tr.probe_subject, "ref": str(tr.ref), "label": tr.label,
                "cross_group": tr.cross_group, "status": r.status.value, "raw": r.raw_score, "quality": r.quality,
                "reason_code": r.reason_code, "latency_ms": (time.perf_counter() - t0) * 1000}

    t_start = time.time()
    base = [score(t) for t in trials]
    log(f"  scored {len(base)} trials in {time.time() - t_start:.0f}s")

    configured = mod.cal.center
    results = [evaluate_split(base, names, seed + k, configured) for k in range(splits)]
    primary = results[0]
    thr = primary["threshold"]
    ev = primary.pop("_ev")
    for r in results[1:]:
        r.pop("_ev")

    lat = np.array([r["latency_ms"] for r in ev]) if ev else np.array([0.0])
    metrics = {k: primary[k] for k in ("genuine_trials", "impostor_trials", "eer", "eer_threshold", "far", "frr",
                                       "far_ci", "frr_ci", "not_evaluable_rate", "genuine_mean", "impostor_mean",
                                       "far_at_configured", "frr_at_configured")}
    metrics.update(
        modality=mod.modality.value, method=mod.method, threshold=thr, configured_threshold=configured,
        calibration_source=mod.cal.source, subjects=len(names), evaluation_subjects=primary["evaluation_subjects"],
        enroll_samples=enroll_k, enrollment_failures=len(failures),
        latency_ms_mean=round(float(lat.mean()), 1), latency_ms_p95=round(float(np.percentile(lat, 95)), 1),
        calibration_fit=primary["fit"],
        trials_scored=len(base), cross_group_genuine_share=rate(
            np.mean([t.cross_group for t in trials if t.label == 1])) if any(t.label == 1 for t in trials) else None,
        splits={"count": splits, "far": mean_sd([r["far"] for r in results]), "frr": mean_sd([r["frr"] for r in results]),
                "eer": mean_sd([r["eer"] for r in results]), "threshold": mean_sd([r["threshold"] for r in results]),
                "not_evaluable_rate": mean_sd([r["not_evaluable_rate"] for r in results]),
                "genuine_trials": mean_sd([r["genuine_trials"] for r in results]),
                "impostor_trials": mean_sd([r["impostor_trials"] for r in results]),
                "per_split": results},
    )

    # degraded inputs: evaluation-half trials of the primary split, re-scored after the transformation
    cal_set = split_subjects(names, seed)
    pool = [t for t in trials if t.enrolled not in cal_set and t.probe_subject not in cal_set]
    rng.shuffle(pool)
    pool = pool[:degraded_trials]
    degraded, degraded_trials_out = [], {}
    for name, fn in DEGRADATIONS[mod.modality.value].items():
        recs = []
        for t in pool:
            try:
                recs.append(score(t, fn))
            except Exception:
                continue    # transformation could not be applied to this sample
        if recs:
            d = summarize_degraded(recs, thr)
            degraded.append({"condition": name, "trials": len(recs), **d})
            degraded_trials_out[name] = recs
            log(f"  degraded '{name}': {d}")
    metrics["degraded"] = degraded

    payload = {"modality": mod.modality.value, "synthetic": synthetic_data, "threshold": thr,
               "calibration": primary["fit"], "eval_trials": ev, "degraded_trials": degraded_trials_out,
               "enrollment_failures": failures}
    metrics["_manifest"] = manifest_hash(trials)
    return metrics, payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modality", required=True, choices=["face", "fingerprint", "voice"])
    ap.add_argument("--root", type=Path)
    ap.add_argument("--synthetic", action="store_true", help="fingerprint only: synthetic prints (NOT real data)")
    ap.add_argument("--max-subjects", type=int, default=100)
    ap.add_argument("--enroll-samples", type=int, default=None)
    ap.add_argument("--genuine-per-subject", type=int, default=3)
    ap.add_argument("--impostors-per-subject", type=int, default=8,
                    help="drawn before the split; about half survive because both owners must share a half")
    ap.add_argument("--splits", type=int, default=10, help="number of random calibration/evaluation splits")
    ap.add_argument("--degraded-trials", type=int, default=120)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--write-calibration", action="store_true",
                    help="fit on ALL scored trials and save to data/calibration.json for the app (not for synthetic data)")
    a = ap.parse_args()

    if a.synthetic and a.write_calibration:
        print("note: --write-calibration is ignored for synthetic data (it must not change the app's thresholds)")
        a.write_calibration = False
    settings = get_settings()
    mod = build_registry(settings).get(a.modality)
    st = mod.status()
    if not st.available:
        raise SystemExit(f"{a.modality} module unavailable: {st.detail}")
    enroll_k = a.enroll_samples or (3 if a.modality == "voice" else 1)
    rng = seeded(a.seed)

    if a.synthetic:
        if a.modality != "fingerprint":
            raise SystemExit("--synthetic is only implemented for fingerprints")
        subjects, source = synthetic_fingerprint_subjects(a.max_subjects), f"synthetic fingerprints ({a.max_subjects} identities x 4 impressions)"
    else:
        if not a.root:
            raise SystemExit("--root is required (or --synthetic for fingerprints)")
        subjects = load_identity_dataset(a.root, AUDIO_EXT if a.modality == "voice" else IMAGE_EXT)
        source = str(a.root)
        eligible = [s for s, f in subjects.items() if len(f) >= enroll_k + 1]
        rng.shuffle(eligible)
        subjects = {s: subjects[s] for s in sorted(eligible[: a.max_subjects])}

    metrics, payload = run_evaluation(mod, subjects, enroll_k, a.genuine_per_subject, a.impostors_per_subject,
                                      a.seed, a.splits, a.degraded_trials, a.synthetic)
    manifest = metrics.pop("_manifest")
    extra = {"manifest_sha256_16": manifest, "data_source": source}
    for f in getattr(mod, "model_files", lambda: [])():
        extra.setdefault("model_files", {})[Path(f).name] = sha256_file(f)
    metrics["reproducibility"] = provenance(sys.argv, a.seed, extra)

    tag = "synthetic" if a.synthetic else "real"
    out = settings.evaluation_dir / f"scores_{a.modality}_{tag}.json"
    save_json(out, {**payload, "source": source, "calibration_source": mod.cal.source})
    run_id = store_run(settings, "modality", a.modality, source, a.synthetic, metrics)
    print(f"saved run {run_id}; scores -> {out}")
    keys = ("genuine_trials", "impostor_trials", "eer", "far", "frr", "far_ci", "frr_ci", "not_evaluable_rate", "latency_ms_mean")
    print({k: metrics[k] for k in keys})
    print("across splits:", {k: metrics["splits"][k] for k in ("far", "frr", "eer")})

    if a.write_calibration:
        # The app gets the logistic fitted on the primary split's CALIBRATION half. The evaluation half
        # played no part in it, so the reported metrics stay honest.
        import json
        fit = payload["calibration"]
        if fit:
            p = settings.data_dir / "calibration.json"
            cur = json.loads(p.read_text()) if p.exists() else {}
            cur[a.modality] = {"center": fit["center"], "scale": fit["scale"],
                               "source": f"{source} (calibration half, seed {a.seed}, trial manifest {manifest})"}
            save_json(p, cur)
            print(f"wrote calibration to {p}")

if __name__ == "__main__":
    main()
