r"""Hermetic tests for the Citi Velocity bond layer.

Bonds are a **two-step mechanism, not a tag family**: ``RATES.BOND`` has zero
children in the DAG because the ISIN universe is far too large for a browse tree.
``CVCURVEBOND`` returns the universe (``Date | ISIN | Description | measure``) and
``RATES.BOND.<ISIN>.<value>`` is the per-bond series.

The description parser is tested against the REAL committed universe - 2,162
descriptions harvested from the add-in - rather than a handful of fixtures,
because the failure mode being guarded is "it parses the examples I thought of".

Nothing here validates a number against a Citi quote: there is no Excel in the
fast gate. What it does validate is that the two backends agree, that the
conventions table covers every harvested country, and that the sign and unit
conventions are the ones the docstrings claim.
"""

from __future__ import annotations

import datetime

import pytest
import QuantLib as ql

from MDP.CitiVelocityExcel.bonds.conventions import (
    BOND_CONVENTIONS,
    approximate_countries,
    conventions_for,
    supported_countries,
)
from MDP.CitiVelocityExcel.bonds.ql_bonds import (
    build_ql_bond,
    ql_asset_swap_spread,
    ql_bond_metrics,
)
from MDP.CitiVelocityExcel.bonds.rl_bonds import build_rl_bond, rl_bond_metrics, rl_settlement_date
from MDP.CitiVelocityExcel.bonds.universe import (
    BondUniverse,
    cross_currency_asw_legs,
    parse_bond_description,
)
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog

AS_OF = datetime.date(2026, 8, 5)
CLEAN_PRICE = 99.50


@pytest.fixture(scope="module")
def universe() -> BondUniverse:
    return BondUniverse.from_catalog()


# ------------------------------------------------------------------ #
#                      the description parser                        #
# ------------------------------------------------------------------ #


def test_parser_handles_the_whole_harvested_universe(universe: BondUniverse):
    """Measured over all 2,162 real descriptions, not a handful of examples.

    The residual non-parses are floating-rate notes and one prospectus line -
    instruments this module deliberately refuses rather than mis-prices. The
    failures are printed in the assertion message so a regression names them.
    """
    frame = universe.to_frame()
    total = len(frame)
    assert total == 2162
    # Maturity comes from the catalog's own column where the description
    # does not yield one, so it is complete. The COUPON is what a floater
    # has no fixed value for, and that is what parse_failures() reports.
    assert int(frame["maturity"].notna().sum()) == total
    parsed = int(frame["coupon"].notna().sum())
    rate = parsed / total
    failures = universe.parse_failures()
    assert rate >= 0.99, f"parse rate {rate:.4%} ({total - parsed} failures): {failures[:15]}"
    assert len(failures) == total - parsed
    # Every failure must be a floater or a prospectus line, never a plain
    # fixed-rate bond the parser simply could not read.
    for descriptor in failures:
        text = str(descriptor.description).upper()
        assert "FLOAT" in text or "FRN" in text or "%" in text, (
            f"unexpected parse failure that is not a floater: {descriptor.description!r}"
        )


def test_known_description_forms_parse_exactly():
    assert parse_bond_description("T 1.25 08/15/2031") == ("T", 1.25, datetime.date(2031, 8, 15))
    assert parse_bond_description("FHLB 4.375 06/14/2030") == (
        "FHLB",
        4.375,
        datetime.date(2030, 6, 14),
    )
    ticker, coupon, maturity = parse_bond_description("DBR 0 02/15/2032")
    assert ticker == "DBR" and coupon == 0.0 and maturity == datetime.date(2032, 2, 15)


def test_unparseable_descriptions_return_nones_rather_than_guessing():
    """A guessed maturity is a silently mispriced bond."""
    ticker, coupon, maturity = parse_bond_description("SOMETHING WITH NO DATE")
    assert maturity is None


def test_date_order_is_mm_dd_and_that_was_measured(universe: BondUniverse):
    """MM/DD vs DD/MM is not assumed - it is read off the whole universe.

    Across all 2,162 descriptions the FIRST numeric field never exceeds 12 while
    the second frequently does, which is only consistent with MM/DD.
    """
    import re

    pattern = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
    first_over_12 = 0
    second_over_12 = 0
    for description in universe.to_frame()["description"]:
        m = pattern.search(str(description))
        if not m:
            continue
        if int(m.group(1)) > 12:
            first_over_12 += 1
        if int(m.group(2)) > 12:
            second_over_12 += 1
    assert first_over_12 == 0, "a first field above 12 would mean DD/MM"
    assert second_over_12 > 500, f"only {second_over_12} second fields above 12"


# ------------------------------------------------------------------ #
#                          conventions table                         #
# ------------------------------------------------------------------ #


def test_every_harvested_country_has_conventions():
    catalog_countries = {b.country for b in CitiVeloCatalog.default().bonds()}
    assert set(supported_countries()) == catalog_countries
    assert len(catalog_countries) == 18


def test_provenance_is_recorded_and_the_approximate_ones_carry_a_note():
    """Nine countries' conventions are market knowledge, not library-supplied.

    They are usable and they are flagged, which is the difference between a
    documented approximation and a silent one.
    """
    approx = set(approximate_countries())
    assert approx == {"BRA", "CHN", "DNK", "ESP", "JPN", "KOR", "MEX", "NZL", "ZAF"}
    for country in supported_countries():
        conv = conventions_for(country)
        assert conv.provenance in {"rateslib_spec", "market_standard"}
        if country in approx:
            assert conv.provenance == "market_standard"
            assert conv.note, f"{country} is approximate and must say what is approximate"
        else:
            assert conv.rl_spec, f"{country} claims a rateslib spec but names none"


def test_spain_is_not_backed_by_the_eurex_future_spec():
    """``sp_gb_10y`` is the EUREX FUTURE, not a Spanish cash bond.

    Reading it as a cash-bond spec would silently import a 6% notional coupon and
    a 100,000 nominal. Spain is therefore market_standard.
    """
    import rateslib as rl

    spec = rl.defaults.spec["sp_gb_10y"]
    assert spec.get("coupon") == 6.0 and spec.get("nominal") == 100_000.0
    assert conventions_for("ESP").provenance == "market_standard"


# ------------------------------------------------------------------ #
#                        the two backends agree                      #
# ------------------------------------------------------------------ #


def _descriptor(universe: BondUniverse, country: str):
    candidates = [
        b
        for b in universe.filter(country=country, asset_type="GOVT")
        if b.maturity and b.maturity > AS_OF + datetime.timedelta(days=730) and b.coupon
    ]
    assert candidates, f"no usable {country} GOVT bond in the universe"
    return sorted(candidates, key=lambda b: b.maturity)[0]


@pytest.mark.parametrize("country", ["USA", "DEU", "GBR", "ITA"])
def test_rateslib_and_quantlib_agree_on_yield_and_duration(universe: BondUniverse, country: str):
    """Two independent implementations, one clean price, a stated tolerance.

    ITA is the interesting case: BTPs quote an ANNUALLY compounded yield, and
    reading them semi-annually is worth ~3 bp. The conventions table records the
    yield frequency per country separately from the accrual frequency.
    """
    descriptor = _descriptor(universe, country)
    ql_bond = build_ql_bond(descriptor=descriptor, evaluation_date=AS_OF)
    ql_metrics = ql_bond_metrics(bond=ql_bond, evaluation_date=AS_OF, clean_price=CLEAN_PRICE)

    rl_bond = build_rl_bond(descriptor=descriptor)
    settle = rl_settlement_date(descriptor=descriptor, as_of=AS_OF)
    rl_metrics = rl_bond_metrics(bond=rl_bond, settlement=settle, price=CLEAN_PRICE)

    ytm_gap_bp = abs(ql_metrics["ytm"] - rl_metrics["ytm"]) * 100.0
    assert ytm_gap_bp < 0.2, (
        f"{country}: ytm gap {ytm_gap_bp:.5f} bp "
        f"(ql {ql_metrics['ytm']:.6f} vs rl {rl_metrics['ytm']:.6f})"
    )
    dur_gap = abs(ql_metrics["mod_duration"] - rl_metrics["mod_duration"])
    assert dur_gap < 1e-3, f"{country}: modified duration gap {dur_gap:.3e} years"


def test_btp_yield_frequency_is_annual_and_it_matters(universe: BondUniverse):
    """MUTATION CHECK: reading a BTP semi-annually moves the yield by basis points."""
    descriptor = _descriptor(universe, "ITA")
    conv = conventions_for("ITA")
    assert conv.yield_frequency in {"a", ql.Annual, 1}, f"BTPs quote annually, got {conv.yield_frequency!r}"

    bond = build_ql_bond(descriptor=descriptor, evaluation_date=AS_OF)
    correct = ql_bond_metrics(bond=bond, evaluation_date=AS_OF, clean_price=CLEAN_PRICE)["ytm"]

    import dataclasses

    semi = dataclasses.replace(conv, yield_frequency="s")
    wrong = ql_bond_metrics(
        bond=bond, evaluation_date=AS_OF, clean_price=CLEAN_PRICE, conventions=semi
    )["ytm"]
    gap_bp = abs(correct - wrong) * 100.0
    assert gap_bp > 1.0, f"the annual/semi distinction should be worth bp, got {gap_bp:.4f}"


def test_dv01_sign_matches_a_finite_difference_bump(universe: BondUniverse):
    """QuantLib's raw ``basisPointValue`` is NEGATIVE for a long bond.

    The repo's sibling forces ``copysign(|BPV|, notional)``; rateslib does not
    coerce at all. One convention is picked here - positive for a long position -
    and checked against an independent price bump rather than against itself.
    """
    descriptor = _descriptor(universe, "USA")
    bond = build_ql_bond(descriptor=descriptor, evaluation_date=AS_OF)
    metrics = ql_bond_metrics(bond=bond, evaluation_date=AS_OF, clean_price=CLEAN_PRICE)
    dv01 = metrics["dv01"]
    assert dv01 > 0, "a long bond's DV01 is reported positive here"

    # ``ytm=`` is in PERCENT (the same unit ``metrics['ytm']`` reports), so one
    # basis point is +0.01, not +0.0001. Getting that wrong understates the bump
    # by 100x and the check would "fail" against correct code.
    base = metrics["ytm"]
    up = ql_bond_metrics(bond=bond, evaluation_date=AS_OF, ytm=base + 0.01)["clean"]
    down = ql_bond_metrics(bond=bond, evaluation_date=AS_OF, ytm=base - 0.01)["clean"]
    finite_difference = abs(up - down) / 2.0
    assert finite_difference == pytest.approx(dv01, rel=1e-4), (
        f"dv01 {dv01:.8f} vs finite difference {finite_difference:.8f}"
    )


# ------------------------------------------------------------------ #
#                           asset swap                               #
# ------------------------------------------------------------------ #


def test_par_par_asw_is_zero_at_the_curve_implied_price(universe: BondUniverse):
    """The definitional zero: a bond priced off the curve has no spread to it.

    This repo has had NO working asset-swap spread anywhere (``zspread()`` raises
    ``NotImplementedError`` on both backends and ``SplineYAxis.ASW`` is an unused
    enum value), so this is new code and it is pinned to its own definition.
    """
    descriptor = _descriptor(universe, "USA")
    bond = build_ql_bond(descriptor=descriptor, evaluation_date=AS_OF)
    ql.Settings.instance().evaluationDate = ql.Date(AS_OF.day, AS_OF.month, AS_OF.year)
    handle = ql.YieldTermStructureHandle(
        ql.FlatForward(
            ql.Date(AS_OF.day, AS_OF.month, AS_OF.year), 0.040, ql.Actual360(), ql.Compounded, ql.Annual
        )
    )
    engine = ql.DiscountingBondEngine(handle)
    bond.setPricingEngine(engine)
    implied_clean = bond.cleanPrice()

    at_par = ql_asset_swap_spread(
        bond=bond, clean_price=implied_clean, curve_handle=handle, evaluation_date=AS_OF
    )
    assert abs(at_par) < 1e-6, f"expected 0 bp at the curve-implied price, got {at_par:.6g}"


def test_par_par_asw_is_monotone_in_clean_price(universe: BondUniverse):
    descriptor = _descriptor(universe, "USA")
    bond = build_ql_bond(descriptor=descriptor, evaluation_date=AS_OF)
    handle = ql.YieldTermStructureHandle(
        ql.FlatForward(
            ql.Date(AS_OF.day, AS_OF.month, AS_OF.year), 0.040, ql.Actual360(), ql.Compounded, ql.Annual
        )
    )
    spreads = [
        ql_asset_swap_spread(
            bond=bond, clean_price=price, curve_handle=handle, evaluation_date=AS_OF
        )
        for price in (95.0, 99.5, 104.0)
    ]
    assert spreads[0] > spreads[1] > spreads[2], f"not monotone: {spreads}"


# ------------------------------------------------------------------ #
#                     the sparse ASW currency matrix                 #
# ------------------------------------------------------------------ #


def test_asw_legs_are_a_sparse_cross_currency_matrix(universe: BondUniverse):
    """``ASW_4_<CCY>`` is NOT the bond's own currency, and there is no rule.

    A bund carries ``ASW_4_USD/GBP/CHF/AUD`` but not ``ASW_4_EUR``; a gilt carries
    ``ASW_4_EUR/GBP/AUD``; a Treasury carries ``ASW_4_USD/JPY``. Which legs are
    populated has to be discovered per bond, which is what the committed
    16,288-tag validation set is for.

    An empty list means "the sweep did not validate it", NOT "the add-in would
    refuse it" - 15 of the 2,162 ISINs were never swept at all.
    """
    from MDP.CitiVelocityExcel.bonds.universe import ASW_CURRENCIES

    treasury = universe.lookup("US91282CCS89")
    assert treasury is not None
    legs = cross_currency_asw_legs(treasury)
    assert isinstance(legs, list)
    assert set(legs) <= set(ASW_CURRENCIES)

    # The claim that actually holds is SPARSITY WITHOUT A RULE: across a
    # sample of bunds the populated leg set differs bond to bond, and no
    # bond carries all six. A first sweep that sampled only USD instruments
    # missed ASW_4_AUD and CAS entirely for exactly this reason.
    bunds = list(universe.filter(country="DEU", asset_type="GOVT"))[:40]
    per_bond = [frozenset(cross_currency_asw_legs(b)) for b in bunds]
    populated = [s for s in per_bond if s]
    assert populated, "no German government bond had any ASW leg validated"
    assert len(set(populated)) > 1, "the leg set must vary bond to bond"
    assert not any(s == set(ASW_CURRENCIES) for s in populated), (
        "no bond should carry every ASW currency - the matrix is sparse"
    )


@pytest.mark.slow
def test_every_live_bond_builds_in_both_backends(universe: BondUniverse):
    """The whole universe, both backends, no failures. ~5s."""
    built = 0
    failures: list[str] = []
    for descriptor in universe:
        if descriptor.maturity is None or descriptor.maturity <= AS_OF or descriptor.coupon is None:
            continue
        try:
            build_ql_bond(descriptor=descriptor, evaluation_date=AS_OF)
            build_rl_bond(descriptor=descriptor)
            built += 1
        except Exception as exc:  # noqa: BLE001 - collected and reported
            failures.append(f"{descriptor.isin}: {type(exc).__name__}: {exc}")
    assert not failures, f"{len(failures)} of {built + len(failures)} failed: {failures[:10]}"
    assert built > 1500
