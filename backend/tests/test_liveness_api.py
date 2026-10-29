"""Liveness inside the authentication workflow, with fake checkers so the policy around it is tested
without a camera, a recognizer or a face detector."""
import pytest
from fastapi.testclient import TestClient

from app.main import LivenessServices, create_app
from tests.conftest import PW, enroll_all, login, make_txn, make_user
from tests.fakes import fake_registry


class FakeFaceLive:
    """Frames equal to b'photo' are a flat picture; anything else is a live turn (first frame used for identity)."""
    class R:
        def __init__(self, ok): self.ok, self.code, self.message, self.frame_index, self.details = ok, None if ok else "flat_face_suspected", None if ok else "flat", 0, {"yaw_change": 0.4}

    def check(self, frames, direction):
        return self.R(not any(f == b"photo" for f in frames))


class FakeSpoken:
    class R:
        def __init__(self, ok): self.ok, self.code, self.message, self.details = ok, None if ok else "phrase_not_heard", None if ok else "not heard", {"transcript": "..."}

    def check(self, audio, phrase):
        return self.R(audio != b"replay")

    def status(self):
        return True, "fake recognizer"


def make_client(settings, face=True, spoken=True, required="high"):
    settings.liveness_required_from = required
    live = LivenessServices(face=FakeFaceLive() if face else None, spoken=FakeSpoken() if spoken else None)
    return TestClient(create_app(settings, fake_registry(), live))


def challenge(c):
    r = c.post("/api/liveness/challenge")
    assert r.status_code == 200, r.text
    return r.json()


def post_auth(c, tid, cid=None, frames=None, **files):
    f = [(k, (f"{k}.bin", v)) for k, v in files.items()]
    f += [("face_frames", (f"f{i}.bin", fr)) for i, fr in enumerate(frames or [])]
    return c.post(f"/api/transactions/{tid}/authenticate", files=f or None, data={"challenge_id": cid} if cid else None)


def results(resp):
    return {r["modality"]: r for r in resp.json()["attempts"][-1]["modality_results"]}


HIGH = dict(amount=12000, recipient_is_new=True)


def test_challenge_has_a_direction_a_phrase_and_is_per_user(settings):
    with make_client(settings) as c:
        make_user(c)
        ch = challenge(c)
        assert ch["face"]["direction"] in ("left", "right") and len(ch["voice"]["phrase"]) == 3
        assert challenge(c)["challenge_id"] != ch["challenge_id"]
        c.headers.pop("Authorization")
        assert c.post("/api/liveness/challenge").status_code == 401


def test_high_risk_still_photo_is_not_accepted_as_evidence(settings):
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        assert t["risk_category"] in ("high", "critical")
        r = post_auth(c, t["id"], face=b"match", voice=b"match", fingerprint=b"match")
        res = results(r)
        assert res["face"]["status"] == "not_evaluated" and res["face"]["reason_code"] == "liveness_required"
        assert res["voice"]["reason_code"] == "liveness_required"
        assert res["fingerprint"]["status"] == "match"                    # fingerprint has no liveness (documented)
        assert r.json()["decision"] == "additional_verification_required"


def test_high_risk_with_live_challenge_can_be_approved(settings):
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        cid = challenge(c)["challenge_id"]
        r = post_auth(c, t["id"], cid, frames=[b"match"] * 8, voice=b"match", fingerprint=b"match")
        res = results(r)
        assert res["face"]["status"] == "match" and res["face"]["details"]["liveness"]["passed"] is True
        assert res["face"]["details"]["liveness"]["kind"] == "head_turn"
        assert res["voice"]["details"]["liveness"]["kind"] == "spoken_phrase"
        assert r.json()["decision"] == "approved"


def test_flat_photo_frames_fail_liveness_and_never_count_as_a_match(settings):
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        r = post_auth(c, t["id"], challenge(c)["challenge_id"], frames=[b"photo"] * 8, voice=b"match", fingerprint=b"match")
        res = results(r)
        assert res["face"]["status"] == "not_evaluated" and res["face"]["reason_code"] == "liveness_failed"
        assert res["face"]["details"]["liveness"]["passed"] is False and res["face"]["calibrated"] is None
        assert r.json()["decision"] == "additional_verification_required"          # voice + fingerprint alone would have passed
        assert "need face and voice" in r.json()["decision_reason"]                  # high risk: the core rule already blocks it


def test_a_failed_liveness_check_vetoes_approval_even_when_policy_would_allow_it(settings):
    """Medium risk accepts voice + fingerprint without the face, so only the veto rule stops this attempt."""
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, amount=3000, recipient_is_new=True)
        assert t["risk_category"] == "medium"
        r = post_auth(c, t["id"], challenge(c)["challenge_id"], frames=[b"photo"] * 8, voice=b"match", fingerprint=b"match")
        assert results(r)["face"]["reason_code"] == "liveness_failed"
        assert r.json()["decision"] == "additional_verification_required"
        assert "liveness check failed" in r.json()["decision_reason"]


def test_replayed_audio_fails_the_spoken_challenge(settings):
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        r = post_auth(c, t["id"], challenge(c)["challenge_id"], frames=[b"match"] * 8, voice=b"replay", fingerprint=b"match")
        assert results(r)["voice"]["reason_code"] == "liveness_failed"
        assert results(r)["face"]["status"] == "match"
        assert r.json()["decision"] != "approved"                                    # a failed check vetoes approval


def test_a_challenge_works_once_only(settings):
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        cid = challenge(c)["challenge_id"]
        t1, t2 = make_txn(c, **HIGH), make_txn(c, **HIGH)
        assert results(post_auth(c, t1["id"], cid, frames=[b"match"] * 8))["face"]["status"] == "match"
        again = post_auth(c, t2["id"], cid, frames=[b"match"] * 8)               # same challenge reused (e.g. replayed request)
        assert results(again)["face"]["reason_code"] == "liveness_failed"


def test_challenge_of_another_user_is_rejected(settings):
    with make_client(settings) as c:
        a = make_user(c, "Alice A", "alice@example.com")
        cid = challenge(c)["challenge_id"]
        c.headers.pop("Authorization")
        b = make_user(c, "Bob B", "bob@example.com"); enroll_all(c, b["id"])
        t = make_txn(c, **HIGH)
        assert results(post_auth(c, t["id"], cid, frames=[b"match"] * 8))["face"]["reason_code"] == "liveness_failed"


def test_expired_challenge_is_rejected(settings):
    settings.liveness_ttl_seconds = 0
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        cid = challenge(c)["challenge_id"]
        t = make_txn(c, **HIGH)
        assert results(post_auth(c, t["id"], cid, frames=[b"match"] * 8))["face"]["reason_code"] == "liveness_failed"


def test_missing_checker_fails_closed_not_open(settings):
    with make_client(settings, face=False, spoken=False) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        res = results(post_auth(c, t["id"], challenge(c)["challenge_id"], frames=[b"match"] * 8, voice=b"match"))
        assert res["face"]["reason_code"] == "liveness_unavailable" and res["face"]["status"] == "not_evaluated"
        assert res["voice"]["reason_code"] == "liveness_unavailable"


def test_low_risk_does_not_need_liveness(settings):
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, amount=50)
        r = post_auth(c, t["id"], face=b"match")
        assert results(r)["face"]["status"] == "match" and r.json()["decision"] == "approved"


def test_required_level_is_configurable(settings):
    with make_client(settings, required="low") as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, amount=50)
        assert results(post_auth(c, t["id"], face=b"match"))["face"]["reason_code"] == "liveness_required"
    settings2 = settings
    with make_client(settings2, required="never") as c:
        u = make_user(c, "Eve E", "eve@example.com"); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        assert results(post_auth(c, t["id"], face=b"match"))["face"]["status"] == "match"


def test_repeated_liveness_failures_are_limited_separately(settings):
    settings.liveness_failure_limit = 3
    with make_client(settings) as c:
        u = make_user(c); enroll_all(c, u["id"])
        codes = []
        for _ in range(5):
            t = make_txn(c, **HIGH)
            codes.append(post_auth(c, t["id"], challenge(c)["challenge_id"], frames=[b"photo"] * 8, voice=b"match").status_code)
        assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]
        # ...but they do not use up the ordinary biometric-failure allowance
        with c.app.state.session_factory() as db:
            from app.models import Event
            assert db.query(Event).filter_by(kind="biometric_failure").count() == 0


def test_dashboard_reports_liveness_status(settings):
    with make_client(settings, spoken=False) as c:
        make_user(c)
        d = c.get("/api/dashboard/stats").json()
        assert d["liveness"]["face"]["available"] is True and d["liveness"]["voice"]["available"] is False
        assert d["liveness_required_from"] == "high"


def test_a_missing_recognizer_is_unavailable_not_an_attack(settings):
    """If the speech recognizer is not installed that is a server problem. It must not look like spoofing or
    use up the user's liveness-failure allowance."""
    class NoAsr(FakeSpoken):
        def check(self, audio, phrase):
            return type("R", (), {"ok": False, "code": "asr_unavailable", "message": "recognizer not installed", "details": {}})()

    settings.liveness_required_from = "high"
    live = LivenessServices(face=FakeFaceLive(), spoken=NoAsr())
    with TestClient(create_app(settings, fake_registry(), live)) as c:
        u = make_user(c); enroll_all(c, u["id"])
        t = make_txn(c, **HIGH)
        res = results(post_auth(c, t["id"], challenge(c)["challenge_id"], frames=[b"match"] * 8, voice=b"match"))
        assert res["voice"]["reason_code"] == "liveness_unavailable"
        with c.app.state.session_factory() as db:
            from app.models import Event
            assert db.query(Event).filter_by(kind="liveness_failure").count() == 0
