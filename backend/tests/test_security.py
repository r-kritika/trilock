"""Authentication, authorization, abuse limits and privacy behaviour."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.biometrics.registry import BiometricRegistry
from app.biometrics.fingerprint import FingerprintModule
from app.biometrics.calibration import DEFAULTS
from app.evaluation.synthetic import impression, to_png
from app.main import create_app
from app.models import Event, Session as Sess, User, utcnow
from tests.conftest import PW, auth, enroll, enroll_all, login, make_admin, make_txn, make_user
from tests.fakes import FakeModule, fake_registry


def new_client(settings):
    return TestClient(create_app(settings, fake_registry()))


@pytest.fixture
def two_users(client):
    """Returns (client, alice, bob, alice_headers, bob_headers). Alice has a transaction."""
    alice = make_user(client, "Alice A", "alice@example.com")
    ha = dict(client.headers)
    enroll_all(client, alice["id"])
    txn = make_txn(client, amount=100)
    client.headers.pop("Authorization")
    bob = make_user(client, "Bob B", "bob@example.com")
    hb = dict(client.headers)
    client.headers.pop("Authorization")
    return client, alice, bob, txn, {"Authorization": ha["authorization"]}, {"Authorization": hb["authorization"]}


PROTECTED = [
    ("GET", "/api/auth/me"), ("GET", "/api/users"), ("GET", "/api/users/1"), ("GET", "/api/users/1/enrollments"),
    ("POST", "/api/users/1/enrollments/face"), ("DELETE", "/api/users/1/enrollments/face"), ("DELETE", "/api/users/1"),
    ("POST", "/api/transactions"), ("GET", "/api/transactions"), ("GET", "/api/transactions/1"),
    ("POST", "/api/transactions/1/authenticate"), ("POST", "/api/verify/face"), ("POST", "/api/risk/assess"),
    ("GET", "/api/dashboard/stats"), ("GET", "/api/policy"), ("GET", "/api/evaluation/runs"),
    ("GET", "/api/evaluation/policy-demo"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_protected_endpoint_requires_login(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


def test_bad_tokens_are_rejected(client):
    for h in ({"Authorization": "Bearer nonsense"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}):
        assert client.get("/api/auth/me", headers=h).status_code == 401


def test_logout_revokes_token(client):
    make_user(client)
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_rejected(client):
    make_user(client)
    with client.app.state.session_factory() as db:
        db.query(Sess).update({"expires_at": utcnow() - timedelta(minutes=1)})
        db.commit()
    assert client.get("/api/auth/me").json()["error"]["code"] == "session_invalid"


# ---- passwords ----
def test_password_rules_and_storage(client):
    base = {"full_name": "Pat Doe", "email": "pat@example.com"}
    assert client.post("/api/auth/register", json={**base, "password": "short"}).json()["error"]["code"] == "weak_password"
    assert client.post("/api/auth/register", json={**base, "password": "pat@example.com"}).status_code == 422
    r = client.post("/api/auth/register", json={**base, "password": PW})
    assert r.status_code == 201 and "password" not in str(r.json()).lower().replace("password_required", "")
    with client.app.state.session_factory() as db:
        h = db.query(User).filter_by(email="pat@example.com").one().password_hash
    assert h.startswith("scrypt$") and PW not in h


def test_same_password_gets_different_hashes():
    from app.security import hash_password, verify_password
    a, b = hash_password(PW), hash_password(PW)
    assert a != b and verify_password(PW, a) and verify_password(PW, b) and not verify_password("x" * 12, a)
    assert verify_password(PW, None) is False and verify_password(PW, "garbage") is False


def test_login_does_not_reveal_which_part_was_wrong(client):
    make_user(client)
    wrong_pw = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "x" * 12})
    no_user = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_login_lockout_after_repeated_failures(client):
    make_user(client)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "ada@example.com", "password": "x" * 12}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "ada@example.com", "password": PW})   # correct, but locked
    assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"
    with client.app.state.session_factory() as db:
        db.query(User).update({"locked_until": utcnow() - timedelta(seconds=1)})
        db.commit()
    assert client.post("/api/auth/login", json={"email": "ada@example.com", "password": PW}).status_code == 200


def test_registration_can_be_closed(settings):
    settings.allow_registration = False
    with new_client(settings) as c:
        r = c.post("/api/auth/register", json={"full_name": "A B", "email": "a@b.co", "password": PW})
        assert r.status_code == 403 and r.json()["error"]["code"] == "registration_closed"


def test_session_token_not_stored_in_clear(client):
    token = make_user(client) and client.headers["Authorization"].split()[1]
    with client.app.state.session_factory() as db:
        assert all(token not in s.token_hash for s in db.query(Sess))
        assert db.query(Sess).count() == 1


# ---- authorization ----
def test_user_cannot_read_or_use_another_users_data(two_users):
    c, alice, bob, txn, ha, hb = two_users
    assert c.get(f"/api/users/{alice['id']}", headers=hb).status_code == 404
    assert c.get(f"/api/users/{alice['id']}/enrollments", headers=hb).status_code == 404
    assert c.get(f"/api/transactions/{txn['id']}", headers=hb).status_code == 404
    assert c.get("/api/transactions", headers=hb).json()["total"] == 0
    assert c.get("/api/transactions", headers=ha).json()["total"] == 1
    assert auth_as(c, hb, txn["id"], face=b"match").status_code == 404
    assert c.get("/api/users", headers=hb).status_code == 403
    # the real owner is unaffected
    assert auth_as(c, ha, txn["id"], face=b"match").status_code == 200


def auth_as(c, headers, tid, **samples):
    return c.post(f"/api/transactions/{tid}/authenticate", headers=headers,
                  files={k: (f"{k}.bin", v) for k, v in samples.items()})


def test_cannot_enroll_or_delete_for_someone_else(two_users):
    c, alice, bob, txn, ha, hb = two_users
    r = c.post(f"/api/users/{alice['id']}/enrollments/face", headers=hb, files=[("files", ("f", b"match"))], data={"password": PW})
    assert r.status_code == 404
    assert c.request("DELETE", f"/api/users/{alice['id']}/enrollments/face", headers=hb, data={"password": PW}).status_code == 404
    assert c.request("DELETE", f"/api/users/{alice['id']}", headers=hb, data={"password": PW}).status_code == 404
    assert [e["state"] for e in c.get("/api/auth/me", headers=ha).json()["enrollments"]] == ["enrolled"] * 3


def test_client_cannot_pick_the_account_of_a_transaction(two_users):
    c, alice, bob, txn, ha, hb = two_users
    r = c.post("/api/transactions", headers=hb, json={"user_id": alice["id"], "amount": 5, "recipient_name": "X",
                                                      "recipient_account": "ACC1"})
    assert r.status_code == 201
    with c.app.state.session_factory() as db:
        from app.models import Transaction
        assert db.get(Transaction, r.json()["id"]).user_id == bob["id"]


def test_admin_is_read_only_for_customers(two_users):
    c, alice, bob, txn, ha, hb = two_users
    make_admin(c)
    assert c.get("/api/users").status_code == 200 and len(c.get("/api/users").json()) == 3
    assert c.get(f"/api/transactions/{txn['id']}").status_code == 200
    assert c.get("/api/transactions").json()["total"] == 1
    assert auth(c, txn["id"], face=b"match").status_code == 403          # cannot decide for a customer
    assert c.post("/api/transactions", json={"amount": 5, "recipient_name": "X", "recipient_account": "ACC1"}).status_code == 403
    r = c.post(f"/api/users/{alice['id']}/enrollments/face", files=[("files", ("f", b"match"))], data={"password": PW})
    assert r.status_code == 403
    assert c.post("/api/verify/face", files={"file": ("f", b"match")}).status_code == 403


def test_dashboard_is_scoped_to_the_user(two_users):
    c, alice, bob, txn, ha, hb = two_users
    assert c.get("/api/dashboard/stats", headers=ha).json()["total_transactions"] == 1
    sb = c.get("/api/dashboard/stats", headers=hb).json()
    assert sb["total_transactions"] == 0 and sb["scope"] == "user"
    make_admin(c)
    sa = c.get("/api/dashboard/stats").json()
    assert sa["total_transactions"] == 1 and sa["scope"] == "all"


def test_no_route_can_set_a_decision_directly(client):
    """The only code path that closes a transaction is /authenticate."""
    for route in client.app.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if "/transactions" in path:
            assert not (methods & {"PUT", "PATCH", "DELETE"}), path
    make_user(client)
    t = make_txn(client)
    for m in ("PUT", "PATCH", "DELETE"):
        assert client.request(m, f"/api/transactions/{t['id']}", json={"decision": "approved"}).status_code == 405
    assert client.get(f"/api/transactions/{t['id']}").json()["decision"] == "pending"


def test_closed_transaction_cannot_be_reopened_or_reapproved(client):
    u = make_user(client); enroll_all(client, u["id"])
    t = make_txn(client, amount=50)
    assert auth(client, t["id"], face=b"nomatch", voice=b"nomatch").json()["decision"] == "rejected"
    assert auth(client, t["id"], face=b"match", voice=b"match").status_code == 409
    assert client.get(f"/api/transactions/{t['id']}").json()["decision"] == "rejected"


# ---- step-up for biometric changes ----
def test_enrollment_changes_need_the_password(client):
    u = make_user(client)
    for pw in (None, "wrong-password-123"):
        r = client.post(f"/api/users/{u['id']}/enrollments/face", files=[("files", ("f", b"match"))],
                        data={"password": pw} if pw else None)
        assert r.status_code == 403 and r.json()["error"]["code"] == "password_required"
    assert client.get("/api/auth/me").json()["enrollments"][0]["state"] == "not_enrolled"
    assert enroll(client, u["id"], "face").status_code == 200
    r = client.request("DELETE", f"/api/users/{u['id']}/enrollments/face")
    assert r.status_code == 403
    assert client.get("/api/auth/me").json()["enrollments"][0]["state"] == "enrolled"


# ---- abuse limits ----
def test_repeated_biometric_failures_lock_further_tries(client):
    u = make_user(client); enroll_all(client, u["id"])
    codes = []
    for _ in range(7):
        t = make_txn(client, amount=50)
        r = auth(client, t["id"], face=b"nomatch", voice=b"nomatch")
        codes.append(r.status_code)
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    assert client.post("/api/verify/face", files={"file": ("f", b"match")}).status_code == 429   # also blocks the oracle


def test_unevaluable_input_does_not_trigger_lockout(client):
    u = make_user(client); enroll_all(client, u["id"])
    for _ in range(7):
        t = make_txn(client, amount=50)
        assert auth(client, t["id"], face=b"bad").status_code == 200


def test_lockout_is_per_user(client):
    u = make_user(client); enroll_all(client, u["id"])
    for _ in range(5):
        auth(client, make_txn(client, amount=50)["id"], face=b"nomatch", voice=b"nomatch")
    client.headers.pop("Authorization")
    v = make_user(client, "Vic V", "vic@example.com"); enroll_all(client, v["id"])
    assert auth(client, make_txn(client, amount=50)["id"], face=b"match").status_code == 200


# ---- score exposure ----
def test_scores_hidden_from_users_when_configured(settings):
    settings.expose_scores_to_users = False
    with new_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, amount=50)
        d = auth(c, t["id"], face=b"match").json()
        res = {r["modality"]: r for r in d["attempts"][0]["modality_results"]}
        assert res["face"]["status"] == "match" and res["face"]["raw_score"] is None and res["face"]["calibrated"] is None
        assert d["attempts"][0]["risk_aware_outcome"]["fused_score"] is None
        assert d["decision"] == "approved"
        row = c.get("/api/transactions").json()["items"][0]["modality_summary"][0]
        assert row["raw_score"] is None and row["calibrated"] is None
        v = c.post("/api/verify/face", files={"file": ("f", b"match")}).json()
        assert v["status"] == "match" and v["raw_score"] is None
        make_admin(c)
        admin_view = c.get(f"/api/transactions/{t['id']}").json()
        assert admin_view["attempts"][0]["modality_results"][0]["raw_score"] is not None


# ---- privacy ----
def test_raw_biometric_samples_are_never_persisted(settings):
    """Enroll and verify with a real fingerprint module, then look for the image anywhere on disk."""
    reg = BiometricRegistry({"face": FakeModule("face"), "voice": FakeModule("voice"),
                             "fingerprint": FingerprintModule(DEFAULTS["fingerprint"])})
    png = to_png(impression(4, 0))
    probe = to_png(impression(4, 1))
    with TestClient(create_app(settings, reg)) as c:
        u = make_user(c)
        assert c.post(f"/api/users/{u['id']}/enrollments/fingerprint", files=[("files", ("a.png", png))],
                      data={"password": PW}).status_code == 200
        t = make_txn(c, amount=50)
        d = c.post(f"/api/transactions/{t['id']}/authenticate", files={"fingerprint": ("p.png", probe)}).json()
        assert d["attempts"][0]["modality_results"][1]["status"] == "match"
    for f in settings.data_dir.rglob("*"):
        if f.is_file():
            blob = f.read_bytes()
            assert b"\x89PNG" not in blob, f"raw image found in {f}"
            assert png[100:200] not in blob and probe[100:200] not in blob
    assert {f.suffix for f in (settings.data_dir / "templates").iterdir()} == {".tpl"}


def test_templates_are_encrypted_on_disk(client, settings):
    u = make_user(client)
    enroll(client, u["id"], "face")
    raw = next((settings.data_dir / "templates").iterdir()).read_bytes()
    assert not raw.startswith(b"PK") and b"embeddings" not in raw


def test_secrets_and_samples_not_in_event_log(client, caplog):
    caplog.set_level("DEBUG")
    u = make_user(client); enroll_all(client, u["id"])
    client.post("/api/auth/login", json={"email": "ada@example.com", "password": "Wrong-password-xyz"})
    auth(client, make_txn(client, amount=50)["id"], face=b"nomatch", voice=b"nomatch")
    with client.app.state.session_factory() as db:
        dump = " ".join(str(e.detail) + e.kind for e in db.query(Event))
    token = client.headers["Authorization"].split()[1]
    for secret in (PW, "Wrong-password-xyz", token):
        assert secret not in dump
        assert secret not in caplog.text


def test_erase_account_removes_everything(settings):
    with new_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, amount=50); auth(c, t["id"], face=b"match")
        tpl_dir = settings.data_dir / "templates"
        assert len(list(tpl_dir.iterdir())) == 3
        assert c.request("DELETE", f"/api/users/{u['id']}", data={"password": "nope-nope-nope"}).status_code == 403
        assert c.request("DELETE", f"/api/users/{u['id']}", data={"password": PW}).status_code == 204
        assert list(tpl_dir.iterdir()) == []
        with c.app.state.session_factory() as db:
            from app.models import AuthAttempt, Enrollment, Transaction
            assert db.query(User).count() == db.query(Transaction).count() == db.query(AuthAttempt).count() == 0
            assert db.query(Enrollment).count() == db.query(Event).filter_by(user_id=u["id"]).count() == 0
        assert c.get("/api/auth/me").status_code == 401


def test_retention_purge(client):
    from app.services.privacy import purge_old
    u = make_user(client); enroll_all(client, u["id"])
    auth(client, make_txn(client, amount=50)["id"], face=b"match")
    with client.app.state.session_factory() as db:
        assert purge_old(db, days=30) == {"events": 0, "attempts": 0, "sessions": 0}
        db.query(Event).update({"created_at": utcnow() - timedelta(days=60)})
        from app.models import AuthAttempt
        db.query(AuthAttempt).update({"created_at": utcnow() - timedelta(days=60)})
        db.commit()
        out = purge_old(db, days=30)
        assert out["events"] > 0 and out["attempts"] == 1


def test_old_database_gets_new_columns(tmp_path):
    """A database created before authentication existed must open and keep its rows."""
    import sqlite3
    from app.config import Settings
    d = tmp_path / "data"; d.mkdir()
    con = sqlite3.connect(d / "trilock.db")
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name VARCHAR(120), email VARCHAR(200) UNIQUE, "
                "account_number VARCHAR(32) UNIQUE, created_at DATETIME)")
    con.execute("INSERT INTO users VALUES (1, 'Old User', 'old@example.com', 'TLOLD', '2026-01-01')")
    con.commit(); con.close()
    s = Settings(data_dir=d, models_dir=tmp_path / "m", _env_file=None)
    with TestClient(create_app(s, fake_registry())) as c:
        with c.app.state.session_factory() as db:
            u = db.query(User).one()
            assert u.full_name == "Old User" and u.role == "user" and u.password_hash is None
        # a legacy account without a password cannot sign in
        assert c.post("/api/auth/login", json={"email": "old@example.com", "password": PW}).status_code == 401


def test_search_wildcards_are_literal(client):
    make_user(client)
    make_txn(client, recipient_name="Alice Shop")
    make_txn(client, recipient_name="50% off_sale")
    assert client.get("/api/transactions", params={"q": "%"}).json()["total"] == 1       # only the name containing a real %
    assert client.get("/api/transactions", params={"q": "_"}).json()["total"] == 1
    assert client.get("/api/transactions", params={"q": "x" * 101}).status_code == 422   # length-capped
