"""Dump the evaluation numbers the slides use from the stored runs, so no figure is typed by hand.
Run from the backend folder:  .venv/bin/python ../docs/presentation/export_deck_data.py"""
import json
import sqlite3
import sys
from pathlib import Path

db = Path("data/trilock.db")
if not db.exists():
    sys.exit("run this from the backend folder")
con = sqlite3.connect(db)
out = {}
for rid, kind, syn, metrics in con.execute("select id, kind, is_synthetic, metrics from evaluation_runs order by id"):
    m = json.loads(metrics)
    if kind == "modality":
        out[f"mod_{m['modality']}"] = {**{k: m[k] for k in ("genuine_trials", "impostor_trials", "eer", "far", "far_ci", "frr", "frr_ci",
                                                           "not_evaluable_rate", "latency_ms_mean", "latency_ms_p95", "evaluation_subjects",
                                                           "splits", "degraded")}, "synthetic": bool(syn)}
    elif kind == "fusion":
        out["fusion"], out["fusion_run_id"] = m, rid          # the newest run wins
    elif kind == "liveness":
        out["liveness"] = m
Path(__file__).with_name("deck_data.json").write_text(json.dumps(out, indent=1, default=str))
print("wrote deck_data.json from runs:", sorted(k for k in out))
