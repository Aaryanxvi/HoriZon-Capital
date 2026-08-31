"""Generate desktop/icons/icon.ico — the window, taskbar and tray icon.

Kept as a script rather than a committed binary blob so the mark can be
regenerated when the brand colour changes:

    python desktop/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CLAY = (201, 100, 66, 255)
PAPER = (250, 249, 245, 255)
SIZES = [16, 32, 48, 64, 128, 256]
OUT = Path(__file__).parent / "icons" / "icon.ico"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    """A clay rounded square with a paper-white H, drawn at 4x then downsampled."""
    scale = 4
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    radius = int(size * scale * 0.22)
    draw.rounded_rectangle(
        [(0, 0), (size * scale - 1, size * scale - 1)], radius=radius, fill=CLAY
    )

    font = _font(int(size * scale * 0.62))
    box = draw.textbbox((0, 0), "H", font=font)
    draw.text(
        (
            (size * scale - (box[2] - box[0])) / 2 - box[0],
            (size * scale - (box[3] - box[1])) / 2 - box[1],
        ),
        "H",
        font=font,
        fill=PAPER,
    )
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [render(size) for size in SIZES]
    images[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT} ({', '.join(f'{s}x{s}' for s in SIZES)})")


if __name__ == "__main__":
    main()
