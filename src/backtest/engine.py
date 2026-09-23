"""Run a single-stock buy-and-hold backtest (python main.py backtest)."""

import argparse
from dataclasses import dataclass, fields
from decimal import Decimal
import math
from numbers import Integral, Real
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest.accounting import BacktestResult, as_float, mark_to_market
from src.backtest.costs import buy_costs
from src.data.loader import INTERVALS, MARKETS, OHLCV_COLUMNS, StockData, load_stock_csv
from src.utils.config import load_strategy_config
from src.utils.paths import BACKTEST_RESULTS_DIR, CONFIG_DIR


@dataclass(frozen=True)
class BacktestConfig:
    """Illustrative costs, in the stock currency; shares is a fixed order size."""

    initial_cash: float = 100_000.0
    shares: int = 100
    commission_rate: float = 0.001
    fixed_fee: float = 0.0
    slippage_bps: float = 0.0

    def __post_init__(self):
        for name in ("initial_cash", "commission_rate", "fixed_fee", "slippage_bps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
            if value < 0 or (name == "initial_cash" and value == 0):
                raise ValueError(f"{name} must be {'positive' if name == 'initial_cash' else 'nonnegative'}")
            object.__setattr__(self, name, float(value))
        if isinstance(self.shares, bool) or not isinstance(self.shares, Integral) or self.shares <= 0:
            raise ValueError("shares must be a positive integer")
        object.__setattr__(self, "shares", int(self.shares))


FILL_COLUMNS = (
    "order_id", "symbol", "side", "bar_timestamp", "phase", "shares",
    "reference_open", "price", "notional", "commission", "slippage_cost", "cash_after",
)


def _validate_stock(stock: StockData) -> pd.Series:
    """Protect accounting when a caller modifies the loader's mutable DataFrame."""
    bars = stock.bars
    if bars.empty or not set(OHLCV_COLUMNS).issubset(bars.columns) or not bars.columns.is_unique:
        raise ValueError("Backtesting requires nonempty bars with unique OHLCV columns")
    if (not isinstance(bars.index, pd.DatetimeIndex) or str(bars.index.tz) != "UTC"
            or bars.index.hasnans or not bars.index.is_unique or not bars.index.is_monotonic_increasing):
        raise ValueError("Bars must have a sorted, unique UTC DatetimeIndex without missing timestamps")
    if stock.metadata.volume_unit != "shares" or stock.metadata.timezone != "UTC":
        raise ValueError("Load data with volume in shares and timestamps in UTC before backtesting")
    numbers = bars.loc[:, list(OHLCV_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(numbers).all() or (numbers[:, :4] <= 0).any() or (numbers[:, 4] < 0).any():
        raise ValueError("OHLCV must be finite, with positive prices and nonnegative volume")
    opening, high, low, close, volume = numbers.T
    if ((low > np.minimum(opening, close)) | (high < np.maximum(opening, close)) | (low > high)).any():
        raise ValueError("Invalid OHLC bounds; use the shared loader to validate input")
    eligible = pd.Series(volume > 0, index=bars.index)
    if "trading_status" in bars:
        status = pd.to_numeric(bars["trading_status"], errors="coerce")
        if not status.isin([0, 1]).all():
            raise ValueError("trading_status must contain only 0 (suspended) or 1 (trading)")
        eligible &= status.eq(1)
    return eligible


def run_buy_and_hold(stock: StockData, config: BacktestConfig | None = None) -> BacktestResult:
    """Submit once at the first close, buy at a later open, and mark each close.

    Zero-volume and suspended bars cannot fill the order. Insufficient cash
    rejects the whole order without fees or later retries. An unfilled order
    expires at the end. Holdings remain open; final equity includes their market
    value. No future close/high/low is used to choose size or execution price.

    Decimal arithmetic is used for cash and costs without currency-specific
    rounding. Result tables contain ordinary numeric values for pandas consumers.
    """
    if config is None:
        config = BacktestConfig()
    eligible = _validate_stock(stock)
    initial_cash = Decimal(str(config.initial_cash))
    cash = initial_cash
    commission_rate = Decimal(str(config.commission_rate))
    fixed_fee = Decimal(str(config.fixed_fee))
    slippage_bps = Decimal(str(config.slippage_bps))
    shares = 0
    fees = Decimal(0)
    slippage_cost = Decimal(0)
    cost_basis = Decimal(0)
    peak_equity = initial_cash
    order = {
        "order_id": 1, "symbol": stock.metadata.symbol, "side": "buy",
        "requested_shares": config.shares,
        "submitted_bar": stock.bars.index[0], "submitted_phase": "close",
        "status": "pending", "resolved_bar": pd.NaT, "resolved_phase": "",
        "reason": "",
    }
    fills, records = [], []
    for bar_number, (timestamp, bar) in enumerate(stock.bars.iterrows()):
        # The first bar supplies the decision point; it cannot fill its own order.
        if bar_number > 0 and order["status"] == "pending" and eligible.iloc[bar_number]:
            reference = Decimal(str(bar["open"]))
            price, notional, commission = buy_costs(
                reference, config.shares, commission_rate, fixed_fee, slippage_bps,
            )
            debit = notional + commission
            as_float(debit)
            order["resolved_bar"] = timestamp
            order["resolved_phase"] = "open"
            if debit > cash:
                order["status"] = "rejected"
                order["reason"] = "insufficient_cash_including_fees"
            else:
                cash -= debit
                shares = config.shares
                fees = commission
                slippage_cost = (price - reference) * shares
                cost_basis = debit
                order["status"] = "filled"
                fills.append({
                    "order_id": 1, "symbol": stock.metadata.symbol, "side": "buy",
                    "bar_timestamp": timestamp, "phase": "open", "shares": shares,
                    "reference_open": as_float(reference), "price": as_float(price),
                    "notional": as_float(notional), "commission": as_float(commission),
                    "slippage_cost": as_float(slippage_cost), "cash_after": as_float(cash),
                })
        record, peak_equity = mark_to_market(
            timestamp, Decimal(str(bar["close"])), cash, shares, initial_cash, fees, peak_equity,
        )
        records.append(record)
    if order["status"] == "pending":
        order.update(status="expired", resolved_bar=stock.bars.index[-1],
                     resolved_phase="close", reason="no_eligible_execution_bar")

    curve = pd.DataFrame(records).set_index("bar_timestamp")
    summary = {
        "bars": len(curve),
        "start_bar": stock.bars.index[0].isoformat(),
        "end_bar": stock.bars.index[-1].isoformat(),
        "initial_cash": config.initial_cash,
        "final_cash": as_float(cash), "final_shares": shares,
        "final_position_value": records[-1]["position_value"], "final_equity": records[-1]["equity"],
        "net_pnl": records[-1]["net_pnl"],
        "total_return_pct": records[-1]["return_pct"],
        "max_drawdown_pct": float(curve["drawdown_pct"].max()),
        "total_fees": as_float(fees), "total_slippage_cost": as_float(slippage_cost),
        "position_cost_including_fees": as_float(cost_basis),
        "filled_orders": int(order["status"] == "filled"),
        "rejected_orders": int(order["status"] == "rejected"),
        "expired_orders": int(order["status"] == "expired"),
    }
    return BacktestResult(config, stock.metadata, curve, pd.DataFrame([order]),
                          pd.DataFrame(fills, columns=FILL_COLUMNS), summary)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", type=Path, help="Override the CSV in the strategy config")
    parser.add_argument("--config", type=Path, default=CONFIG_DIR / "strategy.yaml")
    parser.add_argument("--interval", choices=INTERVALS)
    parser.add_argument("--market", choices=MARKETS)
    parser.add_argument("--adjustment", help="Declare the existing input price adjustment")
    parser.add_argument("--naive-timezone", help="IANA timezone for input timestamps without offsets")
    parser.add_argument("--cash", dest="initial_cash", type=float, help="Starting cash in the stock currency")
    parser.add_argument("--shares", type=int, help="Fixed whole-share buy quantity")
    parser.add_argument("--commission-rate", type=float, help="Fraction of notional; 0.001 = 0.1%%")
    parser.add_argument("--fixed-fee", type=float, help="Additional fee per fill")
    parser.add_argument("--slippage-bps", type=float, help="Buy-price markup; 10 bps = 0.1%%")
    parser.add_argument("--output-dir", type=Path, help="Default: outputs/backtests/<CSV stem>_buy_hold")
    args = parser.parse_args(argv)
    try:
        settings = load_strategy_config(args.config)
        # Explicit CLI values override YAML, including valid zero-valued costs.
        settings.update({key: value for key, value in vars(args).items()
                         if key != "config" and value is not None})
        config = BacktestConfig(**{field.name: settings[field.name]
                                   for field in fields(BacktestConfig) if field.name in settings})
        csv_path = settings["csv"]
        stock = load_stock_csv(
            csv_path, market=settings.get("market"), interval=settings.get("interval"),
            adjustment=settings.get("adjustment"), naive_timezone=settings.get("naive_timezone"),
        )
        result = run_buy_and_hold(stock, config)
        destination = settings.get("output_dir")
        if destination is None:
            destination = BACKTEST_RESULTS_DIR / f"{csv_path.stem}_buy_hold"
        result.save(destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not run backtest: {exc}\n")
    summary = result.summary
    print(f"Buy and hold: {stock.metadata.symbol} | {stock.metadata.currency} | {summary['bars']:,} bars")
    print(f"Order: {result.orders.iloc[0]['status']}")
    print(f"Final equity: {summary['final_equity']:,.2f}; cash: {summary['final_cash']:,.2f}; shares: {summary['final_shares']}")
    print(f"Return: {summary['total_return_pct']:+.4f}%; max drawdown: {summary['max_drawdown_pct']:.4f}%")
    print(f"Fees: {summary['total_fees']:,.4f}; ending holdings valued at the final close")
    print(f"Saved backtest: {destination.resolve()}")


if __name__ == "__main__":
    main()
