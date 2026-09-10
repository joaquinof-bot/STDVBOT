"""Swing-pivot trendline detection.

Pivots are classic "fractal" swing points: a bar is a pivot high if its
high is the max within a symmetric window of bars on either side (and
similarly for pivot lows). A pivot at bar i can only be *confirmed*
`window` bars later, once the bars after it are known — `rolling_trendlines`
respects that so nothing here is lookahead-biased in a backtest.

A trendline is the least-squares line through the most recent N confirmed
pivot highs (resistance) or pivot lows (support).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def find_pivots(df: pd.DataFrame, window: int = 3) -> tuple[pd.Series, pd.Series]:
    """Return (is_pivot_high, is_pivot_low) boolean Series.

    NOTE: these flags use `window` bars on *both* sides, i.e. they are
    known only in hindsight. For no-lookahead use in a backtest, use
    `rolling_trendlines` instead, which confirms a pivot only `window`
    bars after it occurs.
    """
    high = df["high"]
    low = df["low"]
    roll_max = high.rolling(window * 2 + 1, center=True).max()
    roll_min = low.rolling(window * 2 + 1, center=True).min()
    is_ph = (high == roll_max) & roll_max.notna()
    is_pl = (low == roll_min) & roll_min.notna()
    return is_ph, is_pl


def fit_trendline(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    """Least-squares line (slope, intercept) through the given points."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if len(xs) < 2 or len(set(xs.tolist())) < 2:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def trendline_value(slope: float, intercept: float, x: float) -> float:
    return slope * x + intercept


def rolling_trendlines(
    df: pd.DataFrame, window: int = 3, use_last_n: int = 2, max_points: int = 50
) -> pd.DataFrame:
    """Bar-by-bar resistance/support trendlines with no lookahead.

    Returns a DataFrame indexed like `df` with columns:
    res_slope, res_intercept, res_value, sup_slope, sup_intercept, sup_value.
    A value is NaN until at least 2 pivots of that type have been confirmed.
    """
    n = len(df)
    positions = np.arange(n)
    is_ph, is_pl = find_pivots(df, window=window)
    is_ph_arr = is_ph.to_numpy()
    is_pl_arr = is_pl.to_numpy()

    res_slope = np.full(n, np.nan)
    res_intercept = np.full(n, np.nan)
    sup_slope = np.full(n, np.nan)
    sup_intercept = np.full(n, np.nan)

    ph_points: list[tuple[int, float]] = []
    pl_points: list[tuple[int, float]] = []
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    cur_res: tuple[float, float] = (float("nan"), float("nan"))
    cur_sup: tuple[float, float] = (float("nan"), float("nan"))

    for i in range(n):
        confirm_idx = i - window
        if confirm_idx >= 0:
            if is_ph_arr[confirm_idx]:
                ph_points.append((confirm_idx, highs[confirm_idx]))
                if len(ph_points) > max_points:
                    ph_points.pop(0)
                if len(ph_points) >= 2:
                    pts = ph_points[-use_last_n:]
                    cur_res = fit_trendline([p[0] for p in pts], [p[1] for p in pts])
            if is_pl_arr[confirm_idx]:
                pl_points.append((confirm_idx, lows[confirm_idx]))
                if len(pl_points) > max_points:
                    pl_points.pop(0)
                if len(pl_points) >= 2:
                    pts = pl_points[-use_last_n:]
                    cur_sup = fit_trendline([p[0] for p in pts], [p[1] for p in pts])
        res_slope[i], res_intercept[i] = cur_res
        sup_slope[i], sup_intercept[i] = cur_sup

    out = pd.DataFrame(index=df.index)
    out["res_slope"] = res_slope
    out["res_intercept"] = res_intercept
    out["res_value"] = res_slope * positions + res_intercept
    out["sup_slope"] = sup_slope
    out["sup_intercept"] = sup_intercept
    out["sup_value"] = sup_slope * positions + sup_intercept
    return out


def trendline_interaction(
    high: float, low: float, close: float, line_value: float, atr: float, tol_mult: float = 0.25
) -> str | None:
    """Classify a bar's interaction with a single trendline value.

    Returns "reject_down" if the bar poked at/above the line but closed
    back below it (resistance rejection -> bearish), "reject_up" if it
    poked at/below the line but closed back above it (support rejection
    -> bullish), or None.
    """
    if any(np.isnan(v) for v in (line_value, atr)) or atr <= 0:
        return None
    tol = tol_mult * atr
    touched_from_below = high >= line_value - tol
    touched_from_above = low <= line_value + tol
    if touched_from_below and close < line_value:
        return "reject_down"
    if touched_from_above and close > line_value:
        return "reject_up"
    return None
