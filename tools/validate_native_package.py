"""Validate the actual distribution, including files lazily loaded by MaaFW."""
import argparse
import hashlib
import json
from pathlib import Path


def validate_resources(root: Path) -> list[str]:
    errors = []
    image_root = root / "resource/image"

    def visit(value, source):
        if isinstance(value, list):
            for child in value:
                visit(child, source)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key == "template":
                    templates = [child] if isinstance(child, str) else child
                    if isinstance(templates, list):
                        for name in templates:
                            if not isinstance(name, str):
                                continue
                            path = image_root / name
                            if not path.exists():
                                errors.append(f"{source}: missing template {name}")
                if key == "model" and isinstance(child, str) and child.endswith(".onnx"):
                    if not any((root / f"resource/model/{folder}" / child).is_file()
                               for folder in ("detect", "classify", "ocr")):
                        errors.append(f"{source}: missing model {child}")
                visit(child, source)

    for directory in (root / "resource/pipeline", root / "tasks"):
        for file in directory.rglob("*.json"):
            visit(json.loads(file.read_text(encoding="utf-8")), str(file.relative_to(root)))
    interface = json.loads((root / "interface.json").read_text(encoding="utf-8"))
    icon = interface.get("icon")
    if icon and not (root / icon).is_file():
        errors.append(f"interface.json: missing icon {icon}")
    for imported in interface.get("import", []):
        if not (root / imported).is_file():
            errors.append(f"interface.json: missing import {imported}")
    return errors


def validate_package(root: Path) -> list[str]:
    errors = validate_resources(root)
    for relative in ("python", "agent", "resource/model/detect/pipa_bird.onnx",
                     "resource/pipeline/PipaBirdThrow.json"):
        if (root / relative).exists():
            errors.append(f"Obsolete runtime or feature: {relative}")
    for pattern in ("*.py", "*.pyc", "*.pyd", "*.pdb"):
        for file in root.rglob(pattern):
            errors.append(f"Unexpected runtime/build file: {file.relative_to(root)}")
    native = root / "runtimes/win-x64/native"
    for name in ("MaaRocoAgent.exe", "MaaRocoRunner.exe"):
        if not (native / name).is_file():
            errors.append(f"Missing native executable: {name}")
    interface = json.loads((root / "interface.json").read_text(encoding="utf-8"))
    if interface.get("agent") != {"child_exec": "./runtimes/win-x64/native/MaaRocoAgent.exe", "child_args": []}:
        errors.append("Agent entry point does not use the native executable")
    lock = json.loads((root / "maaframework.lock.json").read_text(encoding="utf-8"))
    for name, expected in lock["files"].items():
        file = native / name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            errors.append(f"MaaFramework binary differs from lock: {name}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install_root", type=Path)
    args = parser.parse_args()
    errors = validate_package(args.install_root.resolve())
    if errors:
        raise SystemExit("\n".join(errors))
    print("Native package: entry point, templates, models and framework hashes verified; no Python runtime")


if __name__ == "__main__":
    main()
