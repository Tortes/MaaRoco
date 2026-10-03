import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

original_argv = sys.argv
sys.argv = ["install.py", "v0.0.0-dev", "win", "x86_64"]
import install
sys.argv = original_argv


class InstallNativeRuntimeTest(unittest.TestCase):
    def test_builds_native_agent(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)), \
                patch.object(sys, "platform", "win32"), \
                patch.object(sys, "argv", ["install.py"]), \
                patch.object(install.shutil, "which", return_value="pwsh"), \
                patch.object(install.subprocess, "run") as run:
            install.install_agent()
            run.assert_called_once()
            self.assertIn("build_native_agent.ps1", " ".join(run.call_args.args[0]))
            self.assertTrue(run.call_args.kwargs["check"])

    def test_removes_legacy_runtime_but_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            root = Path(directory)
            for name in ("python/python.exe", "agent/main.py", "resource/model/detect/pipa_bird.onnx", "config/settings.json", "debug/test.log"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test")
            install.remove_legacy_files()
            self.assertFalse((root / "python").exists())
            self.assertFalse((root / "agent").exists())
            self.assertFalse((root / "resource/model/detect/pipa_bird.onnx").exists())
            self.assertTrue((root / "config/settings.json").exists())
            self.assertTrue((root / "debug/test.log").exists())


class InstallDefaultConfigTest(unittest.TestCase):
    def test_initial_quick_and_pipeline_tabs(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            install.install_default_config()
            install.install_global_config()
            instance_dir = Path(directory) / "config/instances"
            default = json.loads((instance_dir / "default.json").read_text(encoding="utf-8"))
            quick = json.loads((instance_dir / "quick-tasks.json").read_text(encoding="utf-8"))
            global_config = json.loads((Path(directory) / "appsettings.json").read_text(encoding="utf-8"))
            self.assertEqual(default["InstanceName"], "任务队列")
            self.assertEqual(default["MaaRoco.TaskMode"], "queue")
            self.assertEqual(quick["InstanceName"], "单任务")
            self.assertEqual(quick["MaaRoco.TaskMode"], "quick")
            self.assertEqual(default["TaskItems"][0]["name"], "LaunchGame")
            self.assertFalse(default["TaskItems"][0]["default_check"])
            self.assertIn("BattleHosting", [task["name"] for task in default["TaskItems"]])
            self.assertEqual(quick["CurrentControllerName"], "Win32-Interception")
            self.assertEqual(quick["DesktopWindowClassName"], "UnrealWindow")
            self.assertEqual(quick["DesktopWindowName"], "洛克王国：世界")
            self.assertEqual(quick["Win32ControlMouseType"], 512)
            self.assertEqual(quick["TaskItems"], install.initial_task_items())
            self.assertEqual(set(quick["CurrentTasks"]), set(default["CurrentTasks"]))
            self.assertFalse((instance_dir / "launch-game.json").exists())
            self.assertEqual(global_config["Instances.List"], "quick-tasks,default")
            self.assertEqual(global_config["Instances.Order"], "quick-tasks,default")
            self.assertEqual(global_config["Instances.LastActive"], "quick-tasks")
            self.assertEqual(global_config["LinkStart"], "F11")

    def test_migrates_old_queue_without_losing_user_settings(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            instance_path = Path(directory) / "config/instances/default.json"
            instance_path.parent.mkdir(parents=True)
            saved_task = {"name": "RandomThrow", "entry": "RandomThrowStart", "default_check": True,
                          "option": [{"name": "RandomThrowClickDuration", "data": {"HoldMin": "250"}}]}
            instance_path.write_text(json.dumps({"TaskItems": [saved_task], "InstanceName": "我的配置"}), encoding="utf-8")
            install.install_default_config()
            install.install_default_config()
            instance = json.loads(instance_path.read_text(encoding="utf-8"))
            self.assertEqual([task["name"] for task in instance["TaskItems"]], ["LaunchGame", "RandomThrow"])
            self.assertEqual(instance["TaskItems"][1], saved_task)
            self.assertEqual(instance["InstanceName"], "我的配置")
            self.assertEqual(len(instance["CurrentTasks"]), 2)
            self.assertEqual(instance["MaaRoco.TaskMode"], "queue")
            quick = json.loads((instance_path.parent / "quick-tasks.json").read_text(encoding="utf-8"))
            quick_throw = next(task for task in quick["TaskItems"] if task["name"] == "RandomThrow")
            self.assertEqual(quick_throw["option"], saved_task["option"])
            # Existing queue check states do not become quick-mode defaults.
            source_throw = next(task for task in install.initial_task_items() if task["name"] == "RandomThrow")
            self.assertEqual(quick_throw["default_check"], source_throw["default_check"])

    def test_migrates_launcher_options_and_backs_up_full_customized_tab(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            instance_dir = Path(directory) / "config/instances"
            instance_dir.mkdir(parents=True)
            options = [{"name": "WeGamePath", "index": 0, "data": {"WeGameExecutable": "D:\\WeGame\\wegame.exe"}},
                       {"name": "WeGameLoginSource", "index": 1}]
            (instance_dir / "default.json").write_text(json.dumps({"TaskItems": [
                {"name": "LaunchGame", "entry": "LaunchGameStart", "default_check": False, "option": options}
            ]}), encoding="utf-8")
            launcher_path = instance_dir / "launch-game.json"
            launcher = {"InstanceName": "自定义启动", "CurrentControllerName": "Win32-Launcher",
                        "DesktopWindowName": "Program Manager", "MySetting": "keep this",
                        "TaskItems": [{"name": "LaunchGame", "entry": "LaunchGameStart",
                                       "default_check": True, "option": options}]}
            original_bytes = json.dumps(launcher).encode("utf-8")
            launcher_path.write_bytes(original_bytes)
            install.install_default_config()
            quick_path = instance_dir / "quick-tasks.json"
            quick = json.loads(quick_path.read_text(encoding="utf-8"))
            self.assertEqual(quick["TaskItems"][0]["option"], options)
            self.assertFalse(quick["TaskItems"][0]["default_check"])
            self.assertFalse(launcher_path.exists())
            backup = Path(directory) / "config/backups/launch-game.json"
            self.assertEqual(backup.read_bytes(), original_bytes)
            install.install_default_config()
            self.assertEqual(json.loads(quick_path.read_text(encoding="utf-8")), quick)
            self.assertEqual(backup.read_bytes(), original_bytes)

    def test_does_not_restore_user_deleted_queue_tasks_or_quick_tab(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            install.install_default_config()
            instance_dir = Path(directory) / "config/instances"
            instance_path = instance_dir / "default.json"
            instance = json.loads(instance_path.read_text(encoding="utf-8"))
            instance["TaskItems"] = [task for task in instance["TaskItems"] if task["name"] != "LaunchGame"]
            instance_path.write_text(json.dumps(instance), encoding="utf-8")
            (instance_dir / "quick-tasks.json").unlink()
            install.install_default_config()
            install.install_global_config()
            instance = json.loads(instance_path.read_text(encoding="utf-8"))
            self.assertNotIn("LaunchGame", [task["name"] for task in instance["TaskItems"]])
            self.assertFalse((instance_dir / "launch-game.json").exists())
            self.assertFalse((instance_dir / "quick-tasks.json").exists())
            global_config = json.loads((Path(directory) / "appsettings.json").read_text(encoding="utf-8"))
            self.assertEqual(global_config["Instances.List"], "default")

    def test_preserves_custom_tabs_and_global_settings_when_registering_modes(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            root = Path(directory)
            instance_dir = root / "config/instances"
            instance_dir.mkdir(parents=True)
            custom = {"InstanceName": "我的捕捉配置", "TaskItems": [], "CustomSetting": 42}
            (instance_dir / "490b7895.json").write_text(json.dumps(custom), encoding="utf-8")
            (instance_dir / "default.json").write_text(json.dumps({"InstanceName": "配置 1"}), encoding="utf-8")
            (root / "appsettings.json").write_text(json.dumps({
                "Instances.List": "default,490b7895,launch-game",
                "Instances.Order": "490b7895,default,launch-game",
                "Instances.LastActive": "490b7895", "Timer.Timer1.Config": "490b7895",
                "CustomGlobalSetting": True,
            }), encoding="utf-8")
            install.install_default_config()
            install.install_global_config()
            config = json.loads((root / "appsettings.json").read_text(encoding="utf-8"))
            self.assertEqual(config["Instances.List"], "quick-tasks,default,490b7895")
            self.assertEqual(config["Instances.Order"], "quick-tasks,default,490b7895")
            self.assertEqual(config["Instances.LastActive"], "490b7895")
            self.assertEqual(config["Instances.LastActiveName"], "我的捕捉配置")
            self.assertEqual(config["Timer.Timer1.Config"], "490b7895")
            self.assertTrue(config["CustomGlobalSetting"])
            migrated_custom = json.loads((instance_dir / "490b7895.json").read_text(encoding="utf-8"))
            for key, value in custom.items():
                self.assertEqual(migrated_custom[key], value)
            self.assertEqual(migrated_custom["CurrentControllerName"], "Win32-Interception")
            self.assertEqual(migrated_custom["Win32ControlMouseType"], 512)
            self.assertEqual(json.loads((instance_dir / "default.json").read_text(encoding="utf-8"))["InstanceName"], "任务队列")

    def test_redirects_retired_launcher_selection_without_rewriting_scheduler(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            root = Path(directory)
            (root / "appsettings.json").write_text(json.dumps({
                "Instances.LastActive": "launch-game", "Instances.LastActiveName": "启动游戏",
                "Timer.Timer1.Config": "launch-game", "Instance.launch-game.Name": "启动游戏",
            }), encoding="utf-8")
            install.install_default_config()
            install.install_global_config()
            config = json.loads((root / "appsettings.json").read_text(encoding="utf-8"))
            self.assertEqual(config["Instances.LastActive"], "quick-tasks")
            self.assertEqual(config["Instances.LastActiveName"], "单任务")
            self.assertEqual(config["Timer.Timer1.Config"], "launch-game")
            self.assertNotIn("Instance.launch-game.Name", config)

    def test_retains_launcher_tab_used_by_an_enabled_schedule(self):
        for enabled_value in ("True", True):
            with self.subTest(enabled=enabled_value), tempfile.TemporaryDirectory() as directory, \
                    patch.object(install, "install_path", Path(directory)):
                root = Path(directory)
                instance_dir = root / "config/instances"
                instance_dir.mkdir(parents=True)
                launcher_path = instance_dir / "launch-game.json"
                original = {"InstanceName": "定时启动",
                    "CurrentControllerName": "Win32-Launcher", "CurrentController": "Win32",
                    "Win32ControlMouseType": 1, "Win32ControlKeyboardType": 1,
                    "DesktopWindowClassName": "Progman", "DesktopWindowName": "Program Manager",
                    "TaskItems": [{"name": "LaunchGame", "entry": "LaunchGameStart",
                                   "default_check": True, "controller": ["Win32-Launcher"],
                                   "option": [{"name": "WeGamePath", "data": {
                                       "WeGameExecutable": "D:\\Scheduled\\wegame.exe"}}]}],
                    "CurrentTasks": ["LaunchGame<|||>LaunchGameStart"], "CustomSetting": 42}
                launcher_path.write_text(json.dumps(original), encoding="utf-8")
                timers = {"Timer.Timer1": enabled_value, "Timer.Timer1Time": "8:00",
                          "Timer.Timer1.Schedule": "0||", "Timer.Timer1.Config": "launch-game"}
                (root / "appsettings.json").write_text(json.dumps({**timers,
                    "Instances.LastActive": "launch-game"}), encoding="utf-8")
                install.install_default_config()
                install.install_global_config()
                config = json.loads((root / "appsettings.json").read_text(encoding="utf-8"))
                self.assertEqual(config["Instances.List"], "quick-tasks,default,launch-game")
                self.assertEqual(config["Instances.LastActive"], "launch-game")
                self.assertEqual(config["Instances.LastActiveName"], "定时启动")
                self.assertEqual({key: config[key] for key in timers}, timers)
                migrated = json.loads(launcher_path.read_text(encoding="utf-8"))
                expected_tasks = [dict(original["TaskItems"][0], controller=["Win32-Interception"])]
                self.assertEqual(migrated["TaskItems"], expected_tasks)
                self.assertEqual(migrated["CurrentTasks"], original["CurrentTasks"])
                self.assertEqual(migrated["CustomSetting"], 42)
                self.assertEqual(migrated["CurrentControllerName"], "Win32-Interception")
                self.assertEqual(migrated["Win32ControlKeyboardType"], 512)
                self.assertEqual(migrated["DesktopWindowClassName"], "UnrealWindow")
                self.assertEqual(migrated["DesktopWindowName"], "洛克王国：世界")
                self.assertFalse((root / "config/backups/launch-game.json").exists())

    def test_migrates_all_tabs_and_preserves_custom_game_window_and_queue(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            root = Path(directory)
            instance_dir = root / "config/instances"
            instance_dir.mkdir(parents=True)
            tasks = [
                {"name": "BattleHosting", "entry": "BattleHostingStart", "default_check": False,
                 "option": [{"name": "CustomOption", "data": {"value": "keep"}}]},
                {"name": "LaunchGame", "entry": "LaunchGameStart", "default_check": True,
                 "controller": ["Win32-Launcher"],
                 "option": [{"name": "WeGameLoginSource", "index": 1}]},
                {"name": "BattleHosting", "entry": "BattleHostingStart", "default_check": True,
                 "option": []},
            ]
            history = ["BattleHosting<|||>BattleHostingStart", "LaunchGame<|||>LaunchGameStart"]
            custom = {"InstanceName": "微信战斗配置", "CurrentControllerName": "Win32-Launcher",
                      "CurrentController": "Win32", "Win32ControlMouseType": 1,
                      "Win32ControlKeyboardType": 1, "Win32ControlScreenCapType": "FramePool",
                      "DesktopWindowClassName": "UnrealWindow", "DesktopWindowName": "我的游戏窗口",
                      "TaskItems": tasks, "CurrentTasks": history, "CustomSetting": {"keep": True}}
            custom_path = instance_dir / "custom.json"
            custom_path.write_text(json.dumps(custom), encoding="utf-8")
            install.install_default_config()
            install.install_default_config()
            migrated = json.loads(custom_path.read_text(encoding="utf-8"))
            expected_tasks = [dict(task) for task in tasks]
            expected_tasks[1]["controller"] = ["Win32-Interception"]
            self.assertEqual(migrated["TaskItems"], expected_tasks)
            self.assertEqual(migrated["CurrentTasks"], history)
            self.assertEqual(migrated["InstanceName"], custom["InstanceName"])
            self.assertEqual(migrated["CustomSetting"], custom["CustomSetting"])
            self.assertEqual(migrated["DesktopWindowClassName"], "UnrealWindow")
            self.assertEqual(migrated["DesktopWindowName"], "我的游戏窗口")
            self.assertEqual(migrated["CurrentControllerName"], "Win32-Interception")
            self.assertEqual(migrated["Win32ControlMouseType"], 512)
            self.assertEqual(migrated["Win32ControlKeyboardType"], 512)
            self.assertEqual(migrated["Win32ControlScreenCapType"], "ScreenDC")

    def test_existing_quick_tab_migrates_launcher_desktop_without_losing_options(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            install.install_default_config()
            path = Path(directory) / "config/instances/quick-tasks.json"
            quick = json.loads(path.read_text(encoding="utf-8"))
            quick.update({"CurrentControllerName": "Win32-Launcher", "Win32ControlMouseType": 1,
                          "Win32ControlKeyboardType": 1, "DesktopWindowClassName": "Progman",
                          "DesktopWindowName": "Program Manager", "InstanceName": "我的快捷任务"})
            quick["TaskItems"][0]["controller"] = ["Win32-Launcher"]
            quick["TaskItems"][0]["option"][0]["data"] = {"WeGameExecutable": "C:\\Quick\\wegame.exe"}
            quick["TaskItems"][0]["default_check"] = True
            path.write_text(json.dumps(quick), encoding="utf-8")
            install.install_default_config()
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["InstanceName"], quick["InstanceName"])
            self.assertEqual(migrated["TaskItems"][0]["option"], quick["TaskItems"][0]["option"])
            self.assertTrue(migrated["TaskItems"][0]["default_check"])
            self.assertEqual(migrated["CurrentTasks"], quick["CurrentTasks"])
            self.assertEqual(migrated["TaskItems"][0]["controller"], ["Win32-Interception"])
            self.assertEqual(migrated["DesktopWindowClassName"], "UnrealWindow")
            self.assertEqual(migrated["DesktopWindowName"], "洛克王国：世界")
            self.assertEqual(migrated["CurrentControllerName"], "Win32-Interception")

    def test_retires_launcher_referenced_only_by_disabled_schedule(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            root = Path(directory)
            instance_dir = root / "config/instances"
            instance_dir.mkdir(parents=True)
            launcher_path = instance_dir / "launch-game.json"
            launcher_path.write_text('{"TaskItems": []}', encoding="utf-8")
            timers = {"Timer.Timer1": "False", "Timer.Timer1.Config": "launch-game"}
            (root / "appsettings.json").write_text(json.dumps(timers), encoding="utf-8")
            install.install_default_config()
            install.install_global_config()
            config = json.loads((root / "appsettings.json").read_text(encoding="utf-8"))
            self.assertFalse(launcher_path.exists())
            self.assertEqual({key: config[key] for key in timers}, timers)

    def test_keeps_quick_options_independent_after_reinstall(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            install.install_default_config()
            instance_dir = Path(directory) / "config/instances"
            quick_path = instance_dir / "quick-tasks.json"
            quick = json.loads(quick_path.read_text(encoding="utf-8"))
            quick["TaskItems"][0]["option"][0]["data"] = {"WeGameExecutable": "C:\\Quick\\wegame.exe"}
            quick["InstanceName"] = "我的单任务"
            quick_path.write_text(json.dumps(quick), encoding="utf-8")
            install.install_default_config()
            self.assertEqual(json.loads(quick_path.read_text(encoding="utf-8")), quick)
            queue = json.loads((instance_dir / "default.json").read_text(encoding="utf-8"))
            self.assertNotIn("data", queue["TaskItems"][0]["option"][0])

    def test_preserves_existing_legacy_backup_when_migrating_another_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(install, "install_path", Path(directory)):
            root = Path(directory)
            backup = root / "config/backups/launch-game.json"
            backup.parent.mkdir(parents=True)
            backup.write_text('{"PreviousSnapshot": true}', encoding="utf-8")
            instance_dir = root / "config/instances"
            instance_dir.mkdir(parents=True)
            launcher_path = instance_dir / "launch-game.json"
            launcher_path.write_text('{"InstanceName": "启动游戏", "TaskItems": []}', encoding="utf-8")
            new_snapshot = launcher_path.read_bytes()
            install.install_default_config()
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"PreviousSnapshot": true}')
            self.assertEqual((backup.parent / "launch-game-1.json").read_bytes(), new_snapshot)

    def test_enables_stable_github_resource_updates(self):
        original_install_path = install.install_path
        original_version = install.version
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                install.install_path = Path(temp_dir)
                install.version = "v1.2.3"
                install.install_default_config()

                config_path = Path(temp_dir) / "config" / "config.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))

                self.assertTrue(config["EnableAutoUpdateResource"])
                self.assertTrue(config["EnableCheckVersion"])
                self.assertFalse(config["EnableAutoUpdateMFA"])
                self.assertEqual(config["DownloadSourceIndex"], 0)
                self.assertEqual(config["UIUpdateChannelIndex"], 2)
                self.assertEqual(config["ResourceUpdateChannelIndex"], 2)
                self.assertNotIn("AutoUpdateResource", config)
            finally:
                install.install_path = original_install_path
                install.version = original_version

    def test_disables_updates_for_debug_build(self):
        original_install_path = install.install_path
        original_version = install.version
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                install.install_path = Path(temp_dir)
                install.version = "v1.2.3-dev"
                install.install_default_config()

                config_path = Path(temp_dir) / "config" / "config.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))

                self.assertFalse(config["EnableAutoUpdateResource"])
                self.assertFalse(config["EnableCheckVersion"])
                self.assertFalse(config["EnableAutoUpdateMFA"])
                self.assertEqual(config["UIUpdateChannelIndex"], 0)
                self.assertEqual(config["ResourceUpdateChannelIndex"], 0)
            finally:
                install.install_path = original_install_path
                install.version = original_version

    def test_only_stable_versions_are_release_builds(self):
        self.assertTrue(install.is_release_version("v1.2.3"))
        for version in (
            "1.2.3",
            "v1.2.3-dev",
            "v1.2.3-ci.260816-abcdef0",
            "v1.2.3-alpha.1",
            "v1.2.3-beta.1",
            "v1.2.3-rc.1",
            "v1.2.3-dirty",
        ):
            with self.subTest(version=version):
                self.assertFalse(install.is_release_version(version))

    def test_selects_interception_controller_by_name_and_type(self):
        original_install_path = install.install_path
        original_version = install.version
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                install.install_path = Path(temp_dir)
                install.version = "v1.2.3-dev"
                install.install_default_config()

                instance_path = (
                    Path(temp_dir) / "config" / "instances" / "default.json"
                )
                instance = json.loads(instance_path.read_text(encoding="utf-8"))

                self.assertEqual(
                    instance["CurrentControllerName"], "Win32-Interception"
                )
                self.assertEqual(instance["CurrentController"], "Win32")
            finally:
                install.install_path = original_install_path
                install.version = original_version


if __name__ == "__main__":
    unittest.main()
