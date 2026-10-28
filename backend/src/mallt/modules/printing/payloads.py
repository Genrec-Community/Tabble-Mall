"""Structured print payloads. The agent turns these into ESC/POS; nothing here is printer-specific.

A kitchen ticket carries no prices and no pickup code (the code is the customer's proof of
purchase: if the store could read it, it could mark orders picked up without the customer).
A bill belongs to ONE store order: never commission, never another store's lines.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mallt.core.tax import tax_split
from mallt.modules.printing.types import PrintableOrder, PrintPrefs


def money(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    whole, frac = divmod(abs(paise), 100)
    return f"{sign}{whole}.{frac:02d}"


def _local(order: PrintableOrder, prefs: PrintPrefs) -> datetime:
    return order.created_at.astimezone(ZoneInfo(prefs.timezone))


def ticket_payload(
    order: PrintableOrder, prefs: PrintPrefs, options: dict[str, Any], *, revision: int = 0
) -> dict[str, Any]:
    return {
        "kind": "ticket",
        "order_id": str(order.id),
        "order_no": order.order_no,
        "store": order.store_name,
        "time": _local(order, prefs).strftime("%H:%M"),
        "eta_minutes": order.prep_minutes,
        "customer_name": order.customer_name,
        "note": order.note,
        "revision": revision,
        "items": [
            {
                "name": f"{ln.name} ({ln.variant_name})" if ln.variant_name else ln.name,
                "quantity": ln.quantity,
                "options": ln.options,
                "note": ln.note,
                "allergens": ln.allergens,
            }
            for ln in order.lines
        ],
        "options": options,
    }


def bill_payload(
    order: PrintableOrder,
    prefs: PrintPrefs,
    header: dict[str, Any],
    footer: str | None,
    options: dict[str, Any],
    *,
    copy_number: int,
    logo: dict[str, Any] | None,
) -> dict[str, Any]:
    local = _local(order, prefs)
    groups: dict[int, int] = {}
    for ln in order.lines:
        groups[ln.tax_bps] = groups.get(ln.tax_bps, 0) + ln.line_total_paise
    tax_lines = []
    for bps in sorted(groups):
        tax = tax_split(groups[bps], bps)
        tax_lines.append(
            {
                "rate": f"{bps / 100:.2f}",
                "taxable": money(groups[bps] - tax.total),
                "cgst": money(tax.cgst),
                "sgst": money(tax.sgst),
            }
        )
    return {
        "kind": "bill",
        "order_id": str(order.id),
        "order_no": order.order_no,
        "invoice_no": f"{order.order_date:%y%m%d}-{order.order_no:04d}",
        "date": local.strftime("%d-%m-%Y %H:%M"),
        "customer_name": order.customer_name,
        "copy_number": copy_number,
        "gstin": prefs.gstin,
        "fssai": prefs.fssai,
        "header": {**header, "logo": logo},
        "footer": footer,
        "lines": [
            {
                "name": f"{ln.name} ({ln.variant_name})" if ln.variant_name else ln.name,
                "quantity": ln.quantity,
                "unit_price": money(ln.unit_price_paise),
                "line_total": money(ln.line_total_paise),
                "options": ln.options,
                "note": ln.note,
            }
            for ln in order.lines
        ],
        "subtotal": money(order.subtotal_paise),
        "tax_lines": tax_lines,
        "prices_include_tax": True,
        "total": money(order.total_paise),
        "options": options,
    }


def test_payload(printer_name: str, store_name: str, paper_width: int) -> dict[str, Any]:
    return {
        "kind": "test",
        "printer_name": printer_name,
        "store": store_name,
        "paper_width": paper_width,
    }
