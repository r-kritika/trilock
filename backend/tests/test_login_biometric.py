"""Sign-in with password + live face AND voice. Fake checkers (see test_liveness_api) keep the tests about the
policy: who gets which kind of session, what must match, and what the limits are."""
import pytest
from fastapi.testclient import TestClient

from app.main import LivenessServices, create_app
from app.models import Event
from tests.conftest import PW, enroll, enroll_all, login, make_admin, make_txn, make_user
from tests.fakes import fake_registry
from tests.test_liveness_api import FakeFaceLive, FakeSpoken


def client_for(settings, liveness=True):
    settings.login_biometrics = "required"
    live = LivenessServices(face=FakeFaceLive(), spoken=FakeSpoken()) if liveness else LivenessServices(face=None, spoken=None)
    return TestClient(create_app(settings, fake_registry(), live))


def register(c, email="ada@example.com", name="Ada A"):
    assert c.post("/api/auth/register", json={"full_name": name, "email": email, "password": PW}).status_code == 201


def password_login(c, email="ada@example.com", password=PW):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bio(c, pre, challenge, frames=(b"match",) * 8, voice=b"match"):
    files = [("face_frames", ("f.bin", f)) for f in frames]
    if voice is not None:
        files.append(("voice", ("v.bin", voice)))
    return c.post("/api/auth/login/biometric", headers={"Authorization": f"Bearer {pre}"}, files=files or None,
                  data={"challenge_id": challenge["challenge_id"]})


def enrolled_user(c, email="ada@example.com"):
    """Register, sign in (limited), enroll face + voice, sign out. Returns the user id."""
    register(c, email)
    r = password_login(c, email)
    assert r["status"] == "enrollment_required" and r["missing"] == ["face", "voice"]
    c.headers["Authorization"] = f"Bearer {r['token']}"
    uid = r["user"]["id"]
    assert enroll(c, uid, "face", proof=None).status_code == 200
    assert enroll(c, uid, "voice").status_code == 200
    c.post("/api/auth/logout")
    c.headers.pop("Authorization")
    return uid


def start(c, email="ada@example.com"):
    r = password_login(c, email)
    assert r["status"] == "biometric_required"
    return r["preauth_token"], r["challenge"]


# ---- a new account: limited session until face and voice are enrolled ----
def test_new_account_gets_a_limited_session_and_is_upgraded_when_face_and_voice_are_enrolled(settings):
    with client_for(settings) as c:
        register(c)
        r = password_login(c)
        assert r["status"] == "enrollment_required" and "preauth_token" not in r
        c.headers["Authorization"] = f"Bearer {r['token']}"
        uid = r["user"]["id"]
        me = c.get("/api/auth/me").json()
        assert me["session_scope"] == "limited"
        # a limited session reaches enrollment, nothing else
        for method, path in (("POST", "/api/transactions"), ("GET", "/api/dashboard/stats"), ("POST", "/api/liveness/challenge"),
                             ("GET", "/api/transactions"), ("POST", "/api/risk/assess")):
            resp = c.request(method, path, json={"amount": 5, "recipient_name": "X", "recipient_account": "ACC1"} if method == "POST" else None)
            assert resp.status_code == 403 and resp.json()["error"]["code"] == "enrollment_incomplete", path
        assert c.get(f"/api/users/{uid}").status_code == 200
        assert enroll(c, uid, "face", proof=None).status_code == 200
        assert c.get("/api/auth/me").json()["session_scope"] == "limited"          # voice still missing
        assert enroll(c, uid, "voice").status_code == 200
        assert c.get("/api/auth/me").json()["session_scope"] == "full"              # both enrolled: unlocked
        assert c.get("/api/dashboard/stats").status_code == 200


def test_fingerprint_is_optional_everywhere(settings):
    with client_for(settings) as c:
        uid = enrolled_user(c)                                                      # face + voice only
        pre, ch = start(c)
        r = bio(c, pre, ch)
        assert r.status_code == 200 and r.json()["status"] == "ok"
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        flags = {e["modality"]: e["required"] for e in c.get("/api/auth/me").json()["enrollments"]}
        assert flags == {"face": True, "fingerprint": False, "voice": True}
        t = make_txn(c, amount=50)                                                   # payments work without a fingerprint
        assert c.post(f"/api/transactions/{t['id']}/authenticate", files={"face": ("f", b"match")}).json()["decision"] == "approved"


def test_payments_need_face_and_voice_enrolled(settings):
    with client_for(settings) as c:
        uid = enrolled_user(c)
        pre, ch = start(c)
        c.headers["Authorization"] = f"Bearer {bio(c, pre, ch).json()['token']}"
        assert enroll(c, uid, "fingerprint").status_code == 200
        from tests.conftest import delete_enrollment
        assert delete_enrollment(c, uid, "voice").status_code == 200
        r = c.post("/api/transactions", json={"amount": 5, "recipient_name": "X", "recipient_account": "ACC1"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "enroll_first" and "voice" in r.json()["error"]["message"]


# ---- accounts with face and voice: the password alone opens nothing ----
def test_password_alone_does_not_give_a_usable_session(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        r = password_login(c)
        assert r["status"] == "biometric_required" and "token" not in r
        assert r["challenge"]["face"]["direction"] in ("left", "right") and len(r["challenge"]["voice"]["phrase"]) == 3
        pre = {"Authorization": f"Bearer {r['preauth_token']}"}
        for path in ("/api/auth/me", "/api/transactions", "/api/dashboard/stats", "/api/users/1", "/api/policy"):
            resp = c.get(path, headers=pre)
            assert resp.status_code == 401 and resp.json()["error"]["code"] == "biometric_login_required", path


def test_successful_login_needs_both_face_and_voice_and_revokes_the_preauth_token(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        r = bio(c, pre, ch)
        assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["user"]["email"] == "ada@example.com"
        full = {"Authorization": f"Bearer {r.json()['token']}"}
        assert c.get("/api/auth/me", headers=full).json()["session_scope"] == "full"
        assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {pre}"}).status_code == 401      # preauth is spent
        assert bio(c, pre, ch).status_code == 401


@pytest.mark.parametrize("frames,voice,face_status,voice_status", [
    ((b"nomatch",) * 8, b"match", "no_match", "match"),          # someone else's face
    ((b"match",) * 8, b"nomatch", "match", "no_match"),          # someone else's voice
    ((b"nomatch",) * 8, b"nomatch", "no_match", "no_match"),
])
def test_both_modalities_must_match(settings, frames, voice, face_status, voice_status):
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        r = bio(c, pre, ch, frames, voice)
        assert r.status_code == 401 and r.json()["error"]["code"] == "biometric_login_failed" and "token" not in r.json()
        by = {m["modality"]: m["status"] for m in r.json()["error"]["details"]["modalities"]}
        assert by == {"face": face_status, "voice": voice_status}
        assert r.json()["error"]["details"]["attempts_left"] == 4
        with c.app.state.session_factory() as db:
            assert db.query(Event).filter_by(kind="biometric_failure").count() == 1


def test_a_flat_photo_or_replayed_audio_cannot_sign_in(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        r = bio(c, pre, ch, frames=(b"photo",) * 8)
        d = {m["modality"]: m for m in r.json()["error"]["details"]["modalities"]}
        assert r.status_code == 401 and d["face"]["reason_code"] == "liveness_failed"
        _, ch2 = pre, c.post("/api/auth/login/challenge", headers={"Authorization": f"Bearer {pre}"}).json()
        r = bio(c, pre, ch2, voice=b"replay")
        d = {m["modality"]: m for m in r.json()["error"]["details"]["modalities"]}
        assert r.status_code == 401 and d["voice"]["reason_code"] == "liveness_failed" and d["face"]["status"] == "match"


def test_missing_face_or_voice_fails_not_passes(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        r = bio(c, pre, ch, voice=None)                                           # no voice sent
        d = {m["modality"]: m for m in r.json()["error"]["details"]["modalities"]}
        assert r.status_code == 401 and d["voice"]["status"] == "not_evaluated" and d["face"]["status"] == "match"
        ch2 = c.post("/api/auth/login/challenge", headers={"Authorization": f"Bearer {pre}"}).json()
        r = bio(c, pre, ch2, frames=())                                           # no face sent
        d = {m["modality"]: m for m in r.json()["error"]["details"]["modalities"]}
        assert r.status_code == 401 and d["face"]["status"] == "not_evaluated"


def test_challenges_work_once_and_a_new_one_can_be_requested(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        assert bio(c, pre, ch, frames=(b"nomatch",) * 8).status_code == 401          # uses the challenge up
        stale = bio(c, pre, ch)                                                       # same challenge again, now with the right samples
        assert stale.status_code == 401
        assert {m["modality"]: m["reason_code"] for m in stale.json()["error"]["details"]["modalities"]}["face"] == "liveness_failed"
        fresh = c.post("/api/auth/login/challenge", headers={"Authorization": f"Bearer {pre}"}).json()
        assert fresh["challenge_id"] != ch["challenge_id"]
        assert bio(c, pre, fresh).status_code == 200


def test_a_challenge_from_one_user_cannot_be_used_by_another(settings):
    with client_for(settings) as c:
        enrolled_user(c, "ada@example.com")
        enrolled_user(c, "bob@example.com")
        _, ada_ch = start(c, "ada@example.com")
        bob_pre, _ = start(c, "bob@example.com")
        r = bio(c, bob_pre, ada_ch)
        assert r.status_code == 401


def test_a_password_entry_allows_only_a_few_biometric_tries(settings):
    settings.preauth_max_attempts = 3
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        for i in range(3):
            r = bio(c, pre, ch, frames=(b"nomatch",) * 8)
            assert r.status_code == 401 and r.json()["error"]["details"]["attempts_left"] == 2 - i
            ch = c.post("/api/auth/login/challenge", headers={"Authorization": f"Bearer {pre}"}).json()
        r = bio(c, pre, ch)                                                           # even the right face is refused now
        assert r.status_code == 401 and r.json()["error"]["code"] == "start_over"
        assert c.post("/api/auth/login/challenge", headers={"Authorization": f"Bearer {pre}"}).status_code == 401


def test_biometric_failures_at_sign_in_share_the_lockout(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        codes = []
        for _ in range(7):
            pre, ch = start(c)
            codes.append(bio(c, pre, ch, frames=(b"nomatch",) * 8).status_code)
        assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]


def test_expired_password_step_cannot_be_completed(settings):
    from datetime import timedelta
    from app.models import Session as Sess, utcnow
    with client_for(settings) as c:
        enrolled_user(c)
        pre, ch = start(c)
        with c.app.state.session_factory() as db:
            db.query(Sess).filter_by(scope="preauth").update({"expires_at": utcnow() - timedelta(seconds=1)})
            db.commit()
        assert bio(c, pre, ch).status_code == 401


def test_wrong_password_never_reaches_the_biometric_step(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        r = c.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong-password-123"})
        assert r.status_code == 401 and "preauth_token" not in r.text


def test_admin_signs_in_with_the_password_only(settings):
    with client_for(settings) as c:
        make_admin(c)
        c.headers.pop("Authorization")
        r = password_login(c, "boss@example.com")
        assert r["status"] == "ok" and r["user"]["role"] == "admin"


def test_biometric_sign_in_can_be_switched_off_for_setups_without_camera_or_recognizer(settings):
    settings.login_biometrics = "off"
    with TestClient(create_app(settings, fake_registry())) as c:
        enrolled_ok = make_user(c)
        enroll_all(c, enrolled_ok["id"])
        c.headers.pop("Authorization")
        assert password_login(c)["status"] == "ok"


def test_liveness_at_sign_in_can_be_switched_off_but_identity_is_still_checked(settings):
    settings.login_liveness = False
    with client_for(settings, liveness=False) as c:
        enrolled_user(c)
        pre, ch = start(c)
        assert bio(c, pre, ch, frames=(b"nomatch",), voice=b"match").status_code == 401        # identity still judged
        ch = c.post("/api/auth/login/challenge", headers={"Authorization": f"Bearer {pre}"}).json()
        assert bio(c, pre, ch, frames=(b"match",), voice=b"match").status_code == 200          # one photo + one recording is enough then


def test_sign_in_fails_closed_when_the_liveness_checkers_are_missing(settings):
    with client_for(settings, liveness=False) as c:               # liveness required but no checker installed
        enrolled_user(c)
        pre, ch = start(c)
        r = bio(c, pre, ch)
        d = {m["modality"]: m["reason_code"] for m in r.json()["error"]["details"]["modalities"]}
        assert r.status_code == 401 and d == {"face": "liveness_unavailable", "voice": "liveness_unavailable"}


def test_someone_who_cannot_pass_the_biometric_step_can_still_ask_for_recovery(settings):
    with client_for(settings) as c:
        enrolled_user(c)
        pre, _ = start(c)
        h = {"Authorization": f"Bearer {pre}"}
        assert c.post("/api/recovery", headers=h, data={"reason": "face changed", "password": "wrong-password-123"}).status_code == 403
        r = c.post("/api/recovery", headers=h, data={"reason": "face changed after surgery", "password": PW})
        assert r.status_code == 201 and r.json()["status"] == "pending"
        assert c.get("/api/transactions", headers=h).status_code == 401            # still nothing else is reachable
