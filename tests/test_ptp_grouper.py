# tests/test_ptp_grouper.py
"""Tests for PTP-based package pre-grouper."""
import pandas as pd
import pytest

from SDRUtils.packages.ptp_grouper import group_by_ptp


def _make_legs(overrides_list: list[dict]) -> pd.DataFrame:
    """Build a test DataFrame from per-leg overrides."""
    base = {
        "trade_id": "T000",
        "execution_timestamp": pd.Timestamp("2026-06-25 14:30:59", tz="UTC"),
        "package_transaction_price": 88100.0,
        "package_indicator": True,
        "unique_product_identifier": "UPI_SOFR_OIS",
        "platform_identifier": "BBSF",
        "estimated_pv01": 10000.0,
        "tenor_years": 5.0,
        "fixed_rate": 0.04,
        "other_payment_amount": 1000.0,
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
    }
    rows = []
    for i, ov in enumerate(overrides_list):
        row = {**base, "trade_id": f"T{i:03d}", **ov}
        rows.append(row)
    return pd.DataFrame(rows)


class TestGroupByPtp:
    def test_exact_match_groups_two_legs(self):
        df = _make_legs([
            {"tenor_years": 2.0},
            {"tenor_years": 10.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 2
        assert len(non_ptp_df) == 0
        assert ptp_df["ptp_group_id"].nunique() == 1
        assert ptp_df["ptp_group_size"].iloc[0] == 2

    def test_different_ptp_splits_groups(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_transaction_price": 88100.0},
            {"tenor_years": 10.0, "package_transaction_price": 88100.0},
            {"tenor_years": 5.0, "package_transaction_price": 50000.0},
            {"tenor_years": 7.0, "package_transaction_price": 50000.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 4
        assert ptp_df["ptp_group_id"].nunique() == 2

    def test_single_leg_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_transaction_price": 88100.0},
            {"tenor_years": 10.0, "package_transaction_price": 99999.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_null_ptp_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_transaction_price": None},
            {"tenor_years": 10.0, "package_transaction_price": None},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_pkg_indicator_false_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "package_indicator": False},
            {"tenor_years": 10.0, "package_indicator": False},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_time_window_merge(self):
        """Legs 3s apart should group; legs 10s apart should not."""
        t0 = pd.Timestamp("2026-06-25 14:30:59", tz="UTC")
        df = _make_legs([
            {"execution_timestamp": t0},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=3)},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=30)},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=32)},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)
        assert ptp_df["ptp_group_id"].nunique() == 2
        assert len(ptp_df) == 4

    def test_different_upi_splits_groups(self):
        df = _make_legs([
            {"tenor_years": 2.0, "unique_product_identifier": "UPI_A"},
            {"tenor_years": 10.0, "unique_product_identifier": "UPI_B"},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0  # each UPI has only 1 leg → min group 2

    def test_different_platform_splits_groups(self):
        df = _make_legs([
            {"tenor_years": 2.0, "platform_identifier": "BBSF"},
            {"tenor_years": 10.0, "platform_identifier": "TPSF"},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0

    def test_group_id_uses_min_trade_id(self):
        df = _make_legs([
            {"trade_id": "Z999", "tenor_years": 2.0},
            {"trade_id": "A001", "tenor_years": 10.0},
        ])
        ptp_df, _ = group_by_ptp(df)
        assert ptp_df["ptp_group_id"].iloc[0] == "PTP_A001"

    def test_empty_dataframe(self):
        df = _make_legs([])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 0

    def test_twelve_leg_fly_groups_together(self):
        """Real-world: 12 legs, same PTP, same exec_ts → one group."""
        df = _make_legs([{"tenor_years": t, "trade_id": f"T{i:03d}"}
                         for i, t in enumerate([2, 5, 10] * 4)])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 12
        assert ptp_df["ptp_group_id"].nunique() == 1
        assert ptp_df["ptp_group_size"].iloc[0] == 12
