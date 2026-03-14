import datetime as dt

import pandas as pd
import QuantLib as ql

import MDP.IRSwaps.IRSwapsMDP as irswaps_mdp_module
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.backends.quantlib.ql_pricer import build_ql_irswap


class _FakeBarchartCurveHandle:
    def __init__(self, curve_id: str, timestamp: dt.datetime):
        self.id = curve_id
        self.timestamp = timestamp


class _FakeBarchartBuilder:
    _STIRF_CURVE_CONFIGS = {
        "USD-SOFR-Q12": {
            "reference_key": "USD-SOFR-1D",
        }
    }

    def __init__(self):
        self.calls = []

    def build_curve(self, curve_name, timestamp, kwargs, curve_only):
        self.calls.append(
            {
                "curve_name": curve_name,
                "timestamp": timestamp,
                "kwargs": dict(kwargs),
                "curve_only": curve_only,
            }
        )
        print("SUCCESS: `conv_tol` reached after 4 iterations (levenberg_marquardt), `f_val`: 0.005443796837877085, `time`: 0.0349s")
        print("builder diagnostic")
        if isinstance(timestamp, list):
            return {
                ts: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts)
                for ts in timestamp
            }
        return _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=dt.datetime(2026, 3, 3, 17, 0))


def test_bulk_get_data_falls_back_one_by_one_for_eris_ql(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-QL_BASIC")
    d1 = dt.date(2026, 2, 13)
    d2 = dt.date(2026, 2, 16)
    seen = []

    def _stub_get_data(request):
        seen.append((request["curve_name"], request["timestamp"], request.get("ignore_cache")))
        if request["timestamp"] == d2:
            raise AssertionError("synthetic holiday failure")
        return {"curve": request["timestamp"]}

    monkeypatch.setattr(mdp, "get_data", _stub_get_data)

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
            "ignore_cache": True,
        }
    )

    assert seen == [
        ("USD-SOFR-1D", d1, True),
        ("USD-SOFR-1D", d2, True),
    ]
    assert out == {d1: {"curve": d1}}


def test_build_ql_irswap_explicit_date_ois_uses_forward_schedule():
    as_of = dt.date(2026, 3, 3)
    ql_date = ql.Date(as_of.day, as_of.month, as_of.year)
    ql.Settings.instance().evaluationDate = ql_date
    curve_handle = ql.YieldTermStructureHandle(ql.FlatForward(ql_date, 0.04, ql.Actual360()))

    swap = build_ql_irswap(
        curve="USD-SOFR-1D",
        curve_handle=curve_handle,
        effective_date=dt.date(2026, 4, 3),
        maturity_date=dt.date(2033, 4, 4),
        fixed_rate=-0.0,
        notional=1.0,
    )

    schedule = swap.fixedSchedule()
    assert schedule[0] == ql.Date(3, 4, 2026)
    assert schedule[1] == ql.Date(5, 4, 2027)
    assert swap.startDate() == ql.Date(3, 4, 2026)
    assert swap.maturityDate() == ql.Date(4, 4, 2033)
    assert swap.fairRate() > 0.0


def test_barchart_stirf_get_data_suppresses_rateslib_solver_logs(monkeypatch, capsys):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    curve = mdp.get_data({"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 3, 3)})
    captured = capsys.readouterr()

    assert "SUCCESS: `conv_tol` reached" not in captured.out
    assert "SUCCESS: `conv_tol` reached" not in captured.err
    assert "builder diagnostic" in captured.out
    assert builder.calls[0]["curve_name"] == "USD-SOFR-Q12"
    assert curve.meta()["curve_name"] == "USD-SOFR-Q12"
    assert curve.meta()["requested_curve_name"] == "USD-SOFR-1D"


def test_barchart_stirf_bulk_get_data_suppresses_rateslib_solver_logs(monkeypatch, capsys):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    d1 = dt.date(2026, 3, 3)
    d2 = dt.date(2026, 3, 4)

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(irswaps_mdp_module.tqdm, "tqdm", lambda iterable, **kwargs: iterable)

    out = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": [d1, d2]})
    captured = capsys.readouterr()

    assert set(out) == {d1, d2}
    assert len(builder.calls) == 1
    assert isinstance(builder.calls[0]["timestamp"], list)
    assert len(builder.calls[0]["timestamp"]) == 2
    assert builder.calls[0]["kwargs"]["cache_full_intraday_fetch"] is True
    assert "SUCCESS: `conv_tol` reached" not in captured.out
    assert "SUCCESS: `conv_tol` reached" not in captured.err
