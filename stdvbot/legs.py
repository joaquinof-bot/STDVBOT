"""Manipulation-leg detection and inverse-Fibonacci level projection.

See ``docs/manipulation_leg_strategy.md`` for the full spec, including
which parts of this module are confirmed rules vs. best-effort
translations of an English explanation. In short:

  1. Within a session-open window, did a directional "leg" form, and is it
     a *valid* leg (spans the confirmed 3-5 candle range), OR a shorter
     "pivotal" leg (formed in fewer candles, even a single one, but with a
     range large enough relative to normal 1-minute movement that it still
     counts) -- see :func:`is_pivotal_leg`. The 3-5 candle range is not a
     blanket requirement; a short but outsized push can be just as real.
  2. Given a valid leg, where are the inverse-Fibonacci reversal levels
     projected from it — extensions *past the leg's origin*, in the
     direction opposite the leg — and how much confidence does a touch of
     a given level carry?

This same primitive is also how higher-timeframe bias is read (confirmed):
running ``detect_leg``/``inverse_fib_levels`` on Daily or 4H bars finds the
"top of a fast pump" and its retracement zone exactly the same way — there
is no separate trend-direction mechanism. Only the timeframe of the input
DataFrame changes; the functions are identical.

Trade-direction-vs-bias wiring, confluence scoring, and the
``stdvbot/strategies.py`` integration are still open (see the spec doc's
remaining TODOs).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional

import pandas as pd

#: Observed level grid: 1 is the leg's own range; 2, 2.25, 2.5, 4, 4.5 are
#: the inverse-Fibonacci extensions past the leg's origin.
DEFAULT_LEVEL_MULTIPLES = (1.0, 2.0, 2.25, 2.5, 4.0, 4.5)

#: Confirmed leg-validity range: fewer than MIN_LEG_CANDLES is a suspect
#: single/few-candle false leg *unless* it's big enough to be "pivotal" (see
#: is_pivotal_leg); more than MAX_LEG_CANDLES is no longer treated as one
#: leg, no size exception -- 3 is the typical case, 5 the observed max.
MIN_LEG_CANDLES = 3
MAX_LEG_CANDLES = 5

#: ASSUMED DEFAULT (not yet confirmed to an exact figure): a leg shorter
#: than MIN_LEG_CANDLES still counts as "pivotal" -- real, not a false
#: leg -- if its range is at least this many times the recent typical
#: single 1-minute bar range. Per the trader: "a few or single candle
#: could be pivotal if its size is big in the differing direction" -- the
#: 3-5 candle rule was never meant as a blanket requirement, just the
#: typical case. Tune this once there's enough real-trade feedback to
#: calibrate it.
BIG_LEG_SIZE_MULTIPLE = 3.0

#: Killzones in scope (session-open time, local UTC-4, plus how many
#: minutes past the open to watch for a leg to form). London is
#: deliberately excluded — not traded.
DEFAULT_KILLZONES = {
    "asia": {"start": time(20, 0), "leg_window_minutes": 6},
    "ny": {"start": time(9, 30), "leg_window_minutes": 6},
}

#: MNQ (Micro E-mini Nasdaq-100) contract specs, for position sizing.
MNQ_TICK_SIZE = 0.25
MNQ_TICK_VALUE = 0.50  # USD per tick -> $2.00 per full index point


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
        """Confirmed range: a leg spanning ``MIN_LEG_CANDLES`` to
        ``MAX_LEG_CANDLES`` candles (3-5, 3 typical) is real; fewer is a
        suspect "false" leg, and more is no longer treated as one leg.
        See spec §2.
        """
        return MIN_LEG_CANDLES <= self.num_candles <= MAX_LEG_CANDLES


def detect_leg(
    df: pd.DataFrame, window_start: pd.Timestamp, window_end: pd.Timestamp
) -> Optional[Leg]:
    """Detect the directional leg within ``[window_start, window_end)``.

    The leg's origin is the open of the first bar in the window. The
    extreme is whichever of the window's high/low represents the larger
    directional excursion away from that origin. ``num_candles`` is the
    position of the extreme within the window (1-indexed) — a proxy for
    "how many candles did it take to form this leg," used to classify it
    as valid vs. a false leg via :attr:`Leg.is_valid`.

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


def is_pivotal_leg(
    leg: Leg,
    reference_range: Optional[float],
    size_multiple: float = BIG_LEG_SIZE_MULTIPLE,
) -> bool:
    """Whether ``leg`` should be treated as real (not a suspect false leg),
    combining the confirmed 3-5 candle rule with a size-based exception.

    Returns ``True`` if ``leg.is_valid`` (the ordinary 3-5 candle case), OR
    if the leg is *short* (fewer than :data:`MIN_LEG_CANDLES` candles) but
    its range is at least ``size_multiple`` times ``reference_range`` --
    "a few or single candle could be pivotal if its size is big in the
    differing direction." ``reference_range`` should be a measure of
    typical single-bar range (e.g. a trailing median of 1-minute
    high-low), computed without look-ahead by the caller.

    This size exception only applies to legs that are *too short*. A leg
    longer than :data:`MAX_LEG_CANDLES` is never pivotal regardless of
    size -- that's "no longer one leg," a different failure mode from "too
    fast to be real," and the trader's correction was specifically about
    the latter.

    ``reference_range`` of ``None`` or non-positive disables the size
    exception (falls back to the plain 3-5 candle rule) -- there isn't
    enough history yet to judge what counts as "big."
    """
    if leg.is_valid:
        return True
    if leg.num_candles >= MIN_LEG_CANDLES:
        return False  # too long, not too short -- no size exception applies
    if reference_range is None or reference_range <= 0:
        return False
    return leg.range_ >= size_multiple * reference_range


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
