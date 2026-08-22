"""Strategies that turn candlestick patterns into a target-position series.

Every strategy exposes ``generate_signals(df) -> pd.Series`` returning a
target position for each bar in ``{-1, 0, 1}`` (short / flat / long).
The signal at bar ``i`` is computed only from data available *at* bar
``i``'s close — :mod:`stdvbot.backtest` is responsible for shifting
execution to the next bar's open so there is no look-ahead bias.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from . import candles as c
from . import manipulation_leg_strategy as mls


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


class Strategy:
    """Base class. Subclasses implement :meth:`generate_signals`."""

    name: str = "strategy"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:  # pragma: no cover
        raise NotImplementedError


@dataclass
class ReversalStrategy(Strategy):
    """Trade single/two/three-candle reversal patterns *with* a trend
    filter: only take bullish reversal signals in a downtrend (buying the
    dip) and bearish reversal signals in an uptrend (selling the rip).
    Optionally requires RSI to confirm oversold/overbought.

    A position, once opened, is held until an opposite-direction signal
    fires or ``max_hold`` bars have elapsed (0 disables the time exit).
    """

    name: str = "candle_reversal"
    trend_window: int = 20
    rsi_window: int = 14
    rsi_oversold: float = 40.0
    rsi_overbought: float = 60.0
    use_rsi_filter: bool = True
    max_hold: int = 10
    bullish_patterns: Iterable[str] = field(
        default_factory=lambda: (
            "hammer",
            "inverted_hammer",
            "bullish_engulfing",
            "piercing_line",
            "morning_star",
        )
    )
    bearish_patterns: Iterable[str] = field(
        default_factory=lambda: (
            "hanging_man",
            "shooting_star",
            "bearish_engulfing",
            "dark_cloud_cover",
            "evening_star",
        )
    )

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        patterns = list(self.bullish_patterns) + list(self.bearish_patterns)
        f = c.detect_patterns(df, trend_window=self.trend_window, patterns=patterns)
        rsi = _rsi(f["close"], self.rsi_window)

        bull_fire = f[list(self.bullish_patterns)].any(axis=1)
        bear_fire = f[list(self.bearish_patterns)].any(axis=1)

        long_entry = bull_fire & f["downtrend"].fillna(False)
        short_entry = bear_fire & f["uptrend"].fillna(False)
        if self.use_rsi_filter:
            long_entry = long_entry & (rsi <= self.rsi_oversold)
            short_entry = short_entry & (rsi >= self.rsi_overbought)

        return _entries_to_positions(long_entry, short_entry, max_hold=self.max_hold)


@dataclass
class ContinuationStrategy(Strategy):
    """Trade three-candle continuation patterns (three white soldiers /
    three black crows) *with* the trend: only take longs in an uptrend
    and shorts in a downtrend. Positions are held until an opposite
    signal or ``max_hold`` bars.
    """

    name: str = "candle_continuation"
    trend_window: int = 20
    max_hold: int = 15

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        f = c.detect_patterns(
            df,
            trend_window=self.trend_window,
            patterns=["three_white_soldiers", "three_black_crows"],
        )
        long_entry = f["three_white_soldiers"] & f["uptrend"].fillna(False)
        short_entry = f["three_black_crows"] & f["downtrend"].fillna(False)
        return _entries_to_positions(long_entry, short_entry, max_hold=self.max_hold)


@dataclass
class CompositeScoreStrategy(Strategy):
    """Aggregate every detected pattern into a signed score (+1 per
    bullish pattern firing, -1 per bearish) on a rolling window, and go
    long/short when the smoothed score crosses a threshold. This is the
    "throw everything in and vote" strategy — noisier but broader
    coverage than the single-pattern strategies above.
    """

    name: str = "candle_composite"
    trend_window: int = 20
    score_window: int = 3
    entry_threshold: int = 2
    max_hold: int = 10
    require_trend_alignment: bool = True

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        f = c.detect_patterns(df, trend_window=self.trend_window)
        rolling_score = f["pattern_score"].rolling(self.score_window, min_periods=1).sum()

        long_entry = rolling_score >= self.entry_threshold
        short_entry = rolling_score <= -self.entry_threshold
        if self.require_trend_alignment:
            long_entry = long_entry & f["downtrend"].fillna(False)
            short_entry = short_entry & f["uptrend"].fillna(False)

        return _entries_to_positions(long_entry, short_entry, max_hold=self.max_hold)


@dataclass
class ManipulationLegStrategy(Strategy):
    """Wraps :func:`stdvbot.manipulation_leg_strategy.generate_signals` to
    fit the same ``Strategy`` interface as the candlestick strategies.
    Requires intraday data with real killzone-aligned timestamps (1m or
    finer) — see :mod:`stdvbot.manipulation_leg_strategy`'s module
    docstring (including a correction to the spec doc's trade-direction
    description) and ``docs/manipulation_leg_strategy.md`` for what's
    confirmed vs. assumed here.
    """

    name: str = "manipulation_leg"
    daily_bias_lookback: int = 20
    regime_window: int = 20
    regime_trending_threshold: float = 0.3
    touch_scan_bars: int = 60
    max_hold_bars: int = 120

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return mls.generate_signals(
            df,
            daily_bias_lookback=self.daily_bias_lookback,
            regime_window=self.regime_window,
            regime_trending_threshold=self.regime_trending_threshold,
            touch_scan_bars=self.touch_scan_bars,
            max_hold_bars=self.max_hold_bars,
        )


def _entries_to_positions(
    long_entry: pd.Series, short_entry: pd.Series, max_hold: int = 0
) -> pd.Series:
    """Turn boolean long/short entry triggers into a stateful target
    position series in {-1, 0, 1}.

    Rule: on a long-entry bar, enter/stay long. On a short-entry bar,
    enter/stay short. If both fire on the same bar, flatten (ambiguous
    signal) rather than guess a direction. Otherwise hold the current
    position until an opposite trigger fires or ``max_hold`` bars have
    passed since entry (0 = no time-based exit).
    """
    idx = long_entry.index
    long_entry = long_entry.fillna(False).to_numpy()
    short_entry = short_entry.fillna(False).to_numpy()

    pos = np.zeros(len(idx), dtype=int)
    current = 0
    bars_held = 0
    for i in range(len(idx)):
        both = long_entry[i] and short_entry[i]
        if both:
            current = 0
            bars_held = 0
        elif long_entry[i]:
            if current != 1:
                current = 1
                bars_held = 0
        elif short_entry[i]:
            if current != -1:
                current = -1
                bars_held = 0
        elif current != 0 and max_hold and bars_held >= max_hold:
            current = 0
            bars_held = 0

        if current != 0:
            bars_held += 1
        pos[i] = current

    return pd.Series(pos, index=idx, name="position")


STRATEGY_REGISTRY = {
    "reversal": ReversalStrategy,
    "continuation": ContinuationStrategy,
    "composite": CompositeScoreStrategy,
    "manipulation_leg": ManipulationLegStrategy,
}


def get_strategy(name: str, **kwargs) -> Strategy:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy '{name}'. Choices: {sorted(STRATEGY_REGISTRY)}"
        )
    return STRATEGY_REGISTRY[name](**kwargs)
