"""OHLCV data loading and synthetic data generation.

No network calls live here on purpose — this module either reads a
local CSV or generates synthetic candles, so examples and tests run
offline and deterministically.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def load_ohlcv_csv(path: str, date_col: str = "date") -> pd.DataFrame:
    """Load OHLCV data from a CSV with columns
    ``date, open, high, low, close, volume`` (case-insensitive; ``volume``
    optional). Returns a DataFrame indexed by a parsed ``DatetimeIndex``,
    sorted ascending, with lowercase column names.
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if date_col not in df.columns:
        raise ValueError(f"CSV must contain a '{date_col}' column; got {list(df.columns)}")
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required column(s): {sorted(missing)}")

    return df


def generate_synthetic_ohlcv(
    n: int = 500,
    start: str = "2022-01-03",
    freq: str = "B",
    start_price: float = 100.0,
    daily_vol: float = 0.015,
    drift: float = 0.0002,
    seed: int | None = 42,
) -> pd.DataFrame:
    """Generate a synthetic OHLCV series via a geometric random walk for
    closes, with open/high/low derived from an intraday noise model that
    occasionally produces long-wicked, engulfing, and doji-like candles
    so the pattern detectors have something real to find.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n) if freq == "B" else pd.date_range(
        start=start, periods=n, freq=freq
    )

    log_returns = rng.normal(loc=drift, scale=daily_vol, size=n)
    close = start_price * np.exp(np.cumsum(log_returns))

    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]

    # Intraday excursion beyond the open/close body, asymmetric per bar
    # to create varied wick shapes (some candles hammer-like, some doji-like).
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    body_size = np.maximum(body_hi - body_lo, 1e-6)

    upper_extra = np.abs(rng.normal(0.0, 0.6, size=n)) * body_size * rng.uniform(0.2, 2.5, size=n)
    lower_extra = np.abs(rng.normal(0.0, 0.6, size=n)) * body_size * rng.uniform(0.2, 2.5, size=n)

    high = body_hi + upper_extra
    low = body_lo - lower_extra
    low = np.minimum(low, body_lo)  # guard against fp weirdness
    high = np.maximum(high, body_hi)

    volume = rng.integers(1_000_00, 5_000_00, size=n).astype(float)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    df.index.name = "date"
    return df


def generate_synthetic_intraday_ohlcv(
    n_days: int = 10,
    start: str = "2022-01-03",
    bars_per_day: int = 1440,
    start_price: float = 15_000.0,
    minute_vol: float = 0.0006,
    drift_per_day: float = 0.0002,
    seed: int | None = 42,
) -> pd.DataFrame:
    """Generate synthetic 1-minute OHLCV bars spanning ``n_days`` calendar
    days, continuous (no weekend/session gaps -- a simplification, this is
    for exercising intraday-aware code like
    :mod:`stdvbot.manipulation_leg_strategy`, not a realistic market
    simulator). Same random-walk-plus-wick-noise approach as
    :func:`generate_synthetic_ohlcv`, just at minute granularity so every
    calendar day includes both the Asia (20:00) and NY (09:30) killzone
    windows.
    """
    rng = np.random.default_rng(seed)
    n = n_days * bars_per_day
    idx = pd.date_range(start=start, periods=n, freq="1min")

    per_bar_drift = drift_per_day / bars_per_day
    log_returns = rng.normal(loc=per_bar_drift, scale=minute_vol, size=n)
    close = start_price * np.exp(np.cumsum(log_returns))

    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]

    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    body_size = np.maximum(body_hi - body_lo, 1e-6)

    upper_extra = np.abs(rng.normal(0.0, 0.6, size=n)) * body_size * rng.uniform(0.2, 2.5, size=n)
    lower_extra = np.abs(rng.normal(0.0, 0.6, size=n)) * body_size * rng.uniform(0.2, 2.5, size=n)

    high = np.maximum(body_hi + upper_extra, body_hi)
    low = np.minimum(body_lo - lower_extra, body_lo)

    volume = rng.integers(50, 500, size=n).astype(float)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    df.index.name = "date"
    return df
