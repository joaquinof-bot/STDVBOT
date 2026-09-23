"""A small, leak-free vectorized backtester.

Design choices, spelled out because they materially affect results:

* **Signals are decided on bar i's close, executed on bar i+1's open.**
  ``signals`` (from a Strategy) represents the position an agent would
  *decide* to hold once bar i's candle is complete. That decision can
  only be acted on at the next open, so we shift the target position
  series by one bar before turning it into P&L. This is what keeps the
  backtest from "trading the pattern before it has finished forming".
* **Returns are simple close-to-close returns**, scaled by the
  (shifted) position, so a +1 position earns the bar's return and a -1
  position earns its negative.
* **Transaction costs** (fees + slippage, both in basis points) are
  charged on every bar where the *effective* position changes, against
  the notional being turned over (``|new_pos - old_pos|``).
* Equity compounds: ``equity_t = equity_{t-1} * (1 + net_return_t)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from . import metrics as m


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series          # net per-bar strategy returns
    positions: pd.Series        # effective (already-shifted) position held during each bar
    trades: pd.DataFrame        # one row per position change
    stats: dict

    def summary(self) -> str:
        lines = [f"{k:>18s}: {v}" for k, v in self.stats.items()]
        return "\n".join(lines)


def run_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    periods_per_year: int = 252,
) -> BacktestResult:
    """Run a single-asset, single-position backtest.

    Parameters
    ----------
    df : DataFrame with an ``open``/``close`` column (others ignored).
    signals : target position per bar in {-1, 0, 1} (or any float size),
        decided using information available *as of that bar's close*.
    fee_bps, slippage_bps : round-trip cost components, in basis points
        of notional traded, charged whenever the effective position
        changes.
    """
    if len(df) != len(signals):
        raise ValueError("df and signals must have the same length")
    if not df.index.equals(signals.index):
        signals = signals.reindex(df.index)

    close = df["close"].astype(float)
    bar_return = close.pct_change().fillna(0.0)

    # Execute the *previous* bar's decided signal at this bar's open ->
    # equivalent to shifting the target position forward by one bar and
    # applying it to this bar's close-to-close return.
    effective_pos = signals.shift(1).fillna(0.0)

    turnover = effective_pos.diff().abs()
    turnover.iloc[0] = effective_pos.iloc[0]  # entering from flat counts as turnover
    cost_rate = (fee_bps + slippage_bps) / 10_000.0
    costs = turnover * cost_rate

    gross_return = effective_pos * bar_return
    net_return = gross_return - costs

    equity = initial_capital * (1.0 + net_return).cumprod()

    trades = _extract_trades(effective_pos, close, df.index)

    stats = m.compute_stats(
        net_return, equity, trades, periods_per_year=periods_per_year
    )

    return BacktestResult(
        equity_curve=equity,
        returns=net_return,
        positions=effective_pos,
        trades=trades,
        stats=stats,
    )


def _extract_trades(effective_pos: pd.Series, close: pd.Series, index: pd.Index) -> pd.DataFrame:
    """Summarize each contiguous non-zero position as one trade row."""
    pos = effective_pos.to_numpy()
    px = close.to_numpy()
    rows = []
    i = 0
    n = len(pos)
    while i < n:
        if pos[i] == 0:
            i += 1
            continue
        side = pos[i]
        entry_i = i
        j = i
        while j < n and pos[j] == side:
            j += 1
        exit_i = j - 1
        entry_px = px[entry_i]
        exit_px = px[exit_i]
        ret = side * (exit_px / entry_px - 1.0)
        rows.append(
            {
                "entry_time": index[entry_i],
                "exit_time": index[exit_i],
                "side": "long" if side > 0 else "short",
                "bars_held": exit_i - entry_i + 1,
                "entry_price": entry_px,
                "exit_price": exit_px,
                "return": ret,
            }
        )
        i = j
    return pd.DataFrame(rows)
