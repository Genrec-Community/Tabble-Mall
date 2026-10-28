"""Money arithmetic in integer paise. Prices are GST-inclusive."""


def tax_included(total_paise: int, tax_bps: int) -> int:
    """The GST contained in a GST-inclusive amount, rounded half up."""
    divisor = 10_000 + tax_bps
    return (total_paise * tax_bps + divisor // 2) // divisor


def commission(total_paise: int, commission_bps: int) -> int:
    """MallT's cut of an amount, rounded half up."""
    return (total_paise * commission_bps + 5_000) // 10_000
