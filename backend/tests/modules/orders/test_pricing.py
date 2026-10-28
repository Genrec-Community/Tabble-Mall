from mallt.modules.orders.pricing import commission, tax_included


def test_tax_included_in_a_gst_inclusive_price() -> None:
    assert tax_included(10_500, 500) == 500  # 10,500 = 10,000 + 5%
    assert tax_included(12_000, 500) == 571  # 571.43 rounds down
    assert tax_included(12_100, 500) == 576  # 576.19
    assert tax_included(0, 500) == 0
    assert tax_included(1_000, 0) == 0
    assert tax_included(11_200, 1_200) == 1_200


def test_commission_rounds_half_up_and_never_goes_negative() -> None:
    assert commission(10_000, 500) == 500
    assert commission(1, 500) == 0
    assert commission(10, 500) == 1  # 0.5 rounds up
    assert commission(3_000, 500) == 150
    assert commission(999_999, 0) == 0
