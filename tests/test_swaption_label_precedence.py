import datetime
import sys
import types

import pandas as pd

from SDRUtils.core.tenors import forward_to_label, get_imm_label, get_special_label, tenor_from_dates
from SDRUtils.products._swaptions import upi as upi_mod


def _mock_ref(
    *,
    upi: str = "TEST-UPI",
    option_type: str = "CALL",
    exercise_style: str = "EURO",
    delivery_type: str = "PHYS",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "swaption_Identifier_UPI": upi,
                "swaption_Attributes_OptionType": option_type,
                "swaption_Attributes_OptionExerciseStyle": exercise_style,
                "swaption_Derived_CFIDeliveryType": delivery_type,
                "swap_Attributes_ReferenceRate": "USD-SOFR-OIS Compound",
                "swap_Attributes_ReferenceRateTermValue": "1",
                "swap_Attributes_ReferenceRateTermUnit": "DAY",
                "swap_Attributes_NotionalSchedule": "CONSTANT",
            }
        ]
    )


def _trade_row(**overrides) -> pd.Series:
    row = {
        "Unique Product Identifier": "TEST-UPI",
        "UPI FISN": "NA/O Call Epn Fxd Flt USD",
        "Notional currency-Leg 1": "USD",
        "Execution Timestamp": "2026-03-09 12:53:42+00:00",
        "Effective Date": "2026-03-09",
        "Expiration Date": "2026-06-09",
        "Maturity date of the underlier": "2027-06-11",
        "First exercise date": pd.NaT,
    }
    row.update(overrides)
    return pd.Series(row)


def _build_desc(monkeypatch, *, ref_df: pd.DataFrame, trade_overrides: dict | None = None) -> str:
    monkeypatch.setattr(upi_mod, "_build_upi_df", lambda base_dir=None: ref_df.copy())
    desc_fn = upi_mod.make_swaption_desc_func()
    return desc_fn(_trade_row(**(trade_overrides or {})))


def test_get_imm_label_requires_exact_date():
    assert get_imm_label(pd.Timestamp("2026-06-17")) == "IMM_M2026"
    # tolerance_days=1 is now the default; use 0 to require exact match
    assert get_imm_label(pd.Timestamp("2026-06-16"), tolerance_days=0) is None
    # within 7-day tolerance, June 16 matches IMM June 17
    assert get_imm_label(pd.Timestamp("2026-06-16"), tolerance_days=7) == "IMM_M2026"
    assert get_special_label(pd.Timestamp("2027-06-11")) is None


def test_tenor_from_dates_prefers_constant_maturity_over_nearby_imm():
    assert tenor_from_dates(pd.Timestamp("2026-06-09"), pd.Timestamp("2027-06-11")) == "1Y"
    assert tenor_from_dates(pd.Timestamp("2036-03-10"), pd.Timestamp("2056-03-12")) == "20Y"


def test_forward_to_label_uses_exact_special_date_only_when_not_constant_maturity(monkeypatch):
    stub = types.SimpleNamespace(
        _CENTRAL_BANK_DATES={
            "USD-FEDFUNDS": {
                "meeting": (datetime.date(2026, 4, 1), datetime.date(2026, 4, 2)),
            }
        }
    )
    monkeypatch.setitem(sys.modules, "Query.IRSwaps._CENTRAL_BANK_DATES", stub)

    assert forward_to_label(44 / 365, pd.Timestamp("2026-04-01"), True) == "FOMC_20260401"
    assert forward_to_label(0.0, pd.Timestamp("2026-04-01"), False) == "spot"
    assert forward_to_label(100 / 365, pd.Timestamp("2026-06-17"), True) == "IMM_M2026"


def test_swaption_desc_uses_constant_maturity_labels_before_imm(monkeypatch):
    desc = _build_desc(monkeypatch, ref_df=_mock_ref(option_type="PUT"), trade_overrides={"UPI FISN": "NA/O Put Epn Fxd Flt USD"})
    assert "3Mx1Y" in desc
    assert "IMM_" not in desc

    long_desc = _build_desc(
        monkeypatch,
        ref_df=_mock_ref(option_type="PUT"),
        trade_overrides={
            "UPI FISN": "NA/O Put Epn Fxd Flt USD",
            "Expiration Date": "2036-03-10",
            "Maturity date of the underlier": "2056-03-12",
        },
    )
    assert "10Yx20Y" in long_desc
    assert "IMM_" not in long_desc
