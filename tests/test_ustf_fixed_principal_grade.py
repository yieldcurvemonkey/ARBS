"""The deliverable grade is FIXED-PRINCIPAL: no TIPS, no floating-rate notes.

CBOT Chapter 19 (and its siblings) restrict the grade to "U.S. Treasury fixed-principal notes which
have fixed semi-annual coupon payments". The repo's own note said that leg was unenforced because
the fiscaldata reference frame has no security-type column. That is half wrong, and the half that is
wrong is the dangerous half: the rule IS enforced, at FETCH time, by
``inflation_index_security:eq:No`` in the auctions query -- and by nothing else.

Measured: re-fetching with that one filter removed admits 106 TIPS CUSIPs and contaminates the
December-2026 basket of ALL SIX roots (TYZ26 3, TUZ26 1, FVZ26 1, USZ26 10, WNZ26 5, TNZ26 1). A 10-
year TIPS is ``security_type='Note'`` with a fixed ``int_rate`` and semi-annual payments; nothing but
that boolean separates it from a deliverable note, and its conversion factor gets computed off its
real coupon, which is economically meaningless.

So the filter is load-bearing on every root, and the comment told a future reader it was redundant.
These tests pin the behaviour at the layer that actually builds the basket, so the protection no
longer depends on one query string in a different package.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.USTFutures.treasury_conversion_factors import build_delivery_basket_frame

_AS_OF = datetime.date(2026, 8, 13)


def _reference_frame() -> pd.DataFrame:
    """Three genuine 10-year notes, all inside TYZ26's 6y6m-8y remaining window."""
    return pd.DataFrame(
        [
            {"cusip": "91282CJJ1", "label": "T 4 1/8 Aug-33", "oi": "10-Year", "auction_date": datetime.date(2023, 8, 9),
             "issue_date": datetime.date(2023, 8, 15), "maturity_date": datetime.date(2033, 8, 15), "cpn": 3.875},
            {"cusip": "91282CJT1", "label": "T 4 1/2 Nov-33", "oi": "10-Year", "auction_date": datetime.date(2023, 11, 8),
             "issue_date": datetime.date(2023, 11, 15), "maturity_date": datetime.date(2033, 11, 15), "cpn": 4.5},
            {"cusip": "91282CKB6", "label": "T 4 Feb-34", "oi": "10-Year", "auction_date": datetime.date(2024, 2, 7),
             "issue_date": datetime.date(2024, 2, 15), "maturity_date": datetime.date(2034, 2, 15), "cpn": 4.0},
        ]
    )


def _tips_row(**overrides) -> dict:
    """A real 10-year TIPS: TII 1 3/4 Jan-34. Indistinguishable from a note on every other field."""
    row = {
        "cusip": "91282CJY0", "label": "TII 1 3/4 Jan-34", "oi": "10-Year",
        "auction_date": datetime.date(2024, 1, 18), "issue_date": datetime.date(2024, 1, 31),
        "maturity_date": datetime.date(2034, 1, 15), "cpn": 1.75,
    }
    row.update(overrides)
    return row


def _frn_row(**overrides) -> dict:
    """A 2-year FRN: quarterly, no fixed coupon. `cpn` is NaN, which is what excludes it today."""
    row = {
        "cusip": "91282CLL3", "label": "TF 0 Jul-28", "oi": "2-Year",
        "auction_date": datetime.date(2026, 7, 22), "issue_date": datetime.date(2026, 7, 31),
        "maturity_date": datetime.date(2028, 7, 31), "cpn": float("nan"),
    }
    row.update(overrides)
    return row


def test_a_tips_carrying_the_marker_is_excluded_from_the_basket():
    """The frame-level guard. A TIPS row flagged as inflation-indexed must never be deliverable."""
    base = build_delivery_basket_frame(as_of=_AS_OF, symbol="TYZ26", reference_data=_reference_frame())

    frame = _reference_frame()
    frame["inflation_index_security"] = "No"
    contaminated = pd.concat([frame, pd.DataFrame([_tips_row(inflation_index_security="Yes")])], ignore_index=True)

    with_tips = build_delivery_basket_frame(as_of=_AS_OF, symbol="TYZ26", reference_data=contaminated)

    assert "91282CJY0" not in set(with_tips["cusip"]), "an inflation-indexed security is not fixed-principal"
    assert set(with_tips["cusip"]) == set(base["cusip"])


def test_a_floating_rate_note_carrying_the_marker_is_excluded():
    frame = _reference_frame()
    frame["floating_rate"] = "No"
    # Give the FRN a coupon so the incidental `cpn.notna()` gate cannot be what excludes it.
    contaminated = pd.concat(
        [frame, pd.DataFrame([_frn_row(floating_rate="Yes", cpn=0.0, oi="10-Year", maturity_date=datetime.date(2033, 7, 31))])],
        ignore_index=True,
    )
    out = build_delivery_basket_frame(as_of=_AS_OF, symbol="TYZ26", reference_data=contaminated)
    assert "91282CLL3" not in set(out["cusip"])


def test_the_guard_calibrates_against_an_unflagged_tips():
    """CALIBRATION, and the honest statement of what the frame guard can and cannot do.

    Without the marker column a TIPS is indistinguishable from a note at this layer -- it IS
    admitted, and a conversion factor is computed off its real coupon. This is exactly why the
    fetch-time ``inflation_index_security:eq:No`` filter is load-bearing and must not be removed as
    "redundant". It also proves the two tests above are testing the marker, not some other filter
    that happens to catch this CUSIP.
    """
    contaminated = pd.concat([_reference_frame(), pd.DataFrame([_tips_row()])], ignore_index=True)
    out = build_delivery_basket_frame(as_of=_AS_OF, symbol="TYZ26", reference_data=contaminated)
    assert "91282CJY0" in set(out["cusip"])


def test_a_frame_without_the_marker_columns_still_builds():
    """Cached frames written before the columns were requested must keep working, not fail closed.

    ``_cleanup_old_cache_dirs`` keeps three dated directories, so for up to three days after this
    change the on-disk parquet has neither column. The guard fires only when the column is present.
    """
    out = build_delivery_basket_frame(as_of=_AS_OF, symbol="TYZ26", reference_data=_reference_frame())
    assert len(out) == 3
    assert out["invoice_conversion_factor"].notna().all()


def test_the_fetch_query_still_asks_the_api_to_exclude_tips_and_frns():
    """A string test, deliberately. This filter is the only thing standing between the basket and
    106 TIPS CUSIPs, and it is one edit away from being deleted as redundant."""
    import inspect

    from MDP.FixedRateBonds.reference_data_cache import fiscaldata

    src = inspect.getsource(fiscaldata._fetch_auctions_raw_fiscaldata)
    assert "inflation_index_security:eq:No" in src
    assert 'frn_index_determination_rate"] == "null"' in src
