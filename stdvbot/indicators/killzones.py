"""Session killzone windows (UTC).

Killzones are the recurring intraday windows where institutional session
opens tend to produce the highest-volume swings (and therefore the most
reliable VWAP reversion setups). Times are UTC and naive of DST in the
underlying exchange's local time -- adjust the config if a session you
care about observes DST differently than UTC does year-round.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

# (start_hour, start_minute, end_hour, end_minute), all UTC, end exclusive.
DEFAULT_KILLZONES: dict[str, tuple[int, int, int, int]] = {
    "asian": (0, 0, 3, 0),
    "london_open": (7, 0, 10, 0),
    "ny_am": (12, 0, 15, 0),
    "ny_pm_london_close": (15, 0, 17, 0),
}


def in_killzone(
    timestamp: pd.Timestamp,
    killzones: dict[str, tuple[int, int, int, int]] | None = None,
) -> str | None:
    """Return the name of the killzone `timestamp` (UTC) falls in, else None."""
    killzones = killzones or DEFAULT_KILLZONES
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be tz-aware (UTC)")
    ts_utc = timestamp.tz_convert("UTC")
    t = ts_utc.time()
    for name, (sh, sm, eh, em) in killzones.items():
        start = dt.time(sh, sm)
        end = dt.time(eh, em)
        if start <= t < end:
            return name
    return None


def killzone_mask(index: pd.DatetimeIndex, killzones: dict | None = None) -> pd.Series:
    """Vectorized version of `in_killzone` over a DatetimeIndex."""
    killzones = killzones or DEFAULT_KILLZONES
    idx_utc = index.tz_convert("UTC")
    minutes = pd.Series(idx_utc.hour * 60 + idx_utc.minute, index=index)
    names = pd.Series([None] * len(index), index=index, dtype=object)
    for name, (sh, sm, eh, em) in killzones.items():
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        in_zone = (minutes >= start_m) & (minutes < end_m)
        names[in_zone & names.isna()] = name
    return names
