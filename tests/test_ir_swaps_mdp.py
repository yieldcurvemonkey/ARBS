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

    def reconstruct_curves_batch(self, df, *, cfg=None, max_workers=4):
        self.reconstruct_calls.append(
            {
                "cfg": cfg,
                "max_workers": max_workers,
                "timestamps": list(df["timestamp_utc"]),
            }
        )
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

    assert len(raw_calls) == 1
    assert raw_calls[0][0] == "USD-SOFR-1D"
    assert raw_calls[0][1] == dt.date(2026, 1, 2)
    assert raw_calls[0][2][0].source_variant == "ERIS_RL_BASIC"
    assert len(analytics_calls) == 1
    assert analytics_calls[0][0] == "USD-SOFR-1D"
    assert analytics_calls[0][1] == dt.date(2026, 1, 2)
    assert "par_rate_10Y" in analytics_calls[0][2].columns


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
