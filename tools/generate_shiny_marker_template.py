"""Extract the floating shiny marker at 720p, masking the scene background."""
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = cv2.imread(str(ROOT.parent / "database" / "diff_color.png"))
    if source is None:
        raise FileNotFoundError("database/diff_color.png")
    height, width = source.shape[:2]
    image = cv2.resize(source, (round(width * 720 / height), 720),
                       interpolation=cv2.INTER_AREA)
    template = image[287:316, 894:930].copy()
    hsv = cv2.cvtColor(template, cv2.COLOR_BGR2HSV)
    template[hsv[:, :, 2] < 180] = (0, 255, 0)
    destination = ROOT / "assets/resource/image/battle_shiny_marker.png"
    if not cv2.imwrite(str(destination), template):
        raise RuntimeError(f"Unable to write {destination}")
    print(destination)


if __name__ == "__main__":
    main()
