"""Download A-share price bars using BaoStock (python -m src.data.a_share)."""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import baostock as bs
import pandas as pd


INTERVALS = {"5m": "5", "15m": "15", "30m": "30", "1h": "60", "1d": "d"}
ADJUSTMENTS = {"raw": "3", "qfq": "2", "hfq": "1"}
COLUMN_NAMES = {
    "code": "symbol",
    "preclose": "previous_close",
    "amount": "turnover_cny",
    "turn": "turnover_rate_pct",
    "pctChg": "change_pct",
    "tradestatus": "trading_status",
    "isST": "is_st",
}


def get_a_share(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    adjustment: str = "raw",
) -> pd.DataFrame:
    """Return English column names for inclusive YYYY-MM-DD dates.

    Use a six-digit Shanghai/Shenzhen symbol, e.g. '000001' or '600519'.
    No API key is needed. BaoStock does not provide one-minute bars.
    Dates/times use China local time. volume_lots is in lots, not shares.
    Missing numeric values stay missing; suspended-stock rows are retained.
    """
    if not isinstance(symbol, str) or len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
        raise ValueError("symbol must be a six-digit string, e.g. '000001'")
    if interval not in INTERVALS:
        raise ValueError(f"BaoStock intervals: {', '.join(INTERVALS)}; 1m is not supported")
    if adjustment not in ADJUSTMENTS:
        raise ValueError("adjustment must be raw, qfq or hfq")
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    if start_day > end_day:
        raise ValueError("start must be on or before end")
    if symbol.startswith("6"):
        stock_code = f"sh.{symbol}"
    elif symbol.startswith(("0", "3")):
        stock_code = f"sz.{symbol}"
    else:
        raise ValueError("This example supports Shanghai/Shenzhen A-share codes starting with 0, 3 or 6")

    fields = "date,code,open,high,low,close,volume,amount"
    if interval == "1d":
        fields += ",preclose,turn,pctChg,tradestatus,isST"
    else:
        fields += ",time"

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed ({login.error_code}): {login.error_msg}")
    try:
        result = bs.query_history_k_data_plus(
            stock_code, fields,
            start_date=start_day.isoformat(),
            end_date=end_day.isoformat(),
            frequency=INTERVALS[interval],
            adjustflag=ADJUSTMENTS[adjustment],
        )
        rows = []
        while result.error_code == "0" and result.next():
            rows.append(result.get_row_data())
        if result.error_code != "0":
            raise RuntimeError(f"BaoStock query failed ({result.error_code}): {result.error_msg}")
        data = pd.DataFrame(rows, columns=result.fields)
    finally:
        # Always close the session, including when a query fails.
        bs.logout()

    if data.empty:
        raise ValueError("No bars returned. Check the symbol, dates and market holidays.")
    if not data["code"].eq(stock_code).all():
        raise ValueError("BaoStock returned a different stock code than requested")

    # BaoStock returns strings; convert numbers without turning missing data into zero.
    for column in data.columns.difference(["date", "time", "code"]):
        data[column] = pd.to_numeric(data[column].replace("", float("nan")))
    data = data.rename(columns=COLUMN_NAMES)
    data["symbol"] = symbol
    # BaoStock volume is shares. Keep the existing CSV/chart unit of 100-share lots.
    data["volume_lots"] = data.pop("volume") / 100
    if interval == "1d":
        time_column = "date"
        data[time_column] = pd.to_datetime(data[time_column], format="%Y-%m-%d")
    else:
        time_column = "timestamp"
        timestamps = pd.to_datetime(data.pop("time"), format="%Y%m%d%H%M%S%f")
        data = data.drop(columns="date")
        data.insert(0, time_column, timestamps)
    data["source"] = "baostock"
    data["adjustment"] = adjustment
    first_columns = [time_column, "symbol", "open", "high", "low", "close", "volume_lots", "turnover_cny"]
    data = data[first_columns + [column for column in data.columns if column not in first_columns]]
    return data.sort_values(time_column).reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    yesterday = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="000001")
    parser.add_argument("--start", help="YYYY-MM-DD; defaults to seven days before --end")
    parser.add_argument("--end", default=yesterday.isoformat())
    parser.add_argument("--interval", choices=INTERVALS, default="1d")
    parser.add_argument("--adjustment", choices=("raw", "qfq", "hfq"), default="qfq")
    parser.add_argument("--output", type=Path, help="Optional CSV path")
    args = parser.parse_args(argv)

    try:
        start = args.start or (date.fromisoformat(args.end) - timedelta(days=7)).isoformat()
        data = get_a_share(args.symbol, start, args.end, args.interval, args.adjustment)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            data.to_csv(args.output, index=False, encoding="utf-8-sig")
            print(f"Saved {len(data)} rows to {args.output.resolve()}")
        time_column = "date" if args.interval == "1d" else "timestamp"
        print(f"Returned {len(data)} bars: {data[time_column].min()} to {data[time_column].max()}")
        print("Times are China local time; volume_lots is in lots, not shares.")
        print(data.head(10).to_string(index=False))
    except Exception as exc:
        parser.exit(1, f"Download failed: {exc}\n")


if __name__ == "__main__":
    main()
