"""The KLayout Salt icon and screenshot of the plugin, from the Quantcore Circuits logo.

    python scripts/release/make_salt_images.py

writes ``kplugin/icons/salt_icon.png`` (64 x 64: the Quantcore mark ``assets/logo.png``, CIRCUITS in letter-spaced caps under it, on a white rounded square so it reads on light and dark package
lists) and ``kplugin/icons/salt_screenshot.png`` (640 px wide: the logo over
``docs/images/plugin/window_overview.png``).
``scripts/release/export_plugin.py`` embeds both in the exported ``grain.xml``.
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
LOGO = ROOT / "assets" / "logo-circuits-black.png"
MARK = ROOT / "assets" / "logo.png"  # the small company mark of the Salt icon
SHOT = ROOT / "docs" / "images" / "plugin" / "window_overview.png"
ICONS = ROOT / "kplugin" / "icons"
INK = (17, 17, 17, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    inter = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts/Inter-VariableFont_opsz,wght.ttf"
    for name in (str(inter), "Inter-SemiBold.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf"):
        try:
            f = ImageFont.truetype(name, size)
        except OSError:
            continue
        try:
            f.set_variation_by_axes([14, 650])  # opsz, wght (semibold) on the variable Inter
        except Exception:  # noqa: BLE001 - static fonts have no axes
            pass
        return f
    return ImageFont.load_default()


def icon(out: Path, k: int = 8) -> None:
    n = 64 * k
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * k, 2 * k, n - 2 * k - 1, n - 2 * k - 1), radius=12 * k, fill=(255, 255, 255, 255),
                        outline=(205, 208, 214, 255), width=k)
    mark = Image.open(MARK).convert("RGBA")
    mark = mark.crop(mark.getbbox())  # its visible content
    mh = 36 * k  # rows 6-42: the mark above the CIRCUITS line
    mark = mark.resize((round(mark.width * mh / mark.height), mh), Image.LANCZOS)
    img.alpha_composite(mark, ((n - mark.width) // 2, 6 * k))
    f = _font(10 * k)
    letters = "CIRCUITS"
    boxes = [f.getbbox(c) for c in letters]
    widths = [b[2] - b[0] for b in boxes]
    span = 50 * k
    gap = (span - sum(widths)) / (len(letters) - 1)
    x = (n - span) / 2
    y = 46 * k - min(b[1] for b in boxes)
    for c, b, w in zip(letters, boxes, widths):
        d.text((x - b[0], y), c, font=f, fill=INK)
        x += w + gap
    img.resize((64, 64), Image.LANCZOS).save(out, optimize=True)


def screenshot(out: Path, width: int = 640) -> None:
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.resize((260, round(logo.height * 260 / logo.width)), Image.LANCZOS)
    shot = Image.open(SHOT).convert("RGB")
    shot = shot.resize((width - 24, round(shot.height * (width - 24) / shot.width)), Image.LANCZOS)
    img = Image.new("RGB", (width, 14 + logo.height + 14 + shot.height + 12), (255, 255, 255))
    img.paste(logo, ((width - logo.width) // 2, 14), logo)
    img.paste(shot, (12, 14 + logo.height + 14))
    img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(out, optimize=True)


if __name__ == "__main__":
    ICONS.mkdir(parents=True, exist_ok=True)
    for name, make in (("salt_icon.png", icon), ("salt_screenshot.png", screenshot)):
        make(ICONS / name)
        im = Image.open(ICONS / name)
        print(f"{ICONS / name}  {im.size[0]} x {im.size[1]}  {(ICONS / name).stat().st_size} bytes")
