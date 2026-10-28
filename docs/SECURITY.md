# Security and privacy

This is a prototype and I have not had it reviewed by anyone. This file lists what the code does, what the tests check, and what is still missing. It is not a claim that the application is secure.

## What is protected and how

| Area | Implementation | Test |
|---|---|---|
| Passwords | scrypt (N=2^14, r=8, p=1) with a random 16-byte salt per password, constant-time comparison, minimum length 10, must not equal name or email, maximum 200 characters (stops huge-input hashing). Never returned by the API or written to logs. | `test_password_rules_and_storage`, `test_same_password_gets_different_hashes`, `test_secrets_and_samples_not_in_event_log` |
| Sessions | Random 256-bit bearer tokens, 8 hour expiry, logout revokes. Only the SHA-256 of a token is stored. | `test_logout_revokes_token`, `test_expired_session_rejected`, `test_session_token_not_stored_in_clear` |
| Authentication required | Every endpoint except `GET /api/health`, `POST /api/auth/register` and `POST /api/auth/login`. | `test_every_protected_endpoint_requires_login` (17 endpoints) |
| Login abuse | Same answer for wrong password and unknown email. After 5 failures the account is locked for 15 minutes, including for the correct password. Unknown-email logins still burn one scrypt computation to keep timing similar. | `test_login_does_not_reveal_which_part_was_wrong`, `test_login_lockout_after_repeated_failures` |
| Access control | Roles `user` and `admin`. A user can only read and act on their own account and transactions; other people's records answer 404 (same as missing). Administrators have read access everywhere and cannot enroll biometrics, create transactions, authenticate or verify for anyone. The account of a transaction is taken from the session, never from the request body. | `test_user_cannot_read_or_use_another_users_data`, `test_cannot_enroll_or_delete_for_someone_else`, `test_client_cannot_pick_the_account_of_a_transaction`, `test_admin_is_read_only_for_customers`, `test_dashboard_is_scoped_to_the_user` |
| Admin creation | Only through the command line (`python -m app.cli create-admin`). Self-registration always creates a normal user, so nobody can register themselves as admin. | `make_admin` in tests promotes directly in the database |
| Decision flow cannot be bypassed | A transaction only leaves `pending` through the authentication service. There is no route that sets a decision (PUT, PATCH and DELETE on transactions answer 405). Closing uses a guarded database update, so two simultaneous requests cannot both decide the same transaction. Closed transactions answer 409. | `test_no_route_can_set_a_decision_directly`, `test_closed_transaction_cannot_be_reopened_or_reapproved` |
| Biometric reference tampering | Adding, replacing or removing a biometric reference needs the account password again. A stolen session token alone cannot enroll an attacker's face or voice onto a victim's account. | `test_enrollment_changes_need_the_password` |
| Guessing and score probing | After 5 failed biometric attempts within 15 minutes a user's further attempts (including the standalone `/verify` endpoint) answer 429. Inputs that could not be evaluated do not count, so a broken camera does not lock anyone out. With `TRILOCK_EXPOSE_SCORES_TO_USERS=false` raw and calibrated scores are hidden from normal users in every response, so the decision is the only feedback. | `test_repeated_biometric_failures_lock_further_tries`, `test_unevaluable_input_does_not_trigger_lockout`, `test_scores_hidden_from_users_when_configured` |
| Input validation | Pydantic limits on every field; upload size caps (images 8 MB, audio 12 MB) enforced while reading; unknown modality 404; search text escaped so `%` and `_` are literal and length-capped; SQL goes through SQLAlchemy parameters. | `test_transaction_validation`, `test_oversized_upload_rejected`, `test_search_wildcards_are_literal` |
| Errors | One error shape. Unexpected exceptions return a generic 500 and are logged server-side only. Model failures become "not evaluated", never a match. | `test_model_crash_and_bad_input_do_not_approve` |
| Secrets | No credentials in the repository. Template encryption key from `TRILOCK_TEMPLATE_KEY` or a generated `data/template.key` (mode 600). `.env`, `*.key` and `backend/data/` are git-ignored. | `test_wrong_key_cannot_read` |

## Privacy and retention

- **Raw biometrics are never written by the application.** Photos, recordings and fingerprint images are decoded in memory, turned into an embedding or keypoint set, and discarded. `test_raw_biometric_samples_are_never_persisted` enrolls and verifies a fingerprint image and then searches every file under the data directory (database, templates, key) for the image bytes and PNG signature.
- Caveat: the web framework (Starlette) keeps uploads under 1 MB in memory but writes larger ones to a temporary file in the system temp directory until the request ends. Webcam frames are normally well below that. I did not change it.
- Stored per user: name, email, a generated account number, a password hash, and per modality an encrypted template (embeddings or SIFT descriptors). An embedding is still biometric data. Fernet protects the files at rest; it is not a cancelable template scheme, and the key lives next to the data unless you set the environment variable.
- The audit log (`events`) stores kinds, user ids, modality names, outcome and score values. It does not store samples, filenames, passwords, tokens or email addresses of failed logins (`test_secrets_and_samples_not_in_event_log`).
- Deletion: a user can erase their account (`DELETE /api/users/{id}`, needs the password; also a button on the Enrollment page). It removes the encrypted templates, enrollments, sessions, transactions, attempts and events (`test_erase_account_removes_everything`). Administrators can do the same by command (`python -m app.cli erase-user`).
- Retention: `python -m app.cli purge --days N` deletes events and authentication attempts older than N days and expired or revoked sessions (`test_retention_purge`). Nothing runs it automatically; there is no default retention period.
- Evaluation data: score files in `backend/data/evaluation/` contain raw scores and file paths of public datasets, not images.

## Known gaps

- **No TLS.** Bearer tokens and passwords cross the network in clear text unless you put a TLS-terminating proxy in front. CORS is limited to the Vite dev origins.
- **Token storage in the browser.** The token sits in `sessionStorage`, which any script on the page can read, so an XSS bug would expose it. No Content-Security-Policy headers are set. React escapes output, and I found no raw HTML rendering, but I did not run a scanner.
- **Per-account lockout is a denial-of-service lever.** Anyone who knows an email can lock that account for 15 minutes by failing five logins. There is no per-IP rate limiting and no CAPTCHA, so registration spam and distributed guessing are not limited.
- **Registration reveals whether an email exists** (409). Login does not.
- **Open self-registration** is on by default for the demo. Set `TRILOCK_ALLOW_REGISTRATION=false` for anything shared. There is no email verification and no identity proofing, so whoever types a name owns that account and enrolls their own face for it.
- **Replay and spoofing.** A photo, screen replay or recording of the enrolled person is accepted by the biometric modules, and a captured request could be replayed by anyone holding the session token. There is no liveness detection and no challenge-response.
- **Score leakage is on by default** (`expose_scores_to_users=true`) because the demo is more instructive with it. The approve/reject result itself is also an oracle for an attacker who is willing to burn attempts across many accounts.
- **Audit log is not tamper-evident**, and the SQLite file and key are only protected by file permissions.
- No session listing or "log out everywhere" endpoint (the code has `revoke_all` but no route), no password change or reset flow, no multi-factor for the password itself.
- `/docs` and `/openapi.json` are public, which exposes the API shape.
