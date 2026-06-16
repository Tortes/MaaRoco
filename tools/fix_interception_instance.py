#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def fix_instance(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("CurrentControllerName") != "Win32-Interception":
        return False

    changed = False

    # MFA client binaries in this repo do not recognize the new enum name
    # "Interception" yet, but they can still persist raw numeric values.
    # MaaFramework maps 1 << 9 to Interception.
    if data.get("Win32ControlMouseType") != 512:
        data["Win32ControlMouseType"] = 512
        changed = True

    # MaaFramework maps 1 << 7 to PostMessage.
    if data.get("Win32ControlKeyboardType") != 128:
        data["Win32ControlKeyboardType"] = 128
        changed = True

    if not data.get("Win32ControlScreenCapType"):
        data["Win32ControlScreenCapType"] = "ScreenDC"
        changed = True

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix MaaRoco instance config so Win32-Interception uses MaaFramework Interception mouse + PostMessage keyboard."
    )
    parser.add_argument(
        "instance_files",
        nargs="*",
        default=["config/instances/default.json"],
        help="Instance config files to patch.",
    )
    args = parser.parse_args()

    changed_any = False
    for item in args.instance_files:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            print(f"skip missing: {path}")
            continue
        changed = fix_instance(path)
        print(f"{'updated' if changed else 'nochange'}: {path}")
        changed_any = changed_any or changed

    return 0 if changed_any else 0


if __name__ == "__main__":
    raise SystemExit(main())
