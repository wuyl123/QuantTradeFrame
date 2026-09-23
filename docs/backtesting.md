# Buy-and-hold accounting baseline

`quantlibrary.backtesting.buy_and_hold` is the first executable backtest. It
accepts the shared loader's `StockData` and simulates one fixed-size buy, then
holds the position. It establishes cash, fee, position, and valuation accounting
before general strategies are added.

## Run it

From the project root, with the virtual environment active:

```powershell
python -m quantlibrary.backtesting.buy_and_hold
python -m quantlibrary.backtesting.buy_and_hold data/raw/000001_5m_2026-08.csv --interval 5m --cash 100000 --shares 100 --commission-rate 0.001
python -m quantlibrary.backtesting.buy_and_hold --help
python -m unittest discover -s tests -v
```

The default input is the four-day sample. `--cash` defaults to 100,000 in the
stock currency, `--shares` to 100, and `--commission-rate` to 0.001 (0.1%).
`--fixed-fee` and `--slippage-bps` default to zero. The values are examples, not
market-specific costs. A slippage setting of 5 means 0.05% added to the buy price.

The loader's `--market`, `--interval`, `--adjustment`, and `--naive-timezone`
options are also available. They describe the input rather than altering it.

## Execution rules

1. Begin entirely in cash. Submit one market buy after the first bar completes.
   The requested whole-share quantity is fixed in advance.
2. Consider subsequent bars in order. A bar can fill only if its total volume
   is positive and its `trading_status`, if supplied, is 1. Suspended and
   zero-volume bars leave the order pending.
3. Fill the entire quantity at `open * (1 + slippage_bps / 10000)` and charge
   `notional * commission_rate + fixed_fee`. If cash cannot cover both, reject
   the whole order without charging fees. Rejected orders are not retried.
4. After each bar, value the position at its close. Pending orders expire at
   the end of the data. A one-bar input therefore has no fill.
5. Keep the ending position open. Final equity is cash plus shares times final
   close; no final sale or hypothetical exit fee is inserted.

Decisions and order size do not use later prices. The execution price uses the
next eligible open, not that bar's close. Eligibility uses completed-bar volume
and status as a bar-level execution assumption; it does not reconstruct what
liquidity was available at the opening instant.

## Cash and valuation

Cash and execution costs use decimal arithmetic, without currency-specific
minor-unit rounding. Output tables use normal numeric columns for pandas.

```text
notional       = shares bought * execution price
commission     = notional * commission rate + fixed fee
cash after buy = initial cash - notional - commission
position value = shares held * current close
equity         = cash + position value
net P&L        = equity - initial cash
return (%)     = (equity / initial cash - 1) * 100
drawdown (%)   = (running peak equity - equity) / running peak equity * 100
```

The running peak starts at initial cash, so initial trading costs and losses are
included in drawdown. Slippage is already included in execution price and is
reported separately for inspection; it is not deducted from cash twice.

The test fixture starts with 1,000 cash, buys 10 shares, charges a 1% commission,
and has these bars:

| Bar | Open | Close | Action | Cash | Shares | Equity |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 10 | 10 | Submit after close | 1,000.00 | 0 | 1,000.00 |
| 2 | 11 | 12 | Buy at open; fee 1.10 | 888.90 | 10 | 1,008.90 |
| 3 | 9 | 9 | Hold | 888.90 | 10 | 978.90 |

Final net P&L is -21.10, return is -2.11%, and maximum drawdown is
`30 / 1008.90 * 100`, approximately 2.974%. Tests assert the individual balances
and cash-plus-position reconciliation, as well as order timing and failure cases.

## Result files and timestamps

The default directory is `outputs/backtests/<CSV stem>_buy_hold/`:

- `orders.csv`: the submitted order, requested shares, final status, and reason.
- `fills.csv`: executed purchases with price, quantity, fees, and cash after the
  fill. It has headers even when there are no executions.
- `equity.csv`: per-bar cash, shares, closing price, position value, equity,
  cumulative fees, net P&L, return, and drawdown.
- `summary.json`: configuration, stock metadata, aggregate results, and explicit
  model assumptions. Unknown source/adjustment metadata remains `null`.

Re-running a destination replaces these four files. Set `--output-dir` to keep
multiple scenarios. `run_buy_and_hold()` itself has no file-writing side effects;
call `result.save(directory)` to export from Python.

Times remain the loader's original UTC **bar labels**. Columns such as
`submitted_phase`, `resolved_phase`, and `phase` distinguish open versus close
events. In particular, a daily label at market-local midnight is not claimed to
be a trade's wall-clock execution time. No exchange calendar or session hours
are fabricated. See [Normalized data](data_contract.md) for label semantics.

## Scope of the baseline

This is an accounting and execution-order reference, not a venue-specific broker
simulator. It does not model partial fills, volume participation limits, order
queues, market impact, lot-size rules, taxes, settlement, or price-limit rules.
Slippage is a configurable markup and is not clipped to a bar's high/low.
Prices retain the input's adjustment convention; dividends and corporate actions
are not separately credited. Results describe performance on that supplied price
series, rather than an independently calculated total-return series.

The baseline reports one open position, not a completed round trip. It therefore
does not manufacture a win rate, realized trade statistics, or annualized metrics
from these short examples. General entry/exit strategies and performance charts
remain separate next steps.
