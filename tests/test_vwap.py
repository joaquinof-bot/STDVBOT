import numpy as np
import pandas as pd

from stdvbot.indicators.vwap import session_vwap, vwap_swing_state


def _make_df(n=48, start="2024-01-01", freq="1h"):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    price = 100 + np.sin(np.linspace(0, 6, n)) * 5
    df = pd.DataFrame(
        {
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": np.full(n, 10.0),
        },
        index=idx,
    )
    return df


def test_vwap_resets_each_session():
    df = _make_df(n=48, freq="1h")
    out = session_vwap(df, anchor="D")
    # First bar of each UTC day: vwap must equal that bar's typical price
    day_starts = out.index.hour == 0
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    assert np.allclose(out.loc[day_starts, "vwap"], typical.loc[day_starts])


def test_vwap_bands_are_symmetric_and_ordered():
    df = _make_df()
    out = session_vwap(df, bands=(1.0, 2.0))
    valid = out.dropna()
    assert (valid["vwap_upper_2"] >= valid["vwap_upper_1"]).all()
    assert (valid["vwap_lower_2"] <= valid["vwap_lower_1"]).all()
    assert np.allclose(
        (valid["vwap_upper_1"] - valid["vwap"]), (valid["vwap"] - valid["vwap_lower_1"])
    )


def test_vwap_requires_tz_aware_index():
    df = _make_df()
    df.index = df.index.tz_localize(None)
    try:
        session_vwap(df)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_vwap_swing_state_classification():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    close = pd.Series([110.0, 90.0, 100.0], index=idx)
    upper = pd.Series([105.0, 105.0, 105.0], index=idx)
    lower = pd.Series([95.0, 95.0, 95.0], index=idx)
    state = vwap_swing_state(close, upper, lower)
    assert list(state) == ["above_upper", "below_lower", "inside"]
