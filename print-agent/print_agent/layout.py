"""How a slip is laid out, as the store chose it, with today's look as the default.

A job carries two optional objects the admin edits on the printers screen:

* `layout` (on the job frame): this printer's hardware settings -- font, text size,
  margins, line spacing, feeds, cut, copies, drawer.
* `options` (in the payload): which lines print and what they are called.

Both are read **leniently**. A value of the wrong type, out of range, or from a
server that predates the field is ignored and the default used, because a slip that
prints in the usual layout beats a job that fails over a cosmetic setting. With
neither object present every byte produced is what it was before they existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import escpos


def _int(source: Any, key: str, default: int, low: int, high: int) -> int:
    value = source.get(key) if isinstance(source, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    return default


def _optional_int(source: Any, key: str, low: int, high: int) -> int | None:
    value = source.get(key) if isinstance(source, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    return None


def _choice(source: Any, key: str, default: str, allowed: tuple[str, ...]) -> str:
    value = source.get(key) if isinstance(source, dict) else None
    return value if isinstance(value, str) and value in allowed else default


def _flag(source: Any, key: str, default: bool) -> bool:
    value = source.get(key) if isinstance(source, dict) else None
    return value if isinstance(value, bool) else default


def _word(source: Any, key: str, default: str) -> str:
    value = source.get(key) if isinstance(source, dict) else None
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else default


@dataclass(frozen=True)
class Layout:
    font: str = "a"
    text_width: int = 1
    text_height: int = 1
    heading_width: int = 2
    heading_height: int = 2
    item_width: int = 1
    item_height: int = 2
    line_spacing: int | None = None
    left_margin: int = 0
    print_width_dots: int | None = None
    rule_char: str = "-"
    feed_before: int = 0
    feed_after: int = 3
    cut: str = "partial"
    copies: int = 1
    qr_size: int | None = None
    open_drawer: bool = False
    beep: bool = False
    bold_items: bool = False

    @classmethod
    def from_job(cls, job: dict[str, Any]) -> Layout:
        raw = job.get("layout")
        d = cls()
        return cls(
            font=_choice(raw, "font", d.font, ("a", "b")),
            text_width=_int(raw, "text_width", d.text_width, 1, 4),
            text_height=_int(raw, "text_height", d.text_height, 1, 4),
            heading_width=_int(raw, "heading_width", d.heading_width, 1, 4),
            heading_height=_int(raw, "heading_height", d.heading_height, 1, 4),
            item_width=_int(raw, "item_width", d.item_width, 1, 4),
            item_height=_int(raw, "item_height", d.item_height, 1, 4),
            line_spacing=_optional_int(raw, "line_spacing", 0, 255),
            left_margin=_int(raw, "left_margin", d.left_margin, 0, 600),
            print_width_dots=_optional_int(raw, "print_width_dots", 96, 832),
            rule_char=_choice(raw, "rule_char", d.rule_char, ("-", "=", "*", "_", ".")),
            feed_before=_int(raw, "feed_before", d.feed_before, 0, 10),
            feed_after=_int(raw, "feed_after", d.feed_after, 0, 20),
            cut=_choice(raw, "cut", d.cut, ("full", "partial", "none")),
            copies=_int(raw, "copies", d.copies, 1, 5),
            qr_size=_optional_int(raw, "qr_size", 2, 16),
            open_drawer=_flag(raw, "open_drawer", d.open_drawer),
            beep=_flag(raw, "beep", d.beep),
            bold_items=_flag(raw, "bold_items", d.bold_items),
        )

    # -- derived bytes and widths -------------------------------------------

    @property
    def prologue(self) -> bytes:
        """Reset, code page, then only the settings that differ from the default."""
        out = bytearray(escpos.INIT + escpos.SELECT_CP437)
        if self.font == "b":
            out += escpos.FONT_B
        if self.line_spacing is not None:
            out += escpos.line_spacing(self.line_spacing)
        if self.left_margin:
            out += escpos.left_margin(self.left_margin)
        if self.print_width_dots:
            out += escpos.print_width(self.print_width_dots)
        if self.beep:
            out += escpos.BEEP
        out += self.normal
        if self.feed_before:
            out += escpos.feed(self.feed_before)
        return bytes(out)

    @property
    def normal(self) -> bytes:
        return escpos.scale(self.text_width, self.text_height)

    @property
    def heading(self) -> bytes:
        return escpos.scale(self.heading_width, self.heading_height)

    @property
    def item(self) -> bytes:
        return escpos.scale(self.item_width, self.item_height)

    def cols(self, width: int, scale: int = 0) -> int:
        """Characters per line once text is enlarged: a double-width line holds half."""
        return max(1, width // (scale or self.text_width))

    @property
    def epilogue(self) -> bytes:
        out = bytearray(escpos.feed(self.feed_after))
        if self.cut == "full":
            out += escpos.CUT_FULL
        elif self.cut == "partial":
            out += escpos.CUT
        return bytes(out)

    @property
    def drawer(self) -> bytes:
        return escpos.DRAWER_KICK if self.open_drawer else b""


@dataclass(frozen=True)
class Options:
    """What a bill and a kitchen slip show and what the lines are called."""

    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Options:
        raw = payload.get("options")
        return cls(raw if isinstance(raw, dict) else {})

    def show(self, key: str) -> bool:
        return _flag(self.raw, key, True)

    def on(self, key: str) -> bool:
        """For a line that is off unless the store turns it on."""
        return _flag(self.raw, key, False)

    def label(self, key: str, default: str) -> str:
        return _word(self.raw, key, default)

    @property
    def currency(self) -> str:
        value = self.raw.get("currency_symbol")
        return value.strip() if isinstance(value, str) else ""

    def money(self, value: Any) -> str:
        text = str(value)
        return f"{self.currency}{text}" if self.currency and text else text
