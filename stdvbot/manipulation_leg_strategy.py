"""Manipulation-leg trading strategy: signal generation wired end-to-end.

Turns the primitives in ``stdvbot/legs.py`` and ``stdvbot/poi.py`` into a
real ``generate_signals(df) -> pd.Series`` pipeline compatible with
:func:`stdvbot.backtest.run_backtest`, so it can run against 1-minute
OHLCV data (real or synthetic) exactly like the candlestick strategies in
``stdvbot/strategies.py``. Read ``docs/manipulation_leg_strategy.md``
first -- several pieces here are ``ASSUMED DEFAULT``, not fully confirmed
rules.

**Correction made while wiring this up, read before trusting a trade
direction:** the spec doc's §3 said entries go "opposite the manipulation
leg's own push." Re-checking that against the actual worked example
verbatim -- "manipulates higher... mark a lower fib... once it strikes
2.5 you enter a long" (an *up* leg leading to a *long* entry) -- shows the
entry direction is the SAME as the leg's own direction, not opposite. The
"opposite" language describes the intermediate retrace move that carries
price down to the fib zone, not the trade actually taken. This module
implements ``trade_direction = leg.direction``, confirmed straight from
the worked example, not the spec doc's (incorrect) paraphrase of it. The
spec doc needs a matching correction -- flagging loudly since getting
this backwards means systematically wrong-way trades.

The higher-timeframe bias is used only as an *off-trend filter* (a leg
only counts as manipulation if it runs counter to the prevailing daily
bias) -- it does not itself set the trade direction; the leg does.

Simplifications made to ship a working v1 (documented, not hidden):
  - Confluence in the 2.0-4.5 zone is currently just "a candlestick
    reversal pattern matching trade direction fires on the touching bar."
    The full spec also lists VWAP/round-number/POI proximity -- not wired
    in yet (TODO).
  - Target is session VWAP; if price has already passed VWAP by entry,
    falls back to a 2R target rather than "nearest opposing POI" (TODO,
    needs POI-selection logic).
  - Regime (ranging vs. trending) is read from Kaufman's Efficiency Ratio
    on daily closes -- an ASSUMED DEFAULT proxy, the spec doc leaves the
    exact formula open.
  - Only one position at a time; a new killzone signal is ignored while
    already in a trade or already watching a pending setup.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import candles as c
from .legs import (
    DEFAULT_KILLZONES,
    DEFAULT_LEVEL_MULTIPLES,
    detect_leg,
    inverse_fib_levels,
)

#: A touch at/above this multiple needs no confluence confirmation (the
#: spec's "A+ / zone of no return"); anything shallower needs a
#: confirming candlestick pattern in the trade's direction.
A_PLUS_MULTIPLE = 4.5


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample a 1-minute (or finer) OHLCV DataFrame to a coarser
    timeframe (e.g. ``"1D"``, ``"4h"``)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna(subset=["open"])


def efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    """Kaufman's Efficiency Ratio: ``|net change| / sum(|bar changes|)``
    over a rolling window. Near 1 = trending, near 0 = choppy/ranging.
    ASSUMED DEFAULT regime proxy -- the spec doc leaves the exact
    regime-classification formula open.
    """
    net_change = (close - close.shift(window)).abs()
    path_length = close.diff().abs().rolling(window).sum()
    return (net_change / path_length.replace(0.0, np.nan)).fillna(0.0)


def daily_bias_series(daily_df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """For each day, the higher-timeframe bias — the direction OPPOSITE
    the most recent valid daily leg found in the trailing ``lookback``
    days (a daily "fast pump" tops out; the bias is toward its
    retracement — see spec §1). Uses only the ``lookback`` days *before*
    each day (excluding the day itself) to avoid look-ahead. Values are
    ``"up"``/``"down"``/``None`` (window too short).

    Note: this deliberately does NOT gate on :attr:`Leg.is_valid` — that
    3-5 candle rule was confirmed specifically for 1-minute killzone legs
    (the "fast pump" would need to peak within the first 3-5 *days* of a
    ``lookback``-day window otherwise, which is far too strict and would
    leave bias undefined almost everywhere — caught by testing this
    against synthetic data). Any leg found over the window is used.
    """
    bias = pd.Series(index=daily_df.index, dtype=object)
    for i in range(len(daily_df)):
        if i < lookback:
            continue
        window = daily_df.iloc[i - lookback : i]
        leg = detect_leg(window, window.index[0], window.index[-1] + pd.Timedelta(days=1))
        if leg is not None:
            bias.iloc[i] = "down" if leg.direction == "up" else "up"
    return bias


def regime_series(
    daily_df: pd.DataFrame, window: int = 20, trending_threshold: float = 0.3
) -> pd.Series:
    """``"ranging"`` or ``"trending"`` per day, from the trailing
    efficiency ratio (shifted by one day to avoid look-ahead). ASSUMED
    DEFAULT threshold -- see spec doc.
    """
    er = efficiency_ratio(daily_df["close"], window).shift(1)
    return er.apply(lambda v: "trending" if v >= trending_threshold else "ranging")


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Session (calendar-day) VWAP, resetting each day. Falls back to the
    close price where volume is unavailable/zero.
    """
    if "volume" not in df.columns or df["volume"].sum() == 0:
        return df["close"]
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df.index.normalize()
    pv = (typical * df["volume"]).groupby(day).cumsum()
    v = df["volume"].groupby(day).cumsum().replace(0.0, np.nan)
    return (pv / v).fillna(df["close"])


def generate_signals(
    df: pd.DataFrame,
    killzones: dict = DEFAULT_KILLZONES,
    level_multiples=DEFAULT_LEVEL_MULTIPLES,
    daily_bias_lookback: int = 20,
    regime_window: int = 20,
    regime_trending_threshold: float = 0.3,
    touch_scan_bars: int = 60,
    max_hold_bars: int = 120,
) -> pd.Series:
    """Generate a target position series (-1/0/1) for the manipulation-leg
    strategy on 1-minute (or finer) OHLCV data ``df``, compatible with
    :func:`stdvbot.backtest.run_backtest`.

    Pipeline, per calendar day: read the daily bias and regime (from data
    strictly before that day); at each killzone's leg-detection window
    close, detect a leg; keep it only if it's valid and counter to the
    daily bias (the "off-trend"/manipulation filter); project its
    inverse-Fibonacci levels; watch subsequent bars (up to
    ``touch_scan_bars``) for a level touch, gated by regime (trending
    days only allow the deepest/``A_PLUS_MULTIPLE`` level) and confluence
    (shallower touches need a same-direction candlestick pattern on the
    touching bar); on entry, hold until stop, target, or
    ``max_hold_bars`` elapses.

    Requires intraday data with real killzone-aligned timestamps (see
    :func:`stdvbot.data.generate_synthetic_intraday_ohlcv` for a synthetic
    stand-in, or your own 1-minute historical data) -- this will not
    produce meaningful signals on daily bars.
    """
    idx = df.index
    n = len(idx)
    if n == 0:
        return pd.Series(dtype=float, name="position")

    daily = resample_ohlc(df, "1D")
    bias_by_day = daily_bias_series(daily, lookback=daily_bias_lookback).to_dict()
    regime_by_day = regime_series(
        daily, window=regime_window, trending_threshold=regime_trending_threshold
    ).to_dict()
    patterns = c.detect_patterns(df)
    vwap = session_vwap(df)

    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    pattern_score = (
        patterns["pattern_score"].to_numpy() if "pattern_score" in patterns else np.zeros(n)
    )
    vwap_arr = vwap.to_numpy()
    day_arr = idx.normalize()
    sorted_multiples = sorted(level_multiples)

    # Precompute which bar each killzone's leg-detection window closes at.
    fire_events: dict[int, list[tuple]] = {}
    for day in pd.Index(idx.normalize().unique()):
        for kz in killzones.values():
            window_start = pd.Timestamp.combine(day.date(), kz["start"])
            window_end = window_start + pd.Timedelta(minutes=kz["leg_window_minutes"])
            pos = idx.searchsorted(window_end)
            if pos < n:
                fire_events.setdefault(pos, []).append((window_start, window_end))

    position = np.zeros(n, dtype=float)
    pending = None  # dict: eligible [(multiple, price)], trade_direction, deadline, stop_by_level
    active = None  # dict: direction, stop, target, bars_held

    for j in range(n):
        if active is not None:
            direction = active["direction"]
            exit_now = False
            if direction == 1:
                if lows[j] <= active["stop"]:
                    exit_now = True
                elif highs[j] >= active["target"]:
                    exit_now = True
            else:
                if highs[j] >= active["stop"]:
                    exit_now = True
                elif lows[j] <= active["target"]:
                    exit_now = True

            position[j] = direction
            active["bars_held"] += 1
            if exit_now or active["bars_held"] >= max_hold_bars:
                active = None
            continue

        if pending is not None:
            if j > pending["deadline"]:
                pending = None
            else:
                td = pending["trade_direction"]
                touched = None
                for m, px in pending["eligible"]:
                    if (td == 1 and lows[j] <= px) or (td == -1 and highs[j] >= px):
                        touched = (m, px)
                        break
                if touched is not None:
                    m, px = touched
                    ok = m >= A_PLUS_MULTIPLE or (
                        (td == 1 and pattern_score[j] > 0) or (td == -1 and pattern_score[j] < 0)
                    )
                    if ok:
                        stop = pending["stop_by_level"][m]
                        entry_vwap = vwap_arr[j]
                        if (td == 1 and entry_vwap > px) or (td == -1 and entry_vwap < px):
                            target = entry_vwap
                        else:
                            risk = abs(px - stop)
                            target = px + td * 2.0 * risk
                        active = {"direction": td, "stop": stop, "target": target, "bars_held": 0}
                        position[j] = td
                        pending = None
                        continue
                    pending["eligible"] = [t for t in pending["eligible"] if t[0] != m]
                    if not pending["eligible"]:
                        pending = None

        if pending is None and active is None and j in fire_events:
            for window_start, window_end in fire_events[j]:
                day = day_arr[j]
                bias = bias_by_day.get(day)
                regime = regime_by_day.get(day)
                if bias is None:
                    continue
                leg = detect_leg(df, window_start, window_end)
                if leg is None or not leg.is_valid:
                    continue
                leg_implied_bias = "down" if leg.direction == "up" else "up"
                if leg_implied_bias != bias:
                    continue  # leg agrees with bias -- not manipulation

                trade_direction = 1 if leg.direction == "up" else -1
                levels = inverse_fib_levels(leg, level_multiples)
                eligible = sorted(
                    (m, px)
                    for m, px in levels.items()
                    if m >= A_PLUS_MULTIPLE or regime == "ranging"
                )
                if not eligible:
                    continue

                stop_by_level = {}
                for m, _ in eligible:
                    later = [mm for mm in sorted_multiples if mm > m]
                    next_tier = later[0] if later else m + 0.5
                    stop_by_level[m] = inverse_fib_levels(leg, (next_tier,))[next_tier]

                pending = {
                    "eligible": eligible,
                    "trade_direction": trade_direction,
                    "deadline": min(j + touch_scan_bars, n - 1),
                    "stop_by_level": stop_by_level,
                }
                break  # at most one pending setup even if both killzones fire the same bar

    return pd.Series(position, index=idx, name="position")
