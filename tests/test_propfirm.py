import pandas as pd
import pytest

from stdvbot.propfirm import MFF_PRO_50K, PropFirmRules, check_compliance, pass_rate


def _equity(values, start="2024-01-01"):
    idx = pd.date_range(start=start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def test_mff_pro_50k_config():
    assert MFF_PRO_50K.starting_balance == 50_000.0
    assert MFF_PRO_50K.max_loss_limit == 2_000.0
    assert MFF_PRO_50K.profit_target == 3_000.0
    assert MFF_PRO_50K.daily_loss_limit is None
    assert MFF_PRO_50K.consistency_rule_pct == pytest.approx(0.5)
    assert MFF_PRO_50K.min_trading_days == 2


def test_check_compliance_passes_with_balanced_days():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=2_000.0,
        profit_target=3_000.0, consistency_rule_pct=0.5, min_trading_days=2,
    )
    equity = _equity([50_000, 51_000, 52_200, 53_100])
    outcome = check_compliance(equity, rules)

    assert outcome.status == "passed"
    assert outcome.outcome_date == equity.index[3]
    assert outcome.days_traded == 3
    assert outcome.total_profit == pytest.approx(3_100.0)


def test_check_compliance_fails_mll():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=2_000.0,
        profit_target=3_000.0,
    )
    equity = _equity([50_000, 49_500, 47_500])
    outcome = check_compliance(equity, rules)

    assert outcome.status == "failed_mll"
    assert outcome.outcome_date == equity.index[2]


def test_check_compliance_in_progress_when_unresolved():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=2_000.0,
        profit_target=3_000.0,
    )
    equity = _equity([50_000, 50_500, 50_200, 50_800])
    outcome = check_compliance(equity, rules)

    assert outcome.status == "in_progress"
    assert outcome.total_profit == pytest.approx(800.0)


def test_check_compliance_consistency_rule_blocks_then_allows_pass():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=5_000.0,
        profit_target=3_000.0, consistency_rule_pct=0.5, min_trading_days=2,
    )
    # day1 +100, day2 +3400 (target hit, but day2 is 3400/3500 = 97% of
    # profit -> consistency violated, must not pass yet), day3 +3500 more
    # dilutes the ratio to 3400/7000 = 48.6% -> should pass on day3.
    equity = _equity([50_000, 50_100, 53_500, 57_000])
    outcome = check_compliance(equity, rules)

    assert outcome.status == "passed"
    assert outcome.outcome_date == equity.index[3]
    assert outcome.total_profit == pytest.approx(7_000.0)


def test_check_compliance_respects_min_trading_days():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=2_000.0,
        profit_target=1_000.0, min_trading_days=5,
    )
    # Target is hit on day 1 already, but min_trading_days=5 isn't met
    # until later -- must not pass early.
    equity = _equity([50_000, 51_500, 51_500, 51_500, 51_500, 51_500])
    outcome = check_compliance(equity, rules)

    assert outcome.status == "in_progress"
    assert outcome.days_traded == 1


def test_check_compliance_daily_loss_limit():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=10_000.0,
        profit_target=3_000.0, daily_loss_limit=500.0,
    )
    equity = _equity([50_000, 50_200, 49_600])  # day2 loses 600 > 500 DLL
    outcome = check_compliance(equity, rules)

    assert outcome.status == "failed_daily_loss"
    assert outcome.outcome_date == equity.index[2]


def test_check_compliance_empty_series():
    rules = MFF_PRO_50K
    outcome = check_compliance(pd.Series(dtype=float), rules)
    assert outcome.status == "in_progress"
    assert outcome.days_traded == 0


def test_pass_rate_counts_are_consistent_and_bounded():
    rules = PropFirmRules(
        name="test", starting_balance=50_000.0, max_loss_limit=2_000.0,
        profit_target=3_000.0, consistency_rule_pct=0.5, min_trading_days=2,
    )
    # First segment steadily passes; second segment steadily breaches MLL.
    passing_segment = [50_000 + i * 400 for i in range(10)]  # ends +3600
    failing_segment = [50_000 - i * 300 for i in range(10)]  # ends -2700
    equity = _equity(passing_segment + failing_segment)

    stats = pass_rate(equity, rules, window_days=10, step_days=10)

    assert stats["attempts"] == stats["passed"] + stats["failed"] + stats["in_progress"]
    assert stats["passed"] >= 1
    assert stats["failed"] >= 1
    assert stats["pass_rate"] is not None
    assert 0.0 <= stats["pass_rate"] <= 1.0


def test_pass_rate_handles_short_series():
    rules = MFF_PRO_50K
    equity = _equity([50_000, 50_100])
    stats = pass_rate(equity, rules, window_days=60, step_days=5)
    assert stats["attempts"] == 0
    assert stats["pass_rate"] is None
