# STDVBOT

A small, dependency-light toolkit for building and backtesting trading
strategies derived from **candlestick patterns** — the shape of
individual and small groups of OHLC bars (dojis, hammers, engulfing
patterns, stars, etc.) rather than indicators like moving averages or
RSI on their own.

> ⚠️ **Educational / research code.** Nothing here is investment
> advice, and none of the bundled strategies is validated as
> profitable on any real market. Backtests are not a promise of live
> results — see [Caveats](#caveats) below.

## What's in here

```
stdvbot/
  candles.py     candle geometry features + 14 pattern detectors
  strategies.py  turns patterns into a target position (-1/0/1) per bar
  backtest.py    leak-free vectorized backtester (signal@close -> fill@next open)
  metrics.py     Sharpe, Sortino, max drawdown, Calmar, win rate, profit factor
  data.py        CSV loader + offline synthetic OHLCV generator
  cli.py         `python -m stdvbot.cli ...`
examples/
  run_backtest.py   compares all bundled strategies side by side
tests/                  pytest suite (pattern shapes, backtest math, strategies)
```

## Install

```bash
python3 -m pip install -r requirements.txt
# or, as an editable package (adds the `stdvbot` CLI script):
python3 -m pip install -e .
```

## Quickstart

```bash
# Synthetic data (no network / no API keys needed), composite strategy
python -m stdvbot.cli --strategy composite --synthetic --bars 750

# Your own OHLCV CSV: columns date,open,high,low,close[,volume]
python -m stdvbot.cli --strategy reversal --data prices.csv --plot equity.png

# Compare every bundled strategy on the same synthetic series
python examples/run_backtest.py
```

Or from Python:

```python
from stdvbot.data import generate_synthetic_ohlcv
from stdvbot.strategies import get_strategy
from stdvbot.backtest import run_backtest

df = generate_synthetic_ohlcv(n=1000, seed=7)
strategy = get_strategy("composite")          # or "reversal" / "continuation"
signals = strategy.generate_signals(df)
result = run_backtest(df, signals, fee_bps=5, slippage_bps=2)

print(result.summary())
print(result.trades.tail())
```

## Candlestick patterns implemented

Single-candle: `doji`, `hammer`, `hanging_man`, `inverted_hammer`, `shooting_star`
Two-candle: `bullish_engulfing`, `bearish_engulfing`, `bullish_harami`, `bearish_harami`, `piercing_line`, `dark_cloud_cover`
Three-candle: `morning_star`, `evening_star`, `three_white_soldiers`, `three_black_crows`

Each is a pure, vectorized function in `stdvbot/candles.py` operating on
an `open/high/low/close` DataFrame and returning a boolean `pd.Series`
("did this pattern complete as of this bar's close"). `detect_patterns()`
runs the whole set at once and adds a signed `pattern_score` column
(+1 per bullish pattern firing, -1 per bearish).

## Strategies

| name           | idea                                                                                   |
|----------------|-----------------------------------------------------------------------------------------|
| `reversal`     | Buy bullish reversal patterns *in a downtrend*, short bearish reversal patterns *in an uptrend*, optionally confirmed by RSI oversold/overbought. |
| `continuation` | Trade three white soldiers / three black crows *with* the prevailing trend.             |
| `composite`    | Rolling sum of every pattern's signed score; enters when the sum crosses a threshold.   |

All three share the same exit logic: hold until an opposite signal
fires or `max_hold` bars elapse.

## Backtester design (read this before trusting a number)

- **No look-ahead:** a strategy's signal for bar *i* is decided from
  information available at bar *i*'s close, but is only realized
  starting bar *i+1*'s return (i.e. execution happens at the next
  bar's open, modeled by shifting the position series one bar before
  applying it to close-to-close returns).
- **Transaction costs** (fees + slippage, in bps of notional) are
  charged only when the effective position changes, on the notional
  turned over.
- **Equity compounds** bar over bar: `equity_t = equity_{t-1} * (1 + net_return_t)`.

## Testing

```bash
python3 -m pytest -q
```

The test suite hand-builds small OHLC DataFrames for every pattern
(known engulfing/hammer/star/etc. shapes) and asserts detection,
verifies the backtester's shift/cost/compounding math against
hand-computed numbers, and smoke-tests every strategy end-to-end on
synthetic data.

## Caveats

- The synthetic data generator (`stdvbot.data.generate_synthetic_ohlcv`)
  is a simple geometric random walk with noise added for wick shapes —
  it exists so examples/tests run offline, not as a realistic market
  simulator. Good backtest numbers on it mean nothing about live
  performance.
- Default strategy parameters were chosen for coverage/readability,
  not tuned/optimized on real data — treat them as a starting point.
- No position sizing beyond a fixed +-1 unit, no multi-asset support,
  no slippage model beyond a flat bps charge, no borrow costs for
  shorts. Extend `backtest.py` before using this near real money.
