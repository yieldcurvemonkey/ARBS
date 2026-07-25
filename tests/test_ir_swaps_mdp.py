import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
import QuantLib as ql
import pytz

import MDP.IRSwaps.IRSwapsMDP as irswaps_mdp_module
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
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

    @staticmethod
    def _trading_date_for_timestamp(timestamp: dt.datetime) -> dt.date:
        chi = pytz.timezone("America/Chicago")
        ts_chi = timestamp.astimezone(chi)
        if ts_chi.hour >= 17:
            return (ts_chi + dt.timedelta(days=1)).date()
        return ts_chi.date()

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


class _FakeCurveStore:
    def __init__(self, day_df: pd.DataFrame, curves_by_ts):
        self.day_df = day_df
        self.curves_by_ts = curves_by_ts
        self.read_calls = []
        self.raw_node_calls = []
        self.reconstruct_calls = []

    def read_raw_day(self, curve_name, trading_date):
        self.read_calls.append((curve_name, trading_date))
        return self.day_df.copy()

    def read_raw_nodes(self, curve_name, *, start=None, end=None, session_minute_min=None, session_minute_max=None, timestamps_utc=None):
        self.raw_node_calls.append(
            {
                "curve_name": curve_name,
                "start": start,
                "end": end,
                "session_minute_min": session_minute_min,
                "session_minute_max": session_minute_max,
                "timestamps_utc": list(timestamps_utc or []),
            }
        )
        df = self.day_df.copy()
        if timestamps_utc and "timestamp_utc" in df.columns:
            requested = {
                pd.Timestamp(ts.astimezone(pytz.UTC).replace(microsecond=0))
                for ts in timestamps_utc
            }
            ts_keys = pd.to_datetime(df["timestamp_utc"], utc=True)
            df = df.loc[ts_keys.isin(requested)].copy()
        return df

    def reconstruct_curves_batch(self, df, *, cfg=None, max_workers=4, progress_callback=None):
        self.reconstruct_calls.append(
            {
                "cfg": cfg,
                "max_workers": max_workers,
                "timestamps": list(df["timestamp_utc"]),
            }
        )
        if progress_callback is not None:
            for _ in range(len(df)):
                progress_callback(1)
        return dict(self.curves_by_ts)


class _FakePromotableErisCurve:
    def __init__(self, timestamp):
        self._meta = {"timestamp": timestamp}
        self._handle = SimpleNamespace(
            id="USD-SOFR-1D",
            interpolation="log_linear",
            nodes=SimpleNamespace(
                _nodes={
                    dt.date(2026, 1, 2): 1.0,
                    dt.date(2027, 1, 2): 0.95,
                }
            ),
        )

    def meta(self):
        return self._meta

    def handle(self):
        return self._handle

    def build_irswap(self, tenor=None, **kwargs):
        _ = kwargs
        return tenor

    def fair_rate(self, irswap):
        _ = irswap
        return 0.04


def _grid_token_to_months(token: str) -> int:
    normalized = str(token).strip().upper()
    if normalized == "0D":
        return 0
    if normalized.endswith("M"):
        return int(normalized[:-1])
    if normalized.endswith("Y"):
        return int(normalized[:-1]) * 12
    raise ValueError(f"Unsupported grid token: {token}")


class _FakeGridCurve:
    def build_irswap(self, fwd=None, tenor=None, **kwargs):
        _ = kwargs
        return {"fwd": fwd, "tenor": tenor}

    def fair_rate(self, irswap):
        fwd_months = _grid_token_to_months(irswap["fwd"])
        tenor_months = _grid_token_to_months(irswap["tenor"])
        return tenor_months / 1_000.0 + fwd_months / 10_000.0


def test_bulk_get_data_falls_back_one_by_one_for_eris_ql(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-QL_BASIC")
    d1 = dt.date(2026, 2, 13)  # Fri
    # Both must be real business days: bulk_get_data now applies the same
    # calendar validation as the single-point path, so a genuine holiday
    # (2026-02-16 is Presidents' Day) is dropped BEFORE the fallback loop and
    # would never reach get_data. This test is about the per-point fallback
    # tolerating a pricing failure, not about calendar handling.
    d2 = dt.date(2026, 2, 17)  # Tue
    seen = []

    def _stub_get_data(request):
        seen.append((request["curve_name"], request["timestamp"], request.get("ignore_cache")))
        if request["timestamp"] == d2:
            raise AssertionError("synthetic pricing failure")
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


def test_eod_curve_request_rejects_non_business_day():
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")

    with pytest.raises(ValueError, match="not a business day"):
        mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 3, 8)})


def test_barchart_stirf_allows_sunday_evening_globex_timestamp(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    builder._STIRF_CURVE_CONFIGS = {
        "USD-SOFR-1D-Q12STIRT": {
            "reference_key": "USD-SOFR-1D",
        }
    }
    ny_tz = pytz.timezone("America/New_York")
    ts_local = ny_tz.localize(dt.datetime(2026, 3, 8, 23, 0))
    sentinel = object()
    seen = []

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)

    def _curve_store_hit(**kwargs):
        seen.append(kwargs)
        return sentinel

    monkeypatch.setattr(mdp, "_load_barchart_stirf_curve_store_point", _curve_store_hit)

    out = mdp.get_pricer({"curve_name": "USD-SOFR-1D-Q12STIRT", "timestamp": ts_local})

    assert out is sentinel
    assert seen
    assert seen[0]["request_timestamp"] == ts_local


def test_barchart_stirf_rejects_sunday_pre_open_timestamp(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    builder._STIRF_CURVE_CONFIGS = {
        "USD-SOFR-1D-Q12STIRT": {
            "reference_key": "USD-SOFR-1D",
        }
    }
    ny_tz = pytz.timezone("America/New_York")
    ts_local = ny_tz.localize(dt.datetime(2026, 3, 8, 16, 0))

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)

    with pytest.raises(ValueError, match="non-business trading date"):
        mdp.get_pricer({"curve_name": "USD-SOFR-1D-Q12STIRT", "timestamp": ts_local})


def test_get_grid_supports_custom_axes_without_mutating_request(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    request = {
        "curve_name": "USD-SOFR-1D",
        "timestamp": dt.date(2026, 3, 3),
        "ignore_cache": True,
    }

    def _stub_get_pricer(req):
        assert req is not request
        req.pop("curve_name")
        req.pop("timestamp")
        return _FakeGridCurve()

    monkeypatch.setattr(mdp, "get_pricer", _stub_get_pricer)

    grid = mdp.get_grid(
        request,
        fwds=["Spot", "1m", "1Y"],
        swap_tenors=["2Y", "10y"],
    )

    expected = pd.DataFrame(
        [[2.40, 2.41, 2.52], [12.00, 12.01, 12.12]],
        index=["2Y", "10Y"],
        columns=["Spot", "1M", "1Y"],
        dtype=float,
    )
    expected.index.name = "swap_tenor"
    expected.columns.name = "forward_tenor"

    pd.testing.assert_frame_equal(grid, expected)
    assert request == {
        "curve_name": "USD-SOFR-1D",
        "timestamp": dt.date(2026, 3, 3),
        "ignore_cache": True,
    }


def test_get_grid_can_flip_axes(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    monkeypatch.setattr(mdp, "get_pricer", lambda req: _FakeGridCurve())

    grid = mdp.get_grid(
        {"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 3, 3)},
        fwds=["Spot", "6M"],
        swap_tenors=["2Y", "5Y"],
        flip_axes=True,
    )

    expected = pd.DataFrame(
        [[2.40, 6.00], [2.46, 6.06]],
        index=["Spot", "6M"],
        columns=["2Y", "5Y"],
        dtype=float,
    )
    expected.index.name = "forward_tenor"
    expected.columns.name = "swap_tenor"

    pd.testing.assert_frame_equal(grid, expected)


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


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("SUCCESS: `conv_tol` reached after 4 iterations (levenberg_marquardt)", True),
        ("SUCCESS: `func_tol` reached after 4 iterations (levenberg_marquardt)", True),
        ("builder diagnostic", False),
    ],
)
def test_should_suppress_ratelibs_solver_output(line, expected):
    assert IRSwapsMDP._should_suppress_ratelibs_solver_output(line) is expected


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


def test_barchart_stirf_bulk_get_data_forwards_parallelism_and_tqdm(monkeypatch):
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

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
            "n_jobs": 3,
            "show_tqdm": True,
        }
    )

    assert set(out) == {d1, d2}
    assert len(builder.calls) == 1
    assert builder.calls[0]["kwargs"]["show_tqdm"] is True
    assert builder.calls[0]["kwargs"]["calibration_max_workers"] == 3


def test_barchart_stirf_bulk_get_data_forwards_process_executor(monkeypatch):
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

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
            "n_jobs": 4,
            "show_tqdm": True,
            "calibration_executor": "process",
        }
    )

    assert set(out) == {d1, d2}
    assert len(builder.calls) == 1
    assert builder.calls[0]["kwargs"]["show_tqdm"] is True
    assert builder.calls[0]["kwargs"]["calibration_max_workers"] == 4
    assert builder.calls[0]["kwargs"]["calibration_executor"] == "process"


def test_barchart_stirf_bulk_get_data_process_failure_raises(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    d1 = dt.date(2026, 3, 3)
    d2 = dt.date(2026, 3, 4)

    def _boom(*args, **kwargs):
        raise ValueError("synthetic process pool failure")

    builder.build_curve = _boom

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    try:
        mdp.bulk_get_data(
            {
                "curve_name": "USD-SOFR-1D",
                "timestamps": [d1, d2],
                "calibration_executor": "process",
            }
        )
    except RuntimeError as exc:
        assert "Process-pool calibration failed" in str(exc)
    else:
        raise AssertionError("Expected process-mode bulk_get_data to raise on builder failure")


def test_barchart_stirf_bulk_get_data_retries_by_trading_day_before_per_timestamp_fallback(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    chi = pytz.timezone("America/Chicago")
    ts1 = chi.localize(dt.datetime(2026, 3, 3, 10, 0))
    ts2 = chi.localize(dt.datetime(2026, 3, 3, 11, 0))
    ts3 = chi.localize(dt.datetime(2026, 3, 4, 10, 0))
    fallback_calls = []

    class _RetryByDayBuilder(_FakeBarchartBuilder):
        @staticmethod
        def _trading_date_for_timestamp(timestamp):
            ts_chi = timestamp.astimezone(chi)
            return (ts_chi + dt.timedelta(days=1)).date() if ts_chi.hour >= 17 else ts_chi.date()

        def build_curve(self, curve_name, timestamp, kwargs, curve_only):
            self.calls.append(
                {
                    "curve_name": curve_name,
                    "timestamp": timestamp,
                    "kwargs": dict(kwargs),
                    "curve_only": curve_only,
                }
            )
            ts_batch = list(timestamp) if isinstance(timestamp, list) else [timestamp]
            if len(ts_batch) == 3:
                raise ValueError("synthetic full batch failure")
            return {
                ts: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts)
                for ts in ts_batch
            }

    builder = _RetryByDayBuilder()

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(irswaps_mdp_module.tqdm, "tqdm", lambda iterable, **kwargs: iterable)

    def _unexpected_get_curve(*args, **kwargs):
        fallback_calls.append(kwargs.get("timestamp"))
        raise AssertionError("per-timestamp fallback should not run when day retries recover all timestamps")

    monkeypatch.setattr(mdp, "_get_curve", _unexpected_get_curve)

    out = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": [ts1, ts2, ts3], "n_jobs": 4})

    assert set(out) == {ts1, ts2, ts3}
    assert fallback_calls == []
    assert [len(call["timestamp"]) if isinstance(call["timestamp"], list) else 1 for call in builder.calls] == [3, 2, 1]


def test_barchart_stirf_bulk_get_data_uses_per_timestamp_fallback_only_for_residual_misses(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    chi = pytz.timezone("America/Chicago")
    ts1 = chi.localize(dt.datetime(2026, 3, 3, 10, 0))
    ts2 = chi.localize(dt.datetime(2026, 3, 3, 11, 0))
    ts3 = chi.localize(dt.datetime(2026, 3, 4, 10, 0))
    fallback_calls = []

    class _ResidualFallbackBuilder(_FakeBarchartBuilder):
        @staticmethod
        def _trading_date_for_timestamp(timestamp):
            ts_chi = timestamp.astimezone(chi)
            return (ts_chi + dt.timedelta(days=1)).date() if ts_chi.hour >= 17 else ts_chi.date()

        def build_curve(self, curve_name, timestamp, kwargs, curve_only):
            self.calls.append(
                {
                    "curve_name": curve_name,
                    "timestamp": timestamp,
                    "kwargs": dict(kwargs),
                    "curve_only": curve_only,
                }
            )
            ts_batch = list(timestamp) if isinstance(timestamp, list) else [timestamp]
            if len(ts_batch) == 3:
                raise ValueError("synthetic full batch failure")
            if len(ts_batch) == 2 and set(ts_batch) == {ts1, ts2}:
                return {ts1: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts1)}
            if len(ts_batch) == 1 and ts_batch[0] == ts2:
                return {}
            return {
                ts: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts)
                for ts in ts_batch
            }

    builder = _ResidualFallbackBuilder()

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(irswaps_mdp_module.tqdm, "tqdm", lambda iterable, **kwargs: iterable)

    def _record_get_curve(curve_name, timestamp, kwargs):
        fallback_calls.append(timestamp)
        return {"curve_name": curve_name, "timestamp": timestamp, "kwargs": dict(kwargs)}

    monkeypatch.setattr(mdp, "_get_curve", _record_get_curve)

    out = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": [ts1, ts2, ts3], "n_jobs": 4})

    assert set(out) == {ts1, ts2, ts3}
    assert fallback_calls == [ts2]
    assert [len(call["timestamp"]) if isinstance(call["timestamp"], list) else 1 for call in builder.calls] == [3, 2, 1, 1]


def test_bulk_get_data_rejects_empty_timestamp_collection():
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

    with pytest.raises(ValueError, match="empty collection"):
        mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": []})


def test_barchart_stirf_bulk_get_data_uses_curve_store_fast_path(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    chi_tz = pytz.timezone("America/Chicago")
    ts_local = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    ts_utc = ts_local.astimezone(pytz.UTC).replace(microsecond=0)
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(ts_utc)]}),
        curves_by_ts={ts_utc: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts_local)},
    )

    def _unexpected_builder_call(*args, **kwargs):
        raise AssertionError("builder.build_curve should not be called when CurveStore covers all timestamps")

    builder.build_curve = _unexpected_builder_call

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    out = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": [ts_local]})

    assert set(out) == {ts_local}
    assert len(store.raw_node_calls) == 1
    assert store.raw_node_calls[0]["curve_name"] == "USD-SOFR-Q12"
    assert store.raw_node_calls[0]["timestamps_utc"] == [ts_local]
    assert store.read_calls == []
    assert len(store.reconstruct_calls) == 1
    assert out[ts_local].meta()["curve_name"] == "USD-SOFR-Q12"
    assert builder.calls == []


def test_barchart_stirf_get_pricer_uses_curve_store_fast_path(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    chi_tz = pytz.timezone("America/Chicago")
    ts_local = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    ts_utc = ts_local.astimezone(pytz.UTC).replace(microsecond=0)
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(ts_utc)]}),
        curves_by_ts={ts_utc: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts_local)},
    )

    def _unexpected_builder_call(*args, **kwargs):
        raise AssertionError("builder.build_curve should not be called when CurveStore covers the single intraday timestamp")

    builder.build_curve = _unexpected_builder_call

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp,
        "bulk_get_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("single-date get_pricer fast path should not route through bulk_get_data")
        ),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    out = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": ts_local})

    assert out.meta()["curve_name"] == "USD-SOFR-Q12"
    assert len(store.raw_node_calls) == 1
    assert store.raw_node_calls[0]["curve_name"] == "USD-SOFR-Q12"
    assert store.raw_node_calls[0]["timestamps_utc"] == [ts_local]
    assert len(store.reconstruct_calls) == 1
    assert builder.calls == []


def test_barchart_stirf_get_pricer_ignore_cache_miss_skips_solver_on_point_miss(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    chi_tz = pytz.timezone("America/Chicago")
    ts_local = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    store = _FakeCurveStore(day_df=pd.DataFrame({"timestamp_utc": []}), curves_by_ts={})

    def _unexpected_builder_call(*args, **kwargs):
        raise AssertionError("builder.build_curve should not be called when ignore_cache_miss is enabled")

    builder.build_curve = _unexpected_builder_call

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    with pytest.raises(RuntimeError, match="could not build a curve"):
        mdp.get_pricer(
            {
                "curve_name": "USD-SOFR-1D",
                "timestamp": ts_local,
                "ignore_cache_miss": True,
            }
        )

    assert len(store.raw_node_calls) == 1
    assert store.raw_node_calls[0]["curve_name"] == "USD-SOFR-Q12"
    assert store.raw_node_calls[0]["timestamps_utc"] == [ts_local]
    assert builder.calls == []


def test_barchart_stirf_get_pricer_ignore_cache_miss_uses_latest_prior_cached_timestamp(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    chi_tz = pytz.timezone("America/Chicago")
    prior_local = chi_tz.localize(dt.datetime(2026, 3, 10, 9, 58))
    requested_local = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    prior_utc = prior_local.astimezone(pytz.UTC).replace(microsecond=0)
    requested_utc = requested_local.astimezone(pytz.UTC).replace(microsecond=0)
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(prior_utc)]}),
        curves_by_ts={prior_utc: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=prior_local)},
    )

    def _unexpected_builder_call(*args, **kwargs):
        raise AssertionError("builder.build_curve should not be called when a prior cache hit exists")

    builder.build_curve = _unexpected_builder_call

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    out = mdp.get_pricer(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": requested_local,
            "ignore_cache_miss": True,
        }
    )

    assert out.meta()["curve_name"] == "USD-SOFR-Q12"
    assert len(store.raw_node_calls) == 1
    assert store.raw_node_calls[0]["timestamps_utc"] == [requested_local]
    assert store.read_calls == [("USD-SOFR-Q12", dt.date(2026, 3, 10))]
    assert len(store.reconstruct_calls) == 1
    assert list(store.reconstruct_calls[0]["timestamps"]) == [pd.Timestamp(prior_utc)]
    assert builder.calls == []


def test_barchart_stirf_bulk_get_data_curve_store_fast_path_reconstructs_only_requested_rows(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    chi_tz = pytz.timezone("America/Chicago")
    ts_local = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    extra_local = chi_tz.localize(dt.datetime(2026, 3, 10, 11, 0))
    ts_utc = ts_local.astimezone(pytz.UTC).replace(microsecond=0)
    extra_utc = extra_local.astimezone(pytz.UTC).replace(microsecond=0)
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(ts_utc), pd.Timestamp(extra_utc)]}),
        curves_by_ts={
            ts_utc: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts_local),
            extra_utc: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=extra_local),
        },
    )

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    out = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": [ts_local]})

    assert set(out) == {ts_local}
    assert len(store.raw_node_calls) == 1
    assert store.raw_node_calls[0]["timestamps_utc"] == [ts_local]
    assert store.read_calls == []
    assert len(store.reconstruct_calls) == 1
    assert list(store.reconstruct_calls[0]["timestamps"]) == [pd.Timestamp(ts_utc)]


def test_barchart_stirf_bulk_get_data_ignore_cache_miss_returns_partial_curve_store_hits(monkeypatch):
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    builder = _FakeBarchartBuilder()
    chi_tz = pytz.timezone("America/Chicago")
    ts1_local = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    ts2_local = chi_tz.localize(dt.datetime(2026, 3, 10, 11, 0))
    ts1_utc = ts1_local.astimezone(pytz.UTC).replace(microsecond=0)
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(ts1_utc)]}),
        curves_by_ts={ts1_utc: _FakeBarchartCurveHandle(curve_id="USD-SOFR-1D", timestamp=ts1_local)},
    )

    def _unexpected_builder_call(*args, **kwargs):
        raise AssertionError("builder.build_curve should not be called when ignore_cache_miss is enabled")

    def _unexpected_get_curve(*args, **kwargs):
        raise AssertionError("per-timestamp fallback should not be called when ignore_cache_miss is enabled")

    builder.build_curve = _unexpected_builder_call

    monkeypatch.setattr(mdp, "_get_barchart_stirf_curve_builder", lambda: builder)
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(mdp, "_get_curve", _unexpected_get_curve)
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [ts1_local, ts2_local],
            "ignore_cache_miss": True,
        }
    )

    assert set(out) == {ts1_local}
    assert len(store.raw_node_calls) == 1
    assert store.raw_node_calls[0]["timestamps_utc"] == [ts1_local, ts2_local]
    assert len(store.reconstruct_calls) == 1
    assert list(store.reconstruct_calls[0]["timestamps"]) == [pd.Timestamp(ts1_utc)]


def test_get_curve_store_uses_curve_store_default_singleton(monkeypatch):
    from Caching.curve_store import CurveStore

    sentinel = object()
    calls = []
    state = IRSwapsMDP._CURVE_STORE_STATE
    original_store = state["store"]
    state["store"] = None
    monkeypatch.setattr(
        CurveStore,
        "default",
        classmethod(lambda cls: calls.append("default") or sentinel),
    )

    try:
        first = IRSwapsMDP._get_curve_store()
        second = IRSwapsMDP._get_curve_store()
    finally:
        state["store"] = original_store

    assert first is sentinel
    assert second is sentinel
    assert calls == ["default"]


def test_eris_bulk_get_data_reuses_fixings_once_per_batch(monkeypatch):
    rateslib = pytest.importorskip("rateslib")

    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    d1 = dt.date(2026, 1, 2)
    d2 = dt.date(2026, 1, 5)

    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_eris_eod_live_rl_basic",
        lambda **kwargs: {d1: "curve-json-1", d2: "curve-json-2"},
    )
    monkeypatch.setattr(rateslib, "from_json", lambda _: SimpleNamespace(calendar=None))

    fixings_calls = []

    def _stub_fetch_fixings(**kwargs):
        fixings_calls.append(kwargs["as_of_date"])
        idx = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-03"])
        return pd.Series([4.1, 4.2, 4.3], index=idx)

    wrap_calls = []

    def _stub_wrap(**kwargs):
        wrap_calls.append(kwargs)
        return {
            "timestamp": kwargs["request_timestamp"],
            "cache_dates": sorted(kwargs["fixings_cache"].keys()),
        }

    monkeypatch.setattr(irswaps_mdp_module, "_fetch_fixings", _stub_fetch_fixings)
    monkeypatch.setattr(mdp, "_build_eris_eod_rl_curve", _stub_wrap)

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
        }
    )

    assert set(out) == {d1, d2}
    assert fixings_calls == [d2]
    assert len(wrap_calls) == 2
    assert out[d1]["cache_dates"] == [d1, d2]
    assert out[d2]["cache_dates"] == [d1, d2]


def test_eris_bulk_get_data_uses_curve_store_fast_path(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    d1 = dt.date(2026, 1, 2)
    d2 = dt.date(2026, 1, 5)
    ts1 = pytz.UTC.localize(dt.datetime(2026, 1, 2, 20, 0))
    ts2 = pytz.UTC.localize(dt.datetime(2026, 1, 5, 20, 0))
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)]}),
        curves_by_ts={
            pd.Timestamp(ts1): object(),
            pd.Timestamp(ts2): object(),
        },
    )

    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_eris_eod_live_rl_basic",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy ERIS curve cache should not be used when CurveStore covers all dates")
        ),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    wrap_calls = []

    def _stub_wrap(**kwargs):
        wrap_calls.append(kwargs["request_timestamp"])
        return {"timestamp": kwargs["request_timestamp"]}

    monkeypatch.setattr(mdp, "_build_eris_eod_rl_curve", _stub_wrap)

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
        }
    )

    assert set(out) == {d1, d2}
    assert len(store.raw_node_calls) == 1
    assert store.read_calls == []
    assert len(store.reconstruct_calls) == 1
    assert wrap_calls == [d1, d2]


def test_eris_bulk_get_data_uses_curve_store_fast_path_for_today(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    today = dt.date.today()
    ts_today = mdp._to_curve_store_timestamp(today).astimezone(pytz.UTC)
    store = _FakeCurveStore(
        day_df=pd.DataFrame({"timestamp_utc": [pd.Timestamp(ts_today)]}),
        curves_by_ts={pd.Timestamp(ts_today): object()},
    )

    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "get_eris_eod_live_rl_basic",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy ERIS live path should not be used when CurveStore already has today's day")
        ),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(
        mdp,
        "_build_eris_eod_rl_curve",
        lambda **kwargs: {"timestamp": kwargs["request_timestamp"]},
    )

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [today],
        }
    )

    assert out == {today: {"timestamp": today}}
    assert len(store.raw_node_calls) == 1
    assert store.read_calls == []


def test_promote_eris_curve_store_day_writes_missing_raw_and_analytics(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    nyc = pytz.timezone("America/New_York")
    curve = _FakePromotableErisCurve(nyc.localize(dt.datetime(2026, 1, 2, 15, 0)))

    raw_calls = []
    analytics_calls = []

    class _Store:
        def has_day(self, curve_name, trading_date):
            _ = curve_name, trading_date
            return False

        def has_analytics_day(self, curve_name, trading_date):
            _ = curve_name, trading_date
            return False

        def write_day(self, curve_name, trading_date, snapshots):
            raw_calls.append((curve_name, trading_date, snapshots))

        def write_analytics_day(self, curve_name, trading_date, df):
            analytics_calls.append((curve_name, trading_date, df))

    monkeypatch.setattr(mdp, "_get_curve_store", lambda: _Store())

    mdp._promote_eris_curve_store_day(
        requested_curve_name="USD-SOFR-1D",
        curve=curve,
        request_timestamp=dt.date(2026, 1, 2),
    )

    # -RL_BASIC writes to its OWN asset key, not the shared USD-SOFR-1D one that
    # holds the -NOJUMPS daily frame.
    expected_asset = mdp._eris_curve_store_asset("USD-SOFR-1D")
    assert expected_asset != "USD-SOFR-1D"
    assert len(raw_calls) == 1
    assert raw_calls[0][0] == expected_asset
    assert raw_calls[0][1] == dt.date(2026, 1, 2)
    assert raw_calls[0][2][0].source_variant == "ERIS_RL_BASIC"
    assert len(analytics_calls) == 1
    assert analytics_calls[0][0] == expected_asset
    assert analytics_calls[0][1] == dt.date(2026, 1, 2)
    assert "par_rate_10Y" in analytics_calls[0][2].columns


def test_gsquant_bulk_get_data_uses_curve_store_fast_path(monkeypatch):
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    d1 = dt.date(2026, 1, 2)
    d2 = dt.date(2026, 1, 5)
    ts1 = mdp._to_curve_store_timestamp(d1).astimezone(pytz.UTC)
    ts2 = mdp._to_curve_store_timestamp(d2).astimezone(pytz.UTC)
    store = _FakeCurveStore(
        day_df=pd.DataFrame(
            {
                "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
                "trading_date": [d1, d2],
            }
        ),
        curves_by_ts={
            pd.Timestamp(ts1): object(),
            pd.Timestamp(ts2): object(),
        },
    )

    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_gsquant_rl_basic",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy GSQUANT curve cache should not be used when CurveStore covers all dates")
        ),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )

    wrap_calls = []

    def _stub_wrap(**kwargs):
        wrap_calls.append(kwargs["request_timestamp"])
        return {"timestamp": kwargs["request_timestamp"]}

    monkeypatch.setattr(mdp, "_build_gsquant_rl_curve", _stub_wrap)

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-OIS",
            "timestamps": [d1, d2],
        }
    )

    assert set(out) == {d1, d2}
    assert len(store.raw_node_calls) == 1
    assert store.read_calls == []
    assert len(store.reconstruct_calls) == 1
    assert wrap_calls == [d1, d2]


def test_gsquant_bulk_get_data_uses_curve_store_fast_path_even_when_ignore_cache_true(monkeypatch):
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    d1 = dt.date(2026, 1, 2)
    ts1 = mdp._to_curve_store_timestamp(d1).astimezone(pytz.UTC)
    store = _FakeCurveStore(
        day_df=pd.DataFrame(
            {
                "timestamp_utc": [pd.Timestamp(ts1)],
                "trading_date": [d1],
            }
        ),
        curves_by_ts={
            pd.Timestamp(ts1): object(),
        },
    )

    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_gsquant_rl_basic",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy GSQUANT curve cache should not be used when CurveStore covers the requested day")
        ),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(
        mdp,
        "_build_gsquant_rl_curve",
        lambda **kwargs: {"timestamp": kwargs["request_timestamp"]},
    )

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-OIS",
            "timestamps": [d1],
            "ignore_cache": True,
        }
    )

    assert out == {d1: {"timestamp": d1}}
    assert len(store.raw_node_calls) == 1
    assert len(store.reconstruct_calls) == 1


def test_gsquant_bulk_get_data_ignores_invalid_curve_store_rows_and_falls_back(monkeypatch):
    rateslib = pytest.importorskip("rateslib")

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    d1 = dt.date(2026, 3, 3)
    ts1 = mdp._to_curve_store_timestamp(d1).astimezone(pytz.UTC)
    store = _FakeCurveStore(
        day_df=pd.DataFrame(
            {
                "timestamp_utc": [pd.Timestamp(ts1)],
                "trading_date": [d1],
                "node_dates": [[]],
                "discount_factors": [[]],
            }
        ),
        curves_by_ts={pd.Timestamp(ts1): object()},
    )

    bulk_calls = []
    monkeypatch.setattr(mdp, "_get_curve_store", lambda: store)
    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_gsquant_rl_basic",
        lambda **kwargs: bulk_calls.append(kwargs)
        or {
            d1: ("curve-cache-id-1", '{"curve":"d1"}', "NYC"),
        },
    )
    monkeypatch.setattr(rateslib, "from_json", lambda _: object())
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(
        mdp,
        "_build_gsquant_rl_curve",
        lambda **kwargs: {"timestamp": kwargs["request_timestamp"]},
    )
    monkeypatch.setattr(mdp, "_promote_gsquant_curve_store_day", lambda **kwargs: None)

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-OIS",
            "timestamps": [d1],
        }
    )

    assert bulk_calls == [
        {
            "curve_id": "USD-OIS",
            "bdates": [d1],
            "force_refresh": False,
            "max_workers": 1,
        }
    ]
    assert out == {d1: {"timestamp": d1}}
    assert store.reconstruct_calls == []


def test_promote_gsquant_curve_store_day_writes_missing_raw_and_analytics(monkeypatch):
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    nyc = pytz.timezone("America/New_York")

    class _Curve:
        def __init__(self, timestamp):
            self._meta = {"timestamp": timestamp}
            self._handle = SimpleNamespace(
                id="USD-OIS",
                interpolation="log_linear",
                nodes=SimpleNamespace(
                    _nodes={
                        dt.date(2026, 1, 2): 1.0,
                        dt.date(2027, 1, 2): 0.96,
                    }
                ),
            )

        def meta(self):
            return self._meta

        def handle(self):
            return self._handle

        def build_irswap(self, tenor=None, **kwargs):
            _ = kwargs
            return tenor

    curve = _Curve(nyc.localize(dt.datetime(2026, 1, 2, 15, 0)))
    raw_calls = []
    analytics_calls = []

    class _Store:
        def has_day(self, curve_name, trading_date):
            _ = curve_name, trading_date
            return False

        def has_analytics_day(self, curve_name, trading_date):
            _ = curve_name, trading_date
            return False

        def write_day(self, curve_name, trading_date, snapshots):
            raw_calls.append((curve_name, trading_date, snapshots))

        def write_analytics_day(self, curve_name, trading_date, df):
            analytics_calls.append((curve_name, trading_date, df))

    monkeypatch.setattr(mdp, "_get_curve_store", lambda: _Store())

    mdp._promote_gsquant_curve_store_day(
        requested_curve_name="USD-OIS",
        curve=curve,
        request_timestamp=dt.date(2026, 1, 2),
    )

    assert len(raw_calls) == 1
    assert raw_calls[0][0] == "USD-OIS"
    assert raw_calls[0][1] == dt.date(2026, 1, 2)
    assert raw_calls[0][2][0].source_variant == "GSQUANT_RL"
    assert raw_calls[0][2][0].reference_key == "USD-OIS"
    assert len(analytics_calls) == 1
    assert analytics_calls[0][0] == "USD-OIS"
    assert analytics_calls[0][1] == dt.date(2026, 1, 2)
    assert "par_rate_10Y" in analytics_calls[0][2].columns


def test_gsquant_get_data_uses_curve_store_fast_path(monkeypatch):
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    d1 = dt.date(2026, 1, 2)
    ts1 = mdp._to_curve_store_timestamp(d1).astimezone(pytz.UTC)
    store = _FakeCurveStore(
        day_df=pd.DataFrame(
            {
                "timestamp_utc": [pd.Timestamp(ts1)],
                "trading_date": [d1],
            }
        ),
        curves_by_ts={
            pd.Timestamp(ts1): object(),
        },
    )

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

    wrap_calls = []

    def _stub_wrap(**kwargs):
        wrap_calls.append(kwargs["request_timestamp"])
        return {"timestamp": kwargs["request_timestamp"]}

    monkeypatch.setattr(mdp, "_build_gsquant_rl_curve", _stub_wrap)

    out = mdp.get_data(
        {
            "curve_name": "USD-OIS",
            "timestamp": d1,
        }
    )

    assert out == {"timestamp": d1}
    assert len(store.raw_node_calls) == 1
    assert len(store.reconstruct_calls) == 1
    assert wrap_calls == [d1]


def test_gsquant_get_data_uses_curve_store_fast_path_even_when_force_refresh_true(monkeypatch):
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    d1 = dt.date(2026, 1, 2)
    ts1 = mdp._to_curve_store_timestamp(d1).astimezone(pytz.UTC)
    store = _FakeCurveStore(
        day_df=pd.DataFrame(
            {
                "timestamp_utc": [pd.Timestamp(ts1)],
                "trading_date": [d1],
            }
        ),
        curves_by_ts={
            pd.Timestamp(ts1): object(),
        },
    )

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
    monkeypatch.setattr(
        mdp,
        "_build_gsquant_rl_curve",
        lambda **kwargs: {"timestamp": kwargs["request_timestamp"]},
    )

    out = mdp.get_data(
        {
            "curve_name": "USD-OIS",
            "timestamp": d1,
            "force_refresh": True,
        }
    )

    assert out == {"timestamp": d1}
    assert len(store.raw_node_calls) == 1
    assert len(store.reconstruct_calls) == 1


def test_eris_bulk_get_data_promotes_curve_store_for_cached_historical_days(monkeypatch):
    rateslib = pytest.importorskip("rateslib")

    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    d1 = dt.date(2026, 1, 2)
    d2 = dt.date(2026, 1, 5)

    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_eris_eod_live_rl_basic",
        lambda **kwargs: {d1: "curve-json-1", d2: "curve-json-2"},
    )
    monkeypatch.setattr(rateslib, "from_json", lambda _: object())
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series([4.1], index=pd.to_datetime(["2025-12-31"])),
    )
    monkeypatch.setattr(
        mdp,
        "_build_eris_eod_rl_curve",
        lambda **kwargs: _FakePromotableErisCurve(kwargs["request_timestamp"]),
    )
    monkeypatch.setattr(mdp, "_load_eris_curve_store_history", lambda **kwargs: {})

    promote_calls = []
    monkeypatch.setattr(
        mdp,
        "_promote_eris_curve_store_day",
        lambda **kwargs: promote_calls.append(kwargs["request_timestamp"]),
    )

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
        }
    )

    assert set(out) == {d1, d2}
    assert promote_calls == [d1, d2]


def test_gsquant_bulk_get_data_promotes_curve_store_for_cached_historical_days(monkeypatch):
    rateslib = pytest.importorskip("rateslib")

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    d1 = dt.date(2026, 1, 2)
    d2 = dt.date(2026, 1, 5)

    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_gsquant_rl_basic",
        lambda **kwargs: {
            d1: ("curve-cache-id-1", "curve-json-1", "NYC"),
            d2: ("curve-cache-id-2", "curve-json-2", "NYC"),
        },
    )
    monkeypatch.setattr(rateslib, "from_json", lambda _: object())
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: pd.Series([4.1], index=pd.to_datetime(["2025-12-31"])),
    )

    class _Curve:
        def __init__(self, timestamp):
            self._meta = {"timestamp": timestamp}
            self._handle = SimpleNamespace(
                id="USD-OIS",
                interpolation="log_linear",
                nodes=SimpleNamespace(
                    _nodes={
                        dt.date(2026, 1, 2): 1.0,
                        dt.date(2027, 1, 2): 0.96,
                    }
                ),
            )

        def meta(self):
            return self._meta

        def handle(self):
            return self._handle

        def build_irswap(self, tenor=None, **kwargs):
            _ = kwargs
            return tenor

    monkeypatch.setattr(
        mdp,
        "_build_gsquant_rl_curve",
        lambda **kwargs: _Curve(kwargs["request_timestamp"]),
    )
    monkeypatch.setattr(mdp, "_load_gsquant_curve_store_history", lambda **kwargs: {})

    promote_calls = []
    monkeypatch.setattr(
        mdp,
        "_promote_gsquant_curve_store_day",
        lambda **kwargs: promote_calls.append(kwargs["request_timestamp"]),
    )

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-OIS",
            "timestamps": [d1, d2],
        }
    )

    assert set(out) == {d1, d2}
    assert promote_calls == [d1, d2]


@pytest.mark.parametrize(
    ("curve_name", "reference_curve_name"),
    [
        ("USD-SOFR-1D-STIR-CME", "USD-SOFR-1D"),
        ("USD-OIS-STIR-LCH", "USD-OIS-STIR"),
    ],
)
def test_gsquant_rl_alias_curves_use_reference_curve_for_fixings_and_conventions(monkeypatch, curve_name, reference_curve_name):
    pytest.importorskip("gs_quant")
    rateslib = pytest.importorskip("rateslib")
    import Query.IRSwaps.backends.rateslib.RLIRSwapCurve as rl_curve_module

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    fixings_curve_names = []

    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "get_gsquant_rl_basic",
        lambda **kwargs: ("curve-cache-id", "{}", "NYC"),
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: fixings_curve_names.append(kwargs["curve_name"]) or pd.Series(dtype=float, index=pd.DatetimeIndex([])),
    )
    monkeypatch.setattr(rateslib, "from_json", lambda serialized: object())

    add_tenor_call = {}

    def _stub_add_tenor(date, tenor, modifier, calendar):
        add_tenor_call["tenor"] = tenor
        add_tenor_call["modifier"] = modifier
        add_tenor_call["calendar"] = calendar
        return date

    monkeypatch.setattr(rl_curve_module.rl, "add_tenor", _stub_add_tenor)

    curve = mdp.get_pricer({"curve_name": curve_name, "timestamp": dt.date(2026, 3, 3)})
    curve.calendar_advance(dt.date(2026, 3, 3), "1b")

    curve_def = RATESLIB_CURVE_DEFINITIONS[reference_curve_name]
    assert fixings_curve_names == [reference_curve_name]
    assert curve.id() == curve_name
    assert curve.meta()["curve_name"] == curve_name
    assert curve.meta()["requested_curve_name"] == curve_name
    assert curve.meta()["reference_curve_name"] == reference_curve_name
    assert add_tenor_call == {
        "tenor": "1b",
        "modifier": curve_def["BusinessConvention"],
        "calendar": curve_def["Calendar"],
    }


def test_gsquant_rl_bulk_get_data_uses_batch_cache_and_shared_fixings(monkeypatch):
    rateslib = pytest.importorskip("rateslib")

    d0 = dt.date(2026, 1, 19)
    d1 = dt.date(2026, 3, 3)
    d2 = dt.date(2026, 3, 4)
    mdp = IRSwapsMDP(source="GSQUANT-RL")

    bulk_calls = []
    fixings_calls = []
    monkeypatch.setattr(mdp, "_supports_curve_store_raw_curve_fast_path", lambda: False)

    monkeypatch.setattr(
        mdp._rl_curve_cache,
        "bulk_get_gsquant_rl_basic",
        lambda **kwargs: bulk_calls.append(kwargs)
        or {
            d1: ("curve-cache-id-1", '{"curve":"d1"}', "NYC"),
            d2: ("curve-cache-id-2", '{"curve":"d2"}', "NYC"),
        },
    )
    monkeypatch.setattr(
        irswaps_mdp_module,
        "_fetch_fixings",
        lambda **kwargs: fixings_calls.append(kwargs)
        or pd.Series([4.10, 4.15], index=pd.to_datetime(["2026-03-01", "2026-03-02"])),
    )
    monkeypatch.setattr(rateslib, "from_json", lambda serialized: SimpleNamespace(serialized=serialized))

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-OIS",
            "timestamps": [d0, d1, d2],
            "n_jobs": 3,
        }
    )

    assert bulk_calls == [
        {
            "curve_id": "USD-OIS",
            "bdates": [d1, d2],
            "force_refresh": False,
            "max_workers": 3,
        }
    ]
    assert fixings_calls == [
        {
            "as_of_date": d2,
            "curve_name": "USD-OIS",
            "force_refresh": False,
        }
    ]
    assert d0 not in out
    assert set(out) == {d1, d2}
    assert out[d1].meta()["id"] == "curve-cache-id-1"
    assert out[d1].meta()["pricing_location"] == "NYC"
    assert out[d1].meta()["reference_curve_name"] == "USD-OIS"
    assert out[d2].meta()["id"] == "curve-cache-id-2"



def test_eris_eod_variants_use_separate_curve_store_assets():
    """The two ERIS EOD sources must not share one CurveStore asset key.

    What lives under USD-SOFR-1D is the raw ~18.3k-node daily discount frame --
    the -NOJUMPS curve. -RL_BASIC prices off a 25-node log-cubic spline built
    from it, so a shared key silently turned -RL_BASIC into -NOJUMPS whenever the
    day was cached (identical rates on every tenor, so any RV spread between the
    two sources was exactly zero) and let them diverge by up to ~7.4 bp at the
    long end when it was not.
    """
    nojumps = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")
    basic = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")

    # -NOJUMPS keeps the original key so its stored history stays live
    assert nojumps._eris_curve_store_asset("USD-SOFR-1D") == "USD-SOFR-1D"
    assert basic._eris_curve_store_asset("USD-SOFR-1D") != "USD-SOFR-1D"
    assert basic._eris_curve_store_asset("USD-SOFR-1D").startswith("USD-SOFR-1D")


def test_bulk_get_data_applies_calendar_validation_like_single_point(monkeypatch):
    """Weekend/holiday points must be dropped by the BULK path too.

    _validate_curve_request_timestamp was only reached via _get_curve, and every
    source with a dedicated bulk branch bypassed it -- while TB only ever calls
    bulk_get_data. Those points were priced off the previous session's anchor, so
    the index label and the curve's reference_date disagreed by a business day
    (+1.691 bp measured on the 2026-07-03 Jul-4 holiday), for a request the
    single-point path refuses outright.
    """
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-QL_BASIC")
    good = dt.date(2026, 2, 13)      # Fri
    holiday = dt.date(2026, 2, 16)   # Presidents' Day
    saturday = dt.date(2026, 2, 14)

    seen = []

    def _stub_get_data(request):
        seen.append(request["timestamp"])
        return {"curve": request["timestamp"]}

    monkeypatch.setattr(mdp, "get_data", _stub_get_data)

    out = mdp.bulk_get_data(
        {"curve_name": "USD-SOFR-1D", "timestamps": [good, holiday, saturday]}
    )

    assert seen == [good]
    assert set(out) == {good}

    # ... and the single-point path refuses the same dates
    for bad in (holiday, saturday):
        with pytest.raises(Exception):
            mdp._validate_curve_request_timestamp(curve_name="USD-SOFR-1D", timestamp=bad)
