"""Train and export the Pipa Bird detector from a YOLO dataset."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="YOLO dataset YAML path")
    parser.add_argument("--output", type=Path, required=True, help="Directory for training artifacts")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=416)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from ultralytics import YOLO

    args.output.mkdir(parents=True, exist_ok=True)
    model = YOLO("yolo11n.pt")
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=4,
        device="cpu",
        workers=0,
        project=str(args.output.parent),
        name=args.output.name,
        exist_ok=True,
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.05,
        patience=20,
        degrees=0,
        translate=0.03,
        scale=0.15,
        fliplr=0.5,
        mosaic=0.0,
        close_mosaic=0,
    )

    best_model = YOLO(str(args.output / "weights" / "best.pt"))
    best_model.export(format="onnx", imgsz=args.imgsz, simplify=True, opset=17)


if __name__ == "__main__":
    main()
