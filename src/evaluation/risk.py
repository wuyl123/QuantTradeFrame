"""Drawdown measures used by the current accounting baseline."""

from decimal import Decimal


def drawdown_pct(equity: Decimal, peak_equity: Decimal) -> Decimal:
    """Return the percentage decline from a positive running equity peak."""
    if peak_equity <= 0:
        raise ValueError("peak_equity must be positive")
    if equity > peak_equity:
        raise ValueError("peak_equity must include the current equity")
    return (peak_equity - equity) / peak_equity * 100
