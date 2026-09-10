"""Session-anchored VWAP with standard-deviation bands.

The VWAP resets at the start of each "anchor session" (daily by default, at
00:00 UTC). Bands are the volume-weighted standard deviation of the typical
price around the running VWAP, which is the same construction TradingView's
"VWAP with bands" indicator uses. A "VWAP swing" is price extending to (or
through) one of the outer bands and then reverting back toward the VWAP.
"""
from __future__ import annotations

import pandas as pd


def session_vwap(
    df: pd.DataFrame,
    anchor: str = "D",
    bands: tuple[float, ...] = (1.0, 2.0, 3.0),
    tz: str = "UTC",
) -> pd.DataFrame:
    """Compute a session-anchored VWAP with N standard-deviation bands.

    Parameters
    ----------
    df: DataFrame with columns ["open", "high", "low", "close", "volume"]
        and a DatetimeIndex (UTC).
    anchor: pandas offset alias used to group bars into VWAP sessions
        (e.g. "D" for daily reset, "W" for weekly).
    bands: standard-deviation multipliers to compute bands for.
    tz: index is assumed to already be in this timezone; only used to
        validate the index is tz-aware.

    Returns
    -------
    A DataFrame indexed like `df` with columns: vwap, vwap_std,
    vwap_upper_<n>, vwap_lower_<n> for each n in `bands`.
    """
    if df.index.tz is None:
        raise ValueError("df index must be tz-aware (UTC)")

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].clip(lower=0)

    session_key = df.index.tz_convert(tz).tz_localize(None).to_period(anchor).astype(str)

    pv = typical * volume
    cum_pv = pv.groupby(session_key).cumsum()
    cum_vol = volume.groupby(session_key).cumsum().replace(0, pd.NA)

    vwap = cum_pv / cum_vol

    sq_dev = volume * (typical - vwap) ** 2
    cum_sq_dev = sq_dev.groupby(session_key).cumsum()
    variance = cum_sq_dev / cum_vol
    std = variance.clip(lower=0) ** 0.5

    out = pd.DataFrame(index=df.index)
    out["vwap"] = vwap.astype(float)
    out["vwap_std"] = std.astype(float)
    for n in bands:
        out[f"vwap_upper_{n:g}"] = out["vwap"] + n * out["vwap_std"]
        out[f"vwap_lower_{n:g}"] = out["vwap"] - n * out["vwap_std"]

    return out


def vwap_swing_state(close: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    """Classify each bar's relationship to the VWAP bands.

    Returns a Series of strings: "above_upper", "below_lower", "inside".
    Used to detect a swing: price was outside a band and the current bar
    has reverted back inside (or is still extending).
    """
    state = pd.Series("inside", index=close.index)
    state[close > upper] = "above_upper"
    state[close < lower] = "below_lower"
    return state
