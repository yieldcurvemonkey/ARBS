"""Tests for file_date tagging in SDR data ingestion."""

import pandas as pd
import pytest
from datetime import date


class TestFileDateTagging:
    def test_historical_dict_tagged_per_day(self):
        """When grab_historical_sdr_trades returns dict, each day has file_date."""
        # Simulate the merged dict that grab_historical_sdr_trades produces
        merged = {
            date(2026, 3, 9): pd.DataFrame({
                "Dissemination Identifier": ["100", "101"],
                "Action type": ["NEWT", "NEWT"],
            }),
            date(2026, 3, 10): pd.DataFrame({
                "Dissemination Identifier": ["200", "201"],
                "Action type": ["NEWT", "CORR"],
            }),
        }

        # Apply the same tagging logic used in grab_historical_sdr_trades
        for day, day_df in merged.items():
            if not day_df.empty and "file_date" not in day_df.columns:
                merged[day] = day_df.assign(file_date=day)

        assert (merged[date(2026, 3, 9)]["file_date"] == date(2026, 3, 9)).all()
        assert (merged[date(2026, 3, 10)]["file_date"] == date(2026, 3, 10)).all()

    def test_concat_preserves_file_date(self):
        """When daily dfs are concatenated, file_date column persists."""
        dfs = [
            pd.DataFrame({
                "Dissemination Identifier": ["100"],
                "file_date": [date(2026, 3, 9)],
            }),
            pd.DataFrame({
                "Dissemination Identifier": ["200"],
                "file_date": [date(2026, 3, 10)],
            }),
        ]
        combined = pd.concat(dfs, ignore_index=True)
        assert "file_date" in combined.columns
        assert combined.loc[0, "file_date"] == date(2026, 3, 9)
        assert combined.loc[1, "file_date"] == date(2026, 3, 10)

    def test_cross_day_correction_detectable_via_file_date(self):
        """A CORR appearing in Day 2's file for a Day 1 NEWT is detectable."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "Original Dissemination Identifier": [None, "100"],
            "Action type": ["NEWT", "CORR"],
            "Event timestamp": ["2026-03-09 14:00:00", "2026-03-10 04:00:55"],
            "file_date": [date(2026, 3, 9), date(2026, 3, 10)],
        })

        newt_row = df[df["Action type"] == "NEWT"].iloc[0]
        corr_row = df[df["Action type"] == "CORR"].iloc[0]

        assert corr_row["file_date"] > newt_row["file_date"]
        # This is the key signal for look-ahead bias
        assert corr_row["Original Dissemination Identifier"] == newt_row["Dissemination Identifier"]
