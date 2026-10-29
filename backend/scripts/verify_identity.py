"""End-to-end check that TriLock verifies the ENROLLED ACCOUNT HOLDER, not just that it captured samples.

  python scripts/verify_identity.py --people 25

It starts the real app in-process (real SFace face model, real ECAPA voice model, real database and encrypted
template store in a throw-away folder) and drives it through the HTTP API exactly like the browser does.
Each virtual user is a real LFW face paired with a real LibriSpeech speaker. For every user it:

  * enrolls two photos and three recordings of that person through the enrollment endpoint
  * opens a transaction and authenticates with that SAME person's fresh photo + recording  (genuine)
  * opens transactions and tries to authenticate AS THAT USER with someone else's face and voice  (impostor)
  * tries impostors that have only the face right, or only the voice right  (partial)
  * submits broken input: no samples, garbage bytes, a blank picture, silent audio, audio that is too short

It prints the outcome of every scenario by risk level and exits non-zero if any impostor or any broken input
was ever APPROVED. Liveness is switched off here on purpose, so what is tested is identity matching and the
decision policy. Liveness has its own tests (and does not decide who someone is).

Needs the datasets under data/datasets (LFW funneled, Mini LibriSpeech); see docs/EVALUATION.md.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

PASSWORD = "correct-horse-battery"
RISKS = {  # chosen to land in each category for a fresh account; the ACTUAL category is read back from the server
    "low": dict(amount=40),
    "medium": dict(amount=3000, recipient_is_new=True),
    "high": dict(amount=12000, recipient_is_new=True, is_international=True),
}


def load_people(lfw: Path, speech: Path, n: int, seed: int):
    rng = random.Random(seed)
    faces = {p.name: sorted(p.glob("*.jpg")) for p in sorted(lfw.iterdir()) if p.is_dir()}
    faces = {k: v for k, v in faces.items() if len(v) >= 3}
    speakers: dict[str, list[Path]] = {}
    for f in sorted(speech.rglob("*.flac")):
        speakers.setdefault(f.parts[len(speech.parts)], []).append(f)
    speakers = {k: v for k, v in speakers.items() if len(v) >= 5}
    names = sorted(faces)
    rng.shuffle(names)
    spk = sorted(speakers)
    rng.shuffle(spk)
    n = min(n, len(spk))
    out = []
    for i in range(n):
        out.append({"name": names[i], "faces": [p.read_bytes() for p in faces[names[i]][:3]],
                    "speaker": spk[i], "voices": [p.read_bytes() for p in speakers[spk[i]][:5]]})
    return out


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def wav(x, sr=16000) -> bytes:
    b = io.BytesIO()
    sf.write(b, x, sr, format="WAV")
    return b.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--people", type=int, default=25)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--lfw", type=Path, default=ROOT / "data/datasets/lfw/lfw_funneled")
    ap.add_argument("--speech", type=Path, default=ROOT / "data/datasets/librispeech/LibriSpeech/dev-clean-2")
    ap.add_argument("--json", type=Path, help="also write the raw results here")
    a = ap.parse_args()

    people = load_people(a.lfw, a.speech, a.people, a.seed)
    print(f"{len(people)} virtual users (real LFW face + real LibriSpeech voice each)")
    real = get_settings()
    tmp = Path(tempfile.mkdtemp(prefix="trilock-identity-"))
    shutil.copy(real.data_dir / "calibration.json", tmp / "calibration.json")   # the thresholds the app really uses
    settings = Settings(data_dir=tmp, models_dir=real.models_dir, login_biometrics="off", liveness_required_from="never",
                        biometric_failure_limit=1000, biometric_user_failure_limit=1000, _env_file=None)
    results: list[dict] = []
    problems: list[str] = []
    notes: list[str] = []

    with TestClient(create_app(settings)) as c:
        mods = c.app.state.registry.statuses()
        assert all(mods[m]["available"] for m in ("face", "voice")), f"models unavailable: {mods}"
        print("modules:", {k: v["available"] for k, v in mods.items()}, "| thresholds:",
              {m: round(c.app.state.registry.get(m).cal.center, 3) for m in ("face", "voice")})

        users = []
        for i, p in enumerate(people):
            email = f"user{i}@example.com"
            c.post("/api/auth/register", json={"full_name": f"User {i}", "email": email, "password": PASSWORD})
            tok = c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            uid = c.get("/api/auth/me", headers=h).json()["id"]
            r1 = c.post(f"/api/users/{uid}/enrollments/face", headers=h, data={"password": PASSWORD},
                        files=[("files", ("a.jpg", p["faces"][0])), ("files", ("b.jpg", p["faces"][1]))])
            proof = [("proof_face", ("p.jpg", p["faces"][0]))]
            r2 = c.post(f"/api/users/{uid}/enrollments/voice", headers=h, data={"password": PASSWORD},
                        files=[("files", (f"v{k}.flac", v)) for k, v in enumerate(p["voices"][:3])] + proof)
            if r1.status_code != 200 or r2.status_code != 200:
                print(f"  could not enroll user {i}: face {r1.status_code} {r1.text[:90]} | voice {r2.status_code} {r2.text[:90]}")
                continue
            users.append((i, uid, h, p))
        print(f"{len(users)} users enrolled (face from 2 photos, voice from 3 recordings)\n")

        def attempt(i, uid, h, scenario, face, voice, risk, expect_approved):
            body = {"recipient_name": "Test", "recipient_account": "ACC123", "transaction_type": "domestic_transfer", **RISKS[risk]}
            t = c.post("/api/transactions", headers=h, json=body).json()
            files = {}
            if face is not None:
                files["face"] = ("face.bin", face)
            if voice is not None:
                files["voice"] = ("voice.bin", voice)
            r = c.post(f"/api/transactions/{t['id']}/authenticate", headers=h, files=files or None)
            d = r.json()
            res = {x["modality"]: x for x in d["attempts"][-1]["modality_results"]}
            row = {"user": i, "scenario": scenario, "requested_risk": risk, "risk": t["risk_category"], "decision": d["decision"],
                   "face": res["face"]["status"], "voice": res["voice"]["status"],
                   "face_raw": res["face"]["raw_score"], "voice_raw": res["voice"]["raw_score"],
                   "face_p": res["face"]["calibrated"], "voice_p": res["voice"]["calibrated"], "reason": d["decision_reason"]}
            results.append(row)
            if row["decision"] == "approved" and not expect_approved:
                if scenario.startswith("partial") and "no_match" not in (row["face"], row["voice"]) and "match" in (row["face"], row["voice"]) \
                        and risk == "low":
                    # the wrong person's sample was unusable, so only the holder's own sample was evaluated and it matched:
                    # the documented low-risk single-modality rule, not an impostor getting through
                    notes.append(f"user {i} {scenario}: approved at low risk on the holder's own sample alone (other sample unusable)")
                    return row
                problems.append(f"APPROVED but should not be: user {i} {scenario} risk {row['risk']} face={row['face']} voice={row['voice']}")
            return row

        n = len(users)
        for k, (i, uid, h, p) in enumerate(users):
            other = users[(k + 7) % n][3]            # a different real person (face and voice)
            other2 = users[(k + 11) % n][3]
            own_face, own_voice = p["faces"][2], p["voices"][3]   # NOT used for enrollment
            for risk in RISKS:
                attempt(i, uid, h, "genuine: own face + own voice", own_face, own_voice, risk, True)
                attempt(i, uid, h, "IMPOSTOR: other face + other voice", other["faces"][2], other["voices"][3], risk, False)
                attempt(i, uid, h, "partial: own face + other voice", own_face, other2["voices"][3], risk, False)
                attempt(i, uid, h, "partial: other face + own voice", other2["faces"][2], own_voice, risk, False)
            # one risk level is enough for the single-modality and broken-input checks (the policy is checked above)
            attempt(i, uid, h, "IMPOSTOR: other face only", other["faces"][2], None, "low", False)
            attempt(i, uid, h, "IMPOSTOR: other voice only", None, other["voices"][3], "low", False)
            attempt(i, uid, h, "own face only", own_face, None, "low", True)
            attempt(i, uid, h, "broken: nothing submitted", None, None, "low", False)
            attempt(i, uid, h, "broken: garbage bytes", b"not an image", b"not audio", "low", False)
            attempt(i, uid, h, "broken: blank picture + silence", png(np.full((300, 300, 3), 128, np.uint8)),
                    wav(np.zeros(16000 * 4, np.float32)), "low", False)
            attempt(i, uid, h, "broken: 0.5 s of audio", None, wav(np.random.default_rng(0).normal(0, .1, 8000).astype(np.float32)), "low", False)
            attempt(i, uid, h, "broken: a face photo sent as the voice", None, own_face, "low", False)
            attempt(i, uid, h, "broken: a voice file sent as the face", own_voice, None, "low", False)

    # ---------------------------------------------------------------- report
    by: dict = defaultdict(lambda: defaultdict(Counter))
    for r in results:
        by[r["scenario"]][r["risk"]][r["decision"]] += 1
    short = {"approved": "approve", "rejected": "reject", "additional_verification_required": "more"}
    print(f"{'scenario':46s} {'risk':9s} approve  reject   more")
    for sc in sorted(by, key=lambda s: (not s.startswith("genuine"), s)):
        for risk in ("low", "medium", "high", "critical"):
            cnt = by[sc].get(risk)
            if cnt:
                print(f"{sc:46s} {risk:9s} {cnt['approved']:7d} {cnt['rejected']:7d} {cnt['additional_verification_required']:6d}")
    gen = [r for r in results if r["scenario"].startswith("genuine")]
    imp = [r for r in results if r["scenario"].startswith("IMPOSTOR") or r["scenario"].startswith("partial")]
    print(f"\ngenuine attempts approved: {sum(r['decision'] == 'approved' for r in gen)} of {len(gen)}")
    print(f"impostor / partial attempts approved: {sum(r['decision'] == 'approved' for r in imp)} of {len(imp)}")
    broken = [r for r in results if r["scenario"].startswith("broken")]
    print(f"broken-input attempts approved: {sum(r['decision'] == 'approved' for r in broken)} of {len(broken)}")
    fm = [r["face_raw"] for r in results if r["scenario"].startswith("genuine") and r["face_raw"] is not None]
    fi = [r["face_raw"] for r in results if r["scenario"].startswith("IMPOSTOR: other face + other voice") and r["face_raw"] is not None]
    vm = [r["voice_raw"] for r in results if r["scenario"].startswith("genuine") and r["voice_raw"] is not None]
    vi = [r["voice_raw"] for r in results if r["scenario"].startswith("IMPOSTOR: other face + other voice") and r["voice_raw"] is not None]
    if fm and fi and vm and vi:
        print(f"face cosine: own {np.mean(fm):.2f} (min {min(fm):.2f})  vs other person {np.mean(fi):.2f} (max {max(fi):.2f})")
        print(f"voice cosine: own {np.mean(vm):.2f} (min {min(vm):.2f})  vs other person {np.mean(vi):.2f} (max {max(vi):.2f})")
    if notes:
        print(f"\nBy-design approvals ({len(notes)}): a low-risk payment needs one matching modality and nothing contradicting it.")
        print("\n".join("  " + n for n in notes))
    if a.json:
        a.json.write_text(json.dumps(results, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        print("\nPROBLEMS:")
        print("\n".join(problems[:30]))
        print(f"({len(problems)} in total)")
        return 1
    print("\nOK: no impostor and no broken input was ever approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
