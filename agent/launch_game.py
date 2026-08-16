import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction


_INTERCEPTION = 1 << 9
_SEIZE = 1


def _log(message: str) -> None:
    line = f"[LaunchGame] {message}"
    print(line, flush=True)
    try:
        log_dir = Path("debug")
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "launch_game.log").open("a", encoding="utf-8") as log_file:
            log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def _parse_param(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _positive_int(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, parsed))


def _find_window(title_contains: str, class_name: str) -> int | None:
    user32 = ctypes.windll.user32
    matches: list[tuple[int, int]] = []
    enum_proc_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @enum_proc_type
    def visit(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))

        if title_contains and title_contains not in title_buffer.value:
            return True
        if class_name and class_buffer.value != class_name:
            return True

        rect = wintypes.RECT()
        area = 0
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        matches.append((area, int(hwnd)))
        return True

    user32.EnumWindows(visit, 0)
    if not matches:
        return None
    return max(matches)[1]


def _stop_runner(process: subprocess.Popen[str], timeout_seconds: float = 10.0) -> None:
    if process.poll() is not None:
        return
    if process.stdin is not None:
        try:
            process.stdin.write("stop\n")
            process.stdin.flush()
        except OSError:
            pass
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _start_runner(
    hwnd: int,
    entry: str,
    mouse_method: int,
    keyboard_method: int,
) -> subprocess.Popen[str]:
    runner_path = Path(__file__).with_name("launch_game_runner.py")
    command = [
        sys.executable,
        str(runner_path),
        "--hwnd",
        str(hwnd),
        "--entry",
        entry,
        "--mouse-method",
        str(mouse_method),
        "--keyboard-method",
        str(keyboard_method),
    ]
    return subprocess.Popen(
        command,
        cwd=Path.cwd(),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@AgentServer.custom_action("launch_game_wait_and_run")
class LaunchGameWaitAndRun(CustomAction):
    """Wait for the game window and run an existing pipeline on a new controller."""

    def run(self, context, argv: CustomAction.RunArg) -> bool:
        param = _parse_param(argv.custom_action_param)
        title_contains = str(param.get("title_contains", "洛克王国：世界"))
        class_name = str(param.get("class_name", "UnrealWindow"))
        wegame_title_contains = str(param.get("wegame_title_contains", "WeGame"))
        wegame_class_name = str(param.get("wegame_class_name", ""))
        wegame_click_entry = str(
            param.get("wegame_click_entry", "LaunchGameClickWeGameStart")
        )
        downstream_entry = str(param.get("downstream_entry", "BattleHostingStart"))
        timeout_ms = _positive_int(param.get("timeout_ms"), 180_000, 900_000)
        poll_interval_ms = _positive_int(
            param.get("poll_interval_ms"), 500, 10_000
        )
        mouse_method = _positive_int(
            param.get("mouse_method"), _INTERCEPTION, 1 << 20
        )
        keyboard_method = _positive_int(
            param.get("keyboard_method"), _INTERCEPTION, 1 << 20
        )
        wegame_mouse_method = _positive_int(
            param.get("wegame_mouse_method"), _SEIZE, 1 << 20
        )
        wegame_keyboard_method = _positive_int(
            param.get("wegame_keyboard_method"), _SEIZE, 1 << 20
        )

        _log(
            "waiting for window "
            f"title_contains={title_contains!r} class_name={class_name!r} "
            f"timeout_ms={timeout_ms}"
        )
        deadline = time.monotonic() + timeout_ms / 1000
        hwnd = None
        click_attempted = False
        while time.monotonic() < deadline:
            if context.tasker.stopping:
                _log("parent task is stopping while waiting for the game window")
                return True
            hwnd = _find_window(title_contains, class_name)
            if hwnd is not None:
                break

            if not click_attempted:
                wegame_hwnd = _find_window(
                    wegame_title_contains, wegame_class_name
                )
                if wegame_hwnd is not None:
                    click_attempted = True
                    _log(
                        f"WeGame window found hwnd=0x{wegame_hwnd:X}; "
                        f"starting template click entry={wegame_click_entry!r}"
                    )
                    click_runner = _start_runner(
                        wegame_hwnd,
                        wegame_click_entry,
                        wegame_mouse_method,
                        wegame_keyboard_method,
                    )
                    try:
                        while (
                            click_runner.poll() is None
                            and time.monotonic() < deadline
                        ):
                            if context.tasker.stopping:
                                _log(
                                    "parent task is stopping; stopping WeGame click"
                                )
                                _stop_runner(click_runner)
                                return True
                            hwnd = _find_window(title_contains, class_name)
                            if hwnd is not None:
                                _log(
                                    "game window appeared while WeGame click was running"
                                )
                                _stop_runner(click_runner)
                                break
                            if not ctypes.windll.user32.IsWindow(wegame_hwnd):
                                _log(
                                    "WeGame window closed after click; waiting for game window"
                                )
                                _stop_runner(click_runner)
                                break
                            time.sleep(0.1)

                        if hwnd is not None:
                            break
                        if click_runner.poll() is None:
                            _stop_runner(click_runner)
                        elif click_runner.returncode == 0:
                            _log(
                                "WeGame start-button click action sent; "
                                "waiting for the game window"
                            )
                        else:
                            _log(
                                "WeGame start button template click failed "
                                f"exit_code={click_runner.returncode}; "
                                "continuing to wait for a manually started game"
                            )
                    finally:
                        _stop_runner(click_runner)
            time.sleep(poll_interval_ms / 1000)

        if hwnd is None:
            _log("game window wait timed out")
            return False

        _log(
            f"game window found hwnd=0x{hwnd:X}; "
            f"starting existing downstream pipeline entry={downstream_entry!r}"
        )
        process = _start_runner(
            hwnd,
            downstream_entry,
            mouse_method,
            keyboard_method,
        )
        try:
            while process.poll() is None:
                if context.tasker.stopping:
                    _log("parent task is stopping; stopping downstream pipeline")
                    _stop_runner(process)
                    return True
                if not ctypes.windll.user32.IsWindow(hwnd):
                    _log("game window closed; stopping downstream pipeline")
                    _stop_runner(process)
                    return True
                time.sleep(0.1)

            if process.returncode == 0:
                _log(f"downstream pipeline completed entry={downstream_entry!r}")
                return True

            _log(
                f"downstream pipeline failed entry={downstream_entry!r} "
                f"exit_code={process.returncode}"
            )
            return False
        finally:
            _stop_runner(process)
