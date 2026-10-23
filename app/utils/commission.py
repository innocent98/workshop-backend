from decimal import Decimal, ROUND_HALF_UP


MONEY_QUANT = Decimal("0.01")


def calculate_platform_fee(gross_amount: Decimal, commission_percent: Decimal) -> Decimal:
    gross = Decimal(gross_amount or 0)
    percent = Decimal(commission_percent or 0)
    fee = (gross * percent / Decimal("100")).quantize(
        MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )
    return fee


def calculate_artisan_amount(gross_amount: Decimal, commission_percent: Decimal) -> Decimal:
    gross = Decimal(gross_amount or 0)
    fee = calculate_platform_fee(gross, commission_percent)
    return (gross - fee).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
