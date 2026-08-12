"""Performance metrics for a backtested equity/return series."""
from __future__ import annotations

import numpy as np
import pandas as pd


def total_return(equity: pd.Series) -> float:
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def cagr(equity: pd.Series, periods_per_year: int = 252) -> float:
    n_periods = len(equity)
    if n_periods < 2:
        return 0.0
    years = n_periods / periods_per_year
    if years <= 0:
        return 0.0
    ratio = equity.iloc[-1] / equity.iloc[0]
    if ratio <= 0:
        return -1.0
    return float(ratio ** (1.0 / years) - 1.0)


def annualized_vol(returns: pd.Series, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / periods_per_year
    std = excess.std(ddof=1)
    if not std or np.isnan(std) or std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / periods_per_year
    downside = excess[excess < 0]
    dd_std = downside.std(ddof=1)
    if not dd_std or np.isnan(dd_std) or dd_std == 0:
        return 0.0
    return float(excess.mean() / dd_std * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def calmar_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    return float(cagr(equity, periods_per_year) / mdd)


def win_rate(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    return float((trades["return"] > 0).mean())


def profit_factor(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    gains = trades.loc[trades["return"] > 0, "return"].sum()
    losses = -trades.loc[trades["return"] < 0, "return"].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def compute_stats(
    returns: pd.Series,
    equity: pd.Series,
    trades: pd.DataFrame,
    periods_per_year: int = 252,
) -> dict:
    return {
        "total_return": round(total_return(equity), 4),
        "cagr": round(cagr(equity, periods_per_year), 4),
        "annualized_vol": round(annualized_vol(returns, periods_per_year), 4),
        "sharpe": round(sharpe_ratio(returns, periods_per_year), 3),
        "sortino": round(sortino_ratio(returns, periods_per_year), 3),
        "max_drawdown": round(max_drawdown(equity), 4),
        "calmar": round(calmar_ratio(equity, periods_per_year), 3),
        "num_trades": int(len(trades)),
        "win_rate": round(win_rate(trades), 4),
        "profit_factor": round(profit_factor(trades), 4),
    }
