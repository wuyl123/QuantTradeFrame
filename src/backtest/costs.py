"""Illustrative buy-side commission and slippage calculations."""

from decimal import Decimal


def buy_costs(
    reference_open: Decimal,
    shares: int,
    commission_rate: Decimal,
    fixed_fee: Decimal,
    slippage_bps: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return execution price, notional, and fee using validated engine inputs.

    No currency rounding, exchange-specific taxes, or OHLC clipping is applied.
    """
    price = reference_open * (1 + slippage_bps / Decimal(10_000))
    notional = price * shares
    commission = notional * commission_rate + fixed_fee
    return price, notional, commission
