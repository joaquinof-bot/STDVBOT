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


class PO3Entry:
    """PO3's post-MSS entry and trade management, shared by ``po3_stdv`` and
    ``killzone_po3`` -- they differ only in what arms the MSS watch.

    Call order per 1m bar ``j``: :meth:`manage`, then (if a 5m bar completed)
    :meth:`arm` / :meth:`on_5m_bar`, then :meth:`step_entry`.
    """

    def __init__(self, df, entry_mode="nested", target_multiple=2.5, extend_to_terminus=True,
                 extension_stop_multiple=2.0, max_hold_bars=240):
        if entry_mode not in ("nested", "any_irl"):
            raise ValueError(f"entry_mode must be 'nested' or 'any_irl', got {entry_mode!r}")
        self.idx = df.index
        self.highs, self.lows, self.closes = (df[c].to_numpy() for c in ("high", "low", "close"))
        self.position = np.zeros(len(df), dtype=float)
        self.log: list[dict] = []
        self.entry_mode = entry_mode
        self.target_multiple = target_multiple
        self.extend_to_terminus = extend_to_terminus
        self.extension_stop_multiple = extension_stop_multiple
        self.max_hold_bars = max_hold_bars
        self.setup = None
        self.active = None
        self.last_exit = -2  # v1 convention: always >=1 flat bar between trades

    @property
    def idle(self):
        return self.setup is None and self.active is None

    def result(self):
        return pd.Series(self.position, index=self.idx, name="position"), self.log

    def manage(self, j):
        a = self.active
        if a is None:
            return
        d = a["dir"]
        self.position[j] = d
        a["bars"] += 1
        hi, lo, cl = self.highs[j], self.lows[j], self.closes[j]
        reason = None
        if (d == 1 and lo <= a["stop"]) or (d == -1 and hi >= a["stop"]):
            reason = "stop"
        elif (d == 1 and hi >= a["target"]) or (d == -1 and lo <= a["target"]):
            closes_through = cl >= a["target"] if d == 1 else cl <= a["target"]
            if self.extend_to_terminus and not a["extended"] and closes_through:
                a["extended"] = True
                a["stop"] = a["levels"][self.extension_stop_multiple]
                a["target"] = a["levels"][TERMINUS]
            else:
                reason = "target_4" if a["extended"] else "target"
        if reason is None and a["bars"] >= self.max_hold_bars:
            reason = "timeout"
        if reason is not None:
            a["log"].update(exit_time=self.idx[j], exit_reason=reason)
            self.active = None
            self.last_exit = j

    def arm(self, direction, anchor0, anchor1, extreme_k, info):
        """MSS confirmed: project STDV off the manipulation's last leg
        (``anchor0`` = the swing, ``anchor1`` = the manipulation extreme)."""
        self.setup = {"dir": direction, "anchor0": anchor0, "anchor1": anchor1, "extreme_k": extreme_k,
                      "levels": stdv_projection(anchor0, anchor1, LEVELS), "fvgs": [],
                      "reached_sbz": False, "info": info}

    def on_5m_bar(self, k, j, h5, l5):
        s = self.setup
        if s is None:
            return
        d, lv = s["dir"], s["levels"]
        if (d == 1 and h5[k] >= lv[SBZ[0]]) or (d == -1 and l5[k] <= lv[SBZ[0]]):
            s["reached_sbz"] = True
        f = fvg_at(h5, l5, k)
        if f is not None and f[0] == d and k - 2 >= s["extreme_k"]:
            _, bottom, top = f
            if self.entry_mode == "any_irl" or _overlaps_sbz(bottom, top, lv):
                s["fvgs"].append({"bottom": bottom, "top": top, "known_at": j})

    def step_entry(self, j):
        """Enter on a retrace into a qualifying FVG, or drop the setup. Returns
        ``"entered"``, ``"extreme_broken"`` (a new manipulation extreme --
        callers may re-arm on a fresh MSS), ``"target_reached"`` (the move ran
        without us -- callers should not re-arm this setup), or ``None``."""
        s = self.setup
        if s is None or self.active is not None or j <= self.last_exit + 1:
            return None
        d, lv = s["dir"], s["levels"]
        hi, lo = self.highs[j], self.lows[j]
        if self.entry_mode == "nested" or s["reached_sbz"]:
            for f in s["fvgs"]:
                if f["known_at"] < j and ((d == 1 and lo <= f["top"]) or (d == -1 and hi >= f["bottom"])):
                    stop = s["anchor1"] - d * MNQ_TICK_SIZE
                    target = lv[self.target_multiple]
                    entry = {
                        **s["info"], "direction": "long" if d == 1 else "short",
                        "anchor0": s["anchor0"], "anchor1": s["anchor1"],
                        "range": abs(s["anchor0"] - s["anchor1"]),
                        "fvg_bottom": f["bottom"], "fvg_top": f["top"],
                        "entry_time": self.idx[j], "stop": stop, "target": target,
                    }
                    self.log.append(entry)
                    self.active = {"dir": d, "stop": stop, "target": target, "levels": lv,
                                   "extended": False, "bars": 0, "log": entry}
                    self.position[j] = d
                    self.setup = None
                    return "entered"
        if (d == 1 and lo < s["anchor1"]) or (d == -1 and hi > s["anchor1"]):
            self.setup = None
            return "extreme_broken"
        if (d == 1 and hi >= lv[self.target_multiple]) or (d == -1 and lo <= lv[self.target_multiple]):
            self.setup = None
            return "target_reached"
        return None


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
    ex = PO3Entry(df, entry_mode, target_multiple, extend_to_terminus, extension_stop_multiple, max_hold_bars)
    idx = df.index
    if len(idx) == 0:
        return ex.result()

    view = FiveMinuteView.build(df)
    idx5 = view.df5.index
    o5, h5, l5, c5 = (view.df5[col].to_numpy() for col in ("open", "high", "low", "close"))

    starts_arr = pd.DatetimeIndex(four_hour_boundaries(idx, candle_hours))
    four_h = pd.Timedelta(hours=4)

    def candle_of(t):
        pos = starts_arr.searchsorted(t, side="right") - 1
        if pos < 0 or t >= starts_arr[pos] + four_h:
            return None
        return starts_arr[pos]

    pivots_hi: list[tuple[int, float]] = []
    pivots_lo: list[tuple[int, float]] = []
    candle = None
    spent = set()  # one PO3 per candle: traded, or the move ran without us

    for j in range(len(idx)):
        ex.manage(j)

        k = view.completes_at.get(j)
        if k is not None:
            _confirm_pivots(k, h5, l5, pivot_left, pivot_right, pivots_hi, pivots_lo)
            c_start = candle_of(idx5[k])
            if c_start is not None and (candle is None or candle["start"] != c_start):
                candle = {"start": c_start, "end": c_start + four_h, "k0": k, "open": o5[k],
                          "low": l5[k], "low_k": k, "high": h5[k], "high_k": k}
                ex.setup = None
            elif c_start is not None:
                if l5[k] < candle["low"]:
                    candle["low"], candle["low_k"] = l5[k], k
                if h5[k] > candle["high"]:
                    candle["high"], candle["high_k"] = h5[k], k

            if candle is not None and c_start == candle["start"]:
                if ex.idle and candle["start"] not in spent:
                    _check_mss(ex, candle, k, c5, pivots_hi, pivots_lo, swing_lookback_5m)
                ex.on_5m_bar(k, j, h5, l5)

        if ex.setup is not None and ex.active is None and idx[j] >= candle["end"]:
            ex.setup = None
        if ex.step_entry(j) in ("entered", "target_reached"):
            spent.add(candle["start"])

    return ex.result()


def _confirm_pivots(k, h5, l5, left, right, pivots_hi, pivots_lo):
    p = k - right
    if p < 0:
        return
    if pivot_confirmed_at(h5, p, left, right, "high"):
        pivots_hi.append((p, h5[p]))
    if pivot_confirmed_at(l5, p, left, right, "low"):
        pivots_lo.append((p, l5[p]))


def _check_mss(ex, candle, k, c5, pivots_hi, pivots_lo, swing_lookback_5m):
    lo_bound = candle["k0"] - swing_lookback_5m
    info = {"candle": candle["start"]}
    if candle["low"] < candle["open"] and candle["low_k"] < k:
        swing = _last_pivot_before(pivots_hi, lo_bound, candle["low_k"])
        if swing is not None and c5[k] > swing:
            ex.arm(1, swing, candle["low"], candle["low_k"], info)
            return
    if candle["high"] > candle["open"] and candle["high_k"] < k:
        swing = _last_pivot_before(pivots_lo, lo_bound, candle["high_k"])
        if swing is not None and c5[k] < swing:
            ex.arm(-1, swing, candle["high"], candle["high_k"], info)


def _last_pivot_before(pivots, lo_bound, before_k):
    for p, price in reversed(pivots):
        if p < before_k:
            return price if p >= lo_bound else None
    return None


def _overlaps_sbz(bottom, top, levels):
    band_lo, band_hi = sorted((levels[SBZ[0]], levels[SBZ[1]]))
    return top >= band_lo and bottom <= band_hi


def generate_signals(df: pd.DataFrame, **kwargs) -> pd.Series:
    return run(df, **kwargs)[0]
