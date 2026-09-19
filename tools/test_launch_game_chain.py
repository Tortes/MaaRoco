"""Exercise the launch task's window handoff without starting WeGame."""

from __future__ import annotations

import json
import os
import subprocess
import time
import ctypes

from run_yueya_xuexiong_headless import (
    BINARY,
    INSTALL,
    find_window,
    read_after,
    start_agent,
    stop_tasker,
)


LAUNCH_LOG = INSTALL / "debug" / "launch_game.log"


def main() -> int:
    os.add_dll_directory(str(BINARY))
    os.environ["MAAFW_BINARY_PATH"] = str(BINARY)
    os.environ["PATH"] = f"{BINARY};{os.environ['PATH']}"

    from maa.agent_client import AgentClient
    from maa.controller import Win32Controller
    from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum
    from maa.resource import Resource
    from maa.tasker import Tasker

    hwnd = int(ctypes.windll.user32.GetForegroundWindow())
    if not hwnd:
        hwnd = find_window("Progman")
    title_length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(max(1, title_length + 1))
    ctypes.windll.user32.GetWindowTextW(hwnd, title, len(title))
    class_name = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, class_name, len(class_name))
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
                    "title_contains": title.value,
                    "class_name": class_name.value,
                    "process_name": "",
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

        retry_log_offset = LAUNCH_LOG.stat().st_size if LAUNCH_LOG.exists() else 0
        retry_override = {
            "LaunchGameWaitForWindow": {
                "custom_action_param": {
                    "title_contains": "__missing_game_window__",
                    "class_name": "__MissingGameWindow__",
                    "process_name": "__missing_game__.exe",
                    "wegame_title_contains": title.value,
                    "wegame_class_name": class_name.value,
                    "wegame_process_name": "",
                    "wegame_click_entry": "LaunchGameControllerReady",
                    "timeout_ms": 2_000,
                    "poll_interval_ms": 100,
                    "diagnostic_interval_ms": 500,
                    "wegame_retry_interval_ms": 200,
                    "wegame_success_retry_interval_ms": 200,
                    "wegame_click_attempt_timeout_ms": 1_000,
                    "wegame_mouse_method": 1,
                    "wegame_keyboard_method": 1,
                }
            }
        }
        retry_job = tasker.post_task("LaunchGameWaitForWindow", retry_override)
        retry_deadline = time.monotonic() + 5
        while not retry_job.done and time.monotonic() < retry_deadline:
            time.sleep(0.05)
        _, retry_log = read_after(LAUNCH_LOG, retry_log_offset)
        retry_attempts = retry_log.count("starting template click attempt=")
        retry_verified = retry_job.done and not retry_job.succeeded and retry_attempts >= 2

        launch_pipeline = json.loads(
            (INSTALL / "resource" / "pipeline" / "LaunchGame.json").read_text(
                encoding="utf-8"
            )
        )
        stops_after_entry = (
            launch_pipeline["LaunchGameEnterWorldButtonGone"]["next"] == []
            and "BattleHostingStart"
            not in json.dumps(launch_pipeline, ensure_ascii=False)
        )
        launch_task = json.loads(
            (INSTALL / "tasks" / "LaunchGame.json").read_text(
                encoding="utf-8"
            )
        )
        login_source = launch_task["option"]["WeGameLoginSource"]
        source_cases = {
            case["name"]: case for case in login_source["cases"]
        }
        wechat_entry = source_cases["WeChat"]["pipeline_override"][
            "LaunchGameWaitForWindow"
        ]["custom_action_param"]["wegame_click_entry"]
        wechat_attempt_timeout = source_cases["WeChat"][
            "pipeline_override"
        ]["LaunchGameWaitForWindow"]["custom_action_param"][
            "wegame_click_attempt_timeout_ms"
        ]
        source_nodes = {
            "LaunchGameClickWeGameStartWeChat",
            "LaunchGameQQSourceButton",
            "LaunchGameSourceMenuWeChat",
            "LaunchGameWeChatSourceSelected",
        }
        login_source_option_verified = (
            login_source["default_case"] == "QQ"
            and source_cases["QQ"]["pipeline_override"] == {}
            and wechat_entry == "LaunchGameClickWeGameStartWeChat"
            and wechat_attempt_timeout >= 30000
            and source_nodes <= launch_pipeline.keys()
            and launch_pipeline["LaunchGameSourceMenuWeChat"]["template"]
            == "wegame_source_menu_wechat.png"
        )
        report = {
            "done": probe_done,
            "succeeded": probe_succeeded,
            "status": str(job.status),
            "window_hwnd": hwnd,
            "window_title": title.value,
            "window_class": class_name.value,
            "launch_pipeline_stops_after_entry": stops_after_entry,
            "wegame_retry_attempts": retry_attempts,
            "wegame_retry_verified": retry_verified,
            "login_source_option_verified": login_source_option_verified,
        }
        print(json.dumps(report, ensure_ascii=False))
        return (
            0
            if probe_succeeded
            and stops_after_entry
            and retry_verified
            and login_source_option_verified
            else 1
        )
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
