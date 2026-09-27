import numpy as np
import pandas as pd
import pytest

from stdvbot import ipda_strategy, po3_strategy
from stdvbot.data import generate_synthetic_intraday_ohlcv


def _path(waypoints, end):
    """1-minute OHLC from piecewise-linear (time, price) waypoints: each
    bar opens at the path's price at its start and closes at the next
    minute's, so structure (swings, gaps) is fully deterministic."""
    times = pd.to_datetime([t for t, _ in waypoints])
    prices = [p for _, p in waypoints]
    idx = pd.date_range(times[0], end, freq="1min")
    grid = pd.date_range(times[0], pd.Timestamp(end) + pd.Timedelta(minutes=1), freq="1min")
    x = (grid - times[0]).total_seconds().to_numpy()
    xp = (times - times[0]).total_seconds().to_numpy()
    p = np.interp(x, xp, prices)
    o, c = p[:-1], p[1:]
    return pd.DataFrame(
        {"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 100.0},
        index=idx,
    )


def _mirror(df, around=200.0):
    return pd.DataFrame(
        {"open": around - df["open"], "high": around - df["low"], "low": around - df["high"],
         "close": around - df["close"], "volume": df["volume"]},
        index=df.index,
    )


def _bullish_po3(rally_to=107.0, mss=True):
    # 4H candle opens 10:00 at 100. Manipulation: drop to 98, bounce to a swing
    # high at 99, final leg down to 96 (the low of OLHC). MSS: close back above
    # 99. STDV off that last leg (99 -> 96, R=3): SBZ 102-103.5, target 2.5 =
    # 106.5, terminus 111. Expansion leaves a bullish FVG nested in the SBZ,
    # price retraces into it, then runs to target.
    after_low = 99.5 if mss else 98.5
    return _path(
        [
            ("2024-01-02 09:00", 100.0), ("2024-01-02 10:00", 100.0),
            ("2024-01-02 10:15", 98.0), ("2024-01-02 10:30", 99.0), ("2024-01-02 10:50", 96.0),
            ("2024-01-02 11:10", after_low), ("2024-01-02 11:30", 104.0 if mss else 98.5),
            ("2024-01-02 11:45", 102.5 if mss else 98.5), ("2024-01-02 12:15", rally_to if mss else 98.5),
            ("2024-01-02 13:00", rally_to if mss else 98.5),
        ],
        end="2024-01-02 13:00",
    )


def test_po3_takes_the_sbz_fvg_retrace_after_mss_and_hits_2_5():
    df = _bullish_po3()
    pos, log = po3_strategy.run(df, extend_to_terminus=False)

    assert len(log) == 1
    t = log[0]
    assert t["direction"] == "long"
    assert (t["anchor0"], t["anchor1"]) == (pytest.approx(99.0), pytest.approx(96.0))
    assert t["target"] == pytest.approx(106.5)
    assert t["stop"] == pytest.approx(95.75)
    assert pd.Timestamp("2024-01-02 11:30") < t["entry_time"] < pd.Timestamp("2024-01-02 11:45")
    assert t["exit_reason"] == "target"
    assert set(np.unique(pos)) <= {0.0, 1.0}


def test_po3_extends_to_terminus_on_a_strong_close_through_2_5():
    df = _bullish_po3(rally_to=112.0)
    _, log = po3_strategy.run(df, extend_to_terminus=True)
    assert len(log) == 1 and log[0]["exit_reason"] == "target_4"


def test_po3_no_trade_without_market_structure_shift():
    _, log = po3_strategy.run(_bullish_po3(mss=False))
    assert log == []


def test_po3_bearish_is_the_mirror_image():
    _, log = po3_strategy.run(_mirror(_bullish_po3()), extend_to_terminus=False)
    assert len(log) == 1
    t = log[0]
    assert t["direction"] == "short"
    assert t["target"] == pytest.approx(200 - 106.5)
    assert t["exit_reason"] == "target"


def _ipda_reversal():
    # 12h lookback before 10:00: leg down 99 -> 95 (range low), then a rally
    # to 104 (range high) -> bullish IOF, STDV off 99->95 (R=4): 2.0 = 107,
    # 2.5 = 109. Cast forward: price pushes into 2-2.5 (108), fails to close
    # above 2.5, closes back below 2.0 -> fade toward EQ of low..extreme.
    return _path(
        [
            ("2024-01-01 22:00", 100.0), ("2024-01-01 22:30", 98.0), ("2024-01-01 22:45", 99.0),
            ("2024-01-01 23:15", 95.0), ("2024-01-02 09:00", 104.0), ("2024-01-02 10:00", 104.0),
            ("2024-01-02 10:30", 108.0), ("2024-01-02 10:45", 106.0), ("2024-01-02 11:30", 101.0),
            ("2024-01-02 12:00", 101.0),
        ],
        end="2024-01-02 12:00",
    )


def test_ipda_reversal_profile_fades_the_2_to_2_5_zone():
    _, log = ipda_strategy.run(_ipda_reversal())
    assert len(log) == 1
    t = log[0]
    assert t["profile"] == "reversal_2_2.5"
    assert t["direction"] == "short"
    assert t["iof"] == "bullish"
    assert t["stop"] == pytest.approx(108.25)
    assert t["target"] == pytest.approx((95.0 + 108.0) / 2)
    assert t["exit_reason"] == "target"


def test_ipda_reversal_bearish_is_the_mirror_image():
    _, log = ipda_strategy.run(_mirror(_ipda_reversal()))
    assert len(log) == 1
    assert (log[0]["profile"], log[0]["direction"], log[0]["iof"]) == ("reversal_2_2.5", "long", "bearish")
    assert log[0]["exit_reason"] == "target"


def _ipda_continuation():
    # Bullish IOF (low 95 before high 106), then a pullback to 99.5 -- below
    # EQ (100.5), i.e. in discount, with unfilled bullish FVGs below from the
    # rally. Cast forward: retrace into one, continue to the range high (ERL).
    return _path(
        [
            ("2024-01-01 22:00", 100.0), ("2024-01-01 22:30", 98.0), ("2024-01-01 22:45", 99.0),
            ("2024-01-01 23:15", 95.0), ("2024-01-01 23:45", 99.0), ("2024-01-02 03:00", 106.0),
            ("2024-01-02 09:30", 99.5), ("2024-01-02 10:00", 99.5), ("2024-01-02 10:20", 98.2),
            ("2024-01-02 12:00", 106.5),
        ],
        end="2024-01-02 12:00",
    )


def test_ipda_continuation_profile_targets_external_range_liquidity():
    _, log = ipda_strategy.run(_ipda_continuation())
    assert len(log) == 1
    t = log[0]
    assert t["profile"] == "continuation"
    assert t["direction"] == "long"
    assert t["target"] == pytest.approx(106.0)
    assert t["stop"] == pytest.approx(94.75)
    assert t["exit_reason"] == "target"


def test_ipda_profiles_can_be_switched_off():
    _, log = ipda_strategy.run(_ipda_continuation(), profiles=("reversal",))
    assert log == []


@pytest.mark.parametrize("module", [po3_strategy, ipda_strategy])
def test_no_look_ahead(module):
    # Positions up to bar m must not change when data after m is removed.
    df = generate_synthetic_intraday_ohlcv(n_days=6, seed=3)
    full, _ = module.run(df)
    for m in (2000, 4500, 7000):
        part, _ = module.run(df.iloc[:m])
        cut = m - 6  # the final 5m bucket of the truncated run may be partial
        pd.testing.assert_series_equal(part.iloc[:cut], full.iloc[:cut])
