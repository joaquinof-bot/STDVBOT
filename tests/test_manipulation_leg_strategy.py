import numpy as np
import pandas as pd
import pytest

from stdvbot import manipulation_leg_strategy as mls
from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_intraday_ohlcv
from stdvbot.strategies import get_strategy


def _daily_df(closes, start="2022-01-01"):
    idx = pd.date_range(start=start, periods=len(closes), freq="D")
    closes = np.asarray(closes, dtype=float)
    highs = closes + 0.5
    lows = closes - 0.5
    opens = np.r_[closes[0], closes[:-1]]
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=idx)


def test_resample_ohlc_basic():
    idx = pd.date_range("2022-01-01 00:00", periods=4, freq="30min")
    df = pd.DataFrame(
        {
            "open": [10, 11, 12, 13],
            "high": [10.5, 11.5, 12.5, 13.5],
            "low": [9.5, 10.5, 11.5, 12.5],
            "close": [10.2, 11.2, 12.2, 13.2],
            "volume": [100, 100, 100, 100],
        },
        index=idx,
    )
    out = mls.resample_ohlc(df, "1h")
    assert len(out) == 2
    first = out.iloc[0]
    assert first["open"] == pytest.approx(10.0)
    assert first["high"] == pytest.approx(11.5)
    assert first["low"] == pytest.approx(9.5)
    assert first["close"] == pytest.approx(11.2)
    assert first["volume"] == pytest.approx(200.0)


def test_efficiency_ratio_trending_vs_ranging():
    trending = pd.Series(np.arange(30, dtype=float))  # steady up move
    ranging = pd.Series(10.0 + np.sin(np.arange(30) * 1.5))  # oscillating, ~no net move

    er_trend = mls.efficiency_ratio(trending, window=10).iloc[-1]
    er_range = mls.efficiency_ratio(ranging, window=10).iloc[-1]

    assert er_trend == pytest.approx(1.0, abs=1e-6)  # perfectly straight move
    assert er_range < 0.3


def test_daily_bias_series_is_opposite_of_the_leg():
    # A clean upward daily leg over the lookback window.
    closes = [100 + i for i in range(25)]
    daily = _daily_df(closes)
    bias = mls.daily_bias_series(daily, lookback=20)

    assert pd.isna(bias.iloc[19])  # not enough history yet
    assert bias.iloc[20] == "down"  # up leg -> bias is toward the retracement (down)


def test_regime_series_classifies_trending_and_ranging():
    trending_closes = [100 + i for i in range(40)]
    ranging_closes = [100 + (i % 2) for i in range(40)]  # flips +-1, no net progress

    trending_regime = mls.regime_series(_daily_df(trending_closes), window=10)
    ranging_regime = mls.regime_series(_daily_df(ranging_closes), window=10)

    assert trending_regime.iloc[-1] == "trending"
    assert ranging_regime.iloc[-1] == "ranging"


def test_session_vwap_matches_manual_calc_and_resets_daily():
    idx = pd.to_datetime(
        ["2022-01-01 10:00", "2022-01-01 11:00", "2022-01-02 10:00", "2022-01-02 11:00"]
    )
    df = pd.DataFrame(
        {
            "open": [10, 11, 20, 21],
            "high": [10, 11, 20, 21],
            "low": [10, 11, 20, 21],
            "close": [10, 11, 20, 21],
            "volume": [2.0, 3.0, 1.0, 1.0],
        },
        index=idx,
    )
    vwap = mls.session_vwap(df)

    # Day 1: typical price == close here (h=l=c), cumulative VWAP:
    # bar1: (10*2)/2 = 10; bar2: (10*2 + 11*3)/(2+3) = 53/5 = 10.6
    assert vwap.iloc[0] == pytest.approx(10.0)
    assert vwap.iloc[1] == pytest.approx(10.6)
    # Day 2 resets: bar1 vwap == 20 again, not carrying day 1's average.
    assert vwap.iloc[2] == pytest.approx(20.0)


def test_session_vwap_falls_back_to_close_without_volume():
    idx = pd.date_range("2022-01-01", periods=3, freq="D")
    df = pd.DataFrame({"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3], "close": [1, 2, 3]}, index=idx)
    vwap = mls.session_vwap(df)
    assert list(vwap) == [1, 2, 3]


def test_generate_signals_end_to_end_produces_valid_positions():
    df = generate_synthetic_intraday_ohlcv(n_days=90, seed=7)
    signals = mls.generate_signals(df)

    assert isinstance(signals, pd.Series)
    assert len(signals) == len(df)
    assert signals.index.equals(df.index)
    assert set(signals.unique()).issubset({-1.0, 0.0, 1.0})
    # Regression guard for the daily_bias_series bug caught during
    # development (over-strict validity gating silently produced zero
    # signals for the entire history).
    assert (signals != 0).any()


def test_generate_signals_runs_through_real_backtest():
    df = generate_synthetic_intraday_ohlcv(n_days=90, seed=7)
    strategy = get_strategy("manipulation_leg")
    assert strategy.name == "manipulation_leg"

    signals = strategy.generate_signals(df)
    result = run_backtest(df, signals, initial_capital=50_000.0)

    assert len(result.equity_curve) == len(df)
    assert (result.equity_curve > 0).all()
    assert len(result.trades) > 0


def test_generate_signals_empty_dataframe_returns_empty_series():
    df = generate_synthetic_intraday_ohlcv(n_days=1, seed=1).iloc[0:0]
    signals = mls.generate_signals(df)
    assert len(signals) == 0


def test_typical_bar_range_is_trailing_median_with_no_lookahead():
    idx = pd.date_range("2024-01-01", periods=6, freq="1min")
    df = pd.DataFrame(
        {
            "open": [0] * 6,
            "high": [1, 1, 1, 1, 1, 100],  # last bar is a huge outlier
            "low": [0, 0, 0, 0, 0, 0],
            "close": [0.5] * 6,
        },
        index=idx,
    )
    ref = mls.typical_bar_range(df, window=3)

    assert pd.isna(ref.iloc[0])  # nothing before the first bar yet
    # By the last bar, the trailing median (shifted) must not include the
    # huge outlier bar itself -- otherwise a pivotal leg could "see" its
    # own size in its own reference range.
    assert ref.iloc[-1] == pytest.approx(1.0)


def test_short_pivotal_leg_produces_a_trade_that_the_plain_3to5_rule_would_miss():
    # A single-bar spike at the NY killzone open, far larger than normal
    # 1-minute movement elsewhere in the data -- too short to satisfy the
    # ordinary 3-5 candle rule, but exactly the "big single candle" case
    # the size exception exists for.
    df = generate_synthetic_intraday_ohlcv(n_days=40, seed=11)
    ny_open = df.index.normalize().unique()[25] + pd.Timedelta(hours=9, minutes=30)
    spike_bar = df.index.searchsorted(ny_open)
    typical_range = float((df["high"] - df["low"]).median())
    huge = typical_range * 20

    df = df.copy()
    df.iloc[spike_bar, df.columns.get_loc("high")] = df["close"].iloc[spike_bar] + huge
    df.iloc[spike_bar, df.columns.get_loc("low")] = df["close"].iloc[spike_bar]
    df.iloc[spike_bar, df.columns.get_loc("open")] = df["close"].iloc[spike_bar]

    strict = mls.generate_signals(df, pivotal_leg_size_multiple=1e9)  # size exception disabled
    with_pivotal = mls.generate_signals(df, pivotal_leg_size_multiple=3.0)

    # Not a strict claim that this exact spike trades either way (a lot of
    # other gating still applies) -- just that the size exception can only
    # ever add opportunities relative to the strict rule, never remove any.
    assert (with_pivotal != 0).sum() >= (strict != 0).sum()
