import base64
import io

import pytest
from PIL import Image

from mallt.core.errors import BadRequest
from mallt.modules.printing import logo


def png(size: tuple[int, int], color: object = (0, 0, 0, 255), mode: str = "RGBA") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format="PNG")
    return out.getvalue()


def test_normalise_shrinks_and_flattens_transparency_onto_white() -> None:
    stored = logo.normalise(png((2000, 1000), (0, 0, 0, 0)))  # fully transparent
    image = Image.open(io.BytesIO(stored))
    assert image.mode == "L" and image.width <= 576 and image.height <= 240
    assert image.getpixel((0, 0)) == 255  # white, not a black slab


def test_normalise_rejects_garbage_and_oversize() -> None:
    with pytest.raises(BadRequest) as bad:
        logo.normalise(b"not an image")
    assert bad.value.code == "bad_image"
    with pytest.raises(BadRequest) as big:
        logo.normalise(b"\0" * (logo.MAX_UPLOAD_BYTES + 1))
    assert big.value.code == "logo_too_large"


def test_raster_is_one_bit_msb_first_with_black_as_one() -> None:
    stored = logo.normalise(png((16, 4), (0, 0, 0, 255)))  # solid black
    r = logo.raster_for(stored, 32)
    assert r is not None and r["width"] == 16 and r["height"] == 4
    raw = base64.b64decode(r["data"])
    assert raw == b"\xff" * 8  # 2 bytes per row x 4 rows, all black
    white = logo.raster_for(logo.normalise(png((16, 4), (255, 255, 255, 255))), 32)
    assert white is not None and set(base64.b64decode(white["data"])) == {0}


def test_raster_fits_the_paper_and_pads_rows_to_bytes() -> None:
    r = logo.raster_for(logo.normalise(png((500, 100))), 32)  # 58 mm = 384 dots
    assert r is not None and r["width"] <= 384 and r["height"] <= 200
    assert len(base64.b64decode(r["data"])) == ((r["width"] + 7) // 8) * r["height"]
    r_odd = logo.raster_for(logo.normalise(png((13, 5))), 32)
    assert r_odd is not None and len(base64.b64decode(r_odd["data"])) == 2 * 5
    assert logo.raster_for(b"junk", 32) is None
