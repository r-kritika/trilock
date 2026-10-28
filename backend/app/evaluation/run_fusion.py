"""Compare fixed-threshold and risk-aware fusion on identical attempts.

  python -m app.evaluation.run_fusion [--attempts 1000] [--repeats 5] [--policy-file policy.json]

Input: data/evaluation/scores_<modality>_<real|synthetic>.json written by run_modality (evaluation-half
trials of the primary split, raw scores). Raw scores are mapped to calibrated probabilities with the
logistic fitted on that split's calibration half. The real score file is preferred; the synthetic
one is used only when no real file exists, and the run is then flagged synthetic.

Protocol ("virtual multimodal users": no single dataset here contains all three traits, so a
genuine attempt combines unrelated people's genuine trials; this assumes independent modalities)
  genuine attempt        one genuine trial per modality
  zero-effort impostor   one impostor trial per modality
  single-modality bypass the attacker beats ONE modality (a genuine-like trial, as after a good
                         spoof) and is an impostor on the others. Run once per modality.
  omission attack        the attacker beats ONE modality and submits ONLY that one, leaving the others
                         blank. A policy that averages whatever is present is exposed to this.
Three policies are compared: fixed threshold (baseline A), fixed threshold plus a static "at least 2
modalities" rule (ablation, to see whether risk adaptation adds anything beyond that rule) and
risk-aware (proposed B).
For each risk category the same number of attempts is generated, and BOTH policies score exactly
the same attempts. The overall figures weight the categories by an assumed transaction mix.
That mix and the use of categories are simulated, not measured.

Outcomes: approved / rejected / additional verification. For genuine attempts "rejected" is a false
reject and "additional" is friction. For attacks "approved" is the attack succeeding; "additional" and
"rejected" both stop it (an additional-verification request is a challenge the attacker still has to pass,
which this experiment does not model, so this is optimistic for the policies that use it).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict

from ..biometrics.calibration import Calibrator
from ..biometrics.types import ModalityResult, VerificationStatus
from ..config import get_settings
from ..services.fusion import (fixed_min_modalities_fusion, fixed_threshold_fusion, load_policy_config,
                               risk_aware_fusion)
from .common import mean_sd, provenance, rate, seeded, store_run, wilson_ci

RISK_MIX = {"low": 0.4, "medium": 0.3, "high": 0.2, "critical": 0.1}
MODS = ("face", "fingerprint", "voice")
POLS = {"fixed": fixed_threshold_fusion, "fixed_min2": fixed_min_modalities_fusion, "risk_aware": risk_aware_fusion}
SWEEP = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]


def to_result(modality: str, rec: dict | None, cal: Calibrator) -> ModalityResult:
    if rec is None:
        return ModalityResult.not_evaluated(modality, "eval", "not_provided", "not provided")
    if rec["status"] == "not_evaluated":
        return ModalityResult.not_evaluated(modality, "eval", rec.get("reason_code") or "not_evaluated", "could not be evaluated")
    p = cal(rec["raw"])
    return ModalityResult(modality=modality, status=VerificationStatus.MATCH if p >= 0.5 else VerificationStatus.NO_MATCH,
                          method="eval", raw_score=rec["raw"], calibrated=p, quality=rec["quality"])


def counts(decisions: list[str]) -> dict:
    n = len(decisions)
    f = lambda d: rate(sum(x == d for x in decisions) / n) if n else None
    return {"approved": f("approved"), "rejected": f("rejected"), "additional": f("additional_verification_required"), "n": n}


def load_pools(settings):
    pools, sources, synth = {}, [], False
    for m in MODS:
        for tag in ("real", "synthetic"):
            p = settings.evaluation_dir / f"scores_{m}_{tag}.json"
            if p.exists():
                d = json.loads(p.read_text())
                if not d.get("calibration"):
                    continue
                pools[m] = d
                sources.append(f"{m}: {d['source']}")
                synth |= d["synthetic"]
                break
    return pools, sources, synth


def simulate(pools, cals, conditions, fusion_cfg, attempts, seed):
    """Returns per-condition results. All policies see the same attempts."""
    rng = seeded(seed)
    cats = list(RISK_MIX)
    out = []
    for name, spec in conditions:           # spec: modality -> degradation name (or None)
        def pool(m, label):
            d = pools[m]
            src = d["degraded_trials"].get(spec[m], []) if spec[m] else d["eval_trials"]
            return [r for r in src if r["label"] == label]
        used = list(spec)
        if any(not pool(m, l) for m in used for l in (0, 1)):
            continue
        n_eff = min(len(pool(m, l)) for m in used for l in (0, 1))
        scenarios = {"genuine": {m: 1 for m in used}, "zero_effort": {m: 0 for m in used}}
        for b in used:
            scenarios[f"bypass_{b}"] = {m: (1 if m == b else 0) for m in used}
        if len(used) > 1:
            for b in used:
                scenarios[f"omit_{b}"] = {b: 1}          # only the beaten modality is submitted
        cell = {c: {s: {p: [] for p in POLS} for s in scenarios} for c in cats}
        sweep = {t: {s: [] for s in scenarios} for t in SWEEP} if name.startswith("all") else None
        for c in cats:
            for s, labels in scenarios.items():
                for _ in range(attempts):
                    results = [to_result(m, rng.choice(pool(m, labels[m])) if m in labels else None, cals.get(m)) for m in MODS]
                    for pol, fn in POLS.items():
                        cell[c][s][pol].append(fn(results, c, fusion_cfg).decision.value)
                    if sweep is not None and c == "medium":    # fixed policy ignores risk, one category is enough
                        for t in SWEEP:
                            cfg = copy.deepcopy(fusion_cfg); cfg.fixed_threshold = t
                            sweep[t][s].append(fixed_threshold_fusion(results, c, cfg).decision.value)

        def summarize(getter):
            res = {}
            for pol in POLS:
                g = counts(getter("genuine", pol))
                z = counts(getter("zero_effort", pol))
                byp = {b: counts(getter(f"bypass_{b}", pol)) for b in used}
                worst = max(byp.values(), key=lambda x: x["approved"] or 0)["approved"] if byp else None
                omit = {b: counts(getter(f"omit_{b}", pol)) for b in used} if len(used) > 1 else {}
                worst_omit = max((v["approved"] or 0) for v in omit.values()) if omit else None
                far_k = int(round((z["approved"] or 0) * n_eff)); frr_k = int(round((g["rejected"] or 0) * n_eff))
                res[pol] = {"far": z["approved"], "frr": g["rejected"], "genuine_approved": g["approved"],
                            "genuine_additional_rate": g["additional"], "impostor_additional_rate": z["additional"],
                            "impostor_rejected_rate": z["rejected"],
                            "bypass": {b: {"asr": v["approved"], "stopped_by_extra_verification": v["additional"]} for b, v in byp.items()},
                            "worst_bypass_asr": worst,
                            "omission": {b: {"asr": v["approved"]} for b, v in omit.items()}, "worst_omission_asr": worst_omit,
                            "far_ci": wilson_ci(far_k, n_eff), "frr_ci": wilson_ci(frr_k, n_eff),
                            "genuine_n": g["n"], "impostor_n": z["n"]}
            return res

        by_risk = {c: summarize(lambda s, pol, c=c: cell[c][s][pol]) for c in cats}
        # overall: weight categories by the assumed mix (each category has the same number of attempts)
        overall = {}
        for pol in POLS:
            def w(key, sub=None, grp="bypass"):
                tot = 0.0
                for c in cats:
                    v = by_risk[c][pol]
                    v = v[key] if sub is None else v[key][sub]["asr"]
                    tot += RISK_MIX[c] * (v or 0)
                return rate(tot)
            overall[pol] = {k: w(k) for k in ("far", "frr", "genuine_approved", "genuine_additional_rate", "impostor_additional_rate")}
            overall[pol]["bypass_asr"] = {b: w("bypass", b) for b in used}
            overall[pol]["worst_bypass_asr"] = max(overall[pol]["bypass_asr"].values()) if used else None
            overall[pol]["omission_asr"] = {b: w("omission", b) for b in used} if len(used) > 1 else {}
            overall[pol]["worst_omission_asr"] = max(overall[pol]["omission_asr"].values()) if overall[pol]["omission_asr"] else None
            ci_far = wilson_ci(int(round(overall[pol]["far"] * n_eff)), n_eff)
            ci_frr = wilson_ci(int(round(overall[pol]["frr"] * n_eff)), n_eff)
            overall[pol]["far_ci"], overall[pol]["frr_ci"] = ci_far, ci_frr
        entry = {"name": name, "modalities": used, "pool_size_min": n_eff, "overall": overall, "by_risk": by_risk}
        if sweep:
            entry["fixed_sweep"] = [{
                "threshold": t,
                "genuine_not_approved": rate(1 - counts(sweep[t]["genuine"])["approved"]),
                "far": counts(sweep[t]["zero_effort"])["approved"],
                "worst_bypass_asr": max(counts(sweep[t][f"bypass_{b}"])["approved"] for b in used),
                "worst_omission_asr": max((counts(sweep[t][f"omit_{b}"])["approved"] for b in used), default=None)
                if len(used) > 1 else None} for t in SWEEP]
        out.append(entry)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--attempts", type=int, default=1000, help="attempts per scenario and risk category")
    ap.add_argument("--repeats", type=int, default=5, help="independent resampling repeats (seed, seed+1, ...)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--policy-file", type=str, default=None, help="JSON overriding fusion/risk settings")
    a = ap.parse_args()
    settings = get_settings()
    _, fusion_cfg = load_policy_config(a.policy_file or settings.policy_file)

    pools, sources, synthetic_used = load_pools(settings)
    if not pools:
        raise SystemExit("no usable score files; run run_modality first")
    cals = {m: Calibrator(d["calibration"]["center"], d["calibration"]["scale"], "primary split fit") for m, d in pools.items()}
    print("modalities:", ", ".join(pools), "| synthetic data used:", synthetic_used)

    first_deg = {m: next(iter(pools[m]["degraded_trials"]), None) for m in pools}
    conditions = [("all available modalities", {m: None for m in pools})]
    if len(pools) > 1:
        conditions += [(f"{m} missing", {k: None for k in pools if k != m}) for m in pools]
        conditions += [(f"only {m}", {m: None}) for m in pools]
    if all(first_deg.values()):
        conditions.append(("all modalities degraded", {m: first_deg[m] for m in pools}))

    runs = [simulate(pools, cals, conditions, fusion_cfg, a.attempts, a.seed + r) for r in range(a.repeats)]
    primary = runs[0]
    for ci, cond in enumerate(primary):
        for pol in POLS:
            reps = [r[ci]["overall"][pol] for r in runs if ci < len(r) and r[ci]["name"] == cond["name"]]
            cond["overall"][pol]["across_repeats"] = {k: mean_sd([x[k] for x in reps]) for k in
                                                       ("far", "frr", "genuine_additional_rate", "worst_bypass_asr", "worst_omission_asr")}
    for cond in primary:
        o = cond["overall"]
        fmt = lambda k: "/".join(str(o[p][k]) for p in POLS)
        print(f"{cond['name']:28s} FAR {fmt('far')}  FRR {fmt('frr')}  genuine->more {fmt('genuine_additional_rate')}  "
              f"worst bypass {fmt('worst_bypass_asr')}  worst omission {fmt('worst_omission_asr')}   (fixed/fixed_min2/risk-aware)")

    pool_sizes = {m: {"genuine": sum(r["label"] == 1 for r in d["eval_trials"]),
                      "impostor": sum(r["label"] == 0 for r in d["eval_trials"])} for m, d in pools.items()}
    metrics = {"attempts_per_cell": a.attempts, "repeats": a.repeats, "risk_mix": RISK_MIX, "sources": sources,
               "pool_sizes": pool_sizes, "calibration_used": {m: asdict(c) for m, c in cals.items()},
               "conditions": primary,
               "fusion_config": {"fixed_threshold": fusion_cfg.fixed_threshold, "weights": fusion_cfg.weights,
                                 "bands": {k: asdict(v) for k, v in fusion_cfg.bands.items()}},
               "reproducibility": provenance(sys.argv, a.seed)}
    rid = store_run(settings, "fusion", "fixed vs risk-aware", "; ".join(sources), synthetic_used, metrics)
    print(f"saved run {rid}")


if __name__ == "__main__":
    main()
