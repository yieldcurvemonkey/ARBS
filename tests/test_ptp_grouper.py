# tests/test_ptp_grouper.py
"""Tests for PTP-based package pre-grouper."""
import pandas as pd
import pytest

from SDRUtils.packages.ptp_grouper import classify_ptp_groups, group_by_ptp


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


class TestGroupByPtpEdgeCases:
    """Audit-added regressions: NaT timestamps, dtype variants, window bridging."""

    def test_nat_execution_timestamp_stays_in_global_pool(self):
        df = _make_legs([
            {"tenor_years": 2.0, "execution_timestamp": pd.NaT},
            {"tenor_years": 10.0, "execution_timestamp": pd.NaT},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 0
        assert len(non_ptp_df) == 2

    def test_float_package_indicator_still_groups(self):
        """package_indicator arriving as float 1.0 (NaN-padded bool col)."""
        df = _make_legs([{"tenor_years": 2.0}, {"tenor_years": 10.0}])
        df["package_indicator"] = pd.Series([1.0, 1.0])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 2

    def test_non_candidate_remainder_group_size_is_none(self):
        df = _make_legs([
            {"package_indicator": False},
            {"package_indicator": False},
        ])
        _, non_ptp_df = group_by_ptp(df)
        assert non_ptp_df["ptp_group_size"].isna().all()

    def test_raw_string_ptp_with_thousands_separator_groups(self):
        """Live-path regression: at detection time PTP arrives as a raw
        DTCC string like '88,100'. pd.to_numeric alone coerces that to
        NaN, which silently dropped every USD-amount package >= $1,000
        from PTP grouping (found in the 2026-07-01 audit)."""
        df = _make_legs([
            {"tenor_years": 2.0}, {"tenor_years": 5.0}, {"tenor_years": 10.0},
        ])
        df["package_transaction_price"] = pd.Series(["88,100", "88,100", "88,100"])
        ptp_df, non_ptp_df = group_by_ptp(df)
        assert len(ptp_df) == 3
        assert ptp_df["ptp_group_id"].nunique() == 1

    def test_unrelated_trade_cannot_bridge_time_window(self):
        """Same-PTP legs 8s apart must not merge just because an unrelated
        different-PTP trade sits between them."""
        t0 = pd.Timestamp("2026-06-25 14:30:00", tz="UTC")
        df = _make_legs([
            {"execution_timestamp": t0, "package_transaction_price": 88100.0},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=4),
             "package_transaction_price": 55555.0},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=8),
             "package_transaction_price": 88100.0},
            {"execution_timestamp": t0 + pd.Timedelta(seconds=4),
             "package_transaction_price": 55555.0},
        ])
        ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)
        # The two 55555 legs at the same second group; the 88100 legs are
        # 8s apart with nothing of their own key in between -> global pool.
        grouped_ptps = set(
            pd.to_numeric(ptp_df["package_transaction_price"]).unique()
        )
        assert grouped_ptps == {55555.0}
        assert len(non_ptp_df) == 2


def _grouped_legs(overrides_list, ptp_group_id="PTP_T000"):
    """Build a PTP-grouped test DataFrame."""
    df = _make_legs(overrides_list)
    df["ptp_group_id"] = ptp_group_id
    df["ptp_group_size"] = len(df)
    return df


class TestClassifyPtpGroups:
    def test_two_leg_curve(self):
        df = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 10000.0},
            {"tenor_years": 10.0, "estimated_pv01": 10000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "CURVE").all()
        assert out["package_id"].iloc[0] == "PTP_T000"
        assert len(out["package_legs"].iloc[0]) == 2

    def test_three_leg_fly(self):
        df = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "FLY").all()

    def test_three_leg_unbalanced_is_pkg3(self):
        df = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 5000.0},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-3").all()

    def test_eight_leg_ladder_is_pkg8(self):
        tenors = [2, 3, 5, 7, 10, 15, 20, 30]
        df = _grouped_legs([
            {"tenor_years": float(t), "estimated_pv01": 1000.0 * t}
            for t in tenors
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-8").all()
        assert out["package_id"].iloc[0] == "PTP_T000"
        assert len(out["package_legs"].iloc[0]) == 8
        assert out["ptp_sub_structures"].iloc[0] == []

    def test_twelve_leg_multi_fly_has_sub_annotations(self):
        legs = []
        for risk_scale in [1.0, 1.8]:
            for rate_offset in [0.0, 0.001]:
                legs.extend([
                    {"tenor_years": 2.0, "estimated_pv01": 5000 * risk_scale,
                     "fixed_rate": 0.0397 + rate_offset},
                    {"tenor_years": 5.0, "estimated_pv01": 10000 * risk_scale,
                     "fixed_rate": 0.0387 + rate_offset},
                    {"tenor_years": 10.0, "estimated_pv01": 5000 * risk_scale,
                     "fixed_rate": 0.0398 + rate_offset},
                ])
        df = _grouped_legs(legs)
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-12").all()
        subs = out["ptp_sub_structures"].iloc[0]
        assert isinstance(subs, list)
        assert len(subs) == 4
        assert all(s["type"] == "FLY" for s in subs)

    def test_two_leg_same_tenor_is_pkg2_not_curve(self):
        """CURVE requires two different tenors (spec) — a balanced
        same-tenor pair is a switch/roll."""
        df = _grouped_legs([
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-2").all()

    def test_three_leg_same_tenor_is_pkg3_not_fly(self):
        df = _grouped_legs([
            {"tenor_years": 5.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
            {"tenor_years": 5.0, "estimated_pv01": 5000.0},
        ])
        out = classify_ptp_groups(df)
        assert (out["package_type"] == "PKG-3").all()

    def test_multiple_groups_classified_independently(self):
        g1 = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 5000.0},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0},
        ], ptp_group_id="PTP_A")
        g2 = _grouped_legs([
            {"tenor_years": 2.0, "estimated_pv01": 1000.0, "package_transaction_price": 50000},
            {"tenor_years": 30.0, "estimated_pv01": 1000.0, "package_transaction_price": 50000},
        ], ptp_group_id="PTP_B")
        df = pd.concat([g1, g2], ignore_index=True)
        out = classify_ptp_groups(df)
        types = out.groupby("ptp_group_id")["package_type"].first()
        assert types["PTP_A"] == "FLY"
        assert types["PTP_B"] == "CURVE"

    def test_sub_flies_use_rounded_tenor_buckets(self):
        """Raw tenors 2.01/2.04 bucket to the same 2.0 — the distinct-tenor
        check must agree with the bucketing (audit observation)."""
        legs = [
            {"tenor_years": 2.01, "estimated_pv01": 5000.0, "trade_id": "T000"},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0, "trade_id": "T001"},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0, "trade_id": "T002"},
            {"tenor_years": 2.04, "estimated_pv01": 5000.0, "trade_id": "T003"},
            {"tenor_years": 5.0, "estimated_pv01": 10000.0, "trade_id": "T004"},
            {"tenor_years": 10.0, "estimated_pv01": 5000.0, "trade_id": "T005"},
        ]
        df = _grouped_legs(legs)
        out = classify_ptp_groups(df)
        subs = out["ptp_sub_structures"].iloc[0]
        assert len(subs) == 2  # was [] because raw-distinct saw 4 tenors

    def test_sub_fly_pairing_keeps_rates_together(self):
        """Two equal-DV01 sub-flies at different rates must not cross-pair
        legs in the annotation."""
        legs = []
        for rate in (0.040, 0.041):
            legs.extend([
                {"tenor_years": 2.0, "estimated_pv01": 5000.0, "fixed_rate": rate},
                {"tenor_years": 5.0, "estimated_pv01": 10000.0, "fixed_rate": rate},
                {"tenor_years": 10.0, "estimated_pv01": 5000.0, "fixed_rate": rate},
            ])
        df = _grouped_legs(legs)
        rates = dict(zip(df["trade_id"], df["fixed_rate"]))
        out = classify_ptp_groups(df)
        for sub in out["ptp_sub_structures"].iloc[0]:
            leg_rates = {round(rates[tid], 6) for tid in sub["legs"]}
            assert len(leg_rates) == 1, f"cross-paired rates: {sub}"
