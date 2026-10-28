from enum import StrEnum


class Diet(StrEnum):
    VEG = "veg"
    NONVEG = "nonveg"
    EGG = "egg"


class StockMode(StrEnum):
    MANUAL = "manual"  # available / sold-out toggle (kitchens)
    COUNTED = "counted"  # reserved at checkout, committed on payment, released on failure


# Mall discovery categories: a fixed list so the QR page can group stores.
FOOD_TYPES = (
    "fast_food",
    "meals",
    "snacks",
    "beverages",
    "desserts",
    "bakery",
    "healthy",
    "chinese",
    "south_indian",
    "north_indian",
)

PRINT_KOT_WHEN = ("paid", "accepted")
PRINT_BILL_WHEN = ("accepted", "ready", "picked_up", "manual")
