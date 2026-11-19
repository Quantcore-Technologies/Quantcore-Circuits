"""Make the KLayout toolbar icons (kplugin/icons/<tool>.png) from the artwork in assets/.

Run from the repo root in the qcd env:  python kplugin/make_icons.py
Each source image is cropped to its visible (non-transparent) content, padded to a square and resized to 64×64
(KLayout scales it down for the toolbar). The tool ids match ``qcc_kplugin.tools.register_tools``.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "qcc_connect": "connect.png",
    "qcc_route_edit": "Route Handles.png",
    "qcc_snap": "move_snap.png",
}
SIZE = 64
PAD = 0.06  # fraction of the side kept free around the artwork


def make_icon(src: Path, dst: Path, size: int = SIZE) -> Path:
    im = Image.open(src).convert("RGBA")
    alpha = im.getchannel("A").point(lambda a: 255 if a > 8 else 0)
    box = alpha.getbbox() or (0, 0, *im.size)
    im = im.crop(box)
    side = int(max(im.size) * (1 + 2 * PAD))
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    dst.parent.mkdir(parents=True, exist_ok=True)
    square.resize((size, size), Image.LANCZOS).save(dst)
    return dst


if __name__ == "__main__":
    for ident, name in SOURCES.items():
        print(make_icon(ROOT / "assets" / name, ROOT / "kplugin" / "icons" / f"{ident}.png"))
