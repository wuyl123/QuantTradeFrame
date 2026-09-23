"""Offline checks for normalization, time semantics, and invalid input handling."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from quantlibrary.data.loader import DataValidationError, OHLCV_COLUMNS, load_stock_csv
from quantlibrary.paths import RAW_DATA_DIR, SAMPLE_DATA_DIR


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quantlibrary_loader_")
        self.addCleanup(self.temp.cleanup)
        self.csv_path = Path(self.temp.name) / "bars.csv"
        self.frame = pd.DataFrame({
            "timestamp": ["2024-01-02 09:35:00", "2024-01-02 09:40:00", "2024-01-02 09:45:00"],
            "symbol": ["000001"] * 3,
            "open": [10, 11, 12], "high": [12, 13, 14],
            "low": [9, 10, 11], "close": [11, 12, 13],
            "volume_lots": [1.25, 0, 2.5],
            "source": ["baostock"] * 3, "adjustment": ["qfq"] * 3,
            "trading_status": [1, 0, 1],
        }).astype(object)

    def write(self, frame=None):
        (self.frame if frame is None else frame).to_csv(self.csv_path, index=False, encoding="utf-8-sig")
        return self.csv_path

    def us_frame(self):
        frame = self.frame.drop(columns=["source", "adjustment", "trading_status"])
        frame = frame.rename(columns={"volume_lots": "volume"})
        frame["symbol"] = "AAPL"
        return frame

    def test_a_share_conversion_sorting_and_preserved_columns(self):
        path = self.write(self.frame.iloc[::-1])
        before = path.read_bytes()
        result = load_stock_csv(path, interval="5m")
        self.assertEqual(result.metadata.symbol, "000001")
        self.assertEqual(result.metadata.market, "a_share")
        self.assertEqual(result.metadata.adjustment, "qfq")
        self.assertEqual(result.metadata.source, "baostock")
        self.assertEqual(result.metadata.volume_unit, "shares")
        self.assertEqual(result.metadata.input_volume_unit, "lots")
        self.assertEqual(result.metadata.timestamp_kind, "provider_timestamp")
        self.assertEqual(result.bars.index.name, "timestamp")
        self.assertEqual(str(result.bars.index.tz), "UTC")
        self.assertEqual(result.bars.index[0], pd.Timestamp("2024-01-02 01:35:00Z"))
        self.assertEqual(list(result.bars.columns[:5]), list(OHLCV_COLUMNS))
        self.assertEqual(result.bars["volume"].tolist(), [125, 0, 250])
        self.assertEqual(result.bars["close"].tolist(), [11, 12, 13])
        self.assertEqual(result.bars["trading_status"].tolist(), [1, 0, 1])
        self.assertTrue((result.bars[list(OHLCV_COLUMNS)].dtypes == "float64").all())
        self.assertEqual(path.read_bytes(), before)

    def test_existing_datasets(self):
        cases = [(SAMPLE_DATA_DIR / "000001_daily_sample.csv", {}, 4, "1d"),
                 (RAW_DATA_DIR / "000001_5m_2026-08.csv", {"interval": "5m"}, 1008, "5m")]
        for path, kwargs, count, interval in cases:
            with self.subTest(path=path.name):
                # Downloaded data is optional in a clean checkout.
                if not path.exists() and path.parent == RAW_DATA_DIR:
                    continue
                before = hashlib.sha256(path.read_bytes()).digest()
                result = load_stock_csv(path, **kwargs)
                self.assertEqual(len(result.bars), count)
                self.assertEqual(result.metadata.interval, interval)
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
        sample = load_stock_csv(SAMPLE_DATA_DIR / "000001_daily_sample.csv")
        self.assertEqual(sample.bars.index[0], pd.Timestamp("2024-01-01 16:00:00Z"))
        self.assertEqual(sample.metadata.timestamp_kind, "session_date")
        self.assertIsNone(sample.metadata.adjustment)
        self.assertIsNone(sample.metadata.source)

    def test_us_naive_times_are_utc_and_volume_is_unchanged(self):
        frame = self.us_frame()
        frame["symbol"] = "NA"  # A symbol must not be interpreted as a missing value.
        result = load_stock_csv(self.write(frame), interval="5m", adjustment="split")
        self.assertEqual(result.metadata.symbol, "NA")
        self.assertEqual(result.metadata.currency, "USD")
        self.assertEqual(result.metadata.adjustment, "split")
        self.assertEqual(result.bars.index[0], pd.Timestamp("2024-01-02 09:35:00Z"))
        self.assertEqual(result.bars["volume"].tolist(), [1.25, 0, 2.5])

    def test_explicit_offsets_across_dst(self):
        frame = self.us_frame().iloc[:2].copy()
        frame["timestamp"] = ["2024-03-08T09:30:00-05:00", "2024-03-11T09:30:00-04:00"]
        result = load_stock_csv(self.write(frame), interval="5m")
        self.assertEqual(result.bars.index.tolist(),
                         [pd.Timestamp("2024-03-08 14:30Z"), pd.Timestamp("2024-03-11 13:30Z")])
        self.assertEqual(len(result.bars), 2)  # No filling overnight/weekend gaps.

    def test_us_daily_dates_use_local_midnight_across_dst(self):
        frame = self.us_frame().iloc[:2].rename(columns={"timestamp": "date"})
        frame["date"] = ["2024-03-10", "2024-03-11"]
        result = load_stock_csv(self.write(frame))
        self.assertEqual(result.bars.index.tolist(),
                         [pd.Timestamp("2024-03-10 05:00Z"), pd.Timestamp("2024-03-11 04:00Z")])
        self.assertEqual(result.metadata.market_timezone, "America/New_York")
        with self.assertRaisesRegex(DataValidationError, "market timezone"):
            load_stock_csv(self.csv_path, naive_timezone="UTC")

    def test_explicit_naive_timezone_and_dst_rejection(self):
        frame = self.us_frame().iloc[:1].copy()
        result = load_stock_csv(self.write(frame), interval="5m", naive_timezone="America/New_York")
        self.assertEqual(result.bars.index[0], pd.Timestamp("2024-01-02 14:35Z"))
        for stamp in ("2024-03-10 02:30:00", "2024-11-03 01:30:00"):
            with self.subTest(stamp=stamp):
                frame["timestamp"] = stamp
                with self.assertRaisesRegex(DataValidationError, "Cannot interpret timestamps"):
                    load_stock_csv(self.write(frame), interval="5m", naive_timezone="America/New_York")
        with self.assertRaisesRegex(DataValidationError, "Unknown IANA timezone"):
            load_stock_csv(self.write(), interval="5m", naive_timezone="Not/AZone")

    def test_interval_is_explicit_and_metadata_must_agree(self):
        with self.assertRaisesRegex(DataValidationError, "Specify interval"):
            load_stock_csv(self.write())
        self.frame["interval"] = "5m"
        result = load_stock_csv(self.write())
        self.assertEqual(result.metadata.interval, "5m")
        for kwargs in ({"interval": "1m"}, {"adjustment": "raw"}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(DataValidationError, "conflicts"):
                load_stock_csv(self.csv_path, **kwargs)
        self.frame["market"] = "a_share"
        with self.assertRaisesRegex(DataValidationError, "conflicts"):
            load_stock_csv(self.write(), market="us")

    def test_market_override_for_a_share_volume_in_shares(self):
        frame = self.frame.rename(columns={"volume_lots": "volume"})
        result = load_stock_csv(self.write(frame), market="a_share", interval="5m")
        self.assertEqual(result.metadata.currency, "CNY")
        self.assertEqual(result.bars["volume"].tolist(), [1.25, 0, 2.5])

    def test_numeric_and_ohlc_validation(self):
        cases = [("close", "", "numeric"), ("close", "bad", "numeric"),
                 ("high", np.inf, "finite"), ("volume_lots", np.nan, "non-missing"),
                 ("close", True, "numeric"), ("volume_lots", -1, "negative"),
                 ("open", 0, "positive"), ("low", -1, "positive"),
                 ("high", 10, "Inconsistent OHLC"), ("low", 12, "Inconsistent OHLC"),
                 ("volume_lots", 1e308, "overflows")]
        for column, value, message in cases:
            with self.subTest(column=column, value=value):
                frame = self.frame.copy()
                frame.loc[0, column] = value
                with self.assertRaisesRegex(DataValidationError, message):
                    load_stock_csv(self.write(frame), interval="5m")

    def test_duplicate_missing_invalid_and_mixed_timestamps(self):
        for value, message in [("2024-01-02 09:40:00", "Duplicate"),
                               ("", "Missing"), ("not-a-time", "Invalid"),
                               ("2024-01-02 09:35:00 EST", "ISO 8601"),
                               ("2024-01-02T01:35:00Z", "Do not mix")]:
            with self.subTest(value=value):
                frame = self.frame.copy()
                frame.loc[0, "timestamp"] = value
                with self.assertRaisesRegex(DataValidationError, message):
                    load_stock_csv(self.write(frame), interval="5m")
        frame = self.us_frame().iloc[:2].copy()
        frame["timestamp"] = ["2024-01-02T09:30:00-05:00", "2024-01-02T14:30:00Z"]
        with self.assertRaisesRegex(DataValidationError, "Duplicate timestamp after UTC"):
            load_stock_csv(self.write(frame), interval="5m")

    def test_missing_ambiguous_and_mixed_columns(self):
        for column in ("symbol", "open", "high", "low", "close", "timestamp", "volume_lots"):
            with self.subTest(column=column), self.assertRaises(DataValidationError):
                load_stock_csv(self.write(self.frame.drop(columns=column)), interval="5m")
        for column, value in (("symbol", "600519"), ("symbol", ""),
                              ("source", "another-provider"), ("adjustment", "raw"), ("adjustment", "")):
            frame = self.frame.copy()
            frame.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(DataValidationError):
                load_stock_csv(self.write(frame), interval="5m")
        for column in ("date", "volume"):
            frame = self.frame.copy()
            frame[column] = "2024-01-02" if column == "date" else 100
            with self.subTest(column=column), self.assertRaisesRegex(DataValidationError, "exactly one"):
                load_stock_csv(self.write(frame), interval="5m")

    def test_interval_and_daily_label_validation(self):
        with self.assertRaisesRegex(DataValidationError, "shorter"):
            load_stock_csv(self.write(), interval="1h")
        with self.assertRaisesRegex(DataValidationError, "one bar per market-local date"):
            load_stock_csv(self.csv_path, interval="1d")
        frame = self.frame.iloc[:1].rename(columns={"timestamp": "date"})
        with self.assertRaisesRegex(DataValidationError, "YYYY-MM-DD"):
            load_stock_csv(self.write(frame))
        frame["date"] = "2024-01-02"
        with self.assertRaisesRegex(DataValidationError, "requires interval='1d'"):
            load_stock_csv(self.write(frame), interval="5m")

    def test_header_normalization_and_malformed_csv(self):
        frame = self.frame.rename(columns=lambda name: f" {name.upper()} ")
        result = load_stock_csv(self.write(frame), interval="5m")
        self.assertEqual(result.metadata.symbol, "000001")
        for text, message in [("", "header"), ("date,symbol,open,high,low,close,volume\n", "at least one"),
                              ("date,DATE\n2024-01-02,2024-01-02\n", "duplicate column"),
                              ("date,symbol\n2024-01-02,AAPL,unexpected\n", "field count"),
                              ('date,symbol\n2024-01-02,"AAPL\n', "Malformed CSV")]:
            with self.subTest(text=text):
                self.csv_path.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(DataValidationError, message):
                    load_stock_csv(self.csv_path, interval="5m")

    def test_cli_success_and_actionable_error(self):
        self.write()
        command = [sys.executable, "-m", "quantlibrary.data.loader", str(self.csv_path)]
        failed = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Specify interval", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)
        passed = subprocess.run(command + ["--interval", "5m"], capture_output=True, text=True)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn('"volume_unit": "shares"', passed.stdout)
        self.assertIn("Validated 3 bars", passed.stdout)


if __name__ == "__main__":
    unittest.main()
