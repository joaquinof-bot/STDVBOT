"""Bars, session arithmetic, and resampling.

Futures sessions do not align to calendar days. The CME session opens at
18:00 ET and runs to 17:00 ET the next afternoon, so a bar printed at
20:00 on Monday belongs to Tuesday's trading session. Every date in this
module means *session date*, never calendar date, because getting that
wrong silently shifts every prior-day POI by one day.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

EXCHANGE_TZ = ZoneInfo("America/New_York")

# The hour at which one trading session ends and the next begins (ET).
SESSION_BOUNDARY_HOUR = 18


class Session(Enum):
    """The two windows the leg watcher arms (Procedure step 23)."""

    ASIA = ("asia", time(18, 0), time(19, 0))
    NY = ("ny", time(9, 30), time(10, 30))

    def __init__(self, label: str, start: time, end: time) -> None:
        self.label = label
        self.start = start
        self.end = end

    @property
    def opens_before_midnight(self) -> bool:
        """True when the window sits in the evening half of the session date."""
        return self.start.hour >= SESSION_BOUNDARY_HOUR


@dataclass(frozen=True)
class Bar:
    timestamp: datetime  # timezone-aware, exchange time
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar.timestamp must be timezone-aware")
        if self.high < self.low:
            raise ValueError(f"Bar high {self.high} is below low {self.low}")

    @property
    def session_date(self) -> date:
        return session_date_of(self.timestamp)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def typical_price(self) -> float:
        """(H+L+C)/3 — the price VWAP is weighted against."""
        return (self.high + self.low + self.close) / 3


def session_date_of(moment: datetime) -> date:
    """The trading session a moment belongs to.

    Anything at or after 18:00 ET rolls into the next session date.
    """
    local = moment.astimezone(EXCHANGE_TZ)
    if local.hour >= SESSION_BOUNDARY_HOUR:
        return (local + timedelta(days=1)).date()
    return local.date()


def session_window(session: Session, on: date) -> tuple[datetime, datetime]:
    """Absolute start and end instants of `session` for session date `on`.

    The Asia window opens the evening *before* its session date, which is why
    this cannot be derived from the date alone.
    """
    day = on - timedelta(days=1) if session.opens_before_midnight else on
    start = datetime.combine(day, session.start, tzinfo=EXCHANGE_TZ)
    end = datetime.combine(day, session.end, tzinfo=EXCHANGE_TZ)
    return start, end


def bars_in_window(bars: list[Bar], start: datetime, end: datetime) -> list[Bar]:
    """Bars with timestamp in [start, end). Assumes `bars` is sorted."""
    return [bar for bar in bars if start <= bar.timestamp < end]


def bars_in_session(bars: list[Bar], session: Session, on: date) -> list[Bar]:
    start, end = session_window(session, on)
    return bars_in_window(bars, start, end)


def group_by_session_date(bars: list[Bar]) -> dict[date, list[Bar]]:
    grouped: dict[date, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(bar.session_date, []).append(bar)
    return grouped


def aggregate(bars: list[Bar]) -> Bar | None:
    """Collapse consecutive bars into one. Returns None for an empty list."""
    if not bars:
        return None
    return Bar(
        timestamp=bars[0].timestamp,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        volume=sum(b.volume for b in bars),
    )


def _bucket_start(moment: datetime, hours: int) -> datetime:
    """Floor `moment` to a bucket anchored on the 18:00 ET session boundary.

    Anchoring on the session open rather than midnight keeps 4H buckets at
    18:00, 22:00, 02:00, 06:00, 10:00 and 14:00 — the boundaries a futures
    chart actually draws.
    """
    local = moment.astimezone(EXCHANGE_TZ)
    anchor_day = local.date() if local.hour >= SESSION_BOUNDARY_HOUR else local.date() - timedelta(days=1)
    anchor = datetime.combine(anchor_day, time(SESSION_BOUNDARY_HOUR), tzinfo=EXCHANGE_TZ)
    elapsed = local - anchor
    periods = int(elapsed.total_seconds() // (hours * 3600))
    return anchor + timedelta(hours=hours * periods)


def resample(bars: list[Bar], hours: int) -> list[Bar]:
    """Aggregate 1-minute bars into `hours`-hour bars (Procedure step 16)."""
    if hours <= 0:
        raise ValueError("hours must be positive")
    buckets: dict[datetime, list[Bar]] = {}
    for bar in bars:
        buckets.setdefault(_bucket_start(bar.timestamp, hours), []).append(bar)
    resampled = []
    for start in sorted(buckets):
        merged = aggregate(buckets[start])
        assert merged is not None  # buckets are never created empty
        resampled.append(
            Bar(start, merged.open, merged.high, merged.low, merged.close, merged.volume)
        )
    return resampled


def resample_daily(bars: list[Bar]) -> list[Bar]:
    """One bar per trading session, stamped at the session's first bar."""
    daily = []
    for session_day in sorted(group_by_session_date(bars)):
        merged = aggregate(group_by_session_date(bars)[session_day])
        assert merged is not None
        daily.append(merged)
    return daily


def load_csv(path: str | Path, tz: ZoneInfo = EXCHANGE_TZ) -> list[Bar]:
    """Read 1-minute bars from a FirstRate-style CSV.

    Expected columns: timestamp, open, high, low, close, volume. A header row
    is detected and skipped. Timestamps are assumed to be in `tz` unless they
    carry an explicit offset. Rows are returned sorted by timestamp.
    """
    bars: list[Bar] = []
    with open(path, newline="") as handle:
        for line_number, row in enumerate(csv.reader(handle), start=1):
            if not row or len(row) < 5:
                continue
            if line_number == 1 and not row[1].replace(".", "", 1).isdigit():
                continue  # header
            try:
                stamp = datetime.fromisoformat(row[0].strip())
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=tz)
                bars.append(
                    Bar(
                        timestamp=stamp,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(float(row[5])) if len(row) > 5 and row[5] else 0,
                    )
                )
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    bars.sort(key=lambda b: b.timestamp)
    return bars
