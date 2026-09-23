# Normalized data

`quantlibrary.data.loader.load_stock_csv()` reads one stock CSV and returns a
`StockData` object containing `bars` (a pandas DataFrame) and `metadata` (a frozen
`StockMetadata` dataclass). It performs no downloads and never modifies the input.

```python
from quantlibrary.data.loader import load_stock_csv
from quantlibrary.paths import RAW_DATA_DIR, SAMPLE_DATA_DIR

daily = load_stock_csv(SAMPLE_DATA_DIR / "000001_daily_sample.csv")
intraday = load_stock_csv(RAW_DATA_DIR / "000001_5m_2026-08.csv", interval="5m")

# An Alpaca export does not record interval/adjustment. Declare them when known.
us = load_stock_csv("data/raw/AAPL_1d_2024-01.csv", interval="1d", adjustment="raw")
```

## Bar format

| Field | Convention |
| --- | --- |
| Index | Unique, ascending, timezone-aware `DatetimeIndex`, named `timestamp`, in UTC |
| `open`, `high`, `low`, `close` | Positive, finite `float64` prices, in the original currency and adjustment convention |
| `volume` | Nonnegative, finite `float64` volume in shares |
| Remaining columns | Provider-specific fields retained after OHLCV, with pandas' parsed types |

The symbol is recorded once in metadata. Input `date`/`timestamp`, `symbol`,
`market`, `interval`, `source`, `adjustment`, and `volume_lots` are consumed during
normalization. Extra fields, including `trading_status`, `turnover_cny`, and
`trade_count`, are preserved; they are not independently validated or converted.
Rows with zero volume are retained. Invalid required values in suspended-stock
rows still fail validation; the loader never drops those rows silently.

`volume_lots` is multiplied by 100. Fractional shares remain representable; no
rounding or integer truncation occurs. `volume` is already shares and is not
rescaled. Missing bars, overnight gaps, and weekends are not filled or resampled.

## Metadata and overrides

| Field / argument | Rule |
| --- | --- |
| `symbol` | Required, nonblank, one stock per file; leading zeros are preserved |
| `market` | `a_share` or `us`; argument or CSV column wins, otherwise infer A-shares from `volume_lots` and US from `volume` |
| `currency` | `CNY` for A-shares, `USD` for US stocks |
| `interval` | `1m`, `5m`, `15m`, `30m`, `1h`, or `1d`; argument or CSV column, otherwise only a `date` column implies `1d` |
| `source` | CSV value, or `None` when absent; never guessed from a filename |
| `adjustment` | Argument or CSV value, or `None` when unknown |
| `market_timezone` | `Asia/Shanghai` or `America/New_York` |
| `naive_timezone` | IANA timezone used only for input values without explicit offsets |
| `timezone` | Always `UTC` in the normalized frame |
| `input_volume_unit` / `volume_unit` | Original `lots` or `shares` / normalized `shares` |
| `timestamp_kind` | `session_date` for a daily `date` column, otherwise `provider_timestamp` |

CSV metadata and an explicit argument must agree. Metadata columns may be absent
or entirely blank when optional, but partially missing or mixed values are
rejected. A-share adjustments support `raw`, `qfq`, and `hfq`; US adjustments
support `raw`, `split`, `dividend`, and `all`. These labels describe existing
prices; setting a label does not transform prices.

The market inference targets this project's two provider exports. For another
A-share CSV whose volume is already in shares, pass `market="a_share"` explicitly.
Both volume columns in one input are ambiguous and are rejected.

## Time conventions

- A `date` column must contain `YYYY-MM-DD` session labels. It requires `1d`.
  The loader localizes midnight in the market timezone and converts to UTC.
  For example, `2024-01-02` in Shanghai becomes `2024-01-01 16:00:00+00:00`.
  This is a session identifier, **not the time its closing price became known**.
- A `timestamp` column accepts ISO 8601 dates/times, with an optional `Z` or
  numeric UTC offset. Naive A-share timestamps default to `Asia/Shanghai`;
  naive US timestamps default to UTC, matching the project exporters.
- For other naive timestamp sources, pass `naive_timezone="America/New_York"`
  or another IANA name. Daily `date` labels always use the market timezone.
- Explicit offsets are respected; `naive_timezone` does not reinterpret them.
  Mixed explicit offsets across daylight-saving changes are supported. Mixing
  timezone-aware and timezone-naive values in one file is rejected.
- Ambiguous or nonexistent local times during daylight-saving transitions are
  rejected. Provide explicit offsets for such timestamps. Abbreviations such as
  `EST` are not accepted in timestamps.

The loader retains each provider's timestamp meaning. A future engine adapter
must establish when a bar becomes available, including whether its label denotes
a session, a bar start, or a bar end. The loader does not fabricate execution
times or shift timestamps to market close.

## Validation

Errors raise `DataValidationError`, a subclass of `ValueError`. File access
errors retain their usual `OSError` types. The checks include:

- Nonempty data, well-formed CSV rows, and distinct column names after trimming
  whitespace and converting names to lowercase.
- Exactly one `date` or `timestamp` column, one volume column, all OHLC columns,
  and a consistent nonblank symbol.
- Valid timestamps and no duplicates after UTC conversion. Unsorted rows are
  sorted with their prices and auxiliary fields kept together.
- Numeric, finite, nonmissing OHLCV; strictly positive prices; nonnegative volume;
  and `low <= open/close <= high` for each row.
- A consistent market, source, interval, and adjustment convention.
- At most one daily bar per market-local date. Intraday timestamps cannot be
  closer together than the declared interval. Gaps are allowed; this check does
  not prove bar duration or complete trading-session coverage.

The CLI prints metadata and a preview without creating files:

```powershell
python -m quantlibrary.data.loader data/raw/000001_5m_2026-08.csv --interval 5m
python -m quantlibrary.data.loader --help
python -m unittest discover -s tests -v
```
