"""Compare pass rate across a few risk-per-trade levels.

Caveat, read before trusting a number: neither the candlestick strategies
nor stdvbot.backtest.run_backtest() have real stop-distance-based position
sizing wired up yet -- no strategy defines a stop, so there's no dollar
risk-per-trade to size against directly. This sweep instead scales the
composite strategy's position size proportionally (1% risk = the
reference full +-1 position, 0.5% = half size, 0.25% = quarter size) as a
proxy for "does trading smaller help the pass rate." That's a legitimate
question to ask, but it is not a true risk-per-trade backtest -- that
needs the manipulation-leg strategy's stop logic, which isn't built yet.

Run with:  python examples/run_propfirm_risk_sweep.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_ohlcv
from stdvbot.propfirm import MFF_PRO_50K, check_compliance, pass_rate
from stdvbot.strategies import get_strategy

REFERENCE_RISK_PCT = 0.01  # the existing +-1 position is treated as "1% risk"
RISK_LEVELS = [0.0025, 0.005, 0.01]


def main():
    df = generate_synthetic_ohlcv(n=1500, seed=11)
    strategy = get_strategy("composite")
    base_signals = strategy.generate_signals(df)

    rows = []
    for risk_pct in RISK_LEVELS:
        scale = risk_pct / REFERENCE_RISK_PCT
        scaled_signals = base_signals * scale
        result = run_backtest(df, scaled_signals, initial_capital=MFF_PRO_50K.starting_balance)

        single = check_compliance(result.equity_curve, MFF_PRO_50K)
        stats = pass_rate(result.equity_curve, MFF_PRO_50K, window_days=60, step_days=5)

        rows.append(
            {
                "risk_pct": f"{risk_pct:.2%}",
                "position_scale": f"{scale:.2f}x",
                "single_run_status": single.status,
                "single_run_profit": round(single.total_profit, 2),
                "attempts": stats["attempts"],
                "passed": stats["passed"],
                "failed": stats["failed"],
                "in_progress": stats["in_progress"],
                "pass_rate": (
                    f"{stats['pass_rate']:.1%}" if stats["pass_rate"] is not None else "N/A"
                ),
            }
        )

    summary = pd.DataFrame(rows).set_index("risk_pct")
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    print(
        "Position-size-scaling proxy for risk-per-trade (NOT a true "
        "stop-based risk model -- see module docstring):\n"
    )
    print(summary)


if __name__ == "__main__":
    main()
