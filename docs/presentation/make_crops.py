"""Crop the app screenshots to the part that matters, so the text is readable on a slide.
Run after frontend/e2e/smoke.mjs has written docs/screenshots."""
from pathlib import Path
from PIL import Image

SRC = Path(__file__).resolve().parent.parent / "screenshots"
DST = Path(__file__).resolve().parent / "crops"
DST.mkdir(exist_ok=True)
# name -> (source file, left, top, right, bottom) in the 1360x900 screenshots
CROPS = {
    "enroll": ("02-face-enrolled.png", 270, 55, 1340, 560),
    "signin": ("23-login-biometric-step.png", 250, 225, 1110, 670),
    "pay-risk": ("06-payment-risk.png", 270, 60, 1340, 660),
    "pay-decision": ("08-decision-approved.png", 270, 195, 1340, 790),
    "big-risk": ("09-high-risk-assessment.png", 270, 60, 1340, 710),
    "big-refused": ("11-liveness-refused.png", 270, 200, 1340, 870),
    "dashboard": ("20-dashboard.png", 270, 55, 1340, 800),
    "history": ("12-history.png", 270, 55, 1340, 470),
    "analytics": ("15-analytics-modules.png", 270, 55, 1340, 800),
}
for name, (src, l, t, r, b) in CROPS.items():
    Image.open(SRC / src).convert("RGB").crop((l, t, r, b)).save(DST / f"{name}.png", optimize=True)
    print("wrote", name, (r - l, b - t))
