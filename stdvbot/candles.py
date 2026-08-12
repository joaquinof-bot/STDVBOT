"""Candle feature engineering and candlestick pattern detection.

All functions are vectorized over a pandas DataFrame with columns
``open, high, low, close`` (a ``volume`` column is tolerated but not
required). Detection at row ``i`` only ever looks at rows ``<= i``, so
these features are safe to use for signal generation in a backtest
that executes on the *next* bar (see :mod:`stdvbot.backtest`).

Pattern functions return boolean ``pd.Series`` aligned to the input
index. A ``True`` at index ``i`` means "the pattern completed as of
the close of bar ``i``".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLS = ("open", "high", "low", "close")


def _check_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required OHLC columns: {missing}")


def add_candle_features(df: pd.DataFrame, trend_window: int = 20) -> pd.DataFrame:
    """Return a copy of ``df`` with derived per-candle geometry columns.

    Added columns:
      body        close - open (signed)
      body_abs    |close - open|
      range_      high - low (candle's total range; 0-range candles are
                  handled safely via a small epsilon)
      upper_wick  high - max(open, close)
      lower_wick  min(open, close) - low
      body_pct    body_abs / range_  (fraction of the range the body fills)
      is_bullish  close > open
      is_bearish  close < open
      trend_sma   simple moving average of close over trend_window
      uptrend     close > trend_sma (a cheap trend-context filter)
      downtrend   close < trend_sma
    """
    _check_columns(df)
    out = df.copy()

    body = out["close"] - out["open"]
    rng = (out["high"] - out["low"]).astype(float)
    eps = 1e-12
    safe_rng = rng.where(rng > eps, eps)

    out["body"] = body
    out["body_abs"] = body.abs()
    out["range_"] = rng
    out["upper_wick"] = out["high"] - out[["open", "close"]].max(axis=1)
    out["lower_wick"] = out[["open", "close"]].min(axis=1) - out["low"]
    out["body_pct"] = out["body_abs"] / safe_rng
    out["is_bullish"] = out["close"] > out["open"]
    out["is_bearish"] = out["close"] < out["open"]

    out["trend_sma"] = out["close"].rolling(trend_window, min_periods=trend_window).mean()
    out["uptrend"] = out["close"] > out["trend_sma"]
    out["downtrend"] = out["close"] < out["trend_sma"]

    return out


# ---------------------------------------------------------------------------
# Single-candle patterns
# ---------------------------------------------------------------------------

def doji(df: pd.DataFrame, body_pct_max: float = 0.1) -> pd.Series:
    """Body is a tiny fraction of the candle's range (indecision)."""
    f = add_candle_features(df) if "body_pct" not in df.columns else df
    return (f["body_pct"] <= body_pct_max).rename("doji")


def hammer(
    df: pd.DataFrame,
    wick_body_mult: float = 2.0,
    opp_wick_max_mult: float = 0.5,
    require_downtrend: bool = True,
) -> pd.Series:
    """Bullish reversal: small body near the top, long lower wick, forming
    after a downtrend. (Same shape after an uptrend is a "hanging man" —
    see :func:`hanging_man`.)
    """
    f = add_candle_features(df) if "lower_wick" not in df.columns else df
    body = f["body_abs"].clip(lower=1e-12)
    shape = (f["lower_wick"] >= wick_body_mult * body) & (
        f["upper_wick"] <= opp_wick_max_mult * body
    )
    cond = shape
    if require_downtrend:
        cond = cond & f["downtrend"].fillna(False)
    return cond.rename("hammer")


def hanging_man(
    df: pd.DataFrame,
    wick_body_mult: float = 2.0,
    opp_wick_max_mult: float = 0.5,
    require_uptrend: bool = True,
) -> pd.Series:
    """Bearish reversal: hammer-shaped candle forming after an uptrend."""
    f = add_candle_features(df) if "lower_wick" not in df.columns else df
    body = f["body_abs"].clip(lower=1e-12)
    shape = (f["lower_wick"] >= wick_body_mult * body) & (
        f["upper_wick"] <= opp_wick_max_mult * body
    )
    cond = shape
    if require_uptrend:
        cond = cond & f["uptrend"].fillna(False)
    return cond.rename("hanging_man")


def inverted_hammer(
    df: pd.DataFrame,
    wick_body_mult: float = 2.0,
    opp_wick_max_mult: float = 0.5,
    require_downtrend: bool = True,
) -> pd.Series:
    """Bullish reversal: small body near the bottom, long upper wick,
    forming after a downtrend."""
    f = add_candle_features(df) if "upper_wick" not in df.columns else df
    body = f["body_abs"].clip(lower=1e-12)
    shape = (f["upper_wick"] >= wick_body_mult * body) & (
        f["lower_wick"] <= opp_wick_max_mult * body
    )
    cond = shape
    if require_downtrend:
        cond = cond & f["downtrend"].fillna(False)
    return cond.rename("inverted_hammer")


def shooting_star(
    df: pd.DataFrame,
    wick_body_mult: float = 2.0,
    opp_wick_max_mult: float = 0.5,
    require_uptrend: bool = True,
) -> pd.Series:
    """Bearish reversal: inverted-hammer-shaped candle after an uptrend."""
    f = add_candle_features(df) if "upper_wick" not in df.columns else df
    body = f["body_abs"].clip(lower=1e-12)
    shape = (f["upper_wick"] >= wick_body_mult * body) & (
        f["lower_wick"] <= opp_wick_max_mult * body
    )
    cond = shape
    if require_uptrend:
        cond = cond & f["uptrend"].fillna(False)
    return cond.rename("shooting_star")


# ---------------------------------------------------------------------------
# Two-candle patterns
# ---------------------------------------------------------------------------

def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Prior bearish candle fully engulfed by a bullish candle's body."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    p_open, p_close = f["open"].shift(1), f["close"].shift(1)
    p_bear = f["is_bearish"].shift(1).fillna(False)
    cond = (
        p_bear
        & f["is_bullish"]
        & (f["open"] <= p_close)
        & (f["close"] >= p_open)
        & (f["body_abs"] > f["body_abs"].shift(1))
    )
    return cond.fillna(False).rename("bullish_engulfing")


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Prior bullish candle fully engulfed by a bearish candle's body."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    p_open, p_close = f["open"].shift(1), f["close"].shift(1)
    p_bull = f["is_bullish"].shift(1).fillna(False)
    cond = (
        p_bull
        & f["is_bearish"]
        & (f["open"] >= p_close)
        & (f["close"] <= p_open)
        & (f["body_abs"] > f["body_abs"].shift(1))
    )
    return cond.fillna(False).rename("bearish_engulfing")


def bullish_harami(df: pd.DataFrame) -> pd.Series:
    """Large bearish candle followed by a small bullish candle whose body
    sits inside the prior body (compression / possible reversal up)."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    p_open, p_close = f["open"].shift(1), f["close"].shift(1)
    p_bear = f["is_bearish"].shift(1).fillna(False)
    cond = (
        p_bear
        & f["is_bullish"]
        & (f["open"] >= f["close"].shift(1))
        & (f["close"] <= f["open"].shift(1))
        & (f["body_abs"] < f["body_abs"].shift(1))
    )
    return cond.fillna(False).rename("bullish_harami")


def bearish_harami(df: pd.DataFrame) -> pd.Series:
    """Large bullish candle followed by a small bearish candle whose body
    sits inside the prior body (compression / possible reversal down)."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    p_bull = f["is_bullish"].shift(1).fillna(False)
    cond = (
        p_bull
        & f["is_bearish"]
        & (f["open"] <= f["close"].shift(1))
        & (f["close"] >= f["open"].shift(1))
        & (f["body_abs"] < f["body_abs"].shift(1))
    )
    return cond.fillna(False).rename("bearish_harami")


def piercing_line(df: pd.DataFrame) -> pd.Series:
    """Bearish candle followed by a bullish candle that opens below the
    prior low and closes above the midpoint of the prior body."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    p_open, p_close, p_low = f["open"].shift(1), f["close"].shift(1), f["low"].shift(1)
    p_bear = f["is_bearish"].shift(1).fillna(False)
    midpoint = (p_open + p_close) / 2.0
    cond = (
        p_bear
        & f["is_bullish"]
        & (f["open"] < p_low)
        & (f["close"] > midpoint)
        & (f["close"] < p_open)
    )
    return cond.fillna(False).rename("piercing_line")


def dark_cloud_cover(df: pd.DataFrame) -> pd.Series:
    """Bullish candle followed by a bearish candle that opens above the
    prior high and closes below the midpoint of the prior body."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    p_open, p_close, p_high = f["open"].shift(1), f["close"].shift(1), f["high"].shift(1)
    p_bull = f["is_bullish"].shift(1).fillna(False)
    midpoint = (p_open + p_close) / 2.0
    cond = (
        p_bull
        & f["is_bearish"]
        & (f["open"] > p_high)
        & (f["close"] < midpoint)
        & (f["close"] > p_open)
    )
    return cond.fillna(False).rename("dark_cloud_cover")


# ---------------------------------------------------------------------------
# Three-candle patterns
# ---------------------------------------------------------------------------

def morning_star(df: pd.DataFrame, star_body_pct_max: float = 0.3) -> pd.Series:
    """Big bearish candle, small-bodied "star" that gaps down, then a
    bullish candle closing back into the first candle's body — a bottoming
    reversal."""
    f = add_candle_features(df) if "body_pct" not in df.columns else df
    c1_bear = f["is_bearish"].shift(2).fillna(False)
    c1_open, c1_close = f["open"].shift(2), f["close"].shift(2)
    c1_mid = (c1_open + c1_close) / 2.0
    star_small = f["body_pct"].shift(1) <= star_body_pct_max
    star_gap_down = f[["open", "close"]].shift(1).max(axis=1) < c1_close
    c3_bull = f["is_bullish"]
    c3_closes_into_c1 = f["close"] > c1_mid
    cond = c1_bear & star_small & star_gap_down & c3_bull & c3_closes_into_c1
    return cond.fillna(False).rename("morning_star")


def evening_star(df: pd.DataFrame, star_body_pct_max: float = 0.3) -> pd.Series:
    """Big bullish candle, small-bodied "star" that gaps up, then a
    bearish candle closing back into the first candle's body — a topping
    reversal."""
    f = add_candle_features(df) if "body_pct" not in df.columns else df
    c1_bull = f["is_bullish"].shift(2).fillna(False)
    c1_open, c1_close = f["open"].shift(2), f["close"].shift(2)
    c1_mid = (c1_open + c1_close) / 2.0
    star_small = f["body_pct"].shift(1) <= star_body_pct_max
    star_gap_up = f[["open", "close"]].shift(1).min(axis=1) > c1_close
    c3_bear = f["is_bearish"]
    c3_closes_into_c1 = f["close"] < c1_mid
    cond = c1_bull & star_small & star_gap_up & c3_bear & c3_closes_into_c1
    return cond.fillna(False).rename("evening_star")


def three_white_soldiers(df: pd.DataFrame, max_wick_body_mult: float = 0.5) -> pd.Series:
    """Three consecutive bullish candles, each closing higher than the
    last and opening within the previous body, with modest wicks — strong
    upward continuation/reversal."""
    f = add_candle_features(df) if "is_bullish" not in df.columns else df
    bull0, bull1, bull2 = f["is_bullish"], f["is_bullish"].shift(1), f["is_bullish"].shift(2)
    rising_closes = (f["close"] > f["close"].shift(1)) & (f["close"].shift(1) > f["close"].shift(2))
    opens_within = (
        (f["open"] > f["open"].shift(1)) & (f["open"] <= f["close"].shift(1))
        & (f["open"].shift(1) > f["open"].shift(2)) & (f["open"].shift(1) <= f["close"].shift(2))
    )
    small_wicks = (
        (f["upper_wick"] <= max_wick_body_mult * f["body_abs"].clip(lower=1e-12))
        & (f["upper_wick"].shift(1) <= max_wick_body_mult * f["body_abs"].shift(1).clip(lower=1e-12))
    )
    cond = bull0.fillna(False) & bull1.fillna(False) & bull2.fillna(False) & rising_closes & opens_within & small_wicks
    return cond.fillna(False).rename("three_white_soldiers")


def three_black_crows(df: pd.DataFrame, max_wick_body_mult: float = 0.5) -> pd.Series:
    """Three consecutive bearish candles, each closing lower than the
    last and opening within the previous body — strong downward
    continuation/reversal."""
    f = add_candle_features(df) if "is_bearish" not in df.columns else df
    bear0, bear1, bear2 = f["is_bearish"], f["is_bearish"].shift(1), f["is_bearish"].shift(2)
    falling_closes = (f["close"] < f["close"].shift(1)) & (f["close"].shift(1) < f["close"].shift(2))
    opens_within = (
        (f["open"] < f["open"].shift(1)) & (f["open"] >= f["close"].shift(1))
        & (f["open"].shift(1) < f["open"].shift(2)) & (f["open"].shift(1) >= f["close"].shift(2))
    )
    small_wicks = (
        (f["lower_wick"] <= max_wick_body_mult * f["body_abs"].clip(lower=1e-12))
        & (f["lower_wick"].shift(1) <= max_wick_body_mult * f["body_abs"].shift(1).clip(lower=1e-12))
    )
    cond = bear0.fillna(False) & bear1.fillna(False) & bear2.fillna(False) & falling_closes & opens_within & small_wicks
    return cond.fillna(False).rename("three_black_crows")


# Bullish patterns are worth +1, bearish -1, in the composite score.
PATTERN_DIRECTION = {
    "hammer": 1,
    "inverted_hammer": 1,
    "bullish_engulfing": 1,
    "bullish_harami": 1,
    "piercing_line": 1,
    "morning_star": 1,
    "three_white_soldiers": 1,
    "hanging_man": -1,
    "shooting_star": -1,
    "bearish_engulfing": -1,
    "bearish_harami": -1,
    "dark_cloud_cover": -1,
    "evening_star": -1,
    "three_black_crows": -1,
}

ALL_PATTERN_FUNCS = {
    "hammer": hammer,
    "hanging_man": hanging_man,
    "inverted_hammer": inverted_hammer,
    "shooting_star": shooting_star,
    "bullish_engulfing": bullish_engulfing,
    "bearish_engulfing": bearish_engulfing,
    "bullish_harami": bullish_harami,
    "bearish_harami": bearish_harami,
    "piercing_line": piercing_line,
    "dark_cloud_cover": dark_cloud_cover,
    "morning_star": morning_star,
    "evening_star": evening_star,
    "three_white_soldiers": three_white_soldiers,
    "three_black_crows": three_black_crows,
}


def detect_patterns(df: pd.DataFrame, trend_window: int = 20, patterns=None) -> pd.DataFrame:
    """Compute candle features plus every (or a selected subset of)
    pattern column, and a signed ``pattern_score`` summing +1/-1 per
    bullish/bearish pattern firing on that bar.

    Returns a new DataFrame; the input is not mutated.
    """
    _check_columns(df)
    f = add_candle_features(df, trend_window=trend_window)

    names = list(ALL_PATTERN_FUNCS) if patterns is None else list(patterns)
    unknown = set(names) - set(ALL_PATTERN_FUNCS)
    if unknown:
        raise ValueError(f"Unknown pattern name(s): {sorted(unknown)}")

    for name in names:
        f[name] = ALL_PATTERN_FUNCS[name](f)

    score = pd.Series(0, index=f.index, dtype=int)
    for name in names:
        score = score + f[name].astype(int) * PATTERN_DIRECTION[name]
    f["pattern_score"] = score

    return f
