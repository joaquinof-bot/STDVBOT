from datetime import time

import pandas as pd
import pytest

from stdvbot.poi import daily_high_low, detect_sweep, session_high_low


def test_daily_high_low_shifts_previous_day_forward():
    idx = pd.to_datetime(
        [
            "2024-01-01 10:00", "2024-01-01 14:00",
            "2024-01-02 10:00", "2024-01-02 14:00",
            "2024-01-03 10:00", "2024-01-03 14:00",
        ]
    )
    df = pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105],
            "high": [105, 108, 110, 112, 90, 92],
            "low": [95, 100, 101, 104, 85, 87],
            "close": [102, 106, 103, 111, 88, 90],
        },
        index=idx,
    )
    result = daily_high_low(df)

    day1 = pd.Timestamp("2024-01-01")
    day2 = pd.Timestamp("2024-01-02")
    day3 = pd.Timestamp("2024-01-03")

    assert pd.isna(result.loc[day1, "prev_high"])
    assert pd.isna(result.loc[day1, "prev_low"])
    assert result.loc[day2, "prev_high"] == pytest.approx(108.0)
    assert result.loc[day2, "prev_low"] == pytest.approx(95.0)
    assert result.loc[day3, "prev_high"] == pytest.approx(112.0)
    assert result.loc[day3, "prev_low"] == pytest.approx(101.0)


def test_session_high_low_handles_midnight_crossing_window():
    idx = pd.to_datetime(
        [
            "2024-01-01 19:30",  # before window, excluded
            "2024-01-01 20:30",  # inside window, start side
            "2024-01-02 00:30",  # inside window, post-midnight side
            "2024-01-02 10:00",  # after window, excluded
        ]
    )
    df = pd.DataFrame(
        {
            "open": [10, 20, 30, 40],
            "high": [15, 50, 55, 45],
            "low": [5, 40, 42, 38],
            "close": [12, 48, 50, 41],
        },
        index=idx,
    )
    result = session_high_low(df, start=time(20, 0), end=time(2, 0), label="asia")

    assert len(result) == 1
    row = result.loc[pd.Timestamp("2024-01-01")]
    assert row["asia_high"] == pytest.approx(55.0)
    assert row["asia_low"] == pytest.approx(40.0)


def test_session_high_low_same_day_window():
    idx = pd.to_datetime(["2024-01-01 09:00", "2024-01-01 09:30", "2024-01-01 12:00"])
    df = pd.DataFrame(
        {
            "open": [10, 11, 12],
            "high": [12, 14, 20],
            "low": [9, 10, 11],
            "close": [11, 13, 19],
        },
        index=idx,
    )
    result = session_high_low(df, start=time(9, 0), end=time(10, 0), label="ny")

    assert len(result) == 1
    row = result.loc[pd.Timestamp("2024-01-01")]
    assert row["ny_high"] == pytest.approx(14.0)
    assert row["ny_low"] == pytest.approx(9.0)


def test_detect_sweep_above():
    idx = pd.date_range("2024-01-01 10:00", periods=3, freq="1min")
    df = pd.DataFrame(
        {
            "open": [99, 100.5, 97],
            "high": [99.5, 101.0, 98],
            "low": [98.5, 99.5, 96],
            "close": [99.0, 99.5, 97.5],
        },
        index=idx,
    )
    result = detect_sweep(df, level=100.0, direction="above")
    assert result.tolist() == [False, True, False]


def test_detect_sweep_below():
    idx = pd.date_range("2024-01-01 10:00", periods=3, freq="1min")
    df = pd.DataFrame(
        {
            "open": [52, 51, 53],
            "high": [53, 51.5, 54],
            "low": [51, 49.0, 52],
            "close": [52.5, 50.5, 53.5],
        },
        index=idx,
    )
    result = detect_sweep(df, level=50.0, direction="below")
    assert result.tolist() == [False, True, False]


def test_detect_sweep_invalid_direction_raises():
    idx = pd.date_range("2024-01-01 10:00", periods=1, freq="1min")
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]}, index=idx)
    with pytest.raises(ValueError):
        detect_sweep(df, level=1.0, direction="sideways")
