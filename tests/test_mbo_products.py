"""Known-answer tests for the product registry.

The registry is the single place that knows what a contract's prices mean.  Every
tick below is either measured from the archives on ``D:\\`` or taken from the CME
contract specification; the tests exist so that a later edit cannot quietly change
one, because a wrong tick here is invisible downstream.
"""
from __future__ import annotations

from fractions import Fraction

import pytest

from RVUtils.MBO.products import (
    PRODUCTS,
    check_tick,
    is_known_root,
    root_of,
    spec_for,
)

TREASURY_ROOTS = ("ZT", "ZF", "ZN", "TN", "ZB", "UB")


# --------------------------------------------------------------------------- #
# registry shape
# --------------------------------------------------------------------------- #

def test_every_registered_root_is_self_consistent():
    for root, spec in PRODUCTS.items():
        assert spec.root == root
        assert spec.outright_tick > 0
        assert spec.usd_per_tick > 0
        assert spec.grammar in ("sr3", "ust")
        assert spec.quote in ("index_points", "points_32nds")
        assert spec.match_algo in ("FIFO", "PRORATA", "SPLIT")


def test_sr3_is_a_rate_contract_with_an_intrinsic_basis_point_value():
    s = spec_for("SR3")
    assert s.outright_tick == Fraction(1, 200)          # 0.005 index points
    assert s.usd_per_tick == pytest.approx(12.50)
    assert s.usd_per_bp_per_lot == pytest.approx(25.0)
    # 0.005 index points is half a basis point, and half of $25 is $12.50.
    assert s.usd_per_point == pytest.approx(2500.0)


def test_treasury_products_have_no_intrinsic_basis_point_value():
    """A price contract's bp needs a CTD DV01, so the registry must not invent one."""
    for root in TREASURY_ROOTS:
        assert spec_for(root).usd_per_bp_per_lot is None


@pytest.mark.parametrize(
    "root, tick, usd",
    [
        ("ZT", Fraction(1, 256), 7.8125),
        ("ZF", Fraction(1, 128), 7.8125),
        ("ZN", Fraction(1, 64), 15.625),
        ("TN", Fraction(1, 64), 15.625),
        ("ZB", Fraction(1, 32), 31.25),
        ("UB", Fraction(1, 32), 31.25),
    ],
)
def test_treasury_outright_ticks_match_the_measured_lattice(root, tick, usd):
    """These are the gcd of price offsets over tens of thousands of real prints."""
    s = spec_for(root)
    assert s.outright_tick == tick
    assert s.usd_per_tick == pytest.approx(usd)


def test_treasury_dollar_per_tick_follows_from_notional_and_tick():
    for root in TREASURY_ROOTS:
        s = spec_for(root)
        assert s.usd_per_tick == pytest.approx(
            s.contract_unit * float(s.outright_tick) / 100.0
        )


def test_sr3_bundles_quote_on_a_quarter_tick_not_the_outright_tick():
    """Measured: 1/400 over 44,554 bundle prints against 1/200 for outrights."""
    assert spec_for("SR3").tick_for("BUNDLE") == Fraction(1, 400)


def test_sr3_differential_instruments_tick_in_half_a_basis_point():
    s = spec_for("SR3")
    for kind in ("CALENDAR", "BUTTERFLY", "CONDOR", "DOUBLE_FLY", "BUNDLE_SPREAD"):
        assert s.tick_for(kind) == Fraction(1, 2)


def test_sr3_lead_contract_ticks_finer_than_the_deferreds():
    s = spec_for("SR3")
    assert s.outright_tick_front == Fraction(1, 400)
    assert s.tick_for("OUTRIGHT") == Fraction(1, 400)


# --------------------------------------------------------------------------- #
# root resolution
# --------------------------------------------------------------------------- #

def test_root_of_finds_the_root_in_every_symbol_form():
    assert root_of("SR3Z6") == "SR3"
    assert root_of("SR3:BF Z6-H7-M7") == "SR3"
    assert root_of("SR3Z6-SR3H7") == "SR3"
    assert root_of("SR3:AB 01Y U6") == "SR3"
    assert root_of("ZNU6") == "ZN"
    assert root_of("ZNU6-ZNZ6") == "ZN"
    assert root_of("ZN:BF M6-U6-Z6") == "ZN"
    assert root_of("TNU6-MTNU6") == "TN"


def test_root_of_prefers_the_longest_matching_root():
    """TN and ZN both end in N; a shortest-match rule would mis-root one of them."""
    assert root_of("TNZ6") == "TN"
    assert root_of("ZNZ6") == "ZN"
    assert root_of("TNU6-TNZ6") == "TN"


def test_root_of_returns_none_for_an_unknown_product():
    assert root_of("WOBBLE") is None
    assert root_of("") is None


def test_is_known_root():
    assert is_known_root("ZN")
    assert not is_known_root("MTN")


def test_unknown_root_raises_in_spec_for():
    with pytest.raises(KeyError):
        spec_for("WOBBLE")


# --------------------------------------------------------------------------- #
# the tick gate
# --------------------------------------------------------------------------- #

def test_check_tick_accepts_the_specified_tick():
    assert check_tick("SR3", "CALENDAR", 0.5) == Fraction(1, 2)
    assert check_tick("ZN", "OUTRIGHT", 0.015625) == Fraction(1, 64)


def test_check_tick_accepts_a_coarser_grid_from_a_quiet_instrument():
    """A gcd over forty prints is an integer multiple of the true tick."""
    assert check_tick("ZN", "OUTRIGHT", 0.015625 * 4) == Fraction(1, 64)


def test_check_tick_accepts_a_finer_grid_than_the_spec_claims():
    """A spec that is too coarse is a bug in the table, not a reason to refuse
    to replay: the ladder uses the observed lattice either way."""
    assert check_tick("ZB", "CALENDAR", float(Fraction(1, 512))) == Fraction(1, 128)


def test_check_tick_raises_on_a_hundredfold_disagreement():
    """The failure this gate exists for: a differential instrument's price read as
    index points reports a one-tick market as fifty basis points wide."""
    with pytest.raises(ValueError, match="tick disagreement"):
        check_tick("SR3", "CALENDAR", 0.005)


def test_check_tick_raises_on_a_non_integer_ratio():
    with pytest.raises(ValueError, match="tick disagreement"):
        check_tick("ZN", "OUTRIGHT", 0.015625 * 1.5)


def test_check_tick_raises_on_a_non_positive_tick():
    with pytest.raises(ValueError, match="tick disagreement"):
        check_tick("ZN", "OUTRIGHT", 0.0)
