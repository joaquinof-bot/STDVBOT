"""Prop-firm evaluation compliance checking and pass-rate estimation.

Turns a backtest's daily equity curve into a pass/fail read against a
specific prop firm's evaluation rules (see
``docs/propfirm_myfundedfutures_pro_50k.md`` for the MyFundedFutures Pro
50K numbers this was built against), and estimates a "pass %" by replaying
the rules across many overlapping windows of a longer equity history.

This is deliberately decoupled from any particular strategy: it operates
on the daily equity curve any stdvbot backtest already produces
(``stdvbot.backtest.BacktestResult.equity_curve``), one value per trading
day. It doesn't require the manipulation-leg strategy or a live execution
pipeline to exist — it works today against the candlestick strategies
already in ``stdvbot/strategies.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class PropFirmRules:
    """A prop firm's evaluation rule set, in dollar terms."""

    name: str
    starting_balance: float
    max_loss_limit: float  # flat trailing-drawdown amount
    profit_target: float  # flat dollar profit needed to pass
    daily_loss_limit: Optional[float] = None
    consistency_rule_pct: Optional[float] = None  # max single-day profit share of total, during eval
    min_trading_days: int = 0


#: MyFundedFutures Pro plan, $50,000 account. Confirmed by the account
#: holder 2026-08-14 (see docs/propfirm_myfundedfutures_pro_50k.md): $2,000
#: MLL, $3,000 target, no daily loss limit, 50% consistency rule, 80/20
#: split (split isn't modeled here, only compliance mechanics are).
#: ``min_trading_days`` and the MLL-trail/lock mechanic (below) are
#: ASSUMED DEFAULTs from background research, not reconfirmed — see the
#: doc's "still open" section.
MFF_PRO_50K = PropFirmRules(
    name="MyFundedFutures Pro 50K",
    starting_balance=50_000.0,
    max_loss_limit=2_000.0,
    profit_target=3_000.0,
    daily_loss_limit=None,
    consistency_rule_pct=0.5,
    min_trading_days=2,
)


@dataclass
class EvalOutcome:
    status: str  # "passed", "failed_mll", "failed_daily_loss", "in_progress"
    outcome_date: Optional[pd.Timestamp]
    days_traded: int
    final_equity: float
    max_single_day_profit: float
    total_profit: float


def check_compliance(daily_equity: pd.Series, rules: PropFirmRules) -> EvalOutcome:
    """Replay ``daily_equity`` (one EOD balance per trading day, starting
    at ``rules.starting_balance``) against ``rules`` and report the
    outcome.

    Max-loss-limit is modeled as an EOD-trailing floor that trails the
    high-water mark up but locks once the high-water mark reaches
    ``starting_balance + max_loss_limit`` (a common prop-firm mechanic;
    ASSUMED for this firm specifically, not reconfirmed — see spec doc).
    A day only counts toward ``min_trading_days`` if equity moved at all
    that day (a proxy for "a trade happened," not an exact rule read).
    """
    if daily_equity.empty:
        return EvalOutcome("in_progress", None, 0, rules.starting_balance, 0.0, 0.0)

    hwm = rules.starting_balance
    lock_point = rules.starting_balance + rules.max_loss_limit
    days_traded = 0
    profits_by_day = []
    prev_equity = rules.starting_balance

    for date, equity in daily_equity.items():
        pnl = equity - prev_equity
        prev_equity = equity
        if pnl != 0:
            days_traded += 1
            profits_by_day.append(pnl)

        if rules.daily_loss_limit is not None and pnl < -rules.daily_loss_limit:
            return EvalOutcome(
                "failed_daily_loss", date, days_traded, equity,
                max(profits_by_day, default=0.0), sum(profits_by_day),
            )

        hwm = min(max(hwm, equity), lock_point)
        floor = hwm - rules.max_loss_limit
        if equity < floor:
            return EvalOutcome(
                "failed_mll", date, days_traded, equity,
                max(profits_by_day, default=0.0), sum(profits_by_day),
            )

        total_profit = equity - rules.starting_balance
        if total_profit >= rules.profit_target and days_traded >= rules.min_trading_days:
            positive_days = [p for p in profits_by_day if p > 0]
            total_positive = sum(positive_days)
            max_day = max(positive_days, default=0.0)
            consistency_ok = (
                rules.consistency_rule_pct is None
                or total_positive <= 0
                or max_day <= rules.consistency_rule_pct * total_positive
            )
            if consistency_ok:
                return EvalOutcome("passed", date, days_traded, equity, max_day, total_profit)

    positive_days = [p for p in profits_by_day if p > 0]
    return EvalOutcome(
        "in_progress",
        daily_equity.index[-1],
        days_traded,
        float(daily_equity.iloc[-1]),
        max(positive_days, default=0.0),
        float(daily_equity.iloc[-1] - rules.starting_balance),
    )


def pass_rate(
    daily_equity: pd.Series,
    rules: PropFirmRules,
    window_days: int = 60,
    step_days: int = 5,
) -> dict:
    """Estimate a "pass %" by replaying ``rules`` against many overlapping
    windows of ``daily_equity``, each window rebased to start at
    ``rules.starting_balance`` (as if a fresh evaluation started there).

    This is a walk-forward estimate over one historical path, not a full
    Monte Carlo resample — a reasonable v1, not a claim of statistical
    robustness. Returns counts and the pass rate among windows that
    reached a definite passed/failed outcome; ``in_progress`` windows
    (the window ended before the eval resolved either way) are reported
    separately and excluded from the rate.
    """
    n = len(daily_equity)
    outcomes = []
    # Only full-length windows count as an "attempt" -- a short tail
    # window smaller than window_days isn't a complete evaluation replay.
    for start in range(0, n - window_days + 1, step_days):
        window = daily_equity.iloc[start : start + window_days]
        if window.iloc[0] == 0:
            continue
        rebased = rules.starting_balance * (window / window.iloc[0])
        outcomes.append(check_compliance(rebased, rules))

    passed = sum(1 for o in outcomes if o.status == "passed")
    failed = sum(1 for o in outcomes if o.status.startswith("failed"))
    in_progress = sum(1 for o in outcomes if o.status == "in_progress")
    resolved = passed + failed

    return {
        "attempts": len(outcomes),
        "passed": passed,
        "failed": failed,
        "in_progress": in_progress,
        "pass_rate": (passed / resolved) if resolved else None,
        "outcomes": outcomes,
    }
