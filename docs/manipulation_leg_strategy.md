# Manipulation-Leg / Liquidity-Sweep Strategy — Spec (v1, work in progress)

This document consolidates the trading methodology as explained so far, so it
doesn't live only in chat scrollback. It is **not fully implemented yet** —
sections marked `TODO` are genuinely open; sections marked `ASSUMED DEFAULT`
are deliberate choices made to keep a fully-autonomous design moving (per
the trader's direction: full automation, no human input at trade time, WIP
so assumptions are fine for now) and can be corrected later without
architectural rework. Code in `stdvbot/legs.py` and `stdvbot/poi.py`
implements the parts that are well-defined.

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
   "false" leg; more than 5 is no longer treated as one leg.

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

- **Trade direction**: entering **opposite the manipulation leg's own
  push** — i.e., toward whatever the leg's origin implies was the "true"
  direction. Mirror case (downward leg) enters short once price rallies up
  to strike the equivalent level above.

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

## 5. Autonomous operation (confirmed target: full automation, no human input at trade time)

`ASSUMED DEFAULT`s locked in to make this operable end-to-end without a
human decision point (see chat log for full reasoning — summarized here):

- **Position sizing**: risk 1% of account equity per trade; contract count
  derived from `risk_amount / stop_distance` using instrument tick specs.
- **Instrument**: MNQ (Micro E-mini Nasdaq-100) — `MNQ_TICK_SIZE = 0.25`,
  `MNQ_TICK_VALUE = 0.50` (i.e. $2.00/point). Encoded in `stdvbot/legs.py`.
- **Max concurrent positions**: 1.
- **Daily loss circuit breaker**: halt new entries for the rest of the day
  once daily loss exceeds 3% of account equity.
- **Stop**: beyond the next fib tier out from the entry level.
- **Target**: session VWAP; if VWAP has already been passed by entry time,
  switch to the nearest opposing POI.
- **Stagnation handling** (the "closes flat" 4.5 outcome): auto-close at
  market 30 minutes past session close if neither stop nor target has hit.
- **Fail-safe**: on data feed or broker connectivity loss, auto-flatten any
  open position and halt new entries until connectivity is confirmed
  restored.
- **Logging**: every decision — trades taken *and* setups auto-skipped, with
  reason — gets logged, since no human is approving trades in real time.

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

## 8. What's implemented so far

- `stdvbot/legs.py` — leg detection within a session window, the confirmed
  3-5 candle validity rule, inverse-Fibonacci level projection, killzone
  config (Asia/NY only), and MNQ contract specs.
- `stdvbot/poi.py` — session and daily high/low tracking, and a generic
  sweep-detector (wick through a level, close back on the other side) used
  for POIs at any scale.

**Not yet built**: the autonomous decision/execution pipeline described in
§5 (confluence scoring, regime gating, risk/position sizing, order
placement, trade management, safety loop) — i.e. `stdvbot/live.py` and
`stdvbot/execution.py` don't exist yet. Also not built: applying
`detect_leg`/`inverse_fib_levels` to resampled 4H/Daily bars for the
higher-timeframe bias read described in §1 (the primitives support it, but
nothing calls them that way yet).
