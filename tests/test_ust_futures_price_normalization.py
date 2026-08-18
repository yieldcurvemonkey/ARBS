"""BarChart UST futures price handling.

This file used to assert the opposite of what it asserts now. It pinned a "compact 32nds" decoder
that mapped a BarChart "UB" quote of 11.13 to 111.40625, on the theory that BarChart served the
Ultra Bond as a handle-and-32nds pair. It did not. BarChart's "UB" is the CME Euro/Krone FX future
and 11.13 was an exchange rate; the Ultra Bond is BarChart root "UD". The decoder's own premise was
measurably false -- the fractional part routinely exceeded 32 (a raw 9.465 implies "46.5
thirty-seconds"), which is not a quote in any convention.

Kept as a reminder that a test can lock in a bug as effectively as it can prevent one.
"""

import datetime
import math

import pandas as pd
import pytest

from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP, _from_barchart_symbol, _to_barchart_symbol
from definitions.USTFutures import (
    UST_FUTURE_BARCHART_ROOTS,
    UST_FUTURE_BARCHART_TO_INTERNAL,
    is_plausible_ust_future_price,
    normalize_barchart_ust_future_price,
    to_barchart_root,
)


def test_ultra_bond_maps_to_barchart_ud_not_ub():
    """BarChart's Ultra 30-Year Treasury-Bond root is UD. Its UB is the Euro/Krone FX future."""
    assert to_barchart_root("WN") == "UD"
    assert to_barchart_root("ULTRA") == "UD"
    assert UST_FUTURE_BARCHART_ROOTS["WN"] == "UD"
    assert UST_FUTURE_BARCHART_TO_INTERNAL["UD"] == "WN"
    # "UB" must never be emitted as a vendor root again.
    assert "UB" not in UST_FUTURE_BARCHART_ROOTS.values()
    assert "UB" not in UST_FUTURE_BARCHART_TO_INTERNAL
    assert _to_barchart_symbol("WNU26") == "UDU26"
    assert _from_barchart_symbol("UDU26") == "WNU26"


def test_ub_still_accepted_as_the_globex_spelling_on_input():
    """UB is the CME Globex code for the Ultra Bond, so callers do type it."""
    assert _to_barchart_symbol("UBU26") == "UDU26"


def test_prices_pass_through_unchanged_there_is_nothing_to_decode():
    assert normalize_barchart_ust_future_price("ZBH26", 116.59375) == pytest.approx(116.59375)
    assert normalize_barchart_ust_future_price("UDU26", 110.625) == pytest.approx(110.625)
    # The Ultra Bond really did trade above 220 at the 2020 yield lows; the band must not clip it.
    assert normalize_barchart_ust_future_price("UDZ20", 222.71875) == pytest.approx(222.71875)


def test_wrong_instrument_values_are_rejected_rather_than_made_plausible():
    """The old decoder turned 11.13 into 111.40625. Absence beats a plausible wrong number."""
    assert math.isnan(normalize_barchart_ust_future_price("UDH26", 11.13))
    assert math.isnan(normalize_barchart_ust_future_price("UDU26", 10.9575))
    assert not is_plausible_ust_future_price(11.13)
    assert is_plausible_ust_future_price(159.28125)


def test_ust_future_option_mdp_leaves_option_premiums_alone(monkeypatch):
    """Option premiums are fractions of a point; the old decoder mapped a 1.25 premium to 101.78."""
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    idx = pd.DatetimeIndex([pd.Timestamp("2026-03-06")])

    class _DummyFetcher:
        def barchart_timeseries_api(self, **kwargs):
            _ = kwargs
            return {
                "UDH26": pd.DataFrame(
                    {"Open": [1.25], "High": [1.375], "Low": [1.125], "Close": [1.1875]},
                    index=idx,
                ),
                "ZBH26": pd.DataFrame(
                    {"Open": [116.625], "High": [116.96875], "Low": [115.875], "Close": [116.59375]},
                    index=idx,
                ),
            }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda required_concurrency=None: _DummyFetcher())

    out = mdp._fetch_barchart_eod_series(
        symbols=["UDH26", "ZBH26"],
        start=datetime.date(2026, 3, 6),
        end=datetime.date(2026, 3, 6),
        show_tqdm=False,
    )

    assert out["UDH26"].iloc[0]["Open"] == pytest.approx(1.25)
    assert out["UDH26"].iloc[0]["Close"] == pytest.approx(1.1875)
    assert out["ZBH26"].iloc[0]["Close"] == pytest.approx(116.59375)


def test_ust_futures_mdp_fetches_the_ultra_bond_under_ud(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    idx = pd.DatetimeIndex([pd.Timestamp("2026-03-06 14:00:00", tz="America/Chicago")])
    seen = {}

    class _DummyFetcher:
        def barchart_timeseries_api(self, **kwargs):
            seen["symbols"] = list(kwargs.get("barchart_symbols") or [])
            return pd.DataFrame({"UDH26": [110.625], "ZBH26": [116.59375]}, index=idx)

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyFetcher())

    out = mdp.get_pricer(
        {
            "symbols": ["WNH26", "USH26"],
            "timestamp": datetime.date(2026, 3, 6),
            "show_tqdm": False,
            "force_refresh": True,
            "include_basket": False,
        }
    )

    assert seen["symbols"] == ["UDH26", "ZBH26"], "the Ultra Bond must be requested as UD"
    assert out["WNH26"]._price == pytest.approx(110.625)
    assert out["USH26"]._price == pytest.approx(116.59375)
