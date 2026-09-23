"""Configuration and end-to-end checks for the unified command-line entry point."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from main import main
from src.utils.paths import PROJECT_ROOT


class MainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quant_research_cli_")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder / "prices.csv").write_text(
            "date,symbol,open,high,low,close,volume\n"
            "2024-01-02,TEST,10,10,10,10,1000\n"
            "2024-01-03,TEST,11,12,11,12,1000\n"
            "2024-01-04,TEST,9,9,9,9,1000\n", encoding="utf-8",
        )
        self.config = self.folder / "strategy.yaml"
        self.config.write_text(
            "strategy: buy_and_hold\ncsv: prices.csv\ninterval: 1d\n"
            "initial_cash: 1000\nshares: 10\ncommission_rate: 0.01\n"
            "fixed_fee: 0\nslippage_bps: 0\noutput_dir: reports\n",
            encoding="utf-8",
        )

    def run_command(self, *args):
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py"), *args],
            cwd=self.folder, capture_output=True, text=True,
        )

    def test_yaml_paths_resolve_from_config_and_cli_values_override(self):
        result = self.run_command("backtest", "--config", str(self.config))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.folder / "reports" / "summary.json").read_text())
        self.assertEqual(report["summary"]["final_equity"], 978.9)

        result = self.run_command(
            "backtest", "--config", str(self.config), "--cash", "2000", "--shares", "5",
            "--commission-rate", "0", "--output-dir", "overridden",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.folder / "overridden" / "summary.json").read_text())
        self.assertEqual(report["config"]["commission_rate"], 0)
        self.assertEqual(report["summary"]["final_equity"], 1990)
        self.assertEqual(report["summary"]["total_fees"], 0)

    def test_default_command_uses_shipped_config(self):
        # Redirect only the destination so the user's existing reports stay intact.
        with patch("src.backtest.engine.BACKTEST_RESULTS_DIR", self.folder), redirect_stdout(io.StringIO()):
            main([])
        report_path = self.folder / "000001_daily_sample_buy_hold" / "summary.json"
        report = json.loads(report_path.read_text())
        self.assertEqual(report["strategy"], "buy_and_hold")
        self.assertEqual(report["config"]["initial_cash"], 100000)
        self.assertEqual(report["summary"]["bars"], 4)

    def test_invalid_config_is_rejected_before_writing_results(self):
        invalid = [
            ("[]\n", "YAML mapping"),
            ("csv: [\n", "Invalid strategy YAML"),
            ("csv: prices.csv\nstrategy: momentum\n", "Only the buy_and_hold"),
            ("csv: prices.csv\ncommision_rate: 0.01\n", "Unknown strategy config keys"),
            ("strategy: buy_and_hold\n", "must specify csv"),
            ("csv: prices.csv\nshares: true\n", "positive integer"),
        ]
        for text, error in invalid:
            with self.subTest(error=error):
                self.config.write_text(text, encoding="utf-8")
                result = self.run_command(
                    "backtest", "--config", str(self.config), "--output-dir", "reports",
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(error, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((self.folder / "reports").exists())

    def test_validate_command_and_subcommand_help(self):
        result = self.run_command("validate", "prices.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 3 bars", result.stdout)
        result = self.run_command("backtest", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--config", result.stdout)
        self.assertIn("--commission-rate", result.stdout)


if __name__ == "__main__":
    unittest.main()
