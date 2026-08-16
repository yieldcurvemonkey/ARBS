"""BarChart's namespace is not Globex's, and the price band cannot tell them apart.

This repo already lost months to that: internal ``WN`` pointed at BarChart's ``UB``, which is the
CME Euro/Krone FX future, and a "compact 32nds" decoder turned 11.13 into a plausible-looking
111.40625. The lesson recorded then was that a plausibility band is not a discriminator.

Wiring the two remaining roots -- the 3-Year (Globex ``Z3N``) and the 20-Year (Globex ``TWE``) --
was done against that lesson rather than by guessing. Measured 2026-08-15 on EOD history:

    ZEM22  106.52-115.53, max volume 31,176   100% in the 50-300 band, 100% on the 1/256 grid
    ZEU26  104.06-107.13, max volume  9,690   100% / 100%
    ZZM22  136.34-175.63, max volume  1,896   100% / 100% (1/32)
    UBU26   10.81- 12.45, max volume    398     0% in band, 2.8% on tick   <- EUR/NOK, negative control
    TBU26   96.03- 97.19, max volume  4,921   100% IN BAND, 4.3% on tick   <- the trap

``TB`` is the point of the last row: it sits inside the plausible band and would have been accepted
by a band check, exactly as ``UB`` was. The tick grid is what discriminates.
"""

from __future__ import annotations

import datetime

import pytest

from definitions.USTFutures import (
    UST_FUTURE_BARCHART_ROOTS,
    UST_FUTURE_BARCHART_TO_INTERNAL,
    UST_FUTURE_GLOBEX_ROOTS,
    UST_FUTURE_TICK_SPECS,
    front_month,
    normalize_root,
    to_barchart_root,
    to_globex_root,
)
from MDP.USTFutures.USTFuturesMDP import _from_barchart_symbol, _normalize_symbol, _snapshot_root, _to_barchart_symbol


def test_every_root_with_a_tick_spec_is_reachable():
    """A spec nobody can fetch is a spec nobody checks. Z3N and TWE had one and no vendor root."""
    for root in UST_FUTURE_TICK_SPECS:
        assert root in UST_FUTURE_BARCHART_ROOTS, f"{root} has a tick spec but no BarChart root"
        assert root in UST_FUTURE_GLOBEX_ROOTS, f"{root} has a tick spec but no Globex root"


def test_the_two_namespaces_stay_separate():
    """They agree on every root except three; merging them is what caused the Ultra Bond defect."""
    assert to_barchart_root("WN") == "UD" and to_globex_root("WN") == "UB"
    assert to_barchart_root("Z3N") == "ZE" and to_globex_root("Z3N") == "Z3N"
    assert to_barchart_root("TWE") == "ZZ" and to_globex_root("TWE") == "TWE"
    for root in ("TU", "FV", "TY", "US", "UXY"):
        assert to_barchart_root(root) == to_globex_root(root)


def test_the_reverse_map_is_consistent():
    for internal, vendor in UST_FUTURE_BARCHART_ROOTS.items():
        assert UST_FUTURE_BARCHART_TO_INTERNAL[vendor] == internal


@pytest.mark.parametrize(
    "typed,internal,vendor",
    [
        ("Z3NU26", "Z3NU26", "ZEU26"),
        ("ZEU26", "Z3NU26", "ZEU26"),
        ("TWEU26", "TWEU26", "ZZU26"),
        ("ZZU26", "TWEU26", "ZZU26"),
        ("ZBU26", "USU26", "ZBU26"),
        ("UBU26", "WNU26", "UDU26"),
        ("WNU26", "WNU26", "UDU26"),
        ("TNU26", "UXYU26", "TNU26"),
        ("ZTU26", "TUU26", "ZTU26"),
    ],
)
def test_symbols_round_trip(typed, internal, vendor):
    """``Z3N`` contains a DIGIT, which the symbol regexes rejected. Anchoring plus a month-letter
    code group keeps ``ZBU26`` unambiguous while admitting ``Z3NU26``."""
    assert _normalize_symbol(typed) == internal
    assert _to_barchart_symbol(typed) == vendor
    assert _from_barchart_symbol(vendor) == internal


def test_snapshot_root_handles_a_digit_bearing_root():
    """The store partitions by root; ``Z3N`` must not collapse to ``Z3``."""
    assert _snapshot_root("Z3NU26") == "Z3N"
    assert _snapshot_root("TWEU26") == "TWE"
    assert _snapshot_root("WNU26") == "WN"


def test_the_new_roots_resolve_a_front_month():
    assert front_month(datetime.date(2026, 8, 15), "Z3N") == "Z3NU26"
    assert front_month(datetime.date(2026, 8, 15), "TWE") == "TWEU26"
    assert normalize_root("3Y") == "Z3N"
    assert normalize_root("20Y") == "TWE"
