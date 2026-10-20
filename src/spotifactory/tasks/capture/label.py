"""The playlist name printed across the bottom of a playlist's artwork, so a
print of a generic or auto-made cover still says which playlist it is."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

SIZE = 800            # Instax Square print, pixels
SHADE_FRAC = 0.32     # bottom part of the art darkened behind the name
SHADE_ALPHA = 200     # darkness at the very bottom (0-255)
MARGIN = 44           # side and bottom margin for the text
MAX_FONT, MIN_FONT = 64, 36
MAX_LINES = 2


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)   # Pillow's bundled font: nothing to install


def _lines(draw: ImageDraw.ImageDraw, text: str, size: int, width: int) -> list[str] | None:
    """Wrap `text` into at most MAX_LINES that fit `width`, or None if it won't."""
    font, lines, line = _font(size), [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if not line or len(lines) + 1 == MAX_LINES:
            return None
        lines.append(line)
        line = word
    lines.append(line)
    return lines if all(draw.textlength(ln, font=font) <= width for ln in lines) else None


def _fit(draw: ImageDraw.ImageDraw, text: str, width: int) -> tuple[int, list[str]]:
    """Largest font size the name fits at; past MIN_FONT it's cut with an ellipsis."""
    for size in range(MAX_FONT, MIN_FONT - 1, -2):
        lines = _lines(draw, text, size, width)
        if lines:
            return size, lines
    font, words, out = _font(MIN_FONT), text.split(), []
    for _ in range(MAX_LINES):
        line = ""
        while words and draw.textlength(f"{line} {words[0]}".strip() + "…", font=font) <= width:
            line = f"{line} {words.pop(0)}".strip()
        out.append(line)
    out[-1] = out[-1] + "…" if words else out[-1]
    return MIN_FONT, [ln for ln in out if ln]


def add_playlist_label(image: BytesIO, name: str) -> BytesIO:
    """`image` cropped square and sized for the print, with `name` across the bottom."""
    image.seek(0)
    art = Image.open(image).convert("RGB")
    side = min(art.size)
    left, top = (art.width - side) // 2, (art.height - side) // 2
    art = art.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)

    # Fade to dark toward the bottom so white text reads on any cover.
    shade_h = int(SIZE * SHADE_FRAC)
    shade = Image.new("L", (1, shade_h))
    shade.putdata([int(SHADE_ALPHA * (i / (shade_h - 1)) ** 1.5) for i in range(shade_h)])
    black = Image.new("RGB", (SIZE, shade_h))
    art.paste(black, (0, SIZE - shade_h), shade.resize((SIZE, shade_h)))

    draw = ImageDraw.Draw(art)
    size, lines = _fit(draw, " ".join(name.split()), SIZE - 2 * MARGIN)
    font = _font(size)
    line_h = int(size * 1.15)
    y = SIZE - MARGIN - line_h * len(lines)
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill="white",
                  stroke_width=max(1, size // 32), stroke_fill="white")   # a touch bolder
        y += line_h

    out = BytesIO()
    art.save(out, "JPEG", quality=95)
    out.seek(0)
    return out
