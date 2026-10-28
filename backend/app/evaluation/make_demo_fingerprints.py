"""Write a few SYNTHETIC fingerprint images for trying the UI without a dataset.

  python -m app.evaluation.make_demo_fingerprints

Output: data/demo/finger<N>_enroll.png and finger<N>_probe.png (same finger, different
impression) plus finger<N>_other.png... Finger 1 probe should match finger 1 enroll; any
other finger should not. These are generated patterns, not real fingerprints.
"""
import cv2

from ..config import get_settings
from . import synthetic


def main() -> None:
    out = get_settings().data_dir / "demo"
    out.mkdir(parents=True, exist_ok=True)
    for s in (1, 2, 3):
        cv2.imwrite(str(out / f"finger{s}_enroll.png"), synthetic.impression(s, 0))
        cv2.imwrite(str(out / f"finger{s}_probe.png"), synthetic.impression(s, 1))
    print(f"wrote 6 synthetic images to {out}")


if __name__ == "__main__":
    main()
