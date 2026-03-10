import argparse
import datetime as dt

import pandas as pd

import SDRUtils._swappulse_scripts.ingest_listed_vs_swaption_vol as ingest_mod
from SDRUtils._swappulse_scripts.ingest_listed_vs_swaption_vol import (
    LISTED_TO_SWAPTION_EXPIRY,
    PRODUCT_SWAP_TENOR,
    REALIZED_WINDOWS,
    ROLLING_EXPIRIES,
    _build_comparison_row,
    _build_snapshot_row_from_stir_smile,
    _build_snapshot_row_from_ust_smile,
    build_smile_request_maps,
    compute_annualized_realized_normal_vol_bps,
)


class _DummyUstParams:
    alpha = 0.12
    beta = 0.5
    rho = -0.2
    nu = 0.8
    forward_price = 110.25
    forward_futures_ytm = 0.0431
    expiry_date = dt.date(2026, 3, 31)


class _DummyUstSmile:
    params = _DummyUstParams()
    fv01 = 0.08
    underlying_contract = "TYM26"
    source = "USTFO_DUAL-QL"

    def normal_vol(self, strike):
        assert strike == self.params.forward_price
        return 0.64

    def to_dict(self):
        return {"symbol": "TY_30", "points": [{"label": "25DC"}]}


class _DummyStirParams:
    alpha = 0.09
    beta = 0.5
    rho = 0.1
    nu = 0.7
    forward_price = 95.625
    forward_rate = 4.375
    expiry_date = dt.date(2026, 4, 15)


class _DummyStirSmile:
    params = _DummyStirParams()
    underlying_contract = "SR3M26"
    source = "STIRFO_DUAL-QL"

    def normal_vol(self, strike, vol_units="price"):
        assert strike == self.params.forward_price
        return 0.55 if vol_units == "price" else 55.0

    def to_dict(self):
        return {"symbol": "SR3_30", "points": [{"label": "25DC"}]}


def test_build_smile_request_maps_covers_all_products_and_expiries():
    mapping = build_smile_request_maps()

    assert mapping["TY_30"] == ("TY", "1M")
    assert mapping["UL_07"] == ("WN", "1W")
    assert mapping["TN_07"] == ("UXY", "1W")
    assert mapping["SR3_30"] == ("SFR", "1M")
    assert len(mapping) == len(ROLLING_EXPIRIES) * len(PRODUCT_SWAP_TENOR)


def test_build_snapshot_row_from_ust_smile_converts_price_vol_to_bps():
    row = _build_snapshot_row_from_ust_smile(
        as_of_date=dt.date(2026, 3, 1),
        product="TY",
        expiry_label="1M",
        expiry_days_requested=30,
        smile=_DummyUstSmile(),
    )

    assert row["product_class"] == "UST"
    assert row["atm_nvol_price"] == 0.64
    assert row["atm_nvol_bps"] == 8.0
    assert row["forward_yield"] == 0.0431
    assert row["underlying_contract"] == "TYM26"


def test_build_snapshot_row_from_stir_smile_uses_bps_output_directly():
    row = _build_snapshot_row_from_stir_smile(
        as_of_date=dt.date(2026, 3, 16),
        product="SFR",
        expiry_label="1M",
        expiry_days_requested=30,
        smile=_DummyStirSmile(),
    )

    assert row["product_class"] == "STIR"
    assert row["atm_nvol_price"] == 0.55
    assert row["atm_nvol_bps"] == 55.0
    assert row["forward_yield"] == 4.375
    assert row["fv01"] is None


def test_build_comparison_row_uses_swaption_mappings_and_ratios():
    listed_row = {
        "as_of_date": dt.date(2026, 3, 9),
        "product": "TY",
        "expiry_label": "2M",
        "atm_nvol_bps": 82.5,
    }

    row = _build_comparison_row(listed_row, swaption_atmf_nvol_bps=90.75)

    assert row["swaption_expiry_label"] == LISTED_TO_SWAPTION_EXPIRY["2M"]
    assert row["swaption_tenor_label"] == PRODUCT_SWAP_TENOR["TY"]
    assert row["vol_diff_bps"] == 8.25
    assert row["vol_ratio"] == 90.75 / 82.5


def test_compute_annualized_realized_normal_vol_bps_uses_daily_changes():
    levels = pd.Series(
        [420.0, 423.0, 421.5, 425.5, 424.0, 426.5],
        index=pd.bdate_range("2026-03-02", periods=6),
    )

    realized = compute_annualized_realized_normal_vol_bps(
        levels,
        window_sessions=REALIZED_WINDOWS["1W"],
    )

    assert realized is not None
    assert realized > 0


def test_main_range_continues_when_single_day_fails(monkeypatch):
    called_dates: list[dt.date] = []

    def _stub_create_db_engine():
        return object()

    def _stub_ensure_schema(engine):
        assert engine is not None

    def _stub_run_daily_ingest(engine, *, as_of_date, curve_name, surface_type, force_refresh):
        assert engine is not None
        assert curve_name == "USD-SOFR-1D"
        assert surface_type == "atmf_normal"
        called_dates.append(as_of_date)
        if as_of_date == dt.date(2026, 3, 4):
            raise RuntimeError("boom")
        return {
            "as_of_date": as_of_date.isoformat(),
            "listed_rows": 1,
            "comparison_rows": 1,
            "realized_rows": 1,
        }

    monkeypatch.setattr(ingest_mod, "create_db_engine", _stub_create_db_engine)
    monkeypatch.setattr(ingest_mod, "ensure_schema", _stub_ensure_schema)
    monkeypatch.setattr(ingest_mod, "run_daily_ingest", _stub_run_daily_ingest)

    args = argparse.Namespace(
        start_date="2026-03-03",
        end_date="2026-03-05",
        curve_name="USD-SOFR-1D",
        surface_type="atmf_normal",
        lookback_business_days=10,
        force_refresh=False,
    )

    ingest_mod.main_range(args)

    assert called_dates == [
      dt.date(2026, 3, 3),
      dt.date(2026, 3, 4),
      dt.date(2026, 3, 5),
    ]
