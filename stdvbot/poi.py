"""Points-of-interest (POI) tracking and liquidity-sweep detection.

POIs are prior session or prior day highs/lows — levels price tends to
run (sweep) before reversing. See ``docs/manipulation_leg_strategy.md``
§4. Sweep detection here is timeframe- and level-source-agnostic: the same
logic applies whether the level came from a prior day's high/low, a prior
session's, or anywhere else.
"""
from __future__ import annotations

from datetime import time

import pandas as pd


def daily_high_low(df: pd.DataFrame) -> pd.DataFrame:
    """Previous calendar day's high and low, available as a POI for the
    *current* day. Returns a DataFrame indexed by date with ``prev_high``
    and ``prev_low`` columns (NaN on the first day, with no prior data).
    """
    daily = df.resample("D").agg(high=("high", "max"), low=("low", "min"))
    daily = daily.dropna(how="all")
    daily["prev_high"] = daily["high"].shift(1)
    daily["prev_low"] = daily["low"].shift(1)
    return daily[["prev_high", "prev_low"]]


def session_high_low(
    df: pd.DataFrame, start: time, end: time, label: str = "session"
) -> pd.DataFrame:
    """High/low reached during a named intraday session window (e.g. Asia,
    London, NY), one row per calendar date the window *starts* on. Windows
    crossing midnight (start > end, e.g. 20:00-02:00) are handled by
    anchoring the post-midnight bars back to the window's start date.
    """
    idx_time = df.index.time
    dates = df.index.normalize()

    if end > start:
        mask = (idx_time >= start) & (idx_time < end)
    else:
        mask = (idx_time >= start) | (idx_time < end)
        dates = dates.where(idx_time >= start, dates - pd.Timedelta(days=1))

    windowed = df.loc[mask].copy()
    windowed["session_date"] = dates[mask]

    grouped = windowed.groupby("session_date").agg(high=("high", "max"), low=("low", "min"))
    grouped.index.name = "date"
    grouped.columns = [f"{label}_high", f"{label}_low"]
    return grouped


def detect_sweep(
    df: pd.DataFrame, level: float, direction: str, confirm_bars: int = 1
) -> pd.Series:
    """Detect bars where price wicks through ``level`` and then closes
    back on the other side within ``confirm_bars`` bars — a liquidity
    sweep.

    ``direction="above"``: price wicks *above* level (high > level) then
        closes back *below* it (a swept high — bearish implication).
    ``direction="below"``: price wicks *below* level (low < level) then
        closes back *above* it (a swept low — bullish implication).

    Returns a boolean Series aligned to ``df.index``. Note: if the reject
    condition holds for several consecutive bars after the wick, this may
    flag more than one bar per sweep event — take the first True per
    event (e.g. via cumulative logic) if only the initial confirmation is
    wanted.
    """
    if direction not in ("above", "below"):
        raise ValueError("direction must be 'above' or 'below'")

    if direction == "above":
        wicked = df["high"] > level
        reject = df["close"] < level
    else:
        wicked = df["low"] < level
        reject = df["close"] > level

    wicked_recently = wicked.rolling(confirm_bars, min_periods=1).max().astype(bool)
    return (wicked_recently & reject).fillna(False)
