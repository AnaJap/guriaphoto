"""Generate src/assets/icon.png — the branded Kodak "K" badge app icon.

Dev-only tool (requires Pillow). Run once to (re)generate the icon, then
commit the resulting PNG. The icon is NOT a runtime dependency.

    uv pip install --python venv/bin/python pillow
    PYTHONPATH=src venv/bin/python tools/make_icon.py

Flet's `flet build` reads `<app-path>/assets/icon.png` (app path is "src" per
[tool.flet.app]) and derives the platform icons (Windows .ico, macOS .icns).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Kodak brand colors — matches ui/login.py:_kodak_logo
KODAK_RED = (237, 28, 36)      # #ED1C24
KODAK_YELLOW = (245, 166, 35)  # #F5A623
WHITE = (255, 255, 255)

SIZE = 1024
# Rounded-square badge inset from the canvas edge.
MARGIN = 96
CORNER = 180
STRIPE_H = 96  # yellow bottom stripe height


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    """Try a few common bold fonts; fall back to Pillow's default."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    return ImageFont.load_default()


def build_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    left, top = MARGIN, MARGIN
    right, bottom = SIZE - MARGIN, SIZE - MARGIN

    # Red rounded-square badge.
    draw.rounded_rectangle(
        [left, top, right, bottom], radius=CORNER, fill=KODAK_RED
    )

    # Yellow bottom stripe — clipped to the badge's rounded corners.
    stripe_top = bottom - STRIPE_H
    stripe = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(stripe)
    sdraw.rounded_rectangle(
        [left, top, right, bottom], radius=CORNER, fill=KODAK_YELLOW
    )
    # Keep only the band below stripe_top.
    band = stripe.crop((0, stripe_top, SIZE, bottom))
    img.paste(band, (0, stripe_top), band)

    # White bold "K", centered in the red area above the stripe.
    font = _load_font(560)
    text = "K"
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    cx = (left + right) / 2
    cy = (top + stripe_top) / 2
    tx = cx - tw / 2 - tb[0]
    ty = cy - th / 2 - tb[1]
    draw.text((tx, ty), text, font=font, fill=WHITE)

    return img


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "src" / "assets" / "icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    build_icon().save(out, "PNG")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
