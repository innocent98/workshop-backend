from decimal import Decimal

import pytest

from app.utils.commission import calculate_artisan_amount, calculate_platform_fee


@pytest.mark.parametrize(
    "gross,percent,fee,artisan",
    [
        ("10000.00", "10.00", "1000.00", "9000.00"),
        ("5000.00", "10.00", "500.00", "4500.00"),
        ("3333.33", "10.00", "333.33", "3000.00"),
        ("1234.56", "10.00", "123.46", "1111.10"),  # fee rounds half-up
        ("10000.00", "0", "0.00", "10000.00"),
    ],
)
def test_split(gross, percent, fee, artisan):
    gross, percent = Decimal(gross), Decimal(percent)
    assert calculate_platform_fee(gross, percent) == Decimal(fee)
    assert calculate_artisan_amount(gross, percent) == Decimal(artisan)


def test_fee_plus_artisan_equals_gross():
    for gross in ("999.99", "1.01", "250000.55"):
        g = Decimal(gross)
        p = Decimal("10.00")
        assert calculate_platform_fee(g, p) + calculate_artisan_amount(g, p) == g
