import uuid
from datetime import UTC, date, datetime

from mallt.core.tax import tax_split
from mallt.modules.printing.payloads import bill_payload, money, ticket_payload
from mallt.modules.printing.types import PrintableLine, PrintableOrder, PrintPrefs

PREFS = PrintPrefs(True, "accepted", "ready", "27AAPFU0939F1ZV", "11223344556677", "Asia/Kolkata")


def order() -> PrintableOrder:
    lines = [
        PrintableLine(
            "Cheese Burger", "Large", 2, 20000, 40000, 500, ["Extra cheese"], "no onion", "milk"
        ),
        PrintableLine("Cold Coffee", "Regular", 1, 12000, 12000, 1200),
    ]
    return PrintableOrder(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        mall_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        store_name="Burger Hub",
        order_no=7,
        order_date=date(2026, 10, 28),
        created_at=datetime(2026, 10, 28, 12, 30, tzinfo=UTC),
        customer_name="Asha",
        prep_minutes=15,
        note="hurry",
        subtotal_paise=52000,
        tax_paise=2000,
        total_paise=52000,
        lines=lines,
    )


def test_money_formats_paise() -> None:
    assert [money(p) for p in (0, 5, 100, 12345, -250)] == [
        "0.00",
        "0.05",
        "1.00",
        "123.45",
        "-2.50",
    ]


def test_tax_split_always_adds_up() -> None:
    for total in (1, 99, 12000, 12345, 999_999):
        for bps in (0, 250, 500, 1200, 1800):
            s = tax_split(total, bps)
            assert s.cgst + s.sgst == s.total and s.sgst - s.cgst in (0, 1)


def test_ticket_has_no_money_and_no_pickup_code() -> None:
    p = ticket_payload(order(), PREFS, {})
    flat = str(p)
    for forbidden in ("price", "total", "paise", "pickup", "tax", "subtotal"):
        assert forbidden not in flat.lower(), forbidden
    assert p["order_no"] == 7 and p["time"] == "18:00" and p["eta_minutes"] == 15
    assert p["items"][0] == {
        "name": "Cheese Burger (Large)",
        "quantity": 2,
        "options": ["Extra cheese"],
        "note": "no onion",
        "allergens": "milk",
    }


def test_bill_totals_tax_groups_and_no_commission() -> None:
    p = bill_payload(
        order(), PREFS, {"name": "Burger Hub"}, "Thanks!", {}, copy_number=1, logo=None
    )
    assert p["total"] == "520.00" and p["subtotal"] == "520.00" and p["prices_include_tax"] is True
    assert [t["rate"] for t in p["tax_lines"]] == ["5.00", "12.00"]
    five = p["tax_lines"][0]
    assert five["taxable"] == "380.95" and five["cgst"] == "9.52" and five["sgst"] == "9.53"
    assert p["invoice_no"] == "261028-0007" and p["gstin"] == "27AAPFU0939F1ZV"
    assert "commission" not in str(p).lower()
    assert p["lines"][0]["unit_price"] == "200.00" and p["lines"][0]["line_total"] == "400.00"
