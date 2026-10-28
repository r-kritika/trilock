"""The evaluation code is part of the claim, so it gets tests too."""
import json

import numpy as np
import pytest

from app.biometrics.calibration import DEFAULTS, Calibrator
from app.biometrics.fingerprint import FingerprintModule
from app.evaluation.common import (construct_trials, eer, far_frr, manifest_hash, mean_sd, seeded, select_in_half,
                                   split_subjects, wilson_ci)
from app.evaluation.run_fusion import simulate
from app.evaluation.run_modality import evaluate_split, run_evaluation, synthetic_fingerprint_subjects
from app.services.fusion import FusionConfig


# ---------------- metrics
def test_far_frr_acceptance_is_greater_or_equal():
    g, i = np.array([0.5, 0.8]), np.array([0.5, 0.2])
    far, frr = far_frr(g, i, 0.5)
    assert far == 0.5 and frr == 0.0          # a score exactly at the threshold is accepted


def test_eer_perfect_separation_is_zero():
    e, t = eer(np.array([0.8, 0.9, 1.0]), np.array([0.1, 0.2, 0.3]))
    assert e == 0.0 and 0.3 < t <= 0.8


def test_eer_identical_distributions_is_near_half():
    rng = np.random.default_rng(0)
    e, _ = eer(rng.normal(0, 1, 2000), rng.normal(0, 1, 2000))
    assert 0.45 < e < 0.55


def test_eer_known_small_example():
    # genuine 0.3 0.6 0.7 0.9 ; impostor 0.1 0.2 0.4 0.65. At t=0.6: FAR=1/4, FRR=1/4
    e, t = eer(np.array([0.3, 0.6, 0.7, 0.9]), np.array([0.1, 0.2, 0.4, 0.65]))
    assert e == pytest.approx(0.25) and t == pytest.approx(0.6)


def test_eer_empty_is_nan():
    assert np.isnan(eer(np.array([]), np.array([1.0]))[0])


def test_wilson_interval():
    lo, hi = wilson_ci(0, 100)
    assert lo == 0.0 and 0.03 < hi < 0.05                  # known: about 0.037 for 0/100
    lo, hi = wilson_ci(50, 100)
    assert lo == pytest.approx(0.404, abs=0.005) and hi == pytest.approx(0.596, abs=0.005)
    assert wilson_ci(0, 0) == (None, None)


def test_mean_sd_ignores_missing():
    assert mean_sd([1.0, 3.0, None])["mean"] == 2.0 and mean_sd([])["mean"] is None


# ---------------- trial construction and data separation
def fake_subjects(n=20, per=6, folders=2):
    return {f"s{i}": [f"s{i}/ch{k % folders}/u{k}" for k in range(per)] for i in range(n)}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_enrolled_sample_is_used_as_a_probe_and_impostors_are_other_people(seed):
    subjects = fake_subjects()
    enroll_sets, trials = construct_trials(subjects, 2, 3, 5, seeded(seed))
    for t in trials:
        assert t.ref in subjects[t.probe_subject]
        if t.label == 1:
            assert t.probe_subject == t.enrolled and t.ref not in enroll_sets[t.enrolled]
        else:
            assert t.probe_subject != t.enrolled
    assert all(len(v) == 2 for v in enroll_sets.values())
    assert sum(t.label == 1 for t in trials) == 20 * 3 and sum(t.label == 0 for t in trials) == 20 * 5


def test_genuine_probes_prefer_other_sessions():
    subjects = {f"s{i}": [f"s{i}/chA/u0", f"s{i}/chA/u1", f"s{i}/chB/u2", f"s{i}/chB/u3"] for i in range(10)}
    _, trials = construct_trials(subjects, 1, 2, 1, seeded(1))
    gen = [t for t in trials if t.label == 1]
    assert all(t.cross_group for t in gen)                         # both probes come from chB
    # when only same-session samples exist the flag says so
    _, trials = construct_trials({f"s{i}": [f"s{i}/chA/u{k}" for k in range(3)] for i in range(10)}, 1, 2, 1, seeded(1))
    assert not any(t.cross_group for t in trials if t.label == 1)


def test_subjects_with_too_few_samples_are_dropped():
    subjects = fake_subjects(10, 4)
    subjects["lonely"] = ["lonely/ch0/u0"]
    enroll_sets, trials = construct_trials(subjects, 2, 3, 3, seeded(1))
    assert "lonely" not in enroll_sets and all(t.enrolled != "lonely" and t.probe_subject != "lonely" for t in trials)


def test_construction_is_deterministic():
    a = construct_trials(fake_subjects(), 1, 3, 4, seeded(5))[1]
    b = construct_trials(fake_subjects(), 1, 3, 4, seeded(5))[1]
    c = construct_trials(fake_subjects(), 1, 3, 4, seeded(6))[1]
    assert manifest_hash(a) == manifest_hash(b) != manifest_hash(c)


def test_halves_are_disjoint_and_cross_half_trials_are_dropped():
    names = [f"s{i}" for i in range(20)]
    cal = split_subjects(names, 1)
    assert len(cal) == 10 and cal == split_subjects(names, 1) and cal != split_subjects(names, 2)
    _, trials = construct_trials(fake_subjects(), 1, 3, 6, seeded(1))
    recs = [{"enrolled": t.enrolled, "probe_subject": t.probe_subject, "label": t.label} for t in trials]
    ev = select_in_half(recs, set(names) - cal)
    assert ev and all(r["enrolled"] not in cal and r["probe_subject"] not in cal for r in ev)
    cal_part = select_in_half(recs, cal)
    assert not ({id(r) for r in ev} & {id(r) for r in cal_part})
    assert len(ev) + len(cal_part) < len(recs)             # trials spanning both halves are used by neither


def test_evaluate_split_uses_only_calibration_half_for_the_fit():
    rng = np.random.default_rng(0)
    names = [f"s{i}" for i in range(20)]
    base = []
    for s in names:
        for o in names:
            base.append({"enrolled": s, "probe_subject": o, "label": int(s == o), "status": "match",
                         "raw": float(rng.normal(0.7 if s == o else 0.2, 0.08)), "cross_group": True,
                         "quality": 0.9, "latency_ms": 1, "reason_code": None})
    r = evaluate_split(base, names, 1, 0.45)
    assert r["calibration_subjects"] + r["evaluation_subjects"] == 20
    assert 0.35 < r["fit"]["center"] < 0.55 and r["far"] == 0.0 and r["frr"] == 0.0
    # poison the evaluation half only: the fit must not move
    cal = split_subjects(names, 1)
    for x in base:
        if x["enrolled"] not in cal and x["probe_subject"] not in cal:
            x["raw"] = 99.0 if x["label"] == 0 else -99.0
    r2 = evaluate_split(base, names, 1, 0.45)
    assert r2["fit"] == r["fit"] and r2["far"] == 1.0 and r2["frr"] == 1.0


def test_not_evaluable_trials_are_reported_not_counted_as_errors():
    names = [f"s{i}" for i in range(12)]
    base = []
    for s in names:
        for o in names:
            ok = (hash((s, o)) % 5) != 0
            base.append({"enrolled": s, "probe_subject": o, "label": int(s == o), "status": "match" if ok else "not_evaluated",
                         "raw": (0.8 if s == o else 0.1) if ok else None, "cross_group": True, "quality": 1,
                         "latency_ms": 1, "reason_code": None})
    r = evaluate_split(base, names, 1, 0.45)
    assert r["far"] == 0.0 and r["frr"] == 0.0 and 0 < r["not_evaluable_rate"] < 0.5


# ---------------- end to end on the real fingerprint module + synthetic data
def test_run_evaluation_end_to_end_is_reproducible_and_json_safe():
    mod = FingerprintModule(DEFAULTS["fingerprint"])
    subs = synthetic_fingerprint_subjects(16)
    logs = []
    m1, p1 = run_evaluation(mod, subs, 1, 2, 6, seed=3, splits=3, degraded_trials=6, synthetic_data=True, log=logs.append)
    m2, p2 = run_evaluation(mod, subs, 1, 2, 6, seed=3, splits=3, degraded_trials=6, synthetic_data=True, log=logs.append)
    assert m1["_manifest"] == m2["_manifest"] and m1["far"] == m2["far"] and m1["eer"] == m2["eer"]
    json.dumps(m1, allow_nan=False); json.dumps(p1, allow_nan=False)
    assert m1["splits"]["count"] == 3 and len(m1["splits"]["per_split"]) == 3
    assert m1["eer"] == 0.0 and m1["frr"] == 0.0           # synthetic prints are easy; this checks plumbing only
    assert m1["genuine_trials"] > 0 and m1["impostor_trials"] > 0
    # every stored evaluation trial belongs to the evaluation half only
    cal = split_subjects(sorted({t["enrolled"] for t in p1["eval_trials"]} | set(subs)), 3)
    assert all(t["enrolled"] not in cal and t["probe_subject"] not in cal for t in p1["eval_trials"])


# ---------------- fusion simulation
def make_pool(g_raw, i_raw):
    mk = lambda raw, label: {"label": label, "status": "match", "raw": raw, "quality": 0.9}
    return {"eval_trials": [mk(g_raw + k * 0.001, 1) for k in range(20)] + [mk(i_raw - k * 0.001, 0) for k in range(20)],
            "degraded_trials": {}}


def test_fusion_simulation_same_attempts_and_bypass_behaviour():
    pools = {m: make_pool(0.9, 0.05) for m in ("face", "fingerprint", "voice")}
    cals = {m: Calibrator(0.5, 0.1) for m in pools}
    conds = [("all available modalities", {m: None for m in pools}), ("only face", {"face": None})]
    out = simulate(pools, cals, conds, FusionConfig(), attempts=30, seed=1)
    allc, onlyf = out
    for pol in ("fixed", "risk_aware"):
        assert allc["overall"][pol]["far"] == 0.0 and allc["overall"][pol]["frr"] == 0.0
    # same number of attempts for both policies in every cell
    for c in allc["by_risk"].values():
        assert c["fixed"]["genuine_n"] == c["risk_aware"]["genuine_n"] == 30
    # attacker who beat the only modality: fixed approves, risk-aware stops it above low risk
    assert onlyf["by_risk"]["high"]["fixed"]["bypass"]["face"]["asr"] == 1.0
    assert onlyf["by_risk"]["high"]["risk_aware"]["bypass"]["face"]["asr"] == 0.0
    assert onlyf["by_risk"]["low"]["risk_aware"]["bypass"]["face"]["asr"] == 1.0     # low risk accepts one modality
    assert onlyf["overall"]["risk_aware"]["genuine_additional_rate"] > 0.5            # the usability price
    assert any(p["threshold"] == 0.9 for p in allc["fixed_sweep"])
    # omission attack: attacker submits only the beaten modality. Baseline falls for it above low risk too.
    assert allc["by_risk"]["high"]["fixed"]["omission"]["face"]["asr"] == 1.0
    assert allc["by_risk"]["high"]["fixed_min2"]["omission"]["face"]["asr"] == 0.0
    assert allc["by_risk"]["high"]["risk_aware"]["omission"]["face"]["asr"] == 0.0
    assert allc["by_risk"]["low"]["fixed_min2"]["omission"]["face"]["asr"] == 0.0
    assert allc["by_risk"]["low"]["risk_aware"]["omission"]["face"]["asr"] == 1.0      # low risk accepts one modality


def test_fusion_simulation_is_deterministic():
    pools = {m: make_pool(0.8, 0.2) for m in ("face", "voice")}
    cals = {m: Calibrator(0.5, 0.1) for m in pools}
    conds = [("all available modalities", {m: None for m in pools})]
    a = simulate(pools, cals, conds, FusionConfig(), 20, 4)
    b = simulate(pools, cals, conds, FusionConfig(), 20, 4)
    assert a == b
