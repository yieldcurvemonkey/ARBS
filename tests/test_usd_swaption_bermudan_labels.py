import pandas as pd
import pytest

from SDRUtils.products._swaptions import upi as upi_mod


def _mock_ref(
    *,
    upi: str = "TEST-UPI",
    option_type: str = "CALL",
    exercise_style: str = "BERM",
    delivery_type: str = "CASH",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "swaption_Identifier_UPI": upi,
                "swaption_Attributes_OptionType": option_type,
                "swaption_Attributes_OptionExerciseStyle": exercise_style,
                "swaption_Derived_CFIDeliveryType": delivery_type,
                "swap_Attributes_ReferenceRate": "USD-SOFR-COMPOUND",
                "swap_Attributes_ReferenceRateTermValue": "1",
                "swap_Attributes_ReferenceRateTermUnit": "DAY",
                "swap_Attributes_NotionalSchedule": "CONSTANT",
            }
        ]
    )


def _trade_row(**overrides) -> pd.Series:
    row = {
        "Unique Product Identifier": "TEST-UPI",
        "UPI FISN": "NA/O Call Brm Fxd Flt USD",
        "Notional currency-Leg 1": "USD",
        "Execution Timestamp": "2026-03-02 17:08:14+00:00",
        "Effective Date": "2026-03-02",
        "First exercise date": "2026-09-10",
        "Expiration Date": "2031-02-10",
        "Maturity date of the underlier": "2031-03-17",
        "Floating rate reset frequency period-leg 1": "MNTH",
        "Floating rate reset frequency period multiplier-leg 1": "1.0",
        "Fixed rate-Leg 2": "0.041",
    }
    row.update(overrides)
    return pd.Series(row)


def _build_desc(monkeypatch, *, ref_df: pd.DataFrame, trade_overrides: dict | None = None) -> str:
    monkeypatch.setattr(upi_mod, "_build_upi_df", lambda base_dir=None: ref_df.copy())
    desc_fn = upi_mod.make_swaption_desc_func()
    return desc_fn(_trade_row(**(trade_overrides or {})))


def test_bermudan_label_uses_nc_freq_and_absolute_strike(monkeypatch):
    desc = _build_desc(monkeypatch, ref_df=_mock_ref())
    assert desc == "USD-SOFR-COMPOUND 1D Constant 6Mnc4Y5Mx1M BERM MTHLY CASH PAYER 4.10%"


@pytest.mark.parametrize(
    ("period", "mult", "expected"),
    [
        ("MNTH", "3.0", "QTRLY"),
        ("MNTH", "6.0", "SANN"),
        ("YEAR", "1.0", "ANN"),
    ],
)
def test_bermudan_exercise_frequency_mapping(monkeypatch, period, mult, expected):
    desc = _build_desc(
        monkeypatch,
        ref_df=_mock_ref(),
        trade_overrides={
            "Floating rate reset frequency period-leg 1": period,
            "Floating rate reset frequency period multiplier-leg 1": mult,
        },
    )
    assert f"BERM {expected} CASH PAYER" in desc


def test_bermudan_direction_uses_fisn_call_put_mapping(monkeypatch):
    desc = _build_desc(
        monkeypatch,
        ref_df=_mock_ref(option_type="CALL"),
        trade_overrides={
            "UPI FISN": "NA/O Put Brm Fxd Flt USD",
            "Fixed rate-Leg 2": "0.03625",
        },
    )
    assert desc.endswith("RECEIVER 3.625%")


def test_bermudan_tail_uses_month_tenor_not_imm(monkeypatch):
    desc = _build_desc(monkeypatch, ref_df=_mock_ref())
    assert "IMM_" not in desc
    assert "x1M" in desc


def test_forward_starting_bermudan_uses_effective_to_first_exercise_for_nc(monkeypatch):
    desc = _build_desc(
        monkeypatch,
        ref_df=_mock_ref(),
        trade_overrides={
            "Execution Timestamp": "2026-01-02 15:00:00+00:00",
            "Effective Date": "2026-07-01",
            "First exercise date": "2027-01-01",
            "Expiration Date": "2030-01-01",
            "Maturity date of the underlier": "2031-01-01",
            "Fixed rate-Leg 2": "0.0403",
        },
    )
    assert "6Mnc3Yx1Y" in desc

