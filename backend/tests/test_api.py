"""End-to-end API tests using fake biometric modules (see tests/fakes.py) and a throwaway DB."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import PW, auth, enroll, enroll_all, login, make_admin, make_txn, make_user
from tests.fakes import fake_registry


def test_health_is_public_and_minimal(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] is True
    assert "modules" not in r.json()
    make_user(client)
    mods = client.get("/api/dashboard/stats").json()["modules"]
    assert set(mods) == {"face", "fingerprint", "voice"}


def test_user_creation_validation_and_duplicates(client):
    u = make_user(client)
    assert u["account_number"].startswith("TL") and [e["state"] for e in u["enrollments"]] == ["not_enrolled"] * 3
    dup = {"full_name": "Ada Test", "email": "ADA@example.com", "password": PW}
    assert client.post("/api/auth/register", json=dup).status_code == 409
    r = client.post("/api/auth/register", json={"full_name": "x", "email": "nope", "password": PW})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert client.get("/api/users/999").status_code == 404


def test_persistence_across_restart(settings):
    with TestClient(create_app(settings, fake_registry())) as c1:
        u = make_user(c1)
        enroll_all(c1, u["id"])
        t = make_txn(c1, amount=250)
        token = c1.headers["Authorization"]
    with TestClient(create_app(settings, fake_registry())) as c2:
        c2.headers["Authorization"] = token                 # the session itself survived the restart
        me = c2.get("/api/auth/me").json()
        assert all(e["state"] == "enrolled" for e in me["enrollments"])
        assert c2.get(f"/api/transactions/{t['id']}").json()["amount"] == 250
        # templates survived too: a genuine sample still verifies
        r = c2.post("/api/verify/face", files={"file": ("f", b"match")})
        assert r.json()["status"] == "match"


def test_enrollment_states_and_failure_is_not_enrolled(client):
    u = make_user(client)
    r = enroll(client, u["id"], "face", b"bad")
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_face"
    states = {e["modality"]: e["state"] for e in client.get(f"/api/users/{u['id']}/enrollments").json()}
    assert states["face"] == "not_enrolled"           # a failed enrollment must not count
    assert enroll(client, u["id"], "iris", b"x").status_code == 404
    enroll(client, u["id"], "face")
    assert client.request("DELETE", f"/api/users/{u['id']}/enrollments/face", data={"password": PW}).status_code == 200
    assert client.request("DELETE", f"/api/users/{u['id']}/enrollments/face", data={"password": PW}).status_code == 404


def test_transaction_creation_computes_risk(client):
    u = make_user(client)
    low = make_txn(client, None, amount=40)
    high = make_txn(client, None, amount=15000, recipient_is_new=True, is_international=True)
    assert low["risk_category"] == "low" and low["decision"] == "pending"
    assert high["risk_category"] in ("high", "critical") and high["risk_score"] > low["risk_score"]
    assert {f["name"] for f in high["risk_factors"]} >= {"amount", "new_recipient", "international"}


@pytest.mark.parametrize("body,field", [({"amount": 0}, "amount"), ({"amount": -5}, "amount"),
                                         ({"recipient_name": ""}, "recipient_name"),
                                         ({"transaction_type": "crypto"}, "transaction_type")])
def test_transaction_validation(client, body, field):
    u = make_user(client)
    base = {"amount": 10, "recipient_name": "B", "recipient_account": "ACC1"}
    r = client.post("/api/transactions", json={**base, **body})
    assert r.status_code == 422 and field in str(r.json()["error"]["fields"])


def test_risk_preview(client):
    make_user(client)
    r = client.post("/api/risk/assess", json={"amount": 20000, "recipient_is_new": True})
    assert r.status_code == 200 and r.json()["category"] in ("high", "critical")


def test_low_risk_single_modality_approved(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, None, amount=50)
    r = auth(client, t["id"], face=b"match")
    assert r.status_code == 200
    d = r.json()
    assert d["decision"] == "approved" and d["attempts"][0]["active_policy"] == "risk_aware"
    assert d["decision_reason"] == d["attempts"][0]["explanation"]
    # both policies were computed and stored
    a = d["attempts"][0]
    assert a["fixed_outcome"]["policy"] == "fixed" and a["risk_aware_outcome"]["policy"] == "risk_aware"
    # an approved transaction is closed
    assert auth(client, t["id"], face=b"match").status_code == 409


def test_high_risk_single_modality_requests_more_then_approves(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, None, amount=12000, recipient_is_new=True)
    assert t["risk_category"] in ("high", "critical")
    first = auth(client, t["id"], face=b"match").json()
    assert first["decision"] == "additional_verification_required"
    assert first["attempts"][0]["fixed_outcome"]["decision"] == "approved"      # baseline is more permissive
    second = auth(client, t["id"], face=b"match", fingerprint=b"match", voice=b"match").json()
    assert second["decision"] == "approved" and second["attempt_count"] == 2


def test_impostor_rejected(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, None, amount=500)
    d = auth(client, t["id"], face=b"nomatch", fingerprint=b"nomatch", voice=b"nomatch").json()
    assert d["decision"] == "rejected"
    assert client.get("/api/dashboard/stats").json()["suspicious"][0]["id"] == t["id"]


def test_missing_enrollment_is_not_a_match(client):
    u = make_user(client)
    enroll(client, u["id"], "face")
    t = make_txn(client, None, amount=50)
    d = auth(client, t["id"], face=b"match", voice=b"match").json()
    res = {r["modality"]: r for r in d["attempts"][0]["modality_results"]}
    assert res["voice"]["status"] == "not_evaluated" and res["voice"]["reason_code"] == "not_enrolled"
    assert res["voice"]["calibrated"] is None
    assert res["fingerprint"]["reason_code"] == "not_provided"


def test_model_crash_and_bad_input_do_not_approve(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, None, amount=50)
    d = auth(client, t["id"], face=b"crash", voice=b"bad").json()
    assert d["decision"] == "additional_verification_required"
    res = {r["modality"]: r for r in d["attempts"][0]["modality_results"]}
    assert res["face"]["reason_code"] == "inference_failed" and res["voice"]["status"] == "not_evaluated"


def test_no_samples_at_all(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, None, amount=50)
    assert auth(client, t["id"]).json()["decision"] == "additional_verification_required"


def test_attempt_limit_locks_transaction_as_rejected(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, None, amount=50)
    decisions = [auth(client, t["id"], face=b"bad").json()["decision"] for _ in range(3)]
    assert decisions == ["additional_verification_required"] * 2 + ["rejected"]
    assert auth(client, t["id"], face=b"match").status_code == 409


def test_unknown_transaction_and_standalone_verify_errors(client):
    u = make_user(client)
    assert client.get("/api/transactions/12345").json()["error"]["code"] == "transaction_not_found"
    assert auth(client, 12345, face=b"match").status_code == 404
    assert client.post("/api/verify/iris", files={"file": ("f", b"match")}).status_code == 404
    r = client.post("/api/verify/face", files={"file": ("f", b"match")})
    assert r.json()["status"] == "not_evaluated" and r.json()["reason_code"] == "not_enrolled"


def test_oversized_upload_rejected(settings):
    settings.max_image_bytes = 10
    with TestClient(create_app(settings, fake_registry())) as c:
        u = make_user(c)
        r = enroll(c, u["id"], "face", b"x" * 50)
        assert r.status_code == 413


def test_history_filters_and_search(client):
    u = make_user(client); enroll_all(client, u["id"])
    a = make_txn(client, None, amount=50, recipient_name="Alice Shop")
    b = make_txn(client, None, amount=20000, recipient_name="Zed Corp", recipient_is_new=True)
    auth(client, a["id"], face=b"match")
    auth(client, b["id"], face=b"match")
    allr = client.get("/api/transactions").json()
    assert allr["total"] == 2 and allr["items"][0]["id"] == b["id"]
    assert client.get("/api/transactions", params={"decision": "approved"}).json()["total"] == 1
    assert client.get("/api/transactions", params={"decision": "additional_verification_required"}).json()["items"][0]["id"] == b["id"]
    assert client.get("/api/transactions", params={"q": "zed"}).json()["total"] == 1
    assert a["id"] in [t["id"] for t in client.get("/api/transactions", params={"q": str(a["id"])}).json()["items"]]
    assert client.get("/api/transactions", params={"risk_category": "low"}).json()["total"] == 1
    assert client.get("/api/transactions", params={"limit": 0}).status_code == 422
    item = allr["items"][0]
    assert item["modality_summary"][0]["modality"] == "face" and item["user_name"] == "Ada Test"


def test_dashboard_empty_then_counts(client):
    u = make_user(client)
    s = client.get("/api/dashboard/stats").json()
    assert s["total_transactions"] == 0 and s["recent_transactions"] == [] and s["attempts"]["total"] == 0
    assert s["mean_attempt_latency_ms"] is None
    enroll_all(client, u["id"])
    t1 = make_txn(client, None, amount=50); auth(client, t1["id"], face=b"match")
    t2 = make_txn(client, None, amount=50); auth(client, t2["id"], face=b"nomatch", voice=b"nomatch")
    t3 = make_txn(client, None, amount=15000, recipient_is_new=True); auth(client, t3["id"], face=b"match")
    make_txn(client, None, amount=10)
    s = client.get("/api/dashboard/stats").json()
    assert (s["total_transactions"], s["approved"], s["rejected"], s["additional_verification"], s["pending"]) == (4, 1, 1, 1, 1)
    assert sum(s["risk_distribution"].values()) == 4
    assert s["attempts"] == {"total": 3, "approved": 1, "rejected": 1, "additional": 1}
    assert s["modality_outcomes"]["face"] == {"match": 2, "no_match": 1, "not_evaluated": 0}


def test_evaluation_endpoints(client):
    make_user(client)
    assert client.get("/api/evaluation/runs").json() == []        # empty until a run is saved
    demo = client.get("/api/evaluation/policy-demo").json()
    assert demo["illustrative"] is True and len(demo["scenarios"]) >= 5
    d = {s["name"]: s for s in demo["scenarios"]}
    s = d["Large new-payee transfer, face only"]
    assert s["fixed"]["decision"] == "approved" and s["risk_aware"]["decision"] == "additional_verification_required"


def test_fixed_policy_can_be_made_active(settings):
    settings.active_policy = "fixed"
    with TestClient(create_app(settings, fake_registry())) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, u["id"], amount=12000, recipient_is_new=True)
        assert auth(c, t["id"], face=b"match").json()["decision"] == "approved"


def test_policy_file_changes_real_decisions_and_is_visible(settings, tmp_path):
    """Thresholds are configuration: a stricter file must change the outcome of the same input."""
    pf = tmp_path / "policy.json"
    pf.write_text('{"fusion": {"bands": {"low": {"approve": 0.99}}}}')       # fake modules return 0.95
    settings.policy_file = pf
    with TestClient(create_app(settings, fake_registry())) as c:
        u = make_user(c); enroll_all(c, u["id"])
        assert c.get("/api/policy").json()["fusion"]["bands"]["low"]["approve"] == 0.99
        t = make_txn(c, amount=50)
        d = auth(c, t["id"], face=b"match").json()
        assert d["decision"] == "additional_verification_required"            # 0.95 < 0.99, default policy would approve
