"""Manipulation-leg detection and inverse-Fibonacci level projection.

See ``docs/manipulation_leg_strategy.md`` for the full spec, including
which parts of this module are confirmed rules vs. best-effort
translations of an English explanation that are still pending
confirmation. In short:

  1. Within a session-open window, did a directional "leg" form, and is it
     a *valid* leg (spans multiple candles) or a suspect *false* leg
     (formed by a single fast candle)?
  2. Given a valid leg, where are the inverse-Fibonacci reversal levels
     projected from it — extensions *past the leg's origin*, in the
     direction opposite the leg — and how much confidence does a touch of
     a given level carry?

Nothing here decides trade direction relative to a higher-timeframe bias,
picks confluence, or wires into ``stdvbot/strategies.py`` yet — those
pieces are still open questions (see the spec doc's TODOs).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional

import pandas as pd

#: Observed level grid: 1 is the leg's own range; 2, 2.25, 2.5, 4, 4.5 are
#: the inverse-Fibonacci extensions past the leg's origin.
DEFAULT_LEVEL_MULTIPLES = (1.0, 2.0, 2.25, 2.5, 4.0, 4.5)


@dataclass(frozen=True)
class Leg:
    """A directional price leg detected within a session window."""

    origin_time: pd.Timestamp
    origin_price: float
    extreme_time: pd.Timestamp
    extreme_price: float
    num_candles: int
    direction: str  # "up" or "down"

    @property
    def range_(self) -> float:
        return abs(self.extreme_price - self.origin_price)

    @property
    def is_valid(self) -> bool:
        """A leg formed by a single candle is a suspect ("false") leg;
        one spanning multiple candles is treated as real. See spec §2.
        """
        return self.num_candles >= 2


def detect_leg(
    df: pd.DataFrame, window_start: pd.Timestamp, window_end: pd.Timestamp
) -> Optional[Leg]:
    """Detect the directional leg within ``[window_start, window_end)``.

    The leg's origin is the open of the first bar in the window. The
    extreme is whichever of the window's high/low represents the larger
    directional excursion away from that origin. ``num_candles`` is the
    position of the extreme within the window (1-indexed) — a proxy for
    "how many candles did it take to form this leg," used to classify it
    as valid vs. a single-candle false leg via :attr:`Leg.is_valid`.

    This does not require the intervening bars to move monotonically
    toward the extreme, only that the extreme occurs at that position —
    a deliberate simplification pending confirmation of the exact
    formation rule (see spec §2 TODOs).

    Returns ``None`` if the window contains no bars.
    """
    window = df.loc[(df.index >= window_start) & (df.index < window_end)]
    if window.empty:
        return None

    origin_time = window.index[0]
    origin_price = float(window["open"].iloc[0])

    up_excursion = float(window["high"].max()) - origin_price
    down_excursion = origin_price - float(window["low"].min())

    if up_excursion >= down_excursion:
        direction = "up"
        extreme_price = float(window["high"].max())
        extreme_idx = window["high"].idxmax()
    else:
        direction = "down"
        extreme_price = float(window["low"].min())
        extreme_idx = window["low"].idxmin()

    num_candles = window.index.get_loc(extreme_idx) + 1

    return Leg(
        origin_time=origin_time,
        origin_price=origin_price,
        extreme_time=extreme_idx,
        extreme_price=extreme_price,
        num_candles=int(num_candles),
        direction=direction,
    )


def session_window(
    date: pd.Timestamp, start: time, end: time
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Build a ``[start, end)`` timestamp pair for a calendar date and a
    time-of-day window, handling windows that cross midnight (e.g. an
    Asia session window like 20:00-02:00).
    """
    window_start = pd.Timestamp.combine(date.date(), start)
    window_end = pd.Timestamp.combine(date.date(), end)
    if window_end <= window_start:
        window_end += pd.Timedelta(days=1)
    return window_start, window_end


def inverse_fib_levels(
    leg: Leg, multiples=DEFAULT_LEVEL_MULTIPLES
) -> dict[float, float]:
    """Project inverse-Fibonacci levels from ``leg``: extensions past the
    leg's origin, in the direction opposite the leg, sized as multiples of
    the leg's own range (see spec §3 for the formula and the confirmation
    caveat — this is inferred from observed level labels and one worked
    example, not yet confirmed as the literal construction).

    An upward leg projects levels *below* the origin; a downward leg
    projects levels *above* the origin. Returns ``{multiple: price}``.
    """
    sign = -1.0 if leg.direction == "up" else 1.0
    return {m: leg.origin_price + sign * m * leg.range_ for m in multiples}


def zone_grade(multiple: float, low: float = 2.0, high: float = 4.5) -> float:
    """A rough 0-1 confidence score for a level multiple, anchored on the
    two graded examples given so far: ``low`` ("B-" — plausible but needs
    confluence) maps to 0.0, ``high`` ("A+" — near-standalone signal) maps
    to 1.0. Linear interpolation between them is a placeholder, not a
    confirmed rule (spec §3 TODOs). Values at/below ``low`` return 0.0;
    at/above ``high`` return 1.0.
    """
    if multiple <= low:
        return 0.0
    if multiple >= high:
        return 1.0
    return (multiple - low) / (high - low)
