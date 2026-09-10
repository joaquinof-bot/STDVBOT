"""Multi-timeframe VWAP-swing / RSI / trendline killzone reversion strategy.

Signal logic (mean reversion, evaluated bar-by-bar on `config.entry_timeframe`):

SHORT setup (fade an overbought swing high):
    1. Bar falls inside a configured killzone window.
    2. RSI is on the "upside" (> neutral) on *every* timeframe in the stack
       -- the multi-timeframe trend-direction alignment the strategy is
       named for.
    3. The highest timeframe's RSI is at/above the overbought threshold
       (the move is actually extended, not just mildly bullish).
    4. Price tagged the upper VWAP band and the current bar has rolled
       back inside it (the "VWAP swing").
    5. A recent bar rejected a resistance trendline (auto-fit through the
       last two confirmed swing-high pivots) on one of the configured
       trendline timeframes.

LONG setup is the mirror image (oversold / lower band / support trendline).

Everything is computed with `merge_asof(direction="backward")` alignment
(see `stdvbot.data.align_to_base`), so no higher-timeframe value is ever
visible before that bar has actually closed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .data import align_to_base, build_timeframe_stack
from .indicators import (
    atr,
    killzone_mask,
    rolling_trendlines,
    rsi,
    session_vwap,
    trendline_interaction,
    vwap_swing_state,
)

RECENT_TREND_REJECTION_BARS = 3
SWING_LOOKBACK_BARS = 10


def _trendline_rejections(
    entry_index: pd.DatetimeIndex, tf_df: pd.DataFrame, config: StrategyConfig
) -> tuple[pd.Series, pd.Series]:
    tl = rolling_trendlines(
        tf_df, window=config.trendline_pivot_window, use_last_n=config.trendline_use_last_n
    )
    tf_atr = atr(tf_df, config.atr_length)
    frame = tf_df[["high", "low", "close"]].join(tl).join(tf_atr.rename("atr"))
    aligned = align_to_base(entry_index, frame)

    reject_down = pd.Series(False, index=entry_index)
    reject_up = pd.Series(False, index=entry_index)
    for ts, row in aligned.iterrows():
        res = trendline_interaction(
            row["high"], row["low"], row["close"], row["res_value"], row["atr"],
            config.trendline_tolerance_atr_mult,
        )
        sup = trendline_interaction(
            row["high"], row["low"], row["close"], row["sup_value"], row["atr"],
            config.trendline_tolerance_atr_mult,
        )
        reject_down.loc[ts] = res == "reject_down"
        reject_up.loc[ts] = sup == "reject_up"

    window = RECENT_TREND_REJECTION_BARS
    reject_down = reject_down.rolling(window, min_periods=1).max().astype(bool)
    reject_up = reject_up.rolling(window, min_periods=1).max().astype(bool)
    return reject_down, reject_up


def generate_signals(base_df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Compute the full indicator stack and entry signals.

    `base_df` must be OHLCV at (or below) the finest timeframe in
    `config.timeframe_stack`, close-time-indexed (see `stdvbot.data`).
    Returns a DataFrame indexed on `config.entry_timeframe` bars.
    """
    if config.entry_timeframe not in config.timeframe_stack:
        raise ValueError("entry_timeframe must be one of timeframe_stack")

    stack = build_timeframe_stack(base_df, config.timeframe_stack)
    entry_df = stack[config.entry_timeframe]
    entry_index = entry_df.index

    out = pd.DataFrame(index=entry_index)
    out["open"] = entry_df["open"]
    out["high"] = entry_df["high"]
    out["low"] = entry_df["low"]
    out["close"] = entry_df["close"]
    out["volume"] = entry_df["volume"]

    # --- RSI on every timeframe, aligned onto the entry timeframe ---
    rsi_cols = []
    for tf in config.timeframe_stack:
        tf_rsi = rsi(stack[tf]["close"], config.rsi_length)
        aligned = align_to_base(entry_index, tf_rsi.to_frame("rsi"))
        col = f"rsi_{tf}"
        out[col] = aligned["rsi"]
        rsi_cols.append(col)

    rsi_all_upside = pd.Series(True, index=entry_index)
    rsi_all_downside = pd.Series(True, index=entry_index)
    for col in rsi_cols:
        rsi_all_upside &= out[col] > config.rsi_neutral
        rsi_all_downside &= out[col] < config.rsi_neutral
    out["rsi_all_upside"] = rsi_all_upside
    out["rsi_all_downside"] = rsi_all_downside

    top_tf_col = f"rsi_{config.timeframe_stack[0]}"
    out["top_tf_overbought"] = out[top_tf_col] >= config.rsi_overbought
    out["top_tf_oversold"] = out[top_tf_col] <= config.rsi_oversold

    # --- VWAP swing on the entry timeframe ---
    vwap_df = session_vwap(entry_df, anchor=config.vwap_anchor, bands=config.vwap_bands)
    band = config.vwap_swing_band
    out["vwap"] = vwap_df["vwap"]
    out["vwap_upper"] = vwap_df[f"vwap_upper_{band:g}"]
    out["vwap_lower"] = vwap_df[f"vwap_lower_{band:g}"]
    out["vwap_state"] = vwap_swing_state(out["close"], out["vwap_upper"], out["vwap_lower"])
    prev_state = out["vwap_state"].shift(1)
    out["vwap_swing_down_reversion"] = (prev_state == "above_upper") & (out["vwap_state"] != "above_upper")
    out["vwap_swing_up_reversion"] = (prev_state == "below_lower") & (out["vwap_state"] != "below_lower")

    # --- ATR on the entry timeframe (stops) ---
    out["atr"] = atr(entry_df, config.atr_length)

    # --- Killzone ---
    out["killzone"] = killzone_mask(entry_index, config.killzones)
    in_kz = out["killzone"].notna()

    # --- Trendline rejections across configured timeframes ---
    trend_reject_down = pd.Series(False, index=entry_index)
    trend_reject_up = pd.Series(False, index=entry_index)
    for tf in config.trendline_timeframes:
        rd, ru = _trendline_rejections(entry_index, stack[tf], config)
        trend_reject_down |= rd
        trend_reject_up |= ru
    out["trend_reject_down"] = trend_reject_down
    out["trend_reject_up"] = trend_reject_up

    # --- Combine into entry signals ---
    short_ok = (
        in_kz
        & out["rsi_all_upside"]
        & out["top_tf_overbought"]
        & out["vwap_swing_down_reversion"]
        & out["trend_reject_down"]
    )
    long_ok = (
        in_kz
        & out["rsi_all_downside"]
        & out["top_tf_oversold"]
        & out["vwap_swing_up_reversion"]
        & out["trend_reject_up"]
    )

    out["signal"] = np.where(short_ok, "short", np.where(long_ok, "long", None))

    swing_high = out["high"].rolling(SWING_LOOKBACK_BARS, min_periods=1).max()
    swing_low = out["low"].rolling(SWING_LOOKBACK_BARS, min_periods=1).min()

    stop = pd.Series(np.nan, index=entry_index)
    target = pd.Series(np.nan, index=entry_index)

    short_mask = out["signal"] == "short"
    stop.loc[short_mask] = swing_high.loc[short_mask] + config.stop_atr_mult * out.loc[short_mask, "atr"]
    risk_short = stop.loc[short_mask] - out.loc[short_mask, "close"]
    target.loc[short_mask] = out.loc[short_mask, "close"] - config.target_r_multiple * risk_short

    long_mask = out["signal"] == "long"
    stop.loc[long_mask] = swing_low.loc[long_mask] - config.stop_atr_mult * out.loc[long_mask, "atr"]
    risk_long = out.loc[long_mask, "close"] - stop.loc[long_mask]
    target.loc[long_mask] = out.loc[long_mask, "close"] + config.target_r_multiple * risk_long

    out["stop_price"] = stop
    out["target_price"] = target

    return out
