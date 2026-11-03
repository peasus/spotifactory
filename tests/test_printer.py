"""Fitting square album art to each Instax film size."""
from io import BytesIO
from unittest.mock import MagicMock, patch

from PIL import Image

from spotifactory.hardware import printer

RED = (220, 20, 20)
WHITE = (255, 255, 255)


def _art(size=(640, 640), colour=RED) -> BytesIO:
    buf = BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    buf.seek(0)
    return buf


def _close(a, b, tol=8):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_square_art_fills_a_square_print():
    film = printer.fit_to_film(_art(), (800, 800))
    assert film.size == (800, 800)
    for xy in [(0, 0), (799, 799), (400, 400)]:
        assert _close(film.getpixel(xy), RED)


def test_square_art_on_mini_gets_bands_top_and_bottom_not_stretched():
    film = printer.fit_to_film(_art(), (600, 800))
    assert film.size == (600, 800)
    assert film.getpixel((300, 50)) == WHITE        # band above
    assert film.getpixel((300, 750)) == WHITE       # band below
    assert _close(film.getpixel((0, 400)), RED)     # art reaches both sides
    assert _close(film.getpixel((599, 400)), RED)
    assert _close(film.getpixel((300, 102)), RED)   # art is 600 tall: rows 100-699
    assert _close(film.getpixel((300, 697)), RED)


def test_square_art_on_wide_gets_bands_either_side():
    film = printer.fit_to_film(_art(), (1260, 840))
    assert film.size == (1260, 840)
    assert film.getpixel((100, 420)) == WHITE
    assert film.getpixel((1160, 420)) == WHITE
    assert _close(film.getpixel((212, 0)), RED)     # art is 840 wide: cols 210-1049
    assert _close(film.getpixel((1047, 839)), RED)


def test_upside_down_turns_the_print_round():
    art = Image.new("RGB", (640, 640), RED)
    art.paste(Image.new("RGB", (640, 320), (0, 0, 255)), (0, 0))   # blue top half
    film = printer.fit_to_film(art, (600, 800), upside_down=True)
    assert _close(film.getpixel((300, 650)), (0, 0, 255))           # blue now at the bottom


def test_prepare_caps_mini_jpegs_small_and_reads_the_flip_setting(monkeypatch):
    mini = MagicMock(imageSize=(600, 800))
    monkeypatch.setenv(printer.FLIP_SETTING, "1")
    out = Image.open(printer._prepare(mini, _art()))
    assert mini.maxImageKb == 55
    assert out.size == (600, 800)
    assert out.getpixel((300, 750)) == WHITE

    square = MagicMock(imageSize=(800, 800))
    monkeypatch.delenv(printer.FLIP_SETTING)
    printer._prepare(square, _art())
    assert square.maxImageKb == printer.DEFAULT_MAX_KB


def test_print_image_sends_art_fitted_to_the_connected_printer():
    fake = MagicMock(imageSize=(1260, 840), photosLeft=5, batteryPercentage=80,
                     upload_complete=True, print_confirmed=True, cancelled=False)
    fake.peripheral.is_connected.return_value = True
    with patch.object(printer, "_make_instax", return_value=fake), \
         patch.object(printer, "_connect"):
        result = printer.print_image(_art())
    assert result.success
    sent = Image.open(fake.print_image.call_args.args[0])
    assert sent.size == (1260, 840)
    assert sent.getpixel((100, 420)) == WHITE
