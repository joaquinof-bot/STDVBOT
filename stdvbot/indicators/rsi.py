"""Wilder's RSI."""
from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Classic Wilder-smoothed RSI.

    Uses an exponential (Wilder) moving average of gains/losses via
    `ewm(alpha=1/length)`, matching the standard indicator found on most
    charting platforms.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    # Where avg_loss is 0 and avg_gain > 0, RSI is 100; where both are 0, RSI is 50.
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out.astype(float)
