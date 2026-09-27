"""Compare the manipulation-leg engine (v1/v2) against the PO3 and IPDA
Standard Deviation strategies on the same 1-minute data, in MNQ terms.

    python examples/compare_stdv_strategies.py --data glbx-mdp3-...ohlcv-1m.csv

Accepts either a raw Databento parent-symbology CSV (``ts_event``/``symbol``
columns -- rolled and back-adjusted on load) or a clean ``date,open,high,
low,close,volume`` CSV.

Per-trade P&L is 1 MNQ contract ($2/point) from the backtester's trade
prices -- bar-close fills for every strategy, so relative comparisons are
fair, but absolute results are optimistic versus live execution (no stop
slippage, no queue position). Commission is a flat per-round-turn
assumption, not the backtester's %-of-notional cost model, which doesn't
fit point-valued futures.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stdvbot import ipda_strategy, po3_strategy  # noqa: E402
from stdvbot.backtest import run_backtest  # noqa: E402
from stdvbot.data import load_databento_parent_ohlcv_csv, load_ohlcv_csv  # noqa: E402
from stdvbot.legs import MNQ_TICK_SIZE, MNQ_TICK_VALUE  # noqa: E402
from stdvbot.strategies import get_strategy  # noqa: E402

POINT_VALUE = MNQ_TICK_VALUE / MNQ_TICK_SIZE


def load(path: str) -> pd.DataFrame:
    head = pd.read_csv(path, nrows=1)
    cols = {c.strip().lower() for c in head.columns}
    if {"ts_event", "symbol"} <= cols:
        return load_databento_parent_ohlcv_csv(path)
    return load_ohlcv_csv(path)


def trade_table(df, signals, commission):
    trades = run_backtest(df, signals, fee_bps=0.0, slippage_bps=0.0).trades
    if trades.empty:
        return trades
    t = trades.copy()
    side = t["side"].map({"long": 1, "short": -1})
    t["points"] = (t["exit_price"] - t["entry_price"]) * side
    t["gross"] = t["points"] * POINT_VALUE
    t["net"] = t["gross"] - commission
    return t


def summarize(name, t, weeks):
    if t.empty:
        return {"strategy": name, "trades": 0}
    wins, losses = t[t["net"] > 0], t[t["net"] <= 0]
    equity = t["net"].cumsum()
    daily = t.groupby(pd.to_datetime(t["entry_time"]).dt.date)["net"].sum()
    total = t["net"].sum()
    return {
        "strategy": name,
        "trades": len(t),
        "per_week": round(len(t) / weeks, 1),
        "win_rate": round(len(wins) / len(t), 3),
        "profit_factor": round(wins["net"].sum() / -losses["net"].sum(), 2) if losses["net"].sum() else float("inf"),
        "gross_$": round(t["gross"].sum(), 2),
        "net_$": round(total, 2),
        "expect_$/trade": round(total / len(t), 2),
        "avg_win_$": round(wins["net"].mean(), 2) if len(wins) else 0.0,
        "avg_loss_$": round(losses["net"].mean(), 2) if len(losses) else 0.0,
        "max_dd_$": round((equity.cummax().clip(lower=0) - equity).max(), 2),
        "best_day/total": round(daily.max() / total, 2) if total > 0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True)
    parser.add_argument("--commission", type=float, default=1.24, help="$ per MNQ round turn")
    args = parser.parse_args()

    df = load(args.data)
    weeks = (df.index[-1] - df.index[0]).days / 7
    print(f"Data: {len(df):,} bars, {df.index[0]} -> {df.index[-1]} ({weeks:.1f} weeks)")
    print(f"1 MNQ contract, ${POINT_VALUE:.2f}/pt, ${args.commission:.2f}/round turn\n")

    runs = {
        "manipulation_leg (v1)": get_strategy("manipulation_leg").generate_signals(df),
        "manipulation_leg_v2": get_strategy("manipulation_leg_v2").generate_signals(df),
    }
    po3_pos, po3_log = po3_strategy.run(df)
    runs["po3_stdv (SBZ-nested FVG)"] = po3_pos
    runs["po3_stdv (any IRL after SBZ)"] = po3_strategy.run(df, entry_mode="any_irl")[0]
    ipda_pos, ipda_log = ipda_strategy.run(df)
    runs["ipda_stdv (both profiles)"] = ipda_pos

    tables = {name: trade_table(df, sig, args.commission) for name, sig in runs.items()}
    summary = pd.DataFrame([summarize(n, t, weeks) for n, t in tables.items()])
    with pd.option_context("display.width", 250, "display.max_columns", None):
        print(summary.to_string(index=False))

        mid = df.index[0] + (df.index[-1] - df.index[0]) / 2
        print(f"\nStability: net $ by half (split at {mid.date()})")
        halves = []
        for n, t in tables.items():
            if t.empty:
                continue
            first = pd.to_datetime(t["entry_time"]) < mid
            halves.append({"strategy": n, "1st_half_$": round(t.loc[first, "net"].sum(), 2),
                           "1st_n": int(first.sum()), "2nd_half_$": round(t.loc[~first, "net"].sum(), 2),
                           "2nd_n": int((~first).sum())})
        print(pd.DataFrame(halves).to_string(index=False))

        for label, log, t in (("ipda_stdv by profile", ipda_log, tables["ipda_stdv (both profiles)"]),
                              ("po3_stdv by 4H candle", po3_log, tables["po3_stdv (SBZ-nested FVG)"])):
            # Strategy logs and backtester trades line up one-to-one (the
            # strategies always leave a flat bar between trades).
            if not log or len(log) != len(t):
                continue
            key = "profile" if "profile" in log[0] else "candle"
            tags = pd.Series([row[key] for row in log])
            if key == "candle":
                tags = pd.to_datetime(tags).dt.strftime("%H:00")
            g = t.assign(tag=tags.to_numpy()).groupby("tag")["net"]
            out = pd.DataFrame({"trades": g.size(), "win_rate": g.apply(lambda s: round((s > 0).mean(), 3)),
                                "net_$": g.sum().round(2)})
            print(f"\n{label}:")
            print(out.to_string())


if __name__ == "__main__":
    main()
