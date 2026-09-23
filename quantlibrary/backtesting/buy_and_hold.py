"""Run a single-stock accounting baseline (python -m quantlibrary.backtesting.buy_and_hold)."""

import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import math
from numbers import Integral, Real
from pathlib import Path

import numpy as np
import pandas as pd

from quantlibrary.data.loader import INTERVALS, MARKETS, OHLCV_COLUMNS, StockData, StockMetadata, load_stock_csv
from quantlibrary.paths import BACKTEST_RESULTS_DIR, SAMPLE_DATA_DIR


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


@dataclass
class BacktestResult:
    """Bar labels in these records retain the loader's timestamp conventions."""

    config: BacktestConfig
    metadata: StockMetadata
    equity_curve: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    summary: dict

    def save(self, output_dir: str | Path) -> Path:
        """Write a reproducible record; replace these four files on repeat runs."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "strategy": "buy_and_hold",
            "config": asdict(self.config),
            "metadata": asdict(self.metadata),
            "summary": self.summary,
            "assumptions": {
                "entry": "One fixed-size buy submitted after the first bar; next eligible bar's open",
                "eligibility": "Completed bar has positive volume and trading_status=1 when provided",
                "liquidity": "Full fill only; no volume participation, queue, or intrabar liquidity model",
                "slippage": "Buy price = open * (1 + slippage_bps / 10000); no OHLC clipping",
                "fees": "Notional * commission_rate + fixed_fee per fill; no minor-unit rounding",
                "end_position": "Held at final close; no forced sale or hypothetical exit fee",
                "timestamps": "UTC bar labels plus open/close phase, not exact execution instants",
                "prices": "Input adjustment convention; no separate dividends or corporate actions",
                "market_rules": "No venue-specific lot sizes, taxes, price limits, or settlement model",
            },
        }
        # Serialize first so invalid report values cannot truncate an existing report.
        report_json = json.dumps(report, indent=2, allow_nan=False) + "\n"
        self.equity_curve.to_csv(output_dir / "equity.csv", encoding="utf-8-sig")
        self.orders.to_csv(output_dir / "orders.csv", index=False, encoding="utf-8-sig")
        self.fills.to_csv(output_dir / "fills.csv", index=False, encoding="utf-8-sig")
        (output_dir / "summary.json").write_text(report_json, encoding="utf-8")
        return output_dir


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


def _number(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Backtest values exceed the supported numeric range")
    return result


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
    slippage_rate = Decimal(str(config.slippage_bps)) / Decimal(10_000)
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
            price = reference * (1 + slippage_rate)
            notional = price * config.shares
            commission = notional * commission_rate + fixed_fee
            debit = notional + commission
            _number(debit)
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
                    "reference_open": _number(reference), "price": _number(price),
                    "notional": _number(notional), "commission": _number(commission),
                    "slippage_cost": _number(slippage_cost), "cash_after": _number(cash),
                })
        closing_price = Decimal(str(bar["close"]))
        position_value = shares * closing_price
        equity = cash + position_value
        peak_equity = max(peak_equity, equity)
        records.append({
            "bar_timestamp": timestamp, "phase": "close", "cash": _number(cash),
            "shares": shares, "close": _number(closing_price),
            "position_value": _number(position_value), "equity": _number(equity),
            "fees_paid": _number(fees), "net_pnl": _number(equity - initial_cash),
            "return_pct": _number((equity / initial_cash - 1) * 100),
            "drawdown_pct": _number((peak_equity - equity) / peak_equity * 100),
        })
    if order["status"] == "pending":
        order.update(status="expired", resolved_bar=stock.bars.index[-1],
                     resolved_phase="close", reason="no_eligible_execution_bar")

    curve = pd.DataFrame(records).set_index("bar_timestamp")
    summary = {
        "bars": len(curve),
        "start_bar": stock.bars.index[0].isoformat(),
        "end_bar": stock.bars.index[-1].isoformat(),
        "initial_cash": config.initial_cash,
        "final_cash": _number(cash), "final_shares": shares,
        "final_position_value": _number(position_value), "final_equity": _number(equity),
        "net_pnl": _number(equity - initial_cash),
        "total_return_pct": _number((equity / initial_cash - 1) * 100),
        "max_drawdown_pct": float(curve["drawdown_pct"].max()),
        "total_fees": _number(fees), "total_slippage_cost": _number(slippage_cost),
        "position_cost_including_fees": _number(cost_basis),
        "filled_orders": int(order["status"] == "filled"),
        "rejected_orders": int(order["status"] == "rejected"),
        "expired_orders": int(order["status"] == "expired"),
    }
    return BacktestResult(config, stock.metadata, curve, pd.DataFrame([order]),
                          pd.DataFrame(fills, columns=FILL_COLUMNS), summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", type=Path, default=SAMPLE_DATA_DIR / "000001_daily_sample.csv")
    parser.add_argument("--interval", choices=INTERVALS)
    parser.add_argument("--market", choices=MARKETS)
    parser.add_argument("--adjustment", help="Declare the existing input price adjustment")
    parser.add_argument("--naive-timezone", help="IANA timezone for input timestamps without offsets")
    parser.add_argument("--cash", type=float, default=100_000, help="Starting cash in the stock currency")
    parser.add_argument("--shares", type=int, default=100, help="Fixed whole-share buy quantity")
    parser.add_argument("--commission-rate", type=float, default=0.001, help="Fraction of notional; 0.001 = 0.1%%")
    parser.add_argument("--fixed-fee", type=float, default=0, help="Additional fee per fill")
    parser.add_argument("--slippage-bps", type=float, default=0, help="Buy-price markup; 10 bps = 0.1%%")
    parser.add_argument("--output-dir", type=Path, help="Default: outputs/backtests/<CSV stem>_buy_hold")
    args = parser.parse_args()
    try:
        config = BacktestConfig(args.cash, args.shares, args.commission_rate, args.fixed_fee, args.slippage_bps)
        stock = load_stock_csv(args.csv, market=args.market, interval=args.interval,
                               adjustment=args.adjustment, naive_timezone=args.naive_timezone)
        result = run_buy_and_hold(stock, config)
        destination = args.output_dir if args.output_dir is not None else BACKTEST_RESULTS_DIR / f"{args.csv.stem}_buy_hold"
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
