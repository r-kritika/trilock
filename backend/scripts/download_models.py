"""Download the model files TriLock needs.

  python scripts/download_models.py            # face (ONNX, ~39 MB) + voice (ECAPA, ~80 MB)
  python scripts/download_models.py --face-only

Face models come from the OpenCV Zoo on GitHub. The voice model is fetched through SpeechBrain
from Hugging Face and the speech recognizer (spoken liveness challenge, ~75 MB) through faster-whisper;
both need requirements-ml.txt installed.
"""
import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
FACE = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--face-only", action="store_true")
    args = ap.parse_args()
    MODELS.mkdir(exist_ok=True)
    for name, url in FACE.items():
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 100_000:
            print(f"have {name}")
            continue
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(url, dest)
    if args.face_only:
        return 0
    try:
        sys.path.insert(0, str(ROOT))
        from app.biometrics.voice import MODEL_SOURCE
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier
        EncoderClassifier.from_hparams(source=MODEL_SOURCE, savedir=str(MODELS / "ecapa"), run_opts={"device": "cpu"})
        print("voice model ready")
    except ImportError as e:
        print(f"voice model skipped: {e}. Install requirements-ml.txt first.")
        return 1
    try:
        from faster_whisper import WhisperModel
        WhisperModel("tiny.en", device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"))
        print("speech recognizer (for the spoken liveness challenge) ready")
    except ImportError as e:
        print(f"speech recognizer skipped: {e}. Install requirements-ml.txt first.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
