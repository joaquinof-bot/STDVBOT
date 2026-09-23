"""Run the manipulation-leg strategy through the real backtester.

Uses synthetic 1-minute data by default (offline, deterministic). Point
it at real 1-minute OHLCV data instead with --data, e.g. real MNQ history
exported from your broker/data provider:

    python examples/run_manipulation_leg_backtest.py --data mnq_1min.csv

See stdvbot/manipulation_leg_strategy.py's module docstring for what's
confirmed vs. assumed in this strategy, including a correction made to
the spec doc's trade-direction description while wiring this up.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stdvbot.backtest import run_backtest
from stdvbot.data import generate_synthetic_intraday_ohlcv, load_ohlcv_csv
from stdvbot.strategies import get_strategy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=str, default=None, help="1-minute OHLCV CSV path")
    parser.add_argument("--days", type=int, default=180, help="synthetic days if --data omitted")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--capital", type=float, default=50_000.0)
    args = parser.parse_args()

    if args.data:
        df = load_ohlcv_csv(args.data)
    else:
        df = generate_synthetic_intraday_ohlcv(n_days=args.days, seed=args.seed)

    strategy = get_strategy("manipulation_leg")
    signals = strategy.generate_signals(df)
    result = run_backtest(df, signals, initial_capital=args.capital)

    print(f"Strategy: {strategy.name}  |  Bars: {len(df)}  |  Source: {args.data or 'synthetic'}")
    print("-" * 48)
    print(result.summary())
    print("-" * 48)
    if not result.trades.empty:
        print(result.trades.to_string(index=False))
    else:
        print("No trades were generated.")


if __name__ == "__main__":
    main()
