"""CLI: fetch historical data and run backtests.

    python -m stdvbot.cli fetch --symbol BTC/USDT --since 2024-01-01T00:00:00Z --out data/btcusdt_1m.csv
    python -m stdvbot.cli backtest --data data/btcusdt_1m.csv --config config/default.yaml
"""
from __future__ import annotations

import argparse
import sys

from .backtest import run_backtest
from .config import StrategyConfig
from .data import fetch_ohlcv_ccxt, load_ohlcv_csv
from .strategy import generate_signals


def cmd_fetch(args: argparse.Namespace) -> None:
    df = fetch_ohlcv_ccxt(
        symbol=args.symbol,
        timeframe=args.timeframe,
        since=args.since,
        exchange_id=args.exchange,
    )
    df.to_csv(args.out)
    print(f"Wrote {len(df)} bars to {args.out}")


def cmd_backtest(args: argparse.Namespace) -> None:
    config = StrategyConfig.from_yaml(args.config) if args.config else StrategyConfig()
    base_df = load_ohlcv_csv(args.data)
    signals = generate_signals(base_df, config)
    result = run_backtest(signals, config, initial_equity=args.equity)

    summary = result.summary()
    print("=== Backtest summary ===")
    for key, value in summary.items():
        print(f"{key:>18}: {value}")

    if args.trades_out:
        import pandas as pd

        pd.DataFrame([t.__dict__ for t in result.trades]).to_csv(args.trades_out, index=False)
        print(f"Wrote {len(result.trades)} trades to {args.trades_out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stdvbot")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch public OHLCV history via ccxt")
    fetch_p.add_argument("--symbol", required=True, help="e.g. BTC/USDT")
    fetch_p.add_argument("--timeframe", default="1m")
    fetch_p.add_argument("--since", required=True, help="ISO8601, e.g. 2024-01-01T00:00:00Z")
    fetch_p.add_argument("--exchange", default="binance")
    fetch_p.add_argument("--out", required=True)
    fetch_p.set_defaults(func=cmd_fetch)

    bt_p = sub.add_parser("backtest", help="Run the strategy backtest on a CSV of OHLCV data")
    bt_p.add_argument("--data", required=True, help="Path to base-timeframe OHLCV CSV")
    bt_p.add_argument("--config", default=None, help="Path to a YAML strategy config")
    bt_p.add_argument("--equity", type=float, default=10_000.0)
    bt_p.add_argument("--trades-out", default=None, help="Optional CSV path to dump trade log")
    bt_p.set_defaults(func=cmd_backtest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
