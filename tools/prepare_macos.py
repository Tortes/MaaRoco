"""Prepare a macOS app on any host; native Agent compilation requires macOS."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil

ROOT = Path(__file__).resolve().parent.parent
KEYS = {18: 58, 32: 49, 49: 18, 50: 19, 51: 20, 52: 21, 69: 14, 70: 3, 87: 13, 88: 7}
KEY_ACTIONS = {"ClickKey", "LongPressKey", "KeyDown", "KeyUp"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def map_key(key):
    if isinstance(key, list):
        return [map_key(item) for item in key]
    if key not in KEYS:
        raise ValueError(f"Unmapped Windows virtual key: {key}")
    return KEYS[key]


def convert_actions(value):
    """Convert only built-in key actions, including task option overrides.

    Custom action parameters retain VK codes; input_macos.mm translates those.
    """
    if isinstance(value, list):
        for item in value:
            convert_actions(item)
    elif isinstance(value, dict):
        action = value.get("action")
        if isinstance(action, str) and action in KEY_ACTIONS and "key" in value:
            value["key"] = map_key(value["key"])
        elif isinstance(action, dict) and action.get("type") in KEY_ACTIONS:
            param = action.get("param", {})
            if "key" in param:
                param["key"] = map_key(param["key"])
        for item in value.values():
            convert_actions(item)


def prepare(output, sdk, gui, arch, version):
    if output.exists():
        raise ValueError(f"Use a new output directory to avoid mixing packages: {output}")
    if not (gui / "MFAAvalonia").is_file() or not (sdk / "bin/libMaaAgentServer.dylib").is_file():
        raise ValueError("Expected extracted macOS MFAAvalonia and MaaFramework SDK")
    app = output / "MaaRoco.app"
    runtime = app / "Contents/MacOS"
    shutil.copytree(gui, runtime, ignore=shutil.ignore_patterns("runtimes", "plugins", "config", "debug", "logs"))
    native = runtime / f"runtimes/osx-{arch}/native"
    shutil.copytree(sdk / "bin", native, ignore=shutil.ignore_patterns("*.node", "*MaaPiCli*", "plugins"))
    (native / "plugins").mkdir()
    if (sdk / "bin/plugins").exists():
        shutil.copytree(sdk / "bin/plugins", runtime / f"plugins/osx-{arch}")
    shutil.copytree(ROOT / "assets/resource", runtime / "resource")
    ocr = runtime / "resource/model/ocr"
    if not ocr.exists():
        shutil.copytree(ROOT / "assets/MaaCommonAssets/OCR/ppocr_v5/zh_cn", ocr)
    model = runtime / "resource/model/detect/yueya_xuexiong.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "training/yueya_xuexiong/models/yueya_xuexiong.onnx", model)
    shutil.copytree(ROOT / "assets/tasks", runtime / "tasks")
    shutil.copytree(ROOT / "assets/locales", runtime / "locales")
    # The Windows launcher cannot operate a macOS game; do not expose a broken task.
    for path in (runtime / "tasks/LaunchGame.json", runtime / "resource/pipeline/LaunchGame.json",
                 runtime / "resource/pipeline/my_task.json"):
        path.unlink(missing_ok=True)
    for directory in (runtime / "tasks", runtime / "resource/pipeline"):
        for path in directory.glob("*.json"):
            data = read_json(path)
            convert_actions(data)
            for task in data.get("task", []):
                task["controller"] = ["MacOS-GlobalEvent"]
                task["default_check"] = False
            write_json(path, data)
    interface = read_json(ROOT / "assets/interface.json")
    interface["version"] = version
    interface["title"] = "MaaRoco macOS Preview"
    interface["controller"] = [{
        "name": "MacOS-GlobalEvent", "label": "macOS 游戏窗口（实验性）",
        "description": "手动启动游戏后选择窗口；需要屏幕录制与辅助功能权限。预览版使用桌面键鼠操作。",
        "type": "MacOS",
        "macos": {"title_regex": ".*", "screencap": "ScreenCaptureKit", "input": "GlobalEvent"},
    }]
    interface["agent"] = {"child_exec": f"./runtimes/osx-{arch}/native/MaaRocoAgent", "child_args": []}
    interface["import"] = [p for p in interface.get("import", []) if p != "tasks/LaunchGame.json"]
    write_json(runtime / "interface.json", interface)
    write_json(runtime / "config/config.json", {
        "CurrentLanguage": "zh-CN", "EnableAutoUpdateResource": False, "EnableAutoUpdateMFA": False,
        "EnableCheckVersion": False, "HasCompletedFirstUseTutorial": True,
        "UI.HasCompletedFirstUseTutorial": True, "UI.LiveView.EnableLiveView": False,
    })
    write_json(runtime / "config/instances/default.json", {
        "CurrentControllerName": "MacOS-GlobalEvent", "CurrentController": "MacOS",
        "UI.LiveView.EnableLiveView": False,
    })
    write_json(runtime / "appsettings.json", {"LinkStart": "F11"})
    with (app / "Contents/Info.plist").open("wb") as f:
        plistlib.dump({
            "CFBundleName": "MaaRoco", "CFBundleDisplayName": "MaaRoco macOS Preview",
            "CFBundleIdentifier": "io.github.tortes.maaroco", "CFBundleExecutable": "MFAAvalonia",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": version.lstrip("v").split("-")[0],
            "CFBundleVersion": "1", "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True,
            "NSScreenCaptureUsageDescription": "MaaRoco needs screenshots to recognize the selected game window.",
        }, f)
    (runtime / "licenses").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "agent/cpp/third_party/meojson/LICENSE", runtime / "licenses/meojson.txt")
    shutil.copy2(ROOT / "LICENSE", runtime / "licenses/MaaRoco.txt")
    shutil.copy2(ROOT / "macos-dependencies.lock.json", runtime)
    shutil.copy2(ROOT / "docs/macos-preview.md", output / "README-macOS.md")
    write_json(runtime / "macos-runtime-manifest.json", {
        "arch": arch, "framework": "v5.13.0",
        "files": {p.relative_to(runtime).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in native.rglob("*.dylib")},
    })
    (runtime / "MFAAvalonia").chmod(0o755)
    print(f"Prepared macOS resources at {runtime}; compile the native Agent on macOS before distribution.")
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--gui", type=Path, required=True)
    parser.add_argument("--arch", choices=["arm64", "x64"], required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.sdk.resolve(), args.gui.resolve(), args.arch, args.version)


if __name__ == "__main__":
    main()
