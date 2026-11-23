from mallt.modules.orders.pricing import gateway_fee, store_payout, tax_included


def test_tax_included_in_a_gst_inclusive_price() -> None:
    assert tax_included(10_500, 500) == 500  # 10,500 = 10,000 + 5%
    assert tax_included(12_000, 500) == 571  # 571.43 rounds down
    assert tax_included(12_100, 500) == 576  # 576.19
    assert tax_included(0, 500) == 0
    assert tax_included(1_000, 0) == 0
    assert tax_included(11_200, 1_200) == 1_200


def test_each_store_bears_the_gateway_fee_on_its_own_share() -> None:
    # The owner's example: a ₹10,000 cart split ₹5,000 / ₹3,000 / ₹2,000 at 0.50%.
    shares = [500_000, 300_000, 200_000]
    assert [gateway_fee(s, 50) for s in shares] == [2_500, 1_500, 1_000]
    assert sum(gateway_fee(s, 50) for s in shares) == gateway_fee(sum(shares), 50)
    assert gateway_fee(12_345, 50) == 62  # 61.725 rounds half up
    # the store gets its whole share minus its own fee: MallT keeps nothing
    assert store_payout(500_000, 2_500) == 497_500
    assert store_payout(10, 50) == 0  # never negative
