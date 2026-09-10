"""Event-driven backtester for the signal DataFrame produced by `strategy.generate_signals`.

Simplifications, stated explicitly rather than hidden:
- One open position at a time.
- Entry fills at the *next* bar's open after a signal bar closes (no
  same-bar fill).
- Exit checks start the bar after entry; if a bar's range touches both
  the stop and the target, the stop is assumed to fill first (conservative).
- No commissions/slippage modeled -- pass `commission_pct`/`slippage_pct`
  to approximate them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import StrategyConfig


@dataclass
class Trade:
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    size: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl: float | None = None
    r_multiple: float | None = None


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    initial_equity: float
    final_equity: float

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if t.pnl is not None]
        if not closed:
            return float("nan")
        wins = sum(1 for t in closed if t.pnl > 0)
        return wins / len(closed)

    @property
    def avg_r_multiple(self) -> float:
        rs = [t.r_multiple for t in self.trades if t.r_multiple is not None]
        return float(np.mean(rs)) if rs else float("nan")

    @property
    def profit_factor(self) -> float:
        closed = [t for t in self.trades if t.pnl is not None]
        gains = sum(t.pnl for t in closed if t.pnl > 0)
        losses = -sum(t.pnl for t in closed if t.pnl < 0)
        if losses == 0:
            return float("inf") if gains > 0 else float("nan")
        return gains / losses

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve.empty:
            return float("nan")
        running_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - running_max) / running_max
        return float(drawdown.min())

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity / self.initial_equity) - 1.0

    def summary(self) -> dict:
        return {
            "num_trades": self.num_trades,
            "win_rate": self.win_rate,
            "avg_r_multiple": self.avg_r_multiple,
            "profit_factor": self.profit_factor,
            "max_drawdown_pct": self.max_drawdown_pct,
            "total_return_pct": self.total_return_pct,
            "final_equity": self.final_equity,
        }


def run_backtest(
    signals: pd.DataFrame,
    config: StrategyConfig,
    initial_equity: float = 10_000.0,
    commission_pct: float = 0.0,
    slippage_pct: float = 0.0,
) -> BacktestResult:
    df = signals
    n = len(df)
    equity = initial_equity
    equity_curve = pd.Series(index=df.index, dtype=float)

    trades: list[Trade] = []
    position: Trade | None = None
    entry_idx: int | None = None
    friction = commission_pct + slippage_pct

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    signal_arr = df["signal"].to_numpy()
    stop_arr = df["stop_price"].to_numpy()
    target_arr = df["target_price"].to_numpy()
    timestamps = df.index

    pending_entry: dict | None = None

    for i in range(n):
        # Fill a pending entry queued from the previous bar's signal.
        if position is None and pending_entry is not None:
            entry_price = opens[i] * (1 + friction if pending_entry["direction"] == "long" else 1 - friction)
            risk_per_unit = abs(entry_price - pending_entry["stop"])
            if risk_per_unit > 0 and not np.isnan(risk_per_unit):
                risk_amount = equity * (config.risk_per_trade_pct / 100.0)
                size = risk_amount / risk_per_unit
                position = Trade(
                    direction=pending_entry["direction"],
                    entry_time=timestamps[i],
                    entry_price=entry_price,
                    stop_price=pending_entry["stop"],
                    target_price=pending_entry["target"],
                    size=size,
                )
                entry_idx = i
            pending_entry = None

        elif position is not None and i > entry_idx:
            bars_in_trade = i - entry_idx
            hit_stop = hit_target = False
            if position.direction == "short":
                hit_stop = highs[i] >= position.stop_price
                hit_target = lows[i] <= position.target_price
            else:
                hit_stop = lows[i] <= position.stop_price
                hit_target = highs[i] >= position.target_price

            exit_price = exit_reason = None
            if hit_stop:
                exit_price, exit_reason = position.stop_price, "stop"
            elif hit_target:
                exit_price, exit_reason = position.target_price, "target"
            elif bars_in_trade >= config.max_bars_in_trade:
                exit_price, exit_reason = closes[i], "time_stop"

            if exit_price is not None:
                exit_price *= (1 - friction) if position.direction == "long" else (1 + friction)
                if position.direction == "long":
                    pnl = (exit_price - position.entry_price) * position.size
                else:
                    pnl = (position.entry_price - exit_price) * position.size
                risk_amount = abs(position.entry_price - position.stop_price) * position.size
                position.exit_time = timestamps[i]
                position.exit_price = exit_price
                position.exit_reason = exit_reason
                position.pnl = pnl
                position.r_multiple = pnl / risk_amount if risk_amount else float("nan")
                equity += pnl
                trades.append(position)
                position = None
                entry_idx = None

        # Queue a new entry off this bar's freshly closed signal (only when flat).
        if position is None and pending_entry is None and i + 1 < n:
            sig = signal_arr[i]
            if sig in ("long", "short"):
                pending_entry = {
                    "direction": sig,
                    "stop": stop_arr[i],
                    "target": target_arr[i],
                }

        unrealized = 0.0
        if position is not None:
            if position.direction == "long":
                unrealized = (closes[i] - position.entry_price) * position.size
            else:
                unrealized = (position.entry_price - closes[i]) * position.size
        equity_curve.iloc[i] = equity + unrealized

    return BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        initial_equity=initial_equity,
        final_equity=equity_curve.iloc[-1] if n else initial_equity,
    )
