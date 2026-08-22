# Manipulation-Leg / Liquidity-Sweep Strategy — Spec (v1, work in progress)

This document consolidates the trading methodology as explained so far, so it
doesn't live only in chat scrollback. It is **not fully implemented yet** —
sections marked `TODO` are genuinely open; sections marked `ASSUMED DEFAULT`
are deliberate choices made to keep the design moving without blocking on
every open question, and can be corrected later without architectural
rework. Code in `stdvbot/legs.py` and `stdvbot/poi.py` implements the parts
that are well-defined.

**Automation level — superseded, see §5**: earlier phases of this project
targeted full automation with no human input at trade time. That's been
replaced with a **semi-automatic** design (bot proposes, human confirms
entry/exit) — see §5 for why and what it changes.

## 1. Core idea

Price is often pushed deliberately in one direction around session opens to
trigger the wrong side of the market before reversing — a **manipulation
leg**. The same "sweep a level, then reverse" mechanism repeats at multiple
timeframes, and — **confirmed** — it's the literal same primitive at every
scale, not separate mechanisms:

- **Daily / 4H** — a fast, impulsive move ("pump") tops out; that top is
  itself a retracement opportunity. This *is* higher-timeframe bias: running
  `detect_leg()` / `inverse_fib_levels()` (see §2-3) on Daily or 4H bars
  finds the "top of the fast pump" and its retracement zone exactly the same
  way as the 1-minute case. There is no separate trend-direction indicator —
  only the timeframe of the input data changes.
- **Session / daily Points of Interest (POI)** — the previous session's or
  previous day's high/low. Price tends to run (sweep) these levels — taking
  out resting liquidity — before retracing the other way.
- **1-minute manipulation leg** — the same sweep-and-reverse mechanism,
  anchored specifically to session open times, used for execution-level
  entries.

## 2. Identifying a manipulation leg

1. **Killzones in scope — confirmed**: Asia (20:00 local UTC-4) and NY
   (09:30 local UTC-4) only. **London is explicitly excluded** — not traded.
   `DEFAULT_KILLZONES` in `stdvbot/legs.py` encodes this.
2. **Leg-detection window**: `ASSUMED DEFAULT` — 6 minutes from the session
   open, sized to comfortably observe up to the confirmed max leg length
   (see #3) plus one bar of confirmation that it stopped extending.
3. **Off-trend filter:** a push at the open only counts as a manipulation
   candidate if it runs counter to the prevailing higher-timeframe bias (the
   Daily/4H leg read from §1) — e.g., pushing up into the open while the
   Daily/4H leg implies a bearish retracement is still in play.
4. **Leg validity — confirmed**: a leg must span **3 to 5 continuous
   candles** (`MIN_LEG_CANDLES`/`MAX_LEG_CANDLES` in `stdvbot/legs.py`), 3
   being typical. Fewer (typically a single fast candle) is a suspect
   "false" leg; more than 5 is no longer treated as one leg. **This range
   is specific to 1-minute killzone legs** — `stdvbot/manipulation_leg_strategy.py`'s
   daily-bias read (§1) deliberately does *not* apply it (a "fast pump"
   peaking within the first 3-5 *days* of a lookback window is far too
   strict and left bias undefined almost everywhere in testing).

## 3. Inverse Fibonacci projection & entries

Given a validated leg with an **origin** (start price) and **extreme**
(furthest point reached):

- The leg range is `R = |extreme - origin|`.
- Levels are projected **past the origin, in the direction opposite the
  leg** (hence "inverse" — not a retracement back into the leg, an
  extension beyond its start):

  ```
  upward leg (origin < extreme):   level(m) = origin - m * R   (levels below origin)
  downward leg (origin > extreme): level(m) = origin + m * R   (levels above origin)
  ```

  where `m` is a level multiple, observed grid: `1, 2, 2.25, 2.5, 4, 4.5`.
  This formula is inferred from observed level labels and a worked example
  and has not been explicitly contradicted since — treated as confirmed
  pending any correction.

- **Trade direction — CORRECTED**: entering in the **same direction as the
  leg's own push** (an up leg leads to a long entry, a down leg to a
  short), confirmed directly from the worked example verbatim ("manipulates
  higher... mark a lower fib... once it strikes 2.5 you enter a long" — an
  *up* leg leading to a *long* entry). An earlier version of this doc said
  "opposite the leg," which was wrong — that language describes the
  intermediate retrace move that carries price down to the fib zone, not
  the trade actually taken. Caught while wiring `stdvbot/manipulation_leg_strategy.py`
  — flagging loudly since getting this backwards means systematically
  wrong-way trades. The higher-timeframe bias (§2.3) is only an off-trend
  *filter* for which legs qualify as manipulation; it does not itself set
  the trade direction — the leg does.

### Confidence gradient (not a single trigger)

| Zone            | Grade | Behavior |
|-----------------|-------|----------|
| ~2.0 – 2.5      | "B-"  | Plausible countertrend zone; **needs additional confluence** to be a real trade. |
| ~4.5            | "A+"  | "Zone of no return" — near-standalone signal. Once reached, either (a) full reversal of the last price delivery, or (b) price goes stagnant and the session closes without further movement. |

`ASSUMED DEFAULT` (autonomous confluence check, since there's no human to
judge "does this look right"): score = count of these booleans passing —
(a) a candlestick reversal pattern from `stdvbot/candles.py` fires on the
touching candle, (b) price is within a configurable tolerance of session
VWAP, (c) price is within a configurable tolerance of a round number, (d)
price aligns with a POI (§4). In the B- zone, require score ≥ 2 to act; in
"A+ only" mode (§4 regime gating) the B- zone is skipped regardless of
score. At 4.5, act automatically, no confluence required.

`ASSUMED DEFAULT`: entry triggers on a **wick touch** of the level (not
requiring a close through).

`TODO`: precise grade mapping between 2.5 and 4.5 (continuum vs. discrete
checkpoints) — currently linear interpolation via `zone_grade()`.

## 4. Higher-timeframe context

- Timeframes used: **4H and Daily** (see §1 — same leg primitive).
- **POIs**: both session highs/lows (Asia/NY — London excluded per §2) *and*
  daily highs/lows — all treated the same way as sweep targets.
- **Regime — confirmed preference, gating rule assumed**: the strategy
  performs better in a **ranging/consolidated** market. `ASSUMED DEFAULT`:
  hard gate — on a trending 4H day, only 4.5-grade ("A+") touches are
  eligible; the 2.0-2.5 zone is skipped entirely for the whole day,
  regardless of confluence score.

## 5. Autonomous operation — **UPDATED: semi-automatic, not fully unattended**

**Superseded decision**: this section originally targeted full automation
with no human input at trade time (the trader's initial WIP direction, to
keep design moving without blocking on every open question). Two things
changed that:

1. Researching live-execution options surfaced that MyFundedFutures
   updated its policy on **2025-07-23** to explicitly permit algorithmic
   trading / third-party automation on both evaluation and live funded
   accounts — but per third-party summaries of that policy (MFF's own
   domains are unreachable from this environment — **re-verify directly
   against MFF's rules/support before relying on this**), traders must
   *actively supervise* entries/exits rather than run fully unattended.
2. Given that, the trader chose **semi-automatic** operation going
   forward: the bot detects setups and stages the trade (direction, entry
   level, stop, target) but a human confirms before it's actually placed
   — not the fully autonomous design originally assumed.

This changes the target design for `stdvbot/live.py` (still not built):
it becomes a *setup-staging + confirmation* flow, not a
detect-and-place-automatically flow. Everything below this line describes
what's still assumed for the parts semi-auto doesn't change (sizing,
stops, targets, fail-safes) — the delta is *who* pulls the trigger on
entry/exit, not how the setup is computed.

`ASSUMED DEFAULT`s (see chat log for full reasoning — summarized here):

- **Position sizing**: risk 1% of account equity per trade; contract count
  derived from `risk_amount / stop_distance` using instrument tick specs.
  (Flagged elsewhere as likely too aggressive against the $2,000 MLL —
  revisit before going live; the risk-sweep example already compares
  0.25%/0.5%/1%.)
- **Instrument**: MNQ (Micro E-mini Nasdaq-100) — `MNQ_TICK_SIZE = 0.25`,
  `MNQ_TICK_VALUE = 0.50` (i.e. $2.00/point). Encoded in `stdvbot/legs.py`.
- **Max concurrent positions**: 1.
- **Daily loss circuit breaker**: halt new entries for the rest of the day
  once daily loss exceeds 3% of account equity. Still auto-enforced even
  in semi-auto mode — it stops *proposing* new setups, it doesn't need a
  human to approve a halt.
- **Stop**: beyond the next fib tier out from the entry level.
- **Target**: session VWAP; if VWAP has already been passed by entry time,
  switch to the nearest opposing POI.
- **Stagnation handling** (the "closes flat" 4.5 outcome): stage an
  auto-close proposal at market 30 minutes past session close if neither
  stop nor target has hit — still needs confirmation like any other exit
  in semi-auto mode, but is time-sensitive enough to page/alert loudly
  rather than wait passively.
- **Fail-safe**: on data feed or broker connectivity loss, auto-flatten any
  open position and halt new setup proposals until connectivity is
  confirmed restored. This one stays fully automatic even in semi-auto
  mode — a human isn't in a position to confirm anything during a
  connectivity loss, and flattening is the safe default.
- **Logging**: every decision — setups proposed, confirmed, skipped by the
  human, or auto-skipped by a filter, with reason — gets logged.

## 6. Explicitly deferred

- **Re-entry / retest logic** at the 2.5 / 4.5 levels — deferred by the
  trader for a later session, not implemented.

## 7. Infrastructure — open, not a strategy question

- **Data feed / broker**: Tradovate, for both live market data and order
  execution. **Setup not yet done** — the trader doesn't yet know how to
  configure Tradovate API access. Needs: registering a Tradovate developer
  app, obtaining API credentials, deciding demo vs. live environment, and
  wiring up their REST/WebSocket API for both market data and order
  placement. This blocks real live operation but not further code
  scaffolding.
- **Considered and rejected: ProjectX Gateway API.** Real, documented API
  (`gateway.docs.projectx.com`) offering L1/L2 data and order execution
  over a REST + SignalR (WebSocket) interface — but its official SDK
  states it works "exclusively with TopStepX ProjectX Gateway API," and
  MyFundedFutures' listed approved platforms (Tradovate, NinjaTrader,
  Rithmic R|Trader Pro, Sierra Chart, Quantower, ATAS, Jigsaw Trading) do
  not include it. Hooking this up would connect to a TopStep account's
  data/orders, not the MFF account this project is built against. Not
  ruled out permanently — if the trader opens a TopStep account
  separately, this becomes relevant again — but Tradovate stays the
  integration target for the current MFF account.
- **MFF algo-trading policy**: per third-party summaries (MFF's own
  domains aren't reachable from this environment to confirm firsthand),
  MFF updated its rules on 2025-07-23 to permit algorithmic
  trading/automation on both evaluation and live funded accounts, subject
  to active supervision of entries/exits — this is what drove the
  semi-automatic design in §5. **Re-verify this directly with MFF support
  or their help center before relying on it operationally.**

## 8. What's implemented so far

- `stdvbot/legs.py` — leg detection within a session window, the confirmed
  3-5 candle validity rule, inverse-Fibonacci level projection, killzone
  config (Asia/NY only), and MNQ contract specs.
- `stdvbot/poi.py` — session and daily high/low tracking, and a generic
  sweep-detector (wick through a level, close back on the other side) used
  for POIs at any scale.
- `stdvbot/manipulation_leg_strategy.py` — **the strategy is wired
  end-to-end** and runs through the real backtester
  (`stdvbot.backtest.run_backtest`), registered as `"manipulation_leg"` in
  `stdvbot/strategies.py`. Per killzone: reads daily bias and regime from
  data before that day, detects a leg, keeps it only if valid and
  off-trend vs. bias, projects inverse-Fib levels, gates them by regime,
  watches for a touch (confluence-gated below 4.5, currently just a
  matching-direction candlestick pattern — VWAP/round-number/POI
  confluence checks from §3's `ASSUMED DEFAULT` aren't wired in yet), and
  manages the resulting trade to stop/target/timeout. See the module's
  docstring for the trade-direction correction (§3) and other
  simplifications made while wiring it up. Demonstrated against synthetic
  1-minute data (and pluggable to real 1-minute CSV data) in
  `examples/run_manipulation_leg_backtest.py`.
- `stdvbot/data.py` gained `generate_synthetic_intraday_ohlcv()` — 1-minute
  synthetic OHLCV so this strategy (which needs intraday, killzone-aligned
  timestamps, unlike the daily-bar candlestick strategies) has something
  to run against offline.

**Not yet built**: the autonomous *live/unattended* execution pipeline
described in §5 (position sizing from account equity, the daily-loss
circuit breaker, order placement against a real broker, the connectivity
fail-safe, decision logging) — `stdvbot/live.py` and
`stdvbot/execution.py` don't exist yet. What exists today is a
**backtestable strategy**, not a live-trading bot — those are different
projects sharing the same signal logic. Also not wired in: POIs (§4) as
targets/confluence, and the full 4-factor confluence score (currently
just the candlestick-pattern check).
