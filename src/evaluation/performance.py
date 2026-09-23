"""Performance measures used by the current accounting baseline."""

from decimal import Decimal


def return_pct(equity: Decimal, initial_cash: Decimal) -> Decimal:
    """Return the percentage change from positive initial capital."""
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    return (equity / initial_cash - 1) * 100
