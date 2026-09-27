import numpy as np
import pandas as pd
import pytest

from stdvbot.legs import Leg, inverse_fib_levels
from stdvbot.stdv import (
    STDV_MULTIPLES,
    FiveMinuteView,
    four_hour_boundaries,
    fvg_at,
    pivot_confirmed_at,
    stdv_projection,
)


@pytest.mark.parametrize("direction,origin,extreme", [("up", 100.0, 104.0), ("down", 100.0, 97.0)])
def test_stdv_projection_is_the_same_math_as_inverse_fib_levels(direction, origin, extreme):
    # The PDFs' STDV Fib (1 on the leg's extreme, 0 on its start, -1..-4
    # projected) is exactly what the v1/v2 engine already computes.
    leg = Leg(pd.Timestamp("2024-01-01"), origin, pd.Timestamp("2024-01-01 00:03"), extreme, 3, direction)
    ours = inverse_fib_levels(leg, STDV_MULTIPLES)
    pdf = stdv_projection(origin, extreme, STDV_MULTIPLES)
    for m in STDV_MULTIPLES:
        assert pdf[m] == pytest.approx(ours[m])


def test_stdv_projection_down_leg_projects_up():
    # Bullish distribution example: last manipulation leg from swing high 99
    # down to low 96 projects the upside.
    levels = stdv_projection(99.0, 96.0)
    assert levels[1.0] == pytest.approx(102.0)
    assert levels[1.5] == pytest.approx(103.5)
    assert levels[2.5] == pytest.approx(106.5)
    assert levels[4.0] == pytest.approx(111.0)


def test_pivot_needs_right_side_bars_to_confirm():
    highs = np.array([1.0, 2.0, 5.0, 3.0, 2.0])
    assert pivot_confirmed_at(highs, 2, 2, 2, "high")
    assert not pivot_confirmed_at(highs[:4], 2, 2, 2, "high")  # only 1 bar after: not yet known


def test_pivot_rejects_flat_tops():
    highs = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
    assert not pivot_confirmed_at(highs, 2, 2, 2, "high")


def test_fvg_detection():
    highs = np.array([10.0, 12.0, 15.0])
    lows = np.array([9.0, 10.5, 11.0])
    assert fvg_at(highs, lows, 2) == (1, 10.0, 11.0)  # bullish: low[2] > high[0]
    assert fvg_at(-lows, -highs, 2) == (-1, -11.0, -10.0)  # mirrored -> bearish
    assert fvg_at(highs, lows, 1) is None


def test_five_minute_view_completes_on_last_minute_of_bucket():
    idx = pd.date_range("2024-01-01 10:00", periods=12, freq="1min")
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx)
    view = FiveMinuteView.build(df)
    assert view.completes_at == {4: 0, 9: 1, 11: 2}  # 10:04, 10:09, and the partial 10:10 bucket


def test_four_hour_boundaries():
    idx = pd.date_range("2024-01-01 01:00", "2024-01-01 15:00", freq="1min")
    got = [t.hour for t in four_hour_boundaries(idx)]
    assert got == [2, 6, 10, 14]
