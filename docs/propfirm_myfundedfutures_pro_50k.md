# MyFundedFutures — Pro Plan, $50K Account — Rule Reference (future phase)

For the planned prop-firm evaluation compliance/optimization phase (after
the manipulation-leg strategy itself is finished — see
`manipulation_leg_strategy.md`). **Not yet built, no code depends on this
doc.**

Researched via web search on 2026-08-14. The MyFundedFutures domains
(`myfundedfutures.com`, `help.myfundedfutures.com`) were **not directly
fetchable** in this environment (network egress blocked them) — everything
below is compiled from third-party summaries and search-result snippets of
MFF's own help-center articles, not a direct read of the primary source.
**Confirm every number against the live MyFundedFutures dashboard before
any of this is used for a real risk decision or gets coded into
`stdvbot/propfirm.py`.**

## Researched parameters (evaluation phase, Pro plan, $50,000 account)

| Parameter | Value found | Confidence |
|---|---|---|
| Account size | $50,000 | high |
| Max drawdown | **Conflicting**: one source says 3% (~$1,500), another says a fixed $2,000 (4%), trailing floor locking once equity reaches $52,000 | **low — needs direct confirmation, this is the load-bearing constraint** |
| Drawdown type | End-of-day trailing (recalculated at day close, not intraday) | medium |
| Daily loss limit | None, evaluation or funded | medium-high (multiple sources agree) |
| Profit target | ~6% (~$3,000) | medium |
| Minimum trading days | 2 | medium |
| Consistency rule | 50% — no single day's profit may exceed 50% of total evaluation profit; drops to a qualitative "Consistent Trading Policy" once funded (no hard %) | medium |
| Profit split (funded) | 80/20 | low-medium |

## Sources
- [MyFundedFutures Rules Overview 2026 — PropTradingVibes](https://proptradingvibes.com/blog/myfundedfutures-rules-overview)
- [My Funded Futures Rules: Drawdown & Targets (2026) — TradingToolsHub](https://tradingtoolshub.com/blog/my-funded-futures-rules-explained/)
- Search-result snippets referencing MFF's own help-center articles
  (titles only, pages not fetchable here): "Consistency Rule at My Funded
  Futures," "Understanding Evaluation Parameters at MyFunded Futures,"
  "Pro Plan Sim-Funded and Live Account Highlights," "Rules: Trailing Max
  Drawdowns / Risk Parameters Explained."

## Why the drawdown discrepancy matters

Whether max drawdown is a **percentage of starting balance**, a **fixed
dollar amount**, or a value that **locks once equity crosses a
threshold** changes how the constraint gets coded in the future compliance
checker (`stdvbot/propfirm.py`, not yet started) — a percentage-of-balance
rule and a fixed-dollar rule diverge as the account grows, and a locking
rule needs its own state tracking. Get the exact current rule from the
dashboard before that module is built; don't build against a guess here.

## Where this fits in the roadmap

1. Manipulation-leg strategy (current focus) — in progress.
2. Live automation pipeline (`stdvbot/live.py`, `stdvbot/execution.py`) —
   not started.
3. **Prop-firm evaluation compliance & risk optimization** (this doc) — not
   started. Once the strategy and live pipeline exist, this phase adds a
   compliance checker (does a given trade sequence pass MFF's Pro 50K
   rules?) and an optimizer (tune risk-per-trade/sizing to maximize
   probability of passing, treating the firm's rules as hard constraints
   rather than optimizing raw return/Sharpe).
