#!/usr/bin/env python3
"""Generate 720p UI templates for the flower-seed battle pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT.parent / "database" / "battle2"
DEFAULT_OUTPUT_DIR = ROOT / "assets" / "resource" / "image"


@dataclass(frozen=True)
class TemplateCrop:
    source: str
    output: str
    x: int
    y: int
    width: int
    height: int


CROPS = (
    TemplateCrop(
        "step1.png",
        "flower_seed_step1_challenge_prompt.png",
        783,
        352,
        193,
        28,
    ),
    TemplateCrop(
        "step2.png",
        "flower_seed_step2_challenge_button.png",
        720,
        580,
        104,
        35,
    ),
    TemplateCrop(
        "step3.png",
        "flower_seed_step3_start_button.png",
        720,
        580,
        104,
        35,
    ),
    TemplateCrop(
        "step4.png",
        "flower_seed_step4_battle_effect_panel.png",
        971,
        165,
        230,
        45,
    ),
    TemplateCrop(
        "step5.png",
        "flower_seed_step5_effect_button.png",
        1185,
        140,
        94,
        80,
    ),
    TemplateCrop(
        "step5.png",
        "flower_seed_step5_skill2_ready.png",
        224,
        295,
        73,
        75,
    ),
    TemplateCrop(
        "step4.png",
        "flower_seed_skill_ui.png",
        1185,
        570,
        95,
        120,
    ),
    TemplateCrop(
        "step6.png",
        "flower_seed_step6_capture_menu.png",
        172,
        176,
        88,
        24,
    ),
)


def normalize_to_720p(path: Path):
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    images = {
        crop.source: normalize_to_720p(source_dir / crop.source) for crop in CROPS
    }
    normalized_shapes = {image.shape[:2] for image in images.values()}
    if len(normalized_shapes) != 1:
        raise ValueError(
            f"Normalized screenshots do not share one size: {normalized_shapes}"
        )

    for crop in CROPS:
        image = images[crop.source]
        template = image[
            crop.y : crop.y + crop.height,
            crop.x : crop.x + crop.width,
        ]
        if template.shape[:2] != (crop.height, crop.width):
            raise ValueError(
                f"Crop for {crop.output} is outside {crop.source}: "
                f"expected {crop.width}x{crop.height}, got "
                f"{template.shape[1]}x{template.shape[0]}"
            )

        output_path = output_dir / crop.output
        if not cv2.imwrite(str(output_path), template):
            raise RuntimeError(f"Unable to write template: {output_path}")
        print(
            f"{crop.source}: ({crop.x}, {crop.y}, {crop.width}, {crop.height}) "
            f"-> {output_path.name}"
        )


if __name__ == "__main__":
    main()
