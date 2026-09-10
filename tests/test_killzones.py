import pandas as pd

from stdvbot.indicators.killzones import DEFAULT_KILLZONES, in_killzone, killzone_mask


def test_in_killzone_matches_asian_session():
    ts = pd.Timestamp("2024-01-01 01:30", tz="UTC")
    assert in_killzone(ts) == "asian"


def test_in_killzone_none_between_sessions():
    ts = pd.Timestamp("2024-01-01 05:00", tz="UTC")
    assert in_killzone(ts) is None


def test_in_killzone_requires_tz_aware():
    ts = pd.Timestamp("2024-01-01 01:30")
    try:
        in_killzone(ts)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_killzone_mask_matches_scalar_version():
    idx = pd.date_range("2024-01-01", periods=24 * 2, freq="1h", tz="UTC")
    mask = killzone_mask(idx)
    for ts, name in zip(idx, mask):
        expected = in_killzone(ts)
        got = None if name is None else name
        assert got == expected


def test_default_killzones_do_not_overlap():
    windows = sorted(DEFAULT_KILLZONES.values())
    for (s1, m1, e1, em1), (s2, m2, e2, em2) in zip(windows, windows[1:]):
        assert (e1, em1) <= (s2, m2)
