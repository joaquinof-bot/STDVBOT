"""IPDA data ranges + Standard Deviation strategy (intraday 12-hour lookback).

Translated from "Liquidity Profiles + Standard Deviation Theory"
(po3trader, crediting ICT / TraderDext3r). The PDF describes the same two
profiles at every scale (3 month / 3 week / 3 day / 12 hour); this
implements the intraday 12-hour one (3 x 4H candles, 5m structure) since
that's the scale an intraday MNQ strategy operates at. See
``docs/stdv_po3_ipda.md`` for what's from the PDF vs. ``ASSUMED DEFAULT``.

At each 4H boundary (02/06/10/14/18/22 local), look back 12 hours:

- **Dealing range** = the lookback's high/low; equilibrium (EQ) = midpoint;
  above EQ = premium, below = discount.
- **Institutional order flow (IOF)** -- ``ASSUMED DEFAULT``: bullish if the
  range low came before the range high (price was delivered upward),
  bearish otherwise. The PDF reads IOF by eye from higher timeframes.
- **STDV projection** from the range's "most discernible" leg -- bullish
  IOF: the leg down into the range low (from the last swing high before
  it), projected up; bearish mirrors.

Then over the next 4 hours (the cast-forward window), whichever triggers
first:

1. **Retracement / reversal profile** -- price reaches the 2-2.5 zone and
   *fails to close strongly above 2.5*: a 5m close back inside (below 2.0
   for bullish IOF) enters a fade toward EQ of the dealing range (low to
   the new extreme). A 5m close beyond 2.5 invalidates the 2-2.5 fade and
   arms the terminus instead: touch 4, then a close back inside 4 enters.
   Stop just beyond the extreme reached.
2. **Continuation profile** -- price is on the discount side (bullish IOF)
   and retraces into an unfilled same-direction fair value gap (internal
   range liquidity) within the discount half: enter with the order flow,
   target external range liquidity (the range high), stop beyond the range
   low.

**Not implemented**: HTF PD arrays as a precondition for the reversal
profile (the PDF's "arrived at a HTF PDA"), and the 20/40/60-day and
3-week/3-day ranges (daily-scale; could be layered on as a bias filter).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .legs import MNQ_TICK_SIZE
from .stdv import (
    INDEX_FUTURES_4H_OPENS,
    REVERSAL_ZONE,
    TERMINUS,
    FiveMinuteView,
    four_hour_boundaries,
    fvg_at,
    pivot_confirmed_at,
    stdv_projection,
)

LEVELS = (1.0, 1.5, 2.0, 2.5, 4.0)
BARS_5M_PER_12H = 144


def dealing_range(h5, l5, c5, k_lo, k_hi, pivot_left=2, pivot_right=2):
    """Dealing range, IOF, and STDV projection for 5m bars ``[k_lo, k_hi)``.
    Returns ``None`` if the range is degenerate."""
    if k_hi - k_lo < 3:
        return None
    hs, ls = h5[k_lo:k_hi], l5[k_lo:k_hi]
    k_h = k_lo + int(np.argmax(hs))
    k_l = k_lo + int(np.argmin(ls))
    H, L = float(hs.max()), float(ls.min())
    if k_h == k_l or H <= L:
        return None
    iof = 1 if k_l < k_h else -1

    last_confirmable = k_hi - 1 - pivot_right
    if iof == 1:
        extreme, extreme_k, kind, arr = L, k_l, "high", h5
    else:
        extreme, extreme_k, kind, arr = H, k_h, "low", l5
    anchor0 = None
    for p in range(min(extreme_k - 1, last_confirmable), k_lo - 1, -1):
        if pivot_confirmed_at(arr, p, pivot_left, pivot_right, kind):
            anchor0 = float(arr[p])
            break
    if anchor0 is None:
        if extreme_k <= k_lo:
            return None
        seg = arr[k_lo:extreme_k]
        anchor0 = float(seg.max() if iof == 1 else seg.min())
    if (iof == 1 and anchor0 <= L) or (iof == -1 and anchor0 >= H):
        return None

    return {
        "H": H, "L": L, "EQ": (H + L) / 2.0, "iof": iof, "anchor0": anchor0, "anchor1": extreme,
        "levels": stdv_projection(anchor0, extreme, LEVELS), "last_close": float(c5[k_hi - 1]),
        "k_lo": k_lo, "k_hi": k_hi,
    }


def _initial_reversal_state(dr):
    """Where price sits relative to the 2-2.5 / 4 zones at the boundary."""
    s = dr["iof"]
    lv = dr["levels"]
    x = dr["last_close"]

    def beyond(level):
        return x > level if s == 1 else x < level

    def at_or_beyond(level):
        return x >= level if s == 1 else x <= level

    if not at_or_beyond(lv[REVERSAL_ZONE[0]]):
        state = "A"
    elif not beyond(lv[REVERSAL_ZONE[1]]):
        state = "B"
    elif not at_or_beyond(lv[TERMINUS]):
        state = "C"
    else:
        state = "D"
    extreme = dr["H"] if s == 1 else dr["L"]
    return {"state": state, "extreme": extreme}


def _continuation_fvgs(dr, h5, l5):
    """Unfilled same-direction FVGs on the order-flow side of EQ."""
    s = dr["iof"]
    out = []
    for k in range(dr["k_lo"] + 2, dr["k_hi"]):
        f = fvg_at(h5, l5, k)
        if f is None or f[0] != s:
            continue
        _, bottom, top = f
        if s == 1 and not (bottom >= dr["L"] and top <= dr["EQ"]):
            continue
        if s == -1 and not (top <= dr["H"] and bottom >= dr["EQ"]):
            continue
        later = slice(k + 1, dr["k_hi"])
        filled = (l5[later] <= bottom).any() if s == 1 else (h5[later] >= top).any()
        if not filled:
            out.append({"bottom": bottom, "top": top})
    return out


def run(
    df: pd.DataFrame,
    boundary_hours=INDEX_FUTURES_4H_OPENS,
    lookback_hours: int = 12,
    min_lookback_coverage: float = 0.5,
    pivot_left: int = 2,
    pivot_right: int = 2,
    profiles=("reversal", "continuation"),
    max_hold_bars: int = 720,
) -> tuple[pd.Series, list[dict]]:
    """Returns ``(position series on df's index, per-trade log)``."""
    idx = df.index
    n = len(idx)
    position = np.zeros(n, dtype=float)
    log: list[dict] = []
    if n == 0:
        return pd.Series(position, index=idx, name="position"), log

    view = FiveMinuteView.build(df)
    idx5 = view.df5.index
    h5, l5, c5 = (view.df5[col].to_numpy() for col in ("high", "low", "close"))
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()

    boundary_at = {}
    for t in four_hour_boundaries(idx, boundary_hours):
        j = int(idx.searchsorted(t))
        if j < n:
            boundary_at[j] = t
    lookback = pd.Timedelta(hours=lookback_hours)
    min_bars = int(min_lookback_coverage * BARS_5M_PER_12H * lookback_hours / 12)

    rev = None   # reversal-profile state
    cont = None  # continuation-profile state
    ctx = None   # current boundary's dealing range
    active = None
    last_exit = -2  # v1 convention: always >=1 flat bar between trades

    for j in range(n):
        held_at_start = active is not None
        if active is not None:
            d = active["dir"]
            position[j] = d
            active["bars"] += 1
            reason = None
            if (d == 1 and lows[j] <= active["stop"]) or (d == -1 and highs[j] >= active["stop"]):
                reason = "stop"
            elif (d == 1 and highs[j] >= active["target"]) or (d == -1 and lows[j] <= active["target"]):
                reason = "target"
            elif active["bars"] >= max_hold_bars:
                reason = "timeout"
            if reason is not None:
                active["log"].update(exit_time=idx[j], exit_reason=reason)
                active = None
                last_exit = j

        if j in boundary_at:
            rev = cont = ctx = None
            if active is None and not held_at_start:
                t = boundary_at[j]
                k_lo, k_hi = int(idx5.searchsorted(t - lookback)), int(idx5.searchsorted(t))
                if k_hi - k_lo >= max(min_bars, 3):
                    ctx = dealing_range(h5, l5, c5, k_lo, k_hi, pivot_left, pivot_right)
                if ctx is not None:
                    ctx["boundary"] = t
                    if "reversal" in profiles:
                        rev = _initial_reversal_state(ctx)
                    on_discount_side = (
                        ctx["last_close"] < ctx["EQ"] if ctx["iof"] == 1 else ctx["last_close"] > ctx["EQ"]
                    )
                    if "continuation" in profiles and on_discount_side:
                        fvgs = _continuation_fvgs(ctx, h5, l5)
                        cont = {"fvgs": fvgs} if fvgs else None

        if ctx is None or active is not None or j <= last_exit + 1:
            continue

        s = ctx["iof"]
        lv = ctx["levels"]
        entered = None

        k = view.completes_at.get(j)
        if rev is not None and k is not None and idx5[k] >= ctx["boundary"]:
            bar_extreme = h5[k] if s == 1 else l5[k]
            close = c5[k]

            def past(a, b):  # a is beyond b in the order-flow direction
                return a > b if s == 1 else a < b

            def reached(level):
                return not past(level, bar_extreme)

            def fade(profile):
                far_side = ctx["L"] if s == 1 else ctx["H"]
                return (profile, -s, rev["extreme"] + s * MNQ_TICK_SIZE, (far_side + rev["extreme"]) / 2)

            if rev["state"] == "A" and reached(lv[REVERSAL_ZONE[0]]):
                rev["state"] = "B"
            if rev["state"] != "A" and past(bar_extreme, rev["extreme"]):
                rev["extreme"] = bar_extreme
            if rev["state"] == "B":
                if past(close, lv[REVERSAL_ZONE[1]]):
                    rev["state"] = "C"  # closed strong beyond 2.5 -> expect terminus
                elif past(lv[REVERSAL_ZONE[0]], close):
                    entered = fade("reversal_2_2.5")
            if entered is None and rev["state"] == "C" and reached(lv[TERMINUS]):
                rev["state"] = "D"
            if entered is None and rev["state"] == "D" and past(lv[TERMINUS], close):
                entered = fade("reversal_terminus")

        if entered is None and cont is not None:
            range_extreme_broken = lows[j] < ctx["L"] if s == 1 else highs[j] > ctx["H"]
            if range_extreme_broken:
                cont = None
            else:
                for f in cont["fvgs"]:
                    if (s == 1 and lows[j] <= f["top"]) or (s == -1 and highs[j] >= f["bottom"]):
                        stop = ctx["L"] - MNQ_TICK_SIZE if s == 1 else ctx["H"] + MNQ_TICK_SIZE
                        target = ctx["H"] if s == 1 else ctx["L"]
                        entered = ("continuation", s, stop, target)
                        break

        if entered is not None:
            profile, d, stop, target = entered
            entry = {
                "boundary": ctx["boundary"], "profile": profile, "direction": "long" if d == 1 else "short",
                "iof": "bullish" if s == 1 else "bearish", "range_high": ctx["H"], "range_low": ctx["L"],
                "eq": ctx["EQ"], "anchor0": ctx["anchor0"], "anchor1": ctx["anchor1"],
                "entry_time": idx[j], "stop": stop, "target": target,
            }
            log.append(entry)
            active = {"dir": d, "stop": stop, "target": target, "bars": 0, "log": entry}
            position[j] = d
            rev = cont = ctx = None

    return pd.Series(position, index=idx, name="position"), log


def generate_signals(df: pd.DataFrame, **kwargs) -> pd.Series:
    return run(df, **kwargs)[0]
