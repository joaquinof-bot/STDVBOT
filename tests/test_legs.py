from datetime import time

import pandas as pd
import pytest

from stdvbot.legs import (
    Leg,
    DEFAULT_LEVEL_MULTIPLES,
    detect_leg,
    inverse_fib_levels,
    session_window,
    zone_grade,
)


def _df(rows, start="2024-01-01 20:00", freq="1min"):
    idx = pd.date_range(start=start, periods=len(rows), freq=freq)
    return pd.DataFrame(rows, index=idx)


def test_detect_leg_single_candle_is_false_leg():
    # The whole excursion happens within the first (origin) candle --
    # later candles barely move. num_candles should be 1 -> invalid.
    rows = [
        {"open": 100.0, "high": 103.0, "low": 99.8, "close": 102.8},
        {"open": 102.8, "high": 102.9, "low": 102.5, "close": 102.6},
        {"open": 102.6, "high": 102.7, "low": 102.4, "close": 102.5},
    ]
    df = _df(rows)
    leg = detect_leg(df, df.index[0], df.index[-1] + pd.Timedelta(minutes=1))

    assert leg is not None
    assert leg.num_candles == 1
    assert leg.is_valid is False
    assert leg.direction == "up"
    assert leg.extreme_price == pytest.approx(103.0)


def test_detect_leg_multi_candle_is_valid():
    # Extreme is reached on the 3rd candle -> num_candles == 3 -> valid.
    rows = [
        {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.3},
        {"open": 100.3, "high": 101.2, "low": 100.1, "close": 101.0},
        {"open": 101.0, "high": 102.0, "low": 100.9, "close": 101.8},
    ]
    df = _df(rows)
    leg = detect_leg(df, df.index[0], df.index[-1] + pd.Timedelta(minutes=1))

    assert leg is not None
    assert leg.num_candles == 3
    assert leg.is_valid is True
    assert leg.direction == "up"
    assert leg.origin_price == pytest.approx(100.0)
    assert leg.extreme_price == pytest.approx(102.0)
    assert leg.range_ == pytest.approx(2.0)


def test_detect_leg_downward():
    rows = [
        {"open": 100.0, "high": 100.2, "low": 99.0, "close": 99.2},
        {"open": 99.2, "high": 99.3, "low": 97.5, "close": 97.8},
    ]
    df = _df(rows)
    leg = detect_leg(df, df.index[0], df.index[-1] + pd.Timedelta(minutes=1))

    assert leg is not None
    assert leg.direction == "down"
    assert leg.extreme_price == pytest.approx(97.5)
    assert leg.num_candles == 2


def test_detect_leg_empty_window_returns_none():
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}]
    df = _df(rows)
    late_start = df.index[-1] + pd.Timedelta(hours=5)
    late_end = late_start + pd.Timedelta(minutes=1)
    assert detect_leg(df, late_start, late_end) is None


def test_session_window_same_day():
    date = pd.Timestamp("2024-01-01")
    start, end = session_window(date, time(20, 0), time(20, 3))
    assert start == pd.Timestamp("2024-01-01 20:00")
    assert end == pd.Timestamp("2024-01-01 20:03")


def test_session_window_crosses_midnight():
    date = pd.Timestamp("2024-01-01")
    start, end = session_window(date, time(23, 0), time(1, 0))
    assert start == pd.Timestamp("2024-01-01 23:00")
    assert end == pd.Timestamp("2024-01-02 01:00")


def test_inverse_fib_levels_upward_leg_projects_below_origin():
    leg = Leg(
        origin_time=pd.Timestamp("2024-01-01 20:00"),
        origin_price=100.0,
        extreme_time=pd.Timestamp("2024-01-01 20:02"),
        extreme_price=102.0,
        num_candles=3,
        direction="up",
    )
    levels = inverse_fib_levels(leg)
    assert levels[1.0] == pytest.approx(98.0)
    assert levels[2.0] == pytest.approx(96.0)
    assert levels[2.25] == pytest.approx(95.5)
    assert levels[2.5] == pytest.approx(95.0)
    assert levels[4.0] == pytest.approx(92.0)
    assert levels[4.5] == pytest.approx(91.0)


def test_inverse_fib_levels_downward_leg_projects_above_origin():
    leg = Leg(
        origin_time=pd.Timestamp("2024-01-01 20:00"),
        origin_price=100.0,
        extreme_time=pd.Timestamp("2024-01-01 20:01"),
        extreme_price=97.0,
        num_candles=2,
        direction="down",
    )
    levels = inverse_fib_levels(leg, multiples=(1.0, 2.5, 4.5))
    assert levels[1.0] == pytest.approx(103.0)
    assert levels[2.5] == pytest.approx(107.5)
    assert levels[4.5] == pytest.approx(113.5)


def test_zone_grade_boundaries_and_interpolation():
    assert zone_grade(2.0) == pytest.approx(0.0)
    assert zone_grade(1.0) == pytest.approx(0.0)  # below low, clipped
    assert zone_grade(4.5) == pytest.approx(1.0)
    assert zone_grade(10.0) == pytest.approx(1.0)  # above high, clipped
    assert zone_grade(3.25) == pytest.approx(0.5)  # halfway between 2.0 and 4.5


def test_default_level_multiples_include_observed_grid():
    assert DEFAULT_LEVEL_MULTIPLES == (1.0, 2.0, 2.25, 2.5, 4.0, 4.5)
