from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import EvaluationRun, User
from ..security import current_user
from ..services import stats
from ..services.demo_scenarios import run_scenarios

router = APIRouter(tags=["system"])
VERSION = "0.2.0"


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    """Public and deliberately minimal. Module details need a login (see /dashboard/stats)."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": VERSION, "database": db_ok}


@router.get("/dashboard/stats")
def dashboard_stats(request: Request, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Administrators see everything; everyone else sees only their own transactions."""
    return stats.dashboard(db, request.app.state.registry, None if me.role == "admin" else me.id)


@router.get("/policy")
def policy(request: Request, _: User = Depends(current_user)):
    """The risk rules and fusion thresholds currently in force (defaults plus any policy file)."""
    s = request.app.state
    return {"active_policy": s.settings.active_policy, "max_auth_attempts": s.settings.max_auth_attempts,
            "risk": asdict(s.risk_cfg), "fusion": asdict(s.fusion_cfg)}


@router.get("/evaluation/runs")
def evaluation_runs(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Persisted results of evaluation CLI runs. Empty until someone runs an evaluation."""
    rows = db.query(EvaluationRun).order_by(EvaluationRun.id.desc()).all()
    return [{"id": r.id, "kind": r.kind, "name": r.name, "data_source": r.data_source,
             "is_synthetic": r.is_synthetic, "metrics": r.metrics, "created_at": r.created_at} for r in rows]


@router.get("/evaluation/policy-demo")
def policy_demo(request: Request, _: User = Depends(current_user)):
    """Hand-written scenarios, run through the real fusion code. ILLUSTRATIVE, not measurements."""
    s = request.app.state
    return {"illustrative": True,
            "note": "Hand-written module scores run through the real fusion code. Not experimental data.",
            "scenarios": run_scenarios(s.fusion_cfg)}
