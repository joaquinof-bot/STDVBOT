import numpy as np
import pandas as pd

from stdvbot.config import StrategyConfig
from stdvbot.strategy import generate_signals


def _synthetic_base_df(days=6, seed=7):
    rng = np.random.default_rng(seed)
    n = days * 24 * 60  # 1-minute bars
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    steps = rng.normal(0, 0.05, n)
    close = 100 + np.cumsum(steps)
    high = close + rng.uniform(0, 0.1, n)
    low = close - rng.uniform(0, 0.1, n)
    open_ = close + rng.normal(0, 0.02, n)
    volume = rng.uniform(1, 10, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_generate_signals_runs_end_to_end_and_has_expected_shape():
    base_df = _synthetic_base_df(days=6)
    config = StrategyConfig(entry_timeframe="15m")  # coarser entry tf keeps the test fast
    out = generate_signals(base_df, config)

    expected_cols = {
        "open", "high", "low", "close", "volume",
        "vwap", "vwap_upper", "vwap_lower", "vwap_state",
        "atr", "killzone", "trend_reject_down", "trend_reject_up",
        "rsi_all_upside", "rsi_all_downside", "top_tf_overbought", "top_tf_oversold",
        "signal", "stop_price", "target_price",
    }
    assert expected_cols.issubset(out.columns)
    assert len(out) > 0
    assert set(out["signal"].dropna().unique()).issubset({"long", "short"})


def test_generate_signals_stop_target_are_directionally_sane():
    base_df = _synthetic_base_df(days=10, seed=3)
    config = StrategyConfig(entry_timeframe="15m")
    out = generate_signals(base_df, config)

    shorts = out[out["signal"] == "short"]
    longs = out[out["signal"] == "long"]

    if not shorts.empty:
        assert (shorts["stop_price"] > shorts["close"]).all()
        assert (shorts["target_price"] < shorts["close"]).all()
    if not longs.empty:
        assert (longs["stop_price"] < longs["close"]).all()
        assert (longs["target_price"] > longs["close"]).all()


def test_signals_only_fire_inside_a_killzone():
    base_df = _synthetic_base_df(days=6)
    config = StrategyConfig(entry_timeframe="15m")
    out = generate_signals(base_df, config)
    signaled = out[out["signal"].notna()]
    assert signaled["killzone"].notna().all()
