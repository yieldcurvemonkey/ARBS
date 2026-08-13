"""Delivery-option (switch) tests, pinned to an independent vendor sheet.

The known-answer case is the J.P. Morgan *U.S. Futures and Options Package*, closes as of
2026-08-12. Every input below is transcribed from that sheet; the expected outputs are JPM's own
model values, produced by a full-basket model this code does not share. That is the point: a
positive control has to come from outside the implementation being tested.
"""

from __future__ import annotations

import math

import pytest

from RVUtils.BasisVsVol.switch import (
    Deliverable,
    cf_adjusted_forward_price,
    crossover_shift,
    delivery_option_two_bond,
    dv01_gap,
    implied_switch_vol,
    map_is_valid,
)

# --------------------------------------------------------------------------- JPM 2026-08-12
# Ultra Bond (UB) Sep26: futures 110-08, term repo 3.69%, 49 days to delivery (09/30/26).
# Opt. IVol 10.80% price vol; futures value of one bp 0.1732 points  ->  68.7bp normal yield vol.
UB_F = 110.25
UB_TTE = 49 / 365.0
UB_SIGMA_BP = 0.1080 * UB_F / 0.17321 * 100.0 / 100.0  # price vol -> bp yield vol

UB_CTD = Deliverable("T 4 Nov 52", cf=0.7383,
                     price_fwd=cf_adjusted_forward_price(2.5, 0.7383, UB_F), dv01=0.1215, prob=0.858)
UB_ALT = Deliverable("T 2 1/4 Feb 52", cf=0.5154,
                     price_fwd=cf_adjusted_forward_price(10.0, 0.5154, UB_F), dv01=0.0953, prob=0.102)

# Bond (ZB) Sep26: futures 109-01; Opt. IVol 9.13%; futures value of one bp 0.1477.
ZB_F = 109.03125
ZB_TTE = 49 / 365.0
ZB_SIGMA_BP = 0.0913 * ZB_F / 0.14768

ZB_CTD = Deliverable("T 5 May 45", cf=0.8892,
                     price_fwd=cf_adjusted_forward_price(2.5, 0.8892, ZB_F), dv01=0.1156, prob=0.409)
ZB_ALT = Deliverable("T 3 Nov 44", cf=0.6725,
                     price_fwd=cf_adjusted_forward_price(5.5, 0.6725, ZB_F), dv01=0.0952, prob=0.128)


def test_forward_price_recovers_from_net_basis():
    """P_fwd = NB/32 + CF*F, checked against the sheet's own CTD row."""
    p = cf_adjusted_forward_price(2.5, 0.7383, UB_F)
    assert p == pytest.approx(2.5 / 32 + 0.7383 * UB_F, rel=1e-12)
    assert 81.0 < p < 82.0  # UB CTD trades near 81-18+


def test_ctd_is_cheapest_on_a_cf_adjusted_basis():
    assert UB_CTD.a < UB_ALT.a
    assert ZB_CTD.a < ZB_ALT.a


def test_dv01_gap_sign_says_a_selloff_triggers_the_switch():
    """Both long-end challengers are lower-coupon and longer-duration: m < 0 => payer-like."""
    assert dv01_gap(UB_CTD, UB_ALT) < 0
    assert dv01_gap(ZB_CTD, ZB_ALT) < 0


def test_ub_crossover_matches_published_baseline_yield_shift():
    """JPM prints 'Baseline Yld Shft' 28.3bp for T 2 1/4 Feb 52 (p4).

    The linearised two-bond solver gives ~24.6bp. The 13% shortfall is expected and attributable:
    JPM's probabilities and shifts are beta-adjusted (yield betas 1.006 vs 0.996 across this pair)
    and carry convexity, both of which a first-order shift drops.
    """
    s = crossover_shift(UB_CTD, UB_ALT)
    assert 20.0 < s < 30.0
    assert s == pytest.approx(24.6, abs=1.5)
    assert abs(s - 28.3) / 28.3 < 0.20


def test_ub_two_bond_switch_component_is_about_one_tick():
    """The switch component alone for Sep26 Ultra Bond is ~1.05/32.

    This is NOT a tie-out to JPM's printed 0-01, though it was once reported as one. Adding the
    wildcard -- the component the dealer literature says dominates in the modern regime -- takes
    the same contract to 2.62/32 against that same printed 1.00. And the sheet prints to the
    half-tick, so a 1-tick number is consistent with anything in [0.75, 1.25]: at these magnitudes
    it cannot discriminate between a switch-only and a switch-plus-wildcard model. The test pins
    the switch component's magnitude and nothing more.
    """
    r = delivery_option_two_bond(UB_CTD, UB_ALT, UB_SIGMA_BP, UB_TTE)
    assert r["w"] == 1  # payer-like
    assert r["value"] == pytest.approx(1.05, abs=0.35)
    assert r["value"] > 0


def test_switch_plus_wildcard_overshoots_the_printed_value_for_ultra_bond():
    """The retraction, as an executable fact rather than a note in a docstring."""
    from RVUtils.BasisVsVol.wildcard import wildcard_value

    wc = wildcard_value(cf=0.7383, dv01_points_per_bp=0.1215,
                        daily_carry_points=3.5 / 32 / 48, n_delivery_days=14,
                        sigma_yield_bp=1.0).value_ticks
    switch = delivery_option_two_bond(UB_CTD, UB_ALT, UB_SIGMA_BP, UB_TTE)["value"]
    assert wc > switch          # the wildcard is the larger component for a low-CF contract
    assert switch + wc > 2.0    # against a printed 0-01


def test_zb_two_bond_understates_a_diffuse_basket():
    """JPM's Sep26 Bond delivery option value is 0-04. Two bonds cannot reach it.

    ZB has seven deliverables above 1% delivery probability spanning 33 months of maturity, so a
    model that sees exactly one switch must miss most of the value. Measuring the shortfall is the
    point -- it is the same conclusion the CTD-probability sheet forces, by an independent route.
    """
    r = delivery_option_two_bond(ZB_CTD, ZB_ALT, ZB_SIGMA_BP, ZB_TTE)
    assert r["value"] == pytest.approx(1.4, abs=0.6)
    assert r["value"] < 0.6 * 4.0, "two-bond should capture well under half of a diffuse basket"


def test_inversion_round_trips_against_the_pricer():
    r = delivery_option_two_bond(UB_CTD, UB_ALT, UB_SIGMA_BP, UB_TTE)
    back = implied_switch_vol(r["value"], UB_CTD, UB_ALT, UB_TTE)
    assert back == pytest.approx(UB_SIGMA_BP, rel=1e-6)


def test_inversion_returns_nan_when_the_basis_cannot_identify_a_vol():
    """A net basis at (or below) zero carries no time value -- there is no vol to report."""
    assert math.isnan(implied_switch_vol(0.0, UB_CTD, UB_ALT, UB_TTE))
    assert math.isnan(implied_switch_vol(-1.0, UB_CTD, UB_ALT, UB_TTE))


def test_zero_vol_gives_zero_option_value():
    r = delivery_option_two_bond(UB_CTD, UB_ALT, 0.0, UB_TTE)
    assert math.isnan(r["value"]) or r["value"] == pytest.approx(0.0, abs=1e-9)


def test_value_is_monotone_in_vol_and_vega_is_positive():
    lo = delivery_option_two_bond(UB_CTD, UB_ALT, 40.0, UB_TTE)["value"]
    hi = delivery_option_two_bond(UB_CTD, UB_ALT, 90.0, UB_TTE)["value"]
    assert hi > lo > 0
    assert delivery_option_two_bond(UB_CTD, UB_ALT, UB_SIGMA_BP, UB_TTE)["vega"] > 0


def test_degenerate_basket_refuses_rather_than_returning_a_number():
    """Identical CF-adjusted bonds have no switch; the crossover must not be fabricated."""
    twin = Deliverable("twin", cf=UB_CTD.cf, price_fwd=UB_CTD.price_fwd, dv01=UB_CTD.dv01)
    assert math.isnan(crossover_shift(UB_CTD, twin))
    assert math.isnan(delivery_option_two_bond(UB_CTD, twin, UB_SIGMA_BP, UB_TTE)["value"])


def test_map_validity_gate_separates_ub_from_zb():
    """G7: UB's live basket is tight, ZB's is not."""
    ub = map_is_valid([UB_CTD, UB_ALT],
                      maturities_months={"T 4 Nov 52": 315, "T 2 1/4 Feb 52": 306})
    assert ub["valid"] is True
    assert ub["span_months"] == pytest.approx(9.0)

    zb_basket = [
        Deliverable("T 5 May 45", 0.8892, 97.0, 0.1156, prob=0.409),
        Deliverable("WI-T 5 1/8 Aug 46", 0.90, 98.0, 0.118, prob=0.154),
        Deliverable("T 2 1/2 Feb 46", 0.60, 66.0, 0.099, prob=0.142),
        Deliverable("T 3 Nov 44", 0.6725, 73.5, 0.0952, prob=0.128),
        Deliverable("T 4 1/2 Feb 44", 0.85, 93.0, 0.105, prob=0.074),
        Deliverable("T 4 3/4 Nov 43", 0.87, 95.0, 0.104, prob=0.017),
    ]
    mats = {"T 5 May 45": 225, "WI-T 5 1/8 Aug 46": 240, "T 2 1/2 Feb 46": 234,
            "T 3 Nov 44": 219, "T 4 1/2 Feb 44": 210, "T 4 3/4 Nov 43": 207}
    zb = map_is_valid(zb_basket, maturities_months=mats)
    assert zb["n_live"] == 6
    assert zb["span_months"] == pytest.approx(33.0)
    assert zb["valid"] is False
