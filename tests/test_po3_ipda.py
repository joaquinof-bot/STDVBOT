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


def test_po3_does_not_rearm_after_the_move_runs_without_an_entry():
    # Regression guard: after MSS, price runs through the 2.5 target (106.5)
    # with no retrace, pulls back, and prints fresh FVGs below target. That
    # PO3 is done -- the first version re-armed the same setup on the next
    # bar and entered late (12:24 here), after the distribution completed.
    df = _path(
        [
            ("2024-01-02 09:00", 100.0), ("2024-01-02 10:00", 100.0),
            ("2024-01-02 10:15", 98.0), ("2024-01-02 10:30", 99.0), ("2024-01-02 10:50", 96.0),
            ("2024-01-02 11:10", 99.5), ("2024-01-02 11:40", 108.0), ("2024-01-02 12:00", 102.5),
            ("2024-01-02 12:20", 105.5), ("2024-01-02 12:30", 104.0), ("2024-01-02 13:00", 109.0),
        ],
        end="2024-01-02 13:00",
    )
    _, log = po3_strategy.run(df, entry_mode="any_irl")
    assert log == []


def _killzone_po3_day(prior_trend_up=True, reach_zone=True):
    # Three prior days (rising -> daily bias "down", so an up killzone leg is
    # counter-trend, i.e. manipulation), then the test day:
    #   09:30-09:33 up leg 100 -> 102 (3 candles, R=2): 2.0 level = 96.
    #   Manipulation down: swing high 98.5 at 10:10, low 95.5 (zone reached).
    #   MSS: close back above 98.5. PO3 off 98.5 -> 95.5 (R=3): SBZ 101.5-103,
    #   target 2.5 = 106. Retrace into the SBZ FVG, then run to target.
    step = 5.0 if prior_trend_up else -5.0
    prior = [_path([(f"2024-01-0{d} 09:00", 90.0 + step * (d - 1)), (f"2024-01-0{d} 11:00", 90.0 + step * (d - 1))],
                   end=f"2024-01-0{d} 11:00") for d in (1, 2, 3)]
    low = 95.5 if reach_zone else 96.5
    day = _path(
        [
            ("2024-01-04 09:00", 100.0), ("2024-01-04 09:30", 100.0), ("2024-01-04 09:33", 102.0),
            ("2024-01-04 09:36", 101.5), ("2024-01-04 10:00", 97.0), ("2024-01-04 10:10", 98.5),
            ("2024-01-04 10:25", low), ("2024-01-04 10:45", 99.0), ("2024-01-04 11:05", 103.5),
            ("2024-01-04 11:15", 102.0), ("2024-01-04 11:45", 106.5), ("2024-01-04 12:30", 106.5),
        ],
        end="2024-01-04 12:30",
    )
    return pd.concat(prior + [day])


def test_killzone_po3_enters_on_mss_and_sbz_retrace_after_the_zone():
    from stdvbot import killzone_po3_strategy

    _, log = killzone_po3_strategy.run(_killzone_po3_day(), daily_bias_lookback=2, extend_to_terminus=False)
    assert len(log) == 1
    t = log[0]
    assert (t["killzone"], t["leg_direction"], t["direction"]) == ("ny", "up", "long")
    assert (t["anchor0"], t["anchor1"]) == (pytest.approx(98.5), pytest.approx(95.5))
    assert t["target"] == pytest.approx(106.0)
    assert pd.Timestamp("2024-01-04 11:05") < t["entry_time"] < pd.Timestamp("2024-01-04 11:15")
    assert t["exit_reason"] == "target"


def test_killzone_po3_needs_the_zone():
    from stdvbot import killzone_po3_strategy

    # Same MSS and FVG retrace, but the manipulation stops short of the 2.0 level.
    _, log = killzone_po3_strategy.run(_killzone_po3_day(reach_zone=False), daily_bias_lookback=2)
    assert log == []


def test_killzone_po3_keeps_v1s_off_trend_filter():
    from stdvbot import killzone_po3_strategy

    # Prior days falling -> daily bias "up" -> an up killzone leg agrees with it: not manipulation.
    _, log = killzone_po3_strategy.run(_killzone_po3_day(prior_trend_up=False), daily_bias_lookback=2)
    assert log == []


def test_killzone_po3_no_look_ahead():
    from stdvbot import killzone_po3_strategy

    df = generate_synthetic_intraday_ohlcv(n_days=12, seed=5)
    full, log = killzone_po3_strategy.run(df, daily_bias_lookback=3)
    for m in (6000, 11000, 15000):
        part, _ = killzone_po3_strategy.run(df.iloc[:m], daily_bias_lookback=3)
        cut = m - 6
        pd.testing.assert_series_equal(part.iloc[:cut], full.iloc[:cut])
