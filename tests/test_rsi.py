import pandas as pd

from stdvbot.indicators.rsi import rsi


def test_rsi_all_gains_approaches_100():
    close = pd.Series(range(1, 40), dtype=float)
    r = rsi(close, length=14)
    assert r.iloc[-1] > 95


def test_rsi_all_losses_approaches_0():
    close = pd.Series(range(40, 1, -1), dtype=float)
    r = rsi(close, length=14)
    assert r.iloc[-1] < 5


def test_rsi_flat_series_is_neutral():
    close = pd.Series([100.0] * 30)
    r = rsi(close, length=14)
    assert r.iloc[-1] == 50.0


def test_rsi_bounded_0_100():
    close = pd.Series([1, 5, 2, 8, 3, 9, 1, 10, 2, 11, 3, 12, 1, 13, 2, 14, 1, 15], dtype=float)
    r = rsi(close, length=14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
