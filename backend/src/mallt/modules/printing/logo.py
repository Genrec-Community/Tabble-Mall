"""Bill logo: normalise an upload once, then cut/dither it to the printer's paper at queue time.

The agent ships to store PCs with a single dependency and has no image library, so the
server produces the 1-bit raster (ESC/POS: 1 = black, MSB first, rows padded to bytes)."""

import base64
import io
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from mallt.core.errors import BadRequest

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_STORED_BYTES = 256 * 1024
STORED_MAX_WIDTH = 576
STORED_MAX_HEIGHT = 240
PRINT_MAX_HEIGHT = 200
DOTS_PER_CHAR = 12  # Font A


def normalise(raw: bytes) -> bytes:
    """Any common image -> small greyscale PNG on white. Raises BadRequest if unusable."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadRequest("logo_too_large", "That image is too large (5 MB maximum).")
    Image.MAX_IMAGE_PIXELS = 20_000_000  # refuse decompression bombs
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise BadRequest("bad_image", "That file is not a usable image.") from exc
    rgba = image.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))  # transparent -> white, not black
    flat.alpha_composite(rgba)
    grey = ImageOps.grayscale(flat.convert("RGB"))
    grey.thumbnail((STORED_MAX_WIDTH, STORED_MAX_HEIGHT))
    out = io.BytesIO()
    grey.save(out, format="PNG", optimize=True)
    data = out.getvalue()
    if len(data) > MAX_STORED_BYTES:
        raise BadRequest("logo_too_complex", "Use a simpler logo (a photo is too detailed).")
    return data


def raster_for(png: bytes, paper_width_chars: int) -> dict[str, Any] | None:
    """The stored logo as a dithered raster for one paper width, or None if it cannot be made."""
    try:
        image = Image.open(io.BytesIO(png)).convert("L")
    except (UnidentifiedImageError, OSError):
        return None
    max_w = max(8, paper_width_chars * DOTS_PER_CHAR)
    image.thumbnail((max_w, PRINT_MAX_HEIGHT))
    bits = image.convert("1")  # Floyd-Steinberg dither; 255 = white
    width, height = bits.size
    inverted = ImageOps.invert(bits.convert("L")).convert("1")  # 1 = black dot
    row_bytes = (width + 7) // 8
    pixels = inverted.load()
    if pixels is None:  # pragma: no cover
        return None
    data = bytearray(row_bytes * height)
    for y in range(height):
        for x in range(width):
            if pixels[x, y]:
                data[y * row_bytes + x // 8] |= 0x80 >> (x % 8)
    return {"width": width, "height": height, "data": base64.b64encode(bytes(data)).decode()}
