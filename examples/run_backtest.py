"""Compare all bundled candle strategies on synthetic data.

Run with:  python examples/run_backtest.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_ohlcv
from stdvbot.strategies import STRATEGY_REGISTRY, get_strategy


def main():
    df = generate_synthetic_ohlcv(n=1000, seed=7)

    rows = []
    for name in STRATEGY_REGISTRY:
        strategy = get_strategy(name)
        signals = strategy.generate_signals(df)
        result = run_backtest(df, signals)
        rows.append({"strategy": name, **result.stats})

    summary = pd.DataFrame(rows).set_index("strategy")
    pd.set_option("display.width", 120)
    print(summary)


if __name__ == "__main__":
    main()
