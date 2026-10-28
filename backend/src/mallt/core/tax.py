"""GST arithmetic shared by orders and printing. Integer paise only."""

from dataclasses import dataclass


def tax_included(total_paise: int, tax_bps: int) -> int:
    """The GST contained in a GST-inclusive amount, rounded half up."""
    divisor = 10_000 + tax_bps
    return (total_paise * tax_bps + divisor // 2) // divisor


@dataclass(frozen=True)
class TaxSplit:
    total: int
    cgst: int
    sgst: int


def tax_split(total_paise: int, tax_bps: int) -> TaxSplit:
    """The tax inside an inclusive amount, split into CGST and SGST (they always add up)."""
    tax = tax_included(total_paise, tax_bps)
    cgst = tax // 2
    return TaxSplit(total=tax, cgst=cgst, sgst=tax - cgst)
