"""Run Yueya Xuexiong exploration directly through MaaFramework, without MFA UI.

The runner owns a Win32 controller, an AgentClient, and the project agent process.
It stops as soon as the custom action logs a confirmed left-button release, making
one real throw a concrete integration-test signal instead of relying on UI state.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install"
BINARY = ROOT / "deps" / "bin"
AGENT_LOG = INSTALL / "debug" / "pipa_bird.log"


def find_window(class_name: str) -> int:
    """Find the one visible game window selected by its Win32 class name."""

    user32 = ctypes.windll.user32
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def visit(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        window_class = ctypes.create_unicode_buffer(256)
        if user32.GetClassNameW(hwnd, window_class, len(window_class)):
            if window_class.value == class_name:
                matches.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if not matches:
        raise RuntimeError(f"No visible window with class {class_name!r}.")
    if len(matches) > 1:
        raise RuntimeError(f"Expected one {class_name!r} window, found {len(matches)}: {matches}")
    return matches[0]


def read_after(path: Path, offset: int) -> tuple[int, str]:
    if not path.exists():
        return offset, ""
    with path.open("r", encoding="utf-8", errors="replace") as file:
        file.seek(offset)
        fragment = file.read()
        return file.tell(), fragment


def start_agent(client, resource, controller, tasker) -> subprocess.Popen[str]:
    if not client.bind(resource):
        raise RuntimeError("AgentClient.bind(resource) failed.")
    if not client.register_sink(resource, controller, tasker):
        raise RuntimeError("AgentClient.register_sink failed.")
    if not client.set_timeout(15_000):
        raise RuntimeError("AgentClient.set_timeout failed.")

    environment = os.environ.copy()
    environment["MAAFW_BINARY_PATH"] = str(BINARY)
    environment["PATH"] = f"{BINARY};{environment['PATH']}"
    process = subprocess.Popen(
        [sys.executable, str(INSTALL / "agent" / "main.py"), client.identifier],
        cwd=INSTALL,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for attempt in range(3):
        if client.connect():
            return process
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Agent process exited early: {output}")
        time.sleep(attempt + 1)
    process.kill()
    raise RuntimeError("AgentClient.connect failed after three attempts.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", type=int, help="Game window handle.")
    parser.add_argument("--class-name", default="UnrealWindow")
    parser.add_argument("--entry", default="YueyaXuexiongExploreStart")
    parser.add_argument(
        "--timeout",
        type=float,
        default=0,
        help="Stop after this many seconds; 0 keeps running until interrupted.",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=0,
        help="Restart a finished pipeline this many times; 0 means indefinitely.",
    )
    parser.add_argument(
        "--stop-after-throw",
        action="store_true",
        help="Exit after the first confirmed release (for integration testing).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate the backend connection without posting a task.")
    args = parser.parse_args()

    os.add_dll_directory(str(BINARY))
    os.environ["MAAFW_BINARY_PATH"] = str(BINARY)
    os.environ["PATH"] = f"{BINARY};{os.environ['PATH']}"

    from maa.agent_client import AgentClient
    from maa.controller import Win32Controller
    from maa.define import MaaWin32ScreencapMethodEnum
    from maa.resource import Resource
    from maa.tasker import Tasker

    hwnd = args.hwnd or find_window(args.class_name)
    resource = Resource()
    if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
        raise RuntimeError("Unable to load installed resource bundle.")

    # The customized MaaFramework accepts 1 << 9 for Interception even though
    # the stock Python enum has not yet published that member.  The game rejects
    # PostMessage keyboard input with ERROR_ACCESS_DENIED, so both input paths
    # must use the installed Interception driver.
    controller = Win32Controller(
        hwnd,
        MaaWin32ScreencapMethodEnum.ScreenDC,
        1 << 9,
        1 << 9,
    )
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError(f"Unable to connect to game window {hwnd}.")
    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        raise RuntimeError("Unable to initialize tasker.")

    client = AgentClient.create_tcp(0)
    process = start_agent(client, resource, controller, tasker)
    started_at = datetime.now().isoformat(timespec="seconds")
    log_offset = AGENT_LOG.stat().st_size if AGENT_LOG.exists() else 0
    report = {
        "started_at": started_at,
        "entry": args.entry,
        "hwnd": hwnd,
        "dry_run": args.dry_run,
        "confirmed_throw": False,
        "attempts": [],
    }
    try:
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False))
            return 0

        deadline = time.monotonic() + args.timeout if args.timeout > 0 else None
        attempt = 0
        while args.max_restarts == 0 or attempt < args.max_restarts:
            attempt += 1
            job = tasker.post_task(args.entry)
            attempt_report = {"attempt": attempt, "started_at": time.time(), "events": []}
            report["attempts"].append(attempt_report)
            while time.monotonic() < deadline:
                log_offset, fragment = read_after(AGENT_LOG, log_offset)
                for line in fragment.splitlines():
                    if "[PipaBird]" in line or "[TargetPet]" in line:
                        attempt_report["events"].append(line)
                    if (
                        "release: target confirmed" in line
                        or "release: target box center confirmed" in line
                    ):
                        report["confirmed_throw"] = True
                        if args.stop_after_throw:
                            tasker.post_stop().wait()
                            print(json.dumps(report, ensure_ascii=False))
                            return 0
                if job.done:
                    attempt_report["task_status"] = str(job.status)
                    break
                time.sleep(0.1)
            if tasker.running:
                tasker.post_stop().wait()
            if deadline is not None and time.monotonic() >= deadline:
                break

        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["confirmed_throw"] else 1
    except KeyboardInterrupt:
        report["interrupted"] = True
        print(json.dumps(report, ensure_ascii=False))
        return 0
    finally:
        if tasker.running:
            tasker.post_stop().wait()
        client.disconnect()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
