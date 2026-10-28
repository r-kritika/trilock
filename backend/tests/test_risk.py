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
