"""Focused checks for target-pet centering and lock continuity."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.pipa_bird import (
    _box_center_tolerance,
    _relative_aim_move,
    _select_locked_candidate,
)


def main() -> None:
    assert _box_center_tolerance((634, 305, 62, 23), 48) == (22, 8)
    assert _box_center_tolerance((661, 317, 88, 60), 48) == (31, 21)
    assert _box_center_tolerance((0, 0, 10, 10), 48) == (8, 6)

    assert _relative_aim_move(-523, -287, 240, 100, 320) == (-240, -768)
    assert _relative_aim_move(1, -107, 24, 100, 320) == (1, -76)
    assert _relative_aim_move(81, -8, 24, 100, 320) == (24, -26)

    previous = (92, 329, 80, 37)
    nearby = (180, 320, 82, 39)
    far_away = (1120, 367, 158, 83)
    assert _select_locked_candidate([nearby, far_away], previous, (-240, -13), 360) == nearby
    assert _select_locked_candidate([far_away], previous, (-240, -13), 360) is None

    print("target pet strategy checks passed")


if __name__ == "__main__":
    main()
