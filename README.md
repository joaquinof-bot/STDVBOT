# STDVBOT

A multi-timeframe **VWAP-swing / RSI / trendline killzone reversion** strategy
engine and backtester. This delivery is backtesting-only — there is no live
broker/exchange execution wired up.

> **Not financial advice.** This is a research/backtesting tool. Nothing here
> guarantees profitability; validate extensively before ever risking real
> capital, and only add live execution once you fully understand the risks.

## Strategy

Mean-reversion setup, evaluated bar-by-bar on a configurable "entry
timeframe" (default `5m`), requiring five things to line up at once:

1. **Killzone** — the bar falls inside a configured session window (UTC):
   Asian, London open, NY AM, NY PM / London close by default.
2. **Multi-timeframe RSI alignment** — RSI(14) is on the same side of
   neutral (50) on **every** timeframe in the stack (`1d, 4h, 1h, 30m, 15m,
   5m, 1m` by default). All-upside RSI + an overbought top-timeframe reading
   sets up a **short** reversion; all-downside + oversold sets up a **long**.
3. **VWAP swing** — price tagged the ±2σ session-VWAP band and the current
   bar has rolled back inside it (the actual "swing" reversion trigger).
4. **Trendline rejection** — a recent bar rejected an auto-fit trendline
   (least-squares line through the last two confirmed swing-pivot highs/lows)
   on one of the configured trendline timeframes (`1h` and the entry
   timeframe by default).
5. Stops are placed beyond the recent swing extreme plus an ATR buffer;
   targets are a configurable R-multiple of that risk.

See `stdvbot/strategy.py` for the exact combination logic and
`config/default.yaml` for every tunable parameter.

### No-lookahead by construction

- Every OHLCV bar is indexed by its **close time** (see `stdvbot/data.py`).
- A higher timeframe is aligned onto the entry timeframe with
  `merge_asof(direction="backward")`, so only bars that have *already
  closed* are ever visible at time `t`.
- Trendline pivots use a centered fractal window, so a pivot is only
  usable `window` bars after it occurs — see `rolling_trendlines` in
  `stdvbot/indicators/trendline.py`.

## Project layout

```
stdvbot/
  data.py                 CSV loading, ccxt fetch, timeframe resampling, MTF alignment
  config.py               StrategyConfig dataclass + YAML loader
  strategy.py             generate_signals(): the full indicator/signal pipeline
  backtest.py             run_backtest(): event-driven simulator + performance stats
  cli.py                  `python -m stdvbot.cli fetch|backtest`
  indicators/
    vwap.py                session-anchored VWAP + stdev bands
    rsi.py                 Wilder RSI
    atr.py                 Wilder ATR
    trendline.py           pivot detection + rolling trendline fit
    killzones.py           session killzone windows
config/default.yaml       default strategy configuration
tests/                     pytest suite (28 tests) covering every module
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Usage

### 1. Get historical data

Either supply your own CSV (`timestamp,open,high,low,close,volume`, at the
finest timeframe you want, `timestamp` as ISO8601 or epoch), or fetch public
OHLCV via `ccxt` (no API key needed — market data only):

```bash
python -m stdvbot.cli fetch \
  --symbol BTC/USDT --timeframe 1m --since 2024-01-01T00:00:00Z \
  --exchange binance --out data/btcusdt_1m.csv
```

### 2. Run a backtest

```bash
python -m stdvbot.cli backtest \
  --data data/btcusdt_1m.csv \
  --config config/default.yaml \
  --equity 10000 \
  --trades-out data/trades.csv
```

Prints trade count, win rate, average R-multiple, profit factor, max
drawdown, and total return; optionally dumps the full trade log to CSV.

### 3. Use it as a library

```python
from stdvbot.config import StrategyConfig
from stdvbot.data import load_ohlcv_csv
from stdvbot.strategy import generate_signals
from stdvbot.backtest import run_backtest

base_df = load_ohlcv_csv("data/btcusdt_1m.csv")
config = StrategyConfig.from_yaml("config/default.yaml")
signals = generate_signals(base_df, config)   # full indicator stack + signal/stop/target columns
result = run_backtest(signals, config)
print(result.summary())
```

## Tuning

Every threshold lives in `StrategyConfig` (`stdvbot/config.py`) /
`config/default.yaml`: which timeframes are required, RSI thresholds,
VWAP band width that defines a "swing," trendline pivot window and
tolerance, killzone windows, risk per trade, stop ATR multiple, and target
R-multiple. Copy `config/default.yaml`, edit, and pass `--config` to the CLI.

## What's not included (by design, per this delivery's scope)

- No live/paper order execution or broker integration.
- No walk-forward optimization or parameter search harness.
- No slippage/commission modeling beyond the flat `commission_pct` /
  `slippage_pct` knobs on `run_backtest`.

These are natural next steps once the strategy logic itself is validated.
