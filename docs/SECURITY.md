# Security and privacy

This is a prototype and nobody independent has reviewed it. This file lists what the code does, which test checks it, and what is still missing. It is not a claim that the application is secure.

## What is protected and how

| Area | Implementation | Tests |
|---|---|---|
| Passwords | scrypt (N=2^14, r=8, p=1), random 16-byte salt per password, constant-time comparison, minimum length 10, must not equal name or email, maximum 200 characters. Never returned by the API or written to logs. | `test_password_rules_and_storage`, `test_same_password_gets_different_hashes`, `test_secrets_and_samples_not_in_event_log` |
| Sessions | Random 256-bit bearer tokens, 8 hour expiry, logout revokes. Only the SHA-256 of a token is stored. | `test_logout_revokes_token`, `test_expired_session_rejected`, `test_session_token_not_stored_in_clear` |
| Authentication required | Every endpoint except `GET /api/health`, `POST /api/auth/register` and `POST /api/auth/login`. The two biometric sign-in endpoints need the short-lived pre-auth token. | `test_every_protected_endpoint_requires_login`, `test_password_alone_does_not_give_a_usable_session` |
| Access control | Roles `user` and `admin`. Users only reach their own account and transactions; other people's records answer 404. Admins can read everything but cannot enroll, create transactions, authenticate or verify for anyone. The account of a transaction comes from the session, never from the request body. | `test_user_cannot_read_or_use_another_users_data`, `test_cannot_enroll_or_delete_for_someone_else`, `test_client_cannot_pick_the_account_of_a_transaction`, `test_admin_is_read_only_for_customers`, `test_dashboard_is_scoped_to_the_user` |
| Admin creation | Only from the command line (`python -m app.cli create-admin`). Registration always makes a normal user. | |
| Decision flow cannot be bypassed | A transaction leaves `pending` only through the authentication service. No route sets a decision (PUT, PATCH, DELETE on transactions answer 405). Closing is a guarded database update, so two simultaneous requests cannot both decide one transaction. | `test_no_route_can_set_a_decision_directly`, `test_closed_transaction_cannot_be_reopened_or_reapproved` |
| Input validation | Pydantic limits on every field; upload size caps (images 8 MB, audio 12 MB) enforced while reading; search text escaped so `%` and `_` are literal; SQL only through SQLAlchemy parameters. | `test_transaction_validation`, `test_oversized_upload_rejected`, `test_search_wildcards_are_literal` |
| Errors | One error shape. Unexpected exceptions give a generic 500 and are logged server-side only. A model failure becomes "not evaluated", never a match. | `test_model_crash_and_bad_input_do_not_approve` |
| Secrets | No credentials in the repository. Template key from `TRILOCK_TEMPLATE_KEY` or a generated `data/template.key` (mode 600). `.env`, `*.key`, `backend/data/` are git-ignored. | `test_wrong_key_cannot_read` |

### Signing in: password, then live face and voice

- **Accounts with face and voice enrolled:** the password opens only a *pre-auth* session (5 minutes, spent by the first success) that can do nothing except answer a liveness challenge. The full session is issued only if the face **and** the voice pass the liveness check (head turn, three spoken words) and **both** match the enrolled references. There is no weighting that lets a strong voice make up for a weak face.
- **Accounts missing face or voice:** a *limited* session that reaches the enrollment and recovery endpoints and nothing else (`403 enrollment_incomplete` elsewhere). It becomes a full session when the second of the two is enrolled. Enrolling it needs proof of the first, so the upgrade never grants more than that proof did.
- **Payments** need face and voice enrolled (`409 enroll_first` otherwise). **Fingerprint is optional** for sign-in, payments and the fusion policy.
- A password entry allows 5 biometric tries; each try uses up its challenge; after that the password must be entered again. Failures share the device-scoped lockouts below.
- **Administrators** have no biometrics and sign in with the password only.
- Someone who cannot pass the biometric step can file a recovery request from the pre-auth session (the password is asked for again), see below.
- If the camera, microphone or recognizer cannot work on a machine, `TRILOCK_LOGIN_BIOMETRICS=off` returns to password-only sign-in. `TRILOCK_LOGIN_LIVENESS=false` keeps the biometric step but judges one photo and one recording on identity only (no head turn, no spoken words), which a photo or recording of the owner can pass.

Tests: `tests/test_login_biometric.py` (21 tests): `test_new_account_gets_a_limited_session_and_is_upgraded_when_face_and_voice_are_enrolled`, `test_password_alone_does_not_give_a_usable_session`, `test_both_modalities_must_match`, `test_a_flat_photo_or_replayed_audio_cannot_sign_in`, `test_missing_face_or_voice_fails_not_passes`, `test_challenges_work_once_and_a_new_one_can_be_requested`, `test_a_password_entry_allows_only_a_few_biometric_tries`, `test_biometric_failures_at_sign_in_share_the_lockout`, `test_sign_in_fails_closed_when_the_liveness_checkers_are_missing`, `test_fingerprint_is_optional_everywhere`, `test_payments_need_face_and_voice_enrolled`, `test_someone_who_cannot_pass_the_biometric_step_can_still_ask_for_recovery`.

What this does not do: a brand-new account with nothing enrolled is protected by the password alone until face and voice exist (there is nothing to protect yet, but whoever has the password can enroll their own). Sign-in is only as strong as the liveness check, which does not stop videos, deepfakes or voice cloning (below). A user whose face changes is locked out until a recovery is approved.

### Lockouts aimed at the attacker, not the owner

The first version locked a whole account after 5 failures, so anyone who knew an email could lock the real owner out. A failure is now attributed to a **source**: a random device id the browser keeps (sent as `X-Device-Id`, only its hash stored) and a hashed network address.

- The owner's **known device** (it has signed in successfully before) has its own allowance (10 failures per 15 minutes, for typos) and is never affected by anyone else's failures.
- An **unknown source** is blocked after 5 failures against one account, or after 20 failures across accounts from one address.
- If many unknown sources hammer one account (30 failures), all unknown sources are blocked, but devices that are at least 24 hours old keep working.
- A device id costs nothing to invent, so only 3 new devices per account per day are allowed, and a freshly made device does not count as established.
- Biometric attempts follow the same logic: 5 failures per device or address, and 15 per account across all sources, which never blocks an established device.
- `X-Forwarded-For` is ignored unless `TRILOCK_TRUST_PROXY_HEADERS=true`; otherwise a client could reset its own counter by changing a header.

Tests: `test_attacker_cannot_lock_the_owner_out_of_login`, `test_owner_known_device_has_its_own_higher_allowance`, `test_unknown_sources_are_blocked_together_but_established_devices_keep_working`, `test_one_network_cannot_hammer_many_accounts`, `test_new_devices_per_day_are_limited`, `test_proxy_header_is_ignored_unless_trusted`, `test_attacker_failures_do_not_block_the_owners_biometrics`, `test_repeated_biometric_failures_lock_further_tries`, `test_unevaluable_input_does_not_trigger_lockout`.

What this does not do: an attacker with many network addresses is not stopped, only slowed. A brand-new owner on a new device during an attack can still be blocked until the window passes.

### Changing biometrics needs more than the password

Adding, replacing, removing or erasing needs the password **and**, once the account has any biometrics, fresh samples that match the enrolled ones: 2 of them when 2 or more are enrolled, otherwise the one that exists (`TRILOCK_ENROLLMENT_PROOF_MODALITIES`). Only the first enrollment on an empty account needs just the password. Wrong proof samples count as failed biometric attempts. Tests: `test_stolen_password_cannot_replace_the_owners_biometrics`, `test_two_proofs_are_required_when_two_or_more_are_enrolled`, `test_failed_proofs_feed_the_lockout`, `test_proof_for_a_modality_that_is_not_enrolled_counts_for_nothing`.

### Recovery when someone cannot provide their biometrics

There is deliberately no way for one administrator to wipe someone's biometrics immediately.

1. The signed-in owner files a request with their password and a reason.
2. The owner sees a banner and can cancel it while it is pending.
3. An administrator can approve only after a **cooling-off period** (24 hours by default), and is told to confirm with the person through another channel first. The project has no mail service, so that check is manual.
4. Approval deletes the references (it cannot add any) and starts a **probation** (72 hours by default) in which `high` and `critical` transactions are rejected at creation, whoever re-enrolls next.

Everything is in the audit log. Tests: `test_there_is_no_direct_admin_reset_any_more`, `test_recovery_request_needs_password_and_enrolled_biometrics`, `test_owner_sees_pending_request_and_can_cancel_it`, `test_admin_cannot_approve_during_cooling_off`, `test_approval_after_cooling_off_wipes_references_and_starts_probation`, `test_probation_blocks_high_value_transactions_only_until_it_ends`, `test_denied_request_changes_nothing`.

Residual risk: someone who knows the password, files a request, and is approved by an administrator who does not verify, can enroll their own biometrics, and is limited to low and medium transactions for 72 hours. A real owner who never signs in during the waiting period will not see the banner.

### Spoofing and liveness

Biometric samples can be faked (a photo, a recording). Liveness checks are applied from a configurable risk level upward (`TRILOCK_LIVENESS_REQUIRED_FROM`, default `high`):

- **Face: head-turn challenge.** The server picks left or right at random; the browser films about 3 seconds (10 frames). The check needs the nose to move relative to the eyes by at least 0.25 eye distances in the requested direction, a parallax test (a homography fitted on the eyes and mouth corners must mispredict the nose by at least 0.15, which a flat photo does not), no abrupt jump between frames (stops swapping two photos), and the same identity at the start and end.
- **Voice: spoken words.** Three random words; a small speech recognizer must hear at least 2 of them (`TRILOCK_SPOKEN_WORDS_NEEDED`). The speaker-verification model still decides whose voice it is, on the same audio.
- Challenges are one-time, per user and expire after 90 seconds. At or above the required risk, a still photo or a free recording is not accepted for face and voice; fingerprint has no liveness check.
- It fails closed: if a check cannot run, that modality counts as "not evaluated", never as a pass. A liveness check that **fails** vetoes approval on that attempt even when other modalities match, and counts toward its own, looser lockout (10 per 15 minutes) so it does not use up the ordinary biometric allowance.

Tests: 30 geometry tests in `tests/test_liveness.py` (3D head model against a flat tilted photo, 20 noise seeds), 13 workflow tests in `tests/test_liveness_api.py`, and real-model integration tests. Measurements are in [EVALUATION.md](EVALUATION.md).

**What liveness does NOT stop** (please read):

- A **video** of the owner turning to the requested side, or a real-time face puppet / deepfake. The challenge makes a pre-recorded video harder only because the direction is random.
- **Voice cloning**: someone who types the three words into a text-to-speech system in the owner's voice passes the content check, and a clone may also pass the speaker model.
- A real 3D mask, or recordings of the owner saying every word of the vocabulary.
- **Attackers who control the client** can send any frames or audio they like; the checks run on the server but the capture does not.
- Fingerprint: no liveness at all, and it is experimental.
- The thresholds come from a simulation on LFW stills, not from a spoofing dataset, and the head-turn check has never been run on a real webcam. The measured numbers say nothing about real attacks.

## Privacy and retention

- **Raw biometrics are never written by the application.** Photos, frames, recordings and fingerprint images are decoded in memory, turned into an embedding or keypoint set, and discarded. `test_raw_biometric_samples_are_never_persisted` enrolls and verifies a fingerprint image and searches every file under the data directory for its bytes. Liveness frames and spoken-challenge audio take the same path.
- Caveat: the web framework (Starlette) keeps uploads under 1 MB in memory but writes larger ones to a temporary file in the system temp directory until the request ends. A burst of 10 camera frames is sent as 10 separate parts, each normally well under that. I did not change it.
- Stored per user: name, email, generated account number, password hash, and per modality an encrypted template. Each transaction also keeps the hour of day the browser reported, used to learn a user's usual hours. An embedding is still biometric data. Fernet protects files at rest; it is not a cancelable template scheme, and the key lives next to the data unless set in the environment.
- Devices are stored as a hash of a random id; network addresses as a truncated hash. Both can be re-identified by anyone who can guess the input, so treat them as pseudonymous, not anonymous.
- The audit log stores event kinds, user ids, modality names, outcomes and score values, hashed device and address, and nothing from the spoken challenge. It never stores samples, filenames, passwords, tokens or the email of a failed login. Stored authentication attempts (not the audit log) keep the words the recognizer heard in a spoken challenge, up to 200 characters.
- Deletion: a user can erase their account (password and biometric proof required); `python -m app.cli erase-user` does it for an admin. It removes templates, enrollments, sessions, devices, recovery requests, transactions, attempts and events.
- Retention: `python -m app.cli purge --days N` deletes old events and authentication attempts and expired sessions. Nothing runs it automatically; there is no default retention period.

## Known gaps

- **No TLS.** Tokens and passwords cross the network in clear text unless a TLS proxy sits in front. CORS is limited to the Vite dev origins.
- **Token storage.** The token sits in `sessionStorage`, readable by any script on the page. No Content-Security-Policy headers. A device id in `localStorage` has the same exposure.
- **No per-address rate limiting on registration**, no CAPTCHA, no email verification, no identity proofing. Open self-registration is on by default (`TRILOCK_ALLOW_REGISTRATION=false` closes it).
- **Registration reveals whether an email exists** (409). Login does not.
- **The recovery workflow depends on an administrator doing the manual check.** There is no second channel to the owner.
- **Score leakage is on by default** (`expose_scores_to_users=true`) and the accept/reject answer is still an oracle for patient attackers.
- **Audit log is not tamper-evident**; the SQLite file and key are protected only by file permissions.
- No password change or reset, no "sign out everywhere" route, no multi-factor for the password itself.
- `/docs` and `/openapi.json` are public.
- The liveness challenges live in memory: a restart or a second server process forgets them (users just get a new one).
