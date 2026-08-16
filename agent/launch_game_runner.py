"""Run an existing pipeline on a newly discovered game window controller."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
from pathlib import Path


_SCREEN_DC = 1 << 5


def _enable_per_monitor_dpi_awareness() -> None:
    """Keep Win32 screenshot coordinates aligned on scaled displays."""
    try:
        per_monitor_v2 = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(per_monitor_v2)
    except (AttributeError, OSError):
        pass


def _activate_window(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)


def _log(message: str) -> None:
    line = f"[LaunchGameRunner] {message}"
    print(line, flush=True)
    try:
        log_dir = Path("debug")
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "launch_game.log").open("a", encoding="utf-8") as log_file:
            log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def _watch_parent_input(stop_event: threading.Event) -> None:
    try:
        sys.stdin.readline()
    finally:
        stop_event.set()


def _stop_tasker(tasker, timeout_seconds: float = 10.0) -> None:
    if not tasker.running:
        return
    stop_job = tasker.post_stop()
    deadline = time.monotonic() + timeout_seconds
    while not stop_job.done and time.monotonic() < deadline:
        time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=int, required=True)
    parser.add_argument("--entry", default="BattleHostingStart")
    parser.add_argument("--mouse-method", type=int, default=1 << 9)
    parser.add_argument("--keyboard-method", type=int, default=1 << 9)
    args = parser.parse_args()

    _enable_per_monitor_dpi_awareness()

    binary_path = os.environ.get("MAAFW_BINARY_PATH")
    if binary_path and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(binary_path)

    from maa.controller import Win32Controller
    from maa.resource import Resource
    from maa.tasker import Tasker

    if not ctypes.windll.user32.IsWindow(args.hwnd):
        _log(f"window no longer exists hwnd=0x{args.hwnd:X}")
        return 2

    _activate_window(args.hwnd)

    resource_path = Path.cwd() / "resource"
    resource = Resource()
    if not resource.post_bundle(resource_path).wait().succeeded:
        _log(f"failed to load resource path={resource_path}")
        return 3

    controller = Win32Controller(
        args.hwnd,
        _SCREEN_DC,
        args.mouse_method,
        args.keyboard_method,
    )
    if not controller.post_connection().wait().succeeded:
        _log(f"failed to connect controller hwnd=0x{args.hwnd:X}")
        return 4

    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        _log("failed to initialize downstream tasker")
        return 5

    stop_event = threading.Event()
    threading.Thread(
        target=_watch_parent_input,
        args=(stop_event,),
        daemon=True,
        name="launch-game-parent-watch",
    ).start()

    Tasker.set_log_dir("./debug")
    _log(f"connected hwnd=0x{args.hwnd:X}; starting entry={args.entry!r}")
    job = tasker.post_task(args.entry)
    try:
        while not job.done:
            if stop_event.is_set():
                _log("received stop request from parent task")
                _stop_tasker(tasker)
                return 0
            if not ctypes.windll.user32.IsWindow(args.hwnd):
                _log("game window closed")
                _stop_tasker(tasker)
                return 0
            time.sleep(0.1)

        if job.succeeded:
            _log(f"pipeline completed entry={args.entry!r}")
            return 0
        _log(f"pipeline failed entry={args.entry!r}")
        return 6
    except KeyboardInterrupt:
        _log("runner interrupted")
        _stop_tasker(tasker)
        return 0
    finally:
        _stop_tasker(tasker)


if __name__ == "__main__":
    raise SystemExit(main())
