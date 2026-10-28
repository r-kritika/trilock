import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import fake_registry

PW = "correct-horse-battery"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", models_dir=tmp_path / "models", _env_file=None)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, fake_registry())) as c:
        yield c


def login(client, email, password=PW):
    """Sign in and make this client send the token from now on. Returns the login JSON."""
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return r.json()


def make_user(client, name="Ada Test", email="ada@example.com"):
    """Register, sign in (the client now acts as this user) and return the user dict."""
    r = client.post("/api/auth/register", json={"full_name": name, "email": email, "password": PW})
    assert r.status_code == 201, r.text
    return login(client, email)["user"]


def make_admin(client, email="boss@example.com"):
    """Register a normal account, promote it directly in the database, sign in as it."""
    client.post("/api/auth/register", json={"full_name": "Boss Admin", "email": email, "password": PW})
    from app.models import User
    with client.app.state.session_factory() as db:
        db.query(User).filter_by(email=email).update({"role": "admin"})
        db.commit()
    return login(client, email)["user"]


def enroll(client, uid, modality, sample=b"match", password=PW):
    return client.post(f"/api/users/{uid}/enrollments/{modality}", files=[("files", ("s.bin", sample))],
                       data={"password": password})


def enroll_all(client, uid):
    for m in ("face", "fingerprint", "voice"):
        r = enroll(client, uid, m)
        assert r.status_code == 200, r.text


def make_txn(client, uid=None, **over):
    body = {"amount": 100, "recipient_name": "Bob", "recipient_account": "ACC123"}
    body.update(over)
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def auth(client, tid, **samples):
    files = {k: (f"{k}.bin", v) for k, v in samples.items()}
    return client.post(f"/api/transactions/{tid}/authenticate", files=files)
