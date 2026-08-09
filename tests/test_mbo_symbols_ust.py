"""Known-answer tests for the Treasury futures symbol grammar.

Every form here was taken from the archives on ``D:\\`` by resolving each
product's parent symbol, so the tests are against symbology the exchange actually
publishes rather than against a grammar someone reconstructed from a spec sheet.
"""
from __future__ import annotations

import datetime

import pytest

from RVUtils.MBO.symbols import parse_symbol, parse_symbols

REF = 2026


# --------------------------------------------------------------------------- #
# the four Treasury forms
# --------------------------------------------------------------------------- #

def test_outright():
    p = parse_symbol("ZNU6", REF)
    assert p.kind == "OUTRIGHT"
    assert p.root == "ZN"
    assert p.legs == ("ZNU6",)
    assert p.weights == (1,)
    assert p.months == (datetime.date(2026, 9, 1),)
    assert p.n_contracts == 1
    assert p.is_outright


def test_calendar_spread():
    p = parse_symbol("ZNU6-ZNZ6", REF)
    assert p.kind == "CALENDAR"
    assert p.root == "ZN"
    assert p.legs == ("ZNU6", "ZNZ6")
    assert p.weights == (1, -1)
    assert p.n_contracts == 2
    assert p.span_months() == 3
    assert p.label == "3m calendar"


def test_listed_butterfly():
    p = parse_symbol("ZN:BF M6-U6-Z6", REF)
    assert p.kind == "BUTTERFLY"
    assert p.root == "ZN"
    assert p.legs == ("ZNM6", "ZNU6", "ZNZ6")
    assert p.weights == (1, -2, 1)
    assert p.n_contracts == 4
    assert p.label == "3m fly"


def test_micro_intercommodity_legs_are_modelled():
    """Unlike SR3's inter-commodity spreads, full-versus-micro legs are known."""
    p = parse_symbol("TNU6-MTNU6", REF)
    assert p.kind == "INTERCOMMODITY"
    assert p.root == "TN"
    assert p.legs == ("TNU6", "MTNU6")
    assert p.weights == (1, -1)


def test_ultra_bond_versus_micro():
    p = parse_symbol("UBZ6-MWNZ6", REF)
    assert p.kind == "INTERCOMMODITY"
    assert p.root == "UB"
    assert p.legs == ("UBZ6", "MWNZ6")


# --------------------------------------------------------------------------- #
# every mapped symbol from the real archives, by product
# --------------------------------------------------------------------------- #

REAL_SYMBOLS = {
    "ZT": ["ZT:BF M6-U6-Z6", "ZT:BF U6-Z6-H7", "ZTH7", "ZTM6", "ZTM6-ZTU6",
           "ZTM6-ZTZ6", "ZTU6", "ZTU6-ZTH7", "ZTU6-ZTZ6", "ZTZ6", "ZTZ6-ZTH7"],
    "ZF": ["ZF:BF M6-U6-Z6", "ZF:BF U6-Z6-H7", "ZFH7", "ZFM6", "ZFM6-ZFU6",
           "ZFM6-ZFZ6", "ZFU6", "ZFU6-ZFH7", "ZFU6-ZFZ6", "ZFZ6", "ZFZ6-ZFH7"],
    "ZN": ["ZN:BF M6-U6-Z6", "ZN:BF U6-Z6-H7", "ZNH7", "ZNM6", "ZNM6-ZNU6",
           "ZNM6-ZNZ6", "ZNU6", "ZNU6-ZNH7", "ZNU6-ZNZ6", "ZNZ6", "ZNZ6-ZNH7"],
    "TN": ["TN:BF U6-Z6-H7", "TNH7", "TNU6", "TNU6-MTNU6", "TNU6-TNH7",
           "TNU6-TNZ6", "TNZ6", "TNZ6-MTNZ6", "TNZ6-TNH7"],
    "ZB": ["ZB:BF U6-Z6-H7", "ZBH7", "ZBU6", "ZBU6-ZBH7", "ZBU6-ZBZ6", "ZBZ6",
           "ZBZ6-ZBH7"],
    "UB": ["UBH7", "UBU6", "UBU6-MWNU6", "UBU6-UBH7", "UBU6-UBZ6", "UBZ6",
           "UBZ6-MWNZ6", "UBZ6-UBH7"],
}


@pytest.mark.parametrize("root", sorted(REAL_SYMBOLS))
def test_every_real_symbol_parses_to_a_known_kind(root):
    """Not one of the 57 mapped Treasury instruments may fall through to OTHER."""
    parsed = parse_symbols(REAL_SYMBOLS[root], REF)
    unknown = [s for s, p in parsed.items() if p.kind == "OTHER"]
    assert unknown == []
    for s, p in parsed.items():
        assert p.root == root, f"{s} rooted as {p.root}"
        assert len(p.legs) == len(p.weights)
        assert p.n_contracts >= 1


def test_the_full_treasury_universe_is_fifty_seven_instruments():
    assert sum(len(v) for v in REAL_SYMBOLS.values()) == 57


# --------------------------------------------------------------------------- #
# year decoding and units
# --------------------------------------------------------------------------- #

def test_year_digit_resolves_forward_from_the_reference_year():
    assert parse_symbol("ZNH7", REF).months == (datetime.date(2027, 3, 1),)
    assert parse_symbol("ZNH5", REF).months == (datetime.date(2035, 3, 1),)


def test_asking_a_treasury_instrument_for_a_basis_point_value_raises():
    """The failure this whole module exists to prevent.

    ``KINDS_QUOTED_IN_BP`` is an SR3 fact.  Consulting it globally reports a ZN
    calendar spread as quoted in basis points, which is not a wrong number so
    much as a meaningless one -- and it would propagate into every spread, cost
    and impact figure without ever looking wrong.  A price contract has no bp
    until a CTD DV01 supplies one, so this raises.
    """
    for sym in ("ZNU6", "ZNU6-ZNZ6", "ZN:BF M6-U6-Z6", "TNU6-MTNU6", "UBZ6"):
        p = parse_symbol(sym, REF)
        with pytest.raises(ValueError, match="no intrinsic basis-point value"):
            _ = p.bp_per_price_unit
        with pytest.raises(ValueError, match="no intrinsic basis-point value"):
            _ = p.usd_per_bp_per_lot


def test_the_raise_names_the_way_out():
    """An error that does not say what to do instead is a trap, not a guard."""
    with pytest.raises(ValueError, match="dv01_for"):
        _ = parse_symbol("ZNU6", REF).bp_per_price_unit


# --------------------------------------------------------------------------- #
# the dispatcher must not have disturbed SR3
# --------------------------------------------------------------------------- #

def test_sr3_parsing_is_unchanged_by_the_package_split():
    p = parse_symbol("SR3:BF Z6-H7-M7", REF)
    assert p.kind == "BUTTERFLY"
    assert p.root == "SR3"
    assert p.legs == ("SR3Z6", "SR3H7", "SR3M7")
    assert p.weights == (1, -2, 1)
    assert p.bp_per_price_unit == 1.0


def test_sr3_bundle_still_expands_to_its_quarterly_legs():
    p = parse_symbol("SR3:AB 01Y U6", REF)
    assert p.kind == "BUNDLE"
    assert p.root == "SR3"
    assert p.legs == ("SR3U6", "SR3Z6", "SR3H7", "SR3M7")
    assert p.unit_legs == 4
    assert p.usd_per_bp_per_lot == 100.0


def test_sr3_intercommodity_stays_unmodelled():
    """Its far leg is a product we hold no data for; inventing legs would be worse."""
    p = parse_symbol("SR3U6-TBF3U6", REF)
    assert p.kind == "INTERCOMMODITY"
    assert p.legs == ()


def test_unknown_root_is_other_and_does_not_raise():
    p = parse_symbol("XYZQ9", REF)
    assert p.kind == "OTHER"
    assert p.legs == ()
    assert p.root == ""
