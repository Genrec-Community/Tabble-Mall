"""Money arithmetic in integer paise. Prices are GST-inclusive."""

from mallt.core.tax import tax_included

__all__ = ["commission", "tax_included"]


def commission(total_paise: int, commission_bps: int) -> int:
    """MallT's cut of an amount, rounded half up."""
    return (total_paise * commission_bps + 5_000) // 10_000
