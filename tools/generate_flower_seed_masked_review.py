#!/usr/bin/env python3
"""Build masked flower-seed UI template candidates for visual review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT.parent / "database" / "battle2"
OUTPUT_DIR = ROOT / "review" / "flower_seed_templates"
MASK_GREEN_BGR = (0, 255, 0)


@dataclass(frozen=True)
class ReviewTemplate:
    source: str
    output: str
    label: str
    crop: tuple[int, int, int, int]
    build_mask: Callable[[np.ndarray], np.ndarray]


def normalize_to_720p(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    # MaaFramework normalizes Win32 screenshots to the pipeline coordinate
    # system (1280 x 720), even when the client area is 2560 x 1380.
    return cv2.resize(image, (1280, 720), interpolation=cv2.INTER_AREA)


def rounded_rectangle(
    mask: np.ndarray,
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
    radius: int,
) -> None:
    x1, y1 = top_left
    x2, y2 = bottom_right
    cv2.rectangle(mask, (x1 + radius, y1), (x2 - radius, y2), 255, -1)
    cv2.rectangle(mask, (x1, y1 + radius), (x2, y2 - radius), 255, -1)
    for center in (
        (x1 + radius, y1 + radius),
        (x2 - radius, y1 + radius),
        (x1 + radius, y2 - radius),
        (x2 - radius, y2 - radius),
    ):
        cv2.circle(mask, center, radius, 255, -1, lineType=cv2.LINE_AA)


def step1_mask(crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    light = cv2.inRange(hsv, np.array([0, 0, 120]), np.array([179, 115, 255]))
    light = cv2.morphologyEx(
        light,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 5)),
    )
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    main = contours[0]
    cv2.drawContours(mask, [main], -1, 255, -1, cv2.LINE_AA)
    key_contour = contours[1]
    key_mask = np.zeros_like(mask)
    cv2.drawContours(key_mask, [key_contour], -1, 255, -1, cv2.LINE_AA)
    key_mask = cv2.dilate(
        key_mask,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
        iterations=1,
    )
    mask = cv2.bitwise_or(mask, key_mask)
    return mask


def dialog_button_mask(crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    light = cv2.inRange(hsv, np.array([0, 0, 120]), np.array([179, 115, 255]))
    light = cv2.morphologyEx(
        light,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 7)),
    )
    contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    main = max(contours, key=cv2.contourArea)
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [main], -1, 255, -1, cv2.LINE_AA)
    return mask


def skill_card_mask(crop: np.ndarray) -> np.ndarray:
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.ellipse(mask, (29, 61), (11, 9), 0, 0, 360, 255, -1, cv2.LINE_AA)
    rounded_rectangle(mask, (58, 26), (94, 48), 10)
    card = np.array(
        [(68, 31), (116, 32), (123, 73), (113, 85), (65, 81), (62, 45)],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [card], 255, lineType=cv2.LINE_AA)
    cv2.ellipse(mask, (62, 83), (11, 11), 0, 0, 360, 255, -1, cv2.LINE_AA)
    rounded_rectangle(mask, (91, 74), (124, 94), 9)
    rounded_rectangle(mask, (53, 88), (124, 108), 10)
    return mask


def capture_ball_mask(crop: np.ndarray) -> np.ndarray:
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    header = np.array(
        [
            (46, 20),
            (116, 19),
            (120, 43),
            (49, 47),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [header], 255, lineType=cv2.LINE_AA)
    cv2.ellipse(mask, (33, 68), (11, 9), 0, 0, 360, 255, -1, cv2.LINE_AA)
    cv2.circle(mask, (78, 66), 28, 255, -1, cv2.LINE_AA)
    rounded_rectangle(mask, (54, 88), (104, 109), 10)
    return mask


TEMPLATES = (
    ReviewTemplate(
        "step1.png",
        "01_challenge_prompt_masked.png",
        "STEP 1: F + CHALLENGE",
        (725, 355, 220, 48),
        step1_mask,
    ),
    ReviewTemplate(
        "step2.png",
        "02_challenge_button_masked.png",
        "STEP 2: CHALLENGE BUTTON",
        (660, 590, 165, 60),
        dialog_button_mask,
    ),
    ReviewTemplate(
        "step3.png",
        "03_start_button_masked.png",
        "STEP 3: START BUTTON",
        (660, 572, 165, 60),
        dialog_button_mask,
    ),
    ReviewTemplate(
        "step4.png",
        "04_skill_ui_masked.png",
        "STEP 4/5: SKILL CARD 1",
        (150, 210, 140, 110),
        skill_card_mask,
    ),
    ReviewTemplate(
        "step6.png",
        "05_capture_ui_masked.png",
        "STEP 6: BALL 1 CAPTURE UI",
        (120, 160, 140, 115),
        capture_ball_mask,
    ),
)


def apply_green_mask(crop: np.ndarray, mask: np.ndarray) -> np.ndarray:
    result = crop.copy()
    result[mask == 0] = MASK_GREEN_BGR
    return result


def make_contact_sheet(rows: list[tuple[str, np.ndarray, np.ndarray]]) -> np.ndarray:
    scale = 3
    margin = 24
    label_height = 34
    row_width = 2 * 230 * scale + 3 * margin
    row_height = 115 * scale + label_height + margin
    sheet = np.full(
        (len(rows) * row_height + margin, row_width, 3),
        (38, 38, 38),
        dtype=np.uint8,
    )
    for index, (label, raw, masked) in enumerate(rows):
        y = margin + index * row_height
        cv2.putText(
            sheet,
            label,
            (margin, y + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        raw_canvas = np.full((115, 230, 3), (38, 38, 38), dtype=np.uint8)
        masked_canvas = raw_canvas.copy()
        raw_canvas[: raw.shape[0], : raw.shape[1]] = raw
        masked_canvas[: masked.shape[0], : masked.shape[1]] = masked
        raw_large = cv2.resize(raw_canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        masked_large = cv2.resize(masked_canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        top = y + label_height
        sheet[top : top + raw_large.shape[0], margin : margin + raw_large.shape[1]] = raw_large
        right = 2 * margin + raw_large.shape[1]
        sheet[top : top + masked_large.shape[0], right : right + masked_large.shape[1]] = masked_large
    return sheet


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    normalized: dict[str, np.ndarray] = {}
    review_rows: list[tuple[str, np.ndarray, np.ndarray]] = []

    for template in TEMPLATES:
        image = normalized.setdefault(
            template.source,
            normalize_to_720p(SOURCE_DIR / template.source),
        )
        x, y, width, height = template.crop
        crop = image[y : y + height, x : x + width]
        if crop.shape[:2] != (height, width):
            raise ValueError(f"Crop outside image for {template.output}")
        mask = template.build_mask(crop)
        masked = apply_green_mask(crop, mask)
        output = OUTPUT_DIR / template.output
        if not cv2.imwrite(str(output), masked):
            raise RuntimeError(f"Unable to write {output}")
        review_rows.append((template.label, crop, masked))
        print(f"{template.source} {template.crop} -> {output.name}")

    sheet = make_contact_sheet(review_rows)
    sheet_path = OUTPUT_DIR / "MASKED_TEMPLATE_REVIEW.png"
    if not cv2.imwrite(str(sheet_path), sheet):
        raise RuntimeError(f"Unable to write {sheet_path}")
    print(f"review -> {sheet_path}")


if __name__ == "__main__":
    main()
