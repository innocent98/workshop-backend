import pytest

from app.db.models.payment import PaymentMethod
from app.services.payment_service import map_paystack_channel


@pytest.mark.parametrize(
    "channel,expected",
    [
        ("card", PaymentMethod.CARD),
        ("bank", PaymentMethod.BANK),
        ("mobile_money", PaymentMethod.MOBILE_MONEY),
        ("qr", PaymentMethod.QR),
        ("eft", PaymentMethod.EFT),
        ("bank_transfer", PaymentMethod.BANK_TRANSFER),
        ("ussd", PaymentMethod.USSD),
        ("apple_pay", PaymentMethod.APPLE_PAY),
        ("CARD", PaymentMethod.CARD),
        (" Bank ", PaymentMethod.BANK),
    ],
)
def test_known_channels(channel, expected):
    assert map_paystack_channel(channel) is expected


@pytest.mark.parametrize("channel", [None, "", "crypto", "something_new", 123])
def test_unknown_channels_fall_back_safely(channel):
    assert map_paystack_channel(channel) is PaymentMethod.OTHER


def test_every_enum_value_fits_the_varchar_20_column():
    assert all(len(m.value) <= 20 for m in PaymentMethod)
