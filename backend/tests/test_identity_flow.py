"""Does TriLock verify the ENROLLED ACCOUNT HOLDER, with the real models? (SFace and ECAPA-TDNN, no fakes.)

Three real people (A, B, C: real photos from LFW, real recordings from LibriSpeech) each get an account with one
enrolled face photo and one enrolled recording. Then every combination of "who is sitting at the laptop" and
"whose account is it" is tried through the HTTP API, exactly as the browser would.

Skipped, with a reason, when the models are not installed. Run alone:  pytest -m integration tests/test_identity_flow.py
Liveness is switched off here so that identity matching and the decision policy are what is tested. The
thresholds are the ones fitted by the evaluation (tests/fixtures/calibration.json).
"""
import io
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration
FIX = Path(__file__).parent / "fixtures"
PW = "correct-horse-battery"
PEOPLE = {  # enrol with *1, probe with *2 (a different photo and a different recording of the same person)
    "A": dict(face1="face_a1.jpg", face2="face_a2.jpg", voice1="voice_a1.flac", voice2="voice_a2.flac"),
    "B": dict(face1="face_b1.jpg", face2="face_b2.jpg", voice1="voice_b1.flac", voice2="voice_b2.flac"),
    "C": dict(face1="face_c1.jpg", face2="face_c2.jpg", voice1="voice_c1.flac", voice2="voice_c2.flac"),
}
# time-based risk factors off, so the risk level depends only on what the test sets
RISK_OFF = {"risk": {"velocity_points": [], "new_account_points": 0, "night_points": 0, "usual_hour_points": 0,
                     "daily_total_points": 0, "recent_biometric_change_points": 0, "dormant_points": 0}}
PAYMENTS = {  # chosen to land in each category once the time factors are off
    "low": dict(amount=40),
    "medium": dict(amount=3000, recipient_is_new=True),
    "high": dict(amount=12000, recipient_is_new=True, is_international=True),
    "critical": dict(amount=25000, recipient_is_new=True, is_international=True, new_device=True),
}
read = lambda name: (FIX / name).read_bytes()


def wav(x, sr=16000):
    b = io.BytesIO()
    sf.write(b, x, sr, format="WAV")
    return b.getvalue()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    real = Settings(_env_file=None)
    tmp = tmp_path_factory.mktemp("identity")
    shutil.copy(FIX / "calibration.json", tmp / "calibration.json")
    (tmp / "policy.json").write_text(json.dumps(RISK_OFF))
    settings = Settings(data_dir=tmp, models_dir=real.models_dir, policy_file=tmp / "policy.json", login_biometrics="off",
                        liveness_required_from="never", biometric_failure_limit=10_000, biometric_user_failure_limit=10_000,
                        _env_file=None)
    app = create_app(settings)
    mods = app.state.registry.statuses()
    if not (mods["face"]["available"] and mods["voice"]["available"]):
        pytest.skip(f"face or voice model unavailable: {mods['face']['detail']} | {mods['voice']['detail']}")
    with TestClient(app) as c:
        users = {}
        for who, f in PEOPLE.items():
            email = f"{who.lower()}@example.com"
            c.post("/api/auth/register", json={"full_name": f"Person {who}", "email": email, "password": PW})
            h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]}
            uid = c.get("/api/auth/me", headers=h).json()["id"]
            r = c.post(f"/api/users/{uid}/enrollments/face", headers=h, data={"password": PW}, files=[("files", ("f.jpg", read(f["face1"])))])
            assert r.status_code == 200, r.text
            r = c.post(f"/api/users/{uid}/enrollments/voice", headers=h, data={"password": PW},
                       files=[("files", ("v.flac", read(f["voice1"]))), ("proof_face", ("p.jpg", read(f["face1"])))])
            assert r.status_code == 200, r.text
            users[who] = (uid, h)
        yield c, users, app


def pay(world, account, risk, face=None, voice=None):
    """Open a payment on `account` and authenticate it with the given samples. Returns the transaction JSON."""
    c, users, _ = world
    _, h = users[account]
    t = c.post("/api/transactions", headers=h, json={"recipient_name": "Test", "recipient_account": "ACC123", **PAYMENTS[risk]}).json()
    assert t["risk_category"] == risk, f"payment for '{risk}' came out as {t['risk_category']}"
    files = {}
    if face is not None:
        files["face"] = ("face.bin", face)
    if voice is not None:
        files["voice"] = ("voice.bin", voice)
    r = c.post(f"/api/transactions/{t['id']}/authenticate", headers=h, files=files or None)
    assert r.status_code == 200, r.text
    return r.json()


def mods(d):
    return {m["modality"]: m for m in d["attempts"][-1]["modality_results"]}


def check_invariant(d):
    """Whatever happened, an approval must rest on real matches and never contain a mismatch."""
    if d["decision"] == "approved":
        res = mods(d)
        assert any(r["status"] == "match" for r in res.values()), "approved with no matching modality"
        assert not any(r["status"] == "no_match" for r in res.values()), "approved although a modality said no match"
        assert not any(r["status"] == "not_evaluated" and r["calibrated"] is not None for r in res.values())


# ------------------------------------------------------------------ the account holder
@pytest.mark.parametrize("who", PEOPLE)
def test_the_account_holder_is_approved_with_real_scores_from_the_real_models(world, who):
    f = PEOPLE[who]
    d = pay(world, who, "low", read(f["face2"]), read(f["voice2"]))
    res = mods(d)
    assert d["decision"] == "approved"
    assert res["face"]["status"] == res["voice"]["status"] == "match"
    assert "SFace" in res["face"]["method"] and "ECAPA" in res["voice"]["method"]      # the actual identity models
    assert res["face"]["raw_score"] > res["face"]["threshold"] and res["voice"]["raw_score"] > res["voice"]["threshold"]
    assert 0.3 < res["face"]["raw_score"] < 1.01 and 0.3 < res["voice"]["raw_score"] < 1.01        # cosine similarities, not placeholders
    check_invariant(d)


# ------------------------------------------------------------------ someone else at the laptop
@pytest.mark.parametrize("account,intruder", [(a, b) for a in PEOPLE for b in PEOPLE if a != b])
@pytest.mark.parametrize("risk", ["low", "medium"])
def test_a_different_person_is_rejected_on_someone_elses_account(world, account, intruder, risk):
    f = PEOPLE[intruder]
    d = pay(world, account, risk, read(f["face2"]), read(f["voice2"]))
    res = mods(d)
    assert res["face"]["status"] == "no_match" and res["voice"]["status"] == "no_match"
    assert res["face"]["raw_score"] < res["face"]["threshold"] and res["voice"]["raw_score"] < res["voice"]["threshold"]
    assert d["decision"] == "rejected"
    check_invariant(d)


def test_the_same_sample_matches_its_owner_and_not_anyone_elses_account(world):
    """The decision follows the ENROLLED template of the account, not the sample: A's face and voice are a match
    on A's account and a mismatch on B's and C's, with clearly different scores."""
    f = PEOPLE["A"]
    scores = {}
    for account in PEOPLE:
        d = pay(world, account, "low", read(f["face2"]), read(f["voice2"]))
        res = mods(d)
        scores[account] = (res["face"]["raw_score"], res["voice"]["raw_score"], res["face"]["status"], res["voice"]["status"])
    assert scores["A"][2:] == ("match", "match") and scores["B"][2:] == ("no_match", "no_match") and scores["C"][2:] == ("no_match", "no_match")
    assert scores["A"][0] > scores["B"][0] + 0.25 and scores["A"][0] > scores["C"][0] + 0.25
    assert scores["A"][1] > scores["B"][1] + 0.25 and scores["A"][1] > scores["C"][1] + 0.25


def test_every_attempt_at_every_risk_level_with_every_wrong_combination_is_never_approved(world):
    """Full cross product: account X, face of person P, voice of person Q, none of the three equal. Also the
    mixed ones (right face + wrong voice, wrong face + right voice) at all four risk levels."""
    approvals = []
    for account in PEOPLE:
        others = [p for p in PEOPLE if p != account]
        for risk in PAYMENTS:
            for fp, vp in [(others[0], others[1]), (others[1], others[0]), (account, others[0]), (others[0], account)]:
                d = pay(world, account, risk, read(PEOPLE[fp]["face2"]), read(PEOPLE[vp]["voice2"]))
                check_invariant(d)
                if d["decision"] == "approved":
                    approvals.append((account, risk, fp, vp))
    assert approvals == [], f"wrongly approved: {approvals}"


def test_a_different_person_with_only_one_modality_is_not_approved(world):
    for risk in ("low", "medium", "high"):
        d = pay(world, "A", risk, face=read(PEOPLE["B"]["face2"]))
        assert d["decision"] == "rejected", risk
        d = pay(world, "A", risk, voice=read(PEOPLE["B"]["voice2"]))
        assert d["decision"] == "rejected", risk
    d = pay(world, "A", "low", face=read("face_d1.jpg"))                   # a fourth person who is not enrolled anywhere
    assert d["decision"] == "rejected"


# ------------------------------------------------------------------ missing, invalid, poor input
def blur(b, s=6):
    return cv2.imencode(".png", cv2.GaussianBlur(cv2.imdecode(np.frombuffer(b, np.uint8), 1), (0, 0), s))[1].tobytes()


def dark(b, k=0.12):
    return cv2.imencode(".png", (cv2.imdecode(np.frombuffer(b, np.uint8), 1) * k).astype(np.uint8))[1].tobytes()


def noisy(path, snr_db):
    x, sr = sf.read(path, dtype="float32")
    p = float(np.mean(x ** 2))
    return wav(x + np.random.default_rng(0).normal(0, np.sqrt(p / 10 ** (snr_db / 10)), x.shape).astype(np.float32), sr)


BROKEN = {
    "nothing": (None, None),
    "garbage": (b"not an image", b"not audio"),
    "blank picture and silence": (cv2.imencode(".png", np.full((300, 300, 3), 128, np.uint8))[1].tobytes(), wav(np.zeros(64000, np.float32))),
    "0.5 s of audio": (None, wav(np.random.default_rng(1).normal(0, 0.1, 8000).astype(np.float32))),
    "a photo sent as the voice": (None, read("face_a2.jpg")),
    "a recording sent as the face": (read("voice_a2.flac"), None),
    "empty files": (b"", b""),
}


@pytest.mark.parametrize("name", list(BROKEN))
@pytest.mark.parametrize("risk", ["low", "medium", "high", "critical"])
def test_missing_or_invalid_input_never_approves_and_is_not_treated_as_a_mismatch(world, name, risk):
    face, voice = BROKEN[name]
    d = pay(world, "A", risk, face, voice)
    res = mods(d)
    assert d["decision"] == "additional_verification_required"            # asks for more; neither approves nor accuses
    for m in ("face", "voice"):
        assert res[m]["status"] == "not_evaluated" and res[m]["calibrated"] is None and res[m]["reason_code"]
    check_invariant(d)


def test_poor_quality_versions_of_the_account_holders_own_samples_are_refused_not_guessed(world):
    f = PEOPLE["A"]
    d = pay(world, "A", "low", face=blur(read(f["face2"]), 6))
    assert mods(d)["face"]["status"] == "not_evaluated" and mods(d)["face"]["reason_code"] in ("blurry", "no_face", "low_face_confidence")
    assert d["decision"] != "approved"
    d = pay(world, "A", "low", face=dark(read(f["face2"])))
    assert mods(d)["face"]["status"] == "not_evaluated" and d["decision"] != "approved"
    d = pay(world, "A", "low", voice=noisy(FIX / f["voice2"], 0))
    assert mods(d)["voice"]["status"] in ("not_evaluated", "match") and mods(d)["voice"]["status"] != "no_match" or d["decision"] != "approved"
    check_invariant(d)


def test_degraded_samples_of_a_different_person_are_never_approved(world):
    b = PEOPLE["B"]
    for face, voice in [(blur(read(b["face2"]), 1.5), noisy(FIX / b["voice2"], 10)), (dark(read(b["face2"]), 0.4), noisy(FIX / b["voice2"], 0)),
                        (cv2.imencode(".jpg", cv2.resize(cv2.imread(str(FIX / b["face2"])), None, fx=.6, fy=.6), [cv2.IMWRITE_JPEG_QUALITY, 25])[1].tobytes(),
                         noisy(FIX / b["voice2"], 20))]:
        for risk in ("low", "medium"):
            d = pay(world, "A", risk, face, voice)
            assert d["decision"] != "approved"
            check_invariant(d)


# ------------------------------------------------------------------ risk level and policy use the match results
def test_the_decision_depends_on_risk_and_on_how_much_matched(world):
    f = PEOPLE["A"]
    face, voice = read(f["face2"]), read(f["voice2"])
    assert pay(world, "A", "low", face=face)["decision"] == "approved"                       # one genuine modality is enough at low risk
    assert pay(world, "A", "medium", face=face)["decision"] == "additional_verification_required"   # medium wants two
    assert pay(world, "A", "high", face=face)["decision"] == "additional_verification_required"
    for risk in PAYMENTS:                                                                       # both genuine: every level approves
        d = pay(world, "A", risk, face, voice)
        assert d["decision"] == "approved", (risk, d["decision_reason"])
    assert pay(world, "A", "critical", voice=voice)["decision"] == "additional_verification_required"  # high levels need face AND voice


def test_a_user_with_nothing_enrolled_for_a_modality_cannot_be_approved_on_it(world):
    c, users, _ = world
    c.post("/api/auth/register", json={"full_name": "Newcomer", "email": "new@example.com", "password": PW})
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "new@example.com", "password": PW}).json()["token"]}
    t = c.post("/api/transactions", headers=h, json={"recipient_name": "X", "recipient_account": "ACC123", **PAYMENTS["low"]}).json()
    d = c.post(f"/api/transactions/{t['id']}/authenticate", headers=h,
               files={"face": ("f.jpg", read("face_a2.jpg")), "voice": ("v.flac", read("voice_a2.flac"))}).json()
    res = mods(d)
    assert res["face"]["reason_code"] == "not_enrolled" and res["voice"]["reason_code"] == "not_enrolled"
    assert d["decision"] == "additional_verification_required"


def test_someone_elses_transaction_cannot_be_authenticated(world):
    c, users, _ = world
    _, hb = users["B"]
    _, ha = users["A"]
    t = c.post("/api/transactions", headers=ha, json={"recipient_name": "X", "recipient_account": "ACC123", **PAYMENTS["low"]}).json()
    r = c.post(f"/api/transactions/{t['id']}/authenticate", headers=hb, files={"face": ("f.jpg", read("face_a2.jpg"))})
    assert r.status_code == 404
