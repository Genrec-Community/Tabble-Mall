"""The feature switches the platform owner can flip from the owner dashboard. Pure: no I/O.

Add a feature by adding an entry here; no migration is needed. The database only stores the
switches someone has changed, so a key missing from the table uses its ``default``, and rows
for keys no longer listed here are ignored.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDef:
    key: str
    label: str
    description: str
    default: bool
    group: str  # "customers" | "stores" | "featured"


FEATURES: dict[str, FeatureDef] = {
    f.key: f
    for f in (
        # Customer ordering features.
        FeatureDef(
            "mall_qr",
            "Mall-wide QR code",
            "One QR code for the whole mall, to put at the entrance or anywhere.",
            True,
            "customers",
        ),
        FeatureDef(
            "schedule_ahead",
            "Schedule ahead",
            "Customers can order now and pick up later at a time they choose.",
            True,
            "customers",
        ),
        FeatureDef(
            "group_orders",
            "Group orders",
            "Friends share one cart link and each person pays their own share.",
            True,
            "customers",
        ),
        FeatureDef(
            "reviews",
            "Ratings and reviews",
            "Customers rate their food after pickup; ratings feed the Popular section.",
            True,
            "customers",
        ),
        FeatureDef(
            "offers",
            "Offers and coupons",
            "Store coupons and mall-wide combos.",
            True,
            "customers",
        ),
        FeatureDef(
            "pwa",
            "Install as an app",
            "Home-screen icon, push notifications and faster loading.",
            True,
            "customers",
        ),
        FeatureDef(
            "whatsapp",
            "WhatsApp updates",
            "Order confirmations, ready alerts and receipts on WhatsApp instead of SMS.",
            False,
            "customers",
        ),
        # Store tools.
        FeatureDef(
            "auto_sold_out",
            "Sold out for today",
            "Stores mark a dish sold out for the day in one tap; it comes back the next day.",
            True,
            "stores",
        ),
        FeatureDef(
            "sales_reports",
            "Daily sales reports",
            "Best sellers, peak hours, totals and GST invoices for stores and malls.",
            True,
            "stores",
        ),
        # Featured spots (stores pay the mall owner to be shown first).
        FeatureDef(
            "featured_spots",
            "Featured spots",
            "Master switch. When off, no store is shown as featured anywhere.",
            True,
            "featured",
        ),
        FeatureDef(
            "featured_rail",
            "Featured row on the mall home",
            "A small 'Featured' row of store cards above the restaurant list.",
            True,
            "featured",
        ),
        FeatureDef(
            "featured_top_of_list",
            "Featured stores first in the list",
            "Featured stores are listed first among restaurants, with a small 'Featured' tag.",
            False,
            "featured",
        ),
    )
}


def defaults() -> dict[str, bool]:
    return {key: f.default for key, f in FEATURES.items()}
