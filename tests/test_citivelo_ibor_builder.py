"""The EURIBOR projection curve: does it actually use the discount curve it is given?

Hermetic - no Excel, no network, no database. rateslib only.

The test that matters here is :func:`test_the_discount_curve_changes_the_forwards`.
Every other assertion in this file would still pass if ``discount_curve=`` were
silently dropped on the floor, because a self-discounted build reproduces its own
par quotes exactly and so does a dual-curve one. Reproducing the calibration set
is an identity, not evidence. The dual-curve claim is only testable on something
the two constructions disagree about, which is the FORWARDS.
"""

from __future__ import annotations

import datetime

import pytest

from MDP.CitiVelocityExcel.curves.ibor_builder import (
    IBOR_CURVES,
    build_rl_ibor_curve,
    ibor_spec_for,
)

REF = datetime.date(2024, 6, 12)

#: A realistic, upward-sloping EUR grid in PERCENT - the unit Citi publishes.
#: Deliberately not flat: a flat curve makes forward-rate differences vanish and
#: would hide the very thing the dual-curve test is looking for.
EURIBOR_PAR = {
    "1M": 3.72, "3M": 3.68, "6M": 3.58, "1Y": 3.36,
    "2Y": 3.05, "3Y": 2.92, "4Y": 2.88, "5Y": 2.87,
    "7Y": 2.90, "10Y": 2.98, "15Y": 3.10, "20Y": 3.11,
    "30Y": 2.99,
}

#: The ESTR curve those EURIBOR swaps discount on, ~35 bp below at the front and
#: converging - the shape of a real EURIBOR/ESTR basis.
ESTR_PAR = {
    "1M": 3.66, "3M": 3.55, "6M": 3.38, "1Y": 3.09,
    "2Y": 2.75, "3Y": 2.62, "4Y": 2.59, "5Y": 2.59,
    "7Y": 2.63, "10Y": 2.72, "15Y": 2.85, "20Y": 2.86,
    "30Y": 2.75,
}


def _estr_curve():
    from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve

    return build_rl_ois_curve(
        par_rates=ESTR_PAR, ref_date=REF, citi_index="EUR_EUROSTR", curve_id="estr"
    ).rl_pricing_curve


def _forwards(curve, starts=("1Y", "2Y", "5Y", "10Y"), tenor="1Y"):
    """Simple forward discount-factor ratios, in percent, at a few points."""
    import rateslib as rl

    out = {}
    for start in starts:
        a = rl.add_tenor(rl.dt(REF.year, REF.month, REF.day), start, "MF", "tgt")
        b = rl.add_tenor(a, tenor, "MF", "tgt")
        years = (b - a).days / 365.0
        out[start] = (float(curve[a]) / float(curve[b]) - 1.0) / years * 100.0
    return out


def test_self_discounted_reproduces_its_own_quotes():
    result = build_rl_ibor_curve(par_rates=EURIBOR_PAR, ref_date=REF)
    assert result.is_self_discounted
    assert result.discount_curve_name is None
    # 0.01 bp, not 0: the solver stops at func_tol=1e-9 and the 30Y residual
    # lands around 2e-3 bp - the same order the OIS builder reports on real grids.
    assert result.max_reprice_error_bp < 0.01, result.meta["reprice_errors_bp"]


def test_dual_curve_reproduces_its_own_quotes():
    result = build_rl_ibor_curve(
        par_rates=EURIBOR_PAR, ref_date=REF,
        discount_curve=_estr_curve(), discount_curve_name="EUR-ESTR-1D",
    )
    assert not result.is_self_discounted
    assert result.discount_curve_name == "EUR-ESTR-1D"
    # 0.01 bp, not 0: the solver stops at func_tol=1e-9 and the 30Y residual
    # lands around 2e-3 bp - the same order the OIS builder reports on real grids.
    assert result.max_reprice_error_bp < 0.01, result.meta["reprice_errors_bp"]


def test_the_discount_curve_changes_the_forwards():
    """The only assertion here that a dropped ``discount_curve=`` would fail.

    Both builds price their calibration swaps to the quote, so the par rates
    cannot separate them. The projected forwards can: discounting on a curve
    ~30 bp below the projection curve reweights the floating-leg cashflows and
    moves the solved forwards. If this comes back at zero, the discount curve is
    not reaching the solver.
    """
    self_disc = build_rl_ibor_curve(par_rates=EURIBOR_PAR, ref_date=REF)
    dual = build_rl_ibor_curve(
        par_rates=EURIBOR_PAR, ref_date=REF,
        discount_curve=_estr_curve(), discount_curve_name="EUR-ESTR-1D",
    )
    a = _forwards(self_disc.curve)
    b = _forwards(dual.curve)
    gaps_bp = {k: abs(a[k] - b[k]) * 100.0 for k in a}
    assert max(gaps_bp.values()) > 0.05, (
        "self-discounted and ESTR-discounted forwards are identical to within "
        f"{max(gaps_bp.values()):.4g} bp, so the discount curve is not being used: {gaps_bp}"
    )
    # ...and the effect is a basis-sized reweighting, not a broken solve.
    assert max(gaps_bp.values()) < 25.0, gaps_bp


def test_node_dates_come_from_the_swap_schedules_and_increase():
    result = build_rl_ibor_curve(par_rates=EURIBOR_PAR, ref_date=REF)
    dates = list(result.node_dates)
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)
    assert len(dates) == len(EURIBOR_PAR)


def test_a_nonsense_quote_raises_rather_than_returning_a_curve():
    """rateslib 2.7 reports SUCCESS on a grid it cannot actually fit."""
    broken = dict(EURIBOR_PAR)
    broken["5Y"] = -5000.0
    with pytest.raises(RuntimeError) as excinfo:
        build_rl_ibor_curve(par_rates=broken, ref_date=REF)
    message = str(excinfo.value).lower()
    assert "misprices" in message or "solver returned" in message, message


def test_too_few_tenors_is_a_clear_error_not_a_curve():
    with pytest.raises(ValueError) as excinfo:
        build_rl_ibor_curve(par_rates={"1Y": 3.3, "2Y": 3.1}, ref_date=REF)
    assert "need" in str(excinfo.value)


def test_nan_tenors_are_dropped_not_propagated():
    thin = dict(EURIBOR_PAR)
    thin["7Y"] = float("nan")
    result = build_rl_ibor_curve(par_rates=thin, ref_date=REF)
    assert "7Y" not in result.tenors
    assert len(result.tenors) == len(EURIBOR_PAR) - 1
    assert result.max_reprice_error_bp < 0.01


@pytest.mark.parametrize(
    "day, expected",
    [
        (datetime.date(2026, 1, 5), "EUR-ESTR-1D"),
        (datetime.date(2021, 9, 15), "EUR-ESTR-1D"),
        (datetime.date(2021, 9, 14), "EUR-EONIA-1D"),
        (datetime.date(2018, 6, 1), "EUR-EONIA-1D"),
        (datetime.date(2017, 12, 5), None),
        (datetime.date(2016, 8, 1), None),
    ],
)
def test_the_discount_plan_follows_the_measured_floors(day, expected):
    """ESTR from its 2021-09-15 intraday floor, EONIA from 2017-12-06, then nothing.

    Those dates are measurements, not conventions: ESTR the index has existed
    since 2019-10 but Citi's INTRADAY history for it starts 2021-09-15, and a
    curve that does not exist at the minute being priced cannot discount it.
    """
    assert ibor_spec_for("EUR-EURIBOR-6M").discount_curve_for(day) == expected


def test_the_registry_only_holds_measured_currencies():
    """RATES.SWAP_LIBOR coverage is per currency; GBP and JPY were empty in 2026-08."""
    assert set(IBOR_CURVES) == {"EUR-EURIBOR-6M"}
    assert IBOR_CURVES["EUR-EURIBOR-6M"].rl_spec == "eur_irs6"


def test_the_curve_is_registered_so_it_does_not_rebuild_on_the_WRONG_CALENDAR():
    """`CurveStore.reconstruct_curve` falls back to act360/**nyc**/mf silently.

    It warns once per reference_key and carries on, so a EUR curve rebuilt on the
    New York calendar shows up as a log line nobody reads and date arithmetic
    that is quietly wrong. MEASURED on 60 real stored EURIBOR days: tying the
    rebuilt curve back to Citi's published par rate gave a worst error of
    **0.0452 bp** unregistered and **0.0001 bp** registered - a 450x difference
    from one dictionary entry.
    """
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
        RATESLIB_CURVE_DEFINITIONS,
    )

    from MDP.CitiVelocityExcel.curves import ibor_builder

    ibor_builder.register()
    row = RATESLIB_CURVE_DEFINITIONS["EUR-EURIBOR-6M"]
    assert row["Calendar"] == "tgt", "a EUR curve must rebuild on TARGET, not nyc"
    assert row["DayCounter"] == "act360"
    assert row["BusinessConvention"] == "mf"
    assert row["SettlementDays"] == 2
    assert row["ReferenceRate"] == "eur_irs6"


def test_registration_never_overwrites_someone_elses_definition():
    """`USD-SOFR-1D` is referenced hundreds of times; a new source redefining a
    name in place would move numbers it never touched."""
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
        RATESLIB_CURVE_DEFINITIONS,
    )

    from MDP.CitiVelocityExcel.curves import ibor_builder

    RATESLIB_CURVE_DEFINITIONS["EUR-EURIBOR-6M"] = {"Calendar": "someone-elses"}
    try:
        assert ibor_builder.register() == []
        assert RATESLIB_CURVE_DEFINITIONS["EUR-EURIBOR-6M"]["Calendar"] == "someone-elses"
        assert ibor_builder.register(force=True) == ["EUR-EURIBOR-6M"]
        assert RATESLIB_CURVE_DEFINITIONS["EUR-EURIBOR-6M"]["Calendar"] == "tgt"
    finally:
        RATESLIB_CURVE_DEFINITIONS.pop("EUR-EURIBOR-6M", None)
        ibor_builder.register()
