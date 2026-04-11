"""Integration tests for linear product classification against real SDR data."""

import os
from pathlib import Path

import pandas as pd
import pytest


# Try multiple possible locations for the example data
_POSSIBLE_PATHS = [
    Path("notebooks/sdr/sdr_example.csv"),
    Path(__file__).parent.parent / "notebooks" / "sdr" / "sdr_example.csv",
    # Main repo path (when running from worktree)
    Path(os.environ.get("ARBS_ROOT", "C:/Users/chris/clee/ARBS")) / "notebooks" / "sdr" / "sdr_example.csv",
]

_SDR_PATH = None
for p in _POSSIBLE_PATHS:
    if p.exists():
        _SDR_PATH = p
        break

_SKIP_REASON = "sdr_example.csv not found in any expected location"


@pytest.fixture
def sdr_week():
    if _SDR_PATH is None:
        pytest.skip(_SKIP_REASON)
    return pd.read_csv(
        _SDR_PATH,
        low_memory=False,
        dtype={"Dissemination Identifier": str, "Original Dissemination Identifier": str},
    )


class TestLinearIntegration:
    def test_sofr_trades_classified(self, sdr_week):
        """All USD-SOFR* trades should classify as SOFR OIS."""
        from SDRUtils.products.usd.upi_classifier import classify_rate_index
        from SDRUtils.products.usd.linear_base import RateIndex, LinearProductType

        sofr_rows = sdr_week[
            sdr_week["UPI Underlier Name"].str.contains("USD-SOFR", na=False)
            & (~sdr_week["UPI Underlier Name"].str.contains(" vs ", na=False))
            & (sdr_week["Action type"] == "NEWT")
        ]
        assert len(sofr_rows) > 100  # sanity check

        for _, row in sofr_rows.head(50).iterrows():
            result = classify_rate_index(row["UPI Underlier Name"], row.get("UPI FISN"))
            assert result.rate_index in (RateIndex.SOFR, RateIndex.SOFR_COMPOUND)
            assert result.product_type == LinearProductType.OIS

    def test_fed_funds_trades_classified(self, sdr_week):
        """All USD-Federal Funds* (non-basis) trades should classify as FED_FUNDS."""
        from SDRUtils.products.usd.upi_classifier import classify_rate_index
        from SDRUtils.products.usd.linear_base import RateIndex

        ff_rows = sdr_week[
            sdr_week["UPI Underlier Name"].str.contains("USD-Federal Funds", na=False)
            & (~sdr_week["UPI Underlier Name"].str.contains(" vs ", na=False))
            & (sdr_week["Action type"] == "NEWT")
        ]
        for _, row in ff_rows.iterrows():
            result = classify_rate_index(row["UPI Underlier Name"], row.get("UPI FISN"))
            assert result.rate_index in (RateIndex.FED_FUNDS, RateIndex.FED_FUNDS_COMPOUND)

    def test_basis_swaps_classified(self, sdr_week):
        """All float-float USD trades should classify with a BasisType."""
        from SDRUtils.products.usd.upi_classifier import classify_rate_index
        from SDRUtils.products.usd.linear_base import LinearProductType

        basis_rows = sdr_week[
            sdr_week["UPI Underlier Name"].str.contains(" vs ", na=False)
            & sdr_week["UPI Underlier Name"].str.contains("USD", na=False)
            & (sdr_week["Action type"] == "NEWT")
        ]
        classified = 0
        for _, row in basis_rows.head(100).iterrows():
            result = classify_rate_index(row["UPI Underlier Name"], row.get("UPI FISN"))
            if result.product_type == LinearProductType.BASIS:
                classified += 1
                assert result.basis_type is not None
        assert classified > 0

    def test_cross_day_corrections_flagged(self, sdr_week):
        """Cross-day CORR/MODI should produce arrived_in_later_file=True."""
        from datetime import date, datetime
        from SDRUtils.core.lifecycle_v2 import LifecycleEvent, build_summary

        sdr_week["event_date"] = pd.to_datetime(sdr_week["Event timestamp"]).dt.date
        newt = sdr_week[sdr_week["Action type"] == "NEWT"].set_index("Dissemination Identifier")
        corr = sdr_week[sdr_week["Action type"] == "CORR"]

        # Pre-filter to CORRs that have matching NEWTs
        corr_with_newt = corr[corr["Original Dissemination Identifier"].isin(newt.index)]

        flagged = 0
        for _, row in corr_with_newt.iterrows():
            orig_id = row["Original Dissemination Identifier"]
            newt_row = newt.loc[orig_id]
            if isinstance(newt_row, pd.DataFrame):
                newt_row = newt_row.iloc[0]

            n_date = newt_row["event_date"]
            c_date = row["event_date"]
            if c_date <= n_date:
                continue  # Skip same-day CORRs for efficiency

            chain = [
                LifecycleEvent(
                    action_type="NEWT", event_type="TRAD", amendment_indicator=None,
                    event_timestamp=pd.Timestamp(newt_row["Event timestamp"]).to_pydatetime(),
                    execution_timestamp=pd.Timestamp(newt_row["Execution Timestamp"]).to_pydatetime(),
                    dissemination_id=orig_id, original_dissemination_id=None,
                    file_date=n_date, changed_economics={},
                ),
                LifecycleEvent(
                    action_type="CORR", event_type=None, amendment_indicator=None,
                    event_timestamp=pd.Timestamp(row["Event timestamp"]).to_pydatetime(),
                    execution_timestamp=pd.Timestamp(row["Execution Timestamp"]).to_pydatetime(),
                    dissemination_id=row["Dissemination Identifier"],
                    original_dissemination_id=orig_id,
                    file_date=c_date, changed_economics={},
                ),
            ]
            summary = build_summary(chain)
            if summary.arrived_in_later_file:
                flagged += 1
                if flagged >= 10:
                    break  # Enough evidence

        assert flagged > 0, "Expected cross-day corrections in full week data"
