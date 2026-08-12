"""ONE real trade, hand-traced from the tape row to the rendered word.

The fixture in ``tests/data/dd_sign_trace.json`` was produced by
``scratch/ddfe07_sign_trace.py`` against the real materialised tables, and it
is committed so this runs offline in the gate.

**Every assertion here names a side.** That is the point. A comparative test --
"the two directions differ", "z is invariant under rescaling" -- passes just as
happily when every sign in the system is flipped, which is exactly how an
inverted z-score survived a 59-test green suite during the backend work. Two
independent inversions were caught on that work; both produced completely
plausible output.

The TypeScript half of this trace is
``SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/dealerDirection.sign.test.ts``,
which reads **the same JSON file**, so the two halves cannot drift apart.
"""
from __future__ import annotations

import json
import math
import os
import pathlib

import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from SDRUtils._swappulse_scripts.backfill_dealer_direction import (  # noqa: E402
    direction_label,
)
from SDRUtils.dealer_direction import conventions as conv  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "data" / "dd_sign_trace.json"


@pytest.fixture(scope="module")
def trace():
    if not FIXTURE.exists():
        pytest.skip(
            f"{FIXTURE} not generated yet -- run "
            "scratch/ddfe07_sign_trace.py after a publish")
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


# ==========================================================================
# SEAM 1-2  the printed rate against the repriced mid
# ==========================================================================

def test_the_deviation_is_the_printed_rate_minus_the_mid_in_bp(trace):
    """`structure_price` takes PERCENT and returns BP, and `fixed_rate` is a
    decimal fraction. Three units in one line, so it is pinned."""
    traded_pct = trace["fixed_rate"] * 100.0
    price = conv.structure_price([traded_pct], "OUTRIGHT", 1, conv.RULE_RATE)
    # structure_price multiplies by 100 to get bp from percent.
    assert price == pytest.approx(traded_pct * 100.0, rel=1e-12)
    # And the stored deviation is that minus the mid, so a mid implied from it
    # is a sane rate rather than a hundredfold of one.
    mid_pct = traded_pct - trace["deviation_bps"] / 100.0
    assert 0.0 < mid_pct < 20.0, (
        f"implied mid {mid_pct}% is not a rate; the bp/percent scaling is wrong")


def test_an_outright_is_quoted_with_weight_plus_one(trace):
    assert conv.quote_weights("OUTRIGHT", 1, conv.RULE_RATE) == (1.0,)
    assert conv.base_orientation("OUTRIGHT", 1, conv.RULE_RATE) == (1,)


# ==========================================================================
# SEAM 3  deviation -> probability, recomputed away from the code
# ==========================================================================

def test_p_is_the_logistic_of_the_bias_corrected_deviation(trace):
    z = (trace["deviation_bps"] - trace["mid_bias_bps"]) / trace["tau_bps"]
    p_hand = 1.0 / (1.0 + math.exp(-z))
    assert trace["p"] == pytest.approx(p_hand, rel=1e-9), (
        "the stored p is not sigmoid((dev - b0)/tau) computed by hand"
    )


def test_the_weight_is_2p_minus_1_and_not_p(trace):
    assert trace["signed_weight"] == pytest.approx(
        2.0 * trace["p"] - 1.0, abs=1e-12)
    assert trace["signed_weight"] == pytest.approx(
        conv.signed_weight(trace["p"]), abs=1e-12)
    # The near-miss this exists to exclude: at p = 0.9, `p` is 0.9 and `2p-1`
    # is 0.8. Both are plausible-looking numbers and only one is a position.
    assert trace["signed_weight"] != pytest.approx(trace["p"], abs=1e-6)


# ==========================================================================
# SEAM 4  the sign becomes a word
# ==========================================================================

def test_a_print_ABOVE_mid_means_the_dealer_RECEIVED(trace):
    """The whole convention, on a real number, with the side named.

        printed above mid -> the customer paid up -> the customer PAID fixed
        -> the dealer RECEIVED fixed -> the dealer is LONG duration
        -> delta_dv01 > 0
    """
    dev_corrected = trace["deviation_bps"] - trace["mid_bias_bps"]
    if dev_corrected > 0:
        assert trace["p"] > 0.5
        assert trace["signed_weight"] > 0
        assert trace["dealer_sign"] == conv.DEALER_RECEIVED == 1
        assert trace["dealer_direction"] == "RECEIVED"
        assert trace["total_delta_dv01"] > 0
    else:
        assert trace["p"] < 0.5
        assert trace["signed_weight"] < 0
        assert trace["dealer_sign"] == conv.DEALER_PAID == -1
        assert trace["dealer_direction"] == "PAID"
        assert trace["total_delta_dv01"] < 0


def test_dealer_side_agrees_with_the_stored_sign(trace):
    assert conv.dealer_side(
        trace["deviation_bps"] - trace["mid_bias_bps"]) == trace["dealer_sign"]


def test_the_label_function_gives_the_stored_word(trace):
    assert direction_label(trace["dealer_sign"], None) == \
        trace["dealer_direction"]


def test_the_mirror_of_this_trade_would_render_the_other_word(trace):
    """The one assertion a global flip cannot survive.

    Every test above could be satisfied by a system in which every sign is
    reversed. This one names both sides of the same arithmetic.
    """
    assert direction_label(trace["dealer_sign"], None) == \
        trace["dealer_direction"]
    assert direction_label(-trace["dealer_sign"], None) != \
        trace["dealer_direction"]
    assert {direction_label(1, None), direction_label(-1, None)} == \
        {"RECEIVED", "PAID"}
    assert direction_label(1, None) == "RECEIVED"


# ==========================================================================
# SEAM 5  the signed key-rate profile
# ==========================================================================

def test_delta_dv01_is_the_weight_times_the_received_dv01(trace):
    for b in trace["buckets"]:
        assert float(b["delta_dv01"]) == pytest.approx(
            float(b["signed_weight"]) * float(b["dv01_if_received"]),
            rel=1e-9, abs=1e-6)


def test_the_summed_profile_carries_the_direction(trace):
    total = sum(float(b["delta_dv01"]) for b in trace["buckets"])
    assert total == pytest.approx(trace["total_delta_dv01"], rel=1e-9, abs=1e-6)
    assert (total > 0) == (trace["dealer_sign"] > 0), (
        "the signed key-rate profile points the opposite way from the call"
    )


def test_the_unit_landed_in_the_ladder_at_all(trace):
    assert trace["rule"] == "RATE_VS_MID"
    assert trace["buckets"], "a called unit with no risk profile"
    assert trace["p"] > 0.90, (
        "the trace should pin a DECISIVE print -- a marginal one would let a "
        "sign error hide inside the dead zone"
    )
