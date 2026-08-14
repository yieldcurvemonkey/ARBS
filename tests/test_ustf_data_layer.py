"""Regression tests for the UST futures data layer.

One test per measured defect. Each was confirmed to FAIL against the unfixed code before the fix
landed -- a test that passes on both sides of a change is not a regression test.

Defects covered:
  1. the Ultra Bond's vendor root pointed at BarChart's EUR/NOK future  (see
     test_ust_futures_price_normalization.py)
  2. the ZN deliverable basket admitted notes 6 months too short AND old 30-year bonds
  3. the repo rate ignored the reference date, so every historical report used today's fixing
  4. nothing on the read path checked whether the numbers could be a market
  5. a cached basis report built by older code was served without question
  6. the report builder zipped one basket's labels against another basket's risk numbers
"""

import datetime
import math

import pandas as pd
import pytest

from MDP.USTFutures.basis_report_quality import (
    BasisReportQualityError,
    check_basis_report,
    enforce_basis_report_quality,
)
from MDP.USTFutures.treasury_conversion_factors import (
    build_delivery_basket_frame,
    get_contract_spec,
)
from MDP.USTFutures.USTFuturesMDP import _BASIS_REPORT_SCHEMA_VERSION, USTFuturesMDP


# --------------------------------------------------------------------------------------------
# Defect 2: the ZN deliverable window
# --------------------------------------------------------------------------------------------

def _refdata(rows):
    return pd.DataFrame(
        [
            {
                "cusip": cusip,
                "label": label,
                "oi": oi,
                "auction_date": datetime.date(2015, 1, 15),
                "issue_date": datetime.date(2015, 2, 15),
                "maturity_date": maturity,
                "cpn": cpn,
            }
            for cusip, label, oi, maturity, cpn in rows
        ]
    )


# Delivery month is June 2024, so the first day of the delivery month is 2024-06-01.
#   CBOT Ch.19: deliverable = original term <= 10y AND remaining >= 6y6m and < 8y.
_AS_OF = datetime.date(2024, 4, 15)
_ZN_FIXTURE = _refdata(
    [
        # remaining 6y2m -- SHORT of the 6y6m minimum, must be excluded
        ("SHORT6Y2M", "T 4 Aug 30", "10-Year", datetime.date(2030, 8, 15), 4.0),
        # remaining 6y8m -- deliverable
        ("NOTE6Y8M", "T 4 Feb 31", "10-Year", datetime.date(2031, 2, 15), 4.0),
        # a 7-year note with 7y0m remaining -- deliverable (original term 7y <= 10y)
        ("NOTE7YR", "T 4 1/8 Jun 31", "7-Year", datetime.date(2031, 6, 30), 4.125),
        # an OLD 30-YEAR BOND with 6y9m remaining -- NOT a note, must be excluded
        ("BOND30YR", "T 5 3/8 Feb 31", "30-Year", datetime.date(2031, 2, 15), 5.375),
        # a 20-year bond with 7y remaining -- also not deliverable into ZN
        ("BOND20YR", "T 4 3/4 May 31", "20-Year", datetime.date(2031, 5, 15), 4.75),
        # remaining 8y1m -- beyond the "less than 8 years" ceiling
        ("LONG8Y1M", "T 4 Jul 32", "10-Year", datetime.date(2032, 7, 15), 4.0),
    ]
)


def test_zn_basket_excludes_notes_shorter_than_six_years_six_months():
    basket = build_delivery_basket_frame(as_of=_AS_OF, symbol="ZNM24", reference_data=_ZN_FIXTURE)
    assert "SHORT6Y2M" not in set(basket["cusip"]), (
        "a note with 6y2m remaining is not deliverable into the 10-year contract"
    )


def test_zn_basket_excludes_old_long_bonds():
    """The dominant leak: 30-year bonds with 6.5-8y left carry 5-7% coupons, so they look
    cheapest-to-deliver whenever yields are under the 6% notional coupon."""
    basket = build_delivery_basket_frame(as_of=_AS_OF, symbol="ZNM24", reference_data=_ZN_FIXTURE)
    cusips = set(basket["cusip"])
    assert "BOND30YR" not in cusips
    assert "BOND20YR" not in cusips


def test_zn_basket_keeps_the_genuinely_deliverable_notes():
    basket = build_delivery_basket_frame(as_of=_AS_OF, symbol="ZNM24", reference_data=_ZN_FIXTURE)
    cusips = set(basket["cusip"])
    assert "NOTE6Y8M" in cusips
    assert "NOTE7YR" in cusips, "7-year notes ARE deliverable into ZN"
    assert "LONG8Y1M" not in cusips


def test_ty_spec_matches_the_cbot_rulebook():
    spec = get_contract_spec("TY")
    assert spec.min_remaining_months_from_first == 78, "6 years 6 months"
    assert spec.max_remaining_months_from_first == 96
    assert spec.max_remaining_months_from_first_exclusive is True, "less than 8 years"
    assert spec.max_original_term_months == 120, "notes only: original term <= 10 years"
    assert spec.max_remaining_effective_period == 202309, "the 8-year cap starts Sept 2023"


# The ZN grade is not a constant. Per CME SER-9102 the "less than 8 years" cap commences with the
# September 2023 contract month; before that there was no maximum. CME's own published December-2017
# ZN basket ("Understanding Treasury Futures", Table 3) runs 6.50-9.67 years and holds 17
# securities, which an 8-year cap would cut to 4.
_VINTAGE_FIXTURE = _refdata(
    [
        ("SHORT", "T 4 Jan 27", "10-Year", datetime.date(2027, 1, 15), 4.0),   # 6y1m from 2020-12 -- too short
        ("MID", "T 4 Nov 27", "10-Year", datetime.date(2027, 11, 15), 4.0),    # 6y11m -- deliverable in both eras
        ("LONG", "T 4 Aug 29", "10-Year", datetime.date(2029, 8, 15), 4.0),    # 8y8m -- only pre-cap
    ]
)


def test_pre_september_2023_zn_grade_has_no_maximum_remaining_term():
    """ZNZ20: delivery period 202012, before the cap commenced."""
    basket = build_delivery_basket_frame(
        as_of=datetime.date(2020, 10, 15), symbol="ZNZ20", reference_data=_VINTAGE_FIXTURE
    )
    cusips = set(basket["cusip"])
    assert "LONG" in cusips, "an 8y8m note WAS deliverable into pre-Sept-2023 ZN"
    assert "MID" in cusips
    assert "SHORT" not in cusips, "the 6y6m minimum applied in both eras"


def test_post_september_2023_zn_grade_applies_the_eight_year_cap():
    """ZNZ26: delivery period 202612, after the cap commenced. Same fixture, different answer."""
    basket = build_delivery_basket_frame(
        as_of=datetime.date(2026, 8, 13), symbol="ZNZ26", reference_data=_VINTAGE_FIXTURE
    )
    assert "LONG" not in set(basket["cusip"]), "the 8-year cap applies from Sept 2023"


@pytest.mark.parametrize(
    "root,attr,expected",
    [
        ("TU", "min_remaining_months_from_first", 21),
        ("TU", "max_original_term_months", 63),
        ("Z3N", "min_remaining_months_from_first", 33),
        ("Z3N", "max_original_term_months", 84),
        ("FV", "min_remaining_months_from_first", 50),
        ("FV", "max_original_term_months", 63),
        ("UXY", "min_remaining_months_from_first", 113),
        ("TWE", "min_remaining_months_from_first", 230),
        ("US", "min_remaining_months_from_first", 180),
        ("US", "max_remaining_months_from_first", 300),
        ("WN", "min_remaining_months_from_first", 300),
        ("WN", "max_remaining_months_from_first", None),
    ],
)
def test_other_deliverable_specs_are_unchanged(root, attr, expected):
    """These already matched the rulebook; pin them so the TY fix cannot drift into its neighbours."""
    assert getattr(get_contract_spec(root), attr) == expected


# --------------------------------------------------------------------------------------------
# Defect 3: the repo rate ignored the reference date
# --------------------------------------------------------------------------------------------

def test_repo_rate_uses_the_fixing_at_the_reference_date(monkeypatch):
    """_fetch_fixings ignores its as_of_date and returns the whole series; taking .tail(1) of that
    used TODAY's overnight rate for every historical report."""
    import Query.USTFutures.backends.rateslib.RLUSTFuturePricer as mod

    series = pd.Series(
        [0.0167, 0.0010, 0.0532, 0.0362],
        index=pd.to_datetime(["2018-06-12", "2020-10-15", "2024-04-15", "2026-08-13"]),
    )
    monkeypatch.setattr(mod, "_fetch_fixings", lambda **kwargs: series)

    pricer = mod.RLUSTFuturePricer(
        symbol="USM24",
        reference_date=datetime.date(2020, 10, 15),
        price=175.1875,
    )
    assert pricer._resolve_repo_rate() == pytest.approx(0.10), "October 2020 SOFR, not today's 3.62%"

    pricer_2018 = mod.RLUSTFuturePricer(
        symbol="USU18",
        reference_date=datetime.date(2018, 6, 12),
        price=142.875,
    )
    assert pricer_2018._resolve_repo_rate() == pytest.approx(1.67)


def test_repo_rate_explicit_override_still_wins(monkeypatch):
    import Query.USTFutures.backends.rateslib.RLUSTFuturePricer as mod

    monkeypatch.setattr(mod, "_fetch_fixings", lambda **kwargs: pd.Series(dtype=float))
    pricer = mod.RLUSTFuturePricer(symbol="USM24", reference_date=datetime.date(2024, 4, 15), price=114.0)
    assert pricer._resolve_repo_rate(repo_rate=5.3) == 5.3


# --------------------------------------------------------------------------------------------
# Defect 4: a consistency gate that is actually read
# --------------------------------------------------------------------------------------------

def _report(n=3, futures_price=114.21875, bnoc=0.08, irr=4.86, repo=5.32, cf=0.75):
    return pd.DataFrame(
        {
            "cusip": [f"C{i}" for i in range(n)],
            "label": [f"T 4 Feb 4{i}" for i in range(n)],
            "clean_price": [95.0 + i for i in range(n)],
            "ytm": [4.5] * n,
            "invoice_cf": [cf] * n,
            "gross_basis": [0.1] * n,
            "bnoc": [bnoc + 0.01 * i for i in range(n)],
            "irr": [irr - 0.01 * i for i in range(n)],
            "futures_price": [futures_price] * n,
            "repo_rate": [repo] * n,
            "trading_date": [datetime.date(2024, 4, 15)] * n,
            "delivery_date": [datetime.date(2024, 6, 28)] * n,
        }
    )


def test_gate_passes_a_healthy_report():
    assert check_basis_report(_report()).ok


def test_gate_catches_a_wrong_instrument_price():
    """The Ultra Bond defect: an EUR/NOK rate served as a futures price."""
    verdict = check_basis_report(_report(futures_price=11.13))
    assert not verdict.ok
    assert any("plausible band" in r for r in verdict.reasons)


def test_gate_catches_an_impossible_implied_repo():
    """The ZN defect: a bond that is not deliverable prices as a 14% riskless return."""
    verdict = check_basis_report(_report(irr=21.78, repo=0.08))
    assert not verdict.ok
    assert any("implied repo" in r for r in verdict.reasons)


def test_gate_catches_an_arbitrage_sized_net_basis():
    verdict = check_basis_report(_report(bnoc=17.8))  # +571/32, the Ultra Bond's actual value
    assert not verdict.ok
    assert any("net basis" in r for r in verdict.reasons)


def test_gate_is_carry_adjusted_and_does_not_flag_a_high_carry_regime():
    """The point of the whole design. In 2020-21, repo near zero against a 2-3% coupon makes GROSS
    basis large for perfectly good ZB data; a gross-basis rule rejected 58% of healthy ZB in 2021.
    A large gross basis with a small net basis must pass."""
    df = _report(bnoc=0.125, irr=-0.39, repo=0.10)
    df["gross_basis"] = 0.85  # +27/32, ZB's real October-2020 value
    assert check_basis_report(df).ok


def test_gate_ignores_implied_repo_close_to_delivery():
    """Implied repo annualises a shrinking horizon, so it is legitimately wild near delivery."""
    df = _report(irr=40.0, repo=5.32)
    df["trading_date"] = [datetime.date(2024, 6, 20)] * len(df)  # 8 days out
    assert check_basis_report(df).ok


def test_gate_catches_nan_contamination():
    df = _report()
    df.loc[1, "bnoc"] = float("nan")
    verdict = check_basis_report(df)
    assert not verdict.ok
    assert any("non-finite" in r for r in verdict.reasons)


def test_gate_treats_an_empty_report_as_absence_not_corruption():
    """A holiday, an unlisted contract or a symbol with no basket produces no rows. There is
    nothing there to contradict itself, so there is nothing to fail -- and raising would break
    callers that legitimately expect an empty frame."""
    assert check_basis_report(pd.DataFrame()).ok
    assert check_basis_report(None).ok
    out = enforce_basis_report_quality(pd.DataFrame(), symbol="USM26")
    assert out.empty


def test_enforce_raises_by_default_so_a_passive_caller_cannot_consume_bad_data():
    with pytest.raises(BasisReportQualityError):
        enforce_basis_report_quality(_report(futures_price=11.13), symbol="WNM24")


def test_enforce_annotates_so_the_verdict_travels_with_the_data():
    out = enforce_basis_report_quality(_report(futures_price=11.13), symbol="WNM24", on_bad_data="warn")
    assert not out["data_ok"].iloc[0]
    assert "plausible band" in out["data_quality_reason"].iloc[0]

    good = enforce_basis_report_quality(_report(), symbol="USM24")
    assert good["data_ok"].all()
    assert (good["data_quality_reason"] == "").all()


# --------------------------------------------------------------------------------------------
# Defect 5: stale cached reports
# --------------------------------------------------------------------------------------------

def test_a_cached_report_without_the_schema_stamp_is_a_cache_miss():
    """Deleting local cache files is not enough -- USTFutureStore pulls missing partitions back
    from Supabase -- so invalidation is a stamp that the read path requires."""
    legacy = _report()
    assert not USTFuturesMDP._basis_report_cache_is_current(legacy)

    current = _report()
    current["schema_version"] = _BASIS_REPORT_SCHEMA_VERSION
    assert USTFuturesMDP._basis_report_cache_is_current(current)

    older = _report()
    older["schema_version"] = _BASIS_REPORT_SCHEMA_VERSION - 1
    assert not USTFuturesMDP._basis_report_cache_is_current(older)
