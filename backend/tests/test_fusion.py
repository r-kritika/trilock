import pytest

from app.biometrics.types import ModalityResult, VerificationStatus
from app.services.fusion import Decision, FusionConfig, fixed_threshold_fusion, load_policy_config, risk_aware_fusion


def res(mod, p, q=0.9):
    if p is None:
        return ModalityResult.not_evaluated(mod, "t", "not_provided", "not provided")
    return ModalityResult(modality=mod, status=VerificationStatus.MATCH if p >= .5 else VerificationStatus.NO_MATCH,
                          method="t", raw_score=p, calibrated=p, quality=q)


def trio(f, fp, v, q=0.9):
    return [res("face", f, q), res("fingerprint", fp, q), res("voice", v, q)]


# ---- fixed threshold ----
def test_fixed_approves_above_threshold():
    o = fixed_threshold_fusion(trio(.9, .85, .9), "low")
    assert o.decision == Decision.APPROVED and o.fused_score == pytest.approx((.9 + .85 + .9) / 3, abs=1e-3)


def test_fixed_rejects_below_threshold():
    assert fixed_threshold_fusion(trio(.2, .3, .1), "low").decision == Decision.REJECTED


def test_fixed_ignores_risk_category():
    a = fixed_threshold_fusion(trio(.8, .8, .8), "low")
    b = fixed_threshold_fusion(trio(.8, .8, .8), "critical")
    assert a.decision == b.decision == Decision.APPROVED


def test_fixed_missing_modality_not_counted_as_match():
    # one modality at 0.9, others missing: average only over what exists, never over invented 1.0s
    o = fixed_threshold_fusion(trio(.9, None, None), "low")
    assert o.usable == ["face"] and o.fused_score == pytest.approx(.9)
    assert o.coverage == pytest.approx(0.5, abs=1e-3)       # one of the two core modalities


def test_fixed_nothing_evaluable_asks_for_more():
    o = fixed_threshold_fusion(trio(None, None, None), "low")
    assert o.decision == Decision.ADDITIONAL and o.fused_score is None


# ---- risk aware ----
def test_risk_aware_low_risk_single_modality_can_approve():
    assert risk_aware_fusion(trio(.9, None, None), "low").decision == Decision.APPROVED


def test_risk_aware_high_risk_single_modality_needs_more_evidence():
    o = risk_aware_fusion(trio(.99, None, None), "high")
    assert o.decision == Decision.ADDITIONAL
    assert any("at least 2" in u for u in o.unmet)
    # the baseline would have approved the same input
    assert fixed_threshold_fusion(trio(.99, None, None), "high").decision == Decision.APPROVED


def test_risk_aware_critical_needs_face_and_voice_and_fingerprint_is_optional():
    assert risk_aware_fusion(trio(.97, .95, None), "critical").decision == Decision.ADDITIONAL      # voice missing, fingerprint cannot stand in
    assert risk_aware_fusion(trio(.97, None, .96), "critical").decision == Decision.APPROVED        # face + voice are enough
    assert risk_aware_fusion(trio(.97, .95, .96), "critical").decision == Decision.APPROVED


def test_risk_aware_threshold_rises_with_risk():
    results = trio(.75, .75, .75)
    assert risk_aware_fusion(results, "low").decision == Decision.APPROVED
    assert risk_aware_fusion(results, "medium").decision == Decision.APPROVED
    assert risk_aware_fusion(results, "high").decision == Decision.ADDITIONAL
    assert risk_aware_fusion(results, "critical").decision == Decision.ADDITIONAL


def test_risk_aware_clear_mismatch_rejects():
    o = risk_aware_fusion(trio(.05, .02, .1), "medium")
    assert o.decision == Decision.REJECTED


def test_risk_aware_conflicting_modality_blocks_approval():
    o = risk_aware_fusion(trio(.99, .99, .14), "medium")
    assert o.fused_score >= .70
    assert o.decision == Decision.ADDITIONAL and any("did not match" in u for u in o.unmet)


def test_risk_aware_low_quality_lowers_reliability_and_coverage():
    good = risk_aware_fusion(trio(.9, .9, .9, q=1.0), "high")
    poor = risk_aware_fusion(trio(.9, .9, .9, q=0.0), "high")
    assert good.coverage > poor.coverage
    assert good.coverage == pytest.approx(1.0) and poor.coverage == pytest.approx(0.6)   # 3 x 0.4 over the core weight 2, capped at 1


def test_poor_quality_weights_shift_fused_score_toward_reliable_modality():
    mixed = [res("face", .95, 1.0), res("fingerprint", .1, 0.0), res("voice", None)]
    o = risk_aware_fusion(mixed, "low")
    plain = (.95 + .1) / 2
    assert o.fused_score > plain


def test_nothing_evaluable_is_additional_not_reject_or_approve():
    for cat in ("low", "medium", "high", "critical"):
        assert risk_aware_fusion(trio(None, None, None), cat).decision == Decision.ADDITIONAL


def test_failed_input_is_not_a_mismatch():
    failed = [res("face", None), res("fingerprint", None), res("voice", None)]
    failed[0].reason = "no face detected"
    o = risk_aware_fusion(failed, "high")
    assert o.decision == Decision.ADDITIONAL
    assert "face" in o.unusable


def test_deterministic_and_explained():
    a = risk_aware_fusion(trio(.8, .6, .9), "high").to_dict()
    b = risk_aware_fusion(trio(.8, .6, .9), "high").to_dict()
    assert a == b and a["explanation"]


def test_unknown_risk_category_raises():
    with pytest.raises(ValueError):
        risk_aware_fusion(trio(.9, .9, .9), "extreme")


def test_policy_file_overrides(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text('{"fusion": {"fixed_threshold": 0.9, "bands": {"high": {"approve": 0.95}}}, "risk": {"high_from": 40}}')
    risk, fusion = load_policy_config(p)
    assert fusion.fixed_threshold == 0.9 and fusion.bands["high"].approve == 0.95
    assert fusion.bands["high"].min_modalities == 2   # untouched keys keep defaults
    assert risk.high_from == 40


def test_policy_file_unknown_key_rejected(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text('{"fusion": {"nope": 1}}')
    with pytest.raises(ValueError):
        load_policy_config(p)


# ---- ablation baseline used by the evaluation ----
def test_fixed_min2_requires_two_modalities_whatever_the_risk():
    from app.services.fusion import fixed_min_modalities_fusion
    one = trio(.99, None, None)
    for cat in ("low", "critical"):
        o = fixed_min_modalities_fusion(one, cat)
        assert o.decision == Decision.ADDITIONAL and o.policy == "fixed_min2"
    assert fixed_min_modalities_fusion(trio(.9, .9, None), "low").decision == Decision.APPROVED
    # it does not turn rejections into anything else
    assert fixed_min_modalities_fusion(trio(.1, None, None), "low").decision == Decision.REJECTED


def test_fixed_policy_is_exposed_to_omission_risk_aware_is_not():
    """An attacker who beat only the face simply leaves the other fields empty."""
    attack = trio(.97, None, None)
    assert fixed_threshold_fusion(attack, "high").decision == Decision.APPROVED
    assert risk_aware_fusion(attack, "high").decision == Decision.ADDITIONAL



# ---- fingerprint is optional; face and voice are the core ----
def test_missing_fingerprint_never_lowers_coverage_or_asks_for_more():
    with_fp = risk_aware_fusion(trio(.95, .95, .95), "critical")
    without = risk_aware_fusion(trio(.95, None, .95), "critical")
    assert without.decision == with_fp.decision == Decision.APPROVED
    assert without.coverage == pytest.approx(0.94, abs=0.01)           # the core alone is not penalised for the absent fingerprint
    assert with_fp.coverage >= without.coverage and with_fp.coverage <= 1.0   # adding it can only help, capped at 1
    assert not any("fingerprint" in u for u in without.unmet)


def test_fingerprint_cannot_replace_face_or_voice_for_high_value_payments():
    for cat in ("high", "critical"):
        o = risk_aware_fusion(trio(.99, .99, None), cat)
        assert o.decision == Decision.ADDITIONAL and any("voice" in u for u in o.unmet), cat
        o = risk_aware_fusion(trio(None, .99, .99), cat)
        assert o.decision == Decision.ADDITIONAL and any("face" in u for u in o.unmet), cat
    # for lower risk any two modalities are fine, so the optional one can still help there
    assert risk_aware_fusion(trio(.9, .9, None), "medium").decision == Decision.APPROVED


def test_fingerprint_only_adds_evidence_when_it_is_present():
    weak_fp = risk_aware_fusion(trio(.9, .2, .9), "medium")             # optional modality disagrees
    no_fp = risk_aware_fusion(trio(.9, None, .9), "medium")
    assert weak_fp.fused_score < no_fp.fused_score                     # present evidence counts, for and against


def test_core_modalities_are_configurable():
    cfg = FusionConfig(core_modalities=["face"])
    o = risk_aware_fusion(trio(.97, None, None), "low", cfg)
    assert o.coverage == pytest.approx(0.94, abs=0.01)



# ---- every evaluated modality must itself match: a "no match" is never outvoted ----
@pytest.mark.parametrize("cat", ["low", "medium", "high", "critical"])
def test_a_borderline_no_match_cannot_be_outvoted_at_any_risk(cat):
    """Face 0.99 plus a voice that says no match (0.45) fuses to 0.72, which used to pass at low and medium risk."""
    o = risk_aware_fusion(trio(.99, None, .45), cat)
    assert o.fused_score >= 0.70                      # the averaged score alone would have been enough at low and medium
    assert o.decision == Decision.ADDITIONAL and any("voice did not match" in u for u in o.unmet)


@pytest.mark.parametrize("cat", ["low", "medium", "high", "critical"])
def test_any_single_no_match_blocks_approval_whichever_modality_it_is(cat):
    for results in (trio(.45, None, .99), trio(.99, .45, .99), trio(.99, .99, .49)):
        assert risk_aware_fusion(results, cat).decision != Decision.APPROVED


def test_unusable_input_is_not_a_no_match_and_a_clear_mismatch_is_still_rejected():
    # a modality that could not be evaluated is no evidence (not a veto): low risk still approves on the other one
    assert risk_aware_fusion(trio(.97, None, None), "low").decision == Decision.APPROVED
    # a clear impostor on every modality is rejected, not merely held
    assert risk_aware_fusion(trio(.02, .03, .01), "critical").decision == Decision.REJECTED


def test_a_modality_exactly_at_its_match_line_counts_as_a_match():
    assert risk_aware_fusion(trio(.99, None, .50), "low").decision == Decision.APPROVED
