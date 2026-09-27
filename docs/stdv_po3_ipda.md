# PO3 + IPDA Standard Deviation strategies — translation & comparison

Source PDFs (po3trader, crediting ICT / TraderDext3r): **"Standard Deviation +
Power of Three"** and **"Liquidity Profiles + Standard Deviation Theory"**
(IPDA data ranges). Code: `stdvbot/stdv.py` (shared), `stdvbot/po3_strategy.py`
(`po3_stdv`), `stdvbot/ipda_strategy.py` (`ipda_stdv`),
`stdvbot/killzone_po3_strategy.py` (`killzone_po3`, v1 legs + PO3 entries). The manipulation-leg
strategies (`manipulation_leg`, `manipulation_leg_v2`) are untouched.

## 1. How the PDFs relate to our existing engine

| | Our engine (v1/v2) | PDFs |
|---|---|---|
| Fib / "STDV" math | `inverse_fib_levels`: `start + m × range`, past the leg's start, opposite the leg | **Identical.** PDF Fib tool: 1 on the leg's extreme, 0 on its start, levels −1…−4. Pinned by `tests/test_stdv.py`. |
| Level grid | 1, 2, 2.25, 2.5, 4, **4.5** ("A+") | 1, **1.5**, 2, 2.5, **4** ("terminus"). 1–1.5 = Silver Bullet Zone (not in ours); our A+ 4.5 sits *past* the PDFs' terminus. |
| Fade direction at 2–2.5 | Same direction as the projecting leg | Same — consistent with our corrected direction rule. |
| Also trades *toward* the zone? | No | Yes — PO3 targets 2–2.5 (4 on a strong close) after the MSS. |
| Where the leg comes from | First 6 min after 09:30 / 20:00, 3–5 one-minute candles (or a "pivotal" big one) | PO3: last swing of the manipulation before the MSS, inside a 4H candle, 5m chart. IPDA: the leg into the extreme of the prior 12h dealing range. |
| Anchor times | Session opens 09:30, 20:00 | 4H candle opens 02/06/10/14/18/22 (our 09:30 NY open sits inside the 06:00 candle). |
| Confirmation | Wick touch; candlestick pattern below A+ | MSS; HTF POI nested in 2–2.5; SMT divergence vs. the Dow. |
| Targets | Session VWAP, else 2R | PO3: 2.5 (→ 4). IPDA: EQ of the dealing range (reversal) or the far range extreme (continuation). |

## 2. `po3_stdv` — what's from the PDF vs. assumed

From the PDF: 4H PO3 read on 5m; manipulation = price trades against the
candle open first (OLHC / OHLC); MSS through the last swing before the
manipulation extreme confirms it; STDV off that last leg; entry on a retrace
to internal range liquidity (an FVG) nested in the 1–1.5 SBZ (the PDF's
"higher probability" scenario — `entry_mode="any_irl"` is its first
scenario); target 2–2.5, extending to 4 on a strong close above 2.5.

`ASSUMED DEFAULT`s: swings = 5m pivots, 2 bars each side; the MSS swing may
sit up to 1h before the candle open; stop 1 tick beyond the manipulation
extreme; "strong close above 2.5" = the 1m bar that reaches 2.5 closes beyond
it (then stop → 2.0, target → 4); entries only within the candle, one trade
per candle; 4h max hold.

**Not implemented:** HTF POI and SMT divergence (needs ES/YM data) — the PDF
treats both as part of confirming the manipulation is done.

## 3. `ipda_stdv` — what's from the PDF vs. assumed

From the PDF: intraday 12h lookback = 3 × 4H candles at the index-futures
boundaries; dealing range + equilibrium; STDV off the range's most
discernible leg; zones 1–1.5 / 2–2.5 / 2.5–4 / 4 terminus; the two profiles —
reversal/retracement at 2–2.5 when price fails to close strongly above 2.5
(target EQ), and continuation from internal range liquidity on the
discount/premium side (target external range liquidity).

`ASSUMED DEFAULT`s: IOF = bullish if the range low came before the range
high (the PDF reads IOF by eye from higher timeframes); discernible leg = from
the last 5m pivot before the range extreme; reversal trigger = 5m close back
inside 2.0 (or back inside 4 after a strong close beyond 2.5); reversal stop 1
tick beyond the extreme reached, target EQ of low…new extreme; continuation
IRL = unfilled same-direction 5m FVGs on the discount (premium) side; stop 1
tick beyond the range extreme; setups live 4h; one trade per boundary; 12h
max hold.

**Not implemented:** HTF PD arrays as a reversal precondition; the 20/40/60-day,
3-week and 3-day ranges (usable later as a bias filter).

## 4. `killzone_po3` — v1's killzone legs with PO3 entries

Setup detection is v1's, unchanged (killzone leg, 3-5 candles or pivotal,
counter to daily bias, regime gating). Read through the PDF, the killzone leg
is the *accumulation* leg and reaching its 2.0 STDV level (4.5 on trending
days, v1's rule) is the manipulation completing. Instead of entering on that
touch, it waits for PO3's MSS and SBZ-nested FVG retrace, then manages the
trade exactly like `po3_stdv`. `ASSUMED DEFAULT`s: zone reached within v1's
60-bar touch window; entry within 240 bars of the killzone.

## 5. Results — real NQ, 2026-06-07 → 2026-09-22 (15.3 weeks)

`python examples/compare_stdv_strategies.py --data <file>`. 1 MNQ contract
($2/pt), $1.24/round turn, bar-close fills for every strategy (fair
relative comparison; optimistic in absolute terms).

| Strategy | Trades | Win % | PF | Net $ | Max DD $ | 1st half $ | 2nd half $ |
|---|---|---|---|---|---|---|---|
| manipulation_leg (v1) = v2 | 9 | 44% | 1.35 | +173 | 377 | +325 | −152 |
| po3_stdv (SBZ-nested FVG) | 108 | 64% | 1.19 | +1,495 | **3,267** | +1,456 | +38 |
| po3_stdv (any IRL) | 211 | 53% | 1.02 | +297 | 3,449 | +200 | +97 |
| ipda_stdv | 144 | 44% | 1.46 | +4,224 | 1,198 | +4,187 | +38 |
| killzone_po3 | 2 | 50% | 0.20 | −339 | 424 | −424 | +84 |

**MFF Pro 50K, fresh eval started on each of 93 trading days** (1 MNQ,
additive rebasing, replayed to the end of the data):

| Strategy | Passed | Failed (MLL) | Unresolved | Pass rate (resolved) |
|---|---|---|---|---|
| v1 / v2 | 0 | 0 | 93 | — |
| po3_stdv (nested) | 5 | 33 | 55 | 13% |
| po3_stdv (any IRL) | 0 | 46 | 47 | 0% |
| ipda_stdv | 17 | 0 | 76 | 100% — but only starts in the first ~3 weeks |
| killzone_po3 | 0 | 0 | 93 | — |

**`killzone_po3` funnel:** 185 killzone windows → 38 legs pass v1's filters
→ 15 reach the 2.0 zone within 60 min → 9 get an MSS → 2 get an SBZ-nested
FVG retrace. Stacking PO3's entry on v1's filters mostly removes trades.

Read this with the following, which matter more than the headline:

- **No strategy shows a demonstrated edge.** Every one either has too few
  trades (v1/v2, killzone_po3) or made essentially all of its result in
  June–July and was flat in August–September.
- **PO3 alone fails the MFF eval far more often than it passes** (33 vs. 5
  across start dates); a single eval started 2026-06-07 happens to pass,
  which is the misleading version of the same data. Its max drawdown
  exceeds the $2,000 MLL on one contract.
- **IPDA's result is fragile.** ~72% of its net came from 21 trades held
  through the 17:00 daily break or a weekend; median trade −$24; without
  its top 5 winners, +$717. If the account must be flat by the daily close,
  most of this result doesn't exist.
- Six variants plus per-profile / per-candle breakdowns were run on the same
  15 weeks, so the best-looking line is biased upward. Don't pick a
  sub-slice off these tables.

## 6. Fixes found during this work

`backtest._extract_trades` reported each trade's entry at the close of the
first *held* bar, while the equity curve (correctly) earns from the signal
bar's close — dropping one bar's move from every trade row, `win_rate`, and
`profit_factor`. The equity curve and `total_return` were always right. Fixed
and pinned by `test_trade_returns_reconcile_with_equity_curve`. Earlier
per-trade figures for v1 (e.g. "+$77 gross, 5W/4L" on this data) were wrong;
corrected: **+$184.50 gross, 4W/5L**.

`po3_stdv`'s first version re-armed a setup on the next 5m bar after the move
had already reached its 2.5 target without an entry, allowing late entries
after the distribution was done (26 of its original 132 trades). A PO3 whose
move runs without us now ends for that candle; pinned by
`test_po3_does_not_rearm_after_the_move_runs_without_an_entry` (which fails
on the old code). Net went from +$868 to +$1,495.
