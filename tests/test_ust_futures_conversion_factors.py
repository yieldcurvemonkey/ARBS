import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

import MDP.cache_populator as cache_populator
import MDP.USTFutures.USTFuturesMDP as ustf_module
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from MDP.USTFutures.treasury_conversion_factors import (
    build_delivery_basket_frame,
    calculate_conversion_factor,
    round_coupon_to_eighth,
)


@pytest.mark.parametrize(
    ("root", "coupon_pct", "maturity_date", "expected"),
    [
        ("TU", 0.0, dt.date(2011, 12, 31), 0.8885),
        ("TU", 0.125, dt.date(2011, 11, 30), 0.8951),
        ("Z3N", 0.5, dt.date(2012, 10, 31), 0.8586),
        ("FV", 0.0, dt.date(2015, 3, 31), 0.7332),
        ("FV", 0.75, dt.date(2014, 7, 31), 0.7923),
        ("TY", 0.5, dt.date(2019, 6, 30), 0.6061),
        ("US", 0.125, dt.date(2049, 9, 30), 0.1142),
    ],
)
def test_calculate_conversion_factor_matches_cme_lookup_points(root, coupon_pct, maturity_date, expected):
    delivery_first = dt.date(2009, 12, 1)
    assert calculate_conversion_factor(
        root=root,
        coupon_pct=coupon_pct,
        maturity_date=maturity_date,
        delivery_month_first_day=delivery_first,
    ) == expected


def test_round_coupon_to_eighth_rounds_ties_up():
    assert round_coupon_to_eighth(4.0625) == 4.125
    assert round_coupon_to_eighth(4.1874) == 4.125


def test_build_delivery_basket_frame_applies_tu_contract_filters():
    ref_df = pd.DataFrame(
        [
            {
                "cusip": "ELIGIBLE_TU",
                "oi": "5-Year",
                "issue_date": dt.date(2020, 5, 31),
                "maturity_date": dt.date(2025, 5, 31),
                "cpn": 5.0,
            },
            {
                "cusip": "TOO_LONG_TU",
                "oi": "5-Year",
                "issue_date": dt.date(2020, 7, 1),
                "maturity_date": dt.date(2025, 7, 1),
                "cpn": 5.0,
            },
            {
                "cusip": "WRONG_OI_TU",
                "oi": "7-Year",
                "issue_date": dt.date(2018, 5, 31),
                "maturity_date": dt.date(2025, 5, 31),
                "cpn": 5.0,
            },
        ]
    )

    basket = build_delivery_basket_frame(
        as_of=dt.date(2023, 3, 15),
        symbol="TUM23",
        reference_data=ref_df,
    )

    assert basket["cusip"].tolist() == ["ELIGIBLE_TU"]


def test_build_delivery_basket_frame_applies_uxy_exact_original_term_and_bounds():
    ref_df = pd.DataFrame(
        [
            {
                "cusip": "ELIGIBLE_UXY",
                "oi": "10-Year",
                "issue_date": dt.date(2023, 11, 15),
                "maturity_date": dt.date(2033, 11, 15),
                "cpn": 4.5,
            },
            {
                "cusip": "WRONG_OI_UXY",
                "oi": "7-Year",
                "issue_date": dt.date(2023, 11, 15),
                "maturity_date": dt.date(2033, 11, 15),
                "cpn": 4.5,
            },
            {
                "cusip": "TOO_SHORT_UXY",
                "oi": "10-Year",
                "issue_date": dt.date(2023, 4, 15),
                "maturity_date": dt.date(2033, 4, 15),
                "cpn": 4.5,
            },
        ]
    )

    basket = build_delivery_basket_frame(
        as_of=dt.date(2024, 3, 15),
        symbol="TNM24",
        reference_data=ref_df,
    )

    assert basket["cusip"].tolist() == ["ELIGIBLE_UXY"]


def test_build_delivery_basket_frame_applies_twe_remaining_term_band():
    ref_df = pd.DataFrame(
        [
            {
                "cusip": "LOW_OK_TWE",
                "oi": "30-Year",
                "issue_date": dt.date(2013, 8, 15),
                "maturity_date": dt.date(2043, 8, 15),
                "cpn": 4.375,
            },
            {
                "cusip": "HIGH_OK_TWE",
                "oi": "30-Year",
                "issue_date": dt.date(2014, 5, 1),
                "maturity_date": dt.date(2044, 5, 1),
                "cpn": 4.25,
            },
            {
                "cusip": "TOO_SHORT_TWE",
                "oi": "30-Year",
                "issue_date": dt.date(2013, 7, 31),
                "maturity_date": dt.date(2043, 7, 31),
                "cpn": 4.25,
            },
            {
                "cusip": "TOO_LONG_TWE",
                "oi": "30-Year",
                "issue_date": dt.date(2014, 5, 15),
                "maturity_date": dt.date(2044, 5, 15),
                "cpn": 4.25,
            },
        ]
    )

    basket = build_delivery_basket_frame(
        as_of=dt.date(2024, 3, 15),
        symbol="TWEM24",
        reference_data=ref_df,
    )

    assert basket["cusip"].tolist() == ["LOW_OK_TWE", "HIGH_OK_TWE"]


def test_build_delivery_basket_frame_includes_auctioned_but_not_yet_issued_cusips():
    ref_df = pd.DataFrame(
        [
            {
                "cusip": "AUCTIONED_NOT_ISSUED",
                "oi": "3-Year",
                "auction_date": dt.date(2026, 3, 10),
                "issue_date": dt.date(2026, 3, 16),
                "maturity_date": dt.date(2029, 3, 15),
                "cpn": 3.5,
            },
            {
                "cusip": "NOT_YET_AUCTIONED",
                "oi": "3-Year",
                "auction_date": dt.date(2026, 3, 13),
                "issue_date": dt.date(2026, 3, 20),
                "maturity_date": dt.date(2029, 3, 15),
                "cpn": 3.5,
            },
        ]
    )

    basket = build_delivery_basket_frame(
        as_of=dt.date(2026, 3, 12),
        symbol="Z3NM26",
        reference_data=ref_df,
    )

    assert basket["cusip"].tolist() == ["AUCTIONED_NOT_ISSUED"]


def test_get_delivery_basket_uses_internal_basket_definition(monkeypatch):
    basket_df = pd.DataFrame(
        {
            "cusip": ["AAA111111", "BBB222222"],
            "invoice_conversion_factor": [0.9123, 0.9456],
            "futures_coupon": [6.0, 6.0],
        }
    )

    class _DummyFixedRateBondsMDP:
        def __init__(self, source):
            self.source = source

        def get_data(self, request):
            return {cusip: f"pricer:{cusip}" for cusip in request["cusips"]}

    monkeypatch.setattr(ustf_module, "FixedRateBondsMDP", _DummyFixedRateBondsMDP)
    monkeypatch.setattr(ustf_module, "build_delivery_basket_frame", lambda **kwargs: basket_df.copy())
    monkeypatch.setattr(ustf_module, "resolve_delivery_contract", lambda symbol, as_of: ("TY", dt.date(2023, 6, 21), 202306))
    monkeypatch.setattr(ustf_module, "delivery_business_window", lambda contract_imm_date: (dt.date(2023, 6, 1), dt.date(2023, 6, 30)))
    monkeypatch.setattr(ustf_module, "get_contract_spec", lambda root: SimpleNamespace(calc_mode="ust_long"))

    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    basket = mdp.get_delivery_basket(as_of=dt.date(2023, 3, 15), symbol="TY", ignore_cache=True)

    assert basket["delivery"] == (dt.date(2023, 6, 1), dt.date(2023, 6, 30))
    assert basket["basket_pricers"] == ["pricer:AAA111111", "pricer:BBB222222"]
    assert basket["conversion_factors"] == [0.9123, 0.9456]
    assert basket["contract_coupon"] == 6.0
    assert basket["calc_mode"] == "ust_long"


def test_cache_populator_delivery_basket_cusips_uses_internal_helper(monkeypatch):
    def _fake_load_attr(module_name, attr_name):
        assert module_name == "MDP.USTFutures.treasury_conversion_factors"
        assert attr_name == "delivery_basket_cusips"
        return lambda *, as_of, symbol: [f"{symbol}-{as_of.isoformat()}"]

    monkeypatch.setattr(cache_populator, "_load_attr", _fake_load_attr)
    result = cache_populator._delivery_basket_cusips("TY", dt.date(2023, 3, 15))
    assert result == ["TY-2023-03-15"]
