"""Phase 5 cross-cutting structural tests.

Covers B10 (schedule truncation), H7 (collateral required), M1 (cap band
violation), M2 (partial-unwind delta), M3 (UFRO/UWIN/PEXH separation),
M4 (D2 validation), N4 (frequency anomaly).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from SDRUtils.core.cap_bands import cap_for_tenor, validate_cap_band
from SDRUtils.core.collateral_required import (
    COLLATERAL_REQUIRED_FIELDS,
    missing_required_fields,
)
from SDRUtils.core.frequency_anomaly import is_frequency_anomaly
from SDRUtils.core.lifecycle import validate_d2_chain
from SDRUtils.core.lifecycle_v2 import (
    LifecycleEvent,
    compute_event_deltas,
)
from SDRUtils.core.other_payments import categorize_other_payment
from SDRUtils.core.rc_timeline import build_rc_timeline
from SDRUtils.core.schedule_model import extract_schedule


class TestScheduleModel:
    def test_ten_step_schedule_truncated(self):
        notional_cell = "10000000;9000000;8000000;7000000;6000000;5000000;4000000;3000000;2000000;1000000"
        date_cell = "2026-06-30;2026-12-31;2027-06-30;2027-12-31;2028-06-30;2028-12-29;2029-06-29;2029-12-31;2030-06-28;2030-12-31"
        info = extract_schedule(notional_cell, date_cell)
        assert info.row_count == 10
        assert info.truncated is True
        assert len(info.notional_series) == 10

    def test_short_schedule_not_truncated(self):
        info = extract_schedule("10000000;5000000", "2026-06-30;2027-06-30")
        assert info.row_count == 2
        assert info.truncated is False

    def test_empty_schedule(self):
        info = extract_schedule("", "")
        assert info.row_count == 0
        assert info.truncated is False


class TestCollateralRequired:
    def test_prc1_missing_vm_pre_haircut(self):
        row = pd.Series(
            {
                "Collateralisation category": "PRC1",
                "Initial margin posted by the reporting counterparty (pre-haircut)": None,
                "Variation margin posted by the reporting counterparty (pre-haircut)": None,
            }
        )
        missing = missing_required_fields(row)
        assert (
            "Variation margin posted by the reporting counterparty (pre-haircut)"
            in missing
        )

    def test_uncl_no_requirements(self):
        row = pd.Series({"Collateralisation category": "UNCL"})
        assert missing_required_fields(row) == []

    def test_narr_no_validation(self):
        row = pd.Series({"Collateralisation category": "NARR"})
        assert missing_required_fields(row) == []

    def test_flcl_expects_im_and_vm_both_sides(self):
        row = pd.Series(
            {
                "Collateralisation category": "FLCL",
                "Initial margin posted by the reporting counterparty (pre-haircut)": 100,
                "Variation margin posted by the reporting counterparty (pre-haircut)": 50,
                # collected missing
            }
        )
        missing = missing_required_fields(row)
        assert any("collected" in m for m in missing)


class TestCapBands:
    def test_cap_for_tenor_schedule(self):
        assert cap_for_tenor(1.0) == 250_000_000.0
        assert cap_for_tenor(5.0) == 100_000_000.0
        assert cap_for_tenor(20.0) == 75_000_000.0
        assert cap_for_tenor(35.0) == 75_000_000.0

    def test_3y_capped_at_500m_violates(self):
        # 2–10Y cap is $100M; $500M capped exceeds it
        assert validate_cap_band(500_000_000, 3.0, is_capped=True) is True

    def test_uncapped_no_violation(self):
        assert validate_cap_band(500_000_000, 3.0, is_capped=False) is False

    def test_within_cap_no_violation(self):
        assert validate_cap_band(100_000_000, 3.0, is_capped=True) is False


class TestPartialUnwindDeltas:
    def _evt(self, action: str, notional_delta: float | None = None):
        now = datetime(2026, 3, 9, 14, 0, 0)
        changed = (
            {"Notional amount-Leg 1": notional_delta}
            if notional_delta is not None
            else {}
        )
        return LifecycleEvent(
            action_type=action,
            event_type="TRAD",
            amendment_indicator=None,
            event_timestamp=now,
            execution_timestamp=now,
            dissemination_id="D1",
            original_dissemination_id=None,
            file_date=now.date(),
            changed_economics=changed,
        )

    def test_newt_plus_two_modis_per_step_delta(self):
        # NEWT 10M + MODI(7M) + MODI(5M) -> deltas [0, -3M, -2M]
        chain = [
            self._evt("NEWT", 10_000_000),
            self._evt("MODI", 7_000_000),
            self._evt("MODI", 5_000_000),
        ]
        deltas = compute_event_deltas(chain)
        assert deltas == [0.0, -3_000_000.0, -2_000_000.0]


class TestOtherPayments:
    def test_ufro_vs_uwin_separation(self):
        ufro = categorize_other_payment(1000, "UFRO")
        assert ufro["UFRO"] == 1000.0
        assert ufro["UWIN"] == 0.0
        uwin = categorize_other_payment(2000, "UWIN")
        assert uwin["UWIN"] == 2000.0
        assert uwin["UFRO"] == 0.0
        pexh = categorize_other_payment(500, "PEXH")
        assert pexh["PEXH"] == 500.0

    def test_unknown_type_returns_zeros(self):
        out = categorize_other_payment(1000, "WAT")
        assert all(v == 0.0 for v in out.values())


class TestD2Validation:
    def test_corr_null_d2_flags(self):
        df = pd.DataFrame(
            {
                "Action type": ["CORR"],
                "Original Dissemination Identifier": [None],
            }
        )
        out = validate_d2_chain(df)
        assert bool(out.iloc[0]["d2_missing"]) is True

    def test_corr_with_d2_no_violation(self):
        df = pd.DataFrame(
            {
                "Action type": ["CORR"],
                "Original Dissemination Identifier": ["D123"],
            }
        )
        out = validate_d2_chain(df)
        assert bool(out.iloc[0]["d2_missing"]) is False

    def test_newt_null_d2_allowed(self):
        df = pd.DataFrame(
            {
                "Action type": ["NEWT"],
                "Original Dissemination Identifier": [None],
            }
        )
        out = validate_d2_chain(df)
        assert bool(out.iloc[0]["d2_missing"]) is False

    def test_modi_amend_false_null_d2_allowed(self):
        df = pd.DataFrame(
            {
                "Action type": ["MODI"],
                "Amendment indicator": ["FALSE"],
                "Original Dissemination Identifier": [None],
            }
        )
        out = validate_d2_chain(df)
        assert bool(out.iloc[0]["d2_missing"]) is False

    def test_modi_amend_true_null_d2_flags(self):
        df = pd.DataFrame(
            {
                "Action type": ["MODI"],
                "Amendment indicator": ["TRUE"],
                "Original Dissemination Identifier": [None],
            }
        )
        out = validate_d2_chain(df)
        assert bool(out.iloc[0]["d2_missing"]) is True


class TestFrequencyAnomaly:
    def test_sofr_ois_yearly_reset_anomaly(self):
        assert is_frequency_anomaly("USD-SOFR-COMPOUND", "1Y") is True

    def test_sofr_ois_daily_reset_normal(self):
        assert is_frequency_anomaly("USD-SOFR-COMPOUND", "1D") is False

    def test_non_ois_yearly_not_anomaly(self):
        assert is_frequency_anomaly("USD-LIBOR-3M", "1Y") is False

    def test_missing_inputs_safe(self):
        assert is_frequency_anomaly(None, "1Y") is False
        assert is_frequency_anomaly("USD-SOFR-COMPOUND", None) is False


class TestRcTimeline:
    def test_single_rc_one_entry(self):
        df = pd.DataFrame(
            {
                "event_timestamp": pd.to_datetime(
                    [
                        "2026-03-09 14:00:00+00:00",
                        "2026-03-09 15:00:00+00:00",
                    ]
                ),
                "Reporting counterparty ID": ["RC_ALPHA", "RC_ALPHA"],
            }
        )
        timeline = build_rc_timeline(df)
        assert len(timeline) == 1
        assert timeline[0][1] == "RC_ALPHA"

    def test_rc_change_produces_two_entries(self):
        df = pd.DataFrame(
            {
                "event_timestamp": pd.to_datetime(
                    [
                        "2026-03-09 14:00:00+00:00",
                        "2026-03-09 16:00:00+00:00",
                    ]
                ),
                "Reporting counterparty ID": ["RC_ALPHA", "RC_BETA"],
            }
        )
        timeline = build_rc_timeline(df)
        assert len(timeline) == 2
        assert timeline[0][1] == "RC_ALPHA"
        assert timeline[1][1] == "RC_BETA"
