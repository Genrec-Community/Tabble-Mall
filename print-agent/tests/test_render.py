"""What ends up on paper. `plain()` strips the control bytes this codebase emits so tests can
assert on the words; test_escpos.py covers the bytes themselves."""

from __future__ import annotations

import base64

import pytest

from print_agent import escpos, render
from print_agent.layout import Layout, Options

pytestmark = pytest.mark.unit

WIDTH = 32
_CONTROLS = sorted(
    (
        escpos.INIT,
        escpos.SELECT_CP437,
        escpos.ALIGN_CENTER,
        escpos.ALIGN_LEFT,
        escpos.BOLD_ON,
        escpos.BOLD_OFF,
        escpos.DOUBLE,
        escpos.DOUBLE_HEIGHT,
        escpos.NORMAL,
        escpos.CUT,
        escpos.CUT_FULL,
        escpos.FONT_B,
        escpos.BEEP,
        escpos.DRAWER_KICK,
    ),
    key=len,
    reverse=True,
)


def plain(data: bytes) -> str:
    out = data
    for sequence in _CONTROLS:
        out = out.replace(sequence, b"")
    while (at := out.find(escpos.ESC + b"d")) != -1:
        out = out[:at] + out[at + 3 :]
    while (at := out.find(escpos.GS + b"!")) != -1:  # any size command
        out = out[:at] + out[at + 3 :]
    return out.decode("cp437")


def ticket(**over) -> dict:
    payload = {
        "kind": "ticket",
        "order_id": "o1",
        "order_no": 12,
        "store": "Burger Hub",
        "time": "18:05",
        "eta_minutes": 15,
        "customer_name": "Asha",
        "note": None,
        "revision": 0,
        "items": [
            {
                "name": "Cheese Burger (Large)",
                "quantity": 2,
                "options": ["Extra cheese"],
                "note": "no onion",
                "allergens": "milk",
            },
            {
                "name": "Cold Coffee",
                "quantity": 1,
                "options": [],
                "note": None,
                "allergens": None,
            },
        ],
        "options": {},
    }
    payload.update(over)
    return payload


def bill(**over) -> dict:
    payload = {
        "kind": "bill",
        "order_id": "o1",
        "order_no": 12,
        "invoice_no": "261028-0012",
        "date": "28-10-2026 18:05",
        "customer_name": "Asha",
        "copy_number": 1,
        "gstin": "27AAPFU0939F1ZV",
        "fssai": "11223344556677",
        "header": {
            "name": "Burger Hub",
            "address": "Shop 4, Phoenix Mall",
            "phone": "9876543210",
            "extra": None,
            "logo": None,
        },
        "footer": "See you again!",
        "lines": [
            {
                "name": "Cheese Burger (Large)",
                "quantity": 2,
                "unit_price": "200.00",
                "line_total": "400.00",
                "options": ["Extra cheese"],
                "note": "no onion",
            },
            {
                "name": "Cold Coffee",
                "quantity": 1,
                "unit_price": "120.00",
                "line_total": "120.00",
                "options": [],
                "note": None,
            },
        ],
        "subtotal": "520.00",
        "tax_lines": [
            {"rate": "5.00", "taxable": "380.95", "cgst": "9.52", "sgst": "9.53"},
            {"rate": "12.00", "taxable": "107.14", "cgst": "6.43", "sgst": "6.43"},
        ],
        "prices_include_tax": True,
        "total": "520.00",
        "options": {},
    }
    payload.update(over)
    return payload


def job(kind: str, payload: dict, layout: dict | None = None) -> dict:
    out = {"kind": kind, "payload": payload}
    if layout is not None:
        out["layout"] = layout
    return out


def paper(kind: str, payload: dict, layout: dict | None = None, width: int = WIDTH) -> str:
    return plain(render.render(job(kind, payload, layout), width=width))


# ---------------------------------------------------------------- the kitchen ticket


def test_ticket_leads_with_the_order_number_and_lists_items_with_choices() -> None:
    text = paper("ticket", ticket())
    assert "#12" in text and "Burger Hub" in text and "18:05" in text
    assert "Ready in about 15 min" in text and "Asha" in text
    assert "2 x Cheese Burger (Large)" in text and "+ Extra cheese" in text
    assert "note: no onion" in text and "ALLERGENS: milk" in text
    assert "1 x Cold Coffee" in text


def test_a_ticket_carries_no_money_and_no_pickup_code() -> None:
    text = paper("ticket", ticket())
    assert (
        "Rs" not in text
        and "₹" not in text
        and "TOTAL" not in text
        and "." not in text.replace("...", "")
    )
    assert "pickup" not in text.lower() and "code" not in text.lower()


def test_reprints_say_so_and_empty_tickets_still_print() -> None:
    assert "REPRINT #2" in paper("ticket", ticket(revision=2))
    assert "REPRINT" not in paper("ticket", ticket(revision=0))
    assert "no items" in paper("ticket", ticket(items=[]))
    assert "#???" in paper("ticket", ticket(order_no=None))


def test_ticket_options_hide_lines_and_rename_the_title() -> None:
    opts = {
        "ticket_show_store": False,
        "ticket_show_time": False,
        "ticket_show_eta": False,
        "ticket_show_customer": False,
        "ticket_show_allergens": False,
        "ticket_title": "KOT",
    }
    text = paper("ticket", ticket(options=opts))
    assert "KOT" in text and "Burger Hub" not in text and "18:05" not in text
    assert "Ready in" not in text and "Asha" not in text and "ALLERGENS" not in text


def test_long_names_wrap_inside_the_paper_width() -> None:
    long = ticket(items=[{"name": "Extra Large Triple Decker Spicy Chicken Burger", "quantity": 1}])
    for line in paper("ticket", long).splitlines():
        assert len(line) <= WIDTH


# ---------------------------------------------------------------- the bill


def test_bill_shows_header_gst_lines_tax_split_and_total() -> None:
    text = paper("bill", bill())
    for expected in (
        "Burger Hub",
        "Shop 4, Phoenix Mall",
        "Ph: 9876543210",
        "BILL",
        "Order #12",
        "TAX INVOICE",
        "GSTIN: 27AAPFU0939F1ZV",
        "FSSAI: 11223344556677",
        "Bill No: 261028-0012",
        "2 x Cheese Burger (Large)",
        "400.00",
        "+ Extra cheese",
        "@ 200.00",
        "Subtotal",
        "CGST @2.5%",
        "9.52",
        "SGST @2.5%",
        "9.53",
        "CGST @6%",
        "(prices include GST)",
        "TOTAL",
        "520.00",
        "See you again!",
    ):
        assert expected in text, expected


def test_bill_without_gstin_is_not_a_tax_invoice_and_totals_are_verbatim() -> None:
    text = paper("bill", bill(gstin=None, fssai=None))
    assert "TAX INVOICE" not in text and "GSTIN" not in text and "FSSAI" not in text
    assert "520.00" in text


def test_second_copy_is_marked_and_first_is_not() -> None:
    assert "COPY 2" in paper("bill", bill(copy_number=2))
    assert "COPY" not in paper("bill", bill(copy_number=1))


def test_bill_options_rename_hide_and_prefix() -> None:
    opts = {
        "bill_title": "TAX BILL",
        "total_label": "PAY",
        "subtotal_label": "Sub",
        "show_unit_price": False,
        "show_item_notes": False,
        "show_tax_breakdown": False,
        "show_invoice_no": False,
        "show_date": False,
        "show_customer": True,
        "show_item_numbers": True,
        "currency_symbol": "Rs",
        "order_label": "Token",
    }
    text = paper("bill", bill(options=opts))
    assert "TAX BILL" in text and "PAY" in text and "Sub" in text and "Token #12" in text
    assert "@ 200.00" not in text and "note:" not in text and "CGST" not in text
    assert "Bill No" not in text and "28-10-2026" not in text and "Asha" in text
    assert "1. 2 x Cheese" in text and "Rs520.00" in text


def test_footer_semantics_absent_blank_and_custom() -> None:
    no_footer = bill()
    del no_footer["footer"]
    assert "Thank you" in paper("bill", no_footer)  # key absent -> the standing default
    assert "See you again!" not in paper("bill", bill(footer=""))  # blank -> none
    assert "Thank you" not in paper("bill", bill(footer=None))
    assert "Come back soon" in paper("bill", bill(footer="Come back soon"))


def test_logo_is_printed_only_when_well_formed() -> None:
    rows = b"\xff" * 16  # 16 dots wide x 8 rows
    good = {"width": 16, "height": 8, "data": base64.b64encode(rows).decode()}
    assert escpos.GS + b"v0" in render.render(
        job("bill", bill(header={"name": "X", "logo": good})), width=WIDTH
    )
    for broken in (
        {**good, "data": "!!!notbase64"},
        {**good, "data": base64.b64encode(b"\xff" * 3).decode()},  # wrong length
        {**good, "width": 9999},
        {**good, "width": True},
        "garbage",
    ):
        data = render.render(job("bill", bill(header={"name": "X", "logo": broken})), width=WIDTH)
        assert escpos.GS + b"v0" not in data  # skipped, bill still printed
        assert "BILL" in plain(data)
    hidden = render.render(
        job("bill", bill(header={"name": "X", "logo": good}, options={"show_logo": False})),
        width=WIDTH,
    )
    assert escpos.GS + b"v0" not in hidden


# ---------------------------------------------------------------- test page and dispatch


def test_test_page_reports_width_and_proves_the_connection() -> None:
    text = paper(
        "test",
        {"kind": "test", "store": "Burger Hub", "printer_name": "Counter"},
        width=48,
    )
    assert "TEST PRINT" in text and "Burger Hub" in text and "Counter" in text
    assert "48 characters per line" in text and "printing works" in text


def test_unknown_kinds_and_missing_payloads_are_refused() -> None:
    with pytest.raises(render.UnknownPayload):
        render.render({"kind": "poster", "payload": {}}, width=WIDTH)
    with pytest.raises(render.UnknownPayload):
        render.render({"kind": "bill"}, width=WIDTH)
    # the payload's own kind is the fallback when the frame has none
    assert "BILL" in plain(render.render({"payload": bill()}, width=WIDTH))


def test_garbage_fields_never_break_a_slip() -> None:
    odd = ticket(
        items=[None, "x", {"name": None, "quantity": None, "options": "nope"}],
        store=7,
        eta_minutes="soon",
        time=None,
        customer_name=[],
        note=5,
        revision="two",
    )
    assert "ORDER" in paper("ticket", odd)
    odd_bill = bill(
        lines=[None, {"name": "A", "quantity": "many"}],
        tax_lines="x",
        header=5,
        subtotal=None,
        options="bad",
    )
    assert "TOTAL" in paper("bill", odd_bill)


# ---------------------------------------------------------------- layout and options objects


def test_defaults_are_unchanged_when_layout_is_empty_or_absent() -> None:
    for kind, payload in (("ticket", ticket()), ("bill", bill())):
        assert render.render(job(kind, payload), width=WIDTH) == render.render(
            job(kind, payload, {}), width=WIDTH
        )


def test_layout_of_the_wrong_shape_falls_back() -> None:
    layout = Layout.from_job(
        {"layout": {"copies": "two", "font": "z", "item_height": 99, "cut": None}}
    )
    assert layout == Layout() and Layout.from_job({"layout": "nonsense"}) == Layout()


def test_layout_reaches_the_printer() -> None:
    data = render.render(
        job(
            "ticket",
            ticket(),
            {
                "font": "b",
                "line_spacing": 40,
                "left_margin": 24,
                "beep": True,
                "print_width_dots": 400,
                "item_height": 3,
            },
        ),
        width=WIDTH,
    )
    assert escpos.FONT_B in data and escpos.BEEP in data
    assert escpos.line_spacing(40) in data and escpos.left_margin(24) in data
    assert escpos.print_width(400) in data and escpos.scale(1, 3) in data


def test_copies_cut_feed_and_drawer() -> None:
    once = render.render(job("ticket", ticket()), width=WIDTH)
    assert render.render(job("ticket", ticket(), {"copies": 3}), width=WIDTH) == once * 3
    assert escpos.CUT_FULL in render.render(job("ticket", ticket(), {"cut": "full"}), width=WIDTH)
    none = render.render(job("ticket", ticket(), {"cut": "none"}), width=WIDTH)
    assert escpos.CUT not in none and escpos.CUT_FULL not in none
    assert escpos.feed(7) in render.render(job("ticket", ticket(), {"feed_after": 7}), width=WIDTH)
    assert render.render(job("bill", bill(), {"open_drawer": True}), width=WIDTH).endswith(
        escpos.DRAWER_KICK
    )
    assert escpos.DRAWER_KICK not in render.render(
        job("ticket", ticket(), {"open_drawer": True}), width=WIDTH
    )


def test_double_width_text_halves_the_columns_so_lines_still_fit() -> None:
    layout = Layout.from_job({"layout": {"text_width": 2}})
    assert layout.cols(32) == 16 and layout.cols(32, 1) == 32


def test_options_object_reads_leniently() -> None:
    o = Options.from_payload(
        {
            "options": {
                "a": True,
                "b": "yes",
                "label": "  Hello   World ",
                "currency_symbol": " ₹ ",
            }
        }
    )
    assert o.show("a") and o.show("missing") and o.show("b")  # non-bool -> default True
    assert not o.on("missing") and o.on("a")
    assert o.label("label", "x") == "Hello World" and o.label("none", "dflt") == "dflt"
    assert o.money("5.00") == "₹5.00"
    assert Options.from_payload({"options": 5}).raw == {}
