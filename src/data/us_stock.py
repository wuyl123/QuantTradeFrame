"""Download US price bars using Alpaca (python -m src.data.us_stock)."""

import argparse
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


INTERVALS = {
    "1m": TimeFrame(1, TimeFrameUnit.Minute),
    "5m": TimeFrame(5, TimeFrameUnit.Minute),
    "15m": TimeFrame(15, TimeFrameUnit.Minute),
    "30m": TimeFrame(30, TimeFrameUnit.Minute),
    "1h": TimeFrame.Hour,
    "1d": TimeFrame.Day,
}


def get_us_stock(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    adjustment: str = "raw",
) -> pd.DataFrame:
    """Return Alpaca bars for inclusive YYYY-MM-DD dates in New York time.

    Credentials come from APCA_API_KEY_ID and APCA_API_SECRET_KEY.
    Output timestamps are UTC; volume is in shares. Intraday bars can include
    extended-hours trading. Today's data stops at least 16 minutes ago and
    may include an incomplete hourly/daily bar.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {', '.join(INTERVALS)}")
    price_adjustment = Adjustment(adjustment)
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    if start_day > end_day:
        raise ValueError("start must be on or before end")

    market_tz = ZoneInfo("America/New_York")
    start_time = datetime.combine(start_day, time.min, tzinfo=market_tz)
    end_time = datetime.combine(end_day, time.max, tzinfo=market_tz)
    # Free SIP historical access excludes the most recent 15 minutes.
    end_time = min(end_time, datetime.now(timezone.utc) - timedelta(minutes=16))
    if start_time >= end_time:
        raise ValueError("The requested dates contain no accessible history yet")

    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError(
            "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in your environment. "
            "See README.md for PowerShell setup."
        )

    client = StockHistoricalDataClient(api_key, secret_key)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=INTERVALS[interval],
        start=start_time,
        end=end_time,
        feed=DataFeed.SIP,
        adjustment=price_adjustment,
    )
    # With no total limit, the SDK follows pagination for the requested range.
    bars = client.get_stock_bars(request)
    if not bars.data.get(symbol):
        raise ValueError("No bars returned. Check the symbol, dates and market holidays.")
    return bars.df.reset_index().sort_values("timestamp").reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--start", help="YYYY-MM-DD; defaults to seven days before --end")
    parser.add_argument("--end", default=yesterday.isoformat())
    parser.add_argument("--interval", choices=INTERVALS, default="1d")
    parser.add_argument("--adjustment", choices=("raw", "split", "dividend", "all"), default="raw")
    parser.add_argument("--output", type=Path, help="Optional CSV path")
    args = parser.parse_args(argv)

    try:
        start = args.start or (date.fromisoformat(args.end) - timedelta(days=7)).isoformat()
        data = get_us_stock(args.symbol, start, args.end, args.interval, args.adjustment)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            data.to_csv(args.output, index=False, encoding="utf-8-sig")
            print(f"Saved {len(data)} rows to {args.output.resolve()}")
        print(f"Returned {len(data)} bars; timestamps are UTC, volume is in shares.")
        print(data.head(10).to_string(index=False))
    except Exception as exc:
        parser.exit(1, f"Download failed: {exc}\n")


if __name__ == "__main__":
    main()
