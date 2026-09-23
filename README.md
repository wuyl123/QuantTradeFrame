# QuantLibrary

Stock-data tools and a workspace for building a backtesting pipeline.
Data downloads, CSV validation/normalization, stock charts, and a tested
buy-and-hold accounting baseline work today. General strategy execution and
pipeline orchestration are the next stages.

## Workspace layout

```text
QuantLibrary/
|-- quantlibrary/              # Importable Python code
|   |-- data/                  # Provider adapters and shared CSV loader
|   |-- visualization/         # Stock charts
|   |-- strategies/            # Future trading signals and strategies
|   |-- backtesting/           # Buy-and-hold execution, accounting, and results
|   |-- pipelines/             # Future orchestration of the stages
|   `-- paths.py               # Shared data and output locations
|-- data/
|   |-- samples/               # Small fixtures kept in version control
|   |-- raw/                   # Provider downloads
|   `-- processed/             # Future normalized engine inputs
|-- outputs/
|   |-- charts/                # Generated PNGs
|   `-- backtests/             # Orders, fills, equity, and run summaries
|-- docs/
|   |-- architecture.md        # Responsibilities and planned data flow
|   |-- data_sources.md        # Provider setup and schema details
|   |-- data_contract.md       # Normalized OHLCV format and validation
|   `-- backtesting.md         # Baseline execution rules and accounting example
|-- tests/                     # Offline loader and backtest tests
|-- requirements.txt
`-- README.md
```

`.venv/` stays at the project root. Downloaded data, generated output, credentials,
and Python caches are ignored by Git; small sample fixtures are kept.

## Setup

Use Python 3.10 or newer. In PowerShell, from this directory:

```powershell
# Only needed when creating the environment for the first time.
python -m venv .venv

.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

You can also use `.\.venv\Scripts\python.exe` in place of `python` in every
command below without activating the environment. No editable install is needed;
run module commands from the project root.

## Download data

```powershell
# China A-shares: no API key needed.
python -m quantlibrary.data.a_share --symbol 000001 --start 2026-08-01 --end 2026-08-31 --interval 5m --output data/raw/000001_5m_2026-08.csv

# US stocks: set Alpaca credentials as described in docs/data_sources.md.
python -m quantlibrary.data.us_stock --symbol AAPL --start 2024-01-02 --end 2024-01-31 --interval 1d --output data/raw/AAPL_1d_2024-01.csv
```

Without `--output`, downloaders return and print data without saving a CSV.
An explicit output path is overwritten if it already exists. Use `--help` for
all options. The default date range is the recent week through yesterday.

Provider-specific timezones, volume units, adjustment settings, credentials,
and available intervals are documented in [Data providers](docs/data_sources.md).

## Load and validate data

```python
from quantlibrary.data.loader import load_stock_csv
from quantlibrary.paths import RAW_DATA_DIR

stock = load_stock_csv(RAW_DATA_DIR / "000001_5m_2026-08.csv", interval="5m")
print(stock.metadata)
print(stock.bars.head())
```

`stock.bars` has a sorted, unique UTC index named `timestamp`, with columns
`open`, `high`, `low`, `close`, and `volume`. Volume is normalized to shares;
additional provider columns, such as `trading_status`, are preserved. Metadata
records the symbol, market, currency, interval, source, and adjustment setting.

The loader rejects invalid data instead of filling or dropping it. It reads
without changing the CSV and does not save a processed file automatically.
Daily `date` columns imply `1d`. For timestamp-based files, provide `interval`
unless the CSV contains that metadata; filenames and gaps are not used to guess.
Unknown adjustment settings stay `None`; prices are never adjusted by the loader.

To validate a file from the terminal:

```powershell
python -m quantlibrary.data.loader data/samples/000001_daily_sample.csv
python -m quantlibrary.data.loader data/raw/000001_5m_2026-08.csv --interval 5m
```

Daily dates are session labels mapped to market-local midnight, then converted
to UTC. They are not execution times. See [Normalized data](docs/data_contract.md)
for timezone rules, overrides, and the complete validation contract. The current
stock chart still reads the original provider CSV directly.

Run the offline checks with:

```powershell
python -m unittest discover -s tests -v
```

## Run the buy-and-hold baseline

```powershell
# Use the included daily sample; defaults to 100,000 cash and 100 shares.
python -m quantlibrary.backtesting.buy_and_hold

# Run the existing intraday data with explicit costs and quantity.
python -m quantlibrary.backtesting.buy_and_hold data/raw/000001_5m_2026-08.csv --interval 5m --cash 100000 --shares 100 --commission-rate 0.001 --slippage-bps 5
```

The baseline submits one buy after the first bar, fills at a later eligible bar's
open, and values the holdings at each close. Zero-volume and suspended bars defer
execution. Insufficient cash, including fees, rejects the order. Ending holdings
remain open and are valued at the final close.

Results are saved to `outputs/backtests/<CSV stem>_buy_hold/`: `orders.csv`,
`fills.csv`, `equity.csv`, and `summary.json`. Repeating a run replaces these four
files. Use `--output-dir` to keep separate scenarios. The summary records the
configuration, input metadata, return, maximum drawdown, and simulation assumptions.
Costs are configurable illustrative inputs, not a venue-specific fee schedule.

```python
from quantlibrary.backtesting.buy_and_hold import BacktestConfig, run_buy_and_hold
from quantlibrary.data.loader import load_stock_csv
from quantlibrary.paths import SAMPLE_DATA_DIR

stock = load_stock_csv(SAMPLE_DATA_DIR / "000001_daily_sample.csv")
result = run_buy_and_hold(stock, BacktestConfig(initial_cash=100000, shares=100))
print(result.summary)
print(result.equity_curve)
```

See [Backtesting baseline](docs/backtesting.md) for the hand-calculated example,
the timing contract, and the limits of this simple execution model.

## Visualize data

```powershell
# Plot the included four-day sample and open a window.
python -m quantlibrary.visualization.stock

# Plot the existing five-minute August dataset without opening a window.
python -m quantlibrary.visualization.stock data/raw/000001_5m_2026-08.csv --save-only

# Choose a different PNG output location.
python -m quantlibrary.visualization.stock --save-only --output outputs/charts/sample.png
```

Default PNGs go to `outputs/charts/<CSV stem>.png`; running again replaces that
chart. The sample produces `outputs/charts/000001_daily_sample.png`. Output
folders are created as needed. Close the chart window to finish an interactive run.

Charts show closing price, trading volume, the latest close, change from the
first close, the closing-price range, and average volume per observation.
Volume bars are teal for an increase, coral for a decrease, and gray for an
unchanged close or the first observation. Dates are equally spaced to compress
non-trading gaps; labels retain the actual dates/times. PNGs use 200 dpi.

Use one stock per CSV. A-share prices are labeled CNY and volume in lots; US
prices are labeled USD and volume in shares. Prices retain the CSV's adjustment
setting. The sample contains only four trading days.

## Import from Python

```python
from quantlibrary.data.a_share import get_a_share
from quantlibrary.data.us_stock import get_us_stock
from quantlibrary.visualization.stock import visualize_stock
from quantlibrary.paths import RAW_DATA_DIR

cn_bars = get_a_share("000001", "2024-01-02", "2024-01-31", interval="1d")
us_bars = get_us_stock("AAPL", "2024-01-02", "2024-01-31", interval="1h")
chart = visualize_stock(RAW_DATA_DIR / "000001_5m_2026-08.csv", show=False)
```

Shared defaults resolve from the project location. Explicit relative paths
resolve from the current working directory.

## File moves

| Previous location | New location |
| --- | --- |
| `a_share_example.py` | `quantlibrary/data/a_share.py` |
| `us_stock_example.py` | `quantlibrary/data/us_stock.py` |
| `visualize.py` | `quantlibrary/visualization/stock.py` |
| `data/000001_daily_sample.csv` | `data/samples/000001_daily_sample.csv` |
| `data/000001_daily_2026-08.csv` | `data/raw/000001_5m_2026-08.csv` |
| `data/*.png` | `outputs/charts/` |

The August filename now reflects its five-minute bars; its contents are
unchanged. Its chart is now `outputs/charts/000001_5m_2026-08.png`.
Use the module commands above in place of the old root scripts.

See [Pipeline layout](docs/architecture.md) for the next stages and their
responsibilities.
