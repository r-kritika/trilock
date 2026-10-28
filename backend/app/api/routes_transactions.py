from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..biometrics.registry import ORDER
from ..deps import get_db, read_upload
from ..errors import ApiError
from ..models import Transaction, User
from ..schemas import (AttemptOut, RiskPreviewIn, TransactionCreate, TransactionDetail, TransactionList,
                       TransactionOut)
from ..security import current_user
from ..services import authentication as auth
from ..services.events import log_event
from ..services.risk import RiskInput, assess_risk

router = APIRouter(tags=["transactions"])

SCORE_FIELDS = ("raw_score", "calibrated", "threshold", "details")


def _scrub_results(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        r = dict(r)
        for k in SCORE_FIELDS:
            r[k] = None if k != "details" else {}
        out.append(r)
    return out


def _scrub_outcome(o: dict) -> dict:
    o = dict(o)
    for k in ("fused_score", "approve_threshold", "reject_threshold", "coverage"):
        o[k] = None
    return o


def _attempt_out(a, show_scores: bool) -> dict:
    d = AttemptOut.model_validate(a).model_dump()
    if not show_scores:
        d["modality_results"] = _scrub_results(d["modality_results"])
        d["fixed_outcome"] = _scrub_outcome(d["fixed_outcome"])
        d["risk_aware_outcome"] = _scrub_outcome(d["risk_aware_outcome"])
        for o in (d["fixed_outcome"], d["risk_aware_outcome"]):
            o["explanation"] = "Score details are hidden for this account."
    return d


def _show_scores(request: Request, viewer: User) -> bool:
    return viewer.role == "admin" or request.app.state.settings.expose_scores_to_users


def _out(txn: Transaction, show_scores: bool, detail: bool = False) -> dict:
    d = TransactionOut.model_validate(txn).model_dump()
    d["user_name"] = txn.user.full_name if txn.user else None
    d["attempt_count"] = len(txn.attempts)
    summary = []
    if txn.attempts:
        results = txn.attempts[-1].modality_results
        if not show_scores:
            results = _scrub_results(results)
        summary = [{"modality": r["modality"], "status": r["status"], "calibrated": r["calibrated"],
                    "raw_score": r["raw_score"], "reason": r["reason"]} for r in results]
    d["modality_summary"] = summary
    if detail:
        d["attempts"] = [_attempt_out(a, show_scores) for a in txn.attempts]
    return d


def _txn(db: Session, me: User, txn_id: int) -> Transaction:
    t = db.get(Transaction, txn_id)
    # other people's transactions look exactly like missing ones
    if t is None or (me.role != "admin" and t.user_id != me.id):
        raise ApiError(404, "transaction_not_found", f"Transaction {txn_id} does not exist.")
    return t


@router.post("/risk/assess")
def preview_risk(body: RiskPreviewIn, request: Request, _: User = Depends(current_user)):
    """Stateless risk preview (no user history, nothing stored)."""
    return assess_risk(RiskInput(**body.model_dump()), request.app.state.risk_cfg).to_dict()


@router.post("/transactions", response_model=TransactionDetail, status_code=201)
def create_transaction(body: TransactionCreate, request: Request, me: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    if me.role == "admin":
        raise ApiError(403, "owner_only", "Administrators cannot create transactions for customers.")
    data = body.model_dump()
    data["user_id"] = me.id
    txn = auth.create_transaction(db, me, data, request.app.state.risk_cfg)
    return _out(txn, _show_scores(request, me), detail=True)


@router.get("/transactions", response_model=TransactionList)
def list_transactions(request: Request, me: User = Depends(current_user), db: Session = Depends(get_db),
                      q: str | None = Query(None, max_length=100), decision: str | None = None,
                      risk_category: str | None = None, user_id: int | None = None,
                      limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    query = db.query(Transaction)
    if me.role != "admin":
        query = query.filter(Transaction.user_id == me.id)      # users only ever see their own
    elif user_id:
        query = query.filter(Transaction.user_id == user_id)
    if decision:
        query = query.filter(Transaction.decision == decision)
    if risk_category:
        query = query.filter(Transaction.risk_category == risk_category)
    if q:
        esc = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")   # literal match only
        like = f"%{esc}%"
        conds = [Transaction.recipient_name.ilike(like, escape="\\"), Transaction.recipient_account.ilike(like, escape="\\"),
                 User.full_name.ilike(like, escape="\\")]
        if q.strip().isdigit():
            conds.append(Transaction.id == int(q))
        query = query.join(User).filter(or_(*conds))
    total = query.count()
    rows = query.order_by(Transaction.id.desc()).offset(offset).limit(limit).all()
    show = _show_scores(request, me)
    return {"total": total, "items": [_out(t, show) for t in rows]}


@router.get("/transactions/{txn_id}", response_model=TransactionDetail)
def get_transaction(txn_id: int, request: Request, me: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(_txn(db, me, txn_id), _show_scores(request, me), detail=True)


@router.post("/transactions/{txn_id}/authenticate", response_model=TransactionDetail)
async def authenticate(txn_id: int, request: Request, me: User = Depends(current_user), db: Session = Depends(get_db),
                       face: UploadFile | None = File(None), fingerprint: UploadFile | None = File(None),
                       voice: UploadFile | None = File(None)):
    s = request.app.state
    txn = _txn(db, me, txn_id)
    if txn.user_id != me.id:
        raise ApiError(403, "owner_only", "Only the account owner can authenticate a transaction.")
    samples = {
        "face": await read_upload(face, s.settings.max_image_bytes),
        "fingerprint": await read_upload(fingerprint, s.settings.max_image_bytes),
        "voice": await read_upload(voice, s.settings.max_audio_bytes),
    }
    auth.authenticate(db, txn, samples, s.registry, s.templates, s.fusion_cfg, s.settings)
    db.refresh(txn)
    return _out(txn, _show_scores(request, me), detail=True)


@router.post("/verify/{modality}")
async def verify_single(modality: str, request: Request, file: UploadFile = File(...),
                        me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Run one module on the signed-in user's own reference (no transaction, no fusion).
    Counts toward the same failed-biometric lockout as real authentication."""
    s = request.app.state
    if modality not in ORDER:
        raise ApiError(404, "unknown_modality", f"Unknown modality '{modality}'.")
    if me.role == "admin":
        raise ApiError(403, "owner_only", "Administrators have no biometric references.")
    auth.check_biometric_lockout(db, me.id, s.settings)
    data = await read_upload(file, s.settings.max_audio_bytes if modality == "voice" else s.settings.max_image_bytes)
    res = auth.run_modality(s.registry.get(modality), modality, s.templates.load(me.id, modality), data, db, me.id)
    log_event(db, "verification", me.id, modality=modality, status=res.status.value)
    if res.status.value == "no_match":
        log_event(db, "biometric_failure", me.id, modality=modality, via="verify")
    out = res.to_dict()
    if not _show_scores(request, me):
        out.update(raw_score=None, calibrated=None, threshold=None, details={})
    return out
