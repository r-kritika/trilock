# Implementation notes

## Face

`backend/app/biometrics/face.py`. OpenCV's `FaceDetectorYN` (YuNet) finds faces and `FaceRecognizerSF` (SFace) aligns the face and produces a 128-dimensional embedding. Both are ONNX files from the OpenCV Zoo; no torch needed.

Input checks, in order: file size, decodable image, at least 160 px on the short side, a face found, not two comparably large faces, detector score at least 0.85, face at least 80 px, sharpness (variance of the Laplacian on the aligned 112x112 crop) at least 25, mean brightness between 40 and 225. Each failure has its own reason code (`no_face`, `multiple_faces`, `blurry`, `bad_lighting`, ...). The quality value is 0.5 sharpness + 0.3 face size + 0.2 brightness, each normalised to 0..1. It is a heuristic, not a trained quality model.

Verification is the cosine similarity between the probe embedding and the enrolled embeddings (the best of up to 5 enrolled images). The documented SFace threshold is 0.363 and that is the starting decision point.

There is no liveness detection. A photo of the enrolled person held up to the camera is accepted like the person.

## Voice

`voice.py`. Audio is decoded with libsndfile (WAV, FLAC, OGG), averaged to mono and resampled to 16 kHz. Gates: not empty, under the size limit, at least 2 s, not near silent (RMS), not heavily clipped, and a crude energy-based check for real speech (loud versus quiet frames, at least 8 dB apart, enough loud frames). Audio longer than 20 s is cut.

The embedding comes from SpeechBrain's `spkrec-ecapa-voxceleb` (ECAPA-TDNN, 192 dimensions). Verification is the cosine between the probe embedding and the mean of the enrolled embeddings. The SpeechBrain example uses 0.25 as the threshold, which is the starting decision point here. The model loads lazily on first use; if torch/speechbrain are missing or the weights cannot be downloaded the module reports `model_unavailable` and the failure is retried at most every 30 s.

This is speaker verification, not speech recognition. There is no replay or synthetic-voice detection.

## Fingerprint (experimental)

`fingerprint.py`. A normal laptop browser cannot read a fingerprint sensor, so this module works on fingerprint images: dataset impressions or a scanner export. This is stated in the UI.

Pipeline: grayscale, resize to 360 px height, build a foreground mask from local contrast (reject the image if less than 30% is ridge area), local normalisation plus CLAHE, SIFT keypoints inside the eroded mask (up to 600), Lowe ratio test (0.7) against the enrolled keypoints, then RANSAC fitting a similarity transform (rotation, translation, scale; 3 px tolerance). The score is the number of RANSAC inliers; the best enrolled impression counts. Only keypoint coordinates and descriptors are stored.

This is a general image-feature matcher, not a minutiae matcher, and it was only tuned and tested against synthetic prints from `evaluation/synthetic.py` (Gabor-filtered noise with an orientation field). The default threshold of 14 inliers is a guess that works there. On real prints with nonlinear skin distortion, dry or wet fingers and partial contact it will need recalibration and may perform much worse. Nothing in this repo measures its accuracy on real fingerprints.

## Calibration

The three raw scores are on different scales (two cosines with different typical ranges, and an inlier count). Each module maps its raw score through a logistic function

    p = 1 / (1 + exp(-(raw - center) / scale))

so p is "probability this is the enrolled person" and p = 0.5 exactly at the module's threshold. A module returns `match` when p is at least 0.5.

Defaults (`calibration.py`): face center 0.363 scale 0.06; voice center 0.25 scale 0.07; fingerprint center 14 scale 3. The face and voice centers come from the model documentation; all the scales and the fingerprint values are my own starting guesses, so p is only roughly a probability. On the datasets I tested the documented voice default was too loose (about 11% false accepts in an early run), which is why the fit matters. `fit_logistic` fits both numbers from labelled genuine and impostor scores. When the two classes do not overlap, the fit's scale would shrink toward zero and turn every score into exactly 0 or 1, so the scale is floored at 10% of the gap between the genuine and impostor means. and `run_modality --write-calibration` saves the fit from the calibration half of the primary split to `data/calibration.json`, which the app loads on start (never for synthetic data). The result page labels a score "default (uncalibrated) mapping" when no fitted file is in use. A fit on one dataset does not transfer automatically to the microphone and camera of a real deployment.

## Transaction risk

`services/risk.py`. A transparent additive score from 0 to 100; each contribution is returned and shown.

| Factor | Points |
|---|---|
| Amount (USD), linear between (0,0) (100,2) (500,6) (2000,15) (10000,30) (50000,40) | 0 to 40 |
| New recipient | 20 |
| International recipient | 12 |
| New device | 10 |
| Transaction type: cash withdrawal 5, wire transfer 8, others 0 | 0 to 8 |
| Amount above 3x the user's mean approved amount (needs at least 3 approved transactions) | 12 |

Categories: low below 25, medium 25 to 49.99, high 50 to 74.99, critical 75 and above. These weights are chosen by hand, not learned from fraud data. It is not a fraud detection model. All of it can be overridden through the policy file (below).

## Fusion and decisions

`services/fusion.py`. Both policies are pure, deterministic functions of the module results, the risk category and a config.

**A. Fixed threshold (baseline).** Weighted mean of the calibrated scores of the evaluable modalities (equal weights), approve at 0.70 or above, otherwise reject. It ignores risk and input quality. If no modality could be evaluated it asks for another verification instead of guessing.

**B. Risk-aware (proposed).**

1. Reliability weight per evaluable modality: `w * (0.4 + 0.6 * quality)`. A poor-quality sample counts less but never zero.
2. Fused score: reliability-weighted mean of calibrated scores.
3. Coverage: sum of reliability weights divided by the sum of base weights. This is how much of the full three-modality evidence we have, so it is 1.0 for three perfect samples and about 0.33 for one.
4. The transaction's risk category selects a band:

| Risk | approve at | reject below | min modalities | min coverage | conflict floor |
|---|---|---|---|---|---|
| low | 0.60 | 0.30 | 1 | 0.30 | 0.00 |
| medium | 0.70 | 0.35 | 2 | 0.50 | 0.15 |
| high | 0.80 | 0.40 | 2 | 0.60 | 0.25 |
| critical | 0.88 | 0.45 | 3 | 0.70 | 0.35 |

5. Decision: fused below the reject threshold gives **rejected**. Fused at or above the approve threshold, with enough modalities, enough coverage, and no evaluable modality below the conflict floor, gives **approved**. Everything else gives **additional verification required**. Nothing evaluable also gives additional verification, because "could not be evaluated" is not evidence of an impostor.

So risk changes the policy in three ways: a higher bar, more required modalities, and less tolerance for one modality contradicting the others. It is not the biometric score multiplied by a risk number. Missing modalities never add to the fused score. They only reduce coverage, which is what stops a single excellent face score from approving a critical transaction.

All numbers above are experimental starting points chosen by reasoning, not tuned on transaction data. They are meant to be changed. A JSON file named in `TRILOCK_POLICY_FILE` overrides any of them, for example:

```json
{"fusion": {"fixed_threshold": 0.8, "bands": {"high": {"approve": 0.85}}},
 "risk": {"new_recipient_points": 25, "high_from": 45}}
```

Unknown keys are rejected at startup so a typo cannot silently do nothing.

## Privacy and storage

- Raw photos, recordings and fingerprint images are processed in memory and discarded.
- Templates are Fernet-encrypted at rest with a key from `TRILOCK_TEMPLATE_KEY` or an auto-generated `data/template.key` (mode 600, git-ignored).
- An embedding is still sensitive biometric data and Fernet only protects the files at rest. These are not cancelable or irreversible templates, and there is no template protection scheme beyond encryption.
- The audit log stores outcomes and scores, not samples.

## Things the evaluation taught me about the design

- The fixed baseline averages only the modalities that are present. That makes it vulnerable to an omission attack: beat one modality, leave the rest empty. The risk-aware policy blocks this above low risk because of the minimum-modality and coverage rules. The cost is friction, and a static "require 2 modalities" rule blocks it too, so the value of the risk bands is mostly in letting low-risk transactions through with one modality. See [EVALUATION.md](EVALUATION.md).
- The fingerprint matcher uses ratio 0.7 and a 3 px RANSAC tolerance. An earlier setting (0.8 and 5 px) let random matches line up; the change was tuned on synthetic identities not used for reporting.
- The reject threshold is only reached when evidence is clearly against the user. A pile of weak scores lands in "additional verification", capped at 3 attempts by `max_auth_attempts`.

## Access control and abuse limits

Short version: bearer sessions, scrypt passwords, per-user data isolation, password re-entry for enrollment changes, login and biometric lockouts, guarded transaction closing. Full table with tests in [SECURITY.md](SECURITY.md). The lockout windows, session length, password length and score visibility are settings (`TRILOCK_*`, see `config.py`).
