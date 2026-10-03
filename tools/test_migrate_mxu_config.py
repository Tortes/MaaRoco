import copy
import json
import tempfile
import unittest
from pathlib import Path

from migrate_mxu_config import migrate_config


class MxuMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "install"
        self.assets = Path(self.temporary.name) / "assets"
        self.root.mkdir()
        self.assets.mkdir()
        self.interface = {
            "name": "MaaRoco", "task": [], "import": ["tasks.json"],
            "controller": [{"name": "Win32-Interception"}], "resource": [{"name": "default"}],
        }
        self.tasks = {"task": [
            {"name": "LaunchGame", "entry": "LaunchGameStart", "default_check": False,
             "option": ["WeGamePath", "WeGameLoginSource"]},
            {"name": "Throw", "entry": "ThrowStart", "default_check": True, "option": ["Hold", "Mode", "Features", "Toggle"]},
        ], "option": {
            "WeGamePath": {"type": "input", "inputs": [{"name": "WeGameExecutable", "default": "C:\\WeGame\\wegame.exe"}]},
            "WeGameLoginSource": {"type": "select", "default_case": "QQ", "cases": [{"name": "QQ"}, {"name": "WeChat"}]},
            "Hold": {"type": "input", "inputs": [{"name": "Min", "default": "200"}, {"name": "Max", "default": "500"}]},
            "Mode": {"type": "select", "default_case": "Normal", "cases": [{"name": "Normal"}, {"name": "Special", "option": ["Child"]}]},
            "Child": {"type": "input", "inputs": [{"name": "Count", "default": "1"}]},
            "Features": {"type": "checkbox", "default_case": ["First"], "cases": [{"name": "First"}, {"name": "Second"}]},
            "Toggle": {"type": "switch", "default_case": "Yes", "cases": [{"name": "Yes"}, {"name": "No"}]},
        }}
        self.write(self.assets / "interface.json", self.interface)
        self.write(self.assets / "tasks.json", self.tasks)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def instance(self, identifier, value):
        self.write(self.root / "config/instances" / f"{identifier}.json", value)

    def migrate(self, version="v0.3.0"):
        report = migrate_config(self.root, self.assets, version)
        config = json.loads(Path(report["config_path"]).read_text(encoding="utf-8"))
        return report, config

    def test_fresh_install_has_single_catalog_and_empty_queue(self):
        report, config = self.migrate()
        self.assertEqual(report["status"], "initialized")
        self.assertEqual(config["version"], "1.0")
        self.assertEqual([(item["name"], item["maarocoMode"]) for item in config["instances"]],
                         [("单任务", "single"), ("任务队列", "queue")])
        single, queue = config["instances"]
        self.assertEqual([item["taskName"] for item in single["tasks"]], ["LaunchGame", "Throw"])
        self.assertEqual(queue["tasks"], [])
        self.assertTrue(all(not item["expanded"] for item in single["tasks"]))
        self.assertEqual(config["settings"]["hotkeys"], {"startTasks": "F10", "stopTasks": "F11", "globalEnabled": True})
        self.assertFalse(config["settings"]["screenshotPanelExpanded"])
        self.assertTrue(config["presetInitialized"])

    def test_order_checks_select_checkbox_switch_inputs_and_nested_options(self):
        self.instance("default", {"InstanceName": "我的队列", "TaskItems": [
            {"name": "Throw", "default_check": False, "display_name_override": "投掷 2", "option": [
                {"name": "Hold", "data": {"Min": "250", "Max": "", "RemovedInput": "123"}},
                {"name": "Mode", "index": 1, "sub_options": [{"name": "Child", "data": {"Count": "9"}}]},
                {"name": "Features", "selected_cases": ["Second", "First", "Second"]},
                {"name": "Toggle", "index": 1}]},
            {"name": "LaunchGame", "default_check": True},
            {"name": "Throw", "default_check": True},
        ], "CurrentTasks": ["LaunchGame<|||>LaunchGameStart", "Throw<|||>ThrowStart"]})
        report, config = self.migrate()
        queue = config["instances"][1]
        self.assertEqual(queue["name"], "我的队列")
        self.assertEqual([item["taskName"] for item in queue["tasks"]], ["Throw", "LaunchGame", "Throw"])
        self.assertEqual([item["enabled"] for item in queue["tasks"]], [False, True, True])
        self.assertEqual(len({item["id"] for item in queue["tasks"]}), 3)
        task = queue["tasks"][0]
        self.assertEqual(task["customName"], "投掷 2")
        self.assertEqual(task["optionValues"]["Hold"]["values"], {"Min": "250", "Max": ""})
        self.assertEqual(task["optionValues"]["Mode"], {"type": "select", "caseName": "Special"})
        self.assertEqual(task["optionValues"]["Child"]["values"]["Count"], "9")
        self.assertEqual(task["optionValues"]["Features"]["caseNames"], ["Second", "First"])
        self.assertFalse(task["optionValues"]["Toggle"]["value"])
        self.assertTrue(any("RemovedInput" in warning for warning in report["warnings"]))

    def test_empty_checkbox_is_preserved_instead_of_default(self):
        self.instance("default", {"TaskItems": [{"name": "Throw", "option": [{"name": "Features", "selected_cases": []}]}]})
        _, config = self.migrate()
        self.assertEqual(config["instances"][1]["tasks"][0]["optionValues"]["Features"]["caseNames"], [])

    def test_launcher_login_and_path_go_to_single_tab_without_changing_queue(self):
        self.instance("default", {"TaskItems": [{"name": "LaunchGame", "option": [{"name": "WeGameLoginSource", "index": 0}]}]})
        self.instance("launch-game", {"InstanceName": "启动", "TaskItems": [{"name": "LaunchGame", "option": [
            {"name": "WeGamePath", "data": {"WeGameExecutable": "D:\\腾讯\\WeGame\\wegame.exe"}},
            {"name": "WeGameLoginSource", "index": 1}]}]})
        _, config = self.migrate()
        single, queue = config["instances"][:2]
        self.assertEqual(single["tasks"][0]["optionValues"]["WeGamePath"]["values"]["WeGameExecutable"], "D:\\腾讯\\WeGame\\wegame.exe")
        self.assertEqual(single["tasks"][0]["optionValues"]["WeGameLoginSource"]["caseName"], "WeChat")
        self.assertEqual(queue["tasks"][0]["optionValues"]["WeGameLoginSource"]["caseName"], "QQ")
        self.assertTrue(any(item["name"] == "启动" for item in config["instances"]))

    def test_existing_quick_options_survive_new_tasks_and_ids_are_unique(self):
        self.instance("quick-tasks", {"TaskItems": [{"name": "Throw", "option": [{"name": "Hold", "data": {"Min": "777"}}]}]})
        _, config = self.migrate()
        tasks = config["instances"][0]["tasks"]
        self.assertEqual(tasks[1]["optionValues"]["Hold"]["values"]["Min"], "777")
        self.assertEqual(len({task["id"] for task in tasks}), len(tasks))

    def test_custom_tabs_order_resource_window_and_last_active(self):
        self.instance("a", {"InstanceName": "甲", "Resource": "my-resource", "DesktopWindowName": "游戏窗口", "TaskItems": []})
        self.instance("b", {"InstanceName": "乙", "TaskItems": []})
        self.write(self.root / "appsettings.json", {"Instances.Order": "b,a,default", "Instances.List": "a,b", "Instances.LastActive": "a"})
        report, config = self.migrate()
        self.assertEqual([item["name"] for item in config["instances"]], ["单任务", "任务队列", "乙", "甲"])
        self.assertEqual(config["instances"][3]["resourceName"], "my-resource")
        self.assertEqual(config["instances"][3]["savedDevice"]["windowName"], "游戏窗口")
        self.assertEqual(config["lastActiveInstanceId"], "mfa-a")
        self.assertTrue(any("my-resource" in warning for warning in report["warnings"]))

    def test_daily_weekly_schedules_and_unsupported_timers_are_reported(self):
        self.instance("default", {"TaskItems": [{"name": "Throw", "default_check": True}]})
        values = {}
        for number, schedule, action in ((1, "0||", "0"), (2, "1|6,1,1|", "0"), (3, "2||1,15", "0"), (4, "0||", "1")):
            prefix = f"Timer.Timer{number}"
            values.update({prefix: "True", prefix + "Time": "8:05", prefix + ".Config": "default",
                           prefix + ".Schedule": schedule, prefix + ".Action": action})
        self.write(self.root / "appsettings.json", values)
        report, config = self.migrate()
        policies = config["instances"][1]["schedulePolicies"]
        self.assertEqual(len(policies), 2)
        self.assertEqual(policies[0]["weekdays"], list(range(7)))
        self.assertEqual(policies[1]["weekdays"], [1, 6])
        self.assertEqual(policies[1]["times"], ["08:05"])
        self.assertTrue(all(item["enabled"] for item in policies))
        self.assertEqual([item["status"] for item in report["timers"]], ["migrated", "migrated", "retained", "retained"])
        self.assertEqual(report["timers"][2]["source"]["Timer.Timer3.Schedule"], "2||1,15")

    def test_unknown_task_option_invalid_index_and_corrupt_source_have_backup(self):
        self.instance("default", {"CustomSetting": 42, "TaskItems": [
            {"name": "Removed", "default_check": True},
            {"name": "Throw", "option": [{"name": "Unknown", "data": {"Secret": "kept"}}, {"name": "Mode", "index": -1}]}]})
        path = self.root / "config/instances/broken.json"
        path.write_bytes(b"\x00\x00invalid")
        original = (self.root / "config/instances/default.json").read_bytes()
        report, config = self.migrate()
        backup = Path(report["backup_path"])
        self.assertEqual((backup / "config/instances/default.json").read_bytes(), original)
        self.assertEqual((backup / "config/instances/broken.json").read_bytes(), b"\x00\x00invalid")
        self.assertTrue(any("Removed" in message for message in report["warnings"]))
        self.assertTrue(any("Unknown" in message for message in report["warnings"]))
        self.assertTrue(any("invalid index" in message for message in report["warnings"]))
        self.assertTrue(any("broken.json" in message for message in report["warnings"]))
        self.assertEqual(config["instances"][1]["tasks"][0]["optionValues"]["Mode"]["caseName"], "Normal")

    def test_original_jsonc_and_bom_bytes_are_unchanged_and_backed_up(self):
        path = self.root / "config/config.json"
        path.parent.mkdir(parents=True)
        content = b'\xef\xbb\xbf{ // comment\n "CurrentLanguage": "en-US", "url": "https://x//y", }'
        path.write_bytes(content)
        report, config = self.migrate()
        self.assertEqual(config["settings"]["language"], "en-US")
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual((Path(report["backup_path"]) / "config/config.json").read_bytes(), content)

    def test_repeated_migration_preserves_user_changes_and_does_not_recreate_tabs(self):
        self.instance("default", {"TaskItems": [{"name": "Throw", "default_check": True}]})
        report, config = self.migrate()
        destination = Path(report["config_path"])
        config["instances"] = [config["instances"][1]]
        config["settings"]["theme"] = "dark"
        self.write(destination, config)
        expected = destination.read_bytes()
        self.instance("default", {"TaskItems": [{"name": "LaunchGame"}]})
        second, _ = self.migrate()
        self.assertEqual(second["status"], "existing")
        self.assertEqual(destination.read_bytes(), expected)
        self.assertEqual(len(list((self.root / "config/backups").iterdir())), 1)

    def test_existing_unreadable_mxu_config_is_never_overwritten(self):
        path = self.root / "config/mxu-MaaRoco.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"corrupt user data")
        result = migrate_config(self.root, self.assets, "v0.3.0")
        self.assertEqual(result["status"], "existing")
        self.assertEqual(path.read_bytes(), b"corrupt user data")
        self.assertFalse((self.root / "config/backups").exists())

    def test_early_single_file_mfa_config_and_dev_update_channel(self):
        self.write(self.root / "config/config.json", {"TaskItems": [{"name": "Throw", "default_check": False}]})
        _, config = self.migrate("v0.3.0-dev")
        self.assertEqual(config["instances"][1]["tasks"][0]["taskName"], "Throw")
        self.assertFalse(config["instances"][1]["tasks"][0]["enabled"])
        self.assertEqual(config["settings"]["mirrorChyan"]["channel"], "beta")

    def test_import_path_cannot_escape_assets(self):
        bad = copy.deepcopy(self.interface)
        bad["import"] = ["../outside.json"]
        self.write(self.assets / "interface.json", bad)
        with self.assertRaisesRegex(ValueError, "escapes assets"):
            migrate_config(self.root, self.assets, "v0.3.0")
        self.assertFalse((self.root / "config/mxu-MaaRoco.json").exists())


if __name__ == "__main__":
    unittest.main()
