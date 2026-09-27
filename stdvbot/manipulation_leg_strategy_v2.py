"""Manipulation-leg strategy, v2: adds a bias-undefined fallback.

This is a deliberate fork of :mod:`stdvbot.manipulation_leg_strategy`, not
an edit to it -- ``manipulation_leg`` (v1) stays exactly as it was, so
existing results/backtests against it are unaffected. Reuses every helper
from v1 unchanged (leg detection, regime, VWAP, confluence, exit
mechanics) and changes exactly one thing:

**v1 behavior**: if a killzone fires on a day with no defined daily bias,
the whole day is skipped. In practice this is exactly the first
``daily_bias_lookback`` days of *whatever dataset you hand it* --
verified against a real 3-month NQ pull: 20 of 80 days had an undefined
bias, and they were precisely day-index 0-19, nothing else (pure warmup,
not an ongoing "no leg found" case scattered through the data -- an
earlier draft of this docstring claimed otherwise before checking; that
was wrong). For a live/production run that's a one-time cost near
startup; for a short backtest window like a 3-month sample, it's a
quarter of the data. Either way, the off-trend filter can't be evaluated
without a bias to compare against, so v1 conservatively does nothing for
that stretch.

(v1 doesn't skip via an explicit "bias is None" check, incidentally --
``daily_bias_series`` stores undefined days as ``float('nan')`` in an
object-dtype Series, not Python ``None``, so ``bias is None`` never
actually fires; v1 ends up skipping anyway because a string compared
``!=`` to ``nan`` is always ``True``, falling through the off-trend
check. Same observable result, different code path -- caught while
building this fork, see below.)

**v2 behavior**: instead of skipping the day outright, a killzone leg is
still allowed through on a bias-undefined day -- but since the off-trend
filter can't be applied (there's nothing to check "counter-trend"
against), eligibility is restricted to the A+ level only
(``A_PLUS_MULTIPLE``), the same restriction v1 already applies on
confirmed-trending days. This is a design decision, not a data-fit: the
call is "we can't confirm this is off-trend, so only take it if it's
strong enough to act on close to standalone" -- substituting the missing
directional check with a higher size/confidence bar rather than either
extreme (skip entirely, or apply no substitute filter at all).

**Bug caught while building this fork**: the first implementation used
``bias is None`` to detect the undefined case, mirroring v1's check --
but since undefined bias is ``nan`` (a float), not ``None``, that check
never actually fired, and this fork would have silently behaved exactly
like v1 for 100% of the 20/80 undefined-bias days it exists to handle.
Fixed to ``pd.isna(bias)``, which catches both ``None`` and ``nan``.

Everything else -- leg validity/pivotal-size exception, regime gating on
defined-bias days, confluence, entry/stop/target/timeout mechanics -- is
unchanged from v1. See ``docs/manipulation_leg_strategy.md`` and v1's
module docstring for what's confirmed vs. assumed in the shared parts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import candles as c
from .legs import (
    BIG_LEG_SIZE_MULTIPLE,
    DEFAULT_KILLZONES,
    DEFAULT_LEVEL_MULTIPLES,
    detect_leg,
    inverse_fib_levels,
    is_pivotal_leg,
)
from .manipulation_leg_strategy import (
    A_PLUS_MULTIPLE,
    daily_bias_series,
    regime_series,
    resample_ohlc,
    session_vwap,
    typical_bar_range,
)


def generate_signals(
    df: pd.DataFrame,
    killzones: dict = DEFAULT_KILLZONES,
    level_multiples=DEFAULT_LEVEL_MULTIPLES,
    daily_bias_lookback: int = 20,
    regime_window: int = 20,
    regime_trending_threshold: float = 0.3,
    touch_scan_bars: int = 60,
    max_hold_bars: int = 120,
    pivotal_leg_size_multiple: float = BIG_LEG_SIZE_MULTIPLE,
    pivotal_leg_reference_window: int = 1440,
) -> pd.Series:
    """Same as :func:`stdvbot.manipulation_leg_strategy.generate_signals`,
    except a killzone leg on a day with no defined daily bias is allowed
    through (A+ level only) instead of being skipped outright -- see the
    module docstring for why. All parameters match v1 exactly.
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
    reference_range = typical_bar_range(df, window=pivotal_leg_reference_window).to_numpy()
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

    fire_events: dict[int, list[tuple]] = {}
    for day in pd.Index(idx.normalize().unique()):
        for kz in killzones.values():
            window_start = pd.Timestamp.combine(day.date(), kz["start"])
            window_end = window_start + pd.Timedelta(minutes=kz["leg_window_minutes"])
            pos = idx.searchsorted(window_end)
            if pos < n:
                fire_events.setdefault(pos, []).append((window_start, window_end))

    position = np.zeros(n, dtype=float)
    pending = None
    active = None

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

                leg = detect_leg(df, window_start, window_end)
                ref = reference_range[j]
                if leg is None or not is_pivotal_leg(
                    leg, None if np.isnan(ref) else float(ref), pivotal_leg_size_multiple
                ):
                    continue

                bias_undefined = pd.isna(bias)
                if not bias_undefined:
                    leg_implied_bias = "down" if leg.direction == "up" else "up"
                    if leg_implied_bias != bias:
                        continue  # leg agrees with bias -- not manipulation

                trade_direction = 1 if leg.direction == "up" else -1
                levels = inverse_fib_levels(leg, level_multiples)
                if bias_undefined:
                    # Can't confirm off-trend without a bias to check against --
                    # substitute a higher bar (A+ only) instead of no filter at all.
                    eligible = sorted((m, px) for m, px in levels.items() if m >= A_PLUS_MULTIPLE)
                else:
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
                break

    return pd.Series(position, index=idx, name="position")
