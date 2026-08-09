"""Focused checks for target-pet centering and lock continuity."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.pipa_bird import (
    _box_center_tolerance,
    _pitch_recovery_move,
    _relative_aim_move,
    _select_locked_candidate,
    _updated_pitch_offset,
)


def main() -> None:
    assert _box_center_tolerance((634, 305, 62, 23), 48) == (25, 9)
    assert _box_center_tolerance((661, 317, 88, 60), 48) == (35, 24)
    assert _box_center_tolerance((0, 0, 10, 10), 48) == (8, 6)

    assert _relative_aim_move(-523, -287, 240, 100, 320) == (-240, -768)
    assert _relative_aim_move(1, -107, 24, 100, 320) == (1, -76)
    assert _relative_aim_move(81, -8, 24, 100, 320) == (24, -26)

    assert _updated_pitch_offset(800, 300, 900) == 900
    assert _updated_pitch_offset(-800, -300, 900) == -900
    assert _pitch_recovery_move(900, 240) == -240
    assert _pitch_recovery_move(-100, 240) == 100

    pitch_offset = 900
    recovery_moves = []
    while pitch_offset:
        recovery_y = _pitch_recovery_move(pitch_offset, 240)
        recovery_moves.append(recovery_y)
        pitch_offset = _updated_pitch_offset(pitch_offset, recovery_y, 900)
    assert recovery_moves == [-240, -240, -240, -180]

    previous = (92, 329, 80, 37)
    nearby = (180, 320, 82, 39)
    far_away = (1120, 367, 158, 83)
    assert _select_locked_candidate([nearby, far_away], previous, (-240, -13), 360) == nearby
    assert _select_locked_candidate([far_away], previous, (-240, -13), 360) is None

    # Regression from the 2026-08-09 run: keep the low-score box near the
    # predicted position instead of jumping to a differently sized far target.
    previous = (631, 368, 73, 62)
    intended = (633, 360, 74, 57)
    wrong_far_target = (471, 159, 38, 32)
    assert (
        _select_locked_candidate(
            [wrong_far_target, intended], previous, (2, 75), 360
        )
        == intended
    )
    assert (
        _select_locked_candidate([wrong_far_target], previous, (2, 75), 360)
        is None
    )

    print("target pet strategy checks passed")


if __name__ == "__main__":
    main()
