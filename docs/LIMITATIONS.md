# Limitations

This is a student prototype. These are the things that stop it from being more than that.

## Hardware

- **Fingerprint** is optional and not needed for sign-in, payments or any policy. A browser cannot read a laptop fingerprint reader, and no scanner SDK is integrated. The fingerprint module only compares fingerprint images (dataset or exported). Real fingerprint capture is not implemented.
- Face and voice capture depend on the browser giving camera and microphone access, which needs `localhost` or https. Upload is the fallback.
- Liveness exists only as challenge-response for face (head turn) and voice (spoken words), and only above a risk level. It stops still photos and pre-recorded audio. It does not stop a video of the owner turning, a deepfake, voice cloning or a mask, fingerprint has none, and the head-turn check has never run on a real webcam. Its thresholds come from a simulation on LFW stills, not a spoofing dataset. Below the required risk level, and for the verification scores themselves, a photo or recording of the enrolled person is still accepted. See [SECURITY.md](SECURITY.md).

## Data and models

- Face and voice were measured on public datasets (see [EVALUATION.md](EVALUATION.md)), which are not banking conditions. LFW is mostly well-lit news photos; Mini LibriSpeech is clean read speech with only 26 speakers (13 per evaluation half), so the voice interval on FAR reaches 6.9%. Phone microphones, noisy rooms and compressed calls will do worse. SFace may have seen some LFW identities in training, which I cannot check.
- The fingerprint matcher has only been exercised on synthetic prints (generated ridge patterns). Its accuracy on real fingerprints is unknown, and on synthetic data it already fails on strong noise (100% false rejects at sigma 40) and loses about 18% of genuine matches on half-occluded prints. I did not find a freely downloadable real fingerprint dataset that I could fetch automatically (SOCOFing and FVC need registration or manual download). If you have one, `run_modality` takes the layout `<root>/<subject>/<images>`.
- The multimodal evaluation pairs unrelated people from different datasets into "virtual users" (assuming independent modalities), uses synthetic fingerprint scores, and draws the transaction risk level from a made-up mix. It tests the fusion code and policy shape, not real customer behaviour. Attacks are simulated by score substitution (one modality beaten, or only one submitted), not by actually spoofing anything, and an "additional verification" outcome is counted as stopping the attacker.
- Thresholds come from a logistic fit on a calibration half, not from a target false accept rate, because the trial counts are too small to estimate small rates. Confidence intervals assume independent trials, which they are not.
- The calibration maps are simple logistic fits (or documented defaults) and a fit on one dataset does not carry over to another sensor.
- The risk engine is hand-weighted rules. It has no connection to real fraud data.
- The fusion thresholds and bands are reasoned starting values and have not been tuned on any data.
- Voice model weights are downloaded from Hugging Face on first use, and nothing is pinned to a hash.

## Privacy and security

The full list is in [SECURITY.md](SECURITY.md). The ones that matter most:

- Passwords and bearer tokens travel unencrypted unless a TLS proxy is added. There is no TLS in the project.
- Sessions live in `sessionStorage`, readable by any script on the page. No CSP headers.
- Lockouts are scoped to device and network so they cannot be used against the owner, but an attacker with many addresses is only slowed, there is no CAPTCHA, no rate limit on registration, and registration is open by default.
- Enrollment is not identity proofing and there is no email verification. Changing biometrics on an account that already has some needs matching proof samples, but the first enrollment needs only the password, proof samples are not liveness-checked, and recovery relies on an administrator checking with the owner by another channel (there is no mail service). See [SECURITY.md](SECURITY.md).
- Template encryption is at rest only and the key sits next to the data unless provided through the environment. Embeddings are still biometric data.
- Large uploads (over 1 MB) are spooled to a temporary file by the web framework until the request ends.
- Scores are shown to users by default; the accept/reject answer still works as an oracle for patient attackers.
- The audit log is not tamper-evident, there is no password reset or change flow, and no self-service "sign out everywhere".

## Deployment and scale

- SQLite, one process, in-memory model state (the guarded transaction update makes concurrent requests safe within SQLite, which I did not stress test). Fine for a demo, not for concurrent load. There are no database migrations; changing the schema means deleting `backend/data/` or migrating by hand.
- The system is not a production banking service and must not be used to protect real accounts.

## Not done

- Liveness detection, score-level learned fusion, a trained risk model, per-user behavioural history beyond the mean approved amount, and real scanner integration.
