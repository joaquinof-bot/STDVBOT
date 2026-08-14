# MyFundedFutures — Pro Plan, $50K Account — Rule Reference (future phase)

For the planned prop-firm evaluation compliance/optimization phase (after
the manipulation-leg strategy itself is finished — see
`manipulation_leg_strategy.md`). **Not yet built, no code depends on this
doc.**

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

1. Manipulation-leg strategy (current focus) — in progress.
2. Live automation pipeline (`stdvbot/live.py`, `stdvbot/execution.py`) —
   not started.
3. **Prop-firm evaluation compliance & risk optimization** (this doc) — not
   started. Once the strategy and live pipeline exist, this phase adds a
   compliance checker (does a given trade sequence pass MFF's Pro 50K
   rules?) and an optimizer (tune risk-per-trade/sizing to maximize
   probability of passing, treating the firm's rules — $2,000 MLL, $3,000
   target, 50% consistency rule, no DLL — as hard constraints rather than
   optimizing raw return/Sharpe).
