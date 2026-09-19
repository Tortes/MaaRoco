"""Import WeGame login-source templates from the local reference database."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "database"
DEFAULT_OUTPUT = ROOT / "assets" / "resource" / "image"
WECHAT_MENU_ROW_CROP = (53, 72, 111, 110)


def read_image(path: Path):
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"Cannot read image: {path}")
    return image


def write_image(path: Path, image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise SystemExit(f"Cannot write image: {path}")
    print(f"Wrote {path} ({image.shape[1]}x{image.shape[0]})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    qq = read_image(args.source_dir / "qq.png")
    wechat = read_image(args.source_dir / "wechat.png")
    menu_reference = read_image(
        args.source_dir / "Snipaste_2026-08-20_23-11-01.png"
    )
    left, top, right, bottom = WECHAT_MENU_ROW_CROP
    wechat_menu_row = menu_reference[top:bottom, left:right]
    if wechat_menu_row.size == 0:
        raise SystemExit("The configured source-menu crop is empty")

    write_image(args.output_dir / "wegame_source_qq.png", qq)
    write_image(args.output_dir / "wegame_source_wechat.png", wechat)
    write_image(
        args.output_dir / "wegame_source_menu_wechat.png",
        wechat_menu_row,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
