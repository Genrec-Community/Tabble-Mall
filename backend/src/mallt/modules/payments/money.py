"""Paise <-> the rupee strings Zoho speaks. Integer arithmetic only: no float, no Decimal maths."""

import re

_RUPEES = re.compile(r"^\s*(-?)(\d+)(?:\.(\d{1,2})\d*)?\s*$")


def to_rupees(paise: int) -> str:
    """12345 -> "123.45"."""
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    return f"{sign}{paise // 100}.{paise % 100:02d}"


def to_paise(value: str | int | float) -> int:
    """ "123.45" / "₹123.45" / 123.45 -> 12345. Digits past the second decimal are dropped."""
    text = str(value).replace("₹", "").replace(",", "")
    match = _RUPEES.match(text)
    if match is None:
        raise ValueError(f"not a rupee amount: {value!r}")
    sign, whole, frac = match.groups()
    paise = int(whole) * 100 + int((frac or "0").ljust(2, "0"))
    return -paise if sign else paise
