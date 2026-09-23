"""Validate and normalize one stock CSV (python -m src.data.loader)."""

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd


OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
INTERVALS = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "1d": pd.Timedelta(days=1),
}
MARKETS = {"a_share": ("CNY", "Asia/Shanghai"), "us": ("USD", "America/New_York")}
ADJUSTMENTS = {
    "a_share": {"raw", "qfq", "hfq"},
    "us": {"raw", "split", "dividend", "all"},
}
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?"
)


class DataValidationError(ValueError):
    """The input cannot safely be interpreted as a single stock's price bars."""


@dataclass(frozen=True)
class StockMetadata:
    """Data conventions; an unknown source or adjustment is represented by None."""

    symbol: str
    market: str
    currency: str
    interval: str
    source: str | None
    adjustment: str | None
    market_timezone: str
    naive_timezone: str
    input_volume_unit: str
    timestamp_kind: str
    timezone: str = "UTC"
    volume_unit: str = "shares"


@dataclass
class StockData:
    """UTC-indexed OHLCV bars followed by any extra provider columns."""

    bars: pd.DataFrame
    metadata: StockMetadata


def _read_csv(path: Path) -> pd.DataFrame:
    # Inspect the header before pandas can silently rename duplicate columns.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader, [])
            for row in reader:
                if row and len(row) != len(header):
                    raise DataValidationError(f"Malformed CSV: wrong field count near line {reader.line_num}")
        except csv.Error as exc:
            raise DataValidationError(f"Malformed CSV: {exc}") from exc
        columns = [name.strip().lower() for name in header]
        if not columns or any(not name for name in columns):
            raise DataValidationError("CSV must have a non-empty header")
        if len(set(columns)) != len(columns):
            raise DataValidationError("CSV has duplicate column names after normalization")
        handle.seek(0)
        symbol_dtype = {header[columns.index("symbol")]: str} if "symbol" in columns else {}
        try:
            data = pd.read_csv(handle, dtype=symbol_dtype, keep_default_na=False)
        except pd.errors.ParserError as exc:
            raise DataValidationError(f"Malformed CSV: {exc}") from exc
    data.columns = columns
    if data.empty:
        raise DataValidationError("CSV must contain at least one price bar")
    return data


def _constant(data: pd.DataFrame, column: str, *, required: bool = False) -> str | None:
    if column not in data:
        if required:
            raise DataValidationError(f"Missing required column: {column}")
        return None
    values = data[column].astype(str).str.strip()
    if not values.ne("").any() and not required:
        return None
    if values.eq("").any():
        raise DataValidationError(f"Column '{column}' must not contain missing values")
    if values.nunique() != 1:
        raise DataValidationError(f"Column '{column}' must contain one consistent value (one stock per CSV)")
    return values.iloc[0]


def _metadata_value(data: pd.DataFrame, column: str, supplied: str | None) -> str | None:
    recorded = _constant(data, column)
    if supplied is not None and recorded is not None and supplied != recorded:
        raise DataValidationError(f"{column}={supplied!r} conflicts with CSV value {recorded!r}")
    return supplied if supplied is not None else recorded


def _timestamps(data: pd.DataFrame, column: str, naive_timezone: str) -> pd.DatetimeIndex:
    values = data[column].astype(str).str.strip()
    if column == "date" and not values.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise DataValidationError("Daily 'date' values must use YYYY-MM-DD without a time")
    parsed = []
    for row, value in enumerate(values, start=2):
        if not value:
            raise DataValidationError(f"Missing {column} at CSV row {row}")
        if column == "timestamp" and not TIMESTAMP_PATTERN.fullmatch(value):
            raise DataValidationError(f"Invalid timestamp at CSV row {row}: use ISO 8601 with an optional UTC offset")
        try:
            stamp = pd.Timestamp(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise DataValidationError(f"Invalid {column} at CSV row {row}: {value!r}") from exc
        if pd.isna(stamp):
            raise DataValidationError(f"Missing {column} at CSV row {row}")
        parsed.append(stamp)
    aware = [stamp.tzinfo is not None for stamp in parsed]
    if any(aware) and not all(aware):
        raise DataValidationError("Do not mix timezone-aware and timezone-naive timestamps in one CSV")
    try:
        if all(aware):
            # Explicit offsets define instants, including offset changes across DST.
            index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
        else:
            index = pd.DatetimeIndex(parsed).tz_localize(
                naive_timezone, ambiguous="raise", nonexistent="raise",
            ).tz_convert("UTC")
    except Exception as exc:
        # pandas' timezone backends use different exception types for DST errors.
        raise DataValidationError(f"Cannot interpret timestamps in {naive_timezone}: {exc}") from exc
    if index.has_duplicates:
        duplicate = index[index.duplicated()][0]
        raise DataValidationError(f"Duplicate timestamp after UTC conversion: {duplicate}")
    return index.rename("timestamp")


def _numeric_column(data: pd.DataFrame, column: str) -> pd.Series:
    numbers = pd.to_numeric(data[column].astype(str), errors="coerce").astype(float)
    invalid = ~np.isfinite(numbers)
    if invalid.any():
        row = int(np.flatnonzero(invalid.to_numpy())[0]) + 2
        raise DataValidationError(f"'{column}' must be numeric, finite, and non-missing (CSV row {row})")
    return numbers


def load_stock_csv(
    csv_path: str | Path,
    *,
    market: str | None = None,
    interval: str | None = None,
    adjustment: str | None = None,
    naive_timezone: str | None = None,
) -> StockData:
    """Load either provider export without modifying the source file.

    Infer a_share from volume_lots, otherwise us from volume, unless market is
    supplied or recorded. Daily date columns imply 1d; timestamp-based files
    require interval in the CSV or as an argument. Missing adjustment stays None.

    Naive A-share timestamps use Asia/Shanghai; naive US timestamps use UTC.
    Daily date labels use market-local midnight and remain session labels, not
    execution times. Explicit timestamp offsets are always respected. Naive
    timezone overrides must be IANA names. Ambiguous DST times are rejected.

    Bars have a sorted, unique UTC DatetimeIndex named timestamp. The leading
    columns are open, high, low, close, volume (float64; volume is shares).
    Additional provider columns are retained as read, including trading_status.
    No rows are filled, dropped, resampled, or price-adjusted.
    """
    data = _read_csv(Path(csv_path))
    time_columns = [name for name in ("date", "timestamp") if name in data]
    volume_columns = [name for name in ("volume_lots", "volume") if name in data]
    if len(time_columns) != 1:
        raise DataValidationError("CSV must contain exactly one time column: date or timestamp")
    if len(volume_columns) != 1:
        raise DataValidationError("CSV must contain exactly one volume column: volume_lots or volume")
    missing = [name for name in OHLCV_COLUMNS[:4] if name not in data]
    if missing:
        raise DataValidationError(f"Missing required OHLC columns: {', '.join(missing)}")
    time_column, volume_column = time_columns[0], volume_columns[0]
    symbol = _constant(data, "symbol", required=True)
    source = _constant(data, "source")
    market = _metadata_value(data, "market", market)
    if market is None:
        market = "a_share" if volume_column == "volume_lots" else "us"
    if market not in MARKETS:
        raise DataValidationError(f"market must be one of: {', '.join(MARKETS)}")
    if volume_column == "volume_lots" and market != "a_share":
        raise DataValidationError("volume_lots is only supported for the a_share market")
    currency, market_timezone = MARKETS[market]

    interval = _metadata_value(data, "interval", interval)
    if interval is None and time_column == "date":
        interval = "1d"
    if interval not in INTERVALS:
        raise DataValidationError(f"Specify interval explicitly: {', '.join(INTERVALS)} (do not infer it from gaps)")
    if time_column == "date" and interval != "1d":
        raise DataValidationError("A daily date column requires interval='1d'")
    adjustment = _metadata_value(data, "adjustment", adjustment)
    if adjustment is not None and adjustment not in ADJUSTMENTS[market]:
        raise DataValidationError(f"Unsupported adjustment {adjustment!r} for market {market!r}")

    if time_column == "date" and naive_timezone not in (None, market_timezone):
        raise DataValidationError(f"Daily date labels use the market timezone {market_timezone}")
    if naive_timezone is None:
        naive_timezone = market_timezone if time_column == "date" or market == "a_share" else "UTC"
    try:
        ZoneInfo(naive_timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise DataValidationError(f"Unknown IANA timezone: {naive_timezone!r}") from exc
    index = _timestamps(data, time_column, naive_timezone)

    prices = pd.DataFrame({name: _numeric_column(data, name) for name in OHLCV_COLUMNS[:4]})
    if prices.le(0).any().any():
        raise DataValidationError("OHLC prices must be strictly positive")
    inconsistent = (
        prices["low"].gt(prices[["open", "close"]].min(axis=1))
        | prices["high"].lt(prices[["open", "close"]].max(axis=1))
        | prices["low"].gt(prices["high"])
    )
    if inconsistent.any():
        row = int(np.flatnonzero(inconsistent.to_numpy())[0]) + 2
        raise DataValidationError(f"Inconsistent OHLC: low <= open/close <= high is required (CSV row {row})")
    volume = _numeric_column(data, volume_column)
    if volume.lt(0).any():
        raise DataValidationError("Volume must not be negative")
    with np.errstate(over="ignore"):
        prices["volume"] = volume * (100 if volume_column == "volume_lots" else 1)
    if not np.isfinite(prices["volume"]).all():
        raise DataValidationError("Volume overflows when converted to shares")

    excluded = set(OHLCV_COLUMNS) | {
        time_column, volume_column, "symbol", "source", "adjustment", "market", "interval",
    }
    extras = [name for name in data if name not in excluded]
    bars = pd.concat([prices, data[extras]], axis=1)
    bars.index = index
    bars = bars.sort_index(kind="stable")
    if interval == "1d":
        sessions = bars.index.tz_convert(market_timezone).date
        if pd.Index(sessions).has_duplicates:
            raise DataValidationError("Daily data must contain at most one bar per market-local date")
    elif (bars.index.to_series().diff().dropna() < INTERVALS[interval]).any():
        raise DataValidationError(f"Timestamp spacing is shorter than the declared {interval} interval")

    return StockData(
        bars=bars,
        metadata=StockMetadata(
            symbol=symbol, market=market, currency=currency, interval=interval,
            source=source, adjustment=adjustment, market_timezone=market_timezone,
            naive_timezone=naive_timezone,
            input_volume_unit="lots" if volume_column == "volume_lots" else "shares",
            timestamp_kind="session_date" if time_column == "date" else "provider_timestamp",
        ),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Single-stock OHLCV CSV")
    parser.add_argument("--market", choices=MARKETS, help="Defaults to the input volume convention")
    parser.add_argument("--interval", choices=INTERVALS, help="Required for timestamps unless recorded in the CSV")
    parser.add_argument("--adjustment", help="Declare a known adjustment when the CSV does not record it")
    parser.add_argument("--naive-timezone", help="IANA timezone for timestamps without an explicit offset")
    args = parser.parse_args(argv)
    try:
        stock = load_stock_csv(args.csv, market=args.market, interval=args.interval,
                               adjustment=args.adjustment, naive_timezone=args.naive_timezone)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not load stock data: {exc}\n")
    print(json.dumps(asdict(stock.metadata), indent=2))
    print(f"Validated {len(stock.bars):,} bars: {stock.bars.index[0]} to {stock.bars.index[-1]}")
    print(stock.bars.head().to_string())


if __name__ == "__main__":
    main()
