"""Validate the macOS bundle without executing it; works on Windows too."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
from validate_native_package import validate_resources


def validate(root, arch, resources_only=False):
    app = root / "MaaRoco.app"
    runtime = app / "Contents/MacOS"
    errors = validate_resources(runtime)
    interface = json.loads((runtime / "interface.json").read_text(encoding="utf-8"))
    native = runtime / f"runtimes/osx-{arch}/native"
    expected = f"./runtimes/osx-{arch}/native/MaaRocoAgent"
    if interface.get("agent") != {"child_exec": expected, "child_args": []}:
        errors.append("Incorrect macOS Agent entry point")
    if [c["type"] for c in interface["controller"]] != ["MacOS"]:
        errors.append("Unexpected controller type")
    if "tasks/LaunchGame.json" in interface.get("import", []):
        errors.append("Windows launcher exposed on macOS")
    for task_file in (runtime / "tasks").glob("*.json"):
        for task in json.loads(task_file.read_text(encoding="utf-8")).get("task", []):
            if task.get("controller") != ["MacOS-GlobalEvent"]:
                errors.append(f"Invalid task controller: {task_file.name}")
    for relative in ("python", "agent", "runtimes/win-x64"):
        if (runtime / relative).exists():
            errors.append(f"Windows/legacy runtime present: {relative}")
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if not (runtime / plist["CFBundleExecutable"]).is_file():
        errors.append("Missing app executable")
    binaries = [native / "libMaaFramework.dylib", native / "libMaaAgentServer.dylib",
                native / "libMaaMacOSControlUnit.dylib"]
    if not resources_only:
        binaries.append(native / "MaaRocoAgent")
    expected_cpu = 0x0100000C if arch == "arm64" else 0x01000007
    for binary in binaries:
        if not binary.is_file():
            errors.append(f"Missing Mach-O binary: {binary.name}")
            continue
        with binary.open("rb") as f:
            header = f.read(8)
        if len(header) < 8 or struct.unpack("<II", header) != (0xFEEDFACF, expected_cpu):
            errors.append(f"Wrong Mach-O architecture: {binary.name}")
    manifest = json.loads((runtime / "macos-runtime-manifest.json").read_text())
    for relative, digest in manifest["files"].items():
        path = runtime / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(f"Framework integrity mismatch: {relative}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--arch", choices=["arm64", "x64"], required=True)
    parser.add_argument("--resources-only", action="store_true")
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.arch, args.resources_only)
    if errors:
        raise SystemExit("\n".join(errors))
    print("macOS package resources, controller, architecture and framework hashes verified")
