from enum import StrEnum


class StoreOrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PAYMENT_FAILED = "payment_failed"


class CustomerOrderStatus(StrEnum):
    PLACED = "placed"  # created, awaiting payment
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"


class FulfilmentType(StrEnum):
    PICKUP = "pickup"  # the only value allowed in v1
