import re

from mallt.core.errors import Unprocessable

_NOISE = re.compile(r"[\s\-().]")
_INDIAN_MOBILE = re.compile(r"[6-9]\d{9}")


def normalize_in_phone(raw: str) -> str:
    """Return the 10-digit Indian mobile number for any common way of writing it."""
    digits = _NOISE.sub("", raw)
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not _INDIAN_MOBILE.fullmatch(digits):
        raise Unprocessable("invalid_phone", "Enter a valid 10-digit Indian mobile number.")
    return digits


def mask_phone(phone: str) -> str:
    return "*" * (len(phone) - 4) + phone[-4:]
