import pandas as pd
import pytest

from stdvbot import candles


def _df(rows):
    """rows: list of dicts with open/high/low/close."""
    return pd.DataFrame(rows)


def test_add_candle_features_basic_geometry():
    df = _df(
        [
            {"open": 10.0, "close": 12.0, "high": 12.5, "low": 9.5},
        ]
    )
    f = candles.add_candle_features(df)
    assert f["body"].iloc[0] == pytest.approx(2.0)
    assert f["body_abs"].iloc[0] == pytest.approx(2.0)
    assert f["range_"].iloc[0] == pytest.approx(3.0)
    assert f["upper_wick"].iloc[0] == pytest.approx(0.5)
    assert f["lower_wick"].iloc[0] == pytest.approx(0.5)
    assert bool(f["is_bullish"].iloc[0]) is True
    assert bool(f["is_bearish"].iloc[0]) is False


def test_doji_detects_tiny_body():
    df = _df([{"open": 10.0, "close": 10.05, "high": 10.6, "low": 9.4}])
    result = candles.doji(df)
    assert bool(result.iloc[0])


def test_doji_rejects_large_body():
    df = _df([{"open": 10.0, "close": 12.0, "high": 12.1, "low": 9.9}])
    result = candles.doji(df)
    assert not bool(result.iloc[0])


def test_hammer_shape():
    df = _df([{"open": 10.0, "close": 10.5, "high": 10.6, "low": 8.5}])
    result = candles.hammer(df, require_downtrend=False)
    assert bool(result.iloc[0])


def test_shooting_star_shape():
    df = _df([{"open": 10.0, "close": 10.5, "high": 12.0, "low": 9.9}])
    result = candles.shooting_star(df, require_uptrend=False)
    assert bool(result.iloc[0])


def test_bullish_engulfing():
    df = _df(
        [
            {"open": 10.0, "close": 8.0, "high": 10.2, "low": 7.8},   # bearish
            {"open": 7.0, "close": 11.0, "high": 11.2, "low": 6.8},   # engulfs it
        ]
    )
    result = candles.bullish_engulfing(df)
    assert not bool(result.iloc[0])
    assert bool(result.iloc[1])


def test_bearish_engulfing():
    df = _df(
        [
            {"open": 8.0, "close": 10.0, "high": 10.2, "low": 7.8},   # bullish
            {"open": 11.0, "close": 7.0, "high": 11.2, "low": 6.8},   # engulfs it
        ]
    )
    result = candles.bearish_engulfing(df)
    assert bool(result.iloc[1])


def test_bullish_harami():
    df = _df(
        [
            {"open": 10.0, "close": 7.0, "high": 10.2, "low": 6.8},   # big bearish
            {"open": 8.0, "close": 9.0, "high": 9.2, "low": 7.8},     # small bullish inside
        ]
    )
    result = candles.bullish_harami(df)
    assert bool(result.iloc[1])


def test_piercing_line():
    df = _df(
        [
            {"open": 10.0, "close": 7.0, "high": 10.2, "low": 6.8},   # bearish, mid=8.5
            {"open": 6.5, "close": 9.0, "high": 9.1, "low": 6.4},     # gaps below low, closes above mid
        ]
    )
    result = candles.piercing_line(df)
    assert bool(result.iloc[1])


def test_dark_cloud_cover():
    df = _df(
        [
            {"open": 7.0, "close": 10.0, "high": 10.2, "low": 6.8},   # bullish, mid=8.5
            {"open": 10.5, "close": 8.0, "high": 10.6, "low": 7.9},   # gaps above high, closes below mid
        ]
    )
    result = candles.dark_cloud_cover(df)
    assert bool(result.iloc[1])


def test_morning_star():
    df = _df(
        [
            {"open": 10.0, "close": 7.0, "high": 10.2, "low": 6.8},     # big bearish, mid=8.5
            {"open": 6.85, "close": 6.9, "high": 7.0, "low": 6.7},      # small star gapping down
            {"open": 6.95, "close": 9.2, "high": 9.3, "low": 6.9},      # bullish closing into c1 body
        ]
    )
    result = candles.morning_star(df)
    assert bool(result.iloc[2])
    assert not bool(result.iloc[0])
    assert not bool(result.iloc[1])


def test_evening_star():
    df = _df(
        [
            {"open": 7.0, "close": 10.0, "high": 10.2, "low": 6.8},     # big bullish, mid=8.5
            {"open": 10.15, "close": 10.2, "high": 10.3, "low": 10.1},  # small star gapping up
            {"open": 10.25, "close": 7.8, "high": 10.3, "low": 7.7},    # bearish closing into c1 body
        ]
    )
    result = candles.evening_star(df)
    assert bool(result.iloc[2])


def test_three_white_soldiers():
    df = _df(
        [
            {"open": 10.0, "close": 11.0, "high": 11.2, "low": 9.8},
            {"open": 10.5, "close": 12.0, "high": 12.3, "low": 10.3},
            {"open": 11.2, "close": 13.0, "high": 13.2, "low": 11.0},
        ]
    )
    result = candles.three_white_soldiers(df)
    assert bool(result.iloc[2])


def test_three_black_crows():
    df = _df(
        [
            {"open": 13.0, "close": 12.0, "high": 13.2, "low": 11.8},
            {"open": 12.5, "close": 11.0, "high": 12.7, "low": 10.7},
            {"open": 11.2, "close": 9.5, "high": 11.4, "low": 9.3},
        ]
    )
    result = candles.three_black_crows(df)
    assert bool(result.iloc[2])


def test_detect_patterns_returns_score_and_columns():
    df = _df(
        [
            {"open": 10.0, "close": 8.0, "high": 10.2, "low": 7.8},
            {"open": 7.0, "close": 11.0, "high": 11.2, "low": 6.8},
        ]
    )
    f = candles.detect_patterns(df, patterns=["bullish_engulfing"])
    assert "bullish_engulfing" in f.columns
    assert "pattern_score" in f.columns
    assert f["pattern_score"].iloc[1] == 1


def test_detect_patterns_rejects_unknown_pattern():
    df = _df([{"open": 1, "close": 2, "high": 2, "low": 1}])
    with pytest.raises(ValueError):
        candles.detect_patterns(df, patterns=["not_a_real_pattern"])


def test_missing_columns_raise():
    with pytest.raises(ValueError):
        candles.add_candle_features(pd.DataFrame({"open": [1], "close": [2]}))
