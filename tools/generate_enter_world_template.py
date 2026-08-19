"""Generate the normalized in-game Enter World button template."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


TARGET_SHORT_SIDE = 720
BUTTON_CROP = (581, 518, 755, 566)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    image = cv2.imread(str(args.source))
    if image is None:
        raise SystemExit(f"Cannot read screenshot: {args.source}")

    height, width = image.shape[:2]
    scale = TARGET_SHORT_SIDE / min(width, height)
    normalized = cv2.resize(
        image,
        (round(width * scale), round(height * scale)),
        interpolation=cv2.INTER_AREA,
    )
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
