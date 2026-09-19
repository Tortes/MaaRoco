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
