# Manipulation-Leg / Liquidity-Sweep Strategy — Spec (v1, work in progress)

This document consolidates the trading methodology as explained so far, so it
doesn't live only in chat scrollback. It is **not fully implemented yet** —
sections marked `ASSUMPTION` or `TODO` are best-effort translations of the
English explanation into precise, codeable rules, and need to be confirmed or
corrected. Code in `stdvbot/legs.py` and `stdvbot/poi.py` implements the
parts that are well-defined; the rest is deliberately left as an open
question rather than guessed into place.

## 1. Core idea

Price is often pushed deliberately in one direction around session opens to
trigger the wrong side of the market before reversing — a **manipulation
leg**. The same "sweep a level, then reverse" mechanism repeats at multiple
timeframes:

- **Daily** — a fast, impulsive daily move ("pump") tops out; that top is
  itself a retracement opportunity.
- **4H** — provides regime context (see §4) and refines daily bias.
- **Session / daily Points of Interest (POI)** — the previous session's or
  previous day's high/low. Price tends to run (sweep) these levels — taking
  out resting liquidity — before retracing the other way.
- **1-minute manipulation leg** — the same sweep-and-reverse mechanism,
  anchored specifically to session open times (Asia ~20:00, NY ~9:30, in the
  trader's local UTC-4), used for execution-level entries.

`ASSUMPTION`: these are the same underlying primitive (sweep a level →
reverse) applied recursively at different scales, rather than the 1-minute
leg logic and the higher-timeframe bias being two independent mechanisms.
**Not yet confirmed.**

## 2. Identifying a manipulation leg (1-minute)

1. Only evaluated around session open windows (Asia, NY — exact windows
   configurable; ICT-style "kill zones" are a likely source, `TODO` confirm
   exact times/zones beyond the two observed: ~20:00 and ~9:30, UTC-4).
2. **Off-trend filter:** a push at the open only counts as a manipulation
   candidate if it runs counter to the prevailing higher-timeframe bias
   (e.g., pushing up into the open during an overall bear context).
3. **Leg validity:**
   - A move formed by a **single fast candle** is suspect ("false leg") —
     it may never get revisited/confirmed.
   - A move spanning **multiple consecutive candles** (observed example: 3
     candles) is treated as the real, tradeable leg.
   - `TODO`: exact minimum candle count (2 vs 3), and whether there's an
     upper bound on how many candles still count as "one leg."

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
  `ASSUMPTION`: this formula is inferred from the observed level labels
  (-1, -2, -2.25, -2.5, -4, -4.5) and the worked example (leg up → enter
  long once price falls to strike level 2.25/2.5 below the leg's origin).
  **Not yet confirmed as the literal construction.**

- **Trade direction**: entering **opposite the manipulation leg's own
  push** — i.e., toward whatever the leg's origin implies was the "true"
  direction. Mirror case (downward leg) enters short once price rallies up
  to strike the equivalent level above.

### Confidence gradient (not a single trigger)

The levels are a **graded confidence zone**, not interchangeable triggers:

| Zone            | Grade | Behavior |
|-----------------|-------|----------|
| ~2.0 – 2.5      | "B-"  | Plausible countertrend zone; **needs additional confluence** to be a real trade. Not inherently weak or strong on its own. |
| ~4.5            | "A+"  | "Zone of no return" — near-standalone signal. Once reached, either (a) full reversal of the last price delivery, or (b) price goes stagnant and the session closes without further movement. Continuation past this point is not expected either way. |

`TODO`:
- Full list of qualifying **confluences** for the 2–2.5 zone (candidates:
  candlestick patterns already in `stdvbot/candles.py`, VWAP proximity,
  round numbers, FVGs/liquidity pools, POI confluence — not yet confirmed
  which of these actually count).
- Whether entry requires a **wick touch** or a **close through** the level.
- How the backtester should score the "stays stagnant, session closes"
  outcome at 4.5 (not a normal win/loss — currently unhandled).
- Precise grade mapping between 2.5 and 4.5 (continuum vs. discrete
  checkpoints).

## 4. Higher-timeframe context

- Timeframes used: **4H and Daily**.
- **POIs**: both session highs/lows (Asia/London/NY) *and* daily
  highs/lows — all treated the same way as sweep targets.
- **Regime**: the strategy performs better in a **ranging/consolidated**
  market than a trending one. `TODO`: confirm whether trending regime
  should fully disable entries or just reduce confidence/size, and how
  regime itself gets classified (structural range measure vs. hand-labeled
  examples).

## 5. Explicitly deferred

- **Re-entry / retest logic** at the 2.5 / 4.5 levels (whether it's an
  add-on retest in the same direction, or a failed-reversal flip into
  continuation) — deferred by the trader for a later session, not
  implemented.
- Stop-loss placement specific to this setup (general principle from
  earlier discussion: stops belong beyond the structural level that
  invalidates the idea, not a fixed percentage — exact placement for this
  strategy specifically still TBD).
- Profit target consistency (one observed example used session VWAP;
  not confirmed as the universal target).

## 6. What's implemented so far

- `stdvbot/legs.py` — leg detection within a session window, leg-validity
  classification (single-candle vs multi-candle), and inverse-Fibonacci
  level projection per §3's formula.
- `stdvbot/poi.py` — session and daily high/low tracking, and a generic
  sweep-detector (wick through a level, close back on the other side) used
  for POIs at any scale.

Neither module wires into `stdvbot/strategies.py`/`backtest.py` yet — the
open TODOs above (confluence list, regime gating, stop/target rules) need
answers before a real tradeable signal/backtest can be built on top of
these primitives without guessing.
