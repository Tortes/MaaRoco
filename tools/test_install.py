import json
import sys
import tempfile
import unittest
from pathlib import Path

original_argv = sys.argv
sys.argv = ["install.py", "v0.0.0-dev", "win", "x86_64"]
import install
sys.argv = original_argv


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
