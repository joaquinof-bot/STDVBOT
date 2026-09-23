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


def load_databento_parent_ohlcv_csv(
    path: str,
    utc_offset_hours: float = -4.0,
) -> pd.DataFrame:
    """Load a Databento ``ohlcv-*`` CSV requested with ``stype_in="parent"``
    (e.g. symbol ``"MNQ.FUT"`` or ``"NQ.FUT"``) and collapse it into a single
    continuous front-month OHLCV series.

    A parent-symbology pull returns every related instrument at once: each
    individual expiry (``MNQU6``, ``MNQZ6``, ...) *and* calendar spread
    contracts (``MNQU6-MNQZ6``, ...), all interleaved by timestamp with a
    ``symbol`` column identifying which is which. This is not directly
    usable as a price series -- spread rows have a completely different
    price scale (a price difference, not a price level), and the outright
    contracts need to be stitched into one continuous series as the front
    month rolls. This function does both:

    1. Drops every spread contract (``symbol`` containing ``"-"``).
    2. For each UTC calendar day, picks whichever remaining single-expiry
       contract traded the most volume that day, and keeps only that
       contract's bars for the day (a volume-based roll, the same idea as
       Databento's own ``.v.0`` continuous symbology, computed locally so
       this works on data already pulled with ``stype_in="parent"``
       instead of requiring a fresh ``stype_in="continuous"`` pull).
    3. **Back-adjusts for the roll.** Two quarterly contracts trade a real,
       persistent price difference against each other (carry/basis) --
       around 290-300 points was observed between NQU6/NQZ6 in testing,
       not noise. Switching feeds day-to-day at step 2 alone would stitch
       in a fake cliff of that size exactly on the roll day, which the leg
       detector (which reacts to raw point moves over 3-5 candles) would
       likely misread as a manipulation leg. To prevent that, at each roll
       this measures the two contracts' actual concurrent price gap
       (median close-price difference over overlapping minutes on the
       roll day) and shifts every earlier bar by that amount, cumulatively
       across multiple rolls -- the standard "back-adjusted continuous
       contract" (Panama) method. The most recent contract's prices are
       left untouched; history behind each roll is what moves. This means
       older absolute price levels in the output won't match what actually
       printed on that historical date -- only the *shape*/point-deltas
       are preserved, which is what the strategy actually consumes.

    Requesting with ``stype_in="continuous"`` and a symbol like
    ``"MNQ.c.0"`` directly from Databento avoids needing this function at
    all -- prefer that when practical. This exists for parent-symbology
    pulls already on hand.

    ``utc_offset_hours``: Databento's ``ts_event`` is UTC; the killzone
    times in :data:`stdvbot.legs.DEFAULT_KILLZONES` (09:30 / 20:00) are a
    naive, non-timezone-aware ``ASSUMED DEFAULT`` of UTC-4 (not DST-aware
    US/Eastern) -- see ``docs/manipulation_leg_strategy.md``. This shifts
    timestamps by that fixed offset so the resulting index's wall-clock
    time lines up with what the killzone detection expects. Pass 0 to keep
    raw UTC.

    Note: this loads **full-size NQ** price levels as-is if that's what was
    requested (NQ and MNQ quote the identical index price, just at 10x
    different dollar-per-point -- CME designed MNQ specifically to track
    NQ 1:1 in price). The strategy's dollar risk/PnL math should still use
    MNQ's own contract specs (``MNQ_TICK_SIZE``/``MNQ_TICK_VALUE`` in
    ``stdvbot/legs.py``), not NQ's -- this function only fixes up the price
    *series*, it doesn't rescale anything.
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"ts_event", "open", "high", "low", "close", "volume", "symbol"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Databento CSV is missing required column(s): {sorted(missing)}")

    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df[~df["symbol"].str.contains("-", regex=False)].copy()
    if df.empty:
        raise ValueError("No outright (non-spread) contracts found in this file")

    df["_day"] = df["ts_event"].dt.date
    daily_volume = df.groupby(["_day", "symbol"])["volume"].sum()
    front_month_by_day = daily_volume.groupby("_day").idxmax().apply(lambda t: t[1])

    days_sorted = sorted(front_month_by_day.index)
    rolls = []  # (roll_day, old_symbol, new_symbol)
    prev_symbol = front_month_by_day[days_sorted[0]]
    for d in days_sorted[1:]:
        sym = front_month_by_day[d]
        if sym != prev_symbol:
            rolls.append((d, prev_symbol, sym))
        prev_symbol = sym

    keep_symbol = df["_day"].map(front_month_by_day)
    kept = df[df["symbol"] == keep_symbol].copy()

    adjustment = pd.Series(0.0, index=kept.index)
    for roll_day, old_symbol, new_symbol in rolls:
        overlap = df[(df["_day"] == roll_day) & (df["symbol"].isin([old_symbol, new_symbol]))]
        pivot = overlap.pivot_table(index="ts_event", columns="symbol", values="close")
        pivot = pivot.dropna(subset=[old_symbol, new_symbol]) if set([old_symbol, new_symbol]).issubset(pivot.columns) else pivot.iloc[0:0]
        if pivot.empty:
            continue  # no concurrent quotes to measure the basis from -- leave unadjusted
        basis = (pivot[new_symbol] - pivot[old_symbol]).median()
        roll_time = pivot.index.min()
        adjustment.loc[kept["ts_event"] < roll_time] += basis

    kept[["open", "high", "low", "close"]] = kept[["open", "high", "low", "close"]].add(adjustment, axis=0)

    kept["ts_event"] = kept["ts_event"] + pd.Timedelta(hours=utc_offset_hours)
    kept["ts_event"] = kept["ts_event"].dt.tz_localize(None)

    kept = kept.set_index("ts_event").sort_index()
    kept = kept[["open", "high", "low", "close", "volume"]]
    kept.index.name = "date"
    return kept


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
