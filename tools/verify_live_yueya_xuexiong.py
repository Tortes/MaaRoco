"""Verify the installed Yueya Xuexiong Maa detector against a live game window.

This intentionally creates a Win32 controller with ``Seize`` input methods but
only calls ``post_screencap`` and ``post_recognition``.  It never starts a
pipeline or sends keyboard/mouse input to the game.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]


def box_values(box) -> tuple[int, int, int, int]:
    """Normalize the binding's Rect and list-style result boxes."""

    if hasattr(box, "x"):
        return box.x, box.y, box.w, box.h
    return tuple(int(value) for value in box)


def find_window(title_part: str) -> int:
    """Return the first visible top-level window whose title contains text."""

    user32 = ctypes.windll.user32
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def visit(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            text = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, text, length + 1)
            if title_part in text.value:
                matches.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if not matches:
        raise RuntimeError(f"Cannot find a visible window containing {title_part!r}.")
    return matches[0]


def draw_detection(image, recognition):
    """Draw candidates and the selected Maa result without modifying the capture."""

    preview = image.copy()
    for result in recognition.all_results:
        x, y, w, h = box_values(result.box)
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 196, 255), 1)

    if recognition.best_result:
        x, y, w, h = box_values(recognition.best_result.box)
        score = recognition.best_result.score
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(
            preview,
            f"YueyaXuexiong {score:.3f}",
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    return preview


def prepare_model_resource(output_dir: Path) -> Path:
    """Make a minimal bundle containing the deployed model only.

    The installed resource bundle also has unrelated legacy pipelines.  A
    legacy action unsupported by the current Maa core must not prevent this
    read-only detector check.  The production Yueya pipeline is loaded
    separately below, so its exact recognition parameters are still verified.
    """

    source = ROOT / "install" / "resource" / "model" / "detect" / "yueya_xuexiong.onnx"
    if not source.is_file():
        raise RuntimeError(f"Deployed model is missing: {source}")

    bundle = output_dir / "_verification_resource"
    target = bundle / "model" / "detect" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        shutil.copy2(source, target)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=int, help="Game window handle; defaults to title lookup.")
    parser.add_argument("--title", default="洛克王国：世界", help="Title text for automatic window lookup.")
    parser.add_argument("--frames", type=int, default=5, help="Number of live frames to verify.")
    parser.add_argument("--interval", type=float, default=0.45, help="Seconds between screenshots.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "install" / "debug" / "live")
    args = parser.parse_args()

    if args.frames < 1:
        parser.error("--frames must be at least 1")

    binary = Path(os.environ.get("MAAFW_BINARY_PATH", ROOT / "deps" / "bin")).resolve()
    os.add_dll_directory(str(binary))
    os.environ["PATH"] = f"{binary};{os.environ['PATH']}"

    from maa.controller import Win32Controller
    from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum
    from maa.resource import Resource
    from maa.tasker import Tasker

    hwnd = args.hwnd or find_window(args.title)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    resource = Resource()
    model_bundle = prepare_model_resource(output_dir)
    if not resource.post_bundle(model_bundle).wait().succeeded:
        raise RuntimeError("Unable to load the isolated deployed model bundle.")
    pipeline_path = ROOT / "install" / "resource" / "pipeline" / "YueyaXuexiongThrow.json"
    if not resource.post_pipeline(pipeline_path).wait().succeeded:
        raise RuntimeError(f"Unable to load deployed Yueya pipeline: {pipeline_path}")
    pipeline_node = resource.get_node_object("YueyaXuexiongDetect")
    if pipeline_node is None:
        raise RuntimeError("YueyaXuexiongDetect is absent from the deployed pipeline.")
    params = pipeline_node.recognition.param

    controller = Win32Controller(
        hwnd,
        MaaWin32ScreencapMethodEnum.ScreenDC,
        MaaWin32InputMethodEnum.Seize,
        MaaWin32InputMethodEnum.Seize,
    )
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError(f"Unable to connect to window handle {hwnd}.")

    tasker = Tasker()
    tasker.bind(resource, controller)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    records = []
    try:
        for index in range(args.frames):
            image = controller.post_screencap().get(wait=True)
            job = tasker.post_recognition("NeuralNetworkDetect", params, image)
            job.wait()
            task = job.get()
            recognition = tasker.get_node_detail(task.node_id_list[-1]).recognition
            best = recognition.best_result
            record = {
                "frame": index + 1,
                "job_success": job.succeeded,
                "hit": recognition.hit,
                "candidate_count": len(recognition.all_results),
                "pipeline": {
                    "model": params.model,
                    "threshold": params.threshold,
                    "order_by": params.order_by,
                },
                "selected": None if best is None else {
                    "box": list(box_values(best.box)),
                    "score": round(best.score, 6),
                },
            }
            records.append(record)
            image_path = output_dir / f"yueya_live_{stamp}_{index + 1:02d}.png"
            preview_path = output_dir / f"yueya_live_{stamp}_{index + 1:02d}_detected.png"
            cv2.imwrite(str(image_path), image)
            cv2.imwrite(str(preview_path), draw_detection(image, recognition))
            print(json.dumps(record, ensure_ascii=False))
            if index + 1 < args.frames:
                time.sleep(args.interval)
    finally:
        # This Maa Python binding owns the controller handle and has no
        # explicit disconnect method; releasing it at process exit is enough.
        del controller

    report_path = output_dir / f"yueya_live_{stamp}_report.json"
    report_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = all(record["job_success"] and record["hit"] for record in records)
    print(f"report={report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
