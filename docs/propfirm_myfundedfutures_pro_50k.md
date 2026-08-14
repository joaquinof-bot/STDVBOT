# MyFundedFutures — Pro Plan, $50K Account — Rule Reference

For the prop-firm evaluation compliance/optimization phase. Compliance
checking (`stdvbot/propfirm.py`) is built and tested against the numbers
below — it did not end up needing to wait for the manipulation-leg
strategy or live pipeline (see `manipulation_leg_strategy.md`); it works
on any backtest's equity curve. The optimizer layer (tuning risk/sizing
to maximize pass rate) is still not built.

## Confirmed parameters (from the account holder, 2026-08-14)

| Parameter | Value | Source |
|---|---|---|
| Account size | $50,000 | confirmed |
| Max Loss Limit (max drawdown) | **$2,000 flat** | confirmed — resolves the earlier 3%-vs-$2,000 discrepancy in favor of the flat dollar figure |
| Daily loss limit | None | confirmed |
| Profit target | $3,000 | confirmed |
| Consistency rule | 50% — no single day's profit may exceed 50% of total evaluation profit | confirmed |
| Profit split (funded) | 80/20 | confirmed |

## Still open / lower priority

- **Drawdown mechanics**: whether the $2,000 MLL trails equity intraday,
  trails only at end-of-day, or locks once equity crosses a threshold
  (earlier research suggested EOD-trailing with a lock around $52,000
  equity) — not yet re-confirmed against the flat-dollar figure above.
  Matters for exactly how `stdvbot/propfirm.py` tracks the floor, but
  doesn't block getting started.
- **Minimum trading days**: researched as 2, not explicitly reconfirmed.
- **Algorithmic/automated trading permission**: not yet confirmed whether
  MyFundedFutures' current ruleset for this evaluation type permits
  algorithmic trading at all — this is a fact only the account holder (or
  MFF support) can confirm, not something research can settle. Worth
  checking before betting the full-automation plan (see
  `manipulation_leg_strategy.md` §5) on this account.

## Sources
- Primary: account holder, direct confirmation (2026-08-14).
- Background research (superseded above where they conflicted):
  [MyFundedFutures Rules Overview 2026 — PropTradingVibes](https://proptradingvibes.com/blog/myfundedfutures-rules-overview),
  [My Funded Futures Rules: Drawdown & Targets (2026) — TradingToolsHub](https://tradingtoolshub.com/blog/my-funded-futures-rules-explained/).
  `myfundedfutures.com`/`help.myfundedfutures.com` were not directly
  fetchable in this environment (network egress blocked them).

## Where this fits in the roadmap

1. Manipulation-leg strategy — in progress.
2. Live automation pipeline (`stdvbot/live.py`, `stdvbot/execution.py`) —
   not started.
3. **Prop-firm evaluation compliance & risk optimization** — **compliance
   checking started** (`stdvbot/propfirm.py`): `check_compliance()`
   replays a daily equity curve against these rules and reports
   passed/failed_mll/failed_daily_loss/in_progress; `pass_rate()` gets a
   walk-forward "pass %" by replaying the rules across many overlapping
   windows of a longer equity history (a walk-forward estimate over one
   historical path, not a full Monte Carlo resample — see the module
   docstring). Demonstrated end-to-end against the existing `composite`
   candlestick strategy in `examples/run_propfirm_backtest.py` — this
   doesn't need the manipulation-leg strategy or live pipeline to exist,
   it works on any backtest's equity curve today.
   **Not yet built**: the optimizer layer (tune risk-per-trade/sizing to
   maximize pass rate as the actual objective, rather than reading a
   pass rate off a strategy that wasn't tuned for it).
