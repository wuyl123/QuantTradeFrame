"""Plot closing price and trading volume (python -m src.evaluation.visualize)."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator
import numpy as np
import pandas as pd

from src.utils.paths import CHARTS_DIR, SAMPLE_DATA_DIR


DEFAULT_CSV = SAMPLE_DATA_DIR / "000001_daily_sample.csv"

COLORS = {
    "background": "#F4F6FA",
    "surface": "#FFFFFF",
    "text": "#172B45",
    "muted": "#758398",
    "grid": "#E9EEF4",
    "line": "#2478B8",
    "up": "#158578",
    "down": "#D16961",
    "flat": "#A7B4C5",
}


def _compact_number(value: float, _position: float | None = None) -> str:
    """Keep volume labels readable at both daily and intraday scales."""
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= scale:
            return f"{value / scale:,.2f}".rstrip("0").rstrip(".") + suffix
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _add_card(fig: plt.Figure, bounds: tuple[float, float, float, float]) -> None:
    fig.add_artist(FancyBboxPatch(
        bounds[:2], bounds[2], bounds[3],
        boxstyle="round,pad=0.008,rounding_size=0.014",
        transform=fig.transFigure, facecolor=COLORS["surface"],
        edgecolor=COLORS["grid"], linewidth=0.8, zorder=-1,
    ))


def _build_chart(
    data: pd.DataFrame, time_column: str, volume_column: str,
    symbol: str, currency: str, volume_unit: str, is_a_share: bool,
) -> plt.Figure:
    """Build a dashboard with evenly spaced observations and a shared timeline."""
    times = data[time_column]
    prices = data["close"].to_numpy(dtype=float)
    volumes = data[volume_column].to_numpy(dtype=float)
    positions = np.arange(len(data))
    first, latest = prices[0], prices[-1]
    low, high = prices.min(), prices.max()
    change = (latest / first - 1) * 100 if first != 0 else None
    change_color = COLORS["flat"] if change is None or change == 0 else COLORS[
        "up" if change > 0 else "down"
    ]
    # Retain useful precision for stocks priced below one currency unit.
    nonzero_prices = np.abs(prices[prices != 0])
    decimals = 2 if not len(nonzero_prices) else max(
        2, min(8, 2 - int(np.floor(np.log10(nonzero_prices.min()))))
    )

    def price_label(value: float) -> str:
        return f"{value:,.{decimals}f}"

    timezone = "Asia/Shanghai" if is_a_share else "UTC"
    daily = time_column == "date"
    market = "A-SHARE" if is_a_share else "US EQUITY"
    date_range = f"{times.iloc[0]:%d %b %Y}  –  {times.iloc[-1]:%d %b %Y}"
    fig = plt.figure(figsize=(14, 9), facecolor=COLORS["background"])
    fig.text(0.06, 0.946, "MARKET OVERVIEW  /  PRICE & VOLUME", fontsize=10,
             weight="bold", color=COLORS["muted"])
    fig.text(0.06, 0.883, str(symbol), fontsize=32, weight="bold", color=COLORS["text"])
    fig.text(0.06, 0.85, f"{market}  /  {currency}", fontsize=10, color=COLORS["muted"])
    fig.text(0.94, 0.908, date_range, ha="right", fontsize=12, color=COLORS["text"])
    fig.text(0.94, 0.875, f"{len(data):,} {'daily' if daily else 'intraday'} observations  ·  {timezone}",
             ha="right", fontsize=10, color=COLORS["muted"])

    _add_card(fig, (0.055, 0.713, 0.89, 0.106))
    metrics = [
        ("LATEST CLOSE", price_label(latest), currency, COLORS["text"]),
        ("PERIOD CHANGE", f"{change:+.2f}%" if change is not None else "N/A",
         "from first close" if change is not None else "first close is zero", change_color),
        ("CLOSING RANGE", f"{price_label(low)} – {price_label(high)}", "low / high", COLORS["text"]),
        ("AVERAGE VOLUME", _compact_number(volumes.mean()), f"{volume_unit} / observation", COLORS["text"]),
    ]
    for index, (label, value, note, color) in enumerate(metrics):
        left = 0.075 + index * 0.2225
        fig.text(left, 0.792, label, fontsize=8.5, weight="bold", color=COLORS["muted"])
        value_size = 20 if index == 2 else 25
        if len(value) > 17:
            value_size = 15
        fig.text(left, 0.752, value, fontsize=value_size, weight="bold", color=color)
        fig.text(left, 0.729, note, fontsize=9, color=COLORS["muted"])
        if index:
            fig.add_artist(Line2D([left - 0.02, left - 0.02], [0.732, 0.795],
                                  transform=fig.transFigure, color=COLORS["grid"], linewidth=1))

    _add_card(fig, (0.055, 0.105, 0.89, 0.58))
    price_ax = fig.add_axes((0.075, 0.325, 0.80, 0.292))
    volume_ax = fig.add_axes((0.075, 0.166, 0.80, 0.085), sharex=price_ax)
    fig.text(0.075, 0.647, "Closing price", fontsize=13, weight="bold", color=COLORS["text"])
    fig.text(0.925, 0.647, currency, fontsize=10, ha="right", color=COLORS["muted"])
    fig.text(0.075, 0.276, "Trading volume", fontsize=11, weight="bold", color=COLORS["text"])
    fig.text(0.925, 0.276, volume_unit, fontsize=10, ha="right", color=COLORS["muted"])

    for axis in (price_ax, volume_ax):
        axis.set_facecolor(COLORS["surface"])
        axis.spines[:].set_visible(False)
        axis.set_axisbelow(True)
        axis.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
        axis.yaxis.tick_right()
        axis.tick_params(axis="both", which="both", length=0, pad=10,
                         labelsize=9, colors=COLORS["muted"])
    price_ax.tick_params(axis="x", labelbottom=False)
    price_ax.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=3))
    price_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, pos: price_label(value)))
    padding = max((high - low) * 0.18, abs(latest) * 0.003, 3 * 10 ** -decimals)
    price_ax.set_ylim(low - padding, high + padding)
    horizontal_padding = max(0.5, (len(data) - 1) * 0.012)
    price_ax.set_xlim(-horizontal_padding, len(data) - 1 + horizontal_padding)
    price_ax.fill_between(positions, prices, low - padding,
                          color=COLORS["line"], alpha=0.065, zorder=1)
    price_ax.axhline(first, color=COLORS["flat"], linewidth=1,
                     linestyle=(0, (4, 4)), zorder=2)
    price_ax.plot(positions, prices, color=COLORS["line"], linewidth=2.2,
                  solid_capstyle="round", marker="o" if len(data) <= 20 else None,
                  markersize=5, markeredgecolor="white", markeredgewidth=1.4, zorder=3)
    price_ax.scatter([positions[-1]], [latest], s=52, color=COLORS["line"],
                     edgecolors="white", linewidths=1.6, zorder=4)
    # Put the latest-price tag inside the plot so it cannot cover y-axis labels.
    price_ax.annotate(price_label(latest), xy=(positions[-1], latest),
                      xytext=(-12, 14), textcoords="offset points", ha="right",
                      fontsize=9, weight="bold", color="white", zorder=5,
                      bbox={"boxstyle": "round,pad=0.45", "facecolor": COLORS["line"], "edgecolor": "none"})
    price_ax.legend(
        handles=[Line2D([], [], color=COLORS["line"], linewidth=2, label="Close"),
                 Line2D([], [], color=COLORS["flat"], linestyle=(0, (4, 4)), label="First close")],
        loc="lower left", bbox_to_anchor=(0.16, 1.065), ncol=2,
        frameon=False, fontsize=9, labelcolor=COLORS["muted"], borderaxespad=0,
    )

    differences = np.diff(prices, prepend=prices[0])
    bar_colors = np.where(differences > 0, COLORS["up"],
                          np.where(differences < 0, COLORS["down"], COLORS["flat"]))
    volume_ax.bar(positions, volumes, width=0.65 if len(data) <= 20 else 0.85,
                  color=bar_colors, edgecolor="none", alpha=0.85, zorder=3)
    volume_ax.set_ylim(0, max(volumes.max() * 1.18, 1))
    volume_ax.yaxis.set_major_locator(MaxNLocator(nbins=3, min_n_ticks=2))
    volume_ax.yaxis.set_major_formatter(FuncFormatter(_compact_number))
    volume_ax.legend(
        handles=[Patch(facecolor=COLORS[key], label=label) for key, label in
                 (("up", "Up"), ("down", "Down"), ("flat", "Flat / first"))],
        loc="lower left", bbox_to_anchor=(0.16, 1.17), ncol=3,
        frameon=False, fontsize=8.5, labelcolor=COLORS["muted"],
        handlelength=0.9, borderaxespad=0,
    )
    # Equal spacing keeps overnight/weekend gaps from overwhelming intraday data.
    ticks = np.unique(np.linspace(0, len(data) - 1, min(len(data), 6), dtype=int))
    date_format = "%d %b" if daily else "%d %b\n%H:%M"
    if times.iloc[0].year != times.iloc[-1].year:
        date_format = "%d %b\n%Y" if daily else "%d %b %Y\n%H:%M"
    volume_ax.set_xticks(ticks, [times.iloc[index].strftime(date_format) for index in ticks])
    fig.text(0.06, 0.057, "Equally spaced observations · Non-trading gaps compressed",
             fontsize=9, color=COLORS["muted"])
    fig.text(0.94, 0.057, "Volume color: close vs. previous observation", ha="right",
             fontsize=9, color=COLORS["muted"])
    return fig


def visualize_stock(
    csv_path: str | Path = DEFAULT_CSV,
    show: bool = True,
    output_path: str | Path | None = None,
) -> Path:
    """Plot one stock CSV; save to outputs/charts unless a PNG path is provided."""
    csv_path = Path(csv_path)

    # Keep stock codes like 000001 as text so their leading zeros survive.
    data = pd.read_csv(csv_path, dtype={"symbol": str}, encoding="utf-8-sig")
    time_column = "date" if "date" in data.columns else "timestamp"
    is_a_share = "volume_lots" in data.columns
    volume_column = "volume_lots" if is_a_share else "volume"
    required = [time_column, "close", volume_column]
    if data.empty or not set(required).issubset(data.columns):
        raise ValueError(f"CSV must contain data and columns: {', '.join(required)}")
    if "symbol" in data.columns and data["symbol"].nunique() > 1:
        raise ValueError("Please use a CSV containing only one stock")

    # A-share times are local; the US example exports UTC timestamps.
    data[time_column] = pd.to_datetime(data[time_column], utc=not is_a_share)
    data["close"] = pd.to_numeric(data["close"])
    data[volume_column] = pd.to_numeric(data[volume_column])
    if data[required].isna().any().any():
        raise ValueError("Dates, closing prices and volumes must not be missing")
    if not np.isfinite(data[["close", volume_column]].to_numpy(dtype=float)).all():
        raise ValueError("Closing prices and volumes must be finite")
    if (data[volume_column] < 0).any():
        raise ValueError("Trading volumes must not be negative")
    data = data.sort_values(time_column, kind="stable")
    symbol = data["symbol"].iloc[0] if "symbol" in data.columns else csv_path.stem
    currency, volume_unit = ("CNY", "lots") if is_a_share else ("USD", "shares")

    if not show:
        plt.switch_backend("Agg")
    output_path = Path(output_path) if output_path is not None else CHARTS_DIR / f"{csv_path.stem}.png"
    if output_path.suffix.lower() != ".png":
        raise ValueError("Chart output path must end in .png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the theme local so importing this module doesn't restyle other plots.
    with plt.rc_context({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
        "font.size": 10,
        "savefig.facecolor": COLORS["background"],
    }):
        fig = _build_chart(data, time_column, volume_column, symbol, currency, volume_unit, is_a_share)
        try:
            fig.savefig(output_path, dpi=200)
            if show:
                plt.show()
        finally:
            plt.close(fig)
    print(f"Saved chart: {output_path.resolve()}")
    return output_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", type=Path, default=DEFAULT_CSV, help="Stock CSV path")
    parser.add_argument("--save-only", action="store_true", help="Save PNG without opening a window")
    parser.add_argument("--output", type=Path, help="PNG path; defaults to outputs/charts/<CSV stem>.png")
    args = parser.parse_args(argv)
    try:
        visualize_stock(args.csv, show=not args.save_only, output_path=args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Could not plot the CSV: {exc}\n")


if __name__ == "__main__":
    main()
