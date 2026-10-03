"""One-time, non-destructive MFAAvalonia -> MXU configuration migration.

MXU reads ``config/mxu-<interface.name>.json``. An existing MXU file is
authoritative, even when unreadable: installation must never reset user data.
The MFA files stay in place and are also copied byte-for-byte to a content
addressed backup before conversion. Unsupported data is recorded in its report.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    # PI and MFA support JSONC. Keep comment markers inside strings intact.
    source = path.read_text(encoding="utf-8-sig")
    source = re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
        lambda match: match[0] if match[0].startswith('"') else " ",
        source,
    )
    source = re.sub(
        r'"(?:\\.|[^"\\])*"|,(\s*[}\]])',
        lambda match: match[0] if match[0].startswith('"') else match[1],
        source,
    )
    value = json.loads(source)
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return default


def _load_interface(assets: Path) -> dict[str, Any]:
    root = assets.resolve()
    interface = _read_json(root / "interface.json")
    merged = copy.deepcopy(interface)
    visited = {root / "interface.json"}

    def merge_imports(document: dict[str, Any]) -> None:
        for relative in _list(document.get("import")):
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"Interface import escapes assets directory: {relative}")
            if path in visited:
                continue
            visited.add(path)
            imported = _read_json(path)
            for key in ("task", "controller", "resource"):
                merged.setdefault(key, []).extend(imported.get(key, []))
            merged.setdefault("option", {}).update(imported.get("option", {}))
            merge_imports(imported)

    merge_imports(interface)
    return merged


def _default_option(definition: dict[str, Any]) -> dict[str, Any]:
    kind = definition.get("type", "select")
    cases = definition.get("cases", [])
    default_case = definition.get("default_case", cases[0]["name"] if cases else "")
    if kind in ("input", "hotkey"):
        return {"type": kind, "values": {
            item["name"]: str(item.get("default", "")) for item in definition.get("inputs", [])
        }}
    if kind == "checkbox":
        return {"type": kind, "caseNames": _list(definition.get("default_case"))}
    if kind == "switch":
        return {"type": kind, "value": default_case in ("Yes", "yes", "Y", "y")}
    return {"type": "select", "caseName": default_case}


def _option_defaults(names: Any, definitions: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    def visit(name: str) -> None:
        if name in result or name not in definitions:
            return
        definition = definitions[name]
        result[name] = _default_option(definition)
        for case in definition.get("cases", []):
            for child in _list(case.get("option")):
                visit(child)

    for name in _list(names):
        if isinstance(name, str):
            visit(name)
    return result


def _convert_options(saved: Any, definitions: dict[str, Any], report: dict, context: str) -> dict:
    result = {}
    for item in _list(saved):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            report["warnings"].append(f"{context}: invalid option retained in MFA backup")
            continue
        name = item["name"]
        definition = definitions.get(name)
        if not definition:
            report["warnings"].append(f"{context}: unknown option {name!r} retained in MFA backup")
        else:
            value = _default_option(definition)
            kind = value["type"]
            cases = definition.get("cases", [])
            case_names = [case["name"] for case in cases]
            if kind in ("input", "hotkey"):
                data = item.get("data")
                if isinstance(data, dict):
                    known_inputs = value["values"]
                    for key, raw in data.items():
                        if key in known_inputs:
                            known_inputs[key] = "" if raw is None else str(raw)
                        else:
                            report["warnings"].append(
                                f"{context}/{name}: unknown input {key!r} retained in MFA backup")
            elif kind == "checkbox" and item.get("selected_cases") is not None:
                selected = _list(item["selected_cases"])
                value["caseNames"] = list(dict.fromkeys(case for case in selected if case in case_names))
                if any(case not in case_names for case in selected):
                    report["warnings"].append(f"{context}/{name}: unknown checkbox cases retained in MFA backup")
            elif kind in ("select", "switch") and item.get("index") is not None:
                index = item["index"]
                if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(cases):
                    case = cases[index]["name"]
                    if kind == "select":
                        value["caseName"] = case
                    else:
                        value["value"] = case in ("Yes", "yes", "Y", "y")
                else:
                    report["warnings"].append(f"{context}/{name}: invalid index retained in MFA backup; using interface default")
            result[name] = value
        result.update(_convert_options(item.get("sub_options"), definitions, report, context))
    return result


def _convert_tasks(saved: Any, interface: dict, report: dict, identifier: str) -> list[dict]:
    definitions = {item["name"]: item for item in interface.get("task", [])}
    result = []
    for index, item in enumerate(_list(saved)):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            report["warnings"].append(f"{identifier}: invalid task retained in MFA backup")
            continue
        name = item["name"]
        definition = definitions.get(name)
        if definition is None:
            report["warnings"].append(f"{identifier}: unsupported task {name!r} retained in MFA backup")
            continue
        options = _option_defaults(definition.get("option"), interface.get("option", {}))
        options.update(_convert_options(item.get("option"), interface.get("option", {}), report, f"{identifier}/{name}"))
        task = {"id": f"{identifier}-task-{index}", "taskName": name,
                "enabled": _bool(item.get("default_check")), "optionValues": options, "expanded": False}
        if item.get("display_name_override"):
            task["customName"] = item["display_name_override"]
        for field in ("remark", "advanced", "pipeline_override", "repeat_count"):
            if item.get(field):
                report["warnings"].append(f"{identifier}/{name}: {field} retained in MFA backup")
        result.append(task)
    return result


def _convert_instance(identifier: str, saved: dict, interface: dict, report: dict) -> dict:
    mode = "single" if identifier == "quick-tasks" or saved.get("MaaRoco.TaskMode") == "quick" else "queue"
    name = saved.get("InstanceName") or ("单任务" if mode == "single" else "任务队列" if identifier == "default" else identifier)
    if identifier == "default" and name in ("default", "Default", "配置 1", "配置1", "Config 1"):
        name = "任务队列"
    resource = saved.get("Resource") or interface.get("resource", [{}])[0].get("name", "default")
    instance = {"id": f"mfa-{identifier}", "name": name, "maarocoMode": mode,
                "controllerName": "Win32-Interception", "resourceName": resource,
                "tasks": _convert_tasks(saved.get("TaskItems", []), interface, report, identifier)}
    if resource not in {item["name"] for item in interface.get("resource", [])}:
        report["warnings"].append(f"{identifier}: custom resource {resource!r} retained; resource definition must remain available")
    title = saved.get("DesktopWindowName")
    if title and title not in ("Program Manager", "程序管理器") and saved.get("DesktopWindowClassName") != "Progman":
        instance["savedDevice"] = {"windowName": title}
    else:
        instance["savedDevice"] = {"windowName": "洛克王国：世界"}
    if saved.get("ConnectedProgramPath"):
        instance["savedDevice"]["connectedProgramPath"] = saved["ConnectedProgramPath"]
    for key in ("ResourceOptionItems", "ControllerOptionItems", "BeforeTask", "AfterTask", "GlobalOptionItems"):
        if saved.get(key):
            report["warnings"].append(f"{identifier}: {key} retained in MFA backup (MXU has no matching per-instance field)")
    mapped = {"InstanceName", "Resource", "TaskItems", "CurrentTasks", "MaaRoco.TaskMode",
              "DesktopWindowName", "DesktopWindowClassName", "ConnectedProgramPath", "CurrentControllerName",
              "CurrentController", "Win32ControlMouseType", "Win32ControlKeyboardType", "Win32ControlScreenCapType",
              "UI.LiveView.EnableLiveView", "MaaRoco.TaskModesInitialized", "MaaRoco.LauncherTabInitialized"}
    unmapped = sorted(set(saved) - mapped)
    if unmapped:
        report["unmapped_fields"][identifier] = unmapped
    return instance


def _migrate_timers(global_config: dict, instances: list[dict], report: dict) -> None:
    targets = {item["id"].removeprefix("mfa-"): item for item in instances}
    numbers = sorted({int(match[1]) for key in global_config
                      if (match := re.match(r"Timer\.Timer(\d+)(?:[.]|Time$|$)", key))})
    for number in numbers:
        prefix = f"Timer.Timer{number}"
        raw = {key: value for key, value in global_config.items()
               if key == prefix or key == prefix + "Time" or key.startswith(prefix + ".")}
        entry = {"timer": number, "source": raw, "status": "retained"}
        report["timers"].append(entry)
        enabled = _bool(global_config.get(prefix))
        if not enabled and not global_config.get(prefix + "Time"):
            entry["reason"] = "Unused timer"
            continue
        target = targets.get(global_config.get(prefix + ".Config"))
        schedule = str(global_config.get(prefix + ".Schedule") or "0||").split("|")
        action = str(global_config.get(prefix + ".Action", "0"))
        time = re.fullmatch(r"(\d{1,2}):(\d{1,2})(?::00)?", str(global_config.get(prefix + "Time", "")))
        reason = None
        if target is None:
            reason = "Timer target is missing or implicit"
        elif action != "0":
            reason = "MXU schedule policies cannot stop tasks"
        elif any(_bool(global_config.get(prefix + suffix)) for suffix in (".StopConnectedProcess", ".StopMFA")):
            reason = "MXU schedule policies cannot stop a process or MFA"
        elif not time or int(time[1]) > 23 or int(time[2]) > 59:
            reason = "Invalid or missing start time"
        elif schedule[0] not in ("0", "1"):
            reason = "Monthly or unknown timer schedule is unsupported"
        else:
            days = list(range(7))
            if schedule[0] == "1":
                tokens = schedule[1].split(",") if len(schedule) > 1 else []
                if not tokens or any(not token.isdigit() or int(token) > 6 for token in tokens):
                    reason = "Invalid or empty weekly schedule"
                else:
                    days = sorted({int(token) for token in tokens})
            if reason is None:
                target.setdefault("schedulePolicies", []).append({
                    "id": f"mfa-timer-{number}", "name": f"MFA 定时任务 {number}", "enabled": enabled,
                    "weekdays": days, "times": [f"{int(time[1]):02}:{int(time[2]):02}"]})
                entry["status"] = "migrated"
        if reason:
            entry["reason"] = reason
            report["warnings"].append(f"Timer {number}: {reason}; original timer retained in MFA backup")


def migrate_config(install_root: str | Path, assets_root: str | Path, version: str) -> dict[str, Any]:
    """Create MXU config once; return status, paths, and migration warnings.

    Call after installing resource/interface files, before modifying or removing
    any MFA config. ``assets_root`` is the PI root containing interface.json.
    """
    root, assets = Path(install_root), Path(assets_root)
    interface = _load_interface(assets)
    project_name = interface.get("name")
    filename = "mxu-" + re.sub(r"[/\\.:]", "_", project_name) + ".json" if project_name else "mxu.json"
    destination = root / "config" / filename
    if destination.exists():
        return {"status": "existing", "config_path": str(destination), "warnings": []}

    sources = [path for path in (root / "config/config.json", root / "appsettings.json") if path.is_file()]
    sources.extend(sorted((root / "config/instances").glob("*.json")))
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
    backup = root / "config/backups" / ("mfa-to-mxu-" + digest.hexdigest()[:16])
    report: dict[str, Any] = {"status": "migrated" if sources else "initialized", "version": version,
                            "config_path": str(destination), "backup_path": str(backup) if sources else None,
                            "source_files": [], "warnings": [], "timers": [], "unmapped_fields": {}}
    if sources:
        for source in sources:
            relative = source.relative_to(root)
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise RuntimeError(f"Conflicting MFA backup: {target}")
            if not target.exists():
                shutil.copy2(source, target)
            report["source_files"].append({"path": relative.as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})

    def read_optional(path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            return _read_json(path)
        except (ValueError, UnicodeError) as error:
            report["warnings"].append(f"{path.relative_to(root)}: {error}; exact file retained in MFA backup")
            return {}

    settings = read_optional(root / "config/config.json")
    global_config = read_optional(root / "appsettings.json")
    saved = {path.stem: read_optional(path) for path in sources if path.parent.name == "instances"}
    # Earlier MFA builds stored their sole queue directly in config/config.json.
    if "default" not in saved and "TaskItems" in settings:
        saved["default"] = settings
    saved.setdefault("default", {})
    instances = [_convert_instance("default", saved["default"], interface, report)]
    queue_options = {task["taskName"]: task["optionValues"] for task in instances[0]["tasks"]}
    quick = _convert_instance("quick-tasks", saved.get("quick-tasks", {}), interface, report)
    quick_by_name = {task["taskName"]: task for task in quick["tasks"]}
    launcher_tasks = _convert_tasks(saved.get("launch-game", {}).get("TaskItems", []), interface, report, "launch-game")
    launcher_options = {task["taskName"]: task["optionValues"] for task in launcher_tasks}
    quick["tasks"] = []
    for index, task in enumerate(interface.get("task", [])):
        name = task["name"]
        item = quick_by_name.get(name)
        if item is None:
            options = _option_defaults(task.get("option"), interface.get("option", {}))
            options.update(copy.deepcopy(launcher_options.get(name, queue_options.get(name, {}))))
            item = {"id": f"quick-tasks-task-{index}", "taskName": name,
                    "enabled": _bool(task.get("default_check")), "optionValues": options, "expanded": False}
        item["id"] = f"quick-tasks-task-{index}"
        quick["tasks"].append(item)
    if "quick-tasks" not in saved:
        quick["resourceName"] = instances[0]["resourceName"]
        quick["savedDevice"] = copy.deepcopy(instances[0]["savedDevice"])
    instances.insert(0, quick)
    ordered = []
    for key in ("Instances.Order", "Instances.List"):
        ordered.extend(str(global_config.get(key, "")).split(","))
    ordered.extend(sorted(saved))
    for identifier in dict.fromkeys(ordered):
        if identifier in saved and identifier not in ("default", "quick-tasks"):
            instances.append(_convert_instance(identifier, saved[identifier], interface, report))
    _migrate_timers(global_config, instances, report)
    language = settings.get("CurrentLanguage", "zh-CN")
    if language not in ("system", "zh-CN", "zh-TW", "en-US", "ja-JP", "ko-KR"):
        language = "zh-CN"
    stable = re.fullmatch(r"v?\d+\.\d+\.\d+", version) is not None
    config = {"version": "1.0", "instances": instances,
              "settings": {"theme": "system", "language": language, "onboardingCompleted": True,
                           "hotkeys": {"startTasks": "F10", "stopTasks": "F11", "globalEnabled": True},
                           "screenshotPanelExpanded": False, "screenshotFrameRate": "1",
                           "mirrorChyan": {"cdk": "", "channel": "stable" if stable else "beta"}},
              "interfaceTaskSnapshot": [task["name"] for task in interface.get("task", [])],
              "presetInitialized": True}
    active = "mfa-" + str(global_config.get("Instances.LastActive", "quick-tasks"))
    config["lastActiveInstanceId"] = active if any(item["id"] == active for item in instances) else quick["id"]
    global_options = _convert_options(settings.get("GlobalOptionItems"), interface.get("option", {}), report, "global")
    if global_options:
        config["globalOptionValues"] = global_options
    for key in ("DownloadCDK", "GitHubToken"):
        if settings.get(key):
            report["warnings"].append(f"{key}: MFA encrypted credential retained in backup; re-enter it in MXU settings")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Persist the recovery report before publishing config. Exclusive creation
    # also prevents a concurrent launch/install from overwriting user config.
    report_path = backup / "migration-report.json" if sources else destination.parent / "mxu-migration-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(report_path)
    _write_json(report_path, report)
    try:
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        return {"status": "existing", "config_path": str(destination), "warnings": []}
    return report
