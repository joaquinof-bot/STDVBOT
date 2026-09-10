import numpy as np
import pandas as pd

from stdvbot.backtest import run_backtest
from stdvbot.config import StrategyConfig


def _base_signals_df(n=6, close_start=100.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, close_start)
    df = pd.DataFrame(
        {
            "open": close.copy(),
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "signal": [None] * n,
            "stop_price": np.nan,
            "target_price": np.nan,
        },
        index=idx,
    )
    return df


def test_backtest_enters_next_bar_and_hits_target_short():
    df = _base_signals_df(n=6)
    df.loc[df.index[1], "signal"] = "short"
    df.loc[df.index[1], "stop_price"] = 102.0
    df.loc[df.index[1], "target_price"] = 96.0
    # Bar 2 = entry bar (opens at 100). Bar 3 dips to hit target.
    df.loc[df.index[3], "low"] = 95.0

    config = StrategyConfig(risk_per_trade_pct=1.0)
    result = run_backtest(df, config, initial_equity=10_000.0)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.direction == "short"
    assert trade.entry_time == df.index[2]  # bar after the signal bar
    assert trade.exit_reason == "target"
    assert trade.exit_time == df.index[3]
    assert trade.pnl > 0
    assert result.final_equity > result.initial_equity


def test_backtest_hits_stop_long():
    df = _base_signals_df(n=6)
    df.loc[df.index[1], "signal"] = "long"
    df.loc[df.index[1], "stop_price"] = 98.0
    df.loc[df.index[1], "target_price"] = 104.0
    df.loc[df.index[3], "low"] = 97.0  # stop hit before target

    config = StrategyConfig(risk_per_trade_pct=1.0)
    result = run_backtest(df, config, initial_equity=10_000.0)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.pnl < 0


def test_backtest_time_stop_closes_trade():
    df = _base_signals_df(n=6)
    df.loc[df.index[0], "signal"] = "long"
    df.loc[df.index[0], "stop_price"] = 90.0
    df.loc[df.index[0], "target_price"] = 200.0  # never hit

    config = StrategyConfig(risk_per_trade_pct=1.0, max_bars_in_trade=2)
    result = run_backtest(df, config, initial_equity=10_000.0)

    assert result.num_trades == 1
    assert result.trades[0].exit_reason == "time_stop"


def test_backtest_no_signal_produces_no_trades():
    df = _base_signals_df(n=6)
    config = StrategyConfig()
    result = run_backtest(df, config)
    assert result.num_trades == 0
    assert result.final_equity == result.initial_equity
    assert len(result.equity_curve) == len(df)


def test_backtest_stays_flat_while_position_open():
    df = _base_signals_df(n=10)
    df.loc[df.index[1], "signal"] = "short"
    df.loc[df.index[1], "stop_price"] = 110.0
    df.loc[df.index[1], "target_price"] = 90.0
    # A second signal while still in the first trade must be ignored.
    df.loc[df.index[2], "signal"] = "long"
    df.loc[df.index[2], "stop_price"] = 95.0
    df.loc[df.index[2], "target_price"] = 120.0
    df.loc[df.index[4], "low"] = 89.0  # eventually hits the short's target

    config = StrategyConfig(risk_per_trade_pct=1.0)
    result = run_backtest(df, config)
    assert result.num_trades == 1
    assert result.trades[0].direction == "short"
