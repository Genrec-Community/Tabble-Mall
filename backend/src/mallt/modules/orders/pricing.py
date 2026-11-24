"""Money arithmetic in integer paise. Prices are GST-inclusive."""

from mallt.core.tax import tax_included

__all__ = ["gateway_fee", "store_payout", "tax_included"]


def gateway_fee(total_paise: int, fee_bps: int) -> int:
    """The gateway fee a store bears on its own share, rounded half up."""
    return (total_paise * fee_bps + 5_000) // 10_000


def store_payout(total_paise: int, gateway_fee_paise: int) -> int:
    """What the store receives: its whole share minus its own gateway fee. MallT keeps nothing."""
    return max(0, total_paise - gateway_fee_paise)
