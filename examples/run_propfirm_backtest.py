"""Estimate a MyFundedFutures Pro 50K pass rate for a bundled strategy.

Demonstrates stdvbot.propfirm on top of the existing candlestick
strategies -- this doesn't require the manipulation-leg strategy or a live
execution pipeline to exist; it works on any backtest's daily equity
curve. Run with:  python examples/run_propfirm_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_ohlcv
from stdvbot.propfirm import MFF_PRO_50K, check_compliance, pass_rate
from stdvbot.strategies import get_strategy


def main():
    df = generate_synthetic_ohlcv(n=1500, seed=11)
    strategy = get_strategy("composite")
    signals = strategy.generate_signals(df)
    result = run_backtest(df, signals, initial_capital=MFF_PRO_50K.starting_balance)

    single = check_compliance(result.equity_curve, MFF_PRO_50K)
    print(f"Single full-history compliance check ({MFF_PRO_50K.name}):")
    print(
        f"  status={single.status} on {single.outcome_date}, "
        f"days_traded={single.days_traded}, total_profit={single.total_profit:.2f}"
    )

    stats = pass_rate(result.equity_curve, MFF_PRO_50K, window_days=60, step_days=5)
    print(
        f"\nWalk-forward pass-rate estimate over {stats['attempts']} overlapping "
        f"60-trading-day windows:"
    )
    print(
        f"  passed={stats['passed']}  failed={stats['failed']}  "
        f"in_progress={stats['in_progress']}"
    )
    if stats["pass_rate"] is not None:
        print(f"  pass_rate={stats['pass_rate']:.1%} (of resolved attempts)")
    else:
        print("  pass_rate=N/A (no windows resolved to pass or fail)")


if __name__ == "__main__":
    main()
