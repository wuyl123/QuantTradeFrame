# Data providers

The modules support `5m`, `15m`, `30m`, `1h`, and `1d`; the US module also
supports `1m`. Both return pandas DataFrames and optionally save OHLCV CSVs.
Run the commands below from the project root after following the
[setup instructions](../README.md#setup).

## US stocks: Alpaca

Create an Alpaca account and generate your own API key and secret. Paper-account
keys can access historical data. Set these locally in your PowerShell session:

```powershell
$env:APCA_API_KEY_ID = "YOUR_API_KEY"
$env:APCA_API_SECRET_KEY = "YOUR_SECRET_KEY"

# Apple daily bars, with both dates included.
.\.venv\Scripts\python.exe -m quantlibrary.data.us_stock --symbol AAPL --start 2024-01-02 --end 2024-01-31 --interval 1d --output data/raw/AAPL_1d_2024-01.csv

# One-minute bars for a historical trading day.
.\.venv\Scripts\python.exe -m quantlibrary.data.us_stock --symbol AAPL --start 2024-01-03 --end 2024-01-03 --interval 1m --output data/raw/AAPL_1m_2024-01-03.csv

# Hourly bars; defaults to the recent week through yesterday.
.\.venv\Scripts\python.exe -m quantlibrary.data.us_stock --symbol MSFT --interval 1h
```

The example explicitly selects the consolidated **SIP** feed. Free historical
access excludes the latest 15 minutes; the code caps the query at 16 minutes ago.
The SDK handles pagination. Credentials stay in environment variables; the
scripts do not load `.env` files or place orders.

Input dates represent New York calendar dates, including daylight-saving changes.
Returned `timestamp` values are UTC; `volume` is in shares. Other returned fields
include `symbol`, `open`, `high`, `low`, `close`, `trade_count` and `vwap`.
Intraday bars may include pre-market and after-hours trading.

Prices default to unadjusted (`--adjustment raw`). You can request `split`,
`dividend`, or `all`. If you include today, an hourly/daily bar may be incomplete.
The default end date is yesterday.

## China A-shares: BaoStock

Pass a six-digit Shanghai/Shenzhen A-share stock code. For example, `000001`
is Ping An Bank and `600519` is Kweichow Moutai. The script adds BaoStock's
exchange prefix internally (`sz.000001` or `sh.600519`). It logs in anonymously
and logs out after reading the result; you do not need a personal API key.

```powershell
# Daily bars for August 2026, with both dates included.
.\.venv\Scripts\python.exe -m quantlibrary.data.a_share --symbol 000001 --start 2026-08-01 --end 2026-08-31 --interval 1d --output data/raw/000001_1d_2026-08.csv

# Five-minute and hourly bars; default dates follow the current date.
.\.venv\Scripts\python.exe -m quantlibrary.data.a_share --symbol 600519 --interval 5m --output data/raw/600519_5m.csv
.\.venv\Scripts\python.exe -m quantlibrary.data.a_share --symbol 600519 --interval 1h

# Forward-adjusted daily prices.
.\.venv\Scripts\python.exe -m quantlibrary.data.a_share --symbol 000001 --interval 1d --adjustment qfq
```

Returned DataFrames and CSVs have English columns:

| Column | Meaning |
| --- | --- |
| `date` / `timestamp` | Trading date / intraday bar time, in China local time |
| `symbol` | Six-digit stock code, preserved as text |
| `open` / `high` / `low` / `close` | Prices in CNY |
| `volume_lots` | Volume in lots, not shares |
| `turnover_cny` | Traded value in CNY |
| `previous_close` | Previous closing price in CNY (daily only) |
| `change_pct` | Price change, in percent (daily only) |
| `turnover_rate_pct` | Turnover rate, in percent (daily only) |
| `trading_status` | 1 for trading, 0 for suspended (daily only) |
| `is_st` | 1 for special-treatment stock, 0 otherwise (daily only) |
| `source` | `baostock` |
| `adjustment` | Requested setting: `raw`, `qfq`, or `hfq` |

BaoStock reports volume in shares. The script divides it by 100 to keep the
existing `volume_lots` convention used by `quantlibrary.visualization.stock`; fractional lots are
preserved. Percentage values are already percentages: `1.76` means `1.76%`.
Missing numeric values remain missing rather than becoming zero. Daily rows
for suspended stocks are retained and identified by `trading_status`.

Timestamps have no timezone attached; interpret them as `Asia/Shanghai`.
Daily bars use `date`; intraday bars use `timestamp`. CSV files use
UTF-8 with a BOM for convenient opening in Excel. An existing output file is
overwritten when you explicitly select the same `--output` path.

BaoStock offers 5-, 15-, 30-, and 60-minute historical bars, but **not one-minute
bars**. Available history depends on the stock and provider. Daily-only fields
such as turnover rate and trading status are omitted from intraday CSVs.
The script prints the date range actually returned and raises an error for
failed logins, failed queries, or empty results instead of saving an empty CSV.

Use `raw` for unadjusted data, `qfq` for forward-adjusted data, or `hfq` for
backward-adjusted data. BaoStock's adjustment methodology can differ from
Eastmoney's, so avoid silently mixing adjusted history from the two providers.
Use completed trading days when requesting daily history.

The fixture `data/samples/000001_daily_sample.csv` is the earlier four-day
Eastmoney sample. New downloads use BaoStock and include the `source` column.
The existing August download contains five-minute bars and is now named
`data/raw/000001_5m_2026-08.csv`. The daily download command above creates a
separate file. To plot the existing five-minute data:

```powershell
python -m quantlibrary.visualization.stock data/raw/000001_5m_2026-08.csv
```

## Provider documentation

- [Alpaca Python historical data client](https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html)
- [Alpaca SIP access and historical-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)
- [BaoStock package and official usage example](https://pypi.org/project/baostock/)
- [BaoStock website](https://www.baostock.com/)
