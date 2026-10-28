"""Build a Markdown report and PNG plots from stored evaluation runs and score files.

  python -m app.evaluation.report [--out reports]

Every number comes from the database (evaluation_runs) or data/evaluation/*.json; nothing is typed in.
Needs matplotlib (requirements-eval.txt).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..config import get_settings
from ..database import make_engine, make_session_factory
from ..models import EvaluationRun


def pc(x, d=2):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def ci(c):
    return "" if not c or c[0] is None else f" ({pc(c[0], 1)} to {pc(c[1], 1)})"


def ms(o, d=2):
    return "n/a" if not o or o.get("mean") is None else f"{pc(o['mean'], d)} ± {pc(o['sd'], d)}"


def latest(runs, kind):
    seen, out = set(), []
    for r in runs:
        key = (r.kind, r.metrics.get("modality"), r.is_synthetic)
        if r.kind == kind and key not in seen:
            seen.add(key)
            out.append(r)
    return out


def plot_modality(plt, score_file: Path, out: Path, title: str, thr):
    d = json.loads(score_file.read_text())
    ev = [t for t in d["eval_trials"] if t["status"] != "not_evaluated"]
    g = np.array([t["raw"] for t in ev if t["label"] == 1])
    i = np.array([t["raw"] for t in ev if t["label"] == 0])
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    bins = np.linspace(min(g.min(), i.min()), max(g.max(), i.max()), 40)
    ax[0].hist(i, bins, alpha=.7, label=f"impostor (n={len(i)})", color="#c4731a")
    ax[0].hist(g, bins, alpha=.7, label=f"genuine (n={len(g)})", color="#3b6fb0")
    if thr is not None:
        ax[0].axvline(thr, color="k", ls="--", lw=1, label=f"threshold {thr:.3g}")
    ax[0].set_xlabel("raw score"); ax[0].set_ylabel("trials"); ax[0].set_title(f"{title}: score distributions"); ax[0].legend(fontsize=8)
    ts = np.unique(np.concatenate([g, i]))
    far = np.array([(i >= t).mean() for t in ts]); frr = np.array([(g < t).mean() for t in ts])
    ax[1].plot(np.clip(far, 1e-4, 1), np.clip(frr, 1e-4, 1), color="#3b6fb0")
    ax[1].plot([1e-4, 1], [1e-4, 1], color="gray", lw=.8, ls=":")
    ax[1].set_xscale("log"); ax[1].set_yscale("log"); ax[1].set_xlabel("FAR"); ax[1].set_ylabel("FRR")
    ax[1].set_title("DET curve (0 plotted as 0.01%)")
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)


POL_STYLE = {"fixed": ("#5b9bd5", "fixed"), "fixed_min2": ("#8c8c8c", "fixed + min 2 modalities"), "risk_aware": ("#a3243a", "risk-aware")}
PANELS = [("far", "Impostor approved (zero effort)"), ("worst_bypass_asr", "Worst single-modality bypass success"),
          ("worst_omission_asr", "Worst omission-attack success"), ("genuine_additional_rate", "Genuine users asked for more verification")]


def plot_fusion(plt, run, out_dir: Path):
    conds = run.metrics["conditions"]
    labels = [c["name"] for c in conds]
    x = np.arange(len(conds)); w = .27
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for ax, (key, title) in zip(axes.ravel(), PANELS):
        for k, pol in enumerate(POL_STYLE):
            color, label = POL_STYLE[pol]
            ax.bar(x + (k - 1) * w, [100 * (c["overall"][pol].get(key) or 0) for c in conds], w, label=label, color=color)
        ax.set_xticks(x); ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8); ax.set_ylabel("%"); ax.set_title(title, fontsize=10)
    axes[0, 0].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out_dir / "fusion_conditions.png", dpi=130); plt.close(fig)

    c = conds[0]
    if "fixed_sweep" in c:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        for ax, (key, title) in zip(axes, [("worst_bypass_asr", "worst single-modality bypass"), ("worst_omission_asr", "worst omission attack")]):
            xs = [100 * p["genuine_not_approved"] for p in c["fixed_sweep"]]
            ys = [100 * (p[key] or 0) for p in c["fixed_sweep"]]
            ax.plot(xs, ys, "o-", color=POL_STYLE["fixed"][0], label="fixed threshold sweep")
            for p, a_, b_ in zip(c["fixed_sweep"], xs, ys):
                ax.annotate(f"{p['threshold']:g}", (a_, b_), fontsize=7, xytext=(3, 3), textcoords="offset points")
            for pol in ("fixed_min2", "risk_aware"):
                o = c["overall"][pol]
                ax.plot(100 * ((o["frr"] or 0) + (o["genuine_additional_rate"] or 0)), 100 * (o[key] or 0), "D", ms=9,
                        color=POL_STYLE[pol][0], label=POL_STYLE[pol][1])
            ax.set_xlabel("genuine users not approved (%)"); ax.set_ylabel(f"{title} success (%)"); ax.set_title(title, fontsize=10); ax.legend(fontsize=8)
        fig.suptitle(f"Security versus friction, {c['name']}", fontsize=11)
        fig.tight_layout(); fig.savefig(out_dir / "fusion_tradeoff.png", dpi=130); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("reports"))
    a = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = get_settings()
    with make_session_factory(make_engine(s.db_url))() as db:
        runs = db.query(EvaluationRun).order_by(EvaluationRun.id.desc()).all()
    if not runs:
        raise SystemExit("no evaluation runs stored; run run_modality / run_fusion first")
    a.out.mkdir(parents=True, exist_ok=True)

    L = ["# TriLock evaluation report", "", "Generated by `python -m app.evaluation.report` from the stored runs. Do not edit by hand.", ""]
    mods = latest(runs, "modality")
    L += ["## Individual modules", "",
          "| Module | Data | Subjects (eval half) | Genuine / impostor trials | Threshold | EER | FAR (95% CI) | FRR (95% CI) | FAR over splits | FRR over splits | Not evaluable | Mean / p95 latency (ms) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mods:
        m = r.metrics
        L.append(f"| {m['modality']} | {'SYNTHETIC' if r.is_synthetic else 'real'}: {r.data_source} | {m['evaluation_subjects']} | "
                 f"{m['genuine_trials']} / {m['impostor_trials']} | {m['threshold']} | {pc(m['eer'])} | {pc(m['far'])}{ci(m['far_ci'])} | "
                 f"{pc(m['frr'])}{ci(m['frr_ci'])} | {ms(m['splits']['far'])} | {ms(m['splits']['frr'])} | {pc(m['not_evaluable_rate'], 1)} | "
                 f"{m['latency_ms_mean']} / {m['latency_ms_p95']} |")
    L += ["", "Thresholds are fitted on a calibration half of the subjects that is disjoint from the evaluation half. "
          "Intervals are Wilson intervals that assume independent trials; trials reuse the same subjects so they are optimistic. "
          f"'Over splits' is the mean ± sd of {mods[0].metrics['splits']['count']} random calibration/evaluation splits.", ""]
    for r in mods:
        m = r.metrics
        tag = "synthetic" if r.is_synthetic else "real"
        sf = s.evaluation_dir / f"scores_{m['modality']}_{tag}.json"
        if sf.exists():
            png = f"scores_{m['modality']}_{tag}.png"
            plot_modality(plt, sf, a.out / png, f"{m['modality']} ({tag})", m["threshold"])
            L += [f"![{m['modality']} scores]({png})", ""]
        L += [f"Run details for {m['modality']}: enrolled subjects {m['subjects']} (enrollment failures {m['enrollment_failures']}), "
              f"{m['trials_scored']} trials scored, cross-session share of genuine probes {pc(m['cross_group_genuine_share'], 0)}, "
              f"trial manifest `{m['reproducibility'].get('manifest_sha256_16')}`, seed {m['reproducibility']['seed']}.", ""]

    L += ["## Degraded inputs (single module)", "", "| Module | Condition | Trials | FAR | FRR | Not evaluable |", "|---|---|---|---|---|---|"]
    for r in mods:
        for d in r.metrics.get("degraded", []):
            L.append(f"| {r.metrics['modality']}{' (synthetic)' if r.is_synthetic else ''} | {d['condition']} | {d['trials']} | "
                     f"{pc(d['far'])} | {pc(d['frr'])} | {pc(d['not_evaluable_rate'], 1)} |")
    L.append("")

    fus = latest(runs, "fusion")
    if fus:
        r = fus[0]; m = r.metrics
        plot_fusion(plt, r, a.out)
        L += ["## Fixed-threshold vs risk-aware fusion", "",
              f"Data: {'**includes SYNTHETIC scores**' if r.is_synthetic else 'real scores'}; sources: {'; '.join(m['sources'])}.",
              f"{m['attempts_per_cell']} attempts per scenario and risk level, {m['repeats']} repeats. Score pools (evaluation half): "
              + ", ".join(f"{k} {v['genuine']} genuine / {v['impostor']} impostor" for k, v in m["pool_sizes"].items()) + ".",
              f"Assumed risk mix: {m['risk_mix']}. All policies are scored on identical attempts.", "",
              "| Condition | Policy | FAR (zero effort) | FRR | Genuine asked for more | Worst bypass | Worst omission attack |", "|---|---|---|---|---|---|---|"]
        for c in m["conditions"]:
            for pol, (_, label) in POL_STYLE.items():
                o = c["overall"][pol]
                L.append(f"| {c['name']} | {label} | {pc(o['far'])}{ci(o['far_ci'])} | {pc(o['frr'])}{ci(o['frr_ci'])} | "
                         f"{pc(o['genuine_additional_rate'], 1)} | {pc(o['worst_bypass_asr'], 1)} | {pc(o.get('worst_omission_asr'), 1)} |")
        L += ["", "![conditions](fusion_conditions.png)", ""]
        if (a.out / "fusion_tradeoff.png").exists():
            L += ["![tradeoff](fusion_tradeoff.png)", ""]
        L += ["### Per risk level, all available modalities", "", "| Risk | Policy | FAR | FRR | Genuine asked for more | Worst bypass | Worst omission attack |", "|---|---|---|---|---|---|---|"]
        for cat, v in m["conditions"][0]["by_risk"].items():
            for pol, (_, label) in POL_STYLE.items():
                o = v[pol]
                L.append(f"| {cat} | {label} | {pc(o['far'])} | {pc(o['frr'])} | {pc(o['genuine_additional_rate'], 1)} | "
                         f"{pc(o['worst_bypass_asr'], 1)} | {pc(o.get('worst_omission_asr'), 1)} |")
        L += ["", "Decision thresholds used:", "", "```json", json.dumps(m["fusion_config"], indent=1), "```", "",
              f"Reproduce: `{m['reproducibility']['command']}` (seed {m['reproducibility']['seed']}).", ""]
    (a.out / "REPORT.md").write_text("\n".join(L))
    print(f"wrote {a.out / 'REPORT.md'} and plots")


if __name__ == "__main__":
    main()
