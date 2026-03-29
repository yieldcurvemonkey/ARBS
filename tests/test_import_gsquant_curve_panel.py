import datetime as dt

import pandas as pd
import pytest

pytest.importorskip("rateslib")

import MDP.IRSwaps.IRSwapsMDP as irswaps_mdp_module
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from scripts import import_gsquant_curve_panel


def _sample_panel_csv(tmp_path):
    csv_path = tmp_path / "usd_ois.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,3m,6m,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y",
                "24-Oct-05,4.13395,4.30188,4.50425,4.57268,4.59952,4.62751,4.65768,4.68495,4.71569,4.73783,4.76515,4.7951,4.89557,4.95917,4.97922,4.99299",
                "25-Oct-05,4.1442,4.32324,4.54556,4.63042,4.66708,4.69469,4.72458,4.75106,4.78103,4.80244,4.83163,4.8582,4.95327,5.01405,5.03043,5.0421",
            ]
        ),
        encoding="utf-8",
    )
    return csv_path


def test_load_historical_curve_panel_normalizes_dates_and_tenors(tmp_path):
    csv_path = _sample_panel_csv(tmp_path)

    panel = import_gsquant_curve_panel.load_historical_curve_panel(csv_path, curve_name="USD-OIS")

    assert list(panel.columns[:4]) == ["3M", "6M", "1Y", "2Y"]
    assert panel["as_of"].tolist() == [dt.date(2005, 10, 24), dt.date(2005, 10, 25)]
    assert panel.loc[0, "10Y"] == pytest.approx(4.7951)


def test_import_curve_panel_writes_curve_store_and_gsquant_get_data_reads_it(tmp_path, monkeypatch):
    rateslib = pytest.importorskip("rateslib")

    csv_path = _sample_panel_csv(tmp_path)
    store = import_gsquant_curve_panel.CurveStore(base_dir=tmp_path / "curve_store")

    summary = import_gsquant_curve_panel.import_curve_panel(
        csv_path=csv_path,
        curve_name="USD-OIS",
        store=store,
    )

    assert summary["errors"] == 0
    assert summary["days_written"] == 2
    assert store.has_day("USD-OIS", dt.date(2005, 10, 24))
    assert store.has_analytics_day("USD-OIS", dt.date(2005, 10, 24))
    analytics = store.read_analytics("USD-OIS", start=dt.date(2005, 10, 24), end=dt.date(2005, 10, 24))
    assert float(analytics.loc[0, "par_rate_2Y"]) == pytest.approx(4.57268, abs=0.02)

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "get_gsquant_rl_basic",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy GSQUANT curve cache should not be used when CurveStore covers the requested day")
        ),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    curve = mdp.get_data({"curve_name": "USD-OIS", "timestamp": dt.date(2005, 10, 24)})

    assert curve.meta()["reference_curve_name"] == "USD-OIS"
    assert curve.meta()["requested_curve_name"] == "USD-OIS"
    spot = curve.calendar_advance(curve.reference_date(), "2b")
    irs = rateslib.IRS(
        effective=rateslib.dt(spot.year, spot.month, spot.day),
        termination="2Y",
        spec="usd_irs",
        curves=curve.handle(),
    )
    assert float(irs.rate(curves=curve.handle()).real) == pytest.approx(4.57268, abs=0.02)
