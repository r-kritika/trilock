# Architecture

TriLock is two programs that talk over HTTP: a FastAPI backend that owns all the logic and data, and a React frontend that only collects input and displays what the backend returns. The frontend never computes a score, a risk level or a decision.

Every request except health, register and login carries a bearer token. `security.current_user` resolves it to a user (or answers 401); routes then check ownership (`owner_only`, `owner_or_admin`) before touching data. See [SECURITY.md](SECURITY.md).

```
Browser (React, Vite dev server :5173)
   |  /api/*  (Vite proxies to :8000 in development)
   v
FastAPI app (backend/app)
   api/routes_*.py        HTTP layer: parse, validate, authorise, call services, shape responses
   security.py            password hashing, sessions, current_user / admin dependencies
   services/              business logic, no HTTP types
       risk.py            rule-based transaction risk
       fusion.py          fixed-threshold and risk-aware decision policies
       authentication.py  create transaction, run modules, fuse, persist the attempt
       enrollment.py      build and store references, report enrollment status
       templates.py       encrypted template files
       privacy.py         account erasure and retention purge
       stats.py           dashboard queries
       demo_scenarios.py  hand-written scenarios for the policy demo table
   biometrics/            one class per modality behind the same interface
       face.py voice.py fingerprint.py calibration.py registry.py types.py
   evaluation/            command line scripts, not imported by the server
   models.py database.py  SQLAlchemy tables and engine
   config.py errors.py    settings from env vars, one error shape for every failure
SQLite file + encrypted templates in backend/data
```

## The authentication request

`POST /api/transactions` stores a transaction for the signed-in user (the account is never taken from the body) and computes its risk from the transaction's attributes plus that user's approved history (mean amount of earlier approved transactions). The decision stays `pending`.

`POST /api/transactions/{id}/authenticate` takes up to three optional files (`face`, `fingerprint`, `voice`) and does this in `services/authentication.py`:

0. Refuse if the transaction is closed, the attempt limit is reached or the user has too many recent failed biometric attempts (429).
1. For every modality, run the module. A missing file, a missing enrollment, a bad input or an exception inside a model all become a `NOT_EVALUATED` result with a reason code. There is no code path that turns a failure into a match.
2. Run both policies on the same list of results and the transaction's risk category.
3. Pick the active policy (`TRILOCK_ACTIVE_POLICY`, default `risk_aware`), store an `AuthAttempt` with the module results and both outcomes, and close the transaction with a guarded update (it only succeeds if the transaction is still open, so concurrent requests cannot both decide it).
4. If the answer is "additional verification" the transaction stays open and the client may submit again. After `max_auth_attempts` (3) non-approved attempts it is closed as rejected, and the explanation says so.

Approved and rejected transactions are closed; a further authenticate call returns 409.

## Data model

| Table | Purpose |
|---|---|
| users | accounts: name, email, generated account number, scrypt password hash, role, failed-login counter and lock time |
| sessions | SHA-256 of each bearer token, expiry, revoked flag |
| enrollments | one row per user and modality: method, sample count, mean quality, template file name |
| transactions | request attributes, risk score/category/factors, current decision and reason |
| auth_attempts | per attempt: every module result, both policy outcomes, active policy, final decision, explanation, latency |
| events | append-only audit log (enrolled, verification, authentication, errors) |
| evaluation_runs | metrics saved by the evaluation scripts, with data source and a synthetic flag |

Templates are not in the database. They are numpy arrays (embeddings or keypoint descriptors) written to `data/templates/` encrypted with Fernet. Raw photos, audio and fingerprint images are decoded in memory and never saved.

## Module interface

Every biometric module implements `enroll(samples) -> (template, quality, n)` and `verify(template, sample) -> ModalityResult`, plus `status()`. `verify` never raises for bad input. A `ModalityResult` carries the status (`match`, `no_match`, `not_evaluated`), the raw score, the calibrated probability, a quality value, the reason code and the latency. The registry builds the three modules from settings. Tests and the API tests swap in fake modules through the same registry, which is how the workflow is tested without models.

## API summary

| Endpoint | Who | Purpose |
|---|---|---|
| GET /api/health | public | status and database check only |
| POST /api/auth/register, /login | public | create account (if enabled), sign in |
| POST /api/auth/logout, GET /api/auth/me | signed in | end session, current user with enrollment status |
| GET /api/users | admin | all accounts |
| GET /api/users/{id}, /enrollments | owner or admin | account and enrollment status |
| POST/DELETE /api/users/{id}/enrollments/{modality} | owner, password required | enroll (multipart `files`, `password`) or remove |
| DELETE /api/users/{id} | owner, password required | erase account and data |
| POST /api/risk/assess | signed in | stateless risk preview |
| POST /api/transactions, GET list, GET one | owner (admin read-only) | transactions; list takes q, decision, risk_category, limit, offset |
| POST /api/transactions/{id}/authenticate | owner | multimodal authentication |
| POST /api/verify/{modality} | owner | run one module alone (counts toward lockout) |
| GET /api/dashboard/stats | signed in | own numbers, or everyone's for admin |
| GET /api/policy | signed in | risk rules and fusion thresholds in force |
| GET /api/evaluation/runs, /policy-demo | signed in | stored measurements; illustrative scenarios |

Errors always look like `{"error": {"code": "...", "message": "..."}}`; validation errors add a `fields` list.

## Frontend

`src/api/client.js` is the only place that calls `fetch`. `src/lib/media.js` wraps the camera and microphone. The microphone path records with `MediaRecorder`, decodes the result and re-encodes it as 16 kHz mono WAV in the browser, because the server has no ffmpeg. Pages live in `src/pages`, shared pieces in `src/components`. `ResultView` renders a stored transaction and is used both right after authentication and on the history detail page, so both show exactly what the backend stored.
