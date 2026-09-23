"""Command-line entry point: run a candle strategy backtest.

Examples
--------
    # Synthetic data, composite strategy
    python -m stdvbot.cli --strategy composite --synthetic --bars 750

    # Your own CSV (date,open,high,low,close[,volume])
    python -m stdvbot.cli --strategy reversal --data prices.csv --plot equity.png
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import data as d
from .backtest import run_backtest
from .strategies import STRATEGY_REGISTRY, get_strategy


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run a candlestick-pattern strategy backtest.")
    src = p.add_mutually_exclusive_group(required=False)
    src.add_argument("--data", type=str, help="Path to an OHLCV CSV file.")
    src.add_argument(
        "--synthetic", action="store_true", default=True,
        help="Use generated synthetic data (default if --data is omitted).",
    )
    p.add_argument("--bars", type=int, default=750, help="Bars of synthetic data to generate.")
    p.add_argument("--seed", type=int, default=42, help="Synthetic data RNG seed.")
    p.add_argument(
        "--strategy", choices=sorted(STRATEGY_REGISTRY), default="composite",
        help="Which candle strategy to run.",
    )
    p.add_argument("--capital", type=float, default=10_000.0, help="Initial capital.")
    p.add_argument("--fee-bps", type=float, default=5.0, help="Fee, in basis points of notional.")
    p.add_argument("--slippage-bps", type=float, default=2.0, help="Slippage, in basis points.")
    p.add_argument("--plot", type=str, default=None, help="If set, save an equity curve PNG here.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.data:
        df = d.load_ohlcv_csv(args.data)
    else:
        df = d.generate_synthetic_ohlcv(n=args.bars, seed=args.seed)

    strategy = get_strategy(args.strategy)
    signals = strategy.generate_signals(df)
    result = run_backtest(
        df,
        signals,
        initial_capital=args.capital,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )

    print(f"Strategy: {strategy.name}  |  Bars: {len(df)}  |  Source: {args.data or 'synthetic'}")
    print("-" * 48)
    print(result.summary())
    print("-" * 48)
    if not result.trades.empty:
        print(result.trades.tail(10).to_string(index=False))
    else:
        print("No trades were generated.")

    if args.plot:
        _save_plot(result.equity_curve, args.plot)
        print(f"\nSaved equity curve to {args.plot}")

    return 0


def _save_plot(equity: pd.Series, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(equity.index, equity.values)
    ax.set_title("Equity Curve")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
