# Pipeline layout

The working stages are data download, shared CSV loading/validation, stock
visualization, and a buy-and-hold accounting baseline. General strategy logic
and pipeline orchestration remain extension points. The baseline is a small
local simulator with no additional dependencies.

## Responsibilities

| Location | Responsibility | Status |
| --- | --- | --- |
| `quantlibrary/data/` | Provider adapters and a common validated OHLCV loader | Implemented |
| `quantlibrary/visualization/` | Stock charts; future equity and drawdown charts | Stock charts implemented |
| `quantlibrary/strategies/` | Indicators, signals, and strategy parameters | Reserved |
| `quantlibrary/backtesting/` | Order execution, cash, positions, fees, and metrics | Buy-and-hold baseline implemented |
| `quantlibrary/pipelines/` | Connect stages into repeatable runs | Reserved |
| `quantlibrary/paths.py` | Shared workspace data and output paths | Implemented |

Keep provider access inside `data`, trading decisions inside `strategies`, and
execution/accounting inside `backtesting`. Pipelines call those components and
hand results to visualization. Importing a module must not download data, run a
backtest, or open a chart window.

## Data flow

```text
Provider downloads -> data/raw/ -> validation / normalization -> data/processed/
                                                                   |
                                                            strategy signals
                                                                   |
                                                               backtesting
                                                                   |
                                                         outputs/backtests/
                                                                   |
                                                          outputs/charts/
```

The current visualization can read either a sample or a raw CSV directly.
The common loader returns normalized bars and metadata in memory; writing
processed datasets will belong to pipeline orchestration. The buy-and-hold
baseline consumes `StockData` and returns `BacktestResult`, with order, fill, and
equity tables plus a summary. Its CLI saves these records under `outputs/backtests`.
General strategy execution and performance charts are the next stages to build.

## File conventions

- `data/samples/`: small, reproducible fixtures that can be committed.
- `data/raw/`: provider downloads, preserved as exported by the existing loaders.
- `data/processed/`: future normalized inputs for the engine.
- `outputs/charts/`: generated PNGs.
- `outputs/backtests/`: run summaries, orders, fills, and equity curves.

Use descriptive names such as `<symbol>_<interval>_<period>.csv`. The August
dataset is `data/raw/000001_5m_2026-08.csv`: its 1,008 rows are five-minute bars,
despite the old filename containing `daily`. Its contents were preserved.

Raw provider schemas currently differ: A-share timestamps are China local time
and `volume_lots` counts 100-share lots; US timestamps are UTC and `volume`
counts shares. `quantlibrary/data/loader.py` normalizes timestamps to UTC and
volume to shares, validates OHLCV data, and records explicit interval and
price-adjustment metadata. See [Normalized data](data_contract.md) for the
contract. Chart-only compression of non-trading gaps does not change CSV timestamps.

## Running modules

Run from the project root with the virtual environment active:

```powershell
python -m quantlibrary.data.a_share --help
python -m quantlibrary.data.us_stock --help
python -m quantlibrary.data.loader data/raw/000001_5m_2026-08.csv --interval 5m
python -m quantlibrary.backtesting.buy_and_hold
python -m quantlibrary.visualization.stock --save-only
```

The package is directly importable from the project root; no editable install or
`PYTHONPATH` changes are required. Shared default paths are anchored to the
workspace, while explicit relative input/output paths follow the current working
directory. See the root README for complete examples.
