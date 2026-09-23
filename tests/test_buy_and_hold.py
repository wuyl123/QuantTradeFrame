"""Cash and execution checks using prices and balances calculated by hand."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.backtest.engine import BacktestConfig, run_buy_and_hold
from src.data.loader import load_stock_csv


class BuyAndHoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quantlibrary_backtest_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv_path = self.root / "prices.csv"
        self.frame = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "symbol": ["TEST"] * 3,
            "open": [10.0, 11.0, 9.0], "high": [10.0, 12.0, 9.0],
            "low": [10.0, 11.0, 9.0], "close": [10.0, 12.0, 9.0],
            "volume": [1000, 1000, 1000],
        })
        self.config = BacktestConfig(initial_cash=1000, shares=10, commission_rate=0.01)

    def load(self, frame=None):
        (self.frame if frame is None else frame).to_csv(self.csv_path, index=False)
        return load_stock_csv(self.csv_path)

    def test_hand_calculated_cash_positions_and_drawdown(self):
        result = run_buy_and_hold(self.load(), self.config)
        # Buy 10 at the second open of 11: cost 110 + fee 1.10 = 111.10.
        # Cash is 888.90; closing values are 1008.90 and 978.90.
        curve = result.equity_curve
        np.testing.assert_allclose(curve["cash"], [1000, 888.9, 888.9])
        np.testing.assert_array_equal(curve["shares"], [0, 10, 10])
        np.testing.assert_allclose(curve["position_value"], [0, 120, 90])
        np.testing.assert_allclose(curve["equity"], [1000, 1008.9, 978.9])
        np.testing.assert_allclose(curve["fees_paid"], [0, 1.1, 1.1])
        np.testing.assert_allclose(curve["equity"], curve["cash"] + curve["shares"] * curve["close"])
        self.assertAlmostEqual(result.summary["net_pnl"], -21.1)
        self.assertAlmostEqual(result.summary["total_return_pct"], -2.11)
        self.assertAlmostEqual(result.summary["max_drawdown_pct"], 30 / 1008.9 * 100)
        self.assertEqual(result.summary["filled_orders"], 1)
        self.assertEqual(result.summary["final_shares"], 10)  # No fabricated final sale.
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills.iloc[0]["side"], "buy")

    def test_open_execution_follows_first_close_and_keeps_bar_labels(self):
        stock = self.load()
        before = stock.bars.copy(deep=True)
        result = run_buy_and_hold(stock, self.config)
        order, fill = result.orders.iloc[0], result.fills.iloc[0]
        self.assertEqual(order["submitted_bar"], stock.bars.index[0])
        self.assertEqual(order["submitted_phase"], "close")
        self.assertEqual(fill["bar_timestamp"], stock.bars.index[1])
        self.assertEqual(fill["phase"], "open")
        self.assertEqual(fill["price"], 11)
        self.assertEqual(result.metadata.timestamp_kind, "session_date")
        self.assertEqual(result.metadata, stock.metadata)
        pd.testing.assert_frame_equal(stock.bars, before)

    def test_slippage_percentage_fee_and_fixed_fee_are_all_charged(self):
        config = replace(self.config, slippage_bps=100, fixed_fee=2)
        result = run_buy_and_hold(self.load(), config)
        # 11 * 1.01 = 11.11; notional 111.10; fee 1.111 + 2 = 3.111.
        fill = result.fills.iloc[0]
        self.assertAlmostEqual(fill["price"], 11.11)
        self.assertAlmostEqual(fill["notional"], 111.1)
        self.assertAlmostEqual(fill["commission"], 3.111)
        self.assertAlmostEqual(fill["slippage_cost"], 1.1)
        self.assertAlmostEqual(result.summary["final_cash"], 885.789)
        self.assertAlmostEqual(result.summary["final_equity"], 975.789)
        self.assertAlmostEqual(result.summary["position_cost_including_fees"], 114.211)

    def test_gap_rejection_does_not_retry_or_charge_fees(self):
        # First close would cost 100, but the actual next open costs 110.
        config = BacktestConfig(initial_cash=100, shares=10, commission_rate=0)
        result = run_buy_and_hold(self.load(), config)
        self.assertEqual(result.orders.iloc[0]["status"], "rejected")
        self.assertEqual(result.orders.iloc[0]["reason"], "insufficient_cash_including_fees")
        self.assertTrue(result.fills.empty)  # The later open of 9 does not trigger a retry.
        self.assertEqual(result.summary["final_cash"], 100)
        self.assertEqual(result.summary["final_shares"], 0)
        self.assertEqual(result.summary["total_fees"], 0)
        self.assertEqual(result.summary["total_return_pct"], 0)
        self.assertEqual(result.summary["rejected_orders"], 1)

    def test_affordability_includes_fees(self):
        result = run_buy_and_hold(self.load(), replace(self.config, initial_cash=110))
        self.assertEqual(result.summary["rejected_orders"], 1)
        self.assertEqual(result.summary["final_cash"], 110)

    def test_exactly_affordable_decimal_trade_leaves_zero_cash(self):
        self.frame[["open", "high", "low", "close"]] = 0.1
        result = run_buy_and_hold(self.load(), BacktestConfig(initial_cash=0.3, shares=3, commission_rate=0))
        self.assertEqual(result.summary["filled_orders"], 1)
        self.assertEqual(result.summary["final_cash"], 0)
        self.assertEqual(result.summary["final_equity"], 0.3)

    def test_zero_volume_or_suspension_defers_execution(self):
        for column, values in (("volume", [1000, 0, 1000]), ("trading_status", [1, 0, 1])):
            with self.subTest(column=column):
                frame = self.frame.copy()
                frame[column] = values
                stock = self.load(frame)
                result = run_buy_and_hold(stock, self.config)
                self.assertEqual(result.fills.iloc[0]["bar_timestamp"], stock.bars.index[2])
                self.assertEqual(result.fills.iloc[0]["price"], 9)
                self.assertEqual(result.summary["final_cash"], 909.1)
                self.assertEqual(result.summary["final_equity"], 999.1)

    def test_single_bar_and_no_eligible_bar_expire_without_fill(self):
        no_volume = self.frame.assign(volume=0)
        for frame in (self.frame.iloc[:1], no_volume):
            with self.subTest(rows=len(frame)):
                result = run_buy_and_hold(self.load(frame), self.config)
                self.assertTrue(result.fills.empty)
                self.assertEqual(result.summary["expired_orders"], 1)
                self.assertEqual(result.summary["final_equity"], 1000)
                self.assertEqual(result.summary["max_drawdown_pct"], 0)
                self.assertEqual(result.orders.iloc[0]["resolved_phase"], "close")

    def test_future_closes_cannot_change_entry_or_earlier_equity(self):
        original = run_buy_and_hold(self.load(), self.config)
        self.frame.loc[2, ["close", "high"]] = 999
        changed = run_buy_and_hold(self.load(), self.config)
        pd.testing.assert_frame_equal(original.fills, changed.fills)
        pd.testing.assert_frame_equal(original.equity_curve.iloc[:2], changed.equity_curve.iloc[:2])

    def test_initial_loss_is_included_in_drawdown(self):
        self.frame.loc[1, ["low", "close"]] = 9
        result = run_buy_and_hold(self.load(), self.config)
        self.assertAlmostEqual(result.summary["max_drawdown_pct"], 2.11)

    def test_config_rejects_invalid_values(self):
        for name, values in {
            "initial_cash": [0, -1, float("nan"), float("inf"), True],
            "shares": [0, -1, 1.5, True],
            "commission_rate": [-0.01, float("nan")],
            "fixed_fee": [-1, float("inf")],
            "slippage_bps": [-1, float("nan")],
        }.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    BacktestConfig(**{name: value})

    def test_mutated_input_and_unknown_trading_status_are_rejected(self):
        stock = self.load()
        for bars in (stock.bars.iloc[:0], stock.bars.iloc[::-1],
                     stock.bars.set_axis(stock.bars.index.tz_localize(None)),
                     stock.bars.assign(close=np.nan), stock.bars.assign(trading_status=2)):
            with self.subTest(bars=bars.shape), self.assertRaises(ValueError):
                run_buy_and_hold(replace(stock, bars=bars), self.config)
        with self.assertRaisesRegex(ValueError, "volume in shares"):
            run_buy_and_hold(replace(stock, metadata=replace(stock.metadata, volume_unit="lots")))

    def test_exports_record_config_metadata_orders_fills_and_equity(self):
        for config in (self.config, replace(self.config, initial_cash=1)):
            with self.subTest(cash=config.initial_cash):
                result = run_buy_and_hold(self.load(), config)
                folder = result.save(self.root / "results")
                report = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual(report["config"]["initial_cash"], config.initial_cash)
                self.assertEqual(report["metadata"]["volume_unit"], "shares")
                self.assertIsNone(report["metadata"]["adjustment"])
                self.assertEqual(report["summary"], result.summary)
                self.assertEqual(len(pd.read_csv(folder / "equity.csv")), 3)
                self.assertEqual(len(pd.read_csv(folder / "orders.csv")), 1)
                self.assertEqual(len(pd.read_csv(folder / "fills.csv")), len(result.fills))

    def test_cli_runs_and_validation_errors_are_actionable(self):
        self.load()
        folder = self.root / "cli"
        command = [sys.executable, "-m", "src.backtest.engine", str(self.csv_path),
                   "--cash", "1000", "--shares", "10", "--commission-rate", "0.01", "--output-dir", str(folder)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("978.90", result.stdout)
        self.assertTrue((folder / "summary.json").is_file())
        failed = subprocess.run(command + ["--shares", "0"], capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("positive integer", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)


if __name__ == "__main__":
    unittest.main()
