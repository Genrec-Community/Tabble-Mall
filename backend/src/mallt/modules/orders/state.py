"""The store-order state machine. Pure: the table below is the only source of truth."""

from mallt.modules.orders.enums import StoreOrderStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING_PAYMENT: frozenset({S.PAID, S.PAYMENT_FAILED}),
    S.PAID: frozenset({S.ACCEPTED, S.REJECTED, S.EXPIRED, S.CANCELLED}),
    S.ACCEPTED: frozenset({S.PREPARING, S.CANCELLED}),
    S.PREPARING: frozenset({S.READY, S.CANCELLED}),
    S.READY: frozenset({S.PICKED_UP, S.CANCELLED}),
    S.REJECTED: frozenset({S.REFUNDED}),
    S.EXPIRED: frozenset({S.REFUNDED}),
    S.CANCELLED: frozenset({S.REFUNDED}),
    S.PICKED_UP: frozenset(),
    S.REFUNDED: frozenset(),
    S.PAYMENT_FAILED: frozenset(),
}

# States that need money returned and held stock released.
REFUND_STATES = frozenset({S.REJECTED, S.EXPIRED, S.CANCELLED})
# "Open" = the store still has to do something (used for pickup-code uniqueness).
OPEN_STATES = frozenset({S.PAID, S.ACCEPTED, S.PREPARING, S.READY})
# A customer may cancel only before the store accepts.
CUSTOMER_CANCELLABLE = frozenset({S.PAID})


def can_transition(current: S, target: S) -> bool:
    return target in TRANSITIONS[current]
