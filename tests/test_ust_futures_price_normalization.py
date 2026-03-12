import datetime

import pandas as pd
import pytest

from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from definitions.USTFutures import normalize_barchart_ust_future_price


def test_normalize_barchart_ust_future_price_decodes_ultra_bond_compact_quotes():
    assert normalize_barchart_ust_future_price("UBH26", 11.13) == pytest.approx(111.40625)
    assert normalize_barchart_ust_future_price("UBH26", 11.1775) == pytest.approx(111.5546875)
    assert normalize_barchart_ust_future_price("ZBH26", 116.59375) == pytest.approx(116.59375)


def test_ust_future_option_mdp_normalizes_ultra_bond_eod_underlying_quotes(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    idx = pd.DatetimeIndex([pd.Timestamp("2026-03-06")])

    class _DummyFetcher:
        def barchart_timeseries_api(self, **kwargs):
            _ = kwargs
            return {
                "UBH26": pd.DataFrame(
                    {"Open": [11.1775], "High": [11.1775], "Low": [11.13], "Close": [11.13]},
                    index=idx,
                ),
                "ZBH26": pd.DataFrame(
                    {"Open": [116.625], "High": [116.96875], "Low": [115.875], "Close": [116.59375]},
                    index=idx,
                ),
            }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda required_concurrency=None: _DummyFetcher())

    out = mdp._fetch_barchart_eod_series(
        symbols=["UBH26", "ZBH26"],
        start=datetime.date(2026, 3, 6),
        end=datetime.date(2026, 3, 6),
        show_tqdm=False,
    )

    assert out["UBH26"].iloc[0]["Open"] == pytest.approx(111.5546875)
    assert out["UBH26"].iloc[0]["Close"] == pytest.approx(111.40625)
    assert out["ZBH26"].iloc[0]["Close"] == pytest.approx(116.59375)


def test_ust_futures_mdp_normalizes_ultra_bond_timeseries_quotes(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    idx = pd.DatetimeIndex([pd.Timestamp("2026-03-06 14:00:00", tz="America/Chicago")])

    class _DummyFetcher:
        def barchart_timeseries_api(self, **kwargs):
            _ = kwargs
            return pd.DataFrame({"UBH26": [11.13], "ZBH26": [116.59375]}, index=idx)

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

    assert out["WNH26"]._price == pytest.approx(111.40625)
    assert out["USH26"]._price == pytest.approx(116.59375)
