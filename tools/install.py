from pathlib import Path

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


working_dir = Path(__file__).parent.parent.resolve()
install_path = working_dir / Path("install")
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"
STABLE_RELEASE_VERSION = re.compile(r"^v\d+\.\d+\.\d+$")

# the first parameter is self name
if sys.argv.__len__() < 4:
    print("Usage: python install.py <version> <os> <arch>")
    print("Example: python install.py v1.0.0 win x86_64")
    sys.exit(1)

os_name = sys.argv[2]
arch = sys.argv[3]


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


def install_deps():
    if not (working_dir / "deps" / "bin").exists():
        print('Please download the MaaFramework to "deps" first.')
        print('请先下载 MaaFramework 到 "deps"。')
        sys.exit(1)

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
    else:
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path / "runtimes" / get_dotnet_platform_tag() / "native",
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
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "libs" / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "bin" / "plugins",
            install_path / "plugins" / get_dotnet_platform_tag(),
            dirs_exist_ok=True,
        )



def install_resource():

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
    shutil.copy2(
        working_dir / "assets" / "interface.json",
        install_path,
    )

    with open(install_path / "interface.json", "r", encoding="utf-8") as f:
        interface = jsonc.load(f)

    interface["version"] = version

    with open(install_path / "interface.json", "w", encoding="utf-8") as f:
        jsonc.dump(interface, f, ensure_ascii=False, indent=4)


def install_agent():
    source_dir = working_dir / "agent"
    if source_dir.exists():
        shutil.copytree(source_dir, install_path / "agent", dirs_exist_ok=True)


def install_python_runtime():
    """Complete local Windows installs; CI bundles its base artifact separately."""
    if os_name != "win" or arch != "x86_64" or "--skip-python" in sys.argv:
        return
    if sys.platform != "win32":
        raise RuntimeError("Bundle Windows Python on Windows, or use --skip-python for a base artifact.")
    executable = install_path / "python" / "python.exe"
    if not executable.is_file():
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise RuntimeError("PowerShell is required to bundle embedded Python.")
        subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(working_dir / "tools" / "bundle_embedded_python.ps1"),
             "-InstallRoot", str(install_path), "-HostPython", sys.executable],
            check=True,
        )
    subprocess.run(
        [str(executable), "-I", "-c",
         "import cv2, numpy, interception, win32api; "
         "from maa.agent.agent_server import AgentServer; "
         "import runpy; runpy.run_path('agent/main.py', run_name='maaroco_install_check'); "
         "print('Installed Python and Agent import check passed')"],
        cwd=install_path,
        check=True,
    )


def install_chores():
    shutil.copy2(
        working_dir / "README.md",
        install_path,
    )
    shutil.copy2(
        working_dir / "LICENSE",
        install_path,
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

    instance.update(
        {
            "CurrentControllerName": "Win32-Interception",
            "CurrentController": "Win32",
            "Win32ControlMouseType": 512,
            "Win32ControlKeyboardType": 512,
            "Win32ControlScreenCapType": "ScreenDC",
            "UI.LiveView.EnableLiveView": False,
        }
    )
    with open(instance_path, "w", encoding="utf-8") as f:
        jsonc.dump(instance, f, ensure_ascii=False, indent=2)


def install_global_config():
    config_path = install_path / "appsettings.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = jsonc.load(f)

    config["LinkStart"] = "F11"

    with open(config_path, "w", encoding="utf-8") as f:
        jsonc.dump(config, f, ensure_ascii=False, indent=2)


def remove_legacy_files():
    stale_log_script = install_path / "resource" / "tools" / "continuous_throw_log.ps1"
    if stale_log_script.exists():
        stale_log_script.unlink()
    tools_dir = install_path / "resource" / "tools"
    if tools_dir.exists() and not any(tools_dir.iterdir()):
        tools_dir.rmdir()


def install_launcher():
    source_exe = install_path / "MFAAvalonia.exe"
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
                "    powershell -NoProfile -ExecutionPolicy Bypass -Command \"Start-Process -FilePath '%~dp0MaaRoco.exe' -WorkingDirectory '%~dp0' -Verb RunAs\"",
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
    install_deps()
    install_resource()
    install_agent()
    install_chores()
    install_default_config()
    install_global_config()
    remove_legacy_files()
    install_launcher()
    install_python_runtime()

    print(f"Install to {install_path} successfully.")
