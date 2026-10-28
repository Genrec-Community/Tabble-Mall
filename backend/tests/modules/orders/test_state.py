from mallt.modules.orders.enums import StoreOrderStatus as S
from mallt.modules.orders.state import OPEN_STATES, REFUND_STATES, TRANSITIONS, can_transition

ALLOWED = {
    (S.PENDING_PAYMENT, S.PAID),
    (S.PENDING_PAYMENT, S.PAYMENT_FAILED),
    (S.PAID, S.ACCEPTED),
    (S.PAID, S.REJECTED),
    (S.PAID, S.EXPIRED),
    (S.PAID, S.CANCELLED),
    (S.ACCEPTED, S.PREPARING),
    (S.ACCEPTED, S.CANCELLED),
    (S.PREPARING, S.READY),
    (S.PREPARING, S.CANCELLED),
    (S.READY, S.PICKED_UP),
    (S.READY, S.CANCELLED),
    (S.REJECTED, S.REFUNDED),
    (S.EXPIRED, S.REFUNDED),
    (S.CANCELLED, S.REFUNDED),
}


def test_every_pair_is_allowed_or_refused_exactly_as_specified() -> None:
    for a in S:
        for b in S:
            assert can_transition(a, b) == ((a, b) in ALLOWED), (a, b)


def test_every_status_has_an_entry_and_terminals_have_no_exits() -> None:
    assert set(TRANSITIONS) == set(S)
    for terminal in (S.PICKED_UP, S.REFUNDED, S.PAYMENT_FAILED):
        assert not TRANSITIONS[terminal]


def test_refund_and_open_sets() -> None:
    assert REFUND_STATES == {S.REJECTED, S.EXPIRED, S.CANCELLED}
    assert OPEN_STATES == {S.PAID, S.ACCEPTED, S.PREPARING, S.READY}
