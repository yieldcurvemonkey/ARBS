import pandas as pd
import numpy as np
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "SDRUtils"
    / "_swappulse_scripts"
    / "ingest_usdswaps.py"
)
SPEC = spec_from_file_location("ingest_usdswaps_test", MODULE_PATH)
assert SPEC and SPEC.loader
ingest_module = module_from_spec(SPEC)
SPEC.loader.exec_module(ingest_module)

build_legs_dataframe = ingest_module.build_legs_dataframe
build_package_metrics = ingest_module.build_package_metrics
build_packages_dataframe = ingest_module.build_packages_dataframe
normalize_dataframe = ingest_module.normalize_dataframe
to_db_value = ingest_module._to_db_value


def _sample_raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_id": "T-OUT-1",
                "package_id": "PKG-OUT",
                "package_type": "OUTRIGHT",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:00:00Z",
                "effective_date": "2026-02-07",
                "expiration_date": "2028-02-07",
                "tenor_years": 2.0,
                "tenor_label": "2Y",
                "forward_start_years": 0.0,
                "forward_label": "spot",
                "is_forward": False,
                "notional": 100_000_000,
                "risk": 20_000,
                "fixed_rate": 0.041,
                "estimated_pv01": 20_200,
                "notional_currency": "USD",
                "is_notional_capped": "false",
                "platform_identifier": "BGCD",
                "cleared": "Cleared",
                "package_indicator": False,
                "package_transaction_spread": None,
                "matched_ust_maturity": False,
                "is_mac": False,
                "is_spreadover": False,
                "is_asset_swap": False,
            },
            {
                "trade_id": "T-CURVE-1",
                "package_id": "PKG-CURVE",
                "package_type": "CURVE",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:01:00Z",
                "effective_date": "2026-02-07",
                "expiration_date": "2029-02-07",
                "tenor_years": 3.0,
                "tenor_label": "3Y",
                "forward_start_years": 0.0,
                "forward_label": "spot",
                "is_forward": False,
                "notional": 50_000_000,
                "risk": 15_000,
                "fixed_rate": 0.0415,
                "estimated_pv01": 15_200,
                "notional_currency": "USD",
                "is_notional_capped": "0",
                "platform_identifier": "ISWV",
                "cleared": "Uncleared",
                "package_indicator": True,
                "package_transaction_spread": -0.0005,
                "matched_ust_maturity": False,
                "is_mac": False,
                "is_spreadover": True,
                "is_asset_swap": False,
            },
            {
                "trade_id": "T-CURVE-2",
                "package_id": "PKG-CURVE",
                "package_type": "CURVE",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:01:10Z",
                "effective_date": "2026-02-07",
                "expiration_date": "2031-02-07",
                "tenor_years": 5.0,
                "tenor_label": "5Y",
                "forward_start_years": 0.0,
                "forward_label": "spot",
                "is_forward": False,
                "notional": -50_000_000,
                "risk": -16_000,
                "fixed_rate": 0.0420,
                "estimated_pv01": -16_300,
                "notional_currency": "USD",
                "is_notional_capped": "0",
                "platform_identifier": "ISWV",
                "cleared": "Uncleared",
                "package_indicator": True,
                "package_transaction_spread": -0.0005,
                "matched_ust_maturity": False,
                "is_mac": False,
                "is_spreadover": True,
                "is_asset_swap": False,
            },
            {
                "trade_id": "T-FLY-1",
                "package_id": "PKG-FLY",
                "package_type": "FLY",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:02:00Z",
                "effective_date": "2026-02-07",
                "expiration_date": "2030-02-07",
                "tenor_years": 4.0,
                "tenor_label": "4Y",
                "forward_start_years": 0.0,
                "forward_label": "spot",
                "is_forward": False,
                "notional": 25_000_000,
                "risk": 8_000,
                "fixed_rate": 0.0412,
                "estimated_pv01": 8_100,
                "notional_currency": "USD",
                "is_notional_capped": "no",
                "platform_identifier": "TPSE",
                "cleared": "Cleared",
                "package_indicator": True,
                "package_transaction_spread": 0.0,
                "matched_ust_maturity": False,
                "is_mac": True,
                "is_spreadover": False,
                "is_asset_swap": False,
            },
            {
                "trade_id": "T-FLY-2",
                "package_id": "PKG-FLY",
                "package_type": "FLY",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:02:07Z",
                "effective_date": "2026-02-07",
                "expiration_date": "2031-02-07",
                "tenor_years": 5.0,
                "tenor_label": "5Y",
                "forward_start_years": 0.0,
                "forward_label": "spot",
                "is_forward": False,
                "notional": -50_000_000,
                "risk": -16_000,
                "fixed_rate": 0.0418,
                "estimated_pv01": -16_300,
                "notional_currency": "USD",
                "is_notional_capped": "no",
                "platform_identifier": "TPSE",
                "cleared": "Cleared",
                "package_indicator": True,
                "package_transaction_spread": 0.0,
                "matched_ust_maturity": False,
                "is_mac": True,
                "is_spreadover": False,
                "is_asset_swap": False,
            },
            {
                "trade_id": "T-FLY-3",
                "package_id": "PKG-FLY",
                "package_type": "FLY",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:02:12Z",
                "effective_date": "2026-02-07",
                "expiration_date": "2032-02-07",
                "tenor_years": 6.0,
                "tenor_label": "6Y",
                "forward_start_years": 0.0,
                "forward_label": "spot",
                "is_forward": False,
                "notional": 25_000_000,
                "risk": 8_500,
                "fixed_rate": 0.0421,
                "estimated_pv01": 8_800,
                "notional_currency": "USD",
                "is_notional_capped": "no",
                "platform_identifier": "TPSE",
                "cleared": "Cleared",
                "package_indicator": True,
                "package_transaction_spread": 0.0,
                "matched_ust_maturity": False,
                "is_mac": True,
                "is_spreadover": False,
                "is_asset_swap": False,
            },
            {
                "trade_id": "T-MM-1",
                "package_id": "PKG-MM",
                "package_type": "MATCHED_MATURITY",
                "event_action": "NEWT-TRAD",
                "execution_timestamp": "2026-02-05T14:03:00Z",
                "effective_date": "2026-03-01",
                "expiration_date": "2036-03-01",
                "tenor_years": 10.0,
                "tenor_label": "10Y",
                "forward_start_years": 0.1,
                "forward_label": "1M",
                "is_forward": True,
                "notional": 200_000_000,
                "risk": 55_000,
                "fixed_rate": 0.043,
                "estimated_pv01": 55_400,
                "notional_currency": "USD",
                "is_notional_capped": "yes",
                "platform_identifier": "BGCD",
                "cleared": "Cleared",
                "package_indicator": True,
                "package_transaction_spread": 0.0002,
                "matched_ust_maturity": True,
                "matched_ust_maturity_trade_confidence": "high",
                "invoice_swap_ticker": "TUH6",
                "ust_cusip": "91282CLZ0",
                "swap_maturity_date": "2036-03-01",
                "is_mac": False,
                "is_spreadover": False,
                "is_asset_swap": True,
            },
        ]
    )


def test_normalize_dataframe_coerces_dates_timestamps_and_flags():
    df = normalize_dataframe(_sample_raw_df())
    assert str(df.loc[0, "execution_timestamp"].tz) == "UTC"
    assert str(df.loc[0, "effective_date"]) == "2026-02-07"
    assert bool(df.loc[0, "is_notional_capped"]) is False
    assert bool(df.loc[6, "is_notional_capped"]) is True
    assert df.loc[0, "cleared"] == "Cleared"


def test_package_aggregation_for_outright_curve_fly_and_matched_maturity():
    df = normalize_dataframe(_sample_raw_df())
    packages = build_packages_dataframe(df)
    assert set(packages["package_type"]) == {
        "OUTRIGHT",
        "CURVE",
        "FLY",
        "MATCHED_MATURITY",
    }
    curve_row = packages.loc[packages["package_id"] == "PKG-CURVE"].iloc[0]
    assert curve_row["legs_count"] == 2
    assert curve_row["total_notional"] == 0.0
    assert curve_row["gross_notional"] == 100_000_000.0
    fly_row = packages.loc[packages["package_id"] == "PKG-FLY"].iloc[0]
    assert fly_row["legs_count"] == 3
    assert fly_row["gross_notional"] == 100_000_000.0


def test_package_metrics_include_swaps_expected_keys():
    df = normalize_dataframe(_sample_raw_df())
    mm_group = df.loc[df["package_id"] == "PKG-MM"]
    metrics = build_package_metrics("MATCHED_MATURITY", mm_group)
    assert "package_trade_ids" in metrics
    assert "platform_set" in metrics
    assert metrics["matched_ust_any"] is True
    assert metrics["is_asset_swap_any"] is True
    assert metrics["invoice_swap_tickers"] == ["TUH6"]
    assert metrics["risk_mean"] == 55_000.0


def test_legs_dataframe_sets_manual_link_defaults_and_flags():
    df = normalize_dataframe(_sample_raw_df())
    legs = build_legs_dataframe(df)
    assert len(legs) == len(df)
    assert legs["manual_link_id"].isna().all()
    assert (legs["is_manually_linked"] == False).all()  # noqa: E712
    mm_leg = legs.loc[legs["trade_id"] == "T-MM-1"].iloc[0]
    assert bool(mm_leg["matched_ust_maturity"]) is True
    assert bool(mm_leg["is_asset_swap"]) is True


def test_to_db_value_converts_nat_and_nan_to_none():
    assert to_db_value(pd.NaT) is None
    assert to_db_value(np.nan) is None
    assert to_db_value("NaT") is None
