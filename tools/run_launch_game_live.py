"""Run the installed LaunchGame chain as an elevated, headless live test.

The script writes incremental evidence to ``install/debug/launch_game_live_status.json``.
It reports success only after the real Unreal window exists and the downstream
``LaunchGameEnterWorldStart`` runner has remained active for a continuity check.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from run_yueya_xuexiong_headless import (
    BINARY,
    INSTALL,
    find_window,
    read_after,
    start_agent,
    stop_tasker,
)


STATUS_PATH = INSTALL / "debug" / "launch_game_live_status.json"
LAUNCH_LOG = INSTALL / "debug" / "launch_game.log"


def write_status(status: dict[str, object]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def window_exists(class_name: str) -> bool:
    user32 = ctypes.windll.user32
    found = False
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def visit(hwnd: int, _: int) -> bool:
        nonlocal found
        if not user32.IsWindowVisible(hwnd):
            return True
        buffer = ctypes.create_unicode_buffer(256)
        if user32.GetClassNameW(hwnd, buffer, len(buffer)):
            if buffer.value == class_name:
                found = True
                return False
        return True

    user32.EnumWindows(visit, 0)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wegame",
        type=Path,
        default=Path(r"D:\Program Files\LOL\WeGame\wegame.exe"),
    )
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--continuity-seconds", type=float, default=5.0)
    parser.add_argument(
        "--downstream-entry",
        default="LaunchGameEnterWorldStart",
        help="Game-window pipeline entry used by the launch action.",
    )
    args = parser.parse_args()

    status: dict[str, object] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "stage": "initializing",
        "success": False,
        "elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "wegame": str(args.wegame),
        "downstream_entry": args.downstream_entry,
        "events": [],
    }
    write_status(status)

    if not status["elevated"]:
        status.update(stage="failed", error="Administrator privileges are required")
        write_status(status)
        return 2
    if not args.wegame.is_file():
        status.update(stage="failed", error=f"WeGame executable not found: {args.wegame}")
        write_status(status)
        return 3

    os.add_dll_directory(str(BINARY))
    os.environ["MAAFW_BINARY_PATH"] = str(BINARY)
    os.environ["PATH"] = f"{BINARY};{os.environ['PATH']}"

    from maa.agent_client import AgentClient
    from maa.controller import Win32Controller
    from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum
    from maa.resource import Resource
    from maa.tasker import Tasker

    resource = Resource()
    controller = None
    tasker = None
    client = None
    agent_process: subprocess.Popen[str] | None = None
    try:
        desktop_hwnd = find_window("Progman")
        status.update(stage="loading_resource", desktop_hwnd=desktop_hwnd)
        write_status(status)

        if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
            raise RuntimeError("Unable to load the installed resource bundle")
        controller = Win32Controller(
            desktop_hwnd,
            MaaWin32ScreencapMethodEnum.ScreenDC,
            MaaWin32InputMethodEnum.PostMessage,
            MaaWin32InputMethodEnum.PostMessage,
        )
        if not controller.post_connection().wait().succeeded:
            raise RuntimeError("Unable to connect the desktop launcher controller")
        tasker = Tasker()
        if not tasker.bind(resource, controller) or not tasker.inited:
            raise RuntimeError("Unable to initialize the launcher tasker")

        client = AgentClient.create_tcp(0)
        agent_process = start_agent(client, resource, controller, tasker)
        log_offset = LAUNCH_LOG.stat().st_size if LAUNCH_LOG.exists() else 0
        status.update(stage="launching", agent_pid=agent_process.pid)
        write_status(status)

        override = {
            "LaunchGameStart": {
                "action": {
                    "param": {
                        "exec": str(args.wegame),
                    }
                }
            },
            "LaunchGameWaitForWindow": {
                "custom_action_param": {
                    "downstream_entry": args.downstream_entry,
                }
            }
        }
        job = tasker.post_task("LaunchGameStart", override)
        deadline = time.monotonic() + args.timeout
        downstream_since: float | None = None
        last_status_write = 0.0

        while time.monotonic() < deadline:
            log_offset, fragment = read_after(LAUNCH_LOG, log_offset)
            for line in fragment.splitlines():
                if "[LaunchGame" not in line:
                    continue
                events = status["events"]
                assert isinstance(events, list)
                events.append(line)
                del events[:-80]
                if "WeGame window found" in line:
                    status["stage"] = "wegame_found"
                elif "start-button click action sent" in line:
                    status["stage"] = "start_clicked"
                elif "game window found" in line:
                    status["stage"] = "game_found"
                elif f"starting entry={args.downstream_entry!r}" in line:
                    status["stage"] = "game_pipeline_running"
                    downstream_since = downstream_since or time.monotonic()

            status["game_window_present"] = window_exists("UnrealWindow")
            status["task_running"] = not job.done
            if (
                downstream_since is not None
                and status["game_window_present"]
                and not job.done
                and time.monotonic() - downstream_since >= args.continuity_seconds
            ):
                status.update(
                    stage="verified",
                    success=True,
                    continuity_seconds=args.continuity_seconds,
                )
                write_status(status)
                stop_tasker(tasker, timeout=10.0)
                return 0

            if job.done:
                status.update(
                    stage="failed",
                    error="LaunchGame task ended before downstream verification",
                    task_status=str(job.status),
                )
                write_status(status)
                return 4

            if time.monotonic() - last_status_write >= 1.0:
                write_status(status)
                last_status_write = time.monotonic()
            time.sleep(0.1)

        status.update(stage="failed", error="Live launch verification timed out")
        write_status(status)
        return 5
    except Exception as error:
        status.update(
            stage="failed",
            error=f"{type(error).__name__}: {error}",
            traceback=traceback.format_exc(),
        )
        write_status(status)
        return 1
    finally:
        if tasker is not None and tasker.running:
            stop_tasker(tasker, timeout=10.0)
        if client is not None:
            client.disconnect()
        if agent_process is not None and agent_process.poll() is None:
            agent_process.terminate()
            try:
                agent_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                agent_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
