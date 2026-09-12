"""Send battle keys only after the bound game window has keyboard focus."""
import json
import time

import interception
import win32api
import win32con
import win32gui
import win32process
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction


def focus_window(hwnd):
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    for _ in range(3):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        current = win32api.GetCurrentThreadId()
        foreground = win32gui.GetForegroundWindow()
        threads = {win32process.GetWindowThreadProcessId(hwnd)[0]}
        if foreground:
            threads.add(win32process.GetWindowThreadProcessId(foreground)[0])
        attached = []
        try:
            for thread in threads - {current}:
                win32process.AttachThreadInput(current, thread, True)
                attached.append(thread)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetFocus(hwnd)
        except win32gui.error:
            pass
        finally:
            for thread in reversed(attached):
                win32process.AttachThreadInput(current, thread, False)
        time.sleep(0.1)
    return win32gui.GetForegroundWindow() == hwnd


@AgentServer.custom_action("battle_focused_key")
class BattleFocusedKey(CustomAction):
    def run(self, context, argv):
        controller = context.tasker.controller
        hwnd = int(controller.info.get("hwnd", 0))
        if not focus_window(hwnd):
            print(f"[battle_input] Focus unavailable for hwnd={hwnd}; key not sent", flush=True)
            return False
        key = int(json.loads(argv.custom_action_param)["key"])
        names = {32: "space", 49: "1", 50: "2", 51: "3", 52: "4", 87: "w"}
        if key not in names:
            raise ValueError(f"Unsupported battle key: {key}")
        # Driver endpoints exist even for empty keyboard slots. The native
        # backend prefers slot 1, while hot-plugging may put the keyboard in 2.
        interception.auto_capture_devices(keyboard=True, mouse=False)
        device_context = interception.inputs._g_context
        device = device_context.keyboard
        if not device_context.devices[device].get_HWID():
            print("[battle_input] No attached Interception keyboard; key not sent", flush=True)
            return False
        print(f"[battle_input] keyboard={device}, key={names[key]}", flush=True)
        interception.press(names[key])
        return True
