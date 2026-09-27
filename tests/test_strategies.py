import pandas as pd
import pytest

from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_ohlcv
from stdvbot.strategies import STRATEGY_REGISTRY, get_strategy


@pytest.fixture(scope="module")
def synthetic_df():
    return generate_synthetic_ohlcv(n=300, seed=1)


@pytest.mark.parametrize("name", sorted(STRATEGY_REGISTRY))
def test_strategy_signals_are_valid_positions(name, synthetic_df):
    strategy = get_strategy(name)
    signals = strategy.generate_signals(synthetic_df)

    assert isinstance(signals, pd.Series)
    assert len(signals) == len(synthetic_df)
    assert signals.index.equals(synthetic_df.index)
    assert set(signals.unique()).issubset({-1, 0, 1})


@pytest.mark.parametrize("name", sorted(STRATEGY_REGISTRY))
def test_strategy_runs_end_to_end_backtest(name, synthetic_df):
    strategy = get_strategy(name)
    signals = strategy.generate_signals(synthetic_df)
    result = run_backtest(synthetic_df, signals)

    expected_keys = {
        "total_return", "cagr", "annualized_vol", "sharpe", "sortino",
        "max_drawdown", "calmar", "num_trades", "win_rate", "profit_factor",
    }
    assert expected_keys.issubset(result.stats.keys())
    assert len(result.equity_curve) == len(synthetic_df)
    assert (result.equity_curve > 0).all()


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        get_strategy("not_a_strategy")


def test_max_hold_forces_exit():
    from stdvbot.strategies import _entries_to_positions

    idx = pd.RangeIndex(6)
    long_entry = pd.Series([True, False, False, False, False, False], index=idx)
    short_entry = pd.Series([False] * 6, index=idx)

    pos = _entries_to_positions(long_entry, short_entry, max_hold=2)
    # Enters long at bar 0, must be flat again after 2 bars held.
    assert pos.tolist() == [1, 1, 0, 0, 0, 0]


def test_conflicting_entries_flatten():
    from stdvbot.strategies import _entries_to_positions

    idx = pd.RangeIndex(2)
    long_entry = pd.Series([True, False], index=idx)
    short_entry = pd.Series([True, False], index=idx)

    pos = _entries_to_positions(long_entry, short_entry, max_hold=0)
    assert pos.tolist() == [0, 0]
