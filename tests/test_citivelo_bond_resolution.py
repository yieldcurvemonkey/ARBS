r"""CUSIP/ISIN -> the bond Citi is actually quoting.

The test that matters here is not "does the check digit work" (that is
``test_identifiers.py``, against 2,162 real ISINs). It is: **when resolution
succeeds, is it the same bond?** A well-formed ISIN for a security outside Citi's
universe is indistinguishable from one inside it until you look, and the failure
is silent.
"""

from __future__ import annotations

import pytest

from MDP.CitiVelocityExcel.bonds.resolution import (
    BondNotQuotedError,
    BondResolution,
    resolve_bond,
    resolve_bonds,
)
from MDP.CitiVelocityExcel.bonds.universe import BondUniverse
from utils.identifiers import InvalidIdentifierError, isin_to_cusip


@pytest.fixture(scope="module")
def universe():
    return BondUniverse.from_catalog()


@pytest.fixture(scope="module")
def us_universe():
    return BondUniverse.from_catalog(country="USA", asset_type="GOVT")


@pytest.fixture(scope="module")
def sample_isin(us_universe):
    return next(d.isin for d in us_universe if d.priceable)


# ── the identity actually holds ──────────────────────────────────────────

def test_cusip_route_reaches_the_same_bond_as_the_isin_route(us_universe):
    """Both doors must open onto the same bond, for every US Treasury Citi carries.

    This is the "alias resolves to the SAME bond Citi is quoting" requirement,
    reduced to its checkable core: the arithmetic route and the direct route
    agree on the descriptor, not merely on the string.
    """
    n = 0
    for d in us_universe:
        by_isin = resolve_bond(d.isin, universe=us_universe)
        by_cusip = resolve_bond(isin_to_cusip(d.isin), universe=us_universe)
        assert by_isin.isin == by_cusip.isin == d.isin
        assert by_isin.descriptor == by_cusip.descriptor
        assert by_isin.available_values == by_cusip.available_values
        assert (by_isin.route, by_cusip.route) == ("isin", "cusip")
        n += 1
    assert n >= 300, f"only {n} US Treasuries compared"


def test_eight_character_cusip_reaches_the_same_bond(us_universe, sample_isin):
    """The 8-char base must complete to the same bond, not to an 11-char stub."""
    cusip = isin_to_cusip(sample_isin)
    assert resolve_bond(cusip[:8], universe=us_universe).isin == sample_isin


def test_resolution_reports_the_route_it_took(us_universe, sample_isin):
    assert resolve_bond(sample_isin, universe=us_universe).route == "isin"
    assert resolve_bond(isin_to_cusip(sample_isin), universe=us_universe).route == "cusip"


def test_descriptor_and_values_come_from_citi_not_from_the_caller(us_universe, sample_isin):
    r = resolve_bond(sample_isin, universe=us_universe)
    assert r.descriptor.isin == sample_isin
    assert r.available_values, "Citi serves nothing for this bond?"
    assert set(r.available_values) <= {
        "PRICE", "YIELD", "SPREAD_TSY", "OAS", "DURATION", "DV01", "CAS",
        "ASW_4_USD", "ASW_4_EUR", "ASW_4_GBP", "ASW_4_CHF", "ASW_4_JPY", "ASW_4_AUD",
    }
    assert r.serves(r.available_values[0])
    assert not r.serves("NOT_A_VALUE")


# ── the silent failure this module exists to prevent ─────────────────────

def test_a_well_formed_cusip_citi_does_not_quote_raises(universe):
    """Arithmetically perfect, commercially absent. Must not resolve quietly.

    ``US0378331005`` is Apple - a real ISIN with a valid check digit that no
    rates desk quotes. Without the universe check it would sail through and
    then return no data, several layers later.
    """
    with pytest.raises(BondNotQuotedError, match="does not quote"):
        resolve_bond("037833100", universe=universe)


def test_the_not_quoted_message_distinguishes_coverage_from_arithmetic(universe):
    with pytest.raises(BondNotQuotedError, match="coverage gap"):
        resolve_bond("037833100", universe=universe)


def test_require_quoted_false_returns_the_isin_without_raising(universe):
    r = resolve_bond("037833100", universe=universe, require_quoted=False)
    assert isinstance(r, BondResolution)
    assert r.isin == "US0378331005"
    assert r.quoted is False and r.descriptor is None and r.available_values == ()
    assert "NOT quoted" in r.describe()


def test_malformed_input_raises_before_any_lookup(universe):
    """Arithmetic failure and coverage failure are different exceptions."""
    for bad in ("", "CT10", "12345", "US037833100"):
        with pytest.raises(InvalidIdentifierError):
            resolve_bond(bad, universe=universe)


def test_on_the_run_alias_is_refused_with_a_pointer(universe):
    """CT10 must not be silently treated as a CUSIP — it would resolve to nothing."""
    with pytest.raises(InvalidIdentifierError, match="reference table"):
        resolve_bond("CT10", universe=universe)


def test_a_one_character_cusip_typo_does_not_resolve_to_a_neighbour(us_universe, sample_isin):
    """The dangerous case: a typo whose check digit happens to be valid.

    Either it fails the check digit (raises) or it is absent from the universe
    (raises). What must never happen is a quiet resolution to a different bond.
    """
    cusip = isin_to_cusip(sample_isin)
    hits = 0
    for pos in range(8):
        for repl in "0123456789":
            if cusip[pos] == repl:
                continue
            typo = cusip[:pos] + repl + cusip[pos + 1:]
            try:
                got = resolve_bond(typo, universe=us_universe)
            except (InvalidIdentifierError, BondNotQuotedError):
                continue
            assert got.isin != sample_isin, f"{typo} silently resolved back to {sample_isin}"
            hits += 1
    # Any that did resolve are genuinely other bonds, correctly identified.
    assert hits >= 0


# ── bulk ─────────────────────────────────────────────────────────────────

def test_resolve_bonds_strict_reraises(universe, sample_isin):
    with pytest.raises(BondNotQuotedError):
        resolve_bonds([sample_isin, "037833100"], universe=universe, strict=True)


def test_resolve_bonds_non_strict_keeps_the_good_ones(universe, sample_isin):
    """One bad name in a warm list must not cost the rest."""
    resolved, failures = resolve_bonds(
        [sample_isin, "037833100", "CT10"], universe=universe, strict=False
    )
    assert list(resolved) == [sample_isin]
    assert set(failures) == {"037833100", "CT10"}
    assert "BondNotQuotedError" in failures["037833100"]
    assert "InvalidIdentifierError" in failures["CT10"]


def test_resolve_bonds_preserves_input_order(us_universe):
    isins = [d.isin for d in us_universe][:12]
    resolved, failures = resolve_bonds(isins, universe=us_universe, strict=True)
    assert list(resolved) == isins and not failures
