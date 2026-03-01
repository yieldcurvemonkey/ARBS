import pandas as pd

from SDRUtils.packages.swaption.delta_hedge import detect_delta_hedge_packages
from SDRUtils.products._swaps.filters import (
    is_usd_swap,
    new_sofr_swap_trades,
    new_usd_swap_trades,
)
from SDRUtils.products.usd import (
    USD_SOFR_SwapProduct,
    USD_SwapProduct,
    classify_sofr_swap_trade,
    classify_usd_swap_trade,
)
from SDRUtils.products.usd.usd_swaptions import _backfill_swaption_fields


def test_usd_swap_filter_expands_to_usd_ois_and_fixed_float():
    df = pd.DataFrame(
        [
            {
                "trade_id": "SOFR",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "UPI FISN": "NA/Swap OIS USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
            {
                "trade_id": "FEDFUNDS",
                "UPI Underlier Name": "USD-Federal Funds-H.15-OIS Compound",
                "UPI FISN": "NA/Swap OIS USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
            {
                "trade_id": "TERMSOFR",
                "UPI Underlier Name": "USD-SOFR CME Term",
                "UPI FISN": "NA/Swap Fxd Flt USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
            {
                "trade_id": "ICESOFR",
                "UPI Underlier Name": "USD-SOFR ICE Swap Rate",
                "UPI FISN": "NA/Swap Fxd Flt USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
            {
                "trade_id": "BSBY",
                "UPI Underlier Name": "USD-BSBY",
                "UPI FISN": "NA/Swap Fxd Flt USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
            {
                "trade_id": "LIBOR",
                "UPI Underlier Name": "USD-LIBOR-BBA",
                "UPI FISN": "NA/Swap Fxd Flt USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
            {
                "trade_id": "XCCY",
                "UPI Underlier Name": "EUR-EURIBOR-3M",
                "UPI FISN": "NA/Swap Ccy EUR USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "EUR",
            },
            {
                "trade_id": "INFL",
                "UPI Underlier Name": "USD-CPI",
                "UPI FISN": "NA/Swap Infl Idx USD",
                "Action type": "NEWT",
                "Notional currency-Leg 1": "USD",
            },
        ]
    )

    out = new_usd_swap_trades(df)
    assert set(out["trade_id"]) == {"SOFR", "FEDFUNDS", "TERMSOFR", "ICESOFR", "BSBY", "LIBOR"}

    # Legacy SOFR wrapper keeps narrow SOFR behavior by default.
    legacy = new_sofr_swap_trades(df, include_misc=False)
    assert set(legacy["trade_id"]) == {"SOFR"}

    assert is_usd_swap(df.iloc[1])
    assert not is_usd_swap(df.iloc[6])


def test_usd_swap_alias_exports_remain_available():
    assert USD_SOFR_SwapProduct is USD_SwapProduct
    assert callable(classify_usd_swap_trade)
    assert callable(classify_sofr_swap_trade)


def test_swaption_backfill_sets_schedule_and_bespoke_fields():
    package_df = pd.DataFrame(
        [
            {
                "description": "USD-SOFR-OIS Compound 1D Custom 1Yx10Y PAYER EURO VANILLA PHYS",
                "trade_label": None,
                "upi_underlier_name": "USD-SOFR-OIS Compound",
                "upi_fisn": "NA/O P EUR",
                "action_type": "NEWT",
                "event_type": "TRAD",
            },
            {
                "description": "USD-Federal Funds-H.15-OIS Compound 1D Constant 1Yx5Y RECEIVER EURO VANILLA PHYS",
                "trade_label": "USD-Federal Funds-H.15-OIS Compound 1D 1Yx5Y RECEIVER EURO VANILLA PHYS",
                "upi_underlier_name": "USD-Federal Funds-H.15-OIS Compound",
                "upi_fisn": "NA/O P EUR",
                "action_type": "NEWT",
                "event_type": "TRAD",
            },
        ]
    )

    out = _backfill_swaption_fields(package_df)
    assert out.loc[0, "underlier_schedule"] == "CUSTOM"
    assert bool(out.loc[0, "is_bespoke_underlier"]) is True
    assert "CUSTOM" in str(out.loc[0, "trade_label"]).upper()

    assert out.loc[1, "underlier_schedule"] == "CONSTANT"
    assert bool(out.loc[1, "is_bespoke_underlier"]) is False
    assert "CONSTANT" in str(out.loc[1, "trade_label"]).upper()


def test_delta_hedge_matches_only_same_underlier_family_and_skips_non_sofr_dv01():
    ts = pd.Timestamp("2026-02-10 15:00:00", tz="UTC")
    swaptions = pd.DataFrame(
        [
            {
                "trade_id": "SWPT-FF",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": ts,
                "platform_identifier": "BILT",
                "notional_currency": "USD",
                "upi_underlier_name": "USD-Federal Funds-H.15-OIS Compound",
                "trade_label": "USD-Federal Funds-H.15-OIS Compound 1D Constant 1Yx5Y PAYER EURO VANILLA PHYS",
                "notional": 100_000_000,
                "strike": 0.04,
                "tenor_years": 5.0,
                "forward_start_years": 1.0,
                "premium": 125_000.0,
                "package_indicator": True,
                "exercise_style": "EUROPEAN",
                "expiration_date": pd.Timestamp("2027-02-10"),
                "underlying_expiration_date": pd.Timestamp("2032-02-10"),
                "package_id": None,
                "package_type": "SWAPTION",
            }
        ]
    )
    swaps = pd.DataFrame(
        [
            {
                "Dissemination Identifier": "SWAP-SOFR",
                "Event timestamp": ts + pd.Timedelta(seconds=1),
                "Effective Date": "2027-02-10",
                "Maturity date of the underlier": "2032-02-10",
                "Notional amount-Leg 1": "50,000,000",
                "Fixed rate-Leg 1": 0.0401,
                "Platform identifier": "BILT",
                "Package indicator": True,
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
            },
            {
                "Dissemination Identifier": "SWAP-FF",
                "Event timestamp": ts + pd.Timedelta(seconds=2),
                "Effective Date": "2027-02-10",
                "Maturity date of the underlier": "2032-02-10",
                "Notional amount-Leg 1": "50,000,000",
                "Fixed rate-Leg 1": 0.0401,
                "Platform identifier": "BILT",
                "Package indicator": True,
                "UPI Underlier Name": "USD-Federal Funds-H.15-OIS Compound",
            },
        ]
    )

    out = detect_delta_hedge_packages(
        swaptions,
        swaps,
        pricer=object(),
        check_dv01=True,
    )
    row = out.iloc[0]
    assert row["delta_hedge_swap_trade_id"] == "SWAP-FF"
    assert row["delta_hedge_dv01_check"] == "SKIP"
