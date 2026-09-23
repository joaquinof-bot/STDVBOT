import numpy as np
import pandas as pd
import pytest

from stdvbot.backtest import run_backtest


def _price_df(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": closes, "close": closes}, index=idx)


def test_signal_is_shifted_one_bar_no_lookahead():
    # A long decision made on bar 0's close can only be realized starting
    # bar 1's return -- bar 0 itself must earn 0.
    df = _price_df([100.0, 110.0, 121.0])
    signals = pd.Series([1, 1, 1], index=df.index)
    result = run_backtest(df, signals, fee_bps=0.0, slippage_bps=0.0)

    assert result.positions.iloc[0] == 0
    assert result.positions.iloc[1] == 1
    assert result.returns.iloc[0] == pytest.approx(0.0)
    assert result.returns.iloc[1] == pytest.approx(0.10)
    assert result.returns.iloc[2] == pytest.approx(0.10)


def test_costs_charged_only_on_position_change():
    df = _price_df([100.0, 110.0, 121.0])
    signals = pd.Series([1, 1, 1], index=df.index)
    result = run_backtest(df, signals, fee_bps=5.0, slippage_bps=2.0)

    cost_rate = 0.0007
    assert result.returns.iloc[0] == pytest.approx(0.0)
    # Entering the position (turnover=1) at bar 1 pays the cost once.
    assert result.returns.iloc[1] == pytest.approx(0.10 - cost_rate)
    # Holding (turnover=0) at bar 2 pays nothing extra.
    assert result.returns.iloc[2] == pytest.approx(0.10)


def test_equity_curve_compounds_correctly():
    df = _price_df([100.0, 110.0, 121.0])
    signals = pd.Series([1, 1, 1], index=df.index)
    result = run_backtest(df, signals, initial_capital=10_000.0, fee_bps=0.0, slippage_bps=0.0)

    expected = [10_000.0, 11_000.0, 12_100.0]
    for got, exp in zip(result.equity_curve.tolist(), expected):
        assert got == pytest.approx(exp)


def test_flat_signal_produces_no_trades():
    df = _price_df([100.0, 101.0, 99.0, 102.0])
    signals = pd.Series([0, 0, 0, 0], index=df.index)
    result = run_backtest(df, signals)
    assert result.trades.empty
    assert result.stats["num_trades"] == 0
    assert result.equity_curve.iloc[-1] == pytest.approx(result.equity_curve.iloc[0])


def test_trade_extraction_matches_manual_calc():
    df = _price_df([100.0, 110.0, 121.0])
    signals = pd.Series([1, 1, 1], index=df.index)
    result = run_backtest(df, signals, fee_bps=0.0, slippage_bps=0.0)

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["side"] == "long"
    assert trade["entry_price"] == pytest.approx(110.0)
    assert trade["exit_price"] == pytest.approx(121.0)
    assert trade["return"] == pytest.approx(121.0 / 110.0 - 1.0)


def test_short_position_earns_negative_of_return():
    df = _price_df([100.0, 90.0, 81.0])
    signals = pd.Series([-1, -1, -1], index=df.index)
    result = run_backtest(df, signals, fee_bps=0.0, slippage_bps=0.0)
    assert result.returns.iloc[1] == pytest.approx(0.10)  # -1 * -10% = +10%


def test_mismatched_length_raises():
    df = _price_df([100.0, 101.0])
    signals = pd.Series([1, 0, 1])
    with pytest.raises(ValueError):
        run_backtest(df, signals)
