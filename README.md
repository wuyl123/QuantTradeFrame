# Quant Research

A stock research workspace organized around data, factors, signals, portfolios,
backtesting, and evaluation. The current working tools are data downloads,
CSV validation, buy-and-hold backtesting, and stock charts.

## Setup

Use Python 3.10 or newer. Run these commands from the project root:

```powershell
# Only create the environment if it does not exist.
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The environment now includes PyYAML for the strategy configuration. You can use
`.\.venv\Scripts\python.exe` in place of `python` without activation.
No package installation or manual `PYTHONPATH` setting is needed.

## Layout

```text
QuantLibrary/                  # Current workspace; no outer-folder rename
|-- data/
|   |-- raw/                   # Provider downloads
|   |-- processed/             # Reserved for normalized research datasets
|   `-- samples/               # Small offline fixtures
|-- src/
|   |-- data/                  # loader, a_share, us_stock, universe, calendar
|   |-- factors/               # base, momentum, value, quality, volatility
|   |-- preprocessing/         # winsorize, neutralize, standardize
|   |-- signals/               # combine, ranking
|   |-- portfolio/             # construction, constraints, rebalance
|   |-- backtest/              # engine, costs, accounting
|   |-- evaluation/            # performance, factor_analysis, risk, visualize
|   `-- utils/                 # paths and config loading
|-- research/
|   `-- notebooks/
|-- tests/
|-- config/
|   `-- strategy.yaml
|-- outputs/                   # Existing charts and backtest records
|-- docs/                      # Provider/data/accounting reference
|-- requirements.txt
`-- main.py
```

`src/data/universe.py`, `src/data/calendar.py`, the factor/preprocessing/signal/
portfolio modules, and `src/evaluation/factor_analysis.py` are explicitly marked
as reserved. They do not yet calculate factors or execute multi-stock strategies.
The current engine still runs one buy-and-hold position.

## Common commands

```powershell
# Run buy-and-hold using config/strategy.yaml.
python main.py

# Override a configured value or choose another config.
python main.py backtest --config config/strategy.yaml --cash 100000 --shares 100

# Download A-share daily data (BaoStock; no personal API key).
python main.py download-a-share --symbol 000001 --start 2026-08-01 --end 2026-08-31 --interval 1d --adjustment raw --output data/raw/000001_1d_2026-08.csv

# Validate and backtest an existing five-minute download.
python main.py validate data/raw/000001_5m_2026-08.csv --interval 5m
python main.py backtest data/raw/000001_5m_2026-08.csv --interval 5m --slippage-bps 5

# Plot the included sample, or another CSV.
python main.py plot --save-only
python main.py plot data/raw/000001_5m_2026-08.csv --save-only

# Show all commands, or the options for one command.
python main.py --help
python main.py backtest --help
```

US downloads use `python main.py download-us` with Alpaca credentials;
see [Data providers](docs/data_sources.md). The sample is included in Git;
the five-minute CSV is a local download. Commands use `main.py` instead of the
former `quantlibrary.*` module paths.

## Configuration and outputs

Edit [config/strategy.yaml](config/strategy.yaml) to choose the CSV, optional
interval/market/adjustment labels, initial cash, shares, fees, and slippage.
Only `strategy: buy_and_hold` is supported. Other strategies are rejected.
Explicit command-line values override YAML values, including zero-valued costs.

Paths written inside YAML are relative to that YAML file's directory.
Paths supplied on the command line are relative to the terminal directory.
The default configuration uses the four-day sample and does not download data.

Backtests save `orders.csv`, `fills.csv`, `equity.csv`, and `summary.json`
under `outputs/backtests/<CSV stem>_buy_hold/`; use `--output-dir` to change it.
Charts go to `outputs/charts/<CSV stem>.png`; use `--output` to change it.
Repeated runs overwrite the selected outputs. Raw/processed data and generated
outputs are ignored by Git; the small sample remains tracked.
The loader normalizes bars in memory and does not write processed CSVs.

The baseline buys at a later eligible open after the first bar, then values
holdings at each close. It does not simulate exchange-specific lot sizes,
settlement, price limits, or separate corporate-action cash flows.

## Use from Python

```python
from src.data.loader import load_stock_csv
from src.backtest.engine import BacktestConfig, run_buy_and_hold

stock = load_stock_csv("data/samples/000001_daily_sample.csv")
result = run_buy_and_hold(stock, BacktestConfig(initial_cash=100000, shares=100))
print(result.summary)
```

## Checks and reference

```powershell
python -m unittest discover -s tests -v
```

- [Data providers](docs/data_sources.md): credentials, download options, CSV units.
- [Data contract](docs/data_contract.md): validation, timestamps, metadata.
- [Backtest details](docs/backtesting.md): execution assumptions and accounting.
