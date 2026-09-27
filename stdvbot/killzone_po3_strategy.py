"""Killzone manipulation legs + PO3 entries (hybrid).

Setup detection is ``manipulation_leg`` (v1), unchanged: the Asia 20:00 / NY
09:30 killzone leg (3-5 candles, or a pivotal big candle), counter to the
daily bias, projected with the same inverse-Fib / STDV levels, regime-gated.

The entry is PO3's instead of v1's level touch. Read through the PDF: the
killzone leg is the *accumulation* leg, and price reaching its 2-2.5 STDV
zone is the *manipulation* completing. So instead of entering on the touch:

1. Wait for price to reach the killzone leg's ``zone_multiple`` level (2.0,
   the start of the PDF's 2-2.5 reversal zone; 4.5 on v1's trending-regime
   days, keeping v1's rule that trending days only take the A+ level).
2. Track the manipulation extreme from the killzone window's close.
3. Wait for a Market Structure Shift: a 5m close back through the last swing
   before that extreme (swings from the leg's start onward).
4. Enter exactly as ``po3_stdv`` does -- retrace into an FVG nested in the
   1-1.5 Silver Bullet Zone of the manipulation's last leg, stop beyond the
   extreme, target 2.5 (4 on a strong close).

Trade direction is unchanged from v1 (the killzone leg's direction), since the
manipulation runs against it and the MSS confirms the turn back.

``ASSUMED DEFAULT``s beyond v1's and PO3's own: the zone must be reached within
``touch_scan_bars`` of the killzone window closing (v1's touch window) and the
entry must follow within ``entry_window_bars``. A new manipulation extreme after
the MSS re-arms on a fresh MSS; if the move reaches its target without an entry,
that killzone setup is done.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .legs import (
    BIG_LEG_SIZE_MULTIPLE,
    DEFAULT_KILLZONES,
    detect_leg,
    inverse_fib_levels,
    is_pivotal_leg,
)
from .manipulation_leg_strategy import (
    A_PLUS_MULTIPLE,
    daily_bias_series,
    regime_series,
    resample_ohlc,
    typical_bar_range,
)
from .po3_strategy import PO3Entry, _confirm_pivots, _last_pivot_before
from .stdv import FiveMinuteView


def run(
    df: pd.DataFrame,
    killzones: dict = DEFAULT_KILLZONES,
    daily_bias_lookback: int = 20,
    regime_window: int = 20,
    regime_trending_threshold: float = 0.3,
    pivotal_leg_size_multiple: float = BIG_LEG_SIZE_MULTIPLE,
    pivotal_leg_reference_window: int = 1440,
    zone_multiple: float = 2.0,
    touch_scan_bars: int = 60,
    entry_window_bars: int = 240,
    pivot_left: int = 2,
    pivot_right: int = 2,
    entry_mode: str = "nested",
    target_multiple: float = 2.5,
    extend_to_terminus: bool = True,
    extension_stop_multiple: float = 2.0,
    max_hold_bars: int = 240,
    funnel: dict | None = None,
) -> tuple[pd.Series, list[dict]]:
    """Returns ``(position series on df's index, per-trade log)``. Pass a
    dict as ``funnel`` to get counts of how many setups survive each stage."""
    funnel = {} if funnel is None else funnel
    for stage in ("killzones_checked", "legs_passing_v1_filters", "zone_reached", "mss", "entered"):
        funnel.setdefault(stage, 0)
    ex = PO3Entry(df, entry_mode, target_multiple, extend_to_terminus, extension_stop_multiple, max_hold_bars)
    idx = df.index
    n = len(idx)
    if n == 0:
        return ex.result()
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()

    daily = resample_ohlc(df, "1D")
    bias_by_day = daily_bias_series(daily, lookback=daily_bias_lookback).to_dict()
    regime_by_day = regime_series(daily, window=regime_window, trending_threshold=regime_trending_threshold).to_dict()
    reference_range = typical_bar_range(df, window=pivotal_leg_reference_window).to_numpy()
    day_arr = idx.normalize()

    view = FiveMinuteView.build(df)
    idx5 = view.df5.index
    h5, l5, c5 = (view.df5[col].to_numpy() for col in ("high", "low", "close"))

    fire_events: dict[int, list[tuple]] = {}
    for day in pd.Index(day_arr.unique()):
        for name, kz in killzones.items():
            ws = pd.Timestamp.combine(day.date(), kz["start"])
            we = ws + pd.Timedelta(minutes=kz["leg_window_minutes"])
            pos = int(idx.searchsorted(we))
            if pos < n:
                fire_events.setdefault(pos, []).append((ws, we, name))

    pivots_hi: list[tuple[int, float]] = []
    pivots_lo: list[tuple[int, float]] = []
    watch = None

    for j in range(n):
        ex.manage(j)
        k = view.completes_at.get(j)
        if k is not None:
            _confirm_pivots(k, h5, l5, pivot_left, pivot_right, pivots_hi, pivots_lo)

        if watch is None and ex.idle and j in fire_events:
            funnel["killzones_checked"] += len(fire_events[j])
            watch = _arm_killzone(df, fire_events[j], j, day_arr, bias_by_day, regime_by_day, reference_range,
                                  pivotal_leg_size_multiple, zone_multiple, touch_scan_bars, entry_window_bars, idx5)
            funnel["legs_passing_v1_filters"] += watch is not None
        if watch is None:
            continue

        d = watch["dir"]
        if not watch["zone_reached"]:
            if (d == 1 and lows[j] <= watch["zone_level"]) or (d == -1 and highs[j] >= watch["zone_level"]):
                watch["zone_reached"] = True
                funnel["zone_reached"] += 1
            elif j > watch["zone_deadline"]:
                watch = None
                continue

        if k is not None and k >= watch["k_after"]:
            bar_extreme = l5[k] if d == 1 else h5[k]
            if watch["extreme"] is None or (bar_extreme < watch["extreme"] if d == 1 else bar_extreme > watch["extreme"]):
                watch["extreme"], watch["extreme_k"] = bar_extreme, k
            if watch["zone_reached"] and ex.idle and watch["extreme_k"] < k:
                swing = _last_pivot_before(pivots_hi if d == 1 else pivots_lo, watch["k_start"], watch["extreme_k"])
                if swing is not None and (c5[k] > swing if d == 1 else c5[k] < swing):
                    ex.arm(d, swing, watch["extreme"], watch["extreme_k"], watch["info"])
                    if not watch.get("mss_counted"):
                        funnel["mss"] += 1
                        watch["mss_counted"] = True
            ex.on_5m_bar(k, j, h5, l5)

        if j > watch["entry_deadline"] and ex.active is None:
            ex.setup = None
            watch = None
            continue
        outcome = ex.step_entry(j)
        if outcome == "entered":
            funnel["entered"] += 1
        if outcome in ("entered", "target_reached"):
            watch = None

    return ex.result()


def _arm_killzone(df, events, j, day_arr, bias_by_day, regime_by_day, reference_range, pivotal_multiple,
                  zone_multiple, touch_scan_bars, entry_window_bars, idx5):
    """v1's leg filters, unchanged; returns a watch for the manipulation phase."""
    day = day_arr[j]
    bias = bias_by_day.get(day)
    if bias is None or pd.isna(bias):
        return None
    regime = regime_by_day.get(day)
    ref = reference_range[j]
    for ws, we, name in events:
        leg = detect_leg(df, ws, we)
        if leg is None or not is_pivotal_leg(leg, None if np.isnan(ref) else float(ref), pivotal_multiple):
            continue
        if ("down" if leg.direction == "up" else "up") != bias:
            continue  # leg agrees with the daily bias -- not manipulation
        zone_m = zone_multiple if regime == "ranging" else A_PLUS_MULTIPLE
        return {
            "dir": 1 if leg.direction == "up" else -1,
            "zone_level": inverse_fib_levels(leg, (zone_m,))[zone_m],
            "zone_reached": False,
            "zone_deadline": j + touch_scan_bars,
            "entry_deadline": j + entry_window_bars,
            "k_start": int(idx5.searchsorted(ws)),
            "k_after": max(0, int(idx5.searchsorted(we, side="right")) - 1),  # 5m bar holding the window close
            "extreme": None,
            "extreme_k": None,
            "info": {"killzone": name, "day": day, "leg_direction": leg.direction, "leg_origin": leg.origin_price,
                     "leg_extreme": leg.extreme_price, "leg_candles": leg.num_candles, "zone_multiple": zone_m,
                     "regime": regime},
        }
    return None


def generate_signals(df: pd.DataFrame, **kwargs) -> pd.Series:
    return run(df, **kwargs)[0]
