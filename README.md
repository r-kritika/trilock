# TriLock

Risk-adaptive multimodal biometric security for digital banking. This is an academic prototype: a React dashboard and a FastAPI backend that verify a user with face, fingerprint and voice before a **simulated** bank transaction, and decide between approve, reject or "additional verification required" based on how risky the transaction is and how reliable the biometric evidence is.

No real money, bank or customer data is involved, and it is not a production authentication service. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before drawing any conclusion from it.

## What it does

1. Register a test account, sign in, and enroll face, voice and fingerprint references (re-entering the password to confirm each change).
2. Fill in a simulated transaction. A rule-based risk engine scores it (amount, new recipient, international, new device, unusual amount for this user).
3. Submit whichever biometric samples you have. Each module verifies independently and returns a score, an input-quality estimate, or a reason why the input could not be evaluated.
4. Two fusion policies decide on the same evidence: a fixed-threshold baseline and the risk-aware policy. The risk-aware one is applied by default, and both results are stored and shown side by side.
5. Everything is persisted in SQLite: users, enrollments, transactions, each attempt, and an audit log. Dashboard, history and analytics read from that data.
6. Users see only their own records. An administrator account (created from the command line) can read everything but cannot enroll, transact or decide for anyone. Details in [docs/SECURITY.md](docs/SECURITY.md).

| Modality | Method | Needs |
|---|---|---|
| Face | YuNet detector + SFace embedding (OpenCV), cosine similarity | two ONNX files (about 39 MB) |
| Voice | SpeechBrain ECAPA-TDNN speaker embedding, cosine similarity | torch, speechbrain, about 80 MB download |
| Fingerprint | SIFT keypoints + RANSAC inlier count on fingerprint **images** (experimental) | nothing extra, but no scanner access |

## Architecture

```
frontend (React + Vite)  --/api-->  backend (FastAPI)
                                      api/        routes only
                                      services/   risk, fusion, authentication workflow, enrollment, stats
                                      biometrics/ face, voice, fingerprint, calibration, registry
                                      evaluation/ CLI scripts that measure the modules and the fusion policies
                                      SQLite + encrypted template files in backend/data
```

More detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), the algorithms in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md), the evaluation protocol, audit and results in [docs/EVALUATION.md](docs/EVALUATION.md), and authentication, privacy and known gaps in [docs/SECURITY.md](docs/SECURITY.md).

## Prerequisites

- Linux (developed on Ubuntu), Python 3.10+ (tested with 3.12), Node 18+ (tested with 24)
- About 1.5 GB of disk for the voice stack (CPU torch) and models; more if you download evaluation datasets
- A browser with camera/microphone access for the live capture features. Camera and microphone need `localhost` or https; on other hosts use the upload buttons.

## Setup

```bash
# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# voice model stack (optional but needed for voice): CPU torch first, then speechbrain
.venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements-ml.txt

# download the face models (and the voice model if the stack above is installed)
.venv/bin/python scripts/download_models.py

# frontend
cd ../frontend
npm install
```

Without the voice stack the app still runs. The voice module reports itself as unavailable on the dashboard and enrollment page, and any voice sample is returned as "not evaluated", never as a match.

Optional configuration: copy `backend/.env.example` to `backend/.env`. Every setting has a default. Decision thresholds and risk weights can be overridden with a JSON file (`TRILOCK_POLICY_FILE`, format in `backend/policy.example.json`); the values in force are shown on the Analytics page.

## Run

Two terminals:

```bash
# terminal 1
cd backend && .venv/bin/uvicorn app.wsgi:app --port 8000

# terminal 2
cd frontend && npm run dev
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

A first walk-through: open the app and register an account (password of at least 10 characters). On Enrollment, type your password in the confirmation box, then enroll a face (camera or photo) and a voice recording. For the fingerprint use an image file; `python -m app.evaluation.make_demo_fingerprints` writes a few **synthetic** demo prints to `backend/data/demo/` if you have no dataset. Then New transaction: try a small payment with only a face, then a large payment to a new recipient with the same face only, and compare the two policies on the result page.

Administrator (read-only overview of all accounts, transactions and analytics):

```bash
cd backend && .venv/bin/python -m app.cli create-admin --email admin@example.com --name "Admin"
```

Data tools: `python -m app.cli purge --days 30` (retention) and `python -m app.cli erase-user --email x@y.z`.

## Tests

```bash
cd backend
.venv/bin/python -m pytest                      # 145 tests; most need no models
.venv/bin/python -m pytest -m integration -rs   # real-model tests on small fixtures
```

Integration tests skip with an explicit reason if a model is missing. API tests use fake biometric modules so decision logic is tested independent of model quality. Security tests cover login, lockout, access control, step-up, privacy and deletion.

## Evaluation

```bash
cd backend
.venv/bin/python -m app.evaluation.run_modality --modality face --root <dataset dir> --write-calibration
.venv/bin/python -m app.evaluation.run_modality --modality voice --root <dataset dir> --write-calibration
.venv/bin/python -m app.evaluation.run_modality --modality fingerprint --synthetic     # synthetic only!
.venv/bin/python -m app.evaluation.run_fusion
.venv/bin/pip install -r requirements-eval.txt && .venv/bin/python -m app.evaluation.report
```

Results are stored in the database (Analytics page) and written to `backend/reports/REPORT.md` with plots. Read [docs/EVALUATION.md](docs/EVALUATION.md) for the protocol, what was fixed during the audit, and the caveats (small datasets, synthetic fingerprints, assumed risk mix).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Frontend shows "Cannot reach the TriLock backend" | Backend not running on port 8000. |
| Sign-in says "account locked" | 5 wrong passwords lock it for 15 minutes. Wait, or clear `locked_until` in the database. |
| "Too many failed biometric attempts" (429) | 5 failed biometric tries in 15 minutes pause further tries for that user. |
| "Enter your account password" on enroll | Type the password in the confirmation box at the top of the Enrollment page. |
| Old database after an update | New columns are added automatically. Accounts made before login existed have no password; register again. |
| Dashboard says Face "Unavailable" | Model files missing in `backend/models`. Run `scripts/download_models.py`. |
| Voice "Unavailable: dependencies are missing (torch)" | Install the voice stack (see Setup). |
| Voice "model could not be loaded" | First use downloads weights from Hugging Face. Check the network, then rerun `scripts/download_models.py`. |
| Camera button says permission denied or unsupported | Allow it in the browser, use `localhost`, or upload a file. |
| "template cannot be decrypted" | `data/template.key` or `TRILOCK_TEMPLATE_KEY` changed. Re-enroll, or restore the key. |
| Want a clean slate | Stop the backend and delete `backend/data/` (users, templates, key and results). |
