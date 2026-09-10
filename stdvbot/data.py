"""OHLCV loading and multi-timeframe resampling.

Convention: every bar's DatetimeIndex value is the bar's **close time**
(the moment the bar's data becomes fully known). This makes it safe to
align a higher timeframe onto a lower one with `merge_asof(direction=
"backward")` without introducing lookahead bias -- see `align_to_base`.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]

# Base-timeframe key -> pandas resample rule, ordered low -> high.
TIMEFRAME_RULES: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

DEFAULT_TIMEFRAME_STACK = ["1d", "4h", "1h", "30m", "15m", "5m", "1m"]


def load_ohlcv_csv(path: str, tz: str = "UTC") -> pd.DataFrame:
    """Load a CSV with columns timestamp,open,high,low,close,volume.

    `timestamp` may be an ISO8601 string or a unix epoch (seconds or ms);
    it is treated as the bar's **close time** and localized/converted to
    `tz` (UTC by default).
    """
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "timestamp" not in cols:
        raise ValueError("CSV must have a 'timestamp' column")
    ts_col = cols["timestamp"]
    ts = df[ts_col]
    if pd.api.types.is_numeric_dtype(ts):
        unit = "ms" if ts.max() > 10**12 else "s"
        idx = pd.to_datetime(ts, unit=unit, utc=True)
    else:
        idx = pd.to_datetime(ts, utc=True)
    df = df.set_index(idx).drop(columns=[ts_col])
    df.index.name = "timestamp"
    df.columns = [c.lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")
    df = df[REQUIRED_COLUMNS].sort_index()
    df.index = df.index.tz_convert(tz)
    return df


def fetch_ohlcv_ccxt(
    symbol: str,
    timeframe: str = "1m",
    since: str | None = None,
    limit: int = 1000,
    exchange_id: str = "binance",
) -> pd.DataFrame:
    """Fetch public OHLCV history via ccxt (no API key required).

    Paginates forward from `since` (ISO8601 string, e.g. "2024-01-01T00:00:00Z")
    until fewer than `limit` candles are returned. Only public market-data
    endpoints are used -- no credentials, no order placement.
    """
    import ccxt  # local import: optional dependency

    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    since_ms = exchange.parse8601(since) if since else None
    rows: list[list[float]] = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < limit:
            break

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    # ccxt gives *open* time; shift to the bar's close time per our convention.
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    idx = pd.to_datetime(df["timestamp"] + tf_ms, unit="ms", utc=True)
    df = df.set_index(idx).drop(columns=["timestamp"])
    df.index.name = "timestamp"
    return df.sort_index()


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample close-time-indexed OHLCV to a higher timeframe, close-time-indexed."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule, label="right", closed="right").agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])


def build_timeframe_stack(
    base_df: pd.DataFrame,
    timeframes: list[str] = None,
) -> dict[str, pd.DataFrame]:
    """Resample a base OHLCV DataFrame into every requested timeframe.

    `timeframes` may include the base timeframe itself (assumed "1m"
    unless it matches another key with rule == base cadence); each
    timeframe maps to a resampled DataFrame, close-time-indexed.
    """
    timeframes = timeframes or DEFAULT_TIMEFRAME_STACK
    stack: dict[str, pd.DataFrame] = {}
    for tf in timeframes:
        if tf not in TIMEFRAME_RULES:
            raise ValueError(f"Unknown timeframe '{tf}', expected one of {list(TIMEFRAME_RULES)}")
        stack[tf] = resample_ohlcv(base_df, TIMEFRAME_RULES[tf])
    return stack


def align_to_base(base_index: pd.DatetimeIndex, higher_tf_df: pd.DataFrame) -> pd.DataFrame:
    """Forward-align a higher-timeframe indicator/OHLCV frame onto `base_index`.

    Uses `merge_asof(direction="backward")`: at base timestamp t, the row
    returned is the most recent higher-timeframe bar whose close time is
    <= t -- i.e. only bars that are already fully closed. No lookahead.
    """
    left = pd.DataFrame(index=base_index).reset_index()
    left.columns = ["timestamp"]
    right = higher_tf_df.reset_index()
    right = right.rename(columns={right.columns[0]: "timestamp"})
    merged = pd.merge_asof(
        left.sort_values("timestamp"),
        right.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    return merged.set_index("timestamp")
