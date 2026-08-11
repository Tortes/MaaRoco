#!/usr/bin/env python3
"""Generate background-independent battle UI templates for MaaFramework.

The game renders fixed UI over a changing scene.  This script aligns several
720p-normalized screenshots, keeps pixels that remain stable in every sample,
and paints all variable pixels MaaFramework green (RGB 0, 255, 0).  Pipeline
nodes can then use ``green_mask: true`` to ignore the composited background.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT.parent / "database" / "battle"
DEFAULT_OUTPUT_DIR = ROOT / "assets" / "resource" / "image"
DEFAULT_SOURCES = (
    "stage1.png",
    "stage2.png",
    "stage3.png",
    "stage4.png",
    "failure1.png",
)
MASK_GREEN_BGR = np.array((0, 255, 0), dtype=np.uint8)


@dataclass(frozen=True)
class TemplateRegion:
    output: str
    x: int
    y: int
    width: int
    height: int
    max_channel_spread: int
    minimum_retained_pixels: int


REGIONS = {
    "chat": TemplateRegion(
        output="battle_chat_ui_masked.png",
        x=1253,
        y=455,
        width=60,
        height=56,
        max_channel_spread=16,
        minimum_retained_pixels=600,
    ),
    "report": TemplateRegion(
        output="battle_report_ui_masked.png",
        x=1252,
        y=522,
        width=61,
        height=58,
        max_channel_spread=16,
        minimum_retained_pixels=500,
    ),
    "capture": TemplateRegion(
        output="battle_capture_ui_masked.png",
        x=1098,
        y=615,
        width=95,
        height=105,
        max_channel_spread=24,
        minimum_retained_pixels=250,
    ),
}


def normalize_to_720p(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Unable to read screenshot: {path}")

    height, width = image.shape[:2]
    normalized_width = round(width * 720 / height)
    return cv2.resize(
        image,
        (normalized_width, 720),
        interpolation=cv2.INTER_AREA,
    )


def generate_template(
    images: list[np.ndarray],
    region: TemplateRegion,
    output_dir: Path,
) -> tuple[Path, int, int]:
    crops = []
    for image in images:
        crop = image[
            region.y : region.y + region.height,
            region.x : region.x + region.width,
        ]
        if crop.shape[:2] != (region.height, region.width):
            raise ValueError(
                f"Region for {region.output} is outside a normalized screenshot: "
                f"expected {region.width}x{region.height}, got "
                f"{crop.shape[1]}x{crop.shape[0]}"
            )
        crops.append(crop)

    samples = np.stack(crops).astype(np.int16)
    channel_spread = samples.max(axis=0) - samples.min(axis=0)
    stable_mask = channel_spread.max(axis=2) <= region.max_channel_spread

    # Remove isolated coincidental background pixels while retaining coherent
    # UI strokes, key caps, outlines, and labels.
    stable_mask = cv2.morphologyEx(
        stable_mask.astype(np.uint8) * 255,
        cv2.MORPH_OPEN,
        np.ones((2, 2), dtype=np.uint8),
    ).astype(bool)

    retained = int(np.count_nonzero(stable_mask))
    total = region.width * region.height
    if retained < region.minimum_retained_pixels:
        raise RuntimeError(
            f"{region.output} retained only {retained}/{total} pixels; "
            "the source screenshots may not be aligned"
        )

    template = crops[0].copy()
    template[~stable_mask] = MASK_GREEN_BGR
    output_path = output_dir / region.output
    if not cv2.imwrite(str(output_path), template):
        raise RuntimeError(f"Unable to write template: {output_path}")
    return output_path, retained, total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sources", nargs="+", default=list(DEFAULT_SOURCES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_paths = [source_dir / name for name in args.sources]
    images = [normalize_to_720p(path) for path in source_paths]
    normalized_shapes = {image.shape[:2] for image in images}
    if len(normalized_shapes) != 1:
        raise ValueError(
            f"Normalized screenshots do not share one size: {normalized_shapes}"
        )

    height, width = images[0].shape[:2]
    print(f"sources={len(images)} normalized={width}x{height}")
    for name, region in REGIONS.items():
        output_path, retained, total = generate_template(images, region, output_dir)
        print(
            f"{name}: {output_path.name} retained={retained}/{total} "
            f"({retained / total:.1%})"
        )


if __name__ == "__main__":
    main()
