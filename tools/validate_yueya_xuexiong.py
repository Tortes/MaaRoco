"""Regression checks for the Yueya Xuexiong detector.

The script deliberately tests positives and known hard negatives together.  A
model is only a candidate for the Maa task when it detects every reviewed real
frame without firing on the hard-negative set.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "training" / "yueya_xuexiong" / "sources"
OUTPUT = ROOT / "training" / "yueya_xuexiong" / "work" / "regression"


@dataclass
class Detection:
    box: tuple[int, int, int, int]
    score: float


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def load_boxes(path: Path, width: int, height: int) -> list[tuple[int, int, int, int]]:
    label = path.with_suffix(".txt")
    if not label.exists():
        return []
    boxes: list[tuple[int, int, int, int]] = []
    for line in label.read_text(encoding="ascii").splitlines():
        _, cx, cy, box_width, box_height = (float(value) for value in line.split())
        x1 = round((cx - box_width / 2) * width)
        y1 = round((cy - box_height / 2) * height)
        x2 = round((cx + box_width / 2) * width)
        y2 = round((cy + box_height / 2) * height)
        boxes.append((x1, y1, x2, y2))
    return boxes


def iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    union = (first[2] - first[0]) * (first[3] - first[1])
    union += (second[2] - second[0]) * (second[3] - second[1])
    union -= intersection
    return intersection / union if union else 0.0


def color_baseline(image: np.ndarray) -> list[Detection]:
    """Mirror the legacy Maa HSV detector so its failure mode stays visible."""
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([100, 70, 140]), np.array([140, 255, 255]))
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
    detections: list[Detection] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index])
        density = area / (box_width * box_height)
        if (
            area < round(width * height * 0.002)
            or y < round(height * 0.06)
            or density < 0.38
        ):
            continue
        center_x, center_y = centers[index]
        detections.append(
            Detection(
                (
                    round(center_x - box_width / 2),
                    round(center_y - box_height / 2),
                    round(center_x + box_width / 2),
                    round(center_y + box_height / 2),
                ),
                min(0.99, density),
            )
        )
    return sorted(detections, key=lambda item: item.score, reverse=True)


def yolo_detector(weights: Path, confidence: float, imgsz: int):
    from ultralytics import YOLO

    model = YOLO(str(weights))

    def run(image_path: Path) -> list[Detection]:
        result = model.predict(
            source=str(image_path), conf=confidence, imgsz=imgsz, verbose=False
        )[0]
        return [
            Detection(tuple(round(value) for value in box.xyxy[0].tolist()), float(box.conf[0]))
            for box in result.boxes
        ]

    return run


def annotate(
    image: np.ndarray, expected: list[tuple[int, int, int, int]], found: list[Detection]
) -> np.ndarray:
    preview = image.copy()
    for x1, y1, x2, y2 in expected:
        cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 255, 0), 3)
    for detection in found:
        x1, y1, x2, y2 = detection.box
        cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(
            preview, f"{detection.score:.2f}", (x1, max(18, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA,
        )
    return preview


def select_detection(detections: list[Detection], mode: str) -> Detection | None:
    if not detections:
        return None
    if mode == "area":
        return max(
            detections,
            key=lambda item: (item.box[2] - item.box[0]) * (item.box[3] - item.box[1]),
        )
    if mode == "horizontal":
        return min(detections, key=lambda item: item.box[0])
    return max(detections, key=lambda item: item.score)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--iou", type=float, default=0.35)
    parser.add_argument(
        "--selection", choices=("score", "area", "horizontal"), default="score"
    )
    parser.add_argument("--baseline-color", action="store_true")
    args = parser.parse_args()
    if bool(args.weights) == bool(args.baseline_color):
        parser.error("Choose exactly one of --weights or --baseline-color")
    if args.weights and not args.weights.exists():
        parser.error(f"Missing model: {args.weights}")

    detector = color_baseline if args.baseline_color else yolo_detector(
        args.weights, args.confidence, args.imgsz
    )
    positives = sorted((SOURCES / "real").glob("*.png")) + sorted((SOURCES / "real").glob("*.jpg"))
    negatives = sorted((SOURCES / "negatives").glob("*.png")) + sorted((SOURCES / "negatives").glob("*.jpg"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    true_positive = false_negative = false_positive = top_score_miss = 0
    for image_path in [*positives, *negatives]:
        image = read_image(image_path)
        expected = load_boxes(image_path, image.shape[1], image.shape[0])
        found = detector(image_path) if args.weights else detector(image)
        matches = 0
        for box in expected:
            if any(iou(box, detection.box) >= args.iou for detection in found):
                matches += 1
        true_positive += matches
        false_negative += len(expected) - matches
        selected = select_detection(found, args.selection)
        top_iou = (
            max((iou(box, selected.box) for box in expected), default=0.0)
            if selected
            else 0.0
        )
        if expected and top_iou < args.iou:
            top_score_miss += 1
        if not expected:
            false_positive += len(found)
        preview = annotate(image, expected, found)
        output = OUTPUT / f"{image_path.stem}_{'color' if args.baseline_color else 'yolo'}.jpg"
        encoded, data = cv2.imencode(".jpg", preview)
        if not encoded:
            raise ValueError(f"Cannot encode {output}")
        data.tofile(output)
        print(
            f"{image_path.name}: expected={len(expected)} found={len(found)} "
            f"matched={matches} top_iou={top_iou:.3f}"
        )
    print(
        f"summary: tp={true_positive} fn={false_negative} fp={false_positive} "
        f"top_score_miss={top_score_miss} "
        f"recall={true_positive / max(1, true_positive + false_negative):.3f}"
    )
    return 0 if false_negative == 0 and false_positive == 0 and top_score_miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
