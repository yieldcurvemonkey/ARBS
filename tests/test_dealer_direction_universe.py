"""Unit construction, the eligibility filters, and the risk-plausibility gate.

Every case here pins a decision that was made from a measurement on the v3
tape, and most of them pin a failure mode that is *silent*: a unit that is
kept when it should not be still produces a confident direction, and a leg
order that is merely a partial order still produces a fly, just not the same
one twice.

Offline only -- the prod-Postgres validation lives behind
``python -m SDRUtils.dealer_direction.sanity --validate`` and
``python -m SDRUtils.dealer_direction.universe --report``, which is where a
database belongs.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from SDRUtils.dealer_direction import sanity, types, universe

# ---------------------------------------------------------------------------
# synthetic legs
# ---------------------------------------------------------------------------

_AS_OF = datetime.date(2026, 6, 16)
_EXEC = pd.Timestamp("2026-06-16 14:15:36", tz="UTC")


def _leg(**kw) -> dict:
    """One plausible on-market SOFR outright leg. Override what a test needs."""
    base = {
        "trade_id": "T1",
        "package_id": "P1",
        "leg_order": 0,
        "as_of_date": _AS_OF,
        "execution_timestamp": _EXEC,
        "original_execution_timestamp": _EXEC,
        "event_timestamp": _EXEC,
        "event_timestamp_granularity": "SECOND",
        "report_lag_seconds": 0.0,
        "lifecycle_type": "NEW_TRADE",
        "economic_class": "ECONOMIC_FLOW",
        "contributes_to_flow": True,
        "effective_date": datetime.date(2026, 6, 18),
        "expiration_date": datetime.date(2031, 6, 18),
        "tenor_years": 5.0,
        "forward_start_years": 0.0,
        "notional": 1e8,
        "risk": 45_300.0,
        "fixed_rate": 0.0395,
        "other_payment_amount": 0.0,
        "other_payment_ufro": 0.0,
        "other_payment_uwin": 0.0,
        "other_payment_pexh": 0.0,
        "package_transaction_price": None,
        "trade_type": "OUTRIGHT",
        "rate_index_clean": "SOFR",
        "special_tenor_type": "STANDARD",
        "upi_notional_schedule": "Constant",
        "leg_tape_label": "USD SOFR 5Y",
        "platform_identifier": "TWSF",
        "venue": "D2C",
        "cleared": "I",
        "is_mac": False,
        "is_capped": False,
        "is_block": False,
        "is_off_market": False,
        "is_exercise_born": False,
        "is_novation": False,
        "is_novation_born": False,
        "is_novation_terminated": False,
    }
    base.update(kw)
    return base


def _frame(*legs: dict) -> pd.DataFrame:
    return pd.DataFrame(list(legs))


def _one(*legs: dict):
    """Build the single unit these legs describe, or raise if it was excluded."""
    units, excl = universe.build_universe(_frame(*legs))
    assert len(units) + len(excl) == 1, (len(units), len(excl))
    return units[0] if units else None


def _reason(*legs: dict) -> tuple:
    units, excl = universe.build_universe(_frame(*legs))
    assert len(units) + len(excl) == 1, (len(units), len(excl))
    if units:
        return (None, None)
    row = excl.iloc[0]
    return (row["exclusion"], row["exclusion_detail"])


# ===========================================================================
# 1. the total leg order
# ===========================================================================

def test_leg_order_is_total_and_independent_of_input_row_order():
    """A partial order is not reproducible, and the failure is invisible.

    ``trade_selection.py``'s own comment says it: ``expiration_date`` alone is
    not unique inside a package, and Postgres is free to return tied rows in
    whatever physical order it likes, which varies per query. That moves the
    FLY belly and ``iloc[0]`` between runs -- so ``structure_dv01`` and the
    inferred side change with nothing but the plan.
    """
    # The trade_ids are chosen so the correct order is NOT the lexicographic
    # trade_id order and NOT the expiration-only order -- otherwise a sort that
    # had lost a key would still produce the expected answer, and a mutation
    # sweep found exactly that in the first version of this case.
    legs = [
        _leg(trade_id="A", expiration_date=datetime.date(2031, 6, 18),
             effective_date=datetime.date(2026, 6, 18)),
        _leg(trade_id="Z", expiration_date=datetime.date(2028, 6, 18),
             effective_date=datetime.date(2026, 6, 18)),
        # ties A on expiration, breaks on effective -- and sorts BEFORE it only
        # if effective_date is actually consulted
        _leg(trade_id="M", expiration_date=datetime.date(2031, 6, 18),
             effective_date=datetime.date(2026, 6, 17)),
    ]
    want = ["Z", "M", "A"]
    assert want != sorted(want)                       # not the trade_id order
    for perm in ([0, 1, 2], [2, 1, 0], [1, 0, 2], [1, 2, 0]):
        unit = _one(*[legs[i] for i in perm])
        assert list(unit.legs["trade_id"]) == want, perm
        assert unit.legs.index.tolist() == [0, 1, 2]


def test_leg_order_ties_on_all_three_keys_still_reproduce():
    """Three keys are only a total order because the tape makes them one.

    Measured: ``(package_id, expiration_date, effective_date, trade_id)`` has
    zero duplicate groups over all 2,326,781 rows. ``leg_order`` is carried as
    a final tiebreaker anyway so a future tape that breaks that property
    degrades to a different order rather than to a random one.
    """
    a = _leg(trade_id="X", leg_order=1)
    b = _leg(trade_id="X", leg_order=0)
    unit = _one(a, b)
    assert list(unit.legs["leg_order"]) == [0, 1]


# ===========================================================================
# 2. no maturity cutoff -- the whole point of the task
# ===========================================================================

def test_thirty_year_unit_is_kept():
    """``config.SUB3Y_HORIZON_DAYS = 1105`` threw away 69.7% of flow legs."""
    unit = _one(_leg(expiration_date=datetime.date(2056, 6, 18),
                     tenor_years=30.0, risk=170_000.0))
    assert unit is not None
    assert unit.kind == "OUTRIGHT"


def test_deep_forward_start_is_kept():
    unit = _one(_leg(effective_date=datetime.date(2046, 6, 18),
                     expiration_date=datetime.date(2051, 6, 18),
                     tenor_years=5.0, forward_start_years=20.0,
                     risk=20_400.0))
    assert unit is not None


# ===========================================================================
# 3. exclusions -- one reason each, from the pinned vocabulary
# ===========================================================================

_VOCAB = {
    types.EXCL_RISK_IMPLAUSIBLE, types.EXCL_UNORIENTABLE,
    types.EXCL_NO_FIXED_RATE, types.EXCL_NOT_FLOW,
    types.EXCL_STANDARD_COUPON, types.EXCL_EXERCISE_OR_NOVATION,
    types.EXCL_NO_CURVE, types.EXCL_PRICING_ERROR, types.EXCL_DEAD_ZONE,
    types.EXCL_UNSUPPORTED_INDEX,
}


def test_every_exclusion_constant_is_from_the_types_vocabulary():
    assert set(universe.EXCLUSION_PRECEDENCE) <= _VOCAB


@pytest.mark.parametrize("kw,want", [
    ({"contributes_to_flow": False}, types.EXCL_NOT_FLOW),
    ({"rate_index_clean": "BASIS", "fixed_rate": None},
     types.EXCL_UNSUPPORTED_INDEX),
    ({"rate_index_clean": "OTHER"}, types.EXCL_UNSUPPORTED_INDEX),
    ({"leg_tape_label": "USD CME Term SOFR 3M 5Y"},
     types.EXCL_UNSUPPORTED_INDEX),
    ({"trade_type": "SPREADOVER"}, types.EXCL_UNORIENTABLE),
    ({"trade_type": "MATCHED_MATURITY_FLY"}, types.EXCL_UNORIENTABLE),
    ({"trade_type": "INVOICE_SWITCH"}, types.EXCL_UNORIENTABLE),
    ({"is_exercise_born": True}, types.EXCL_EXERCISE_OR_NOVATION),
    ({"is_novation_born": True}, types.EXCL_EXERCISE_OR_NOVATION),
    ({"upi_notional_schedule": "Amortizing"}, types.EXCL_PRICING_ERROR),
    ({"upi_notional_schedule": "Accreting"}, types.EXCL_PRICING_ERROR),
    # 11,960 flow legs, the second-largest non-bullet family after Amortizing
    # -- and the one the label-token filter this module replaced never saw.
    ({"upi_notional_schedule": "Custom"}, types.EXCL_PRICING_ERROR),
    ({"notional": 1e20, "fixed_rate": 9.9, "risk": 3.96072e15},
     types.EXCL_RISK_IMPLAUSIBLE),
    ({"fixed_rate": None}, types.EXCL_NO_FIXED_RATE),
])
def test_single_gate_reasons(kw, want):
    got, _ = _reason(_leg(**kw))
    assert got == want


def test_basis_leg_reads_as_unsupported_index_not_missing_rate():
    """Precedence: *what product is this* beats *its numbers are missing*.

    All 15,245 flow legs with ``rate_index_clean='BASIS'`` also carry a NULL
    ``fixed_rate``, so both gates fire. ``UNSUPPORTED_INDEX`` is the one that
    tells a reader anything.
    """
    got, _ = _reason(_leg(rate_index_clean="BASIS", fixed_rate=None,
                          notional=None, risk=None))
    assert got == types.EXCL_UNSUPPORTED_INDEX


def test_a_unit_failing_several_gates_reports_exactly_the_pinned_one():
    got, _ = _reason(_leg(contributes_to_flow=False, rate_index_clean="BASIS",
                          fixed_rate=None, trade_type="SPREADOVER",
                          upi_notional_schedule="Amortizing"))
    assert got == types.EXCL_NOT_FLOW


def test_exclusion_is_a_unit_property_not_a_leg_property():
    """One bad leg condemns the package: the unit has one price."""
    got, _ = _reason(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18),
             rate_index_clean="OTHER"),
    )
    assert got == types.EXCL_UNSUPPORTED_INDEX


#: One entry per ``any``-aggregated gate in :func:`universe.unit_frame`, as the
#: defect applied to the SECOND leg of a two-leg package only. Kept as a list
#: rather than folded into ``test_single_gate_reasons`` because a single-leg
#: unit cannot tell ``any`` from ``all`` -- that test passes either way, and the
#: case above only pins ``bad_index`` incidentally (the ``n_index > 1`` gate
#: catches it too, so ``bad_index`` may flip to ``all`` with nothing going red).
_ONE_BAD_LEG = [
    ({"contributes_to_flow": False}, types.EXCL_NOT_FLOW),
    ({"is_novation": True}, types.EXCL_EXERCISE_OR_NOVATION),
    # A NULL index isolates `bad_index` from the `n_index > 1` gate, because
    # `nunique` skips NaN: n_index reads 1. SYNTHETIC -- measured on v3, no
    # package carries a NULL rate_index_clean and no package mixes indices, so
    # this shape pins the invariant rather than a live population.
    ({"rate_index_clean": None}, types.EXCL_UNSUPPORTED_INDEX),
    ({"leg_tape_label": "USD CME Term SOFR 3M 5Y"}, types.EXCL_UNSUPPORTED_INDEX),
    ({"trade_type": "SPREADOVER"}, types.EXCL_UNORIENTABLE),
    ({"upi_notional_schedule": "Amortizing"}, types.EXCL_PRICING_ERROR),
    # LIVE: 107 multi-leg packages carry a NULL `risk` on some-but-not-all legs.
    ({"risk": None}, types.EXCL_RISK_IMPLAUSIBLE),
    # LIVE: 136 multi-leg packages carry a NULL `fixed_rate` on some-but-not-all.
    ({"fixed_rate": None}, types.EXCL_NO_FIXED_RATE),
    ({"is_mac": True}, types.EXCL_STANDARD_COUPON),
]


@pytest.mark.parametrize("kw,want", _ONE_BAD_LEG)
def test_one_bad_leg_condemns_the_package_for_every_gate(kw, want):
    """``any``, not ``all`` -- and it has to be pinned gate by gate.

    The unit has one price, so a package priced with a missing rate or a
    missing risk on one of its legs is not partly wrong, it is wrong. Measured
    on v3: **136** multi-leg packages carry a NULL ``fixed_rate`` on some but
    not all legs and **107** carry a NULL ``risk``. Under ``all`` those are
    admitted and priced with the missing field, silently and in one direction.
    """
    got, _ = _reason(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18), **kw),
    )
    assert got == want


#: The order, written out here rather than read from the module. Deriving the
#: expectation from :data:`universe.EXCLUSION_PRECEDENCE` makes the case
#: self-fulfilling -- a swap of two entries just relabels the parameters and
#: every assertion still holds. (Measured: the first version of this case did
#: exactly that, and the mutation sweep caught it, not the suite.)
_EXPECTED_PRECEDENCE = (
    types.EXCL_NOT_FLOW,
    types.EXCL_EXERCISE_OR_NOVATION,
    types.EXCL_UNSUPPORTED_INDEX,
    types.EXCL_UNORIENTABLE,
    types.EXCL_PRICING_ERROR,
    types.EXCL_RISK_IMPLAUSIBLE,
    types.EXCL_NO_FIXED_RATE,
    types.EXCL_STANDARD_COUPON,
)

#: One reachable defect per constant, each tripping that gate and no other.
_PRECEDENCE_DEFECT = {
    types.EXCL_NOT_FLOW: {"contributes_to_flow": False},
    types.EXCL_EXERCISE_OR_NOVATION: {"is_novation": True},
    types.EXCL_UNSUPPORTED_INDEX: {"rate_index_clean": "OTHER"},
    types.EXCL_UNORIENTABLE: {"trade_type": "SPREADOVER"},
    types.EXCL_PRICING_ERROR: {"upi_notional_schedule": "Amortizing"},
    types.EXCL_RISK_IMPLAUSIBLE: {"risk": None},
    types.EXCL_NO_FIXED_RATE: {"fixed_rate": None},
    types.EXCL_STANDARD_COUPON: {"is_mac": True},
}


def test_the_precedence_is_the_order_this_file_says_it_is():
    """The literal above is the pin; this is where a reorder has to show up."""
    assert universe.EXCLUSION_PRECEDENCE == _EXPECTED_PRECEDENCE
    assert set(_PRECEDENCE_DEFECT) == set(_EXPECTED_PRECEDENCE)


@pytest.mark.parametrize("earlier,later", list(zip(
    _EXPECTED_PRECEDENCE, _EXPECTED_PRECEDENCE[1:])))
def test_every_adjacent_pair_of_the_precedence_is_pinned(earlier, later):
    """A unit carries exactly ONE reason, so the order is the accounting.

    ``EXCLUSION_PRECEDENCE`` is documented as "most informative answer first",
    not cheapest-test-first, and the whole coverage table is grouped by the
    constant it picks. Reordering it does not change what is *admitted*, so no
    admission test can see it -- it changes which line of the report a
    population lands on, which is the number the report exists to produce.
    Only the top of the tuple and the BASIS/NO_FIXED_RATE pair were pinned.
    """
    kw = dict(_PRECEDENCE_DEFECT[earlier])
    kw.update(_PRECEDENCE_DEFECT[later])
    got, _ = _reason(_leg(**kw))
    assert got == earlier


def test_term_sofr_and_a_mixed_index_are_told_apart_in_the_accounting():
    """One constant, three populations, and the report has to separate them.

    ``UNSUPPORTED_INDEX`` covers a BASIS/OTHER leg, a package mixing indices,
    and a CME Term SOFR print. The detail string is the only thing that keeps
    them apart, and it is the largest of the three -- 33,487 legs -- that would
    otherwise read as a package-construction problem rather than as the index
    gap it is. ``exclusion_detail`` is what ``by_reason`` groups on.
    """
    assert _reason(_leg(leg_tape_label="USD CME Term SOFR 3M 5Y")) == (
        types.EXCL_UNSUPPORTED_INDEX, "CME_TERM_SOFR")
    assert _reason(_leg(rate_index_clean="OTHER")) == (
        types.EXCL_UNSUPPORTED_INDEX, "OTHER")


def test_a_package_that_mixes_platforms_has_no_venue_class():
    """Measured zero on v3 -- and the alternative is worse than a gap.

    Without the guard the unit inherits whichever leg sorted first, so a
    package half-executed on an IDB reads D2C and lands in the primary customer
    series. That is the expensive direction of the venue asymmetry the whole
    ``VENUE_EVIDENCE`` table is built around, taken silently.
    """
    unit = _one(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18),
             platform_identifier="TWSF"),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18),
             platform_identifier="DWSF"),
    )
    assert unit.venue_class == types.VENUE_UNKNOWN


def test_a_package_mixing_two_supported_indices_is_still_unsupported():
    """The other half of the pair above: ``n_index > 1`` with no bad leg.

    SOFR and FED_FUNDS are both supported, so ``bad_index`` never fires and
    this gate is the only thing standing between a SOFR/FF package and a single
    curve pricing both of its legs. Measured zero on v3 -- no package mixes
    ``rate_index_clean`` -- which is exactly why the two gates were free to
    cover for each other with nothing going red.
    """
    got, detail = _reason(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18),
             rate_index_clean="FED_FUNDS"),
    )
    assert got == types.EXCL_UNSUPPORTED_INDEX
    assert detail == "MIXED_INDEX"


# ===========================================================================
# 4. standard coupons: MAC yes, IMM no -- both measured
# ===========================================================================

def test_mac_with_an_upfront_is_kept():
    """MAC is off-market *by construction* -- and that is why it is kept.

    Measured: 98.85% of MAC flow legs carry an other payment, and every MAC
    fixed rate on the tape is one of seven values on a 25bp grid. Routing is
    on upfront presence (D6), so a MAC unit lands on the upfront rule by
    itself; excluding it threw away 14,877 units of the cleanest upfront-rule
    population there is.
    """
    unit = _one(_leg(is_mac=True, trade_type="MAC", fixed_rate=0.035,
                     other_payment_amount=250_000.0,
                     other_payment_ufro=250_000.0))
    assert unit is not None
    assert unit.upfront == pytest.approx(250_000.0)


def test_mac_without_any_upfront_is_excluded():
    """149 units on the whole tape. Off-market coupon, nothing to price it
    against, and the rate rule would call it hugely and wrongly."""
    got, _ = _reason(_leg(is_mac=True, trade_type="MAC", fixed_rate=0.035))
    assert got == types.EXCL_STANDARD_COUPON


def test_imm_is_not_treated_as_a_standard_coupon():
    """The brief's premise, refuted by measurement.

    IMM flow legs carry an upfront on 37.7% against an outright baseline of
    40.9%, and their fixed rates sit on a free grid. An IMM-dated swap is a
    market-rate trade with an IMM effective date; it is not a standard coupon.
    """
    unit = _one(_leg(trade_type="IMM", special_tenor_type="IMM",
                     fixed_rate=0.038614))
    assert unit is not None
    unit2 = _one(_leg(special_tenor_type="IMM", fixed_rate=0.038614))
    assert unit2 is not None


# ===========================================================================
# 5. structures
# ===========================================================================

@pytest.mark.parametrize("n,kind", [(1, "OUTRIGHT"), (2, "CURVE"), (3, "FLY")])
def test_kind_from_leg_count(n, kind):
    legs = [_leg(trade_id=f"T{i}",
                 expiration_date=datetime.date(2028 + i, 6, 18))
            for i in range(n)]
    unit = _one(*legs)
    assert unit.kind == kind
    assert unit.n_legs == n


def test_fly_belly_is_iloc_1_and_curve_front_is_iloc_0():
    """``conventions.base_orientation`` says it assumes exactly this.

    ``(-1, +1, -1)`` for a fly means "pay the belly, receive the wings", and
    the belly is index 1 *only if* the legs are maturity-ordered. If the order
    slips, the fly is priced with the wrong leg in the middle and the answer
    is wrong without being odd-looking.
    """
    from SDRUtils.dealer_direction import conventions as cv

    legs = [
        _leg(trade_id="BACK", expiration_date=datetime.date(2036, 6, 18)),
        _leg(trade_id="BELLY", expiration_date=datetime.date(2031, 6, 18)),
        _leg(trade_id="FRONT", expiration_date=datetime.date(2028, 6, 18)),
    ]
    unit = _one(*legs)
    assert unit.kind == "FLY"
    assert list(unit.legs["trade_id"]) == ["FRONT", "BELLY", "BACK"]
    assert unit.legs.iloc[1]["trade_id"] == "BELLY"
    o = cv.base_orientation(unit.kind, unit.n_legs, cv.RULE_RATE)
    assert o[1] == 1 and o[0] == o[2] == -1        # pays the belly
    curve = _one(legs[0], legs[2])
    assert curve.legs.iloc[0]["trade_id"] == "FRONT"


def test_four_leg_package_is_unorientable():
    """DESIGN §3: no market quote convention fixes the base orientation of a
    PKG-N, so forcing one manufactures a confident direction from nothing."""
    legs = [_leg(trade_id=f"T{i}",
                 expiration_date=datetime.date(2028 + i, 6, 18))
            for i in range(4)]
    got, _ = _reason(*legs)
    assert got == types.EXCL_UNORIENTABLE


def test_unit_key_is_trade_id_for_a_singleton_and_package_id_otherwise():
    """The tie-out join is keyed on this, so it is not free to change."""
    assert _one(_leg(trade_id="T9", package_id="P9")).unit_key == "T9"
    two = _one(_leg(trade_id="A", package_id="P9",
                    expiration_date=datetime.date(2028, 6, 18)),
               _leg(trade_id="B", package_id="P9",
                    expiration_date=datetime.date(2031, 6, 18)))
    assert two.unit_key == "P9"
    assert two.package_id == "P9"


# ===========================================================================
# 6. venue
# ===========================================================================

@pytest.mark.parametrize("pid,want", [
    ("TWSF", types.VENUE_D2C),          # incumbent whitelist
    ("BBSF", types.VENUE_D2C),
    ("BILT", types.VENUE_D2C),
    ("TREU", types.VENUE_D2C),          # added, registry tier
    ("TWEM", types.VENUE_D2C),
    ("BMTF", types.VENUE_D2C),
    ("BTFE", types.VENUE_D2C),
    ("TRWB", types.VENUE_D2C),
    ("DWSF", types.VENUE_D2D),          # incumbent D2D
    ("TSEF", types.VENUE_D2D),
    ("ISWE", types.VENUE_D2D),          # added, registry tier
    ("GSEF", types.VENUE_D2D),
    ("BGCO", types.VENUE_D2D),
    ("RTXF", types.VENUE_D2D),          # added, fingerprint tier
    ("XXXX", types.VENUE_UNKNOWN),      # not a venue
    ("XOFF", types.VENUE_UNKNOWN),
    ("ZZZZ", types.VENUE_UNKNOWN),
    ("BNPS", types.VENUE_UNKNOWN),      # single-dealer, no registry entry
    ("THRE", types.VENUE_UNKNOWN),      # FX/NDF venue, deliberately not loaded
    (None, types.VENUE_UNKNOWN),
])
def test_venue_classes(pid, want):
    assert universe.classify_venue(pid) == want


def test_no_fingerprint_evidence_platform_is_ever_promoted_to_d2c():
    """The asymmetry is the whole safeguard.

    A wrong D2D call costs nothing -- D2D is tagged and kept as its own
    series, never as customer flow. A wrong D2C call contaminates the primary
    series. So fingerprint evidence may promote a platform to D2D and never to
    D2C; D2C needs a named operator.
    """
    for pid, (cls, tier) in universe.VENUE_EVIDENCE.items():
        if tier == universe.EVIDENCE_FINGERPRINT:
            assert cls != types.VENUE_D2C, pid


def test_off_facility_codes_are_separable_from_merely_unrecognised_ones():
    assert universe.venue_evidence("XOFF") == universe.EVIDENCE_OFF_FACILITY
    assert universe.venue_evidence("ZZZZ") == universe.EVIDENCE_UNRECOGNISED
    assert universe.venue_evidence("TWSF") == universe.EVIDENCE_REGISTRY


def test_d2d_units_are_kept_not_excluded():
    unit = _one(_leg(platform_identifier="DWSF", venue="D2D"))
    assert unit is not None
    assert unit.venue_class == types.VENUE_D2D


@pytest.mark.parametrize("pid,want", [
    ("TWSF", True), ("BBSF", True), ("TREU", True), ("BMTF", True),
    ("DWSF", True), ("ISWE", True), ("RTXF", True), ("twsf", True),
    # off-facility: BILT names an arranger, XXXX/XOFF name nobody, but all
    # three executed away from a SEF/MTF and take the off-facility delay.
    ("BILT", False), ("XXXX", False), ("XOFF", False),
    # unrecognised -> None, NOT False
    ("ZZZZ", None), ("BNPS", None), ("CBNL", None), (None, None), ("", None),
])
def test_on_facility_is_a_tri_state_and_venue_class_does_not_decide_it(pid, want):
    """The availability clock for a quarter of the tape hangs on this.

    ``BILT`` is D2C **and** off-facility, so the venue class cannot answer the
    question -- that is why the two sets exist separately. And the third state
    is not decoration: ``visibility_class`` tests ``is True`` / ``is False``,
    so ``None`` falls to INDETERMINATE (+60 min) instead of borrowing a delay
    class the code has no evidence for. Reading an unrecognised platform as
    ``False`` would hand it the off-facility class it was never shown to be in.
    """
    assert universe.on_facility(pid) is want


def test_on_facility_agrees_with_the_evidence_registry_it_is_derived_from():
    """No entry may be on-facility and off-facility at once."""
    for pid in universe.VENUE_EVIDENCE:
        assert universe.on_facility(pid) is (pid not in
                                             universe.OFF_FACILITY_PLATFORMS)
    for pid in universe.OFF_FACILITY_PLATFORMS:
        assert universe.on_facility(pid) is False


@pytest.mark.parametrize("kw,cls,minutes", [
    ({"platform_identifier": "TWSF"}, "ON_FACILITY_NON_BLOCK", 1),
    ({"platform_identifier": "TWSF", "is_block": True}, "SEF_BLOCK", 15),
    # BILT is 325,595 legs and XXXX/XOFF another 80,725: an off-facility read
    # of `True` moves every one of them from +30 to +1, i.e. it shortens the
    # availability clock -- lookahead -- for a quarter of the tape.
    ({"platform_identifier": "BILT", "cleared": "N"},
     "UNCLEARED_OFF_FACILITY", 30),
    ({"platform_identifier": "XXXX", "cleared": "N"},
     "UNCLEARED_OFF_FACILITY", 30),
    ({"platform_identifier": "BILT", "cleared": "I", "is_capped": True},
     "CLEARED_OFF_FACILITY_CAPPED", 15),
    # unrecognised: +60, and it must NOT collapse onto the off-facility +30
    ({"platform_identifier": "ZZZZ", "cleared": "N"}, "INDETERMINATE", 60),
])
def test_the_appendix_c_delay_follows_the_platform(kw, cls, minutes):
    unit = _one(_leg(**kw))
    assert unit.clocks.visibility_source == f"APPENDIX_C:{cls}"
    assert unit.clocks.visibility == _EXEC + pd.Timedelta(minutes=minutes)


# ===========================================================================
# 7. upfront resolution
# ===========================================================================

def test_new_trade_upfront_comes_from_ufro():
    unit = _one(_leg(other_payment_amount=120_000.0, other_payment_ufro=120_000.0))
    assert unit.upfront == pytest.approx(120_000.0)
    assert unit.upfront_source == universe.UPFRONT_UFRO


def test_termination_upfront_comes_from_uwin_when_it_is_there():
    """UWIN is the termination-settlement fee and ``stir_flow`` never read it.

    Routing it in is right, and it is also nearly empty: measured, exactly one
    of 50,752 TERMINATION legs on the whole tape carries a non-zero
    ``other_payment_uwin``. The brief's premise -- that terminations have no
    upfront to compare against -- is false for a different reason: 11,583 of
    them (22.8%) already carry a UFRO.
    """
    unit = _one(_leg(lifecycle_type="TERMINATION",
                     event_timestamp=pd.Timestamp("2026-06-16 15:00:00", tz="UTC"),
                     other_payment_amount=80_000.0, other_payment_uwin=80_000.0))
    assert unit.upfront == pytest.approx(80_000.0)
    assert unit.upfront_source == universe.UPFRONT_UWIN
    assert unit.is_lifecycle is True


def test_termination_still_uses_ufro_when_that_is_what_is_populated():
    unit = _one(_leg(lifecycle_type="TERMINATION",
                     event_timestamp=pd.Timestamp("2026-06-16 15:00:00", tz="UTC"),
                     other_payment_amount=80_000.0, other_payment_ufro=80_000.0))
    assert unit.upfront == pytest.approx(80_000.0)
    assert unit.upfront_source == universe.UPFRONT_UFRO


def test_uwin_on_a_new_trade_is_still_a_fee():
    """12 of the 15 UWIN legs are stamped ``NEW_TRADE``, up to $35.6mm.

    Dropping them because the lifecycle field says NEW_TRADE would send a
    visibly off-market print to the rate rule, which is the exact failure this
    module exists to prevent. Lifecycle status decides *precedence* between
    UFRO and UWIN, not whether a UWIN counts.
    """
    unit = _one(_leg(other_payment_amount=18_600_000.0,
                     other_payment_uwin=18_600_000.0))
    assert unit.is_lifecycle is False
    assert unit.upfront == pytest.approx(18_600_000.0)
    assert unit.upfront_source == universe.UPFRONT_UWIN


def test_uwin_outranks_ufro_on_a_lifecycle_print():
    """The precedence half of the rule, which no other case reaches.

    ``resolve_upfront``'s docstring spends a paragraph on it: lifecycle status
    does not decide whether a UWIN counts, it decides which component wins when
    both are present. On a termination the settlement fee IS the price, and
    taking the UFRO instead would answer the wrong question with the wrong
    number. Measured zero on v3 -- no row carries two other-payment categories
    -- so nothing but this case exercises the branch.
    """
    unit = _one(_leg(lifecycle_type="TERMINATION",
                     event_timestamp=pd.Timestamp("2026-06-16 15:00:00", tz="UTC"),
                     other_payment_amount=80_000.0,
                     other_payment_ufro=40_000.0, other_payment_uwin=80_000.0))
    assert unit.is_lifecycle is True
    assert unit.upfront == pytest.approx(80_000.0)
    assert unit.upfront_source == universe.UPFRONT_UWIN


def test_ufro_and_uwin_are_never_summed():
    """``core/other_payments.py``: the three categories are mutually distinct
    and must not be aggregated. Measured: no row on the tape carries both, so
    the rule costs nothing -- but a sum would be wrong the day one does."""
    unit = _one(_leg(other_payment_amount=100_000.0,
                     other_payment_ufro=100_000.0,
                     other_payment_uwin=40_000.0))
    assert unit.upfront == pytest.approx(100_000.0)
    assert unit.upfront_source == universe.UPFRONT_UFRO


def test_pexh_alone_is_not_an_upfront():
    """PEXH is an early-exercise settlement, not a fee against a printed rate,
    and it is on two legs of the whole tape. Aggregating it would route an
    exercise to the upfront rule and give it a confident answer."""
    unit = _one(_leg(other_payment_amount=50_000.0, other_payment_pexh=50_000.0))
    assert unit.upfront is None
    assert unit.upfront_source is None


def test_package_transaction_price_wins_over_the_ufro_sum():
    unit = _one(_leg(package_transaction_price=900_000.0,
                     other_payment_amount=100_000.0,
                     other_payment_ufro=100_000.0))
    assert unit.upfront == pytest.approx(900_000.0)
    assert unit.upfront_source == universe.UPFRONT_PTP


def test_a_negative_package_transaction_price_is_still_a_fee():
    """LIVE, and larger than any other upfront population here.

    Measured on v3: **382,815 legs carry a ``package_transaction_price`` below
    -500** (403,314 above +500), so the sign on that field is a direction of
    payment, not a magnitude -- ``Unit.upfront`` is documented as unsigned and
    the frozen ``trade_selection.resolve_upfront`` takes ``abs()`` too.

    Drop the ``.abs()`` and a -$900k package price fails the ``> PTP_USD_FLOOR``
    test, reads as *absent*, and the unit falls through to the UFRO sum or to
    the rate rule with a real fee unspent. Nothing raises; the direction is
    simply answered from the wrong rule on a third of the priced packages.
    """
    unit = _one(_leg(package_transaction_price=-900_000.0,
                     other_payment_amount=100_000.0,
                     other_payment_ufro=100_000.0))
    assert unit.upfront == pytest.approx(900_000.0)
    assert unit.upfront_source == universe.UPFRONT_PTP


def test_tiny_package_transaction_price_is_a_notation_not_a_fee():
    """``PTP_USD_FLOOR`` -- below it the field is carrying a price in points,
    not a dollar fee."""
    unit = _one(_leg(package_transaction_price=98.5,
                     other_payment_amount=100_000.0,
                     other_payment_ufro=100_000.0))
    assert unit.upfront == pytest.approx(100_000.0)
    assert unit.upfront_source == universe.UPFRONT_UFRO


def test_upfront_sums_across_the_legs_of_a_package():
    unit = _one(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18),
             other_payment_amount=30_000.0, other_payment_ufro=30_000.0),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18),
             other_payment_amount=20_000.0, other_payment_ufro=20_000.0),
    )
    assert unit.upfront == pytest.approx(50_000.0)


def test_no_upfront_is_none_not_zero():
    """``None`` routes to the rate rule; ``0.0`` would route to the upfront
    rule with a zero fee and call every trade the same way."""
    assert _one(_leg()).upfront is None


# ===========================================================================
# 8. clocks
# ===========================================================================

def test_lifecycle_visibility_is_measured_from_the_event_not_the_frozen_exec():
    """The trap the pricing clock already avoids, one field along.

    ``visibility_timestamp`` takes an execution timestamp, and #96 on a
    termination is frozen at the *original* trade -- Appendix F Example 3 has
    it twenty months stale. Feeding #96 in puts the unwind's visibility before
    the unwind happened.
    """
    unit = _one(_leg(
        lifecycle_type="TERMINATION",
        execution_timestamp=pd.Timestamp("2024-04-01 14:15:36", tz="UTC"),
        original_execution_timestamp=pd.Timestamp("2024-04-01 14:15:36", tz="UTC"),
        event_timestamp=pd.Timestamp("2026-06-16 14:57:10", tz="UTC"),
    ))
    assert unit.clocks.pricing == pd.Timestamp("2026-06-16 14:57:10", tz="UTC")
    assert unit.clocks.visibility > unit.clocks.pricing
    assert unit.clocks.visibility.year == 2026


def test_clocks_carry_all_three_stamps_verbatim():
    unit = _one(_leg())
    assert unit.clocks.execution == _EXEC
    assert unit.clocks.event == _EXEC
    assert unit.clocks.pricing == _EXEC
    assert unit.clocks.visibility == _EXEC + pd.Timedelta(minutes=1)


def test_mixed_lifecycle_package_prices_on_the_event_clock():
    """6,028 packages mix ``lifecycle_type``. #30 is right for a NEWT row too,
    #96 is right only for one, so a mixed unit takes #30."""
    unit = _one(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18),
             event_timestamp=pd.Timestamp("2026-06-16 15:00:00", tz="UTC")),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18),
             lifecycle_type="TERMINATION",
             event_timestamp=pd.Timestamp("2026-06-16 15:00:00", tz="UTC")),
    )
    assert unit.clocks.pricing == pd.Timestamp("2026-06-16 15:00:00", tz="UTC")
    assert unit.is_lifecycle is True


@pytest.mark.parametrize("v,want", [
    (None, None), (np.nan, None), (float("nan"), None),
    (True, True), (False, False), (np.True_, True), (np.False_, False),
    (1, True), (0, False),
])
def test_pybool_keeps_none_distinct_from_false(v, want):
    """``numpy.True_ is True`` is False, and ``bool(None)`` is not ``None``.

    Both halves matter and they pull opposite ways. Without the ``bool()`` a
    numpy flag off a DataFrame column never satisfies ``is True`` and every
    print silently takes the 60-minute INDETERMINATE delay; with a bare
    ``bool()`` an unknown flag becomes a definite ``False`` and claims a delay
    class it was never shown to be in.
    """
    assert universe._pybool(v) is want


@pytest.mark.parametrize("is_block,cls,minutes", [
    (None, "INDETERMINATE", 60),
    (np.nan, "INDETERMINATE", 60),
    (np.False_, "ON_FACILITY_NON_BLOCK", 1),
    (np.True_, "SEF_BLOCK", 15),
])
def test_an_unknown_block_flag_does_not_borrow_a_delay_class(
        is_block, cls, minutes):
    """``bool(None)`` is ``False`` (+1 min) and ``bool(nan)`` is ``True``
    (+15 min) -- two different wrong answers from the same missing tri-state,
    and both of them shorten the availability clock."""
    row = _leg()
    clocks, _field = universe.build_clocks(
        row, lifecycle_type="NEW_TRADE", is_block=is_block, is_capped=False,
        cleared=row["cleared"], platform_identifier=row["platform_identifier"])
    assert clocks.visibility_source == f"APPENDIX_C:{cls}"
    assert clocks.visibility == _EXEC + pd.Timedelta(minutes=minutes)


def test_cleared_intent_is_treated_as_cleared():
    """'I' is 94.5% of the tape and 'Y' is 225 rows.

    Reading 'I' as "not cleared" would put almost the whole tape in the
    uncleared Appendix C class, which is factually wrong: a swap destined for
    a CCP is reported at execution as intent-to-clear because clearing has not
    happened yet.
    """
    assert universe.cleared_flag("I") is True
    assert universe.cleared_flag("Y") is True
    assert universe.cleared_flag("N") is False
    assert universe.cleared_flag(None) is None


# ===========================================================================
# 9. flags carried onto the unit
# ===========================================================================

def test_block_and_capped_are_any_leg_properties():
    unit = _one(
        _leg(trade_id="A", expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="B", expiration_date=datetime.date(2031, 6, 18),
             is_block=True, is_capped=True),
    )
    assert unit.is_block is True
    assert unit.is_capped is True


def test_capped_units_are_kept():
    """3.0% of flow legs and ~15% of DV01. Imputation is a later module's
    problem; dropping them here would delete the tail."""
    assert _one(_leg(is_capped=True)) is not None


def test_unit_carries_its_rate_index():
    assert _one(_leg(rate_index_clean="FED_FUNDS")).rate_index == "FED_FUNDS"


# ===========================================================================
# 10. the report path and the builder path must be one implementation
# ===========================================================================

def test_report_agrees_with_the_builder_on_the_same_day():
    """Two code paths over one definition is how a filter silently drifts."""
    legs = _frame(
        _leg(trade_id="A", package_id="PA"),
        _leg(trade_id="B", package_id="PB", trade_type="SPREADOVER"),
        _leg(trade_id="C", package_id="PC", rate_index_clean="OTHER"),
        _leg(trade_id="D", package_id="PD", expiration_date=datetime.date(2056, 6, 18),
             tenor_years=30.0, risk=170_000.0),
        _leg(trade_id="E1", package_id="PE", expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="E2", package_id="PE", expiration_date=datetime.date(2031, 6, 18)),
    )
    units, excl = universe.build_universe(legs)
    rep = universe.summarise(legs)
    assert int(rep["kept_units"]) == len(units) == 3
    assert int(rep["excluded_units"]) == len(excl) == 2
    assert int(rep["by_reason"]["n_units"].sum()) == len(excl)


def test_economic_unwind_is_admitted_counted_and_not_flipped_to_lifecycle():
    """36,828 legs the gate lets in and no quoted denominator contains.

    ``contributes_to_flow`` is True on ``ECONOMIC_UNWIND`` as well as
    ``ECONOMIC_FLOW``, and 36,763 of those 36,828 carry
    ``lifecycle_type = 'NEW_TRADE'`` (they are H10 backdated NEWTs), so
    ``is_lifecycle`` does not see them and they land in the primary series.

    Both halves are pinned here on purpose. Re-tagging them ``is_lifecycle``
    looks like the fix and is not: ``upfront.orientation`` returns
    ``-s if is_lifecycle else s``, so the tag inverts the inferred direction,
    and it does so for the termination fee mechanism, which does not describe a
    new swap struck at a seasoned coupon. What the accounting owes is a count,
    which is what ``unwind_units_kept`` is.
    """
    legs = _frame(
        _leg(trade_id="F", package_id="PF"),
        _leg(trade_id="U", package_id="PU", economic_class="ECONOMIC_UNWIND",
             lifecycle_type="NEW_TRADE", contributes_to_flow=True),
        # 2,323 multi-leg packages mix `economic_class`, so the unit-level flag
        # is an `any`: one unwind leg makes the package's price an unwind price.
        _leg(trade_id="M1", package_id="PM", contributes_to_flow=True,
             expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="M2", package_id="PM", economic_class="ECONOMIC_UNWIND",
             lifecycle_type="NEW_TRADE", contributes_to_flow=True,
             expiration_date=datetime.date(2031, 6, 18)),
    )
    units, excl = universe.build_universe(legs)
    assert len(units) == 3 and len(excl) == 0
    assert {u.unit_key: u.is_lifecycle for u in units} == {
        "F": False, "U": False, "PM": False}

    rep = universe.summarise(legs)
    assert rep["unwind_units_kept"] == 2
    assert rep["lifecycle_units_kept"] == 0
    assert rep["kept_units"] == 3


def test_venue_dv01_share_is_named_for_the_denominator_it_actually_uses():
    """``by_venue`` is a share of the KEPT total; the exclusion tables are
    shares of the whole universe. Printed side by side under one column name,
    two denominators read as one."""
    legs = _frame(
        _leg(trade_id="A", package_id="PA"),
        _leg(trade_id="B", package_id="PB", trade_type="SPREADOVER"),
    )
    rep = universe.summarise(legs)
    assert "dv01_share_of_kept_pct" in rep["by_venue"].columns
    assert "dv01_share_pct" not in rep["by_venue"].columns
    assert "dv01_share_pct" in rep["by_reason"].columns
    assert "dv01_share_pct" in rep["by_constant"].columns
    # the kept-share column sums to 100 while the universe-share one does not
    assert float(rep["by_venue"]["dv01_share_of_kept_pct"].sum()) == \
        pytest.approx(100.0)
    assert float(rep["by_constant"]["dv01_share_pct"].sum()) < 99.0


def test_the_report_refuses_to_summarise_an_empty_range():
    """``0 legs -> 0 units`` for every month, a zero dict, and exit 0 is
    indistinguishable from an empty tape, a wrong date range, or a connection
    to the wrong database."""
    # shaped exactly as `load_legs` returns it for a range with no rows:
    # the columns are there, the rows are not
    no_rows = _frame(_leg()).iloc[:0]
    u = universe.unit_frame(no_rows)
    assert len(u) == 0
    rep = universe.aggregate_units(u)
    assert rep["kept_units"] == 0 and rep["excluded_units"] == 0
    with pytest.raises(ValueError, match="0 units"):
        universe._print_report(rep, u)


def test_summarise_dv01_share_excludes_the_notional_sentinel_from_the_base():
    """A 1e20 notional times an annuity is 1e17 of DV01. Left in the
    denominator it makes every other share read as zero."""
    legs = _frame(
        _leg(trade_id="A", package_id="PA"),
        _leg(trade_id="S", package_id="PS", notional=1e20, fixed_rate=9.9,
             risk=3.96072e15),
    )
    rep = universe.summarise(legs)
    assert rep["dv01_proxy_total"] < 1e9
    assert int(rep["sentinel_units"]) == 1


# ===========================================================================
# 11. sanity.py -- the port keeps its known answers
# ===========================================================================

def test_sentinel_notional_and_rate_are_both_named():
    r = sanity.implausibility_reason(notional=1e20, tenor_years=0.397,
                                     forward_start_years=0.0, fixed_rate=9.9,
                                     risk=3.96072e15)
    assert r is not None
    assert "NOTIONAL_SENTINEL" in r and "RATE_SENTINEL" in r


def test_the_briefs_own_bound_calls_a_sentinel_clean_and_this_one_does_not():
    """Head to head on a real sentinel row, not arithmetic about one.

    Measured, not argued: |risk|/notional on those 55 rows is 1.004-1.006 times
    tenor*1e-4, so the suggested 2x band flags zero of them -- ``risk`` was
    computed *correctly from* the sentinel notional. The bound that does catch
    them is an absolute one on the inputs, and this pins that it is the input
    bound doing the work and not the ratio test getting lucky.
    """
    n, t, r = 1e20, 0.397, 3.96072e15
    naive = abs(r) / (n * t * 1e-4)
    assert 0.5 < naive < 2.0                        # the brief's bound: clean

    got = sanity.implausibility_reason(
        notional=n, tenor_years=t, forward_start_years=0.0, fixed_rate=9.9,
        risk=r)
    assert got is not None
    assert "NOTIONAL_SENTINEL" in got.split(",")

    flags = sanity.flag_risk_implausible(pd.DataFrame([{
        "notional": n, "tenor_years": t, "forward_start_years": 0.0,
        "fixed_rate": 9.9, "risk": r}])).iloc[0]
    assert not bool(flags["RISK_VS_NOTIONAL_LOW"])
    assert not bool(flags["RISK_VS_NOTIONAL_HIGH"])
    assert flags["risk_ratio"] == pytest.approx(naive, rel=0.02)


#: ``(tenor, n legs, median |risk| / notional * 1e4)`` -- the tape's OWN implied
#: annuity factor, measured on v3 on 2026-08-11 over spot-start
#: (``forward_start_years < 0.02``) ``ECONOMIC_FLOW`` legs with a non-null,
#: non-zero ``risk`` and ``0 < notional < 1e11``. Computed from ``risk`` and
#: ``notional`` alone -- :func:`sanity.expected_dv01` is nowhere in it, so
#: comparing the model against it is not a tautology.
_MEASURED_ANNUITY = [
    (1.000000, 47_677, 0.976087),
    (2.000000, 106_157, 1.920000),
    (3.002740, 72_756, 2.829545),
    (5.002740, 231_264, 4.545455),
    (7.005479, 53_336, 6.142857),
    (10.005479, 278_287, 8.316667),
    (15.010959, 22_354, 11.333333),
    (20.013699, 33_120, 13.800000),
    (30.019178, 125_033, 17.571429),
    (40.027397, 1_558, 20.160000),
]


@pytest.mark.parametrize("tenor,n_legs,a_measured", _MEASURED_ANNUITY)
def test_flat_yield_reproduces_the_annuity_the_tape_implies(
        tenor, n_legs, a_measured):
    """``FLAT_YIELD`` is the one calibrated number in the module and it was
    pinned by nothing.

    The whole argument for the annuity form -- the reason the module exists in
    this shape rather than as ``tenor * 1e-4`` -- is that the median ratio comes
    out flat across tenor bands instead of sliding to 0.59 at the long end. That
    flatness is a property of *this yield*: 0.04 holds to 1.0% out to 40y, 0.02
    is 8% out at 10y and 37% out at 40y, and the error is one-signed, so a
    silent change to it would bias the long end of every band test the same way.
    """
    assert n_legs > 1_000                            # the anchor is not a corner
    got = sanity.expected_dv01(1e8, tenor, 0.0)
    assert float(got) == pytest.approx(a_measured * 1e4, rel=0.02)
    assert float(sanity.annuity(tenor)) == pytest.approx(a_measured, rel=0.02)


@pytest.mark.parametrize("exp_target,want", [(290.0, None), (310.0, "RISK_ZERO_MATERIAL")])
def test_risk_zero_is_material_only_above_the_named_slack(exp_target, want):
    """``risk = 0`` is rounding below the slack and a wrong number above it.

    The quantiser rounds to nearest: ``risk = 0`` flow legs have expected DV01
    p95 = 47.4 and ``risk = 100`` legs p1 = 49.9, so the arithmetic boundary is
    half a quantum. ``RISK_ZERO_SLACK`` sits six times above that on purpose
    (:mod:`sanity` says why), which means the gate governs 16,605 admitted
    zero-risk flow legs and currently fires on none of them -- a threshold that
    can only be checked by construction. The notional is derived from the
    module's own annuity so this case moves with ``FLAT_YIELD`` and pins the
    slack multiplier alone.
    """
    # A guard on this case's own construction, not a pin: the two probes are
    # chosen to straddle $300, so they stop being a boundary test if the slack
    # moves. They must be re-derived, not silently rescaled -- rescaling them
    # with the constant is how a threshold test stops testing the threshold.
    assert sanity.RISK_ZERO_SLACK * sanity.RISK_QUANTUM == pytest.approx(300.0)

    notional = exp_target / (float(sanity.annuity(1.0)) * 1e-4)
    assert sanity.expected_dv01(notional, 1.0, 0.0) == pytest.approx(exp_target)

    got = sanity.implausibility_reason(
        notional=notional, tenor_years=1.0, forward_start_years=0.0,
        fixed_rate=0.04, risk=0.0)
    if want is None:
        assert got is None
    else:
        assert got is not None and want in got.split(",")


def test_annuity_form_does_not_flag_a_deep_forward_start():
    """The naive tenor*1e-4 bound mis-flags 58% of these."""
    assert sanity.implausibility_reason(
        notional=5e8, tenor_years=5.0, forward_start_years=30.0,
        fixed_rate=0.04, risk=67_000.0) is None


def test_quantisation_allowance_keeps_a_tiny_print_clean():
    """``risk`` is quantised to $100, so a $2mm 3-month print whose true DV01
    is ~$50 is stored as 100 and a purely multiplicative band flags it."""
    assert sanity.implausibility_reason(
        notional=2e6, tenor_years=0.25, forward_start_years=0.0,
        fixed_rate=0.0366, risk=100.0) is None


@pytest.mark.parametrize("kw,want", [
    ({"risk": 453_000.0}, "RISK_VS_NOTIONAL_HIGH"),
    ({"risk": 4_500.0}, "RISK_VS_NOTIONAL_LOW"),
    ({"risk": 0.0}, "RISK_ZERO_MATERIAL"),
    ({"risk": None}, "RISK_NULL"),
    ({"notional": None}, "INPUTS_MISSING"),
    ({"notional": 0.0}, "INPUTS_MISSING"),
    ({"fixed_rate": 9.9}, "RATE_SENTINEL"),
    ({"notional": 1e20}, "NOTIONAL_SENTINEL"),
])
def test_mutating_a_clean_row_is_noticed(kw, want):
    """A predicate that cannot be made to fire is not a predicate."""
    base = dict(notional=1e8, tenor_years=5.0, forward_start_years=0.0,
                fixed_rate=0.0395, risk=45_300.0)
    assert sanity.implausibility_reason(**base) is None
    base.update(kw)
    got = sanity.implausibility_reason(**base)
    assert got is not None and want in got.split(",")


def test_synthetic_cases_match_the_frame_api():
    """The scalar predicate and the vectorised one are the same predicate."""
    df, want = sanity.synthetic_cases()
    got = sanity.flag_risk_implausible(df)
    assert list(got["reason"]) == want
    scalar = [
        sanity.implausibility_reason(
            notional=r.notional, tenor_years=r.tenor_years,
            forward_start_years=r.forward_start_years,
            fixed_rate=r.fixed_rate, risk=r.risk) or ""
        for r in df.itertuples()
    ]
    assert scalar == want


def test_annuity_is_the_tenor_at_zero_yield():
    assert sanity.annuity(7.0, flat_yield=0.0) == pytest.approx(7.0)
    assert float(sanity.annuity(0.0)) == pytest.approx(0.0)


def test_expected_dv01_of_a_forward_start_is_the_annuity_difference():
    got = sanity.expected_dv01(1e8, 5.0, 20.0)
    a = sanity.annuity
    assert got == pytest.approx(1e8 * (a(25.0) - a(20.0)) * 1e-4)
    assert got < sanity.expected_dv01(1e8, 5.0, 0.0)


def test_risk_implausible_units_are_excluded_and_named():
    got, detail = _reason(_leg(notional=1e20, fixed_rate=9.9, risk=3.96072e15))
    assert got == types.EXCL_RISK_IMPLAUSIBLE
    assert "NOTIONAL_SENTINEL" in detail


# ===========================================================================
# 12. the frozen predecessor still agrees where it should
# ===========================================================================

def test_venue_matches_stir_flow_on_every_platform_stir_flow_decided():
    """The incumbent whitelist is a subset, not a competitor. Anything
    ``stir_flow`` already classified must classify the same way here."""
    from SDRUtils.stir_flow import config as sf_config
    from SDRUtils.stir_flow import trade_selection as sf_ts

    for pid in sorted(sf_config.D2C_PLATFORM_WHITELIST):
        assert sf_ts.venue_status(pid) == "D2C_WHITELISTED"
        assert universe.classify_venue(pid) == types.VENUE_D2C
    from SDRUtils.analytics.filters import D2D_PLATFORMS
    for pid in sorted(D2D_PLATFORMS):
        assert universe.classify_venue(pid) == types.VENUE_D2D


def test_upfront_matches_stir_flow_where_stir_flow_had_an_answer():
    from SDRUtils.stir_flow import trade_selection as sf_ts

    for ptp, ufros in ((None, [50_000.0]), (900_000.0, [100_000.0]),
                       (-900_000.0, [100_000.0]),      # 382,815 legs on v3
                       (98.5, [100_000.0]), (-98.5, [100_000.0]),
                       (None, [0.0]),
                       (None, [30_000.0, 20_000.0])):
        old_amt, old_src, _ = sf_ts.resolve_upfront(ptp, ufros)
        legs = _frame(*[
            _leg(trade_id=f"T{i}",
                 expiration_date=datetime.date(2028 + i, 6, 18),
                 package_transaction_price=ptp,
                 other_payment_amount=u, other_payment_ufro=u)
            for i, u in enumerate(ufros)
        ])
        new_amt, new_src = universe.resolve_upfront(legs, is_lifecycle=False)
        assert new_amt == old_amt, (ptp, ufros)
        assert (new_src or "") == (old_src or ""), (ptp, ufros)
