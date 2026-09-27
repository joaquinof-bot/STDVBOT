"""Standard Deviation (STDV) primitives shared by the PO3 and IPDA strategies.

Source material: "Standard Deviation + Power of Three" and "Liquidity
Profiles + Standard Deviation Theory" (po3trader, crediting ICT and
TraderDext3r). See ``docs/stdv_po3_ipda.md`` for the full translation.

**STDV projection is the same math as** :func:`stdvbot.legs.inverse_fib_levels`.
The PDFs' TradingView Fib tool is set to levels 0, 1, -1, -1.5, -2, -2.5, -4,
dragged with "1" on the leg's extreme and "0" on the leg's start, so
``level(-m) = start + m * (start - extreme)`` -- projected past the leg's
start, opposite the leg's direction. That is exactly what
``inverse_fib_levels`` already computes (``stdv_projection`` just takes raw
prices instead of a ``Leg``); ``tests/test_stdv.py`` pins the equivalence.

Everything here is look-ahead safe: a 5-minute bar is only usable once its
last 1-minute bar has closed, a pivot is only usable ``right`` bars after it
forms, and an FVG only once its third candle has closed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .manipulation_leg_strategy import resample_ohlc

#: Fib levels from the PDF's tool setup (absolute values of -1, -1.5, -2, -2.5, -4).
STDV_MULTIPLES = (1.0, 1.5, 2.0, 2.5, 4.0)
#: 1-1.5 = Silver Bullet Zone (re-accumulation / re-distribution).
SBZ = (1.0, 1.5)
#: 2-2.5 = reversal / retracement zone; 4 = terminus.
REVERSAL_ZONE = (2.0, 2.5)
TERMINUS = 4.0

#: 4H candle opens for index futures, local (UTC-4) wall-clock hours. The
#: IPDA PDF names 02:00 / 06:00 / 10:00; the rest of the 4H grid follows.
INDEX_FUTURES_4H_OPENS = (2, 6, 10, 14, 18, 22)


def stdv_projection(start: float, extreme: float, multiples=STDV_MULTIPLES) -> dict[float, float]:
    """``{m: start + m * (start - extreme)}`` -- levels past the leg's start,
    opposite its direction. A down leg (start above extreme) projects up; an
    up leg projects down."""
    return {m: start + m * (start - extreme) for m in multiples}


@dataclass
class FiveMinuteView:
    """A 5-minute resample of 1-minute data, plus the 1-minute position at
    which each 5-minute bar becomes known (its last 1-minute bar)."""

    df5: pd.DataFrame
    completes_at: dict[int, int]  # 1m position -> 5m bar index completed there

    @classmethod
    def build(cls, df: pd.DataFrame) -> "FiveMinuteView":
        df5 = resample_ohlc(df, "5min")
        idx1 = df.index
        ends = idx1.searchsorted(df5.index + pd.Timedelta(minutes=5), side="left") - 1
        completes_at = {int(pos): k for k, pos in enumerate(ends) if pos >= 0}
        return cls(df5=df5, completes_at=completes_at)


def pivot_confirmed_at(values: np.ndarray, k: int, left: int, right: int, kind: str) -> bool:
    """Is bar ``k`` a swing high/low, judged with ``left`` bars before and
    ``right`` bars after? Only callable once bar ``k + right`` has closed."""
    if k - left < 0 or k + right >= len(values):
        return False
    window = values[k - left : k + right + 1]
    v = values[k]
    if kind == "high":
        return v == window.max() and v > values[k - left : k].max()
    return v == window.min() and v < values[k - left : k].min()


def fvg_at(highs: np.ndarray, lows: np.ndarray, k: int):
    """The fair value gap completed by bar ``k`` (3-candle pattern k-2..k),
    as ``(direction, bottom, top)``, or ``None``. Bullish: ``low[k] >
    high[k-2]``; bearish: ``high[k] < low[k-2]``."""
    if k < 2:
        return None
    if lows[k] > highs[k - 2]:
        return (1, highs[k - 2], lows[k])
    if highs[k] < lows[k - 2]:
        return (-1, highs[k], lows[k - 2])
    return None


def four_hour_boundaries(idx: pd.DatetimeIndex, hours=INDEX_FUTURES_4H_OPENS) -> list[pd.Timestamp]:
    """Every 4H candle open time (local wall clock) spanned by ``idx``."""
    if len(idx) == 0:
        return []
    out = []
    for day in pd.date_range(idx[0].normalize(), idx[-1].normalize(), freq="D"):
        for h in hours:
            t = day + pd.Timedelta(hours=h)
            if idx[0] <= t <= idx[-1]:
                out.append(t)
    return sorted(out)
