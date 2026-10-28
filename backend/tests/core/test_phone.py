import pytest

from mallt.core.errors import Unprocessable
from mallt.core.phone import mask_phone, normalize_in_phone


@pytest.mark.parametrize(
    "raw",
    [
        "+91 93618 99061",
        "09361899061",
        "919361899061",
        "9361899061",
        " 93618-99061 ",
        "+919361899061",
    ],
)
def test_all_common_formats_normalise_to_ten_digits(raw: str) -> None:
    assert normalize_in_phone(raw) == "9361899061"


@pytest.mark.parametrize(
    "raw", ["12345", "5361899061", "", "93618990612", "abcdefghij", "+1 9361899061", "91936189906"]
)
def test_invalid_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(Unprocessable) as e:
        normalize_in_phone(raw)
    assert e.value.code == "invalid_phone"


def test_mask_phone() -> None:
    assert mask_phone("9361899061") == "******9061"
