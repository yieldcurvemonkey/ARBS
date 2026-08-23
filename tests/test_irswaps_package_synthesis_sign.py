"""The cache-synthesis twin of a sign bug that was already fixed once.

``IRSwapsTB`` can build a cached curve or fly out of cached outright legs
instead of pricing it. That arithmetic wrapped every leg in ``abs()``, which is
the same defect removed from the PRICING path on 2026-08-07 after it was
measured on CHF SARON: a front rate of -0.055314% came back +0.055314%, an
11.06 bp error, exactly twice the rate.

It survived because nothing reaches it - the branch's own guard skips any query
carrying ``structure_kwargs['notional']``, and every ``IRSwapQuery`` ever
constructed has one. Both facts are pinned below, because the second is what
makes the first safe to have missed and what will change if anyone relaxes the
guard.

Two of the five curves this repo warms - EUR-ESTR and JPY-TONAR - have negative
rates in their history, so this is not a theoretical unit.
"""

import pytest

from TB.IRSwapsTB import _decompose_rate_into_outright_legs, _synthesize_package_bp


CURVE = [(-1.0, "2Y"), (1.0, "10Y")]
FLY = [(-1.0, "5Y"), (2.0, "10Y"), (-1.0, "30Y")]


# ── the arithmetic ───────────────────────────────────────────────────

def test_a_curve_of_positive_rates(self_check=None):
    # 2s10s with 2y at 3.50% and 10y at 4.10% is +60 bp.
    assert _synthesize_package_bp(CURVE, {"2Y": 3.50, "10Y": 4.10}) == pytest.approx(60.0)


def test_a_curve_whose_front_leg_is_negative():
    """The CHF SARON shape. abs() would return -410 - 5.5 = ... the wrong sign."""
    got = _synthesize_package_bp(CURVE, {"2Y": -0.055314, "10Y": 0.30})
    assert got == pytest.approx(35.5314)
    # What the old code produced, kept as the discriminator rather than as prose.
    old = (-1.0 * abs(-0.055314) + 1.0 * abs(0.30)) * 100.0
    assert old == pytest.approx(24.4686)
    assert abs(got - old) == pytest.approx(11.0628, abs=1e-3)


def test_a_fly_straddling_zero():
    got = _synthesize_package_bp(FLY, {"5Y": -0.20, "10Y": 0.10, "30Y": 0.60})
    assert got == pytest.approx((0.20 + 0.20 - 0.60) * 100.0)
    old = (-abs(-0.20) + 2 * abs(0.10) - abs(0.60)) * 100.0
    assert got != pytest.approx(old)


def test_all_positive_rates_are_unchanged_by_the_fix():
    """Why it was invisible: on a positive book the two agree exactly."""
    legs = {"5Y": 3.9, "10Y": 4.1, "30Y": 4.4}
    got = _synthesize_package_bp(FLY, legs)
    old = sum(w * abs(legs[t]) for w, t in FLY) * 100.0
    assert got == pytest.approx(old)


def test_a_missing_leg_refuses_rather_than_guessing():
    assert _synthesize_package_bp(CURVE, {"2Y": 3.5, "10Y": None}) is None
    assert _synthesize_package_bp(CURVE, {"2Y": 3.5}) is None


def test_the_units_are_basis_points():
    """Legs are outright RATES in percent; the package is bp."""
    assert _synthesize_package_bp(CURVE, {"2Y": 0.0, "10Y": 1.0}) == pytest.approx(100.0)


# ── why nothing reached it ───────────────────────────────────────────

def test_every_query_carries_a_notional_so_the_branch_cannot_fire():
    """If this ever fails, the synthesis path has gone LIVE - read the sign test above."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    blockers = ("risk_weights", "bpv", "notional",
                "front_notional", "belly_notional", "back_notional")
    for query in (
        IRSwapQuery(curve="USD-SOFR-1D", tenor="2y/10y", value=IRSwapValue.RATE),
        UnifiedQuery(curve="USD-SOFR-1D", tenor="2y/10y",
                     value=UnifiedValue.IRS_RATE).to_legacy(),
    ):
        skw = dict(getattr(query, "structure_kwargs", {}) or {})
        assert any(skw.get(k) is not None for k in blockers), (
            "the cache-synthesis branch is now reachable; its arithmetic is "
            "exercised by the sign tests in this file and its leg lookup is by "
            "VERBATIM tenor string, which no warm grid currently matches"
        )


def test_the_leg_decomposition_does_not_normalise_case():
    """The other half of why synthesis would still miss: spelling is verbatim."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    query = IRSwapQuery(curve="USD-SOFR-1D", tenor="2y/10y", value=IRSwapValue.RATE)
    assert _decompose_rate_into_outright_legs(query) == [(-1.0, "2y"), (1.0, "10y")]
