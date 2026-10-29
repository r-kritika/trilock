import pytest

from app.services.risk import RiskCategory, RiskConfig, RiskInput, assess_risk


def test_small_domestic_payment_is_low():
    r = assess_risk(RiskInput(amount=50))
    assert r.category == RiskCategory.LOW and r.score < 10


def test_amount_curve_is_monotonic():
    scores = [assess_risk(RiskInput(amount=a)).score for a in (10, 100, 500, 2000, 10000, 50000, 500000)]
    assert scores == sorted(scores)
    assert scores[-1] == 40  # curve is flat after the last point


def test_each_factor_adds_listed_points():
    base = assess_risk(RiskInput(amount=1000)).score
    r = assess_risk(RiskInput(amount=1000, recipient_is_new=True, is_international=True, new_device=True))
    assert r.score == pytest.approx(base + 20 + 12 + 10)
    assert {f.name for f in r.factors} == {"amount", "new_recipient", "international", "new_device"}


def test_unusual_amount_needs_history():
    no_hist = assess_risk(RiskInput(amount=3000, history_count=1, history_mean_amount=100))
    hist = assess_risk(RiskInput(amount=3000, history_count=5, history_mean_amount=100))
    assert "unusual_amount" not in {f.name for f in no_hist.factors}
    assert "unusual_amount" in {f.name for f in hist.factors}


def test_critical_and_cap():
    r = assess_risk(RiskInput(amount=1_000_000, transaction_type="wire_transfer", recipient_is_new=True,
                              is_international=True, new_device=True, history_count=9, history_mean_amount=10))
    assert r.category == RiskCategory.CRITICAL and r.score == 100


def test_category_boundaries_configurable():
    cfg = RiskConfig(medium_from=1)
    assert assess_risk(RiskInput(amount=100), cfg).category == RiskCategory.MEDIUM


def test_negative_amount_rejected():
    with pytest.raises(ValueError):
        assess_risk(RiskInput(amount=-1))


def test_deterministic():
    i = RiskInput(amount=777, recipient_is_new=True)
    assert assess_risk(i).to_dict() == assess_risk(i).to_dict()


# ---- time-aware factors ----
from app.services.authentication import typical_hour
from app.services.risk import circular_gap


def names(r):
    return {f.name for f in r.factors}


def pts(r, name):
    return next(f.points for f in r.factors if f.name == name)


def test_velocity_uses_the_highest_matching_step():
    assert "velocity" not in names(assess_risk(RiskInput(amount=10, recent_count=1)))
    assert pts(assess_risk(RiskInput(amount=10, recent_count=2)), "velocity") == 10
    assert pts(assess_risk(RiskInput(amount=10, recent_count=3)), "velocity") == 10
    assert pts(assess_risk(RiskInput(amount=10, recent_count=4)), "velocity") == 20
    assert pts(assess_risk(RiskInput(amount=10, recent_count=9)), "velocity") == 20


def test_daily_total_counts_this_payment_too():
    assert "daily_total" not in names(assess_risk(RiskInput(amount=4000, amount_24h=5000)))
    assert "daily_total" in names(assess_risk(RiskInput(amount=6000, amount_24h=5000)))
    assert "daily_total" not in names(assess_risk(RiskInput(amount=12000, amount_24h=0)))     # one big payment is the amount factor's job


def test_night_hour_when_there_is_no_learned_profile():
    assert "night_hour" in names(assess_risk(RiskInput(amount=10, local_hour=3)))
    assert "night_hour" not in names(assess_risk(RiskInput(amount=10, local_hour=10)))
    assert "night_hour" not in names(assess_risk(RiskInput(amount=10, local_hour=5)))          # window is 00:00 to 04:59
    assert "night_hour" not in names(assess_risk(RiskInput(amount=10)))                        # hour unknown: no factor


def test_learned_profile_replaces_the_fixed_night_window():
    day_worker = RiskInput(amount=10, typical_hour=14.0)
    assert "unusual_hour" in names(assess_risk(RiskInput(**{**day_worker.__dict__, "local_hour": 3})))
    assert "unusual_hour" not in names(assess_risk(RiskInput(**{**day_worker.__dict__, "local_hour": 17})))
    # a night-shift worker is not flagged for paying at 03:00, and IS flagged at noon
    night = dict(amount=10, typical_hour=2.0)
    assert not names(assess_risk(RiskInput(**night, local_hour=3))) & {"unusual_hour", "night_hour"}
    assert "unusual_hour" in names(assess_risk(RiskInput(**night, local_hour=13)))


def test_hours_wrap_around_midnight():
    assert circular_gap(23, 1) == 2 and circular_gap(1, 23) == 2 and circular_gap(0, 12) == 12
    assert "unusual_hour" not in names(assess_risk(RiskInput(amount=10, typical_hour=23.0, local_hour=1)))


def test_typical_hour_is_a_circular_mean_and_needs_a_pattern():
    assert typical_hour([9, 10, 11, 10, 9, 10]) == pytest.approx(9.8, abs=0.3)
    assert typical_hour([23, 0, 1, 0, 23]) in (pytest.approx(0, abs=0.5), pytest.approx(24, abs=0.5))
    assert typical_hour([0, 6, 12, 18, 3, 9, 15, 21]) is None           # spread around the clock: no usual time
    assert typical_hour([]) is None


def test_new_account_and_dormant_account_only_matter_for_real_money():
    assert "new_account" in names(assess_risk(RiskInput(amount=1500, account_age_hours=3)))
    assert "new_account" not in names(assess_risk(RiskInput(amount=500, account_age_hours=3)))
    assert "new_account" not in names(assess_risk(RiskInput(amount=1500, account_age_hours=48)))
    assert "dormant_account" in names(assess_risk(RiskInput(amount=2000, hours_since_last_txn=90 * 24)))
    assert "dormant_account" not in names(assess_risk(RiskInput(amount=200, hours_since_last_txn=90 * 24)))
    assert "dormant_account" not in names(assess_risk(RiskInput(amount=2000, hours_since_last_txn=5)))


def test_recent_biometric_change_decays_with_time():
    assert pts(assess_risk(RiskInput(amount=10, biometric_changed_hours_ago=3)), "recent_biometric_change") == 12
    assert "recent_biometric_change" not in names(assess_risk(RiskInput(amount=10, biometric_changed_hours_ago=30)))


def test_no_time_inputs_means_no_time_factors():
    """Existing callers that know nothing about time must get exactly the old score."""
    plain = assess_risk(RiskInput(amount=1000, recipient_is_new=True))
    assert names(plain) == {"amount", "new_recipient"}


def test_time_factors_are_configurable(tmp_path):
    import json
    from app.services.fusion import load_policy_config
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"risk": {"velocity_points": [[1, 30]], "night_points": 1, "velocity_window_minutes": 5}}))
    risk, _ = load_policy_config(p)
    r = assess_risk(RiskInput(amount=10, recent_count=1, local_hour=2), risk)
    assert pts(r, "velocity") == 30 and pts(r, "night_hour") == 1 and risk.velocity_window_minutes == 5
