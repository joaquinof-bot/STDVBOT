# Procedures — Autonomous Regime-Gated Reversal Trading System (STDVBOT)

## Research Question
Does a fully autonomous, rule-based reversal trading system that gates its own trade
eligibility by higher-timeframe market regime produce a per-trade expectancy
significantly greater than a direction-randomized control using identical position
sizing, stop placement, and exit rules?

## Hypothesis
If trade eligibility is gated by higher-timeframe regime classification (strict "A+ only"
filtering on trending days, permissive "full" filtering on ranging days), then the system
will produce a mean per-trade return in R-multiples significantly greater than zero and
significantly greater than a direction-randomized control (α = 0.05), because
counter-bias session-open legs represent liquidity sweeps that mean-revert more often
than they continue.

## Study Design
This is a **historical simulation study**. All three arms are evaluated by replaying
24 months of archived 1-minute price data through the decision system. No live
brokerage account is connected, no orders are transmitted to any exchange, and no
capital — real or simulated — is placed at risk at any point.

Running all arms over the identical historical period is a methodological advantage
over live forward testing: every arm sees exactly the same market conditions, which
removes the confound of arms trading different weeks.

## Variables

**Independent variable (manipulated):** trade-eligibility gating mode, with three levels
run as separate experimental arms over the same data —
- Arm 1: regime-gated (strict on trending days, permissive on ranging days)
- Arm 2: permissive always (no regime gate; all levels eligible every day)
- Arm 3: direction-randomized control (identical setups detected, entry direction assigned
  by seeded pseudorandom coin flip)

**Dependent variables (measured):** per-trade return in R-multiples; win rate; profit
factor; maximum peak-to-trough drawdown as % of equity; expectancy per trade; count of
each auto-skip reason code.

**Controlled variables (held constant across all arms):** instrument (MNQ, Micro E-mini
Nasdaq-100); historical period; risk per trade (1.0% of equity); maximum concurrent
positions (1); daily loss circuit breaker (3.0% of start-of-day equity); stop placement
(next inverse-Fibonacci tier beyond entry level); target rule (session VWAP, or nearest
opposing POI if VWAP already passed); stagnant-trade cutoff (30 minutes past session
close); session-open windows (Asia 18:00–19:00 ET, New York 09:30–10:30 ET); starting
equity; slippage model (1 tick per fill); commission ($0.74 round turn).

**Sample:** 24 months of 1-minute data. Target n ≥ 100 completed trades per arm.

## Safety and Ethics
No brokerage account is connected to this system and no orders are transmitted anywhere.
The study operates exclusively on archived historical price files, so there is no
financial risk to the researcher or any other party, and no possibility of market impact.

The researcher holds a prop-firm evaluation-style simulated account. That account is
**deliberately excluded** from this study. Prop firms including Apex prohibit fully
autonomous bots that manage both entry and exit without human involvement, with account
termination as the stated penalty; connecting this system to such an account would
violate those terms. The backtest design avoids this entirely.

Should any future extension connect to a broker, it must use a personal simulation
account under adult supervision, never a prop-firm account, and that extension is
outside the scope of this study.

## Materials
- Computer capable of running Python 3.11 or later
- STDVBOT package (this repository)
- 24 months of 1-minute OHLCV data for MNQ, in CSV form, obtained from a historical
  data vendor
- Approximately 2 GB of free disk space for data and result files
- No brokerage account, no API credentials, and no market data subscription

---

## Procedure

### Part A — Setup (performed once, by a human)

1. Install Python 3.11 or later and confirm the version with `python3 --version`.

2. Clone the STDVBOT repository and install it with `pip install -e .` from the
   repository root.

3. Purchase and download 24 months of 1-minute OHLCV data for MNQ from a historical
   data vendor. Save the CSV to `data/mnq_1m.csv`.

4. Confirm the CSV has six columns in the order timestamp, open, high, low, close,
   volume, and that timestamps are US Eastern. Record the vendor, product, and
   download date in the lab notebook; this is the study's data provenance.

5. Run `stdvbot verify-data data/mnq_1m.csv` and confirm it reports the expected date
   range, the total bar count, and zero malformed rows. Do not proceed if any session
   date is missing more than 10% of its expected bars.

6. Set the strategy parameters in `.env`: `STDVBOT_SYMBOL=MNQ`,
   `STDVBOT_RISK_PER_TRADE_PCT=1.0`, `STDVBOT_MAX_CONCURRENT_POSITIONS=1`,
   `STDVBOT_DAILY_LOSS_LIMIT_PCT=3.0`, `STDVBOT_CONFLUENCE_THRESHOLD=2`,
   `STDVBOT_STAGNANT_CUTOFF_MINUTES=30`, and the three tolerance values.

7. Record every parameter value in the lab notebook. These are the controlled
   variables and must not change while any arm is running.

8. Select the arm for this run with `STDVBOT_ARM=regime_gated`,
   `STDVBOT_ARM=permissive`, or `STDVBOT_ARM=random_control`.

### Part B — Simulated decision cycle (performed by the system, per session date)

The system replays each session date in the dataset in chronological order, seeing
only data available up to the moment being simulated. It never reads a future bar.

9. For the session date being simulated, load all closed 4-hour and daily bars
   preceding it.

10. Compute the higher-timeframe bias from those bars, recorded as `bullish` or
    `bearish`.

11. Classify the day's regime from the 4-hour bars, recorded as `trending` or
    `ranging`.

12. If the arm is `regime_gated` and the regime is `trending`, set the day's mode to
    `A+ only`: only levels graded 4.5 are eligible, and every level graded 2.0–2.5 is
    skipped without exception.

13. If the arm is `regime_gated` and the regime is `ranging`, set the day's mode to
    `full`: levels graded 4.5 and 2.0–2.5 are both eligible.

14. If the arm is `permissive` or `random_control`, set the mode to `full` regardless
    of regime. This is the manipulation of the independent variable.

15. Compute the day's points of interest as fixed prices: prior day high, prior day
    low, prior Asia session high and low, prior New York session high and low.

16. For each session window in order (Asia, then New York), collect the 1-minute bars
    inside that window. This group is the leg.

17. If the leg consists of exactly one bar, discard it and log `single_candle_leg`.

18. If the leg consists of two or more bars, compare its direction to the bias from
    step 10.

19. If the leg direction matches the bias, discard it and log `agreed_with_bias`.

20. If the leg direction opposes the bias, accept it as a valid candidate.

21. Project the inverse-Fibonacci levels from the candidate leg's high and low, and
    store them as the session's level grid.

22. Step forward through subsequent 1-minute bars, checking each against the grid.

23. When a bar touches a level, evaluate four boolean confluence checks on that bar:
    whether a candlestick reversal pattern fires; whether price is within tolerance of
    session VWAP; whether price is within tolerance of a round number; and whether
    price is within tolerance of a point of interest from step 15.

24. Sum the true results into a confluence score from 0 to 4, and log the score with
    its four component results.

25. If the level is graded 2.0–2.5 and the mode is `full`, proceed only when the score
    is 2 or greater; otherwise skip and log `low_confluence_score`.

26. If the level is graded 2.0–2.5 and the mode is `A+ only`, skip regardless of score
    and log `a_plus_mode_excluded`.

27. If the level is graded 4.5, proceed regardless of mode and score.

28. Set the trade direction opposite the leg's push. In the `random_control` arm only,
    assign direction by seeded pseudorandom coin flip and log the seed.

29. Compute the stop price as the next inverse-Fibonacci tier beyond the entry level,
    and the stop distance as the absolute difference between entry and stop.

30. Compute the risk amount as 1.0% of current simulated equity, and the position size
    as risk amount divided by stop distance, rounded down to whole contracts.

31. If the rounded size is zero, skip and log `size_below_one_contract`.

32. Set the target to session VWAP; if price has already passed VWAP in the trade's
    favor at entry, set the target to the nearest opposing point of interest instead.

33. Verify the daily loss circuit breaker has not tripped; if it has, skip and log
    `circuit_breaker_tripped`.

34. Verify no simulated position is already open; if one is, skip and log
    `conflicting_position`.

35. If both checks pass, open the simulated position at the touch price plus one tick
    of adverse slippage, and deduct commission.

36. Step forward bar by bar, checking the bar's high and low against the stop and
    target.

37. If the target is reached first, close the position and log a win with its realized
    R-multiple.

38. If the stop is reached first, close the position and log a loss with its realized
    R-multiple.

39. If a single bar's range spans both the stop and the target, resolve it as a loss.
    This is the conservative assumption: intrabar sequence is unknowable from OHLC
    data, and assuming the favorable order would inflate results.

40. If neither is reached within 30 minutes after session close, close at market and
    log a scratch with its realized R-multiple.

41. Write one log record at every decision point containing timestamp, session date,
    arm, mode, regime, bias, level grade, confluence score with its four components,
    decision, reason code, and where applicable entry, stop, target, size, and
    realized R-multiple.

### Part C — Analysis (performed by a human, after each arm completes)

42. Export the arm's decision log with `stdvbot export-log --out arm_<name>.csv`.

43. Verify integrity by confirming that logged entries and logged exits are equal in
    number and that no position remains open at the end of the dataset.

44. Compute for each arm: mean per-trade R-multiple, standard deviation, win rate,
    profit factor, maximum drawdown, and total trade count.

45. Test each arm's mean per-trade R against zero with a one-sample t-test at α = 0.05.

46. Compare the regime-gated arm against the random-direction control with Welch's
    unequal-variance t-test on per-trade R at α = 0.05, and compare win rates with a
    two-proportion z-test.

47. Compute a 95% confidence interval for each arm's mean per-trade R by bootstrap
    resampling with 10,000 resamples.

48. Tabulate the frequency of each skip reason code per arm to determine which filters
    removed the most candidate trades, and report those counts alongside performance.

49. Repeat steps 8 through 48 for each of the three arms. Because all arms replay the
    same historical period, no adjustment for differing market conditions is required.

50. Only after all three arms are analyzed, vary the confluence threshold, stop tier,
    risk percentage, or stagnant cutoff for a sensitivity analysis. Report any such
    variation as a separate secondary result, never as a revision of the primary
    result, since tuning parameters against the same data that produced the primary
    finding would overfit it.
