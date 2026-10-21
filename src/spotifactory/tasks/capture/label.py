"""A name printed across the bottom of the artwork, if asked for: a playlist's
name, or an album's name and artist, so a print whose cover has no text (or a
generic or auto-made one) still says what it is."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

SIZE = 800            # Instax Square print, pixels
SHADE_FRAC = 0.32     # bottom part of the art darkened behind the name, at least
SHADE_RAMP = 90       # px of soft fade above the text
SHADE_TEXT = 170      # darkness where the text starts (0-255)...
SHADE_ALPHA = 215     # ...and at the very bottom
MARGIN = 44           # side and bottom margin for the text
MAX_FONT, MIN_FONT = 64, 36
MAX_LINES = 2
SUB_FONT = 34         # the subtitle (an album's artist) under the name


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


def _one_line(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    """`text` cut with an ellipsis to fit on one line."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def add_label(image: BytesIO, name: str, subtitle: str | None = None) -> BytesIO:
    """`image` cropped square and sized for the print, with `name` across the
    bottom and, if given, a smaller `subtitle` (an album's artist) under it."""
    image.seek(0)
    art = Image.open(image).convert("RGB")
    side = min(art.size)
    left, top = (art.width - side) // 2, (art.height - side) // 2
    art = art.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(art)
    width = SIZE - 2 * MARGIN
    size, lines = _fit(draw, " ".join(name.split()), width)
    font = _font(size)
    line_h = int(size * 1.15)
    sub_font = _font(SUB_FONT)
    sub = _one_line(draw, " ".join(subtitle.split()), sub_font, width) if subtitle else ""
    sub_h = int(SUB_FONT * 1.4) if sub else 0
    text_top = SIZE - MARGIN - line_h * len(lines) - sub_h

    # Fade to dark toward the bottom so white text reads on any cover: a soft
    # ramp above the text, then dark enough behind it, however many lines.
    shade_top = min(SIZE - int(SIZE * SHADE_FRAC), text_top - SHADE_RAMP)
    shade_h = SIZE - shade_top
    ramp = text_top - shade_top
    shade = Image.new("L", (1, shade_h))
    shade.putdata([int(SHADE_TEXT * (i / ramp) ** 1.5) if i < ramp
                   else int(SHADE_TEXT + (SHADE_ALPHA - SHADE_TEXT) * (i - ramp) / max(1, shade_h - ramp))
                   for i in range(shade_h)])
    art.paste(Image.new("RGB", (SIZE, shade_h)), (0, shade_top), shade.resize((SIZE, shade_h)))

    def text(xy, s, f, fill, bold=0):
        x, y = xy
        draw.text((x + 2, y + 3), s, font=f, fill=(0, 0, 0), stroke_width=bold, stroke_fill=(0, 0, 0))  # shadow
        draw.text((x, y), s, font=f, fill=fill, stroke_width=bold, stroke_fill=fill)

    y = text_top
    for line in lines:
        text((MARGIN, y), line, font, (255, 255, 255), bold=max(1, size // 32))   # a touch bolder
        y += line_h
    if sub:
        text((MARGIN, y + int(SUB_FONT * 0.25)), sub, sub_font, (225, 225, 225))

    out = BytesIO()
    art.save(out, "JPEG", quality=95)
    out.seek(0)
    return out
