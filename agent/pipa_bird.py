import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition


@dataclass(frozen=True)
class AimSettings:
    target_recognition: str = "PipaBirdDetect"
    aim_gain_percent: int = 100
    center_tolerance: int = 24
    max_aim_attempts: int = 4
    max_relative_move: int = 480
    settle_delay_ms: int = 320
    verification_frames: int = 2
    max_target_area_percent: int = 30
    min_hold_ms: int = 80
    throw_cooldown_ms: int = 900
    trajectory_base_lift_px: int = 0
    trajectory_distance_lift_px: int = 0
    trajectory_reference_height: int = 100

    @classmethod
    def from_json(
        cls, raw: str, defaults: "AimSettings | None" = None
    ) -> "AimSettings":
        try:
            value = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            value = {}

        if not isinstance(value, dict):
            value = {}

        defaults = defaults or cls()
        target_recognition = value.get("target_recognition", defaults.target_recognition)
        if not isinstance(target_recognition, str) or not target_recognition:
            target_recognition = defaults.target_recognition
        return cls(
            target_recognition=target_recognition,
            aim_gain_percent=_bounded_int(value.get("aim_gain_percent"), defaults.aim_gain_percent, 10, 300),
            center_tolerance=_bounded_int(value.get("center_tolerance"), defaults.center_tolerance, 1, 200),
            max_aim_attempts=_bounded_int(value.get("max_aim_attempts"), defaults.max_aim_attempts, 1, 20),
            max_relative_move=_bounded_int(value.get("max_relative_move"), defaults.max_relative_move, 1, 2000),
            settle_delay_ms=_bounded_int(value.get("settle_delay_ms"), defaults.settle_delay_ms, 0, 2000),
            verification_frames=_bounded_int(value.get("verification_frames"), defaults.verification_frames, 1, 4),
            max_target_area_percent=_bounded_int(
                value.get("max_target_area_percent"), defaults.max_target_area_percent, 1, 90
            ),
            min_hold_ms=_bounded_int(value.get("min_hold_ms"), defaults.min_hold_ms, 1, 1000),
            throw_cooldown_ms=_bounded_int(value.get("throw_cooldown_ms"), defaults.throw_cooldown_ms, 0, 10000),
            trajectory_base_lift_px=_bounded_int(
                value.get("trajectory_base_lift_px"), defaults.trajectory_base_lift_px, 0, 200
            ),
            trajectory_distance_lift_px=_bounded_int(
                value.get("trajectory_distance_lift_px"), defaults.trajectory_distance_lift_px, 0, 300
            ),
            trajectory_reference_height=_bounded_int(
                value.get("trajectory_reference_height"), defaults.trajectory_reference_height, 20, 1000
            ),
        )


def _bounded_int(value: object, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(upper, int(value)))
    except (TypeError, ValueError):
        return default


def _box_center(box: tuple[int, int, int, int]) -> tuple[int, int]:
    x, y, width, height = box
    return x + width // 2, y + height // 2


def _clamp(value: int, limit: int) -> int:
    return max(-limit, min(limit, value))


def _screen_point(width: int, height: int, x: int, y: int) -> tuple[int, int]:
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))


def _aim_point(
    box: tuple[int, int, int, int], settings: AimSettings
) -> tuple[int, int, int]:
    """Return the screen point that should sit under the crosshair and its upward lead."""
    target_x, target_y = _box_center(box)
    _, _, _, target_height = box
    distance_lift = (
        settings.trajectory_distance_lift_px * settings.trajectory_reference_height
        // max(1, target_height)
    )
    vertical_lift = min(
        200, settings.trajectory_base_lift_px + distance_lift
    )
    return target_x, max(0, target_y - vertical_lift), vertical_lift


def _is_aim_point_centered(
    width: int, height: int, box: tuple[int, int, int, int], settings: AimSettings
) -> bool:
    aim_x, aim_y, _ = _aim_point(box, settings)
    return (
        abs(aim_x - width // 2) <= settings.center_tolerance
        and abs(aim_y - height // 2) <= settings.center_tolerance
    )


def _result_boxes(detail) -> list[tuple[int, int, int, int]]:
    """Return Maa neural-network candidates with their normal result shape."""

    if not detail:
        return []
    results = getattr(detail, "all_results", None) or []
    boxes = []
    for result in results:
        score = float(getattr(result, "score", 0.0))
        if score >= 0.35:
            box = tuple(int(value) for value in result.box)
            if len(box) == 4 and box[2] > 0 and box[3] > 0:
                boxes.append(box)
    if not boxes and getattr(detail, "best_result", None):
        boxes.append(tuple(int(value) for value in detail.best_result.box))
    return boxes


def _select_tracked_box(
    detail, expected_center: tuple[float, float] | None = None
) -> tuple[int, int, int, int] | None:
    """Keep following one detection instead of changing to a screen-edge pet."""

    boxes = _result_boxes(detail)
    if not boxes:
        return None
    if expected_center is None:
        best = getattr(detail, "best_result", None)
        return tuple(int(value) for value in best.box) if best else boxes[0]
    expected_x, expected_y = expected_center
    return min(
        boxes,
        key=lambda box: (_box_center(box)[0] - expected_x) ** 2
        + (_box_center(box)[1] - expected_y) ** 2,
    )


def _is_reasonable_target(
    width: int, height: int, box: tuple[int, int, int, int], max_area_percent: int
) -> bool:
    target_x, target_y, target_width, target_height = box
    if target_width <= 0 or target_height <= 0:
        return False
    # The lower-left HUD contains blue iconography that is never a valid
    # throw target. Ignore it before a mouse button can be held.
    if target_x + target_width <= width * 0.25 and target_y >= height * 0.85:
        return False
    return target_width * target_height * 100 <= width * height * max_area_percent


def _is_same_target(
    previous: tuple[int, int, int, int], current: tuple[int, int, int, int]
) -> bool:
    previous_x, previous_y = _box_center(previous)
    current_x, current_y = _box_center(current)
    previous_width, previous_height = previous[2:]
    current_width, current_height = current[2:]
    if min(previous_width, previous_height, current_width, current_height) <= 0:
        return False

    # A deliberate camera drag can move a real target well beyond its own box.
    # Keep the shape check, but do not mistake that movement for a new target.
    max_center_shift = max(800, max(previous_width, previous_height) * 3)
    if abs(current_x - previous_x) > max_center_shift:
        return False
    if abs(current_y - previous_y) > max_center_shift:
        return False

    width_ratio = current_width / previous_width
    height_ratio = current_height / previous_height
    return 0.4 <= width_ratio <= 2.5 and 0.4 <= height_ratio <= 2.5


def _log(message: str) -> None:
    line = f"[PipaBird] {message}"
    print(line, flush=True)
    try:
        log_dir = Path("debug")
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "pipa_bird.log").open("a", encoding="utf-8") as log_file:
            log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


@AgentServer.custom_recognition("yueya_xuexiong_blue")
class YueyaXuexiongBlueRecognition(CustomRecognition):
    """Find the largest blue component belonging to a Yueya snow bear group."""

    def analyze(
        self, context: Context, argv: CustomRecognition.AnalyzeArg
    ) -> CustomRecognition.AnalyzeResult | None:
        param = _json_object(argv.custom_recognition_param)
        # The in-game lighting makes the fur much less saturated than the source image.
        lower = np.array(param.get("hsv_lower", [100, 70, 140]), dtype=np.uint8)
        upper = np.array(param.get("hsv_upper", [140, 255, 255]), dtype=np.uint8)
        min_area_ratio = _bounded_float(param.get("min_area_ratio"), 0.002, 0.0001, 0.25)
        min_density = _bounded_float(param.get("min_density"), 0.38, 0.05, 1.0)
        min_top_ratio = _bounded_float(param.get("min_top_ratio"), 0.06, 0.0, 0.5)

        if lower.shape != (3,) or upper.shape != (3,):
            return None

        hsv = cv2.cvtColor(argv.image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        count, _, stats, centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if count <= 1:
            return None

        frame_height, frame_width = argv.image.shape[:2]
        min_area = round(frame_width * frame_height * min_area_ratio)
        candidates: list[tuple[int, int, int, int, int, float, int]] = []
        min_top = round(frame_height * min_top_ratio)
        for component_index in range(1, count):
            x, y, width, height, area = (
                int(value) for value in stats[component_index]
            )
            if area < min_area or width <= 0 or height <= 0 or y < min_top:
                continue
            density = area / (width * height)
            if density < min_density:
                continue
            candidates.append((area, x, y, width, height, density, component_index))

        if not candidates:
            return None

        area, x, y, width, height, density, component_index = max(candidates)

        center_x, center_y = centers[component_index]
        # A connected snow-bear group is not rectangular.  Center its aim box on
        # the blue-pixel centroid so the action aims at the visible body mass.
        aim_x = round(float(center_x) - width / 2)
        aim_y = round(float(center_y) - height / 2)
        return CustomRecognition.AnalyzeResult(
            box=(aim_x, aim_y, width, height),
            detail={
                "area": area,
                "area_ratio": round(area / (frame_width * frame_height), 5),
                "density": round(density, 3),
                "min_density": min_density,
                "min_top_ratio": min_top_ratio,
                "center": [round(float(center_x), 1), round(float(center_y), 1)],
                "source_box": [x, y, width, height],
                "hsv_lower": lower.tolist(),
                "hsv_upper": upper.tolist(),
            },
        )


@AgentServer.custom_action("pipa_bird_aim_and_throw")
class PipaBirdAimAndThrow(CustomAction):
    default_settings = AimSettings()

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        controller = context.tasker.controller
        if controller is None:
            return False

        pointer_held = False
        hold_started_at = 0.0
        throw_confirmed = False
        try:
            settings = AimSettings.from_json(
                argv.custom_action_param, self.default_settings
            )
            image = controller.cached_image
            height, width = image.shape[:2]
            if width <= 0 or height <= 0:
                return False

            # Confirm the target is still visible before a left-button release can throw a ball.
            detail = context.run_recognition(settings.target_recognition, image)
            if not detail or not detail.hit or not detail.best_result:
                _log("preflight: target not found; retrying recognition")
                return False
            box = _select_tracked_box(detail)
            if box is None:
                _log("preflight: no usable target box; retrying recognition")
                return False
            if not _is_reasonable_target(
                width, height, box, settings.max_target_area_percent
            ):
                _log(
                    f"preflight: rejected oversized target={box}; "
                    f"limit={settings.max_target_area_percent}%; retrying recognition"
                )
                return False

            # Recheck before holding the button. Releasing after a lost target is
            # still a throw in-game, so never start from an unstable detection.
            image = controller.post_screencap().get(wait=True)
            detail = context.run_recognition(settings.target_recognition, image)
            if not detail or not detail.hit or not detail.best_result:
                _log("preflight: target lost before button down")
                return False
            confirmed_box = _select_tracked_box(detail, _box_center(box))
            if confirmed_box is None:
                _log("preflight: target has no usable box before button down")
                return False
            if not _is_reasonable_target(
                width, height, confirmed_box, settings.max_target_area_percent
            ) or not _is_same_target(box, confirmed_box):
                _log(
                    f"preflight: target unstable initial={box} confirmed={confirmed_box}"
                )
                return False
            box = confirmed_box

            pointer_x, pointer_y = width // 2, height // 2
            _log(f"down: screen=({width},{height}) target={box}")
            controller.post_touch_down(pointer_x, pointer_y, contact=0).wait()
            pointer_held = True
            hold_started_at = time.monotonic()
            for attempt in range(settings.max_aim_attempts):
                image = controller.post_screencap().get(wait=True)
                height, width = image.shape[:2]
                if width <= 0 or height <= 0:
                    return False

                target_x, target_y, vertical_lift = _aim_point(box, settings)
                error_x = target_x - width // 2
                error_y = target_y - height // 2

                if _is_aim_point_centered(width, height, box, settings):
                    _log(
                        f"verify candidate: target={box} aim=({target_x},{target_y}) "
                        f"lift={vertical_lift}"
                    )
                    verified = 1
                    while verified < settings.verification_frames:
                        if settings.settle_delay_ms:
                            time.sleep(settings.settle_delay_ms / 1000)
                        image = controller.post_screencap().get(wait=True)
                        detail = context.run_recognition(settings.target_recognition, image)
                        if not detail or not detail.hit or not detail.best_result:
                            _log(f"verify {verified + 1}: target lost")
                            return False
                        updated_box = _select_tracked_box(detail, _box_center(box))
                        if updated_box is None or not _is_same_target(box, updated_box):
                            _log(f"verify {verified + 1}: target lock lost")
                            return False
                        box = updated_box
                        height, width = image.shape[:2]
                        if not _is_reasonable_target(
                            width, height, box, settings.max_target_area_percent
                        ):
                            _log(f"verify {verified + 1}: rejected oversized target={box}")
                            return False
                        if not _is_aim_point_centered(width, height, box, settings):
                            _log(
                                f"verify {verified + 1}: target moved off aim point target={box}"
                            )
                            break
                        verified += 1
                        _log(f"verify {verified}: centered target={box}")

                    if verified == settings.verification_frames:
                        remaining_hold_ms = settings.min_hold_ms - int(
                            (time.monotonic() - hold_started_at) * 1000
                        )
                        if remaining_hold_ms > 0:
                            time.sleep(remaining_hold_ms / 1000)
                        _log("release: target confirmed on crosshair")
                        controller.post_touch_up(contact=0).wait()
                        pointer_held = False
                        throw_confirmed = True
                        break

                    continue

                # A game throw is a single held drag from the current crosshair
                # to the detected target. Apply the complete measured error,
                # then re-check before considering any small correction.
                move_x = _clamp(
                    error_x * settings.aim_gain_percent // 100,
                    settings.max_relative_move,
                )
                move_y = _clamp(
                    error_y * settings.aim_gain_percent // 100,
                    settings.max_relative_move,
                )
                pointer_x, pointer_y = _screen_point(
                    width, height, pointer_x + move_x, pointer_y + move_y
                )
                _log(
                    f"aim move {attempt + 1}: error=({error_x},{error_y}) "
                    f"delta=({move_x},{move_y}) "
                    f"pointer=({pointer_x},{pointer_y}) target={box} "
                    f"aim=({target_x},{target_y}) lift={vertical_lift}"
                )
                controller.post_touch_move(pointer_x, pointer_y, contact=0).wait()

                if settings.settle_delay_ms:
                    time.sleep(settings.settle_delay_ms / 1000)

                image = controller.post_screencap().get(wait=True)
                detail = context.run_recognition(settings.target_recognition, image)
                if not detail or not detail.hit or not detail.best_result:
                    _log("post-move: target lost; aborting throw")
                    return False
                updated_box = _select_tracked_box(detail, _box_center(box))
                if updated_box is None:
                    _log("post-move: target has no usable box; aborting throw")
                    return False
                if not _is_same_target(box, updated_box):
                    _log(
                        f"post-move: target switched previous={box} current={updated_box}; "
                        "aborting throw"
                    )
                    return False
                box = updated_box
                if not _is_reasonable_target(
                    width, height, box, settings.max_target_area_percent
                ):
                    _log(f"post-move: rejected oversized target={box}; aborting throw")
                    return False
        except (RuntimeError, ValueError, TypeError):
            _log("action error; aborting throw")
            throw_confirmed = False
        finally:
            if pointer_held:
                try:
                    _log("cancel release: target was not confirmed")
                    controller.post_touch_up(contact=0).wait()
                except RuntimeError:
                    pass
        if throw_confirmed and settings.throw_cooldown_ms:
            time.sleep(settings.throw_cooldown_ms / 1000)

        return throw_confirmed


@AgentServer.custom_action("yueya_xuexiong_aim_and_throw")
class YueyaXuexiongAimAndThrow(PipaBirdAimAndThrow):
    # Interface pipeline overrides replace the whole custom_action_param object.
    # Keep target-specific defaults here so single-value option overrides are safe.
    default_settings = AimSettings(
        target_recognition="YueyaXuexiongDetect",
        aim_gain_percent=100,
        max_aim_attempts=4,
        max_relative_move=480,
        settle_delay_ms=140,
        max_target_area_percent=55,
        trajectory_base_lift_px=30,
        trajectory_distance_lift_px=12,
        trajectory_reference_height=100,
    )


def _json_object(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _bounded_float(value: object, default: float, lower: float, upper: float) -> float:
    try:
        return max(lower, min(upper, float(value)))
    except (TypeError, ValueError):
        return default
