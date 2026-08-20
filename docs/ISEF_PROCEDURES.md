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

## Variables

**Independent variable (manipulated):** trade-eligibility gating mode, with three levels
run as separate experimental arms —
- Arm 1: regime-gated (strict on trending days, permissive on ranging days)
- Arm 2: permissive always (no regime gate; all levels eligible every day)
- Arm 3: direction-randomized control (identical setups detected, entry direction assigned
  by pseudorandom coin flip with fixed seed)

**Dependent variables (measured):** per-trade return in R-multiples; win rate; profit
factor; maximum peak-to-trough drawdown as % of equity; expectancy per trade; count of
each auto-skip reason code.

**Controlled variables (held constant across all arms):** instrument (MNQ, Micro E-mini
Nasdaq-100 continuous front month); risk per trade (1.0% of equity); maximum concurrent
positions (1); daily loss circuit breaker (3.0% of start-of-day equity); stop placement
(next inverse-Fibonacci tier beyond entry level); target rule (session VWAP, or nearest
opposing POI if VWAP already passed); stagnant-trade cutoff (30 minutes past session
close); session-open windows (Asia 18:00–19:00 ET, New York 09:30–10:30 ET); data
source; commission and slippage model (1 tick slippage per fill, $0.74 round-turn
commission).

**Study period:** Phase 1 — 24 months of historical backtest data. Phase 2 — 60
consecutive trading days of live forward testing on a Tradovate **simulation
(demo) account**. Target sample: n ≥ 100 completed trades per arm.

## Safety and Ethics
This study is conducted entirely on a Tradovate **simulation account funded with
non-redeemable virtual currency**. No real capital is deployed at any point, and no
real financial risk exists for the researcher or any other party. API credentials are
stored in a local environment file that is excluded from version control and never
committed, transmitted, or published. The system is supervised by a qualified adult
supervisor who has read-only access to the trade log. Conversion to a live-funded
account is explicitly out of scope for this study.

## Materials
- Server or always-on computer, Linux, ≥ 4 GB RAM, wired or stable network connection
- Python 3.11 or later
- STDVBOT package (this repository)
- Tradovate simulation account with API access enabled
- Market data subscription providing 1-minute, 4-hour, and daily candles for MNQ
- Local disk storage for the decision log (≥ 1 GB)

---

## Procedure

### Setup (performed once, by a human)

1. Install Python 3.11+ on the host machine and verify the version with `python3 --version`.

2. Clone the STDVBOT repository to the host machine and install it with
   `pip install -e .` from the repository root.

3. Create a Tradovate simulation account and enable API access for it. Record the
   username, password, application ID, application version, API key (`cid`), and API
   secret (`sec`).

4. Copy `.env.example` to `.env` and enter the six credential values from step 3.
   Confirm `.env` is listed in `.gitignore` so credentials are never committed.

5. Set `TRADOVATE_ENV=demo` in `.env`. Verify that this value is `demo` and not
   `live` before proceeding; this is the control that guarantees no real capital
   is at risk.

6. Set the instrument under test by entering `STDVBOT_SYMBOL=MNQ` in `.env`.

7. Set `STDVBOT_RISK_PER_TRADE_PCT=1.0`. This fixes the amount of account equity
   placed at risk on any single trade at one percent.

8. Set `STDVBOT_MAX_CONCURRENT_POSITIONS=1`. This prevents the system from holding
   more than one position at any time.

9. Set `STDVBOT_DAILY_LOSS_LIMIT_PCT=3.0`. This defines the circuit breaker: once
   the sum of realized and unrealized loss for the day reaches three percent of
   start-of-day equity, no new entries are permitted until the next session date.

10. Set `STDVBOT_CONFLUENCE_THRESHOLD=2`, `STDVBOT_STAGNANT_CUTOFF_MINUTES=30`, and
    the three tolerance values `STDVBOT_VWAP_TOLERANCE_TICKS`,
    `STDVBOT_ROUND_NUMBER_TOLERANCE_TICKS`, and `STDVBOT_POI_TOLERANCE_TICKS`.
    Record every value entered in the lab notebook; these constitute the
    controlled variables and must not be altered during a study arm.

11. Run `stdvbot check-connection` and confirm that it reports successful
    authentication, a non-empty account list, and a positive cash balance. Do not
    proceed if any of the three fails.

12. Run `stdvbot check-feed` and confirm that 1-minute, 4-hour, and daily candles
    are being received for the configured symbol. Do not proceed if any timeframe
    is missing.

13. Set the experimental arm for this run by entering `STDVBOT_ARM=regime_gated`,
    `STDVBOT_ARM=permissive`, or `STDVBOT_ARM=random_control` in `.env`. Run only
    one arm at a time; complete its full 60-day period before switching.

14. Start the system as a persistent background service with
    `systemctl --user start stdvbot`, so that it continues running after logout
    and restarts automatically after a reboot.

15. Record the start date, start-of-study equity, arm name, and full configuration
    hash in the lab notebook. Take no further manual action until the arm's 60
    trading days have elapsed.

### Daily automated cycle (performed by the system, unattended)

16. Once per day, before the first session opens, the system downloads the most
    recent closed 4-hour and daily candles for the configured symbol.

17. From those candles it computes a higher-timeframe bias, recorded as either
    `bullish` or `bearish`.

18. From the 4-hour candles it classifies the day's regime, recorded as either
    `trending` or `ranging`.

19. If the arm is `regime_gated` and the regime is `trending`, the system sets the
    day's mode to `A+ only`, under which only levels graded 4.5 are eligible to
    trade and every level graded 2.0–2.5 is skipped automatically without exception.

20. If the arm is `regime_gated` and the regime is `ranging`, the system sets the
    day's mode to `full`, under which levels graded 4.5 and levels graded 2.0–2.5
    are both eligible.

21. If the arm is `permissive` or `random_control`, the system sets the day's mode
    to `full` regardless of regime. This is the manipulation of the independent
    variable.

22. The system computes and stores the day's points of interest as fixed price
    values: prior day high, prior day low, prior Asia session high and low, and
    prior New York session high and low.

23. At the opening of each session window (Asia first, then New York), the system
    records every 1-minute candle formed inside that window.

24. At the close of the window, the system evaluates the recorded candles as a
    single unit called the leg.

25. If the leg consists of exactly one candle, the system discards it and logs the
    reason code `single_candle_leg`.

26. If the leg consists of two or more candles, the system compares the leg's
    direction to the higher-timeframe bias from step 17.

27. If the leg direction matches the bias, the system discards it and logs the
    reason code `agreed_with_bias`.

28. If the leg direction opposes the bias, the system accepts it as a valid
    candidate and continues.

29. From the candidate leg's high and low, the system projects the inverse-Fibonacci
    price levels and stores them as the session's level grid.

30. The system monitors live price against every level in the grid continuously.

31. When price touches a level, the system evaluates four boolean confluence checks
    on the touching candle: whether a candlestick reversal pattern fires; whether
    price is within tolerance of session VWAP; whether price is within tolerance of
    a round number; and whether price is within tolerance of a stored point of
    interest from step 22.

32. The system sums the true results into a confluence score between 0 and 4 and
    records the score and the four individual results in the log.

33. If the touched level is graded 2.0–2.5 and the day's mode is `full`, the system
    proceeds only when the confluence score is 2 or greater; otherwise it skips and
    logs the reason code `low_confluence_score`.

34. If the touched level is graded 2.0–2.5 and the day's mode is `A+ only`, the
    system skips regardless of score and logs the reason code `a_plus_mode_excluded`.

35. If the touched level is graded 4.5, the system proceeds regardless of mode and
    score.

36. The system sets the trade direction opposite to the leg's push direction. In the
    `random_control` arm only, direction is instead assigned by a seeded pseudorandom
    coin flip, and the seed is recorded in the log.

37. The system computes the stop price as the next inverse-Fibonacci tier beyond the
    entry level, and the stop distance as the absolute difference between entry and
    stop.

38. The system computes the risk amount as 1.0% of current account equity, and the
    position size as the risk amount divided by the stop distance, rounded down to
    the nearest whole contract.

39. If the rounded position size is zero, the system skips the trade and logs the
    reason code `size_below_one_contract`.

40. The system sets the target price to the session VWAP; if price has already
    passed VWAP in the trade's favor at the moment of entry, it instead sets the
    target to the nearest opposing point of interest.

41. Before submitting, the system verifies that the daily loss circuit breaker has
    not tripped. If it has, the trade is skipped and logged with the reason code
    `circuit_breaker_tripped`.

42. Before submitting, the system verifies that no position is already open. If one
    is, the trade is skipped and logged with the reason code `conflicting_position`.

43. If both checks pass, the system submits a bracketed order to the Tradovate API
    containing the entry, the stop, and the target, and logs the submission with
    every computed input value.

44. After the fill, the system polls live price against the stop and the target
    continuously.

45. If the target is reached first, the system closes the position and logs the
    outcome as a win, recording the realized R-multiple.

46. If the stop is reached first, the system closes the position and logs the
    outcome as a loss, recording the realized R-multiple.

47. If neither is reached within 30 minutes after session close, the system closes
    the position at market and logs the outcome as a scratch, recording the realized
    R-multiple.

48. Independently of the trading cycle, on every processing cycle the system verifies
    that the price feed is delivering current data and that the broker connection is
    responding without error.

49. If either verification fails, the system immediately closes any open position at
    market, blocks all new entries, and logs the reason code `connectivity_halt`.

50. The system keeps new entries blocked until both verifications pass again, then
    resumes normal operation and logs the recovery.

51. Every decision point — every submitted trade and every skip — writes one log
    record containing timestamp, symbol, arm, day mode, regime, bias, level grade,
    confluence score with its four component results, decision, reason code, and
    where applicable the entry, stop, target, size, and realized R-multiple.

### Data collection and analysis (performed by a human, after each arm completes)

52. At the end of the arm's 60 trading days, stop the service and export the decision
    log to CSV with `stdvbot export-log --out arm_<name>.csv`.

53. Verify data integrity by confirming that the number of logged submissions matches
    the number of fills reported in the Tradovate account statement for the same
    period. Investigate and document any discrepancy before analysis.

54. For each arm, compute mean per-trade R-multiple, standard deviation, win rate,
    profit factor, maximum drawdown, and total trade count.

55. Test the mean per-trade R of each arm against zero using a one-sample t-test at
    α = 0.05.

56. Compare the regime-gated arm against the random-direction control arm using
    Welch's unequal-variance t-test on per-trade R at α = 0.05, and compare win
    rates using a two-proportion z-test.

57. Compute a 95% confidence interval for each arm's mean per-trade R by
    bootstrap resampling with 10,000 resamples.

58. Tabulate the frequency of each skip reason code per arm to determine which
    filters removed the most candidate trades, and report the counts alongside the
    performance results.

59. Repeat steps 13 through 58 for each of the three arms so that all three are run
    over comparable market conditions, and note in the lab notebook any market event
    that affected one arm's period and not another's.

60. Only after all three arms are complete and analyzed, adjust the confluence
    threshold, stop tier, risk percentage, or stagnant cutoff if a follow-up study is
    planned. Changing any of these values mid-arm invalidates that arm and requires
    restarting it.
