"""Candlestick reversal patterns — confluence check (a), Procedure step 31.

Each detector answers one question: does this bar argue for a reversal in
`direction`? `direction` is the side the trade would take, so at a level
touched from below the bot is looking for bullish reversal evidence.

Thresholds are module constants rather than magic numbers so the sensitivity
analysis in Part C can vary them without editing logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .bars import Bar

# A wick must be this many times the body to count as a rejection.
WICK_TO_BODY_RATIO = 2.0
# A body smaller than this fraction of the range is "small" (doji-like).
SMALL_BODY_FRACTION = 0.3
# A doji body is at most this fraction of the range.
DOJI_BODY_FRACTION = 0.1
# The wick opposite the rejection must stay under this fraction of the range.
# Measured against range, not body: a hammer's body is tiny by definition, so
# "upper wick smaller than the body" is a bar almost nothing can satisfy.
OPPOSING_WICK_MAX_FRACTION = 0.15


class Direction(Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def opposite(self) -> Direction:
        return Direction.SHORT if self is Direction.LONG else Direction.LONG


@dataclass(frozen=True)
class PatternHit:
    name: str
    direction: Direction


def _is_bullish_engulfing(previous: Bar, current: Bar) -> bool:
    return (
        previous.is_bearish
        and current.is_bullish
        and current.close >= previous.open
        and current.open <= previous.close
    )


def _is_bearish_engulfing(previous: Bar, current: Bar) -> bool:
    return (
        previous.is_bullish
        and current.is_bearish
        and current.close <= previous.open
        and current.open >= previous.close
    )


def _is_hammer(bar: Bar) -> bool:
    """Long lower wick rejecting downside, small body near the high."""
    if bar.range <= 0 or bar.body <= 0:
        return False
    return (
        bar.lower_wick >= WICK_TO_BODY_RATIO * bar.body
        and bar.upper_wick <= OPPOSING_WICK_MAX_FRACTION * bar.range
        and bar.body <= SMALL_BODY_FRACTION * bar.range
    )


def _is_shooting_star(bar: Bar) -> bool:
    """Long upper wick rejecting upside, small body near the low."""
    if bar.range <= 0 or bar.body <= 0:
        return False
    return (
        bar.upper_wick >= WICK_TO_BODY_RATIO * bar.body
        and bar.lower_wick <= OPPOSING_WICK_MAX_FRACTION * bar.range
        and bar.body <= SMALL_BODY_FRACTION * bar.range
    )


def _is_doji(bar: Bar) -> bool:
    if bar.range <= 0:
        return False
    return bar.body <= DOJI_BODY_FRACTION * bar.range


def _is_bullish_pin_bar(bar: Bar) -> bool:
    """Rejection from below regardless of body colour."""
    return bar.range > 0 and bar.lower_wick >= 0.6 * bar.range


def _is_bearish_pin_bar(bar: Bar) -> bool:
    return bar.range > 0 and bar.upper_wick >= 0.6 * bar.range


def detect(bars: list[Bar], index: int = -1) -> list[PatternHit]:
    """Every reversal pattern firing on `bars[index]`.

    Patterns needing a prior bar are skipped when none exists rather than
    raising, so the first bar of a session is simply pattern-free.
    """
    if not bars:
        return []
    current = bars[index]
    previous = None
    absolute = index if index >= 0 else len(bars) + index
    if absolute > 0:
        previous = bars[absolute - 1]

    hits: list[PatternHit] = []

    if previous is not None:
        if _is_bullish_engulfing(previous, current):
            hits.append(PatternHit("bullish_engulfing", Direction.LONG))
        if _is_bearish_engulfing(previous, current):
            hits.append(PatternHit("bearish_engulfing", Direction.SHORT))

    if _is_hammer(current):
        hits.append(PatternHit("hammer", Direction.LONG))
    if _is_shooting_star(current):
        hits.append(PatternHit("shooting_star", Direction.SHORT))
    if _is_bullish_pin_bar(current):
        hits.append(PatternHit("bullish_pin_bar", Direction.LONG))
    if _is_bearish_pin_bar(current):
        hits.append(PatternHit("bearish_pin_bar", Direction.SHORT))
    if _is_doji(current):
        # A doji is indecision, so it supports a reversal either way.
        hits.append(PatternHit("doji", Direction.LONG))
        hits.append(PatternHit("doji", Direction.SHORT))

    return hits


def fires(bars: list[Bar], direction: Direction, index: int = -1) -> bool:
    """Confluence check (a): does any pattern support `direction` here?"""
    return any(hit.direction is direction for hit in detect(bars, index))
