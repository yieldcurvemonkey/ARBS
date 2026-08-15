"""CBOT's re-opening clause: a 7-year note reopened as a 5-year becomes deliverable.

Verbatim, from CBOT Chapters 19/20/21/26 (primary source: the CFTC copy of CBOT submission 25-099,
filed 2025-02-21, companion SER #9520)::

    If the U.S. Treasury Department auctions and issues a Treasury security that meets these
    standards, such that said security is a re-opening of an extant Treasury issue that had not
    previously met these standards, then the extant Treasury issue shall be deemed to be a Treasury
    note meeting these standards and shall be added to the contract grade as of the issue date of
    said newly auctioned Treasury security.

The spec table cannot express that, and the reference frame could not either: `fiscaldata` collapses
a CUSIP's tranches keeping the EARLIEST, so `oi` said "7-Year" forever and the 63-month cap dropped
the note. Measured against CME's own published conversion-factor file for 2025-03-03:

    ZTH25   CME 11 CUSIPs, ours 10 -- missing 912828Z78 (T 1.5% Jan-27), CME conversion factor 0.9229
    ZFH25   CME 10 CUSIPs, ours  9 -- missing 91282CGQ8 (T 4.0% Feb-30), CME conversion factor 0.9159

After the fix both baskets reproduce CME exactly, conversion factors included. The obvious
alternative -- relax TU's cap from 63 to 84 months -- was refuted by measurement: it also admits
912828YX2, 912828ZB9 and 912828ZE3, which CME does not list.

Vintage matters: Chapters 20 (FV) and 21 (TU) carry the clause today; 25-099 adds it to Chapters 19
(TY) and 26 (UXY) "commencing with the March 2026 contract month". Applying one rule to all four
across all history would repeat the mistake this repo already documented for TY's 8-year cap.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.FixedRateBonds.reference_data_cache.fiscaldata import _add_reopening_columns
from MDP.USTFutures.treasury_conversion_factors import build_delivery_basket_frame


# --------------------------------------------------------------------------------------------
# the reference-data layer
# --------------------------------------------------------------------------------------------


def test_shortest_tranche_is_carried_forward():
    """CALIBRATION on a CUSIP whose answer is published: 912828Z78.

    Auction record: 7-Year issued 2020-01-31, reopened as a 5-Year issued 2022-01-31, both maturing
    2027-01-31. The shortest tranche is therefore 60 months as of 2022-01-31.
    """
    frame = pd.DataFrame(
        [
            {"cusip": "912828Z78", "issue_date": datetime.date(2020, 1, 31), "maturity_date": datetime.date(2027, 1, 31)},
            {"cusip": "912828Z78", "issue_date": datetime.date(2022, 1, 31), "maturity_date": datetime.date(2027, 1, 31)},
        ]
    )
    out = _add_reopening_columns(frame)
    assert set(out["reopened_term_months"]) == {60}
    assert set(out["reopened_issue_date"]) == {datetime.date(2022, 1, 31)}


def test_a_single_tranche_security_reports_its_own_term():
    frame = pd.DataFrame(
        [{"cusip": "91282CJJ1", "issue_date": datetime.date(2023, 8, 15), "maturity_date": datetime.date(2033, 8, 15)}]
    )
    out = _add_reopening_columns(frame)
    assert out["reopened_term_months"].iloc[0] == 120


def test_a_routine_same_term_reopening_does_not_shorten_the_grade():
    """A 7-year reopened a month later is still a 7-year note, and must stay out of ZF.

    Computing the term from DATES rather than parsing `security_term` is what makes this work: the
    string form runs to "6-Year 11-Month", and a parser keeping the leading number would report 72
    months and wrongly clear the 63-month cap.
    """
    frame = pd.DataFrame(
        [
            {"cusip": "AAA", "issue_date": datetime.date(2023, 2, 28), "maturity_date": datetime.date(2030, 2, 28)},
            {"cusip": "AAA", "issue_date": datetime.date(2023, 3, 31), "maturity_date": datetime.date(2030, 2, 28)},
        ]
    )
    out = _add_reopening_columns(frame)
    # 6y10m29d -> 82 whole months. Rounded DOWN, per CBOT's own "nearest one-month increment",
    # and still far above the 63-month cap.
    assert out["reopened_term_months"].iloc[0] == 82


def test_the_reference_loader_actually_requests_the_columns():
    """The frame must CARRY the markers, or every guard downstream is decorative.

    This exists because the columns were once added and then silently reverted -- the recorded
    "restore the rotated reference cache before committing" recipe uses a path that also contains
    this module's source, so `git checkout -- reference_data_cache` undid the edit and the guard
    tests kept passing, because they inject the columns themselves.
    """
    import inspect

    from MDP.FixedRateBonds.reference_data_cache import fiscaldata

    src = inspect.getsource(fiscaldata)
    for column in ("inflation_index_security", "floating_rate", "reopened_term_months", "reopened_issue_date"):
        assert f'"{column}"' in src.split("keep = [")[1].split("]")[0], f"{column} missing from the keep list"


# --------------------------------------------------------------------------------------------
# the grade
# --------------------------------------------------------------------------------------------

_AS_OF = datetime.date(2025, 3, 3)


def _five_year_frame(**reopen) -> pd.DataFrame:
    """Two genuine 5-year notes plus a 7-year note in FVH25's window."""
    rows = [
        {"cusip": "91282CKT7", "label": "T 4 1/8 Oct-29", "oi": "5-Year", "auction_date": datetime.date(2024, 10, 28),
         "issue_date": datetime.date(2024, 10, 31), "maturity_date": datetime.date(2029, 10, 31), "cpn": 4.125,
         "reopened_term_months": 60, "reopened_issue_date": datetime.date(2024, 10, 31)},
        {"cusip": "91282CLC3", "label": "T 4 1/4 Dec-29", "oi": "5-Year", "auction_date": datetime.date(2024, 12, 23),
         "issue_date": datetime.date(2024, 12, 31), "maturity_date": datetime.date(2029, 12, 31), "cpn": 4.25,
         "reopened_term_months": 60, "reopened_issue_date": datetime.date(2024, 12, 31)},
    ]
    seven = {"cusip": "91282CGQ8", "label": "T 4 Feb-30", "oi": "7-Year", "auction_date": datetime.date(2023, 2, 23),
             "issue_date": datetime.date(2023, 2, 28), "maturity_date": datetime.date(2030, 2, 28), "cpn": 4.0,
             "reopened_term_months": 84, "reopened_issue_date": datetime.date(2023, 2, 28)}
    seven.update(reopen)
    rows.append(seven)
    return pd.DataFrame(rows)


def test_a_seven_year_note_is_excluded_until_it_is_reopened_as_a_five_year():
    """The whole clause in one pair of assertions."""
    never = build_delivery_basket_frame(as_of=_AS_OF, symbol="FVH25", reference_data=_five_year_frame())
    assert "91282CGQ8" not in set(never["cusip"])

    reopened = build_delivery_basket_frame(
        as_of=_AS_OF,
        symbol="FVH25",
        reference_data=_five_year_frame(reopened_term_months=60, reopened_issue_date=datetime.date(2025, 2, 28)),
    )
    assert "91282CGQ8" in set(reopened["cusip"])


def test_the_grade_changes_on_the_reopening_issue_date_and_not_before():
    """"as of the issue date of said newly auctioned Treasury security" -- to the day."""
    frame = _five_year_frame(reopened_term_months=60, reopened_issue_date=datetime.date(2025, 2, 28))

    before = build_delivery_basket_frame(as_of=datetime.date(2025, 2, 27), symbol="FVH25", reference_data=frame)
    on_the_day = build_delivery_basket_frame(as_of=datetime.date(2025, 2, 28), symbol="FVH25", reference_data=frame)

    assert "91282CGQ8" not in set(before["cusip"])
    assert "91282CGQ8" in set(on_the_day["cusip"])


def test_the_conversion_factor_of_a_reopened_note_is_computed_off_its_real_coupon():
    """CME publishes 0.9159 for 91282CGQ8 into ZFH25. Ours must be the same number."""
    out = build_delivery_basket_frame(
        as_of=_AS_OF,
        symbol="FVH25",
        reference_data=_five_year_frame(reopened_term_months=60, reopened_issue_date=datetime.date(2025, 2, 28)),
    )
    cf = float(out.loc[out["cusip"] == "91282CGQ8", "invoice_conversion_factor"].iloc[0])
    assert cf == pytest.approx(0.9159, abs=5e-5)


def _ten_year_frame(**reopen) -> pd.DataFrame:
    """An aged 30-year bond sitting in UXY's 9y5m-10y remaining window, plus a real 10-year note."""
    rows = [
        {"cusip": "91282CJJ1", "label": "T 4 1/8 Aug-33", "oi": "10-Year", "auction_date": datetime.date(2023, 8, 9),
         "issue_date": datetime.date(2023, 8, 15), "maturity_date": datetime.date(2033, 8, 15), "cpn": 3.875,
         "reopened_term_months": 120, "reopened_issue_date": datetime.date(2023, 8, 15)},
    ]
    aged = {"cusip": "912810FT0", "label": "T 4 1/2 Feb-36", "oi": "30-Year", "auction_date": datetime.date(2006, 2, 9),
            "issue_date": datetime.date(2006, 2, 15), "maturity_date": datetime.date(2036, 2, 15), "cpn": 4.5,
            "reopened_term_months": 360, "reopened_issue_date": datetime.date(2006, 2, 15)}
    aged.update(reopen)
    rows.append(aged)
    return pd.DataFrame(rows)


def test_the_clause_is_vintage_gated_for_the_ultra_ten_year():
    """CBOT 25-099 adds it to Ch.19/Ch.26 from the MARCH 2026 contract month, not retroactively.

    Same discipline as TY's 8-year cap: a grade is not a constant, and applying today's to old
    contracts is its own defect.

    UXY is the root that exercises this, because 912810FT0 (4.5% Feb-2036) -- the CUSIP 25-099
    itself names as "the first available aging bond that potentially could be reopened as a 10-Year
    Note" -- falls in UXY's 9y5m-10y remaining window, not TY's 6y6m-8y one.
    """
    frame = _ten_year_frame(reopened_term_months=120, reopened_issue_date=datetime.date(2026, 2, 15))

    before = build_delivery_basket_frame(as_of=datetime.date(2026, 2, 20), symbol="UXYZ25", reference_data=frame)
    from_march = build_delivery_basket_frame(as_of=datetime.date(2026, 2, 20), symbol="UXYH26", reference_data=frame)

    assert "912810FT0" not in set(before["cusip"]), "the December-2025 contract predates the clause"
    assert "912810FT0" in set(from_march["cusip"]), "from the March 2026 contract month the clause applies"


def test_an_unreopened_aged_bond_is_still_excluded_after_march_2026():
    """The real 912810FT0 was never reopened as a note -- its only reopening was a 29-Year 6-Month
    bond in 2006, and Treasury issued a fresh CUSIP (91282CPZ8) for the same Feb-2036 maturity.
    CME's published TNU26 basket confirms its absence 3/3. Turning the clause on must not admit it.
    """
    frame = _ten_year_frame()  # shortest tranche stays 360 months
    out = build_delivery_basket_frame(as_of=datetime.date(2026, 2, 20), symbol="UXYH26", reference_data=frame)
    assert "912810FT0" not in set(out["cusip"])


def test_a_frame_without_the_reopening_columns_still_builds():
    """Legacy cached parquet has neither column; the clause simply does not fire."""
    frame = _five_year_frame().drop(columns=["reopened_term_months", "reopened_issue_date"])
    out = build_delivery_basket_frame(as_of=_AS_OF, symbol="FVH25", reference_data=frame)
    assert len(out) == 2
    assert "91282CGQ8" not in set(out["cusip"])
