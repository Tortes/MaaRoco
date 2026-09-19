"""Exercise the native Agent with synthetic frames; never send real game input.

Developer-only dependencies: MaaFw 5.13.0 and numpy. These are not packaged.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time
import sys
import platform


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.install_root.resolve()
    windows = sys.platform == "win32"
    rid = "win-x64" if windows else ("osx-arm64" if platform.machine() == "arm64" else "osx-x64")
    binary = root / f"runtimes/{rid}/native"
    executable = "MaaRocoAgent.exe" if windows else "MaaRocoAgent"
    creationflags = subprocess.CREATE_NO_WINDOW if windows else 0
    os.environ["MAAFW_BINARY_PATH"] = str(binary)
    dll_directory = os.add_dll_directory(str(binary)) if windows else None
    from maa.agent_client import AgentClient
    from maa.controller import CustomController
    from maa.resource import Resource
    from maa.tasker import Tasker
    import numpy as np
    import cv2

    class SyntheticController(CustomController):
        def __init__(self):
            super().__init__()
            self.events = []
            self.fail_after_down = False
            self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            self.frame[310:410, 590:690] = (255, 0, 0)

        def connect(self): return True
        def request_uuid(self): return "native-agent-synthetic-test"
        def start_app(self, intent): return False
        def stop_app(self, intent): return False
        def screencap(self):
            if self.fail_after_down and self.events and self.events[-1] == "down":
                return np.empty((0, 0, 3), dtype=np.uint8)
            return self.frame.copy()
        def click(self, x, y): return False
        def swipe(self, *args): return False
        def touch_down(self, *args): self.events.append("down"); return True
        def touch_move(self, *args): self.events.append("move"); return True
        def touch_up(self, *args): self.events.append("up"); return True
        def click_key(self, *args): return False
        def input_text(self, *args): return False
        def key_down(self, *args): return False
        def key_up(self, *args): return False

    controller = SyntheticController()
    resource = Resource()
    tasker = Tasker()
    client = AgentClient()
    assert controller.post_connection().wait().succeeded
    assert controller.set_screenshot_use_raw_size(True)
    assert resource.post_bundle(root / "resource").wait().succeeded, "Release resource bundle failed to load"
    assert tasker.bind(resource, controller)
    assert client.bind(resource)
    assert client.register_sink(resource, controller, tasker)
    assert client.set_timeout(5000)
    with tempfile.TemporaryDirectory(prefix="maaroco-native-test-", ignore_cleanup_errors=True) as directory:
        Tasker.set_log_dir(directory)
        output = Path(directory) / "agent.log"
        with output.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(binary / executable), client.identifier],
                cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            try:
                assert client.connect(), "Native Agent IPC connection failed"
                def action(name, params):
                    return {"recognition": "DirectHit", "action": "Custom", "custom_action": name,
                            "custom_action_param": params, "pre_delay": 0, "post_delay": 0}
                detect = {"recognition": "Custom", "custom_recognition": "yueya_xuexiong_blue",
                          "custom_recognition_param": {}, "action": "DoNothing", "pre_delay": 0, "post_delay": 0}
                aim = {"target_recognition": "SyntheticBlue", "trajectory_base_lift_px": 0,
                       "trajectory_distance_lift_px": 0, "settle_delay_ms": 0, "min_hold_ms": 1}
                impossible = {"title_contains": "MaaRoco_TEST_NO_SUCH_WINDOW_738162",
                              "class_name": "MaaRoco_TEST_NO_SUCH_CLASS", "process_name": "no-such-process.exe",
                              "wegame_title_contains": "MaaRoco_TEST_NO_SUCH_WINDOW_738162",
                              "wegame_class_name": "MaaRoco_TEST_NO_SUCH_CLASS", "wegame_process_name": "no-such-process.exe",
                              "timeout_ms": 20, "poll_interval_ms": 1}
                pipeline = {"SyntheticBlue": detect,
                            "Explore": action("target_pet_explore", aim),
                            "SnowExplore": action("yueya_xuexiong_explore", aim),
                            "SnowThrow": action("yueya_xuexiong_aim_and_throw", aim),
                            "Reset": action("target_pet_explore", {"reset": True}),
                            "LaunchTimeout": action("launch_game_wait_and_run", impossible)}
                assert resource.override_pipeline(pipeline)
                def run(entry, success=True):
                    job = tasker.post_task(entry)
                    deadline = time.monotonic() + 15
                    while not job.done and time.monotonic() < deadline: time.sleep(.02)
                    assert job.done, f"{entry} hung"
                    assert job.succeeded == success, f"{entry}: unexpected result"
                    return job
                run("SyntheticBlue")
                # Verify the replacement HSV/component code against OpenCV on
                # varied colors, diagonally touching shapes and centroids.
                original_frame = controller.frame.copy()
                rng = np.random.default_rng(7318)
                for sample in range(12):
                    frame = np.zeros((80, 100, 3), dtype=np.uint8)
                    colors = rng.integers(0, 256, (4, 3), dtype=np.uint8)
                    colors[0] = (255, 0, 0)
                    for i, color in enumerate(colors):
                        x, y = 5 + i * 22, 12 + (i % 2) * 25
                        frame[y:y+13, x:x+15] = color
                    frame[25:33, 20:28] = (255, 0, 0)
                    controller.frame = frame
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    lower = [sample * 5, 40, 50]
                    upper = [179 - sample * 3, 255, 255]
                    mask = cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8))
                    count, _, stats, centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
                    candidates = []
                    for i in range(1, count):
                        x, y, w, h, area = map(int, stats[i])
                        if area >= 1 and area / (w*h) >= .05:
                            candidates.append((area, x, y, w, h, area/(w*h), i))
                    expected = max(candidates)
                    area, x, y, w, h, _, i = expected
                    cx, cy = centers[i]
                    expected_box = (round(cx-w/2), round(cy-h/2), w, h)
                    assert resource.override_pipeline({"SyntheticBlue": {"custom_recognition_param": {
                        "hsv_lower": lower, "hsv_upper": upper, "min_area_ratio": .0001,
                        "min_density": .05, "min_top_ratio": 0}}})
                    job = run("SyntheticBlue")
                    result = tasker.get_task_detail(job.job_id).nodes[-1].recognition
                    assert tuple(result.box) == expected_box, (sample, result.box, expected_box)
                    assert result.best_result.detail["area"] == area
                controller.frame = original_frame
                assert resource.override_pipeline({"SyntheticBlue": {"custom_recognition_param": {}}})
                run("Reset")
                for entry in ("Explore", "SnowExplore", "SnowThrow"):
                    controller.events.clear()
                    run(entry)
                    assert controller.events == ["down", "up"], (entry, controller.events)
                for entry in ("Explore", "SnowThrow"):
                    controller.events.clear()
                    controller.fail_after_down = True
                    run(entry, False)
                    assert controller.events == ["down", "up"], (entry, "held input leaked", controller.events)
                controller.fail_after_down = False
                run("LaunchTimeout", False)
                assert resource.override_pipeline({"LaunchTimeout": {"custom_action_param": dict(impossible, timeout_ms=60000)}})
                job = tasker.post_task("LaunchTimeout")
                time.sleep(.2)
                stop = tasker.post_stop()
                deadline = time.monotonic() + 5
                while not stop.done and time.monotonic() < deadline: time.sleep(.02)
                assert stop.done, "Native launch action did not respond to stop"
                if windows:
                    # Invalid HWND fails before any desktop input is attempted.
                    result = subprocess.run([str(binary / "MaaRocoRunner.exe"), "--hwnd", "0"],
                                            cwd=directory, timeout=5, creationflags=creationflags)
                    assert result.returncode == 2
                print("Native IPC, blue recognition, snow/target throwing, launch timeout and stop checks passed")
            except Exception:
                log.flush()
                print(output.read_text(encoding="utf-8", errors="replace"))
                raise
            finally:
                if tasker.running: tasker.post_stop()
                client.disconnect()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    del dll_directory


if __name__ == "__main__":
    main()
