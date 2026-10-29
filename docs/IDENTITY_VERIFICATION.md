# Does TriLock verify the account holder, or only record a sample?

Short answer: it verifies. During a payment the server loads the encrypted face and voice templates of the account that owns the transaction, compares the new samples against them with SFace and ECAPA-TDNN, and the approve/reject decision is computed from those comparison scores and the transaction's risk. This file says where in the code that happens, what I tested with the real models, what I fixed, and what is still not covered.

## The path of a payment, in code

1. `POST /api/transactions/{id}/authenticate` finds the transaction with `_txn`, which returns 404 unless it belongs to the logged-in user. Nobody can authenticate against someone else's transaction.
2. `authentication.authenticate` calls `run_modality` once per modality with the uploaded sample and the template from `store.load(txn.user_id, modality)`. The user id comes from the transaction, not from the request.
3. `run_modality` never turns a missing thing into a match: no sample is `not_provided`, no enrolled template is `not_enrolled`, a model error is `inference_failed`, a failed quality gate is a reason such as `blurry` or `too_short`. All of them are `not_evaluated`, with no score.
4. Face: YuNet finds the face, SFace gives a 128-d embedding, score is the best cosine against the enrolled embeddings. Voice: ECAPA-TDNN gives a 192-d embedding, score is the cosine against the mean enrolled embedding. Each raw score goes through the module's fitted logistic; **match means calibrated score at least 0.5, which is exactly raw score at least the fitted threshold** (face 0.388, voice 0.454 in `data/calibration.json`).
5. `fusion.risk_aware_fusion` takes the module results and the transaction's risk category and returns approved, rejected or additional verification. Rules that matter for impersonation:
   - Only evaluated modalities count; unusable input adds nothing, never a "match".
   - Every evaluated modality must reach 0.50 (**new**, see below). One clear "no" blocks approval at any risk.
   - Medium needs two modalities. High and critical need face **and** voice.
   - If liveness was required and failed, approval is vetoed.
6. With nothing usable the answer is "additional verification required". It is not an approval and it is not an accusation.

## What I tested, with the real models

`backend/tests/test_identity_flow.py` (51 tests, marked `integration`, skipped if the models are not installed) enrolls three real people (LFW photos, LibriSpeech recordings) and drives the HTTP API. Results from the last run: 51 passed. It checks that:

- each person is approved on their own account with a different photo and a different recording than the enrolled ones, and the result reports SFace and ECAPA as the methods and raw cosine scores above the thresholds;
- every other person's face and voice on that account is rejected at low and medium risk, with both modalities `no_match`;
- the same sample matches its owner's account and fails the others, with a score gap of more than 0.25 (so the decision follows the **enrolled template**, not the sample);
- all wrong combinations (wrong face and wrong voice, right face and wrong voice, wrong face and right voice) across all four risk levels are never approved (48 attempts);
- one-modality attacks by another person are never approved at low, medium or high risk;
- 28 broken-input cases (nothing, garbage bytes, blank picture and silence, 0.5 s of audio, a photo sent as voice, a recording sent as face, empty files) at every risk level always give additional verification, never approval, with no score and a reason code;
- a blurred or very dark photo of the real holder is refused, not guessed;
- degraded samples of a different person are not approved;
- a user with nothing enrolled cannot be approved, and a transaction of another user returns 404.

`backend/scripts/verify_identity.py` does the same at larger scale. Last run (`--people 20`, 15 of the 20 virtual users enrolled; the other 5 had photos the quality gates refused: multiple faces or blurry):

| Check | Result |
|---|---|
| Genuine attempts approved | 38 of 45 (all 15 at low risk; 12/15 high, 11/15 critical) |
| Impostor and partial attempts wrongly approved | 0 of 165 |
| Broken-input attempts approved | 0 of 90 |
| Face cosine, own vs other person | own 0.70 (lowest 0.53), other 0.07 (highest 0.19), threshold 0.388 |
| Voice cosine, own vs other person | own 0.78 (lowest 0.48), other 0.11 (highest 0.25), threshold 0.454 |

The 7 genuine attempts not approved were at high and critical risk where a face or voice sample was unusable or just under its line, which gives "additional verification", the intended fail-safe. Two further approvals were "wrong face unusable + the holder's own voice" at **low** risk: the other person's photo was refused by the quality gate, so only the holder's real voice was evaluated, and low risk accepts one matching modality. That is the documented rule, not an impostor getting in, but it is the reason low risk is the weakest spot (see limitations).

Raw outputs are not stored; rerun the script (it takes a few minutes).

## What I fixed

**A modality that said "no match" could be outvoted.** The low and medium bands only had conflict floors of 0.00 and 0.15, so a face at 0.99 and a voice at 0.45 averaged to an approval. In the real flow that meant the right face with a wrong voice could pass at low risk if the average cleared 0.60. All four bands now use a 0.50 floor (each module's own match line). Tests: `test_a_borderline_no_match_cannot_be_outvoted_at_any_risk`, `test_any_single_no_match_blocks_approval_whichever_modality_it_is`, `test_unusable_input_is_not_a_no_match_and_a_clear_mismatch_is_still_rejected`, `test_a_modality_exactly_at_its_match_line_counts_as_a_match`. Cost, measured on the simulated fusion evaluation: friction for genuine users with all inputs present went from 4.7% to 6.8%, and the 0.1% worst bypass went to 0.0%.

Nothing else in the matching path needed changing. The models were already used for the actual decision.

## Limits that remain

- **Low-risk payments accept one matching modality.** At low risk a photo or recording of the holder, if the attacker has one, matches. Liveness is only required from high risk by default. Setting `TRILOCK_LIVENESS_REQUIRED_FROM=low` closes this at a usability cost.
- **Lookalikes, siblings, twins.** Not tested at all. The impostors here are unrelated people.
- **Datasets are small and clean.** LFW photos are old and low-resolution; LibriSpeech is read speech in quiet conditions. Voice false accepts over repeated splits were 1.4% ± 1.8% with only 13 speakers per half. These do not describe a laptop webcam and microphone in a real room.
- **Head-turn liveness has never been run with a real person turning their head** (only simulated attacks and the fake-camera video). Voice liveness depends on `faster-whisper` being installed.
- **Enrollment is not identity proofing.** Whoever enrolls is the enrolled person. If an attacker enrolls on an account, TriLock will faithfully verify the attacker. Enrollment changes require the password and proof of the existing biometrics, but the first enrollment is trusted.
- **An unusable sample is "no evidence", not a veto.** A blurry photo of an impostor next to the holder's genuine voice is evaluated on the voice alone at low risk. At medium and above that is not enough.
- **Voice-only genuine friction.** A real holder with a weaker recording sits close to the voice line and is sometimes asked for more verification.
- This is a student project. It has not been security-audited and is not production ready.
