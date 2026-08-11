"""The sign convention, pinned.

The point of this file is that a flipped sign in dealer-direction inference
produces a complete, plausible, exactly-wrong ladder. So the convention is
pinned three ways: against the frozen predecessor, against worked economics,
and against its own internal invariants.
"""
from __future__ import annotations

import pytest

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.stir_flow import ladder_conventions as frozen


# --------------------------------------------------------------------------
# 1. Reproduce the frozen predecessor exactly.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("direction", ["PAID", "RECEIVED"])
@pytest.mark.parametrize(
    ("kind", "n_legs", "rule"),
    [
        ("OUTRIGHT", 1, conv.RULE_RATE),
        ("CURVE", 2, conv.RULE_RATE),
        ("FLY", 3, conv.RULE_RATE),
        ("OUTRIGHT", 1, conv.RULE_UPFRONT),
        ("CURVE", 2, conv.RULE_UPFRONT),
        ("FLY", 3, conv.RULE_UPFRONT),
        ("PKG", 7, conv.RULE_UPFRONT),
    ],
)
def test_matches_frozen_dealer_leg_signs(kind, n_legs, rule, direction):
    """The new general rule must agree leg-for-leg with `stir_flow`.

    `stir_flow.ladder_conventions.dealer_leg_signs` is the convention the
    persisted ladder was built under. If the generalisation disagrees with it
    on the cases it covers, the generalisation is wrong -- a prior
    investigation established that the old classifier is correct and that an
    apparent bug in it was a charting artefact.
    """
    dealer_sign = conv.DEALER_RECEIVED if direction == "RECEIVED" else conv.DEALER_PAID
    method = "NPV_VS_UPFRONT" if rule == conv.RULE_UPFRONT else "RATE_VS_MID"

    expected = frozen.dealer_leg_signs(kind, method, direction, n_legs)
    actual = conv.dealer_received_signs(kind, n_legs, rule, dealer_sign)

    assert list(actual) == list(expected)


# --------------------------------------------------------------------------
# 2. Worked economics, independent of both implementations.
# --------------------------------------------------------------------------

def test_outright_above_mid_means_dealer_received():
    """The core rule, stated in the brief and in every docstring here.

    A customer paying fixed at 3.51% when mid is 3.50% has paid a basis point
    over mid. The dealer took the other side, so the dealer received fixed and
    is long duration.
    """
    p_traded = conv.structure_price([3.51], "OUTRIGHT", 1, conv.RULE_RATE)
    p_mid = conv.structure_price([3.50], "OUTRIGHT", 1, conv.RULE_RATE)

    assert p_traded - p_mid == pytest.approx(1.0)          # bp, percent in
    assert conv.dealer_side(p_traded - p_mid) == conv.DEALER_RECEIVED
    # long duration: the dealer receives fixed on its only leg
    assert conv.dealer_received_signs("OUTRIGHT", 1, conv.RULE_RATE,
                                      conv.DEALER_RECEIVED) == (1,)


def test_curve_price_is_back_minus_front():
    """A curve is quoted as the longer leg minus the shorter."""
    price = conv.structure_price([3.20, 3.52], "CURVE", 2, conv.RULE_RATE)
    assert price == pytest.approx(32.0)


def test_fly_price_is_two_belly_minus_wings():
    price = conv.structure_price([3.30, 3.45, 3.61], "FLY", 3, conv.RULE_RATE)
    assert price == pytest.approx((2 * 3.45 - 3.30 - 3.61) * 100.0)


def test_curve_traded_wide_puts_dealer_receiving_the_back_leg():
    """A steepener paid above mid: the dealer ends up receiving the back leg.

    Traded 32bp against a 30bp mid. The base party pays the structure, so the
    base party is the customer, and the dealer holds the opposite: paying the
    front leg and receiving the back one.
    """
    s2m = (conv.structure_price([3.20, 3.52], "CURVE", 2, conv.RULE_RATE)
           - conv.structure_price([3.20, 3.50], "CURVE", 2, conv.RULE_RATE))
    assert s2m == pytest.approx(2.0)

    side = conv.dealer_side(s2m)
    assert side == conv.DEALER_RECEIVED
    front, back = conv.dealer_received_signs("CURVE", 2, conv.RULE_RATE, side)
    assert (front, back) == (-1, 1)


def test_upfront_rule_uses_the_net_fixed_frame():
    """One fee cannot resolve a package's internal orientation, only its net side.

    So under the upfront rule every leg carries the same sign -- which is what
    makes it usable on a PKG-N the rate rule cannot orient at all.
    """
    for n in (1, 2, 3, 17):
        signs = conv.dealer_received_signs("PKG", n, conv.RULE_UPFRONT,
                                           conv.DEALER_RECEIVED)
        assert signs == (1,) * n


# --------------------------------------------------------------------------
# 3. Internal invariants.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("kind", "n_legs"),
    [("OUTRIGHT", 1), ("CURVE", 2), ("FLY", 3)],
)
def test_quote_weight_signs_match_the_base_orientation(kind, n_legs):
    """`P` must be the price the base party pays, or the general rule breaks."""
    o = conv.base_orientation(kind, n_legs, conv.RULE_RATE)
    q = conv.quote_weights(kind, n_legs, conv.RULE_RATE)
    assert [1 if w > 0 else -1 for w in q] == list(o)


@pytest.mark.parametrize(
    ("kind", "n_legs"),
    [("OUTRIGHT", 1), ("CURVE", 2), ("FLY", 3), ("PKG", 9)],
)
@pytest.mark.parametrize("rule", [conv.RULE_RATE, conv.RULE_UPFRONT])
def test_the_two_dealer_sides_are_exact_opposites(kind, n_legs, rule):
    try:
        recv = conv.dealer_received_signs(kind, n_legs, rule, conv.DEALER_RECEIVED)
        paid = conv.dealer_received_signs(kind, n_legs, rule, conv.DEALER_PAID)
    except conv.UnorientableUnit:
        pytest.skip("no quote convention for this shape under this rule")
    assert list(recv) == [-s for s in paid]


def test_pkg_n_is_unorientable_under_the_rate_rule_not_guessed():
    """Excluded loudly rather than force-classified.

    Forcing an orientation on a package with no standard quote manufactures a
    confident direction out of nothing, which is worse than a gap.
    """
    with pytest.raises(conv.UnorientableUnit):
        conv.base_orientation("PKG", 5, conv.RULE_RATE)
    with pytest.raises(conv.UnorientableUnit):
        conv.base_orientation("CURVE", 3, conv.RULE_RATE)


# --------------------------------------------------------------------------
# 4. The two defects this package exists partly to fix.
# --------------------------------------------------------------------------

def test_exact_tie_makes_no_call():
    """`stir_flow` ends `RECEIVED if s2m > 0 else PAID` -- no zero branch.

    Measured consequence: on 2026-07-17, three of 376 on-market units had
    `spread_to_mid_bps` of exactly 0.0 and were all silently labelled PAID, and
    one unit's side was decided by a 1.33e-13 float. A tie is not a side.
    """
    assert conv.dealer_side(0.0) == 0
    with pytest.raises(ValueError, match="no call"):
        conv.dealer_received_signs("OUTRIGHT", 1, conv.RULE_RATE, 0)


def test_signed_weight_is_zero_at_a_coin_flip():
    """`p`-weighting a coin flip contributes half a long position; `2p-1` does not."""
    assert conv.signed_weight(0.5) == 0.0
    assert conv.signed_weight(1.0) == 1.0
    assert conv.signed_weight(0.0) == -1.0
    assert conv.signed_weight(0.75) == pytest.approx(0.5)
    # monotone in p, and antisymmetric about 0.5
    assert conv.signed_weight(0.9) == pytest.approx(-conv.signed_weight(0.1))


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_signed_weight_rejects_a_non_probability(bad):
    with pytest.raises(ValueError):
        conv.signed_weight(bad)


def test_the_futures_equivalent_flip_is_one_constant():
    """One constant for every bucket space.

    `stir_flow/ladder.py` carried a per-space dict here and it inverted three
    of the four spaces; the persisted table showed FED_FUNDS 288 PAID-positive
    against MEETING 868/868 PAID-negative. A per-space sign cannot be right,
    because every risk model in this repo is calibrated in rate space.
    """
    assert conv.RL_DELTA_TO_FUTURES_EQ == -1.0
    assert isinstance(conv.RL_DELTA_TO_FUTURES_EQ, float)
