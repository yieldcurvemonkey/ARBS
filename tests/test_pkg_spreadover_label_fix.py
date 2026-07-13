"""Regression tests for PKG-N + spreadover label/grouping bugs (2026-07-13).

Bug 1-3: PKG-N packages whose legs have is_spreadover=True incorrectly
         rendered "Spreadover" in the tape_label instead of compact "PKG-N".
Bug 4:   Four spreadover legs (10Y,10Y,30Y,30Y) sharing PTS were over-grouped
         into a single PKG-4 instead of two separate SPREADOVER_CURVE packages.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from SDRUtils.analytics.flow import assign_trade_type
from SDRUtils.analytics.trade_tape import TradeTape
from SDRUtils.packages.ptp_grouper import classify_ptp_groups


# ---------------------------------------------------------------------------
# Bug 1-3: assign_trade_type must NOT return SPREADOVER for PKG-N
# ---------------------------------------------------------------------------

class TestAssignTradeTypePkgN:
    def test_pkg2_with_is_spreadover_returns_outright(self):
        row = pd.Series({
            "package_type": "PKG-2",
            "is_spreadover": True,
            "special_tenor_type": "STANDARD",
        })
        assert assign_trade_type(row) == "OUTRIGHT"

    def test_pkg3_with_is_spreadover_returns_outright(self):
        row = pd.Series({
            "package_type": "PKG-3",
            "is_spreadover": True,
            "special_tenor_type": "STANDARD",
        })
        assert assign_trade_type(row) == "OUTRIGHT"

    def test_pkg4_returns_outright(self):
        row = pd.Series({
            "package_type": "PKG-4",
            "is_spreadover": False,
            "special_tenor_type": "STANDARD",
        })
        assert assign_trade_type(row) == "OUTRIGHT"

    def test_spreadover_curve_still_passes_through(self):
        row = pd.Series({
            "package_type": "SPREADOVER_CURVE",
            "is_spreadover": True,
            "special_tenor_type": "STANDARD",
        })
        assert assign_trade_type(row) == "SPREADOVER_CURVE"

    def test_standalone_spreadover_still_works(self):
        row = pd.Series({
            "package_type": "SPREADOVER",
            "is_spreadover": True,
            "special_tenor_type": "STANDARD",
        })
        assert assign_trade_type(row) == "SPREADOVER"


# ---------------------------------------------------------------------------
# Bug 1-3: PKG-2 tape_label must show compact "PKG-2" not tenors+Spreadover
# ---------------------------------------------------------------------------

class TestPkgNCompactLabel:
    def _make_pkg_n_df(self, n_legs, tenors, forward="spot"):
        tids = [f"T{i}" for i in range(n_legs)]
        rows = []
        for i, (ty, td) in enumerate(tenors):
            rows.append({
                "trade_id": tids[i],
                "tenor_years": ty,
                "tenor_display": td,
                "tenor_label": td,
                "forward_label": forward,
                "forward_start_years": 0.0,
                "package_type": f"PKG-{n_legs}",
                "package_id": "P1",
                "package_legs": tids,
                "package_indicator": True,
                "is_package": True,
                "n_package_legs": n_legs,
                "product_type": "OIS_SWAP",
                "trade_type": "OUTRIGHT",
                "is_spreadover": True,
                "upi_underlier_name": "USD-SOFR-COMPOUND",
                "upi_reset_freq": "1D",
                "upi_notional_schedule": "Constant",
                "upi_delivery_type": "PHYS",
                "cleared": "Y",
            })
        return pd.DataFrame(rows)

    def _enrich_label(self, df):
        tape = TradeTape(df=df, raw_df=None)
        out = tape._enrich_packages(df.copy())
        return tape._build_enriched_label(out)

    def test_pkg2_no_spreadover_in_label(self):
        df = self._make_pkg_n_df(2, [(10.0, "10Y"), (30.0, "30Y")])
        out = self._enrich_label(df)
        for i in range(2):
            label = out.loc[i, "tape_label"]
            assert "PKG-2" in label
            assert "Spreadover" not in label
            assert "SPREADOVER" not in label
            assert "10Y/30Y" not in label

    def test_pkg3_no_spreadover_in_label(self):
        df = self._make_pkg_n_df(3, [(2.0, "2Y"), (10.0, "10Y"), (30.0, "30Y")])
        out = self._enrich_label(df)
        label = out.loc[0, "tape_label"]
        assert "PKG-3" in label
        assert "Spreadover" not in label

    def test_pkg2_leg_labels_still_show_outright(self):
        """Leg-scope labels should still show individual tenors + Outright."""
        df = self._make_pkg_n_df(2, [(10.0, "10Y"), (30.0, "30Y")])
        out = self._enrich_label(df)
        leg0 = out.loc[0, "leg_tape_label"]
        assert "10Y" in leg0
        assert "Outright" in leg0
        leg1 = out.loc[1, "leg_tape_label"]
        assert "30Y" in leg1
        assert "Outright" in leg1


# ---------------------------------------------------------------------------
# Bug 4: PTS-keyed groups with duplicate tenors must decompose
# ---------------------------------------------------------------------------

class TestPtsKeyedDecomposition:
    def test_four_legs_two_tenors_pts_keyed_splits_into_curves(self):
        """4 legs (10Y,10Y,30Y,30Y) sharing PTS should split into 2 CURVEs."""
        df = pd.DataFrame([
            {"trade_id": "A1", "tenor_years": 10.0, "estimated_pv01": 82.0,
             "fixed_rate": 0.0417, "forward_start_years": 0.0,
             "ptp_group_id": "PTS_A1", "ptp_group_size": 4},
            {"trade_id": "A2", "tenor_years": 10.0, "estimated_pv01": 40.0,
             "fixed_rate": 0.0417, "forward_start_years": 0.0,
             "ptp_group_id": "PTS_A1", "ptp_group_size": 4},
            {"trade_id": "A3", "tenor_years": 30.0, "estimated_pv01": 84.0,
             "fixed_rate": 0.0433, "forward_start_years": 0.0,
             "ptp_group_id": "PTS_A1", "ptp_group_size": 4},
            {"trade_id": "A4", "tenor_years": 30.0, "estimated_pv01": 40.0,
             "fixed_rate": 0.0433, "forward_start_years": 0.0,
             "ptp_group_id": "PTS_A1", "ptp_group_size": 4},
        ])
        out = classify_ptp_groups(df)
        pkg_types = out["package_type"].unique()
        assert "CURVE" in pkg_types
        assert "PKG-4" not in pkg_types
        pkg_ids = out["package_id"].unique()
        assert len(pkg_ids) == 2

    def test_four_legs_ptp_keyed_stays_unified(self):
        """PTP-keyed groups keep unified PKG-N (same PTP = single execution)."""
        df = pd.DataFrame([
            {"trade_id": "B1", "tenor_years": 10.0, "estimated_pv01": 82.0,
             "fixed_rate": 0.0417, "forward_start_years": 0.0,
             "ptp_group_id": "PTP_B1", "ptp_group_size": 4},
            {"trade_id": "B2", "tenor_years": 10.0, "estimated_pv01": 40.0,
             "fixed_rate": 0.0417, "forward_start_years": 0.0,
             "ptp_group_id": "PTP_B1", "ptp_group_size": 4},
            {"trade_id": "B3", "tenor_years": 30.0, "estimated_pv01": 84.0,
             "fixed_rate": 0.0433, "forward_start_years": 0.0,
             "ptp_group_id": "PTP_B1", "ptp_group_size": 4},
            {"trade_id": "B4", "tenor_years": 30.0, "estimated_pv01": 40.0,
             "fixed_rate": 0.0433, "forward_start_years": 0.0,
             "ptp_group_id": "PTP_B1", "ptp_group_size": 4},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-4").all()
        assert out["package_id"].nunique() == 1
