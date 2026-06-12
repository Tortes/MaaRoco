from pathlib import Path

import shutil
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
    config = {
        "CurrentLanguage": "zh-CN",
        "ResourceUpdateChannelInitialized": True,
        "EnableAutoUpdateResource": False,
        "AutoUpdateResource": False,
        "EnableAutoUpdateMFA": False,
        "EnableCheckVersion": False,
        "DownloadSourceIndex": 0,
        "ResourceUpdateChannelIndex": 0,
        "EnableEdit": False,
        "HasCompletedFirstUseTutorial": True,
        "UI.HasCompletedFirstUseTutorial": True,
        "LinkStart": "F11",
    }
    with open(config_dir / "config.json", "w", encoding="utf-8") as f:
        jsonc.dump(config, f, ensure_ascii=False, indent=2)


def remove_legacy_files():
    shutil.rmtree(install_path / "agent", ignore_errors=True)
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
        shutil.copy2(source_exe, target_exe)

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
    install_chores()
    install_default_config()
    remove_legacy_files()
    install_launcher()

    print(f"Install to {install_path} successfully.")
