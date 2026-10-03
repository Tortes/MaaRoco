"""MXU distribution and installer integration regression tests."""

import hashlib
import json
import runpy
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

original_argv = sys.argv
sys.argv = ["install.py", "v0.3.0", "win", "x86_64"]
import install
import build_frontend
import configure
import validate_native_package
sys.argv = original_argv


class MxuInstallTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.output = Path(self.temporary.name) / "installed"
        self.output.mkdir()
        self.lock = {"flavor": "mxu", "commit": "a" * 40, "target": "win-x64",
                     "patch": "tools/frontend/mxu.patch", "version": "v2.7.1",
                     "repository": "https://github.com/MistEO/MXU.git"}
        self.frontend = self.root / "build/frontend/publish/mxu-win-x64"
        self.write(self.root / "tools/frontend/mxu.patch", "frontend patch")
        self.write(self.root / "frontend.lock.json", self.lock)
        self.write(self.root / "build/frontend/MXU/LICENSE", "MXU AGPL license")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, attribute, value in (
            (install, "working_dir", self.root), (install, "install_path", self.output),
            (install, "os_name", "win"), (install, "arch", "x86_64"), (install, "version", "v0.3.0"),
            (build_frontend, "ROOT", self.root),
        ):
            self.stack.enter_context(patch.object(target, attribute, value))
        self.stack.enter_context(patch.object(sys, "argv", ["install.py", "v0.3.0", "win", "x86_64"]))

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value, encoding="utf-8")

    def published_frontend(self, executable=b"verified MXU executable", metadata_changes=None):
        self.write(self.frontend / "mxu.exe", executable)
        metadata = build_frontend.frontend_metadata(self.lock)
        metadata["exe_sha256"] = hashlib.sha256(executable).hexdigest()
        metadata.update(metadata_changes or {})
        self.write(self.frontend / "maaroco-frontend.json", metadata)
        return metadata

    def assets(self):
        self.write(self.root / "assets/interface.json", {
            "name": "MaaRoco", "resource": [{"name": "default", "path": ["./resource"]}],
            "controller": [{"name": "Win32-Interception"}],
            "task": [{"name": "Throw", "entry": "ThrowStart", "default_check": True}],
            "agent": {"child_exec": "./runtimes/win-x64/native/MaaRocoAgent.exe", "child_args": []},
        })
        self.write(self.root / "assets/resource/pipeline/Throw.json", {"ThrowStart": {"action": "DoNothing"}})
        self.write(self.root / "training/yueya_xuexiong/models/yueya_xuexiong.onnx", b"test model")

    def runtime(self):
        self.write(self.root / "deps/bin/MaaFramework.dll", b"framework bytes")
        self.write(self.root / "deps/bin/plugins/MaaWin32ControlUnit.dll", b"Interception plugin")
        self.write(self.root / "deps/bin/MaaPiCli.exe", b"developer executable")
        self.write(self.root / "maaframework.lock.json", {"files": {
            "MaaFramework.dll": hashlib.sha256(b"framework bytes").hexdigest(),
        }, "release": {"url": "https://github.com/MaaXYZ/MaaFramework/releases/test"}})

    def test_verified_frontend_installs_exact_exe_metadata_and_agpl_license(self):
        metadata = self.published_frontend()
        self.write(self.frontend / "config/mxu-MaaRoco.json", {"instances": ["must not copy"]})
        with patch.object(install.subprocess, "run") as run:
            install.install_frontend()
        run.assert_not_called()
        self.assertEqual((self.output / "MaaRoco.exe").read_bytes(), b"verified MXU executable")
        self.assertEqual(json.loads((self.output / "maaroco-frontend.json").read_text(encoding="utf-8")), metadata)
        self.assertEqual((self.output / "licenses/MXU-AGPL-3.0.txt").read_text(encoding="utf-8"), "MXU AGPL license")
        self.assertFalse((self.output / "config/mxu-MaaRoco.json").exists())

    def test_stale_patch_metadata_triggers_build_and_new_verified_output_is_used(self):
        self.published_frontend(metadata_changes={"patch_sha256": "stale"})
        with patch.object(install.subprocess, "run", side_effect=lambda *args, **kwargs: self.published_frontend(b"rebuilt MXU")) as run:
            install.install_frontend()
        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual((self.output / "MaaRoco.exe").read_bytes(), b"rebuilt MXU")

    def test_tampered_executable_is_rebuilt(self):
        self.published_frontend()
        (self.frontend / "mxu.exe").write_bytes(b"tampered")
        with patch.object(install.subprocess, "run", side_effect=lambda *args, **kwargs: self.published_frontend(b"clean rebuild")) as run:
            install.install_frontend()
        run.assert_called_once()
        self.assertEqual((self.output / "MaaRoco.exe").read_bytes(), b"clean rebuild")

    def test_build_claiming_success_with_stale_metadata_is_rejected(self):
        self.published_frontend(metadata_changes={"commit": "wrong"})
        with patch.object(install.subprocess, "run"), self.assertRaises(RuntimeError):
            install.install_frontend()
        self.assertFalse((self.output / "MaaRoco.exe").exists())

    def test_build_claiming_success_with_bad_exe_hash_is_rejected(self):
        self.published_frontend()
        (self.frontend / "mxu.exe").write_bytes(b"wrong hash")
        with patch.object(install.subprocess, "run"), self.assertRaises(RuntimeError):
            install.install_frontend()
        self.assertFalse((self.output / "MaaRoco.exe").exists())

    def test_gnu_webview_loader_hash_is_verified_and_copied_to_install_root(self):
        loader = b"WebView loader runtime"
        self.write(self.frontend / "WebView2Loader.dll", loader)
        self.published_frontend(metadata_changes={"runtime_files": {"WebView2Loader.dll": hashlib.sha256(loader).hexdigest()}})
        with patch.object(install.subprocess, "run") as run:
            install.install_frontend()
        run.assert_not_called()
        self.assertEqual((self.output / "WebView2Loader.dll").read_bytes(), loader)

    def test_tampered_webview_loader_triggers_a_verified_rebuild(self):
        self.write(self.frontend / "WebView2Loader.dll", b"tampered loader")
        self.published_frontend(metadata_changes={"runtime_files": {"WebView2Loader.dll": hashlib.sha256(b"original loader").hexdigest()}})
        def rebuild(*arguments, **keywords):
            self.write(self.frontend / "WebView2Loader.dll", b"rebuilt loader")
            self.published_frontend(metadata_changes={"runtime_files": {"WebView2Loader.dll": hashlib.sha256(b"rebuilt loader").hexdigest()}})
        with patch.object(install.subprocess, "run", side_effect=rebuild) as run:
            install.install_frontend()
        run.assert_called_once()
        self.assertEqual((self.output / "WebView2Loader.dll").read_bytes(), b"rebuilt loader")

    def test_frontend_runtime_inventory_cannot_copy_unexpected_or_escaping_files(self):
        for runtime_files in ({"unexpected.dll": "hash"}, {"../escape.dll": "hash"},
                              {"WebView2Loader.dll": "wrong hash"}, ["WebView2Loader.dll"]):
            with self.subTest(runtime_files=runtime_files):
                self.published_frontend(metadata_changes={"runtime_files": runtime_files})
                with patch.object(install.subprocess, "run"), self.assertRaises(RuntimeError):
                    install.install_frontend()
                self.assertFalse((self.output / "MaaRoco.exe").exists())
                self.assertFalse((self.output / "unexpected.dll").exists())

    def test_dependencies_use_shared_maafw_directory_with_plugins(self):
        self.runtime()
        install.install_deps()
        self.assertEqual((self.output / "maafw/MaaFramework.dll").read_bytes(), b"framework bytes")
        self.assertTrue((self.output / "maafw/plugins/MaaWin32ControlUnit.dll").is_file())
        self.assertFalse((self.output / "maafw/MaaPiCli.exe").exists())
        self.assertFalse((self.output / "runtimes").exists())
        self.assertFalse((self.output / "libs").exists())

    def test_dependency_tamper_is_rejected_before_install(self):
        self.runtime()
        (self.root / "deps/bin/MaaFramework.dll").write_bytes(b"tampered framework")
        with self.assertRaisesRegex(RuntimeError, "Runtime hash mismatch"):
            install.install_deps()
        self.assertFalse((self.output / "maafw").exists())

    def test_installed_interface_runs_agent_from_shared_runtime_directory(self):
        self.assets()
        with patch.object(install, "configure_ocr_model"):
            install.install_resource()
        interface = json.loads((self.output / "interface.json").read_text(encoding="utf-8"))
        self.assertEqual(interface["version"], "v0.3.0")
        self.assertEqual(interface["agent"], {"child_exec": "./maafw/MaaRocoAgent.exe", "child_args": []})

    def test_upgrade_backs_up_exact_interface_bytes_and_keeps_valid_custom_resources(self):
        self.assets()
        custom = {"name": "custom", "path": ["./resource", "./custom-resource"],
                  "label": "我的资源", "description": "Preserve all resource fields"}
        invalid = {"name": "missing", "path": ["./missing-resource"]}
        original = b'\xef\xbb\xbf// previous interface, including a comment\r\n' + json.dumps(
            {"name": "MaaRoco", "resource": [custom, invalid]}, ensure_ascii=False).encode("utf-8")
        self.write(self.output / "interface.json", original)
        self.write(self.output / "custom-resource/pipeline/custom.json", b"custom bytes")
        self.write(self.output / "config/instances/custom.json", {
            "InstanceName": "自定义页", "Resource": "custom", "TaskItems": []})
        self.write(self.output / "appsettings.json", b'{"Instances.List":"custom"}\r\n')
        old_config = (self.output / "config/instances/custom.json").read_bytes()
        old_settings = (self.output / "appsettings.json").read_bytes()
        with patch.object(install, "configure_ocr_model"):
            install.install_resource()
        interface = json.loads((self.output / "interface.json").read_text(encoding="utf-8"))
        self.assertEqual(interface["resource"], [
            {"name": "default", "path": ["./resource"]}, custom])
        backup = self.output / f"config/backups/interface-before-mxu-{hashlib.sha256(original).hexdigest()}/interface.json"
        self.assertEqual(backup.read_bytes(), original)
        result = install.install_mxu_config()
        config = json.loads((self.output / "config/mxu-MaaRoco.json").read_text(encoding="utf-8"))
        self.assertEqual(next(instance for instance in config["instances"] if instance["name"] == "自定义页")["resourceName"], "custom")
        self.assertFalse(any("resource definition" in warning for warning in result["warnings"]))
        self.assertEqual((self.output / "custom-resource/pipeline/custom.json").read_bytes(), b"custom bytes")
        self.assertEqual((self.output / "config/instances/custom.json").read_bytes(), old_config)
        self.assertEqual((self.output / "appsettings.json").read_bytes(), old_settings)

    def test_upgrade_keeps_custom_default_path_and_imported_resource_definitions(self):
        self.assets()
        custom_default = {"name": "default", "path": [".\\custom-default"], "label": "My default"}
        imported = {"name": "imported", "path": ["./imported-resource"]}
        self.write(self.output / "interface.json", {"resource": [custom_default], "import": ["./tasks/custom-resources.json"]})
        self.write(self.output / "tasks/custom-resources.json", {"resource": [imported]})
        self.write(self.output / "custom-default/pipeline/task.json", {})
        self.write(self.output / "imported-resource/pipeline/task.json", {})
        with patch.object(install, "configure_ocr_model"):
            install.install_resource()
        self.assertEqual(json.loads((self.output / "interface.json").read_text(encoding="utf-8"))["resource"], [custom_default, imported])

    def test_upgrade_keeps_existing_absolute_resource_directories(self):
        self.assets()
        external_resource = self.root / "external-resource"
        self.write(external_resource / "pipeline/user.json", b"external resource bytes")
        resource = {"name": "external", "path": [str(external_resource)]}
        self.write(self.output / "interface.json", {"resource": [resource]})
        with patch.object(install, "configure_ocr_model"):
            install.install_resource()
        self.assertIn(resource, json.loads((self.output / "interface.json").read_text(encoding="utf-8"))["resource"])
        install.remove_legacy_files()
        self.assertEqual((external_resource / "pipeline/user.json").read_bytes(), b"external resource bytes")

    def test_repeated_interface_install_never_overwrites_an_earlier_backup(self):
        self.assets()
        original = b'{"name":"MaaRoco","resource":[]}\r\n'
        self.write(self.output / "interface.json", original)
        with patch.object(install, "configure_ocr_model"):
            install.install_resource()
            install.install_resource()
            backups = {path: path.read_bytes() for path in (self.output / "config/backups").rglob("interface.json")}
            install.install_resource()
        self.assertEqual({path: path.read_bytes() for path in (self.output / "config/backups").rglob("interface.json")}, backups)
        self.assertIn(original, backups.values())

    def test_invalid_old_interface_is_backed_up_before_it_is_replaced(self):
        self.assets()
        original = b'{not valid JSON, but recoverable user bytes}\r\n'
        self.write(self.output / "interface.json", original)
        with patch.object(install, "configure_ocr_model"):
            install.install_resource()
        self.assertTrue(any(path.read_bytes() == original for path in (self.output / "config/backups").rglob("interface.json")))
        self.assertEqual(json.loads((self.output / "interface.json").read_text(encoding="utf-8"))["name"], "MaaRoco")

    def test_cleanup_removes_only_known_mfa_runtime_and_preserves_user_files(self):
        self.assets()
        self.write(self.output / "interface.json", {"resource": [
            {"name": "default", "path": ["./resource"]},
            {"name": "custom", "path": ["./agent/custom-resource"]},
            {"name": "empty", "path": ["./libs/empty-resource"]},
        ]})
        known = ("MFAAvalonia.exe", "MFAAvalonia.dll", "MFAAvalonia.runtimeconfig.json",
                 "libs/MFAAvalonia.Core.dll", "libs/Avalonia.Base.dll", "libloader.dll",
                 "runtimes/win-x64/native/MaaFramework.dll", "runtimes/win-x64/native/DirectML.dll",
                 "runtimes/win-x64/native/MaaRocoAgent.exe", "plugins/win-x64/MaaPluginDemo.dll")
        for relative in known:
            self.write(self.output / relative, b"old runtime")
        self.write(self.output / "MFAAvalonia.deps.json", {"targets": {"net10.0/win-x64": {
            "Avalonia/1.0": {"runtime": {"lib/net8.0/Avalonia.Base.dll": {}}}}}})
        user = ("config/mxu-MaaRoco.json", "appsettings.json", "libs/unrelated.dll",
                "runtimes/win-x64/native/config/settings.json", "runtimes/win-x64/native/debug/test.log",
                "agent/custom-resource/pipeline/user.json", "resource/custom/pipeline/user.json",
                "maafw/MaaFramework.dll", "MaaRoco.exe")
        for relative in user:
            self.write(self.output / relative, b"preserve these exact bytes")
        (self.output / "libs/empty-resource").mkdir()
        install.remove_legacy_files()
        for relative in known + ("MFAAvalonia.deps.json",):
            self.assertFalse((self.output / relative).exists(), relative)
        for relative in user:
            self.assertEqual((self.output / relative).read_bytes(), b"preserve these exact bytes", relative)
        self.assertTrue((self.output / "libs/empty-resource").is_dir())
        install.remove_legacy_files()
        self.assertTrue((self.output / "agent/custom-resource/pipeline/user.json").is_file())

    def test_cleanup_preflights_all_paths_before_deleting_anything(self):
        self.write(self.output / "python/user.txt", b"must remain if cleanup fails")
        self.write(self.output / "MFAAvalonia.dll", b"must remain if cleanup fails")
        checked = install.checked_install_path
        def reject(relative):
            if str(relative).replace("\\", "/") == "runtimes/win-x64/native/MaaFramework.dll":
                raise RuntimeError("Refusing to modify path outside installation")
            return checked(relative)
        with patch.object(install, "checked_install_path", side_effect=reject), self.assertRaisesRegex(RuntimeError, "outside installation"):
            install.remove_legacy_files()
        self.assertTrue((self.output / "python/user.txt").is_file())
        self.assertTrue((self.output / "MFAAvalonia.dll").is_file())

    def test_install_path_guard_rejects_escape_and_external_symlinks(self):
        with self.assertRaisesRegex(RuntimeError, "outside installation"):
            install.checked_install_path("../outside.txt")
        external = self.root / "external-runtime"
        self.write(external / "MaaFramework.dll", b"external bytes")
        link = self.output / "runtimes/win-x64/native"
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError as error:
            if sys.platform != "win32":
                self.skipTest(f"Creating symlinks is unavailable: {error}")
            import _winapi
            _winapi.CreateJunction(str(external), str(link))
        with self.assertRaisesRegex(RuntimeError, "outside installation"):
            install.remove_legacy_files()
        self.assertEqual((external / "MaaFramework.dll").read_bytes(), b"external bytes")

    def test_installer_migrates_existing_mfa_before_it_changes_originals(self):
        self.assets()
        old = {"InstanceName": "原队列", "TaskItems": [{"name": "Throw", "default_check": False}], "CustomSetting": 42}
        self.write(self.output / "config/instances/default.json", old)
        source = self.output / "config/instances/default.json"
        before = source.read_bytes()
        result = install.install_mxu_config()
        config = json.loads((self.output / "config/mxu-MaaRoco.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "migrated")
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual((Path(result["backup_path"]) / "config/instances/default.json").read_bytes(), before)
        self.assertEqual(config["instances"][1]["name"], "原队列")
        self.assertFalse(config["instances"][1]["tasks"][0]["enabled"])

    def test_fresh_distribution_leaves_config_for_first_launch(self):
        self.assets()
        install.install_mxu_config()
        self.assertFalse((self.output / "config/mxu-MaaRoco.json").exists(),
                         "A packaged default config would bypass users' first-launch MFA migration")

    def test_main_pipeline_migrates_mfa_and_installs_one_native_runtime(self):
        self.assets()
        self.runtime()
        for relative in ("README.md", "LICENSE", "agent/cpp/third_party/meojson/LICENSE", "tools/install_interception.cmd"):
            self.write(self.root / relative, "fixture")
        source_script = Path(install.__file__).resolve()
        script = self.root / "tools/install.py"
        shutil.copy2(source_script, script)
        old = {"InstanceName": "实际安装队列", "TaskItems": [{"name": "Throw", "default_check": True}]}
        self.write(self.output / "config/instances/default.json", old)
        original = (self.output / "config/instances/default.json").read_bytes()
        for relative in ("MFAAvalonia.dll", "MFAAvalonia.runtimeconfig.json", "libs/MFAAvalonia.Core.dll",
                         "runtimes/win-x64/native/MaaFramework.dll"):
            self.write(self.output / relative, b"old runtime")
        arguments = [str(script), "v0.3.0", "win", "x86_64", "--skip-frontend", "--skip-agent", "--install-dir", str(self.output)]
        with patch.object(sys, "argv", arguments), patch.object(configure, "configure_ocr_model"):
            runpy.run_path(str(script), run_name="__main__")
        config = json.loads((self.output / "config/mxu-MaaRoco.json").read_text(encoding="utf-8"))
        self.assertEqual(config["instances"][1]["name"], "实际安装队列")
        self.assertEqual((self.output / "config/instances/default.json").read_bytes(), original)
        self.assertTrue((self.output / "maafw/MaaFramework.dll").is_file())
        self.assertFalse((self.output / "runtimes").exists())
        self.assertFalse((self.output / "MFAAvalonia.dll").exists())
        self.assertFalse((self.output / "libs").exists())
        self.assertEqual(json.loads((self.output / "interface.json").read_text(encoding="utf-8"))["agent"]["child_exec"], "./maafw/MaaRocoAgent.exe")

    def test_failed_agent_install_keeps_the_previous_runtime_and_original_config(self):
        self.assets()
        self.runtime()
        for relative in ("README.md", "LICENSE", "agent/cpp/third_party/meojson/LICENSE", "tools/install_interception.cmd"):
            self.write(self.root / relative, "fixture")
        script = self.root / "tools/install.py"
        shutil.copy2(Path(install.__file__).resolve(), script)
        self.write(self.output / "config/instances/default.json", {"TaskItems": []})
        self.write(self.output / "appsettings.json", {"LinkStart": "F11"})
        self.write(self.output / "runtimes/win-x64/native/MaaRocoAgent.exe", b"previous agent")
        self.write(self.output / "MFAAvalonia.dll", b"previous frontend")
        before = {relative: (self.output / relative).read_bytes()
                  for relative in ("config/instances/default.json", "appsettings.json")}
        arguments = [str(script), "v0.3.0", "win", "x86_64", "--skip-frontend", "--install-dir", str(self.output)]
        with patch.object(sys, "argv", arguments), patch.object(sys, "platform", "win32"), \
                patch.object(configure, "configure_ocr_model"), patch.object(install.shutil, "which", return_value="pwsh"), \
                patch.object(install.subprocess, "run", side_effect=RuntimeError("simulated Agent build failure")), \
                self.assertRaisesRegex(RuntimeError, "Agent build failure"):
            runpy.run_path(str(script), run_name="__main__")
        self.assertEqual((self.output / "runtimes/win-x64/native/MaaRocoAgent.exe").read_bytes(), b"previous agent")
        self.assertEqual((self.output / "MFAAvalonia.dll").read_bytes(), b"previous frontend")
        self.assertEqual({relative: (self.output / relative).read_bytes() for relative in before}, before)


class MxuPackageValidationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        def write(relative, value):
            MxuInstallTest.write(self.root / relative, value)
        self.write = write
        self.write("interface.json", {"name": "MaaRoco", "task": [], "agent": {"child_exec": "./maafw/MaaRocoAgent.exe", "child_args": []}})
        self.write("frontend.lock.json", {"flavor": "mxu", "commit": "a" * 40, "target": "win-x64"})
        self.write("MaaRoco.exe", b"frontend")
        self.write("frontend-source/mxu.patch", b"source patch")
        self.write("maaroco-frontend.json", {"flavor": "mxu", "commit": "a" * 40, "target": "win-x64",
                                            "exe_sha256": hashlib.sha256(b"frontend").hexdigest(),
                                            "patch_sha256": hashlib.sha256(b"source patch").hexdigest()})
        self.write("maafw/MaaFramework.dll", b"framework")
        self.write("maafw/MaaRocoAgent.exe", b"agent")
        self.write("maafw/MaaRocoRunner.exe", b"runner")
        self.write("maaframework.lock.json", {"files": {"MaaFramework.dll": hashlib.sha256(b"framework").hexdigest()}})
        self.write("install_interception.cmd", "fixture")

    def test_valid_mxu_layout_passes_package_validation(self):
        self.assertEqual(validate_native_package.validate_package(self.root), [])

    def test_mxu_executable_hash_tamper_fails_validation(self):
        self.write("MaaRoco.exe", b"tampered")
        self.assertIn("MXU frontend differs from build metadata", validate_native_package.validate_package(self.root))

    def test_mxu_packaged_patch_tamper_fails_validation(self):
        self.write("frontend-source/mxu.patch", b"tampered patch")
        self.assertIn("MXU source patch differs from build metadata", validate_native_package.validate_package(self.root))

    def test_old_native_user_data_alone_does_not_fail_validation(self):
        self.write("runtimes/win-x64/native/config/settings.json", {})
        self.write("runtimes/win-x64/native/debug/user.log", "preserved debug data")
        self.assertEqual(validate_native_package.validate_package(self.root), [])

    def test_old_mfa_runtime_cannot_be_packaged_alongside_mxu(self):
        self.write("MFAAvalonia.runtimeconfig.json", {})
        self.write("runtimes/win-x64/native/MaaFramework.dll", b"duplicate")
        errors = validate_native_package.validate_package(self.root)
        self.assertTrue(any("MFAAvalonia.runtimeconfig.json" in error for error in errors))
        self.assertTrue(any("runtimes/win-x64/native" in error.replace("\\", "/") for error in errors))


if __name__ == "__main__":
    unittest.main()
