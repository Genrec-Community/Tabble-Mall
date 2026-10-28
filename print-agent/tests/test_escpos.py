"""The byte layer.

Worth its own tests despite being a handful of constants, because the two things that
go wrong here are silent on every machine without a printer attached: an encoding that
turns an item name into mojibake, and a column helper that drops the digits off a total.
Neither raises. Both come back as a slip a hotel cannot use.
"""

from __future__ import annotations

import pytest

from print_agent import escpos

pytestmark = pytest.mark.unit


def test_text_encodes_for_the_printer_not_utf8():
    """CP437, because a thermal printer holds a code page rather than a font.

    The failure this guards is invisible in a test that only checks `bytes`: UTF-8 is
    also bytes, and arrives on paper as two garbage characters per accented letter.
    """
    assert escpos.text("Cafe") == b"Cafe"
    assert escpos.text("Café") == "Café".encode("cp437")
    assert escpos.text("Café") != "Café".encode()


def test_an_unrepresentable_character_is_replaced_rather_than_raising():
    """A rupee sign is not in CP437, and a slip is still better than no slip.

    This is the case that would otherwise take out a whole job: `str.encode` raises by
    default, and the exception would surface as a failed print for an item whose name
    happened to contain a character the printer cannot draw.
    """
    out = escpos.text("Thali ₹120")
    assert b"Thali" in out
    assert b"120" in out


def test_columns_puts_the_amount_hard_right():
    line = escpos.columns("Paneer Tikka", "240.00", width=32)
    assert line.endswith(b"\n")
    assert len(line) == 33
    assert line.decode("cp437").rstrip("\n").endswith("240.00")


def test_columns_truncates_the_name_and_never_the_amount():
    """Which side gives way is the whole decision here.

    A bill whose total lost its last digit is a bill that charges the wrong number; a
    bill whose item name is cut short is legible. So the name is what shortens.
    """
    line = escpos.columns("Chicken Biryani Family Pack Extra Large", "1240.00", width=32)
    text = line.decode("cp437").rstrip("\n")
    assert text.endswith("1240.00")
    assert len(text) == 32
    assert text.startswith("Chicken")


def test_columns_keeps_the_amount_when_it_cannot_fit_at_all():
    """A width narrower than the amount is a misconfiguration, not a crash.

    Slicing keeps the leading digits, so the result is visibly wrong rather than
    plausibly wrong -- which is what gets the paper width corrected.
    """
    line = escpos.columns("Total", "123456789.00", width=8)
    assert line == b"12345678\n"


def test_wrapped_breaks_on_spaces():
    out = escpos.wrapped("no onions and no green chilli please", width=16).decode("cp437")
    lines = out.rstrip("\n").split("\n")
    assert all(len(line) <= 16 for line in lines)
    assert all(not line.startswith(" ") for line in lines)
    assert "".join(lines).replace(" ", "") == "noonionsandnogreenchilliplease".replace(" ", "")


def test_wrapped_splits_a_word_too_long_to_fit():
    """An unbroken run has to be cut somewhere, and dropping it is not an option.

    `rfind` returns -1 when there is no space to break on, which as a slice index would
    quietly cut one character off the end of every long word.
    """
    out = escpos.wrapped("Aaaaaaaaaaaaaaaaaaaaaa", width=10).decode("cp437")
    lines = out.rstrip("\n").split("\n")
    assert all(len(line) <= 10 for line in lines)
    assert "".join(lines) == "Aaaaaaaaaaaaaaaaaaaaaa"


def test_wrapped_keeps_an_indent_within_the_width():
    out = escpos.wrapped("extra spicy please", width=20, indent="    ").decode("cp437")
    for line in out.rstrip("\n").split("\n"):
        assert line.startswith("    ")
        assert len(line) <= 20


def test_wrapped_preserves_a_blank_line_the_diner_typed():
    out = escpos.wrapped("first\n\nsecond", width=20).decode("cp437")
    assert out == "first\n\nsecond\n"


def test_feed_is_clamped_to_one_byte():
    """`ESC d n` has one byte for n. An unclamped 300 would raise mid-render.

    Nothing asks for 300 blank lines, which is why this is a clamp and not a check --
    the value comes from our own code, so the useful outcome is a slip that prints.
    """
    assert escpos.feed(3) == b"\x1bd\x03"
    assert escpos.feed(300) == b"\x1bd\xff"
    assert escpos.feed(-1) == b"\x1bd\x00"


def test_size_and_emphasis_are_always_turned_back_off():
    """Printers hold these modes until told otherwise, and the next job inherits them.

    An unbalanced `BOLD_ON` is not visible on the slip that set it; it makes the *next*
    ticket print entirely bold, which reads like a hardware fault.
    """
    assert escpos.emphasised("x") == escpos.BOLD_ON + b"x\n" + escpos.BOLD_OFF
    assert escpos.NORMAL in escpos.big("x")
    assert escpos.ALIGN_LEFT in escpos.big("x")
    assert escpos.ALIGN_LEFT in escpos.centered("x")


def test_raster_is_gs_v_0_with_little_endian_row_bytes_and_height():
    data = b"\xff\x00\xff\x00"

    out = escpos.raster(16, 2, data)

    # GS v 0, m = 0 (normal), xL xH = 2 bytes per row, yL yH = 2 rows, then the bits.
    assert out == b"\x1d\x76\x30\x00\x02\x00\x02\x00" + data


def test_raster_counts_a_partial_last_byte_as_a_whole_one():
    out = escpos.raster(10, 1, b"\xff\xc0")
    assert out[4:6] == b"\x02\x00"  # ceil(10 / 8) = 2 bytes per row


def test_raster_height_over_255_uses_both_height_bytes():
    out = escpos.raster(8, 300, b"\x00" * 300)
    assert out[6:8] == (300).to_bytes(2, "little")


def test_raster_refuses_data_that_does_not_match_its_size():
    with pytest.raises(ValueError):
        escpos.raster(16, 2, b"\xff")
