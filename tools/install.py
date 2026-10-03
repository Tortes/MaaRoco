from pathlib import Path

import copy
import filecmp
import hashlib
import re
import shutil
import subprocess
import sys

try:
    import jsonc
except ModuleNotFoundError as e:
    raise ImportError(
        "Missing dependency 'json-with-comments' (imported as 'jsonc').\n"
        f"Install it with:\n  {sys.executable} -m pip install json-with-comments\n"
        "Or add it to your project's requirements."
    ) from e

from configure import configure_ocr_model
from build_frontend import frontend_metadata
from migrate_mxu_config import migrate_config


working_dir = Path(__file__).parent.parent.resolve()
install_path = working_dir / Path("install")
if "--install-dir" in sys.argv:
    install_path = Path(sys.argv[sys.argv.index("--install-dir") + 1]).resolve()
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"
STABLE_RELEASE_VERSION = re.compile(r"^v\d+\.\d+\.\d+$")

# the first parameter is self name
if sys.argv.__len__() < 4:
    print("Usage: python install.py <version> <os> <arch>")
    print("Example: python install.py v1.0.0 win x86_64")
    sys.exit(1)

os_name = sys.argv[2]
arch = sys.argv[3]


def copy_file_if_different(source, destination):
    """Avoid replacing an identical runtime file that a running app locked."""
    destination_path = Path(destination)
    if destination_path.is_file() and filecmp.cmp(
        source, destination_path, shallow=False
    ):
        return str(destination_path)
    return shutil.copy2(source, destination)


def checked_install_path(relative):
    root = install_path.resolve()
    path = root / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise RuntimeError(f"Refusing to modify path outside installation: {path}")
    return path


def backup_installed_interface():
    """Keep original JSONC bytes before replacing the installed interface."""
    path = checked_install_path("interface.json")
    if not path.is_file():
        return []
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    backup = checked_install_path(f"config/backups/interface-before-mxu-{digest}/interface.json")
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if backup.read_bytes() != original:
            raise RuntimeError(f"Existing interface backup differs from its hash: {backup}")
    else:
        with backup.open("xb") as output:
            output.write(original)
    print(f"Existing interface backed up to {backup}")

    resources = []
    visited = {path.resolve()}
    root = install_path.resolve()

    def collect(document):
        if not isinstance(document, dict):
            raise ValueError("Expected an interface object")
        resources.extend(document.get("resource", []))
        for relative in document.get("import", []):
            imported_path = (root / relative).resolve()
            if not imported_path.is_relative_to(root) or imported_path in visited:
                continue
            visited.add(imported_path)
            if imported_path.is_file():
                collect(jsonc.loads(imported_path.read_text(encoding="utf-8-sig")))

    try:
        collect(jsonc.loads(original.decode("utf-8-sig")))
    except (ValueError, TypeError, OSError) as error:
        print(f"Could not read all previous resource definitions; original interface is backed up: {error}")
    return resources


def resource_directories(resource):
    if not isinstance(resource, dict) or not isinstance(resource.get("name"), str) or not resource["name"]:
        return []
    paths = resource.get("path")
    if not isinstance(paths, list) or not paths:
        return []
    directories = []
    for relative in paths:
        if not isinstance(relative, str) or not relative:
            return []
        candidate = Path(relative.replace("\\", "/"))
        path = (candidate if candidate.is_absolute() else install_path / candidate).resolve()
        if not path.is_dir():
            return []
        directories.append(path)
    return directories


def preserve_installed_resources(interface, previous_resources):
    resources = interface.setdefault("resource", [])
    by_name = {resource["name"]: index for index, resource in enumerate(resources)}
    for resource in previous_resources:
        if not resource_directories(resource):
            continue
        name = resource["name"]
        if name not in by_name:
            by_name[name] = len(resources)
            resources.append(copy.deepcopy(resource))
        elif resource["path"] != resources[by_name[name]].get("path"):
            # A user may replace the default resource with their own paths.
            resources[by_name[name]] = copy.deepcopy(resource)


def get_dotnet_platform_tag():
    """自动检测当前平台并返回对应的dotnet平台标签"""
    if os_name == "win" and arch == "x86_64":
        platform_tag = "win-x64"
    elif os_name == "win" and arch == "aarch64":
        platform_tag = "win-arm64"
    elif os_name == "macos" and arch == "x86_64":
        platform_tag = "osx-x64"
    elif os_name == "macos" and arch == "aarch64":
        platform_tag = "osx-arm64"
    elif os_name == "linux" and arch == "x86_64":
        platform_tag = "linux-x64"
    elif os_name == "linux" and arch == "aarch64":
        platform_tag = "linux-arm64"
    else:
        print("Unsupported OS or architecture.")
        print("available parameters:")
        print("version: e.g., v1.0.0")
        print("os: [win, macos, linux, android]")
        print("arch: [aarch64, x86_64]")
        sys.exit(1)

    return platform_tag


def is_release_version(value: str) -> bool:
    """Only stable release tags are allowed to check and install updates."""
    return STABLE_RELEASE_VERSION.fullmatch(value) is not None


def install_frontend():
    if "--skip-frontend" in sys.argv:
        return
    if os_name != "win" or arch != "x86_64":
        raise RuntimeError("The custom task frontend currently targets Windows x64.")
    output = working_dir / "build/frontend/publish/mxu-win-x64"
    lock = jsonc.loads((working_dir / "frontend.lock.json").read_text(encoding="utf-8"))
    expected = frontend_metadata(lock)
    metadata_path = output / "maaroco-frontend.json"
    metadata = jsonc.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
    executable = output / "mxu.exe"

    def verified_output(metadata):
        if (not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items())
                or not executable.is_file()
                or hashlib.sha256(executable.read_bytes()).hexdigest() != metadata.get("exe_sha256")):
            return False
        runtime_files = metadata.get("runtime_files", {})
        if not isinstance(runtime_files, dict) or set(runtime_files) - {"WebView2Loader.dll"}:
            return False
        return all((output / name).is_file()
                   and hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
                   for name, digest in runtime_files.items())

    if not verified_output(metadata):
        subprocess.run([sys.executable, str(working_dir / "tools/build_frontend.py")], check=True)
        metadata = jsonc.loads(metadata_path.read_text(encoding="utf-8"))
        if not verified_output(metadata):
            raise RuntimeError("MXU build output does not match the pinned source and executable hash")
    install_path.mkdir(parents=True, exist_ok=True)
    copy_file_if_different(executable, install_path / "MaaRoco.exe")
    for name in metadata.get("runtime_files", {}):
        copy_file_if_different(output / name, checked_install_path(name))
    shutil.copy2(metadata_path, install_path)
    shutil.copy2(working_dir / "frontend.lock.json", install_path)
    licenses = install_path / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(working_dir / "build/frontend/MXU/LICENSE", licenses / "MXU-AGPL-3.0.txt")
    frontend_source = install_path / "frontend-source"
    frontend_source.mkdir(parents=True, exist_ok=True)
    shutil.copy2(working_dir / lock["patch"], frontend_source / "mxu.patch")
    (frontend_source / "README.txt").write_text(
        f"MaaRoco's MXU frontend is based on {lock['repository']}\n"
        f"Commit: {lock['commit']} ({lock['version']})\n"
        "Apply mxu.patch to that commit. Build instructions and scripts are in:\n"
        "https://github.com/Tortes/MaaRoco/blob/feat/mxu-migration/docs/mxu-migration.md\n"
        "The upstream MXU license is included in licenses/MXU-AGPL-3.0.txt.\n",
        encoding="utf-8",
    )


def install_deps():
    if not (working_dir / "deps" / "bin").exists():
        print('Please download the MaaFramework to "deps" first.')
        print('请先下载 MaaFramework 到 "deps"。')
        sys.exit(1)

    if os_name == "win" and arch == "x86_64":
        lock = jsonc.loads((working_dir / "maaframework.lock.json").read_text(encoding="utf-8"))
        for filename, expected in lock["files"].items():
            path = working_dir / "deps" / "bin" / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Runtime hash mismatch: {path}; download {lock['release']['url']}")

    if os_name == "android":
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path,
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
    elif os_name == "win" and arch == "x86_64":
        # MXU and the native Agent load the same verified MaaFramework DLLs.
        native_dir = install_path / "maafw"
        shutil.copytree(
            working_dir / "deps/bin", native_dir, dirs_exist_ok=True,
            copy_function=copy_file_if_different,
            ignore=shutil.ignore_patterns("*MaaDbgControlUnit*", "*MaaThriftControlUnit*",
                                         "*MaaRpc*", "*MaaHttp*", "*.node", "*MaaPiCli*"),
        )
        (native_dir / "plugins").mkdir(parents=True, exist_ok=True)
    else:
        native_dir = (
            install_path / "runtimes" / get_dotnet_platform_tag() / "native"
        )
        shutil.copytree(
            working_dir / "deps" / "bin",
            native_dir,
            ignore=shutil.ignore_patterns(
                "*MaaDbgControlUnit*",
                "*MaaThriftControlUnit*",
                "*MaaRpc*",
                "*MaaHttp*",
                "plugins",
                "*.node",
                "*MaaPiCli*",
            ),
            dirs_exist_ok=True,
            copy_function=copy_file_if_different,
        )
        # MaaFramework probes this adjacent directory during standalone runner
        # initialization. Keep it present even though MFA loads its plugins from
        # the platform-specific directory below.
        (native_dir / "plugins").mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "libs" / "MaaAgentBinary",
            dirs_exist_ok=True,
            copy_function=copy_file_if_different,
        )
        shutil.copytree(
            working_dir / "deps" / "bin" / "plugins",
            install_path / "plugins" / get_dotnet_platform_tag(),
            dirs_exist_ok=True,
            copy_function=copy_file_if_different,
        )



def install_resource():

    previous_resources = backup_installed_interface()
    configure_ocr_model()

    shutil.copytree(
        working_dir / "assets" / "resource",
        install_path / "resource",
        dirs_exist_ok=True,
    )
    snow_bear_model = (
        working_dir
        / "training"
        / "yueya_xuexiong"
        / "models"
        / "yueya_xuexiong.onnx"
    )
    if not snow_bear_model.exists():
        raise FileNotFoundError(f"Missing deployment model: {snow_bear_model}")
    model_dir = install_path / "resource" / "model" / "detect"
    model_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snow_bear_model, model_dir / snow_bear_model.name)
    for dirname in ("tasks", "locales"):
        source_dir = working_dir / "assets" / dirname
        if source_dir.exists():
            shutil.copytree(
                source_dir,
                install_path / dirname,
                dirs_exist_ok=True,
            )
    with open(working_dir / "assets/interface.json", "r", encoding="utf-8-sig") as f:
        interface = jsonc.load(f)

    preserve_installed_resources(interface, previous_resources)
    interface["version"] = version
    if os_name == "win" and arch == "x86_64":
        interface["agent"] = {"child_exec": "./maafw/MaaRocoAgent.exe", "child_args": []}

    with open(checked_install_path("interface.json"), "w", encoding="utf-8") as f:
        jsonc.dump(interface, f, ensure_ascii=False, indent=4)


def install_agent():
    """Build the native user runtime; Python is only a developer build tool."""
    if "--skip-agent" in sys.argv:
        return
    if os_name != "win" or arch != "x86_64" or sys.platform != "win32":
        raise RuntimeError("Build the Windows x64 Agent on Windows, or use --skip-agent for the CI base artifact.")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("PowerShell is required to build the native Agent.")
    subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(working_dir / "tools" / "build_native_agent.ps1"),
         "-InstallRoot", str(install_path)], check=True,
    )


def install_chores():
    if os_name == "win":
        shutil.copy2(
            working_dir / "tools" / "install_interception.cmd",
            install_path / "install_interception.cmd",
        )
    licenses = install_path / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(working_dir / "agent/cpp/third_party/meojson/LICENSE", licenses / "meojson.txt")
    shutil.copy2(working_dir / "maaframework.lock.json", install_path)
    shutil.copy2(
        working_dir / "README.md",
        install_path,
    )
    shutil.copy2(
        working_dir / "LICENSE",
        install_path,
    )


def task_key(task):
    return f"{task['name']}<|||>{task['entry']}"


def initial_task_items():
    interface = jsonc.loads((working_dir / "assets/interface.json").read_text(encoding="utf-8"))
    tasks = list(interface.get("task", []))
    for relative in interface.get("import", []):
        imported = jsonc.loads((working_dir / "assets" / relative).read_text(encoding="utf-8"))
        tasks.extend(imported.get("task", []))
    tasks = copy.deepcopy(tasks)
    for task in tasks:
        task["option"] = [{"name": name} for name in task.get("option", [])]
    return tasks


def update_launch_options(tasks):
    for task in tasks:
        if task.get("name") != "LaunchGame":
            continue
        task["controller"] = ["Win32-Interception"]
        options = task.setdefault("option", [])
        if not any(option.get("name") == "WeGameLoginSource" for option in options):
            options.append({"name": "WeGameLoginSource", "index": 0})


def migrate_interception_config(instance):
    """Keep all tabs on the sole Windows controller without changing task options."""
    instance.update(
        {
            "CurrentControllerName": "Win32-Interception",
            "CurrentController": "Win32",
            "Win32ControlMouseType": 512,
            "Win32ControlKeyboardType": 512,
            "Win32ControlScreenCapType": "ScreenDC",
        }
    )
    if (instance.get("DesktopWindowClassName") == "Progman"
            or instance.get("DesktopWindowName") in ("Program Manager", "程序管理器")):
        # The launcher desktop is now selected temporarily by the frontend.
        instance["DesktopWindowClassName"] = "UnrealWindow"
        instance["DesktopWindowName"] = "洛克王国：世界"
    else:
        instance.setdefault("DesktopWindowClassName", "UnrealWindow")
        instance.setdefault("DesktopWindowName", "洛克王国：世界")
    for task in instance.get("TaskItems", []):
        if task.get("name") == "LaunchGame":
            task["controller"] = ["Win32-Interception"]


def migrate_instance_controllers(instance_dir):
    for path in instance_dir.glob("*.json"):
        instance = jsonc.loads(path.read_text(encoding="utf-8"))
        previous = copy.deepcopy(instance)
        migrate_interception_config(instance)
        if instance != previous:
            path.write_text(jsonc.dumps(instance, ensure_ascii=False, indent=2), encoding="utf-8")


def retire_legacy_launcher(launcher_path):
    """Keep an exact recovery copy outside instances, where it cannot become a tab."""
    backup_dir = install_path / "config" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "launch-game.json"
    suffix = 1
    while backup_path.exists() and not filecmp.cmp(launcher_path, backup_path, shallow=False):
        backup_path = backup_dir / f"launch-game-{suffix}.json"
        suffix += 1
    if not backup_path.exists():
        shutil.copy2(launcher_path, backup_path)
    launcher_path.unlink()


def has_enabled_legacy_launcher_schedule():
    config_path = install_path / "appsettings.json"
    if not config_path.exists():
        return False
    config = jsonc.loads(config_path.read_text(encoding="utf-8"))
    return any(
        key.startswith("Timer.") and key.endswith(".Config")
        and identifier == "launch-game"
        and str(config.get(key.removesuffix(".Config"), False)).lower() == "true"
        for key, identifier in config.items()
    )


def install_default_config():
    config_dir = install_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    enable_release_updates = is_release_version(version)
    config = {
        "CurrentLanguage": "zh-CN",
        "ResourceUpdateChannelInitialized": True,
        "EnableAutoUpdateResource": enable_release_updates,
        "EnableAutoUpdateMFA": False,
        "EnableCheckVersion": enable_release_updates,
        "DownloadSourceIndex": 0,
        "UIUpdateChannelIndex": 2 if enable_release_updates else 0,
        "ResourceUpdateChannelIndex": 2 if enable_release_updates else 0,
        "EnableEdit": False,
        "HasCompletedFirstUseTutorial": True,
        "UI.HasCompletedFirstUseTutorial": True,
        "UI.LiveView.EnableLiveView": False,
    }
    with open(config_dir / "config.json", "w", encoding="utf-8") as f:
        jsonc.dump(config, f, ensure_ascii=False, indent=2)

    instance_dir = config_dir / "instances"
    instance_dir.mkdir(parents=True, exist_ok=True)
    instance_path = instance_dir / "default.json"
    instance = {}
    if instance_path.exists():
        with open(instance_path, "r", encoding="utf-8") as f:
            instance = jsonc.load(f)

    migrate_interception_config(instance)
    instance["UI.LiveView.EnableLiveView"] = False
    # Keep the saved queue, options, and check states independent of quick mode.
    initial_tasks = initial_task_items()
    launch_task = next(task for task in initial_tasks if task["name"] == "LaunchGame")
    launch_key = task_key(launch_task)
    if "TaskItems" not in instance:
        instance["TaskItems"] = copy.deepcopy(initial_tasks)
    elif (not any(task.get("name") == "LaunchGame" for task in instance["TaskItems"])
          and launch_key not in instance.get("CurrentTasks", [])):
        instance["TaskItems"].insert(0, copy.deepcopy(launch_task))
    current_tasks = instance.setdefault("CurrentTasks", [])
    for task in instance["TaskItems"]:
        key = task_key(task)
        if key not in current_tasks:
            current_tasks.append(key)

    update_launch_options(instance["TaskItems"])
    instance["MaaRoco.TaskMode"] = "queue"
    if instance.get("InstanceName", "") in ("", "default", "Default", "配置 1", "配置1", "Config 1"):
        instance["InstanceName"] = "任务队列"

    # Quick mode owns a complete task snapshot for independent option editing.
    # The frontend runs only the clicked task; it never executes this as a queue.
    quick_path = instance_dir / "quick-tasks.json"
    launcher_path = instance_dir / "launch-game.json"
    legacy_launcher = {}
    if launcher_path.exists():
        legacy_launcher = jsonc.loads(launcher_path.read_text(encoding="utf-8"))
    if quick_path.exists():
        quick = jsonc.loads(quick_path.read_text(encoding="utf-8"))
        quick["MaaRoco.TaskMode"] = "quick"
        quick.setdefault("InstanceName", "单任务")
        known_tasks = {task_key(task) for task in quick.get("TaskItems", [])}
        for task in initial_tasks:
            if task_key(task) not in known_tasks:
                quick.setdefault("TaskItems", []).append(copy.deepcopy(task))
        update_launch_options(quick["TaskItems"])
    elif not instance.get("MaaRoco.TaskModesInitialized", False):
        saved_tasks = {task_key(task): task for task in instance["TaskItems"]}
        # The old launch tab may contain a newer WeGame path or login source.
        for task in legacy_launcher.get("TaskItems", []):
            if task.get("name") == "LaunchGame":
                saved_tasks[task_key(task)] = task
        quick_tasks = []
        for task in initial_tasks:
            saved = saved_tasks.get(task_key(task))
            item = copy.deepcopy(task)
            if saved is not None:
                item["option"] = copy.deepcopy(saved.get("option", item.get("option", [])))
            quick_tasks.append(item)
        update_launch_options(quick_tasks)
        quick = {
            "InstanceName": "单任务",
            "MaaRoco.TaskMode": "quick",
            "CurrentControllerName": "Win32-Interception",
            "CurrentController": "Win32",
            "Win32ControlMouseType": 512,
            "Win32ControlKeyboardType": 512,
            "Win32ControlScreenCapType": "ScreenDC",
            "DesktopWindowClassName": "UnrealWindow",
            "DesktopWindowName": "洛克王国：世界",
            "Resource": instance.get("Resource", "default"),
            "ResourceOptionItems": copy.deepcopy(instance.get("ResourceOptionItems", {})),
            "UI.LiveView.EnableLiveView": False,
            "TaskItems": quick_tasks,
        }
    else:
        quick = None  # Honor a quick tab that the user explicitly removed.
    if quick is not None:
        quick["CurrentTasks"] = list(dict.fromkeys(
            quick.get("CurrentTasks", []) + [task_key(task) for task in quick["TaskItems"]]
        ))
        with open(quick_path, "w", encoding="utf-8") as f:
            jsonc.dump(quick, f, ensure_ascii=False, indent=2)
    if launcher_path.exists() and not has_enabled_legacy_launcher_schedule():
        retire_legacy_launcher(launcher_path)
    instance["MaaRoco.LauncherTabInitialized"] = True
    instance["MaaRoco.TaskModesInitialized"] = True
    with open(instance_path, "w", encoding="utf-8") as f:
        jsonc.dump(instance, f, ensure_ascii=False, indent=2)
    # Includes quick mode, custom tabs, and legacy tabs retained for enabled timers.
    migrate_instance_controllers(instance_dir)


def install_global_config():
    config_path = install_path / "appsettings.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = jsonc.load(f)

    config["LinkStart"] = "F11"
    instance_dir = install_path / "config" / "instances"
    available = {path.stem: path for path in instance_dir.glob("*.json")}
    # Keep user-created tabs in their prior relative order after the two modes.
    ordered = [identifier for identifier in ("quick-tasks", "default") if identifier in available]
    previous = ",".join(str(config.get(key, "")) for key in ("Instances.Order", "Instances.List"))
    for identifier in previous.split(",") + sorted(available):
        if identifier in available and identifier not in ordered:
            ordered.append(identifier)
    config["Instances.List"] = ",".join(ordered)
    config["Instances.Order"] = ",".join(ordered)
    active = config.get("Instances.LastActive")
    if active == "launch-game" and active not in available and "quick-tasks" in available:
        active = "quick-tasks"
    if active not in available and ordered:
        active = ordered[0]
    if active in available:
        active_config = jsonc.loads(available[active].read_text(encoding="utf-8"))
        config["Instances.LastActive"] = active
        config["Instances.LastActiveName"] = active_config.get("InstanceName", active)
    if "launch-game" not in available:
        config.pop("Instance.launch-game.Name", None)

    with open(config_path, "w", encoding="utf-8") as f:
        jsonc.dump(config, f, ensure_ascii=False, indent=2)


def install_mxu_config():
    """Read and back up MFA settings before creating MXU's separate configuration."""
    legacy_sources = (install_path / "config/config.json", install_path / "appsettings.json")
    if not any(path.is_file() for path in legacy_sources) and not any(
            (install_path / "config/instances").glob("*.json")):
        # Release archives must not ship generated settings: initialize in MXU on first launch.
        return {"status": "deferred", "warnings": []}
    interface_root = install_path if (install_path / "interface.json").is_file() else working_dir / "assets"
    return migrate_config(install_path, interface_root, version)


def remove_legacy_files():
    root = install_path.resolve()
    obsolete = [
        "python", "agent", "resource/pipeline/PipaBirdThrow.json",
        "resource/model/detect/pipa_bird.onnx", "tasks/PipaBirdThrow.json",
        "resource/tools/continuous_throw_log.ps1",
    ]
    mfa_runtime = set()
    protected_resources = []
    if os_name == "win" and arch == "x86_64":
        mfa_runtime.update((
            "MFAAvalonia.exe", "MFAAvalonia.dll", "MFAAvalonia.deps.json",
            "MFAAvalonia.runtimeconfig.json", "libs/MFAAvalonia.Core.dll", "libloader.dll",
            "DependencySetup_依赖库安装_win.bat",
        ))
        # Native directories can also contain users' debug/config data. Delete
        # known binaries individually, then remove directories only when empty.
        framework_files = (
            "DirectML.dll", "fastdeploy_ppocr_maa.dll", "MaaAdbControlUnit.dll",
            "MaaAgentClient.dll", "MaaAgentServer.dll", "MaaCustomControlUnit.dll",
            "MaaFramework.dll", "MaaGamepadControlUnit.dll", "MaaRecordControlUnit.dll",
            "MaaReplayControlUnit.dll", "MaaToolkit.dll", "MaaUtils.dll",
            "MaaWin32ControlUnit.dll", "onnxruntime_maa.dll", "opencv_world4_maa.dll",
            "ViGEmClient.dll", "MaaRocoAgent.exe", "MaaRocoRunner.exe",
        )
        mfa_runtime.update(f"runtimes/win-x64/native/{name}" for name in framework_files)
        mfa_runtime.update(("runtimes/win-x64/native/plugins/MaaPluginDemo.dll",
                            "plugins/win-x64/MaaPluginDemo.dll"))
        manifest = checked_install_path("MFAAvalonia.deps.json")
        if manifest.is_file():
            try:
                dependencies = jsonc.loads(manifest.read_text(encoding="utf-8-sig"))
                for target in dependencies.get("targets", {}).values():
                    for dependency in target.values():
                        for category in ("runtime", "native", "runtimeTargets"):
                            for asset in dependency.get(category, {}):
                                filename = Path(asset.replace("\\", "/")).name
                                if filename.lower().endswith(".dll"):
                                    mfa_runtime.add(f"libs/{filename}")
            except (ValueError, TypeError, AttributeError) as error:
                print(f"Could not read MFA runtime inventory; unknown files are retained: {error}")
        interface_path = checked_install_path("interface.json")
        if interface_path.is_file():
            interface = jsonc.loads(interface_path.read_text(encoding="utf-8-sig"))
            shipped_interface_path = working_dir / "assets/interface.json"
            shipped_resources = {}
            if shipped_interface_path.is_file():
                shipped_interface = jsonc.loads(shipped_interface_path.read_text(encoding="utf-8-sig"))
                shipped_resources = {resource["name"]: resource.get("path")
                                     for resource in shipped_interface.get("resource", [])}
            for resource in interface.get("resource", []):
                if resource.get("path") != shipped_resources.get(resource.get("name")):
                    protected_resources.extend(resource_directories(resource))

    # Resolve every target before deleting anything, including links/junctions.
    paths = [checked_install_path(relative) for relative in obsolete + sorted(mfa_runtime)]
    for path in paths:
        if any(path.resolve().is_relative_to(resource)
               or (path.is_dir() and resource.is_relative_to(path.resolve()))
               for resource in protected_resources):
            print(f"Retaining legacy runtime file inside a configured resource: {path}")
            continue
        if path.is_symlink():
            path.unlink()
        elif path.is_dir() and path.relative_to(root).as_posix() in obsolete:
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()

    empty_directories = {path.parent for path in paths
                         if path.parent != root and path.relative_to(root).as_posix() in mfa_runtime}
    for path in tuple(empty_directories):
        while path != root:
            empty_directories.add(path)
            path = path.parent
    for path in sorted(empty_directories, key=lambda entry: len(entry.parts), reverse=True):
        checked_install_path(path.relative_to(root))
        if (path.is_dir() and not any(path.iterdir())
                and not any(path.resolve().is_relative_to(resource) for resource in protected_resources)):
            path.rmdir()


def install_launcher():
    source_exe = install_path / "mxu.exe"
    target_exe = install_path / "MaaRoco.exe"
    if source_exe.exists():
        source_exe.replace(target_exe)

    launcher = install_path / "MaaRoco.cmd"
    launcher.write_text(
        "\n".join(
            [
                "@echo off",
                "cd /d %~dp0",
                "net session >nul 2>&1",
                "if %errorlevel% neq 0 (",
                "    powershell -NoProfile -ExecutionPolicy Bypass -Command \"Start-Process -FilePath '%~dp0MaaRoco.exe' -WorkingDirectory '%~dp0' -Verb RunAs -WindowStyle Hidden\"",
                "    exit /b",
                ")",
                "start \"\" \"%~dp0MaaRoco.exe\"",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manifest = install_path / "MaaRoco.exe.manifest"
    manifest.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<assembly xmlns=\"urn:schemas-microsoft-com:asm.v1\" manifestVersion=\"1.0\">
  <assemblyIdentity version=\"1.0.0.0\" processorArchitecture=\"*\" name=\"MaaRoco\" type=\"win32\"/>
  <trustInfo xmlns=\"urn:schemas-microsoft-com:asm.v3\">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level=\"requireAdministrator\" uiAccess=\"false\"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
</assembly>
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    install_frontend()
    if "--frontend-only" in sys.argv:
        install_launcher()
        print(f"Frontend installed to {install_path} successfully.")
        sys.exit(0)
    install_deps()
    install_resource()
    install_chores()
    if os_name == "win" and arch == "x86_64":
        install_mxu_config()
    else:
        install_default_config()
        install_global_config()
    install_launcher()
    install_agent()
    remove_legacy_files()

    print(f"Install to {install_path} successfully.")
