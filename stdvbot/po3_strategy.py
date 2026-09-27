"""Power of Three (PO3) + Standard Deviation strategy (4H PO3, 5m structure).

Translated from "Standard Deviation + Power of Three" (po3trader, crediting
ICT / TraderDext3r). The author's stated entry model is "4H PO3 + STDv",
identified on the 5-minute chart. See ``docs/stdv_po3_ipda.md`` for what's
taken straight from the PDF vs. ``ASSUMED DEFAULT``.

Per 4H candle (opens at 02/06/10/14/18/22 local for index futures):

1. **Manipulation** -- price trades against the candle open first: below it
   for a bullish PO3 (Open-Low-High-Close), above it for a bearish one.
2. **Market Structure Shift (MSS)** -- a 5m close back through the last
   swing before the manipulation extreme (bullish: close above the last
   swing high before the low). This confirms manipulation is done.
3. **STDV projection off the manipulation's last leg** -- from that swing
   ("0") to the manipulation extreme ("1"), projected past the swing:
   1-1.5 = Silver Bullet Zone, 2-2.5 = target / reversal zone, 4 = terminus.
4. **Entry** -- a retrace into a same-direction fair value gap (internal
   range liquidity) nested inside the 1-1.5 Silver Bullet Zone (the PDF's
   "higher probability" scenario). ``entry_mode="any_irl"`` implements its
   first scenario instead: any same-direction FVG from the expansion, once
   price has reached the SBZ.
5. **Exit** -- target 2.5 STDV. If the bar that reaches 2.5 closes beyond it
   ("closes strong above 2.5"), extend the target to 4 and move the stop to
   2.0. Stop beyond the manipulation extreme.

**Direction relative to our v1/v2 engine:** the projection math is identical
(see :mod:`stdvbot.stdv`), but PO3 trades *toward* the 2-2.5 zone (with the
distribution, away from the manipulation) where v1/v2 *fade* it.

**Not implemented** (no data or no codeable definition in the PDF): the
HTF POI nested in 2-2.5 and SMT divergence vs. the Dow (needs a second
instrument) confirmations; the accumulation leg's own projection of where
manipulation should end.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .legs import MNQ_TICK_SIZE
from .stdv import (
    INDEX_FUTURES_4H_OPENS,
    SBZ,
    TERMINUS,
    FiveMinuteView,
    four_hour_boundaries,
    fvg_at,
    pivot_confirmed_at,
    stdv_projection,
)

LEVELS = (1.0, 1.5, 2.0, 2.5, 4.0)


def run(
    df: pd.DataFrame,
    candle_hours=INDEX_FUTURES_4H_OPENS,
    pivot_left: int = 2,
    pivot_right: int = 2,
    swing_lookback_5m: int = 12,
    entry_mode: str = "nested",
    target_multiple: float = 2.5,
    extend_to_terminus: bool = True,
    extension_stop_multiple: float = 2.0,
    max_hold_bars: int = 240,
) -> tuple[pd.Series, list[dict]]:
    """Returns ``(position series on df's index, per-trade log)``."""
    if entry_mode not in ("nested", "any_irl"):
        raise ValueError(f"entry_mode must be 'nested' or 'any_irl', got {entry_mode!r}")
    idx = df.index
    n = len(idx)
    position = np.zeros(n, dtype=float)
    log: list[dict] = []
    if n == 0:
        return pd.Series(position, index=idx, name="position"), log

    view = FiveMinuteView.build(df)
    df5 = view.df5
    idx5 = df5.index
    o5, h5, l5, c5 = (df5[col].to_numpy() for col in ("open", "high", "low", "close"))
    highs, lows, closes = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()

    starts = four_hour_boundaries(idx, candle_hours)
    starts_arr = pd.DatetimeIndex(starts)
    four_h = pd.Timedelta(hours=4)

    def candle_of(t):
        pos = starts_arr.searchsorted(t, side="right") - 1
        if pos < 0 or t >= starts_arr[pos] + four_h:
            return None
        return starts_arr[pos]

    pivots_hi: list[tuple[int, float]] = []
    pivots_lo: list[tuple[int, float]] = []
    candle = None
    setup = None
    active = None
    last_exit = -2  # v1 convention: always >=1 flat bar between trades
    traded = set()

    for j in range(n):
        held_at_start = active is not None
        if active is not None:
            d = active["dir"]
            position[j] = d
            active["bars"] += 1
            reason = None
            hit_stop = lows[j] <= active["stop"] if d == 1 else highs[j] >= active["stop"]
            hit_target = highs[j] >= active["target"] if d == 1 else lows[j] <= active["target"]
            if hit_stop:
                reason = "stop"
            elif hit_target:
                closes_through = closes[j] >= active["target"] if d == 1 else closes[j] <= active["target"]
                if extend_to_terminus and not active["extended"] and closes_through:
                    active["extended"] = True
                    active["stop"] = active["levels"][extension_stop_multiple]
                    active["target"] = active["levels"][TERMINUS]
                else:
                    reason = "target_4" if active["extended"] else "target"
            if reason is None and active["bars"] >= max_hold_bars:
                reason = "timeout"
            if reason is not None:
                active["log"].update(exit_time=idx[j], exit_reason=reason)
                active = None
                last_exit = j

        k = view.completes_at.get(j)
        if k is not None:
            if k - pivot_right >= 0:
                p = k - pivot_right
                if pivot_confirmed_at(h5, p, pivot_left, pivot_right, "high"):
                    pivots_hi.append((p, h5[p]))
                if pivot_confirmed_at(l5, p, pivot_left, pivot_right, "low"):
                    pivots_lo.append((p, l5[p]))

            c_start = candle_of(idx5[k])
            if c_start is not None and (candle is None or candle["start"] != c_start):
                candle = {"start": c_start, "end": c_start + four_h, "k0": k, "open": o5[k],
                          "low": l5[k], "low_k": k, "high": h5[k], "high_k": k}
                setup = None
            elif c_start is not None:
                if l5[k] < candle["low"]:
                    candle["low"], candle["low_k"] = l5[k], k
                if h5[k] > candle["high"]:
                    candle["high"], candle["high_k"] = h5[k], k

            if candle is not None and c_start == candle["start"]:
                if setup is None and active is None and candle["start"] not in traded:
                    setup = _check_mss(candle, k, c5, pivots_hi, pivots_lo, swing_lookback_5m)

                if setup is not None:
                    d = setup["dir"]
                    lv = setup["levels"]
                    if (d == 1 and h5[k] >= lv[SBZ[0]]) or (d == -1 and l5[k] <= lv[SBZ[0]]):
                        setup["reached_sbz"] = True
                    f = fvg_at(h5, l5, k)
                    if f is not None and f[0] == d and k - 2 >= setup["extreme_k"]:
                        _, bottom, top = f
                        if entry_mode == "any_irl" or _overlaps_sbz(bottom, top, lv):
                            setup["fvgs"].append({"bottom": bottom, "top": top, "known_at": j})

        if setup is not None and active is None and j > last_exit + 1:
            d = setup["dir"]
            lv = setup["levels"]
            if idx[j] >= candle["end"] or setup["candle"] != candle["start"]:
                setup = None
            else:
                eligible = entry_mode == "nested" or setup["reached_sbz"]
                touched = None
                if eligible:
                    for f in setup["fvgs"]:
                        if f["known_at"] >= j:
                            continue
                        if (d == 1 and lows[j] <= f["top"]) or (d == -1 and highs[j] >= f["bottom"]):
                            touched = f
                            break
                if touched is not None:
                    stop = setup["anchor1"] - d * MNQ_TICK_SIZE
                    entry = {
                        "candle": setup["candle"], "direction": "long" if d == 1 else "short",
                        "anchor0": setup["anchor0"], "anchor1": setup["anchor1"],
                        "range": abs(setup["anchor0"] - setup["anchor1"]),
                        "fvg_bottom": touched["bottom"], "fvg_top": touched["top"],
                        "entry_time": idx[j], "stop": stop, "target": lv[target_multiple],
                    }
                    log.append(entry)
                    active = {"dir": d, "stop": stop, "target": lv[target_multiple], "levels": lv,
                              "extended": False, "bars": 0, "log": entry}
                    position[j] = d
                    traded.add(setup["candle"])
                    setup = None
                elif (d == 1 and (lows[j] < setup["anchor1"] or highs[j] >= lv[target_multiple])) or (
                    d == -1 and (highs[j] > setup["anchor1"] or lows[j] <= lv[target_multiple])
                ):
                    setup = None  # manipulation extreme broken, or the move ran without us

    return pd.Series(position, index=idx, name="position"), log


def _check_mss(candle, k, c5, pivots_hi, pivots_lo, swing_lookback_5m):
    lo_bound = candle["k0"] - swing_lookback_5m
    if candle["low"] < candle["open"] and candle["low_k"] < k:
        swing = _last_pivot_before(pivots_hi, lo_bound, candle["low_k"])
        if swing is not None and c5[k] > swing:
            return _make_setup(1, swing, candle["low"], candle["low_k"], candle["start"])
    if candle["high"] > candle["open"] and candle["high_k"] < k:
        swing = _last_pivot_before(pivots_lo, lo_bound, candle["high_k"])
        if swing is not None and c5[k] < swing:
            return _make_setup(-1, swing, candle["high"], candle["high_k"], candle["start"])
    return None


def _last_pivot_before(pivots, lo_bound, before_k):
    for p, price in reversed(pivots):
        if p < before_k:
            return price if p >= lo_bound else None
    return None


def _make_setup(direction, anchor0, anchor1, extreme_k, candle_start):
    return {
        "dir": direction, "anchor0": anchor0, "anchor1": anchor1, "extreme_k": extreme_k,
        "candle": candle_start, "levels": stdv_projection(anchor0, anchor1, LEVELS),
        "fvgs": [], "reached_sbz": False,
    }


def _overlaps_sbz(bottom, top, levels):
    band_lo, band_hi = sorted((levels[SBZ[0]], levels[SBZ[1]]))
    return top >= band_lo and bottom <= band_hi


def generate_signals(df: pd.DataFrame, **kwargs) -> pd.Series:
    return run(df, **kwargs)[0]
