"""Structured payload in, paper out.

The server sends fields, not bytes, so a store that wants a different title or a smaller font
changes a setting in the dashboard, not the agent.

**A kitchen ticket carries no money and no pickup code.** The code is the customer's proof of
purchase: a ticket showing it would let the counter mark orders picked up without the customer.

**Nothing here raises for a field being absent.** A payload from a newer or older server is
missing keys, and the right outcome is a slip that omits a line, not a job the kitchen never
sees. Only a payload of a kind we do not recognise is refused.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from . import escpos
from .layout import Layout, Options

logger = logging.getLogger(__name__)

LOGO_MAX_WIDTH = 576
LOGO_MAX_HEIGHT = 512


class UnknownPayload(Exception):
    """The payload names a kind this agent cannot render (reported back by job id)."""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _note_block(note: Any, width: int, *, label: str, indent: str = "") -> bytes:
    """A note with its label wrapped as part of it, all bold: the one thing on a slip that
    must not be skimmed past."""
    if not isinstance(note, str) or not note.strip():
        return b""
    return (
        escpos.BOLD_ON
        + escpos.wrapped(f"{label}: {note.strip()}", width, indent=indent)
        + escpos.BOLD_OFF
    )


def _logo_block(logo: Any) -> bytes:
    """The logo as a centred raster, or nothing. Every check is a reason to skip the logo and
    still print the bill."""
    if not isinstance(logo, dict):
        return b""
    width, height, data = logo.get("width"), logo.get("height"), logo.get("data")
    if (
        _int(width) is None
        or _int(height) is None
        or not isinstance(data, str)
        or not 1 <= width <= LOGO_MAX_WIDTH  # type: ignore[operator]
        or not 1 <= height <= LOGO_MAX_HEIGHT  # type: ignore[operator]
    ):
        logger.warning("bill logo skipped: its size or data is not usable")
        return b""
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        logger.warning("bill logo skipped: its data is not base64")
        return b""
    if len(raw) != ((width + 7) // 8) * height:  # type: ignore[operator]
        logger.warning("bill logo skipped: its data does not match its size")
        return b""
    return (
        escpos.ALIGN_CENTER
        + escpos.raster(width, height, raw)  # type: ignore[arg-type]
        + escpos.ALIGN_LEFT
        + escpos.feed(1)
    )


def _header_block(header: Any, layout: Layout, options: Options, width: int) -> bytes:
    if not isinstance(header, dict):
        return b""
    cols = layout.cols(width)
    out = bytearray()
    if options.show("show_logo"):
        out += _logo_block(header.get("logo"))
    name = _text(header.get("name"))
    if name:
        out += (
            escpos.ALIGN_CENTER
            + escpos.BOLD_ON
            + escpos.scale(layout.text_width, layout.text_height * 2)
            + escpos.wrapped(name, cols)
            + layout.normal
            + escpos.BOLD_OFF
            + escpos.ALIGN_LEFT
        )
    phone = _text(header.get("phone"))
    for text in (
        _text(header.get("address")),
        f"Ph: {phone}" if phone else "",
        _text(header.get("extra")),
    ):
        if text:
            out += escpos.ALIGN_CENTER + escpos.wrapped(text, cols) + escpos.ALIGN_LEFT
    if out:
        out += escpos.rule(cols, layout.rule_char)
    return bytes(out)


def render_ticket(payload: dict[str, Any], *, width: int, layout: Layout) -> bytes:
    """A kitchen ticket: order number at double size (read from arm's length), then items.

    Quantity leads each line so a column of tickets scans down."""
    options = Options.from_payload(payload)
    body = layout.cols(width)
    item_cols = layout.cols(width, layout.item_width)
    big = lambda text: escpos.big(text, layout.heading, layout.normal)  # noqa: E731

    out = bytearray(layout.prologue)
    out += big(options.label("ticket_title", "ORDER"))
    number = _int(payload.get("order_no"))
    out += big(f"#{number}" if number is not None else "#???")
    store = _text(payload.get("store"))
    if store and options.show("ticket_show_store"):
        out += escpos.centered(store)
    when = _text(payload.get("time"))
    if when and options.show("ticket_show_time"):
        out += escpos.centered(when)
    eta = _int(payload.get("eta_minutes"))
    if eta and options.show("ticket_show_eta"):
        out += escpos.centered(f"Ready in about {eta} min")
    customer = _text(payload.get("customer_name"))
    if customer and options.show("ticket_show_customer"):
        out += escpos.centered(customer)
    revision = _int(payload.get("revision"))
    if revision and revision > 0:
        out += escpos.centered(f"*** REPRINT #{revision} ***")
    out += escpos.rule(body, layout.rule_char)

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        # Printed anyway: "no items" is a bug a cook can report; no paper looks like a dead printer.
        out += escpos.emphasised("(no items on this ticket)")
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        quantity, name = item.get("quantity"), item.get("name")
        head = f"{quantity} x {name}" if quantity is not None else str(name)
        out += layout.item + (escpos.BOLD_ON if layout.bold_items else b"")
        out += escpos.wrapped(head, item_cols)
        out += (escpos.BOLD_OFF if layout.bold_items else b"") + layout.normal
        choices = item.get("options")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, str) and choice:
                    out += escpos.wrapped(f"  + {choice}", body)
        allergens = _text(item.get("allergens"))
        if allergens and options.show("ticket_show_allergens"):
            out += escpos.emphasised(f"  ALLERGENS: {allergens}")
        out += _note_block(item.get("note"), body, label="note", indent="  ")

    order_note = payload.get("note")
    if isinstance(order_note, str) and order_note.strip():
        out += escpos.rule(body, layout.rule_char)
        out += _note_block(order_note, body, label="ORDER NOTE")
    out += layout.epilogue
    return bytes(out) * layout.copies


def _nonzero(value: Any) -> bool:
    return value is not None and str(value) not in ("", "0", "0.00", "-0.00")


def _half(rate: Any) -> str:
    try:
        return f"{float(str(rate)) / 2:g}"
    except ValueError:
        return "?"


def render_bill(payload: dict[str, Any], *, width: int, layout: Layout) -> bytes:
    """A customer's bill for ONE store order. Totals are the server's strings, not numbers
    reformatted here, so the paper can never disagree with what was charged."""
    options = Options.from_payload(payload)
    cols = layout.cols(width)
    rule = escpos.rule(cols, layout.rule_char)
    money = options.money
    big = lambda text: escpos.big(text, layout.heading, layout.normal)  # noqa: E731

    out = bytearray(layout.prologue)
    out += _header_block(payload.get("header"), layout, options, width)
    out += big(options.label("bill_title", "BILL"))
    copy = _int(payload.get("copy_number"))
    if copy and copy > 1:
        out += big(f"COPY {copy}")

    number = _int(payload.get("order_no"))
    out += escpos.centered(
        f"{options.label('order_label', 'Order')} #{number}" if number else "Order #???"
    )
    gstin = _text(payload.get("gstin"))
    if gstin:
        out += escpos.centered(options.label("tax_invoice_title", "TAX INVOICE"))
        out += escpos.centered(f"GSTIN: {gstin}")
    fssai = _text(payload.get("fssai"))
    if fssai:
        out += escpos.centered(f"FSSAI: {fssai}")
    invoice = _text(payload.get("invoice_no"))
    if invoice and options.show("show_invoice_no"):
        out += escpos.centered(f"Bill No: {invoice}")
    when = _text(payload.get("date"))
    if when and options.show("show_date"):
        out += escpos.centered(when)
    customer = _text(payload.get("customer_name"))
    if customer and options.on("show_customer"):
        out += escpos.centered(customer)
    out += rule

    lines = payload.get("lines")
    numbered = options.on("show_item_numbers")
    for index, item in enumerate(
        (i for i in (lines if isinstance(lines, list) else []) if isinstance(i, dict)), 1
    ):
        quantity, name = item.get("quantity"), item.get("name")
        left = f"{quantity} x {name}" if quantity is not None else str(name)
        if numbered:
            left = f"{index}. {left}"
        out += escpos.columns(left, money(item.get("line_total", "")), cols)
        choices = item.get("options")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, str) and choice:
                    out += escpos.line(f"    + {choice}")
        unit = item.get("unit_price")
        if (
            isinstance(quantity, int)
            and quantity > 1
            and unit is not None
            and options.show("show_unit_price")
        ):
            out += escpos.line(f"    @ {money(unit)}")
        if options.show("show_item_notes"):
            out += _note_block(item.get("note"), cols, label="note", indent="    ")

    out += rule
    out += escpos.columns(
        options.label("subtotal_label", "Subtotal"),
        money(payload.get("subtotal", "")),
        cols,
    )
    if options.show("show_tax_breakdown"):
        tax_lines = payload.get("tax_lines")
        if isinstance(tax_lines, list) and tax_lines:
            for row in tax_lines:
                if isinstance(row, dict) and _nonzero(row.get("cgst")):
                    half = _half(row.get("rate"))
                    out += escpos.columns(f"CGST @{half}%", money(row.get("cgst", "")), cols)
                    out += escpos.columns(f"SGST @{half}%", money(row.get("sgst", "")), cols)
            if payload.get("prices_include_tax"):
                out += escpos.line("(prices include GST)")
    total_cols = layout.cols(width, layout.text_width)
    out += escpos.BOLD_ON + escpos.scale(layout.text_width, layout.text_height * 2)
    out += escpos.columns(
        options.label("total_label", "TOTAL"), money(payload.get("total", "")), total_cols
    )
    out += layout.normal + escpos.BOLD_OFF

    footer = _text(payload["footer"]) if "footer" in payload else "Thank you"
    if footer:
        out += (
            escpos.feed(1) + escpos.ALIGN_CENTER + escpos.wrapped(footer, cols) + escpos.ALIGN_LEFT
        )
    out += layout.epilogue
    return bytes(out) * layout.copies + layout.drawer


def render_test(payload: dict[str, Any], *, width: int, layout: Layout) -> bytes:
    """A test page: proves the connection, shows the width in use and a sample line."""
    cols = layout.cols(width)
    out = bytearray(layout.prologue)
    out += escpos.big("TEST PRINT", layout.heading, layout.normal)
    out += escpos.centered(_text(payload.get("store")) or "MallT")
    out += escpos.centered(_text(payload.get("printer_name")))
    out += escpos.rule(cols, layout.rule_char)
    ruler = ("1234567890" * 10)[:cols]
    out += escpos.line(ruler)
    out += escpos.line(f"{cols} characters per line")
    out += escpos.columns("2 x Sample item", "240.00", cols)
    out += escpos.rule(cols, layout.rule_char)
    out += escpos.centered("If you can read this, printing works.")
    out += layout.epilogue
    return bytes(out)


def render(job: dict[str, Any], *, width: int) -> bytes:
    """Whichever kind this job is. The frame's own ``kind`` wins over the payload's copy."""
    payload = job.get("payload")
    if not isinstance(payload, dict):
        raise UnknownPayload("job carries no payload object")
    kind = job.get("kind") or payload.get("kind")
    layout = Layout.from_job(job)
    if kind == "ticket":
        return render_ticket(payload, width=width, layout=layout)
    if kind == "bill":
        return render_bill(payload, width=width, layout=layout)
    if kind == "test":
        return render_test(payload, width=width, layout=layout)
    raise UnknownPayload(f"unknown payload kind {kind!r}")
