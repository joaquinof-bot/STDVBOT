import numpy as np
import pandas as pd
import pytest

from stdvbot import manipulation_leg_strategy as mls
from stdvbot import manipulation_leg_strategy_v2 as mls_v2
from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_intraday_ohlcv
from stdvbot.strategies import get_strategy


def _flat_bar(price):
    return {"open": price, "high": price, "low": price, "close": price, "volume": 10}


def _bias_undefined_day_df(dip_to):
    """A 2-day, 1-minute DataFrame where day 0 (2024-01-01) is guaranteed
    to have an undefined daily bias -- day-index 0 is always below
    daily_bias_lookback (default 20), regardless of how much data exists.
    NY killzone (09:30, 6-minute window) on day 0 forms a clean 3-candle
    valid up leg from 100 to 104 (range=4), so level(4.5) = 100 - 18 = 82
    and level(2.5) = 100 - 10 = 90. After the window, price walks down to
    ``dip_to`` and flattens there -- controls which level (if any) gets
    touched.
    """
    idx = pd.date_range("2024-01-01 00:00", periods=1440, freq="1min")
    bars = [_flat_bar(100.0) for _ in idx]

    ny_open_pos = idx.get_loc(pd.Timestamp("2024-01-01 09:30:00"))
    # 3-candle valid leg: 100 -> 101 -> 102.5 -> 104 (extreme at 3rd candle).
    bars[ny_open_pos] = {"open": 100.0, "high": 101.0, "low": 99.8, "close": 101.0, "volume": 50}
    bars[ny_open_pos + 1] = {"open": 101.0, "high": 102.5, "low": 100.8, "close": 102.5, "volume": 50}
    bars[ny_open_pos + 2] = {"open": 102.5, "high": 104.0, "low": 102.3, "close": 104.0, "volume": 50}

    # Walk down toward dip_to over the next 50 bars, then flatten.
    walk_start = ny_open_pos + 6  # window is [start, start+6)
    n_steps = 50
    for i in range(n_steps):
        price = 104.0 - (104.0 - dip_to) * (i + 1) / n_steps
        bars[walk_start + i] = _flat_bar(price)
    for i in range(walk_start + n_steps, walk_start + n_steps + 30):
        bars[i] = _flat_bar(dip_to)

    df1 = pd.DataFrame(bars, index=idx)

    idx2 = pd.date_range("2024-01-02 00:00", periods=1440, freq="1min")
    df2 = pd.DataFrame([_flat_bar(dip_to) for _ in idx2], index=idx2)

    return pd.concat([df1, df2])


def test_v1_never_trades_during_bias_undefined_warmup_even_reaching_aplus():
    df = _bias_undefined_day_df(dip_to=70.0)  # reaches past level(4.5)=82
    signals = mls.generate_signals(df)
    assert (signals == 0).all(), "v1 should skip every killzone while daily bias is undefined"


def test_v2_trades_through_bias_undefined_day_when_aplus_level_is_reached():
    df = _bias_undefined_day_df(dip_to=70.0)  # reaches past level(4.5)=82
    signals = mls_v2.generate_signals(df)
    assert (signals != 0).any(), "v2 should allow an A+-level touch through even with no daily bias"
    assert set(signals.unique()).issubset({-1.0, 0.0, 1.0})


def test_v2_still_refuses_shallow_levels_during_bias_undefined_day():
    # Only reaches level(2.5)=90, never level(4.5)=82 -- v2's fallback is
    # A+-only, not "no filter at all", so this must still produce nothing.
    df = _bias_undefined_day_df(dip_to=88.0)
    signals_v1 = mls.generate_signals(df)
    signals_v2 = mls_v2.generate_signals(df)
    assert (signals_v1 == 0).all()
    assert (signals_v2 == 0).all(), "v2 must not trade a shallow level just because bias is undefined"


def test_v2_matches_v1_once_bias_is_defined():
    # Past the lookback warmup, v2 should behave identically to v1 -- the
    # fork only changes the bias-undefined path.
    df = generate_synthetic_intraday_ohlcv(n_days=60, seed=7)
    signals_v1 = mls.generate_signals(df)
    signals_v2 = mls_v2.generate_signals(df)
    daily = mls.resample_ohlc(df, "1D")
    bias = mls.daily_bias_series(daily, lookback=20)
    defined_days = set(bias[bias.notna()].index)

    on_defined_days = df.index.normalize().isin(defined_days)
    pd.testing.assert_series_equal(
        signals_v1[on_defined_days], signals_v2[on_defined_days], check_names=False
    )


def test_v2_smoke_end_to_end_backtest():
    df = generate_synthetic_intraday_ohlcv(n_days=90, seed=7)
    strategy = get_strategy("manipulation_leg_v2")
    assert strategy.name == "manipulation_leg_v2"

    signals = strategy.generate_signals(df)
    result = run_backtest(df, signals, initial_capital=50_000.0)

    assert len(result.equity_curve) == len(df)
    assert (result.equity_curve > 0).all()


def test_v1_registry_entry_is_unaffected_by_v2_existing():
    # v1 must still be reachable and behave the same as before this fork
    # was added -- a regression guard, not a behavior test.
    strategy = get_strategy("manipulation_leg")
    assert strategy.name == "manipulation_leg"
