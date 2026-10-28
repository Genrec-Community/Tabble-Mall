"""ESC/POS bytes, written here rather than taken from a library.

`python-escpos` is the obvious dependency and is deliberately not used. It reaches the
hardware through `pyusb`, which needs libusb installed on the machine, and this app is
shipped as a PyInstaller binary to store PCs whose owners do not install system
libraries. What we actually need of ESC/POS is the few dozen control bytes below; the
rest of that library is drivers we replace with `transports.py` anyway.

**Encoding is CP437, not UTF-8.** Thermal printers hold a code page, not a Unicode
font, and a UTF-8 item name arrives as mojibake on paper. Anything CP437 cannot
represent is replaced rather than raised on: a rupee sign that prints as `?` is a
legible slip, and an exception here would be a slip that never prints at all.
"""

from __future__ import annotations

from typing import Final

#: The printer's own encoding. Set on the device by `SELECT_CP437` below, so the two
#: cannot drift apart without this constant changing.
CODEPAGE: Final = "cp437"

ESC: Final = b"\x1b"
GS: Final = b"\x1d"

INIT: Final = ESC + b"@"
#: `ESC t 0` -- page 0 is CP437 on every printer that implements the command.
SELECT_CP437: Final = ESC + b"t\x00"

ALIGN_LEFT: Final = ESC + b"a\x00"
ALIGN_CENTER: Final = ESC + b"a\x01"

BOLD_ON: Final = ESC + b"E\x01"
BOLD_OFF: Final = ESC + b"E\x00"

#: `GS ! n`, where the high nibble doubles width and the low nibble doubles height.
NORMAL: Final = GS + b"!\x00"
DOUBLE: Final = GS + b"!\x11"
DOUBLE_HEIGHT: Final = GS + b"!\x01"

#: `GS V 66 n` -- feed n dots, then cut, with n zero here. The feed is not skipped: the
#: renderers emit `feed(3)` first, in whole lines. A cut with nothing fed severs the
#: paper inside the mechanism, above the last thing printed, so the callers own that
#: feed explicitly rather than having it hidden in this constant at some dot count that
#: reads as arbitrary.
CUT: Final = GS + b"VB\x00"


#: `GS V 65 n`: feed, then cut all the way through. `CUT` above is the partial cut.
CUT_FULL: Final = GS + b"VA\x00"

#: `ESC M 1`: Font B (9x17 dots), narrower than the default Font A (12x24).
FONT_B: Final = ESC + b"M\x01"

#: `ESC p 0 25 250`: pulse the cash-drawer kick connector.
DRAWER_KICK: Final = ESC + b"p\x00\x19\xfa"

#: `ESC B 2 2`: two beeps on printers with a buzzer; others ignore it.
BEEP: Final = ESC + b"B\x02\x02"


def scale(width: int = 1, height: int = 1) -> bytes:
    """`GS ! n` for a width and height multiplier of 1-4."""
    w = max(1, min(width, 4)) - 1
    h = max(1, min(height, 4)) - 1
    return GS + b"!" + bytes([(w << 4) | h])


def line_spacing(dots: int) -> bytes:
    """`ESC 3 n`: the space between lines, in dots."""
    return ESC + b"3" + bytes([max(0, min(dots, 255))])


def left_margin(dots: int) -> bytes:
    """`GS L nL nH`: blank dots at the left edge."""
    return GS + b"L" + max(0, min(dots, 65535)).to_bytes(2, "little")


def print_width(dots: int) -> bytes:
    """`GS W nL nH`: the printable width in dots."""
    return GS + b"W" + max(0, min(dots, 65535)).to_bytes(2, "little")


def text(value: str) -> bytes:
    """One run of characters, encoded for the printer.

    Newlines are the caller's business -- `line()` adds them -- because a payload
    field containing one should not silently become two lines on the slip.
    """
    return value.encode(CODEPAGE, errors="replace")


def line(value: str = "") -> bytes:
    return text(value) + b"\n"


def feed(lines: int = 1) -> bytes:
    """Blank lines. `ESC d n` rather than n newlines, which is one byte either way
    but says feed rather than print-nothing."""
    return ESC + b"d" + bytes([max(0, min(lines, 255))])


def centered(value: str) -> bytes:
    return ALIGN_CENTER + line(value) + ALIGN_LEFT


def emphasised(value: str) -> bytes:
    return BOLD_ON + line(value) + BOLD_OFF


def big(value: str, size: bytes = DOUBLE, restore: bytes = NORMAL) -> bytes:
    """Enlarged and centred, for the one thing a cook reads across a pass."""
    return ALIGN_CENTER + size + line(value) + restore + ALIGN_LEFT


def rule(width: int, char: str = "-") -> bytes:
    return line(char * width)


def raster(width: int, height: int, data: bytes) -> bytes:
    """A raster bit image: `GS v 0 m xL xH yL yH d1..dk`, normal density.

    `width` is in dots; the command wants whole bytes per row, so a width that is not a
    multiple of 8 is rounded up and `data` must already carry that padding. Bit 1 is a
    printed dot, most significant bit first. Refuses data that does not match, because
    a printer fed a short raster sits waiting for the rest and prints the *next* thing
    as garbage.
    """
    row_bytes = (width + 7) // 8
    if len(data) != row_bytes * height:
        raise ValueError(
            f"raster of {width}x{height} needs {row_bytes * height} bytes, got {len(data)}"
        )
    return (
        GS + b"v0" + b"\x00" + row_bytes.to_bytes(2, "little") + height.to_bytes(2, "little") + data
    )


def columns(left: str, right: str, width: int) -> bytes:
    """`left` flush left, `right` flush right, on one line of `width` characters.

    When they cannot both fit, the left side is truncated: the right side is a
    quantity or an amount, and a bill whose total lost its last digit is worse than
    one whose item name is cut short.
    """
    room = width - len(right) - 1
    if room < 1:
        return line(right[:width])
    if len(left) > room:
        left = left[: room - 1] + "."
    return line(f"{left:<{room}} {right:>{len(right)}}")


def wrapped(value: str, width: int, *, indent: str = "") -> bytes:
    """A long field broken across lines, on word boundaries where there are any.

    Written out rather than using `textwrap`, which collapses runs of spaces and
    drops leading indentation in ways that need arguments to switch off -- and a
    note reading "no onions   PLEASE" should keep whatever the diner typed.
    """
    room = max(1, width - len(indent))
    out = bytearray()
    for paragraph in value.split("\n"):
        remaining = paragraph
        if not remaining:
            out += line(indent)
            continue
        while remaining:
            if len(remaining) <= room:
                out += line(indent + remaining)
                break
            cut = remaining.rfind(" ", 0, room + 1)
            if cut <= 0:
                cut = room
            out += line(indent + remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
    return bytes(out)


def qr(data: str, *, module_size: int = 6) -> bytes:
    """A QR code printed by the printer itself (`GS ( k`, model 2).

    Used for the UPI payment link on a bill. The printer builds the code from the
    text, so no image library is needed and the code stays sharp at any paper
    width. Centred, with error correction M so a crease or a splash still scans.
    Data is ASCII (a `upi://` URI); anything else is replaced.
    """
    payload = data.encode("ascii", errors="replace")
    store_len = len(payload) + 3
    size = max(1, min(module_size, 16))
    return (
        ALIGN_CENTER
        # Select model 2.
        + GS
        + b"(k"
        + bytes([4, 0, 49, 65, 50, 0])
        # Module size.
        + GS
        + b"(k"
        + bytes([3, 0, 49, 67, size])
        # Error correction level M.
        + GS
        + b"(k"
        + bytes([3, 0, 49, 69, 49])
        # Store the data.
        + GS
        + b"(k"
        + store_len.to_bytes(2, "little")
        + bytes([49, 80, 48])
        + payload
        # Print it.
        + GS
        + b"(k"
        + bytes([3, 0, 49, 81, 48])
        + b"\n"
        + ALIGN_LEFT
    )
