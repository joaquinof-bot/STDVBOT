import numpy as np
import pandas as pd

from stdvbot.data import align_to_base, resample_ohlcv


def _minute_df(n=120):
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    price = np.linspace(100, 100 + n / 10, n)
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": np.full(n, 1.0),
        },
        index=idx,
    )


def test_resample_ohlcv_aggregates_correctly():
    # Minute bars timestamped 00:01..01:00 (close times) all belong to the
    # single (00:00, 01:00] hourly bin -- a bar stamped exactly on an hour
    # boundary (e.g. 00:00) would belong to the *previous* hour's bin
    # instead, since resample uses closed="right".
    idx = pd.date_range("2024-01-01 00:01", periods=60, freq="1min", tz="UTC")
    price = np.linspace(100, 106, 60)
    df = pd.DataFrame(
        {
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": np.full(60, 1.0),
        },
        index=idx,
    )
    hourly = resample_ohlcv(df, "1h")
    assert len(hourly) == 1
    row = hourly.iloc[0]
    assert row["open"] == df["open"].iloc[0]
    assert row["close"] == df["close"].iloc[-1]
    assert row["high"] == df["high"].max()
    assert row["low"] == df["low"].min()
    assert row["volume"] == df["volume"].sum()
    # close-time indexed: the bar's timestamp is the close of the hour.
    assert hourly.index[0] == df.index[-1]


def test_align_to_base_has_no_lookahead():
    base = _minute_df(30)
    hourly = resample_ohlcv(base, "1h")  # closes at minute 30 (only partial hour, dropped) -> none yet
    # Build two complete hourly bars for a clean check.
    base = _minute_df(125)
    hourly = resample_ohlcv(base, "1h")
    aligned = align_to_base(base.index, hourly[["close"]])

    first_hour_close_time = hourly.index[0]
    # Before the first higher-tf bar closes, aligned value must be NaN.
    before = base.index[base.index < first_hour_close_time]
    assert aligned.loc[before, "close"].isna().all()
    # At and after the close time, it must equal that closed bar's value (no future bar's value).
    at_close = aligned.loc[first_hour_close_time, "close"]
    assert at_close == hourly["close"].iloc[0]
    just_after = first_hour_close_time + pd.Timedelta(minutes=1)
    if just_after in aligned.index:
        assert aligned.loc[just_after, "close"] == hourly["close"].iloc[0]
