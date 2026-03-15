import argparse
import datetime as dt
import json

import pytest

from SDRUtils._swappulse_scripts import ingest_ustf_vs_swaption_vol as ingest_mod


def test_main_range_continues_when_single_day_fails(monkeypatch):
    called_dates: list[dt.date] = []
    logged_messages: list[tuple[str, str]] = []

    def _stub_create_db_engine():
        return object()

    def _stub_ensure_schema(engine):
        assert engine is not None

    def _stub_run_daily_ingest(engine, *, as_of_date, curve_name, force_refresh):
        assert engine is not None
        assert curve_name == "USD-SOFR-1D"
        assert force_refresh is False
        called_dates.append(as_of_date)
        if as_of_date == dt.date(2026, 3, 4):
            raise RuntimeError("boom")
        return {
            "as_of_date": as_of_date.isoformat(),
            "ustf_rows": 1,
            "swaption_rows": 1,
            "comparison_rows": 1,
        }

    def _stub_log_status(message, *, level="INFO"):
        logged_messages.append((level, message))

    monkeypatch.setattr(ingest_mod, "create_db_engine", _stub_create_db_engine)
    monkeypatch.setattr(ingest_mod, "ensure_schema", _stub_ensure_schema)
    monkeypatch.setattr(ingest_mod, "run_daily_ingest", _stub_run_daily_ingest)
    monkeypatch.setattr(ingest_mod, "_log_status", _stub_log_status)

    args = argparse.Namespace(
        start_date="2026-03-03",
        end_date="2026-03-05",
        curve_name="USD-SOFR-1D",
        lookback_business_days=10,
        force_refresh=False,
    )

    ingest_mod.main_range(args)

    assert called_dates == [
        dt.date(2026, 3, 3),
        dt.date(2026, 3, 4),
        dt.date(2026, 3, 5),
    ]
    assert ("WARN", "Failed backfill dates: 2026-03-04") in logged_messages
    assert (
        "INFO",
        "USTF-vs-swaption backfill complete: success=2 failure=1",
    ) in logged_messages


def test_fetch_swaption_snapshot_rows_uses_context_cube_and_source(monkeypatch):
    captured_init: dict[str, object] = {}
    captured_request: dict[str, object] = {}
    captured_resolution: dict[str, object] = {}

    class FakeCube:
        def sabr_params_at(self, expiry_label, tail_label):
            assert expiry_label == "1M"
            assert tail_label == "2Y"
            return {
                "atmf_rate": 0.04125,
                "alpha": 0.18,
                "beta": 0.5,
                "rho": -0.22,
                "nu": 0.44,
                "expiry_time": 0.085,
            }

        def atm_vol(self, expiry_label, tail_label):
            assert expiry_label == "1M"
            assert tail_label == "2Y"
            return 0.008816514448951044

    fake_cube = FakeCube()

    class FakeContext:
        source = "GSQUANT_MC_ENHANCED-QL"

        def meta(self):
            return {"vol_cube": fake_cube}

    class FakeMDP:
        def __init__(self, *, source, curve_source, data_dir, force_refresh):
            captured_init.update(
                {
                    "source": source,
                    "curve_source": curve_source,
                    "data_dir": data_dir,
                    "force_refresh": force_refresh,
                }
            )

        def get_data(self, request):
            captured_request.update(request)
            return FakeContext()

    class FakeValueMap:
        def apply(self, value):
            assert value == ingest_mod.IRSwaptionValue.NVOL
            return 88.16514448951044

    class FakeResolvedQuery:
        def resolve_package(self, *, pricer_or_curve):
            captured_resolution["resolve_package_context"] = pricer_or_curve
            return (["pkg"], [1.0, 1.0])

        def build_value_map(self, *, pricer_or_curve, package, risk_weights):
            captured_resolution["build_value_map_context"] = pricer_or_curve
            captured_resolution["package"] = package
            captured_resolution["risk_weights"] = risk_weights
            return FakeValueMap()

    def _stub_resolve_query(query, *, timestamp, pricer_or_curve):
        captured_resolution["timestamp"] = timestamp
        captured_resolution["expiry"] = query.expiry
        captured_resolution["tail"] = query.tail
        captured_resolution["structure"] = query.structure
        captured_resolution["context"] = pricer_or_curve
        return FakeResolvedQuery()

    monkeypatch.setattr(ingest_mod, "IRSwaptionMDP", FakeMDP)
    monkeypatch.setattr(ingest_mod, "resolve_query", _stub_resolve_query)
    monkeypatch.setattr(ingest_mod, "SWAPTION_EXPIRY_LABELS", ["1M"])
    monkeypatch.setattr(ingest_mod, "SWAPTION_TAIL_LABELS", ["2Y"])

    rows = ingest_mod._fetch_swaption_snapshot_rows(
        as_of_date=dt.date(2026, 3, 6),
        curve_name="USD-SOFR-1D",
        force_refresh=True,
    )

    assert captured_init == {
        "source": "GSQUANT_MC_ENHANCED-QL",
        "curve_source": "ERIS_EOD_LIVE-QL_BASIC",
        "data_dir": ingest_mod.MONKEYCUBE_DATA_DIR,
        "force_refresh": True,
    }
    assert captured_request == {
        "curve_name": "USD-SOFR-1D",
        "timestamp": dt.date(2026, 3, 6),
        "ignore_cache": True,
    }
    assert captured_resolution["timestamp"] == dt.date(2026, 3, 6)
    assert captured_resolution["expiry"] == "1M"
    assert captured_resolution["tail"] == "2Y"
    assert captured_resolution["structure"] == ingest_mod.IRSwaptionStructure.STRADDLE
    assert len(rows) == 1
    assert rows[0] == {
        **rows[0],
        "as_of_date": dt.date(2026, 3, 6),
        "expiry_label": "1M",
        "tail_label": "2Y",
        "atm_nvol_bps": 88.16514448951044,
        "atmf_rate": 0.04125,
        "sabr_alpha": 0.18,
        "sabr_beta": 0.5,
        "sabr_rho": -0.22,
        "sabr_nu": 0.44,
        "expiry_time": 0.085,
        "source": "GSQUANT_MC_ENHANCED-QL",
    }
    assert rows[0]["delta_otm_vols"] == "{}"
    assert json.loads(rows[0]["strike_offset_otm_vols"])["payer"]["10"]["vol_bps"] is None


def test_fetch_swaption_snapshot_rows_falls_back_to_surface_when_context_cube_missing(monkeypatch):
    logged_messages: list[tuple[str, str]] = []
    captured_atm_resolution: dict[str, object] = {}

    class FakeCurve:
        @staticmethod
        def calendar_advance(as_of_date, tenor):
            if tenor == "1M":
                return dt.date(2026, 4, 6)
            if tenor == "2Y":
                return dt.date(2028, 4, 6)
            raise AssertionError(f"Unexpected tenor {tenor} from {as_of_date}")

    class FakeContext:
        source = "GSQUANT-QL"
        as_of_date = dt.date(2026, 3, 6)
        curve = FakeCurve()

        def meta(self):
            return {}

    class FakeMDP:
        def __init__(self, *, source, curve_source, data_dir, force_refresh):
            _ = (source, curve_source, data_dir, force_refresh)

        def get_data(self, request):
            _ = request
            return FakeContext()

    def _stub_log_status(message, *, level="INFO"):
        logged_messages.append((level, message))

    def _stub_leg_forward_rate(market_context, leg):
        assert market_context.as_of_date == dt.date(2026, 3, 6)
        assert leg.exercise_date == dt.date(2026, 4, 6)
        assert leg.underlying_maturity_date == dt.date(2028, 4, 6)
        return 0.0375

    def _stub_leg_tte_years(market_context, leg):
        assert market_context.as_of_date == dt.date(2026, 3, 6)
        assert leg.strike == pytest.approx(0.0375)
        return 0.08

    def _stub_leg_model_vol(market_context, leg, *, strike=None):
        assert market_context.as_of_date == dt.date(2026, 3, 6)
        strike_rate = float(leg.strike if strike is None else strike)
        return 0.0077 + abs(strike_rate - 0.0375)

    def _stub_solve_strike_for_target_delta(*, target_delta_abs, option_type, forward, vol_normal, tte):
        assert forward == pytest.approx(0.0375)
        assert vol_normal > 0.0
        assert tte == pytest.approx(0.08)
        bump = float(target_delta_abs) / 10_000.0
        return forward + bump if option_type == "payer" else forward - bump

    def _stub_resolve_swaption_atm_nvol_bps(
        *,
        market_context,
        as_of_date,
        expiry_label,
        tail_label,
        fallback_vol_decimal=None,
    ):
        captured_atm_resolution.update(
            {
                "context": market_context,
                "as_of_date": as_of_date,
                "expiry_label": expiry_label,
                "tail_label": tail_label,
                "fallback_vol_decimal": fallback_vol_decimal,
            }
        )
        return 77.0

    monkeypatch.setattr(ingest_mod, "IRSwaptionMDP", FakeMDP)
    monkeypatch.setattr(ingest_mod, "_log_status", _stub_log_status)
    monkeypatch.setattr(ingest_mod, "leg_forward_rate", _stub_leg_forward_rate)
    monkeypatch.setattr(ingest_mod, "leg_tte_years", _stub_leg_tte_years)
    monkeypatch.setattr(ingest_mod, "leg_model_vol", _stub_leg_model_vol)
    monkeypatch.setattr(ingest_mod, "solve_strike_for_target_delta", _stub_solve_strike_for_target_delta)
    monkeypatch.setattr(ingest_mod, "_resolve_swaption_atm_nvol_bps", _stub_resolve_swaption_atm_nvol_bps)
    monkeypatch.setattr(ingest_mod, "SWAPTION_EXPIRY_LABELS", ["1M"])
    monkeypatch.setattr(ingest_mod, "SWAPTION_TAIL_LABELS", ["2Y"])

    rows = ingest_mod._fetch_swaption_snapshot_rows(
        as_of_date=dt.date(2026, 3, 6),
        curve_name="USD-SOFR-1D",
        force_refresh=False,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["as_of_date"] == dt.date(2026, 3, 6)
    assert row["expiry_label"] == "1M"
    assert row["tail_label"] == "2Y"
    assert row["atm_nvol_bps"] == pytest.approx(77.0)
    assert row["atmf_rate"] == pytest.approx(0.0375)
    assert row["sabr_alpha"] is None
    assert row["sabr_beta"] is None
    assert row["sabr_rho"] is None
    assert row["sabr_nu"] is None
    assert row["expiry_time"] == pytest.approx(0.08)

    delta_payload = json.loads(row["delta_otm_vols"])
    offset_payload = json.loads(row["strike_offset_otm_vols"])
    assert delta_payload["payer"]["10d"]["strike_rate"] == pytest.approx(0.0385)
    assert delta_payload["payer"]["10d"]["vol_bps"] == pytest.approx(87.0)
    assert offset_payload["receiver"]["25"]["strike_rate"] == pytest.approx(0.035)
    assert offset_payload["receiver"]["25"]["vol_bps"] == pytest.approx(102.0)

    assert captured_atm_resolution["fallback_vol_decimal"] == pytest.approx(0.0077)
    assert (
        "WARN",
        "No swaption SABR cube found for 2026-03-06 from GSQUANT-QL; "
        "falling back to surface-only pricing with flat extrapolation",
    ) in logged_messages


def test_fetch_bulk_sabr_smiles_batched_retries_individual_symbols(monkeypatch):
    as_of_date = dt.date(2026, 3, 12)
    logged_messages: list[tuple[str, str]] = []
    requests: list[dict[str, object]] = []

    class FakeMDP:
        def fetch_bulk_sabr_smile(self, request):
            requests.append(dict(request))
            symbols = list(request["globex_symbols"])
            if symbols == ["TU_30", "FV_30"]:
                raise ValueError("batch calibration failed")
            if symbols == ["FV_30"]:
                raise ValueError("Not enough valid SABR smile legs")
            return {symbol: {as_of_date: f"smile:{symbol}"} for symbol in symbols}

    def _stub_log_status(message, *, level="INFO"):
        logged_messages.append((level, message))

    monkeypatch.setattr(ingest_mod, "_log_status", _stub_log_status)

    result = ingest_mod._fetch_bulk_sabr_smiles_batched(
        mdp=FakeMDP(),
        globex_symbols=["TU_30", "FV_30", "TY_30"],
        as_of_date=as_of_date,
        force_refresh=True,
        batch_size=2,
    )

    assert result == {
        "TU_30": {as_of_date: "smile:TU_30"},
        "TY_30": {as_of_date: "smile:TY_30"},
    }
    assert requests == [
        {
            "globex_symbols": ["TU_30", "FV_30"],
            "timestamps": [as_of_date],
            "force_refresh": True,
            "show_tqdm": False,
        },
        {
            "globex_symbols": ["TU_30"],
            "timestamps": [as_of_date],
            "force_refresh": True,
            "show_tqdm": False,
        },
        {
            "globex_symbols": ["FV_30"],
            "timestamps": [as_of_date],
            "force_refresh": True,
            "show_tqdm": False,
        },
        {
            "globex_symbols": ["TY_30"],
            "timestamps": [as_of_date],
            "force_refresh": True,
            "show_tqdm": False,
        },
    ]
    assert (
        "WARN",
        "2026-03-12: USTF SABR batch failed for TU_30, FV_30; retrying individually: "
        "batch calibration failed",
    ) in logged_messages
    assert (
        "WARN",
        "2026-03-12: skipping USTF symbol FV_30: Not enough valid SABR smile legs",
    ) in logged_messages


def test_fetch_ustf_snapshot_rows_skips_bad_symbol_row_build(monkeypatch):
    as_of_date = dt.date(2026, 3, 12)
    logged_messages: list[tuple[str, str]] = []

    class FakeMDP:
        def __init__(self, *, source, force_refresh):
            assert source == "USTFO_DUAL-QL"
            assert force_refresh is False

    def _stub_request_map():
        return {
            "TU_30": ("TU", "1M"),
            "FV_30": ("FV", "1M"),
        }

    def _stub_fetch_bulk_sabr_smiles_batched(*, mdp, globex_symbols, as_of_date, force_refresh):
        assert isinstance(mdp, FakeMDP)
        assert globex_symbols == ["TU_30", "FV_30"]
        assert as_of_date == dt.date(2026, 3, 12)
        assert force_refresh is True
        return {
            "TU_30": {as_of_date: "smile-tu"},
            "FV_30": {as_of_date: "smile-fv"},
        }

    def _stub_build_ustf_snapshot_row(*, as_of_date, product, expiry_label, expiry_days_requested, smile):
        assert as_of_date == dt.date(2026, 3, 12)
        assert expiry_label == "1M"
        assert expiry_days_requested == ingest_mod.ROLLING_EXPIRIES["1M"]
        if product == "FV":
            raise ValueError("bad smile payload")
        return {
            "as_of_date": as_of_date,
            "product": product,
            "expiry_label": expiry_label,
            "smile": smile,
        }

    def _stub_log_status(message, *, level="INFO"):
        logged_messages.append((level, message))

    monkeypatch.setattr(ingest_mod, "USTFutureOptionMDP", FakeMDP)
    monkeypatch.setattr(ingest_mod, "_build_ustf_request_map", _stub_request_map)
    monkeypatch.setattr(ingest_mod, "_fetch_bulk_sabr_smiles_batched", _stub_fetch_bulk_sabr_smiles_batched)
    monkeypatch.setattr(ingest_mod, "_build_ustf_snapshot_row", _stub_build_ustf_snapshot_row)
    monkeypatch.setattr(ingest_mod, "_log_status", _stub_log_status)

    rows = ingest_mod._fetch_ustf_snapshot_rows(
        as_of_date=as_of_date,
        force_refresh=True,
    )

    assert rows == [
        {
            "as_of_date": as_of_date,
            "product": "TU",
            "expiry_label": "1M",
            "smile": "smile-tu",
        }
    ]
    assert (
        "WARN",
        "2026-03-12: skipping USTF symbol FV_30 (FV 1M) during row build: bad smile payload",
    ) in logged_messages


def test_build_ustf_otm_payloads_include_price_and_ytm_metadata():
    class FakePoint:
        def __init__(
            self,
            *,
            label,
            right,
            delta_abs,
            strike_price,
            strike_futures_ytm,
            iv_normal_price,
            iv_normal_bps,
        ):
            self.label = label
            self.right = right
            self.delta_abs = delta_abs
            self.strike_price = strike_price
            self.strike_futures_ytm = strike_futures_ytm
            self.iv_normal_price = iv_normal_price
            self.iv_normal_bps = iv_normal_bps

    class FakeParams:
        forward_price = 110.0
        forward_futures_ytm = 0.0410
        alpha = 0.2
        beta = 0.5
        rho = -0.1
        nu = 0.4
        time_to_expiry = 0.25
        expiry_date = dt.date(2026, 6, 5)

    class FakeSmile:
        params = FakeParams()
        fv01 = 0.8
        points = (
            FakePoint(
                label="5D Call",
                right="C",
                delta_abs=5.0,
                strike_price=110.05,
                strike_futures_ytm=0.0405,
                iv_normal_price=0.0105,
                iv_normal_bps=13.125,
            ),
            FakePoint(
                label="5D Put",
                right="P",
                delta_abs=5.0,
                strike_price=109.95,
                strike_futures_ytm=0.0415,
                iv_normal_price=0.0115,
                iv_normal_bps=14.375,
            ),
        )

        def normal_vol(self, strike, strike_space="price", vol_units="price"):
            _ = strike_space
            vol_price = 0.01 + (float(strike) - self.params.forward_price) * 0.01
            if vol_units == "bps":
                return vol_price / self.fv01
            return vol_price

        def price_to_futures_ytm(self, strike):
            return self.params.forward_futures_ytm - (float(strike) - self.params.forward_price) * 0.01

    delta_payload = ingest_mod._build_ustf_delta_otm_payload(FakeSmile())
    offset_payload = ingest_mod._build_ustf_strike_offset_otm_payload(FakeSmile())

    delta_call = delta_payload["call"]["5d"]
    assert delta_call["selector"] == "5d"
    assert delta_call["right"] == "C"
    assert delta_call["vol_price"] == pytest.approx(0.0105)
    assert delta_call["market_vol_bps"] == pytest.approx(13.125)
    assert delta_call["strike_price"] == pytest.approx(110.05)
    assert delta_call["strike_futures_ytm"] == pytest.approx(0.0405)

    offset_put = offset_payload["put"]["10"]
    assert offset_put["selector"] == "10"
    assert offset_put["signed_offset_bps"] == pytest.approx(-10.0)
    assert offset_put["vol_bps"] == pytest.approx(0.01249)
    assert offset_put["strike_price"] == pytest.approx(109.9992)
    assert offset_put["strike_futures_ytm_offset_bps"] == pytest.approx(0.08)


def test_build_swaption_otm_payloads_include_delta_and_offset_nodes(monkeypatch):
    class FakeCube:
        def sabr_params_at(self, expiry_label, tail_label):
            assert expiry_label == "1M"
            assert tail_label == "2Y"
            return {
                "atmf_rate": 0.04,
                "expiry_time": 1.0,
            }

        def atm_vol(self, expiry_label, tail_label):
            assert expiry_label == "1M"
            assert tail_label == "2Y"
            return 0.01

        def volatility(self, expiry_label, tail_label, strike):
            assert expiry_label == "1M"
            assert tail_label == "2Y"
            return 0.01 + abs(float(strike) - 0.04)

    def _stub_solve_strike_for_target_delta(*, target_delta_abs, option_type, forward, vol_normal, tte):
        _ = (vol_normal, tte)
        bump = float(target_delta_abs) / 10_000.0
        return forward + bump if option_type == "payer" else forward - bump

    monkeypatch.setattr(ingest_mod, "solve_strike_for_target_delta", _stub_solve_strike_for_target_delta)

    cube = FakeCube()
    delta_payload = ingest_mod._build_swaption_delta_otm_payload(
        cube=cube,
        expiry_label="1M",
        tail_label="2Y",
        atmf_rate=0.04,
        expiry_time=1.0,
    )
    offset_payload = ingest_mod._build_swaption_strike_offset_otm_payload(
        cube=cube,
        expiry_label="1M",
        tail_label="2Y",
        atmf_rate=0.04,
    )

    payer_10d = delta_payload["payer"]["10d"]
    assert payer_10d["selector"] == "10d"
    assert payer_10d["strike_rate"] == pytest.approx(0.041)
    assert payer_10d["vol_bps"] == pytest.approx(110.0)
    assert payer_10d["strike_offset_bps"] == pytest.approx(10.0)

    receiver_25bp = offset_payload["receiver"]["25"]
    assert receiver_25bp["selector"] == "25"
    assert receiver_25bp["signed_offset_bps"] == pytest.approx(-25.0)
    assert receiver_25bp["strike_rate"] == pytest.approx(0.0375)
    assert receiver_25bp["vol_bps"] == pytest.approx(125.0)


def test_build_ustf_snapshot_row_serializes_otm_payloads():
    class FakeParams:
        forward_price = 111.0
        forward_futures_ytm = 0.042
        alpha = 0.2
        beta = 0.5
        rho = -0.1
        nu = 0.4
        time_to_expiry = 0.25
        expiry_date = dt.date(2026, 4, 6)

    class FakePoint:
        def __init__(self):
            self.label = "10D Call"
            self.right = "C"
            self.delta_abs = 10.0
            self.strike_price = 111.05
            self.strike_futures_ytm = 0.0415
            self.iv_normal_price = 0.011
            self.iv_normal_bps = 13.75

        def to_dict(self):
            return {
                "label": self.label,
                "right": self.right,
                "delta_abs": self.delta_abs,
                "strike_price": self.strike_price,
                "strike_futures_ytm": self.strike_futures_ytm,
                "iv_normal_price": self.iv_normal_price,
                "iv_normal_bps": self.iv_normal_bps,
            }

    class FakeSmile:
        params = FakeParams()
        fv01 = 0.8
        points = (FakePoint(),)
        underlying_contract = "TYM6"
        source = "USTFO_DUAL-QL"

        def normal_vol(self, strike, strike_space="price", vol_units="price"):
            _ = strike_space
            vol_price = 0.012 + (float(strike) - self.params.forward_price) * 0.01
            if vol_units == "bps":
                return vol_price / self.fv01
            return vol_price

        def price_to_futures_ytm(self, strike):
            return self.params.forward_futures_ytm - (float(strike) - self.params.forward_price) * 0.01

    row = ingest_mod._build_ustf_snapshot_row(
        as_of_date=dt.date(2026, 3, 6),
        product="TY",
        expiry_label="1M",
        expiry_days_requested=30,
        smile=FakeSmile(),
    )

    delta_payload = json.loads(row["delta_otm_vols"])
    offset_payload = json.loads(row["strike_offset_otm_vols"])

    assert delta_payload["call"]["10d"]["strike_price"] == 111.05
    assert "strike_futures_ytm" in delta_payload["call"]["10d"]
    assert offset_payload["call"]["5"]["vol_bps"] is not None
