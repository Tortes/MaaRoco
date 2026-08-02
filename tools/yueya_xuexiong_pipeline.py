"""Build and train a Yueya Xuexiong YOLO11 detector.

The pipeline has two deliberately separate stages:
1. Synthetic images: a cutout from the encyclopedia is pasted on game backgrounds.
2. Mixed fine-tuning: manually verified real frames and known hard negatives are added.

The only training dependency is ultralytics. Dataset preparation uses cv2 and numpy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
TRAINING_ROOT = REPO_ROOT / "training" / "yueya_xuexiong"
SOURCES = TRAINING_ROOT / "sources"
WORK = TRAINING_ROOT / "work"
DATASETS = TRAINING_ROOT / "datasets"
RUNS = TRAINING_ROOT / "runs"
MODELS = TRAINING_ROOT / "models"
CLASS_NAME = "yueya_xuexiong"
IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def _images(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path for path in directory.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _read_image(path: Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded, data = cv2.imencode(path.suffix or ".png", image)
    if not encoded:
        raise ValueError(f"Cannot encode image: {path}")
    data.tofile(path)


def _yolo_lines(boxes: list[list[int]], width: int, height: int) -> str:
    lines: list[str] = []
    for x1, y1, x2, y2 in boxes:
        x1 = max(0, min(width, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height, y1))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        center_x = ((x1 + x2) / 2) / width
        center_y = ((y1 + y2) / 2) / height
        box_width = (x2 - x1) / width
        box_height = (y2 - y1) / height
        lines.append(
            f"0 {center_x:.6f} {center_y:.6f} {box_width:.6f} {box_height:.6f}"
        )
    return "\n".join(lines)


def _copy_labeled_image(source: Path, destination: Path, boxes: list[list[int]]) -> None:
    image = _read_image(source)
    height, width = image.shape[:2]
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.with_suffix(".txt").write_text(
        _yolo_lines(boxes, width, height), encoding="ascii"
    )


def bootstrap_sources(_: argparse.Namespace) -> None:
    """Copy the known real positives and hard negatives into the training tree."""
    annotation_path = TRAINING_ROOT / "real_annotations.json"
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    database_dir = REPO_ROOT.parent / "database" / "yueyaxuexiong"
    error_dir = REPO_ROOT / "install" / "debug" / "on_error"
    live_dir = REPO_ROOT / "install" / "debug" / "live"
    real_dir = SOURCES / "real"
    negative_dir = SOURCES / "negatives"
    background_dir = SOURCES / "backgrounds"
    background_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for filename, boxes in annotations["database"].items():
        source = database_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        _copy_labeled_image(source, real_dir / filename, boxes)
        copied += 1
    for filename, boxes in annotations["on_error"].items():
        source = error_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        _copy_labeled_image(source, real_dir / filename, boxes)
        copied += 1
    review_dir = SOURCES / "review"
    for filename, boxes in annotations.get("video", {}).items():
        source = review_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        _copy_labeled_image(source, real_dir / filename, boxes)
        copied += 1
    for filename, boxes in annotations.get("live", {}).items():
        source = live_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        _copy_labeled_image(source, real_dir / filename, boxes)
        copied += 1

    for location, filenames in annotations.get("negatives", {}).items():
        source_dir = {"database": database_dir, "on_error": error_dir}.get(location)
        if source_dir is None:
            raise ValueError(f"Unsupported negative source: {location}")
        for filename in filenames:
            source = source_dir / filename
            if not source.exists():
                raise FileNotFoundError(source)
            shutil.copy2(source, negative_dir / filename)
            (negative_dir / filename).with_suffix(".txt").write_text("", encoding="ascii")

    for source in _images(database_dir):
        if source.name.startswith("bad_case_"):
            destination = negative_dir / source.name
            shutil.copy2(source, destination)
            destination.with_suffix(".txt").write_text("", encoding="ascii")

    pipa_backgrounds = REPO_ROOT.parent / "database" / "pipaniao"
    for source in [*_images(negative_dir), *_images(pipa_backgrounds)]:
        shutil.copy2(source, background_dir / source.name)

    print(f"Bootstrapped {copied} labeled real images.")
    print(f"Backgrounds: {len(_images(background_dir))}")
    print(f"Hard negatives: {len(_images(negative_dir))}")


def extract_template(args: argparse.Namespace) -> None:
    """Create a usable RGBA cutout, preserving source alpha when available."""
    source = Path(args.source) if args.source else SOURCES / "templates" / "wiki_yueya_xuexiong.png"
    destination = SOURCES / "templates" / "yueya_xuexiong_cutout.png"
    source_image = _read_image(source, cv2.IMREAD_UNCHANGED)
    if source_image.ndim == 3 and source_image.shape[2] == 4 and np.any(source_image[:, :, 3] < 250):
        _write_image(destination, source_image)
        print(f"Wrote cutout from source alpha: {destination}")
        return

    image = source_image[:, :, :3] if source_image.ndim == 3 else source_image
    height, width = image.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    rectangle = (max(1, width // 16), max(1, height // 7), width * 14 // 16, height * 11 // 16)
    cv2.grabCut(
        image,
        mask,
        rectangle,
        background_model,
        foreground_model,
        8,
        cv2.GC_INIT_WITH_RECT,
    )
    alpha = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    _write_image(destination, np.dstack((image, alpha)))
    print(f"Wrote cutout: {destination}")


def _cover_resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = image.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized = cv2.resize(
        image,
        (round(source_width * scale), round(source_height * scale)),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )
    y = max(0, (resized.shape[0] - height) // 2)
    x = max(0, (resized.shape[1] - width) // 2)
    return resized[y : y + height, x : x + width].copy()


def _transform_cutout(cutout: np.ndarray, target_width: int, angle: float, flip: bool) -> np.ndarray:
    source_height, source_width = cutout.shape[:2]
    target_height = max(1, round(source_height * target_width / source_width))
    transformed = cv2.resize(cutout, (target_width, target_height), interpolation=cv2.INTER_AREA)
    if flip:
        transformed = cv2.flip(transformed, 1)
    matrix = cv2.getRotationMatrix2D(
        (target_width / 2, target_height / 2), angle, 1.0
    )
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    rotated_width = max(1, round(target_height * sin + target_width * cos))
    rotated_height = max(1, round(target_height * cos + target_width * sin))
    matrix[0, 2] += rotated_width / 2 - target_width / 2
    matrix[1, 2] += rotated_height / 2 - target_height / 2
    return cv2.warpAffine(
        transformed,
        matrix,
        (rotated_width, rotated_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _paste(background: np.ndarray, foreground: np.ndarray, x: int, y: int) -> tuple[np.ndarray, list[int]]:
    result = background.copy()
    foreground_height, foreground_width = foreground.shape[:2]
    alpha = foreground[:, :, 3] / 255.0
    roi = result[y : y + foreground_height, x : x + foreground_width]
    roi[:] = (
        foreground[:, :, :3] * alpha[:, :, None] + roi * (1.0 - alpha[:, :, None])
    ).astype(np.uint8)
    nonzero = cv2.findNonZero((foreground[:, :, 3] > 24).astype(np.uint8))
    if nonzero is None:
        raise ValueError("Cutout has no foreground alpha")
    left, top, width, height = cv2.boundingRect(nonzero)
    return result, [x + left, y + top, x + left + width, y + top + height]


def synthesize(args: argparse.Namespace) -> None:
    cutout_path = SOURCES / "templates" / "yueya_xuexiong_cutout.png"
    if not cutout_path.exists():
        raise FileNotFoundError(f"Run extract-template first: {cutout_path}")
    cutout = _read_image(cutout_path, cv2.IMREAD_UNCHANGED)
    if cutout.ndim != 3 or cutout.shape[2] != 4:
        raise ValueError("Template must be an RGBA PNG")
    backgrounds = _images(SOURCES / "backgrounds")
    if not backgrounds:
        raise FileNotFoundError("Run bootstrap first so backgrounds are available")

    output_images = WORK / "synthetic" / "images"
    output_labels = WORK / "synthetic" / "labels"
    shutil.rmtree(WORK / "synthetic", ignore_errors=True)
    output_images.mkdir(parents=True)
    output_labels.mkdir(parents=True)
    randomizer = random.Random(args.seed)
    for index in range(args.count):
        background = _cover_resize(_read_image(randomizer.choice(backgrounds)), args.width, args.height)
        size = randomizer.randint(args.min_size, args.max_size)
        foreground = _transform_cutout(
            cutout, size, randomizer.uniform(-16, 16), randomizer.random() < 0.35
        )
        if foreground.shape[0] >= args.height or foreground.shape[1] >= args.width:
            continue
        x = randomizer.randint(0, args.width - foreground.shape[1])
        y = randomizer.randint(max(0, args.height // 8), args.height - foreground.shape[0])
        image, box = _paste(background, foreground, x, y)
        stem = f"synthetic_{index:05d}"
        _write_image(output_images / f"{stem}.jpg", image)
        (output_labels / f"{stem}.txt").write_text(
            _yolo_lines([box], args.width, args.height), encoding="ascii"
        )
    print(f"Synthetic images: {len(_images(output_images))}")


def _split_for(path: Path, validation_percent: int) -> str:
    value = int(hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "val" if value < validation_percent else "train"


def _add_pair(source: Path, label: Path | None, output: Path, split: str, prefix: str) -> None:
    stem = f"{prefix}_{source.stem}"
    image_output = output / "images" / split / f"{stem}.jpg"
    label_output = output / "labels" / split / f"{stem}.txt"
    image = _read_image(source)
    _write_image(image_output, image)
    label_output.parent.mkdir(parents=True, exist_ok=True)
    label_output.write_text(
        label.read_text(encoding="ascii") if label and label.exists() else "",
        encoding="ascii",
    )


def prepare_dataset(args: argparse.Namespace) -> None:
    stage = args.stage
    output = DATASETS / stage
    shutil.rmtree(output, ignore_errors=True)
    synthetic_images = _images(WORK / "synthetic" / "images")
    if not synthetic_images:
        raise FileNotFoundError("Run synthesize before prepare")
    for image in synthetic_images:
        _add_pair(
            image,
            WORK / "synthetic" / "labels" / f"{image.stem}.txt",
            output,
            _split_for(image, args.validation_percent),
            "syn",
        )
    if stage == "mixed":
        for image in _images(SOURCES / "real"):
            _add_pair(
                image,
                image.with_suffix(".txt"),
                output,
                _split_for(image, args.validation_percent),
                "real",
            )
        for image in _images(SOURCES / "negatives"):
            split = _split_for(image, args.validation_percent)
            for repeat in range(args.hard_negative_repeat):
                _add_pair(image, None, output, split, f"neg{repeat:02d}")
    yaml = "\n".join(
        [
            f"path: {output.as_posix()}",
            "train: images/train",
            "val: images/val",
            "names:",
            f"  0: {CLASS_NAME}",
            "",
        ]
    )
    (output / "data.yaml").write_text(yaml, encoding="ascii")
    print(f"Dataset: {output}")
    print(f"Train: {len(_images(output / 'images' / 'train'))}")
    print(f"Validation: {len(_images(output / 'images' / 'val'))}")


def train(args: argparse.Namespace) -> None:
    from ultralytics import YOLO
    import torch

    dataset = DATASETS / args.stage / "data.yaml"
    if not dataset.exists():
        raise FileNotFoundError(f"Run prepare --stage {args.stage} first")
    if args.weights:
        weights = Path(args.weights)
    elif args.stage == "mixed" and (RUNS / "synthetic" / "weights" / "best.pt").exists():
        weights = RUNS / "synthetic" / "weights" / "best.pt"
    else:
        weights = REPO_ROOT / "yolo11n.pt"
    if not weights.exists():
        raise FileNotFoundError(weights)
    device: int | str = 0 if torch.cuda.is_available() else "cpu"
    batch = args.batch or (16 if device == 0 else 4)
    run_name = args.run_name or args.stage
    print(f"Weights: {weights}")
    print(f"Device: {device}")
    print(f"Run: {run_name}")
    model = YOLO(str(weights))
    model.train(
        data=str(dataset),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=batch,
        device=device,
        workers=0,
        project=str(RUNS),
        name=run_name,
        exist_ok=True,
        pretrained=True,
        fliplr=0.5,
        hsv_h=0.015,
        hsv_s=0.55,
        hsv_v=0.35,
        translate=0.08,
        scale=0.45,
        mosaic=0.7 if args.stage == "synthetic" else 0.35,
        close_mosaic=10,
        plots=True,
    )
    best = RUNS / run_name / "weights" / "best.pt"
    if best.exists():
        MODELS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, MODELS / f"yueya_xuexiong_{args.stage}.pt")
        print(f"Model: {MODELS / f'yueya_xuexiong_{args.stage}.pt'}")


def export_onnx(args: argparse.Namespace) -> None:
    from ultralytics import YOLO

    weights = Path(args.weights) if args.weights else MODELS / "yueya_xuexiong_mixed.pt"
    if not weights.exists():
        raise FileNotFoundError(weights)
    output = Path(YOLO(str(weights)).export(format="onnx", imgsz=args.imgsz, simplify=True, opset=16))
    MODELS.mkdir(parents=True, exist_ok=True)
    destination = MODELS / "yueya_xuexiong.onnx"
    shutil.copy2(output, destination)
    print(f"ONNX: {destination}")


def _default_preview_path(image: Path, suffix: str) -> Path:
    return WORK / "inference" / f"{image.stem}_{suffix}.jpg"


def detect_template(args: argparse.Namespace) -> None:
    """Find an encyclopedia-style sprite with masked multi-scale template matching."""
    image_path = Path(args.image)
    image = _read_image(image_path)
    search_scale = min(1.0, args.max_search_width / image.shape[1])
    search_image = cv2.resize(
        image,
        (round(image.shape[1] * search_scale), round(image.shape[0] * search_scale)),
        interpolation=cv2.INTER_AREA,
    )
    image_edges = cv2.Canny(cv2.cvtColor(search_image, cv2.COLOR_BGR2GRAY), 60, 160)
    cutout = _read_image(
        SOURCES / "templates" / "yueya_xuexiong_cutout.png", cv2.IMREAD_UNCHANGED
    )
    if cutout.ndim != 3 or cutout.shape[2] != 4:
        raise ValueError("Run extract-template first so an RGBA template is available")
    alpha = cutout[:, :, 3]
    nonzero = cv2.findNonZero((alpha > 24).astype(np.uint8))
    if nonzero is None:
        raise ValueError("Template has no opaque pixels")
    source_width = cutout.shape[1]

    candidates: list[tuple[float, int, int, int, int]] = []
    for scale in np.linspace(args.min_scale, args.max_scale, args.scales):
        target_width = max(8, round(source_width * scale * search_scale))
        for angle in args.angles:
            transformed = _transform_cutout(cutout, target_width, angle, False)
            alpha = transformed[:, :, 3]
            foreground = cv2.findNonZero((alpha > 24).astype(np.uint8))
            if foreground is None:
                continue
            left, top, match_width, match_height = cv2.boundingRect(foreground)
            template = transformed[
                top : top + match_height, left : left + match_width, :3
            ]
            if match_width >= search_image.shape[1] or match_height >= search_image.shape[0]:
                continue
            template_edges = cv2.Canny(
                cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), 60, 160
            )
            response = cv2.matchTemplate(
                image_edges, template_edges, cv2.TM_CCOEFF_NORMED
            )
            locations = np.argwhere(response >= args.threshold)
            for result_top, result_left in locations:
                candidates.append(
                    (
                        float(response[result_top, result_left]),
                        round(result_left / search_scale),
                        round(result_top / search_scale),
                        round(match_width / search_scale),
                        round(match_height / search_scale),
                    )
                )
    candidates.sort(reverse=True)
    boxes = [[left, top, width, height] for _, left, top, width, height in candidates]
    scores = [score for score, *_ in candidates]
    kept = cv2.dnn.NMSBoxes(boxes, scores, args.threshold, args.iou) if boxes else []

    preview = image.copy()
    matches: list[tuple[float, int, int, int, int]] = []
    for index in np.asarray(kept).reshape(-1).tolist() if len(kept) else []:
        score, left, top, match_width, match_height = candidates[index]
        matches.append((score, left, top, match_width, match_height))
        cv2.rectangle(preview, (left, top), (left + match_width, top + match_height), (0, 255, 255), 2)
        cv2.putText(
            preview, f"template {score:.2f}", (left, max(20, top - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA,
        )
    output = Path(args.output) if args.output else _default_preview_path(image_path, "template")
    _write_image(output, preview)
    print(f"Template matches: {len(matches)}")
    for score, left, top, match_width, match_height in matches:
        print(f"{score:.4f} {left} {top} {left + match_width} {top + match_height}")
    print(f"Preview: {output}")


def detect_yolo(args: argparse.Namespace) -> None:
    """Run the trained detector on a real game screenshot and save a preview."""
    from ultralytics import YOLO
    import torch

    image_path = Path(args.image)
    weights = Path(args.weights) if args.weights else MODELS / "yueya_xuexiong_mixed.pt"
    if not weights.exists():
        raise FileNotFoundError(f"Train the mixed stage first or pass --weights: {weights}")
    results = YOLO(str(weights)).predict(
        source=str(image_path),
        imgsz=args.imgsz,
        conf=args.confidence,
        iou=args.iou,
        device=0 if torch.cuda.is_available() else "cpu",
        verbose=False,
    )
    result = results[0]
    output = Path(args.output) if args.output else _default_preview_path(image_path, "yolo")
    _write_image(output, result.plot())
    detections = result.boxes
    print(f"YOLO matches: {len(detections)}")
    for box in detections:
        left, top, right, bottom = box.xyxy[0].tolist()
        print(f"{float(box.conf[0]):.4f} {left:.1f} {top:.1f} {right:.1f} {bottom:.1f}")
    print(f"Preview: {output}")


def extract_video_frames(args: argparse.Namespace) -> None:
    video = Path(args.video)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    every_frames = max(1, round(fps * args.every_seconds))
    output = SOURCES / "review"
    output.mkdir(parents=True, exist_ok=True)
    frame_number = 0
    saved = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_number % every_frames == 0:
            _write_image(output / f"{video.stem}_{saved:05d}.jpg", frame)
            saved += 1
        frame_number += 1
    capture.release()
    print(f"Frames saved for manual review: {saved}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap").set_defaults(func=bootstrap_sources)

    template = commands.add_parser("extract-template")
    template.add_argument("--source")
    template.set_defaults(func=extract_template)

    synthetic = commands.add_parser("synthesize")
    synthetic.add_argument("--count", type=int, default=400)
    synthetic.add_argument("--width", type=int, default=1280)
    synthetic.add_argument("--height", type=int, default=720)
    synthetic.add_argument("--min-size", type=int, default=90)
    synthetic.add_argument("--max-size", type=int, default=360)
    synthetic.add_argument("--seed", type=int, default=20260729)
    synthetic.set_defaults(func=synthesize)

    dataset = commands.add_parser("prepare")
    dataset.add_argument("--stage", choices=("synthetic", "mixed"), required=True)
    dataset.add_argument("--validation-percent", type=int, default=20)
    dataset.add_argument(
        "--hard-negative-repeat", type=int, default=1,
        help="Repeat each hard negative in mixed training to counter a positive-heavy synthetic set.",
    )
    dataset.set_defaults(func=prepare_dataset)

    training = commands.add_parser("train")
    training.add_argument("--stage", choices=("synthetic", "mixed"), required=True)
    training.add_argument("--weights")
    training.add_argument("--epochs", type=int, default=40)
    training.add_argument("--imgsz", type=int, default=640)
    training.add_argument("--batch", type=int)
    training.add_argument("--run-name")
    training.set_defaults(func=train)

    exporter = commands.add_parser("export")
    exporter.add_argument("--weights")
    exporter.add_argument("--imgsz", type=int, default=640)
    exporter.set_defaults(func=export_onnx)

    template_match = commands.add_parser("detect-template")
    template_match.add_argument("image")
    template_match.add_argument("--threshold", type=float, default=0.30)
    template_match.add_argument("--iou", type=float, default=0.35)
    template_match.add_argument("--min-scale", type=float, default=0.20)
    template_match.add_argument("--max-scale", type=float, default=0.45)
    template_match.add_argument("--scales", type=int, default=11)
    template_match.add_argument(
        "--angles", type=float, nargs="+", default=(-12.0, -8.0, -4.0, 0.0, 4.0, 8.0, 12.0)
    )
    template_match.add_argument("--max-search-width", type=int, default=640)
    template_match.add_argument("--output")
    template_match.set_defaults(func=detect_template)

    yolo_match = commands.add_parser("detect-yolo")
    yolo_match.add_argument("image")
    yolo_match.add_argument("--weights")
    yolo_match.add_argument("--confidence", type=float, default=0.35)
    yolo_match.add_argument("--iou", type=float, default=0.50)
    yolo_match.add_argument("--imgsz", type=int, default=640)
    yolo_match.add_argument("--output")
    yolo_match.set_defaults(func=detect_yolo)

    frames = commands.add_parser("extract-video")
    frames.add_argument("video")
    frames.add_argument("--every-seconds", type=float, default=1.0)
    frames.set_defaults(func=extract_video_frames)
    return root


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
