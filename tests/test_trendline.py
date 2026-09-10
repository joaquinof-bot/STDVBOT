import numpy as np
import pandas as pd

from stdvbot.indicators.trendline import (
    fit_trendline,
    find_pivots,
    rolling_trendlines,
    trendline_interaction,
    trendline_value,
)


def test_fit_trendline_exact_line():
    xs = [0, 10, 20]
    ys = [100, 105, 110]  # slope 0.5, intercept 100
    slope, intercept = fit_trendline(xs, ys)
    assert np.isclose(slope, 0.5)
    assert np.isclose(intercept, 100)
    assert np.isclose(trendline_value(slope, intercept, 30), 115)


def test_fit_trendline_needs_two_distinct_points():
    slope, intercept = fit_trendline([5], [100])
    assert np.isnan(slope) and np.isnan(intercept)
    slope, intercept = fit_trendline([5, 5], [100, 200])
    assert np.isnan(slope) and np.isnan(intercept)


def test_find_pivots_detects_obvious_high_and_low():
    # window=3 needs 3 valid bars on each side, so with n=9 only indices
    # 3..5 have a fully-populated centered window; put the spikes there.
    high = [10, 10, 10, 20, 10, 10, 10, 10, 10]
    low = [5, 5, 5, 5, 5, 1, 5, 5, 5]
    idx = pd.date_range("2024-01-01", periods=9, freq="1h", tz="UTC")
    df = pd.DataFrame({"high": high, "low": low}, index=idx)
    is_ph, is_pl = find_pivots(df, window=3)
    assert is_ph.iloc[3]
    assert is_pl.iloc[5]
    assert not is_ph.iloc[0]


def test_rolling_trendlines_no_lookahead_before_confirmation():
    # A resistance trendline should not exist until 2 pivots are CONFIRMED,
    # which requires `window` bars after the second pivot high.
    #
    # The baseline must be strictly monotonic (not flat) -- on a flat
    # series every bar ties the rolling max/min and is spuriously flagged
    # as a pivot.
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    high = 100.0 - 0.01 * np.arange(n)
    low = 90.0 - 0.01 * np.arange(n)
    high[5] = 110.0  # pivot high #1 (confirmed at bar 5+window)
    high[15] = 108.0  # pivot high #2 (confirmed at bar 15+window)
    df = pd.DataFrame(
        {"open": high, "high": high, "low": low, "close": high}, index=idx
    )
    window = 3
    tl = rolling_trendlines(df, window=window, use_last_n=2)
    confirm_bar = 15 + window
    assert tl["res_value"].iloc[: confirm_bar].isna().all()
    assert tl["res_value"].iloc[confirm_bar:].notna().all()


def test_trendline_interaction_rejection():
    # Resistance at 100, bar pokes above then closes back under -> reject_down
    result = trendline_interaction(high=101, low=98, close=99, line_value=100, atr=2, tol_mult=0.25)
    assert result == "reject_down"

    # Support at 100, bar pokes below then closes back above -> reject_up
    result = trendline_interaction(high=102, low=99, close=101, line_value=100, atr=2, tol_mult=0.25)
    assert result == "reject_up"

    # No interaction
    result = trendline_interaction(high=90, low=85, close=88, line_value=100, atr=2, tol_mult=0.25)
    assert result is None
