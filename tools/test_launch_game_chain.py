"""Exercise the launch task's window handoff without starting WeGame.

The test uses Program Manager as a harmless stand-in for the game window, then
asks the custom action to run the internal no-op probe through a second tasker.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from run_yueya_xuexiong_headless import (
    BINARY,
    INSTALL,
    find_window,
    start_agent,
    stop_tasker,
)


def main() -> int:
    os.add_dll_directory(str(BINARY))
    os.environ["MAAFW_BINARY_PATH"] = str(BINARY)
    os.environ["PATH"] = f"{BINARY};{os.environ['PATH']}"

    from maa.agent_client import AgentClient
    from maa.controller import Win32Controller
    from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum
    from maa.resource import Resource
    from maa.tasker import Tasker

    hwnd = find_window("Progman")
    resource = Resource()
    if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
        raise RuntimeError("Unable to load the installed resource bundle.")

    controller = Win32Controller(
        hwnd,
        MaaWin32ScreencapMethodEnum.ScreenDC,
        MaaWin32InputMethodEnum.PostMessage,
        MaaWin32InputMethodEnum.PostMessage,
    )
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError("Unable to connect the test desktop controller.")

    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        raise RuntimeError("Unable to initialize the test tasker.")

    client = AgentClient.create_tcp(0)
    process = start_agent(client, resource, controller, tasker)
    def make_override(downstream_entry: str) -> dict[str, object]:
        return {
            "LaunchGameWaitForWindow": {
                "custom_action_param": {
                    "title_contains": "Program Manager",
                    "class_name": "Progman",
                    "timeout_ms": 5_000,
                    "poll_interval_ms": 100,
                    "mouse_method": 1 << 9,
                    "keyboard_method": 1 << 9,
                    "downstream_entry": downstream_entry,
                }
            }
        }

    try:
        job = tasker.post_task(
            "LaunchGameWaitForWindow", make_override("LaunchGameControllerReady")
        )
        deadline = time.monotonic() + 15
        while not job.done and time.monotonic() < deadline:
            time.sleep(0.05)
        probe_done = job.done
        probe_succeeded = job.succeeded

        continuity_job = tasker.post_task(
            "LaunchGameWaitForWindow", make_override("BattleHostingStart")
        )
        continuity_deadline = time.monotonic() + 2
        while not continuity_job.done and time.monotonic() < continuity_deadline:
            time.sleep(0.05)
        continuity_was_running = not continuity_job.done
        stop_completed = stop_tasker(tasker)
        report = {
            "done": probe_done,
            "succeeded": probe_succeeded,
            "status": str(job.status),
            "desktop_hwnd": hwnd,
            "battle_pipeline_stayed_running": continuity_was_running,
            "stop_propagated": stop_completed,
        }
        print(json.dumps(report, ensure_ascii=False))
        return 0 if probe_succeeded and continuity_was_running and stop_completed else 1
    finally:
        if tasker.running:
            stop_tasker(tasker)
        client.disconnect()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
