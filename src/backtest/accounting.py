"""Position valuation, cash/equity records, and backtest result export."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src.data.loader import StockMetadata
from src.evaluation.performance import return_pct
from src.evaluation.risk import drawdown_pct

if TYPE_CHECKING:
    from src.backtest.engine import BacktestConfig


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


def as_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Backtest values exceed the supported numeric range")
    return result


def mark_to_market(
    timestamp: pd.Timestamp,
    closing_price: Decimal,
    cash: Decimal,
    shares: int,
    initial_cash: Decimal,
    fees: Decimal,
    peak_equity: Decimal,
) -> tuple[dict, Decimal]:
    """Value holdings at this close and return the record plus updated peak."""
    position_value = shares * closing_price
    equity = cash + position_value
    peak_equity = max(peak_equity, equity)
    record = {
        "bar_timestamp": timestamp, "phase": "close", "cash": as_float(cash),
        "shares": shares, "close": as_float(closing_price),
        "position_value": as_float(position_value), "equity": as_float(equity),
        "fees_paid": as_float(fees), "net_pnl": as_float(equity - initial_cash),
        "return_pct": as_float(return_pct(equity, initial_cash)),
        "drawdown_pct": as_float(drawdown_pct(equity, peak_equity)),
    }
    return record, peak_equity
