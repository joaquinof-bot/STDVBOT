import pandas as pd
import pytest

from stdvbot.data import load_databento_parent_ohlcv_csv


def _write_csv(tmp_path, rows):
    path = tmp_path / "databento.csv"
    df = pd.DataFrame(rows, columns=["ts_event", "open", "high", "low", "close", "volume", "symbol"])
    df.to_csv(path, index=False)
    return str(path)


def test_load_databento_parent_ohlcv_csv_drops_spreads_and_rolls_by_volume(tmp_path):
    rows = [
        # Day 1: only OLD trades -- front month for day 1.
        ("2024-01-01T10:00:00Z", 100, 100, 100, 100, 50, "OLD"),
        ("2024-01-01T10:01:00Z", 101, 101, 101, 101, 50, "OLD"),
        # A spread contract on day 1 -- must be dropped regardless of its (nonsense) price scale.
        ("2024-01-01T10:01:00Z", 5, 5, 5, 5, 999, "OLD-NEW"),
        # Day 2: OLD and NEW both trade, concurrently, with a persistent +30 basis.
        # NEW gets far more volume -> becomes day 2's front month (the roll).
        ("2024-01-02T10:00:00Z", 102, 102, 102, 102, 10, "OLD"),
        ("2024-01-02T10:00:00Z", 132, 132, 132, 132, 200, "NEW"),
        ("2024-01-02T10:01:00Z", 103, 103, 103, 103, 10, "OLD"),
        ("2024-01-02T10:01:00Z", 133, 133, 133, 133, 200, "NEW"),
        # Day 3: only NEW trades.
        ("2024-01-03T10:00:00Z", 134, 134, 134, 134, 300, "NEW"),
    ]
    path = _write_csv(tmp_path, rows)

    df = load_databento_parent_ohlcv_csv(path, utc_offset_hours=0)

    # No spread contract leaked through.
    assert len(df) == 5  # 2 (day1, adjusted OLD) + 2 (day2, NEW) + 1 (day3, NEW)
    assert df.index.is_monotonic_increasing
    assert df.index.duplicated().sum() == 0

    # Day 1 (pre-roll, OLD) is back-adjusted by the measured +30 basis so it
    # joins seamlessly onto NEW's (unadjusted) price plane.
    day1 = df.loc["2024-01-01"]
    assert day1["close"].tolist() == pytest.approx([130.0, 131.0])

    # Day 2 onward (NEW, the chosen front month) is left untouched.
    day2 = df.loc["2024-01-02"]
    assert day2["close"].tolist() == pytest.approx([132.0, 133.0])
    day3 = df.loc["2024-01-03"]
    assert day3["close"].tolist() == pytest.approx([134.0])

    # No artificial cliff at the roll boundary.
    assert df["close"].diff().abs().max() == pytest.approx(1.0)


def test_load_databento_parent_ohlcv_csv_applies_utc_offset(tmp_path):
    rows = [
        ("2024-01-01T09:30:00Z", 100, 100, 100, 100, 10, "OLD"),
    ]
    path = _write_csv(tmp_path, rows)

    df = load_databento_parent_ohlcv_csv(path, utc_offset_hours=-4.0)

    assert df.index[0] == pd.Timestamp("2024-01-01 05:30:00")


def test_load_databento_parent_ohlcv_csv_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"open": [1], "close": [1]}).to_csv(path, index=False)
    with pytest.raises(ValueError):
        load_databento_parent_ohlcv_csv(str(path))
