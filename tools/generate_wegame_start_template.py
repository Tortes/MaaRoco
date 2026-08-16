"""Generate the normalized WeGame start-button template from a screenshot."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


TARGET_SIZE = (1280, 720)
BUTTON_CROP = (998, 653, 1210, 697)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    image = cv2.imread(str(args.source))
    if image is None:
        raise SystemExit(f"Cannot read screenshot: {args.source}")

    normalized = cv2.resize(image, TARGET_SIZE, interpolation=cv2.INTER_AREA)
    left, top, right, bottom = BUTTON_CROP
    template = normalized[top:bottom, left:right]
    if template.size == 0:
        raise SystemExit("The configured crop is empty")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), template):
        raise SystemExit(f"Cannot write template: {args.output}")
    print(f"Wrote {args.output} ({template.shape[1]}x{template.shape[0]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
