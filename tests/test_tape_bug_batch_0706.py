"""Regression tests for the 2026-07-06 tape bug batch.

Covers: gap-package labels (forward gap flies/curves), FOMC leg labels
without tenor suffixes, clean-spot-tenor priority over the UST MMYY alias,
Basis-Outright labeling, leg-scope Outright rendering, signed-net OPA
summaries, the residual same-timestamp package grouper, the same-tenor
spreadover pairing gate, and gap-aware PTP group classification.
"""
import pandas as pd
import pytest

from SDRUtils.analytics.trade_tape import TradeTape
from SDRUtils.core.tenors import _standard_tenor_label, get_imm_label
from SDRUtils.packages.ptp_grouper import _classify_single_group
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    _assert_risk_populated,
    _compute_leg_summary,
    _leg_order_series,
    TapeRiskValidationError,
)
from SDRUtils.products.usd.usd_swaps import group_residual_package_trades


def _base_leg(**over):
    row = {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-07-06 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP",
        "upi_underlier_name": "USD-SOFR-COMPOUND 1D",
        "upi_reset_freq": "1D",
        "upi_notional_schedule": "Constant",
        "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT",
        "package_type": "OUTRIGHT",
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "tenor_label": "10Y",
        "tenor_display": "10Y",
        "tenor_years": 10.0,
        "package_tenors": "10Y",
        "cleared": "Y",
        "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2026-07-08"),
        "expiration_date": pd.Timestamp("2036-07-08"),
        "is_unwind": False,
        "is_mac": False,
        "is_ufro": False,
        "is_block": False,
    }
    row.update(over)
    return row


def _labels(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    return tape._build_enriched_label(out)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def test_gap_fly_package_label_joins_forwards():
    """Bug 12/26: forward gap fly labels as fwd1/fwd2/fwd3 + common tenor."""
    rows = [
        _base_leg(
            trade_id=f"G{i}",
            trade_type="FLY",
            package_type="FLY",
            package_legs=["G0", "G1", "G2"],
            forward_label=fwd,
            forward_start_years=fy,
            tenor_label="2Y",
            tenor_display="2Y",
            tenor_years=2.0,
            package_tenors="2Y/2Y/2Y",
            effective_date=pd.Timestamp(eff),
            expiration_date=pd.Timestamp(exp),
        )
        for i, (fwd, fy, eff, exp) in enumerate([
            ("IMM_U2030", 4.2, "2030-09-18", "2032-09-18"),
            ("IMM_U2032", 6.2, "2032-09-15", "2034-09-15"),
            ("IMM_U2034", 8.2, "2034-09-20", "2036-09-20"),
        ])
    ]
    out = _labels(rows)
    label = out.loc[0, "tape_label"]
    assert "IMM_U2030/IMM_U2032/IMM_U2034 2Y" in label
    assert "FLY" in label
    # Leg scope stays a plain outright with its own forward.
    assert "IMM_U2030 2Y Outright" in out.loc[0, "leg_tape_label"]


def test_gap_curve_package_label_orders_forwards():
    """Bug 18: 1y1y vs 2y1y gap curve labels '1Y/2Y 1Y CURVE'."""
    rows = [
        _base_leg(
            trade_id=f"C{i}",
            trade_type="CURVE",
            package_type="CURVE",
            package_legs=["C0", "C1"],
            forward_label=fwd,
            forward_start_years=fy,
            tenor_label="1Y",
            tenor_display="1Y",
            tenor_years=1.0,
            package_tenors="1Y/1Y",
            effective_date=pd.Timestamp(eff),
            expiration_date=pd.Timestamp(exp),
        )
        for i, (fwd, fy, eff, exp) in enumerate([
            ("2Y", 2.0, "2028-07-07", "2029-07-08"),
            ("1Y", 1.0, "2027-07-08", "2028-07-08"),
        ])
    ]
    out = _labels(rows)
    assert "1Y/2Y 1Y" in out.loc[0, "tape_label"]
    assert "CURVE" in out.loc[0, "tape_label"]


def test_fomc_leg_label_has_no_tenor_suffix():
    """Bug 3: consecutive-meeting legs read 'FOMC OCT26 Outright', no '1M'."""
    rows = [
        _base_leg(
            trade_id="F1",
            trade_type="CURVE",
            package_type="CURVE",
            package_indicator=True,
            package_legs=["F1", "F2"],
            tenor_label="1M",
            tenor_display="1M",
            tenor_years=0.115,
            package_tenors="1M/2M",
            special_tenor_type="FOMC",
            effective_date=pd.Timestamp("2026-10-28"),
            expiration_date=pd.Timestamp("2026-12-09"),
        ),
        _base_leg(
            trade_id="F2",
            trade_type="CURVE",
            package_type="CURVE",
            package_indicator=True,
            package_legs=["F1", "F2"],
            tenor_label="2M",
            tenor_display="2M",
            tenor_years=0.134,
            package_tenors="1M/2M",
            special_tenor_type="FOMC",
            effective_date=pd.Timestamp("2026-12-09"),
            expiration_date=pd.Timestamp("2027-01-27"),
        ),
    ]
    out = _labels(rows)
    leg1 = out.loc[0, "leg_tape_label"]
    assert "FOMC OCT26" in leg1
    assert "1M" not in leg1
    assert "Outright" in leg1
    # Bug 16: package label in chronological meeting order.
    assert "FOMC OCT26/DEC26" in out.loc[0, "tape_label"]


def test_clean_spot_tenor_wins_over_ust_alias():
    """Bug 22: a clean 2M swap maturing on a UST date keeps 'Spot 2M'."""
    rows = [
        _base_leg(
            trade_id="M1",
            trade_type="MATCHED_MATURITY",
            package_type="MATCHED_MATURITY",
            special_tenor_type="MATCHED_MATURITY",
            matched_ust_maturity=True,
            tenor_label="2M",
            tenor_display="2M",
            tenor_years=0.17,
            package_tenors="2M",
            effective_date=pd.Timestamp("2026-07-08"),
            expiration_date=pd.Timestamp("2026-09-08"),
        )
    ]
    out = _labels(rows)
    alias_label = out.loc[0, "tape_label_ust_alias"]
    assert "Spot 2M" in alias_label
    assert "0926" not in alias_label


def test_broken_tenor_still_uses_ust_alias():
    """Bug 4: a broken-date MMS keeps the MMYY alias ('0236')."""
    rows = [
        _base_leg(
            trade_id="M2",
            trade_type="MATCHED_MATURITY",
            package_type="MATCHED_MATURITY",
            special_tenor_type="MATCHED_MATURITY",
            matched_ust_maturity=True,
            tenor_label="9Y7M",
            tenor_display="9Y7M",
            tenor_years=9.61,
            package_tenors="9Y7M",
            effective_date=pd.Timestamp("2026-07-08"),
            expiration_date=pd.Timestamp("2036-02-15"),
        )
    ]
    out = _labels(rows)
    assert "0236" in out.loc[0, "tape_label_ust_alias"]
    assert "MMS" in out.loc[0, "tape_label_ust_alias"]


def test_basis_swap_labels_basis_outright():
    """Bug 14: float-float basis swaps read 'Basis-Outright'."""
    rows = [
        _base_leg(
            trade_id="B1",
            product_type="BASIS_SWAP",
            basis_type="SOFR_FF",
            upi_underlier_name="USD-Federal Funds-OIS Compound vs USD-SOFR-OIS Compound",
            tenor_label="1Y",
            tenor_display="1Y",
            tenor_years=1.0,
            package_tenors="1Y",
            expiration_date=pd.Timestamp("2027-07-08"),
        )
    ]
    out = _labels(rows)
    assert "Basis-Outright" in out.loc[0, "tape_label"]


def test_unpaired_package_leg_scope_renders_outright():
    """Bug 4 (leg scope): leg labels never read 'Package'."""
    rows = [
        _base_leg(
            trade_id="P1",
            package_indicator=True,
            trade_type="MATCHED_MATURITY",
            package_type="PKG-3",
            tenor_label="9Y7M",
            tenor_display="9Y7M",
            tenor_years=9.61,
            package_tenors="9Y7M",
            expiration_date=pd.Timestamp("2036-02-15"),
        )
    ]
    out = _labels(rows)
    assert "Package" in out.loc[0, "tape_label"] or "PKG" in out.loc[0, "tape_label"]
    assert "Package" not in out.loc[0, "leg_tape_label"]
    assert "Outright" in out.loc[0, "leg_tape_label"]


def test_fomc_stt_without_label_falls_through_to_tenor():
    """Bug 15/27: FOMC-typed rows without a meeting label render Spot+tenor."""
    rows = [
        _base_leg(
            trade_id="S1",
            trade_type="FOMC",
            special_tenor_type="FOMC",
            tenor_label="11M",
            tenor_display="11M",
            tenor_years=0.917,
            package_tenors="11M",
            expiration_date=pd.Timestamp("2027-06-08"),
        )
    ]
    out = _labels(rows)
    assert "Spot 11M Outright" in out.loc[0, "tape_label"]


def test_ois_reset_freq_normalizes_to_1d():
    """Bug 3: meeting-dated UPIs carry 6W/7W terms; OIS resets render 1D."""
    rows = [_base_leg(trade_id="R1", upi_reset_freq="7W")]
    out = _labels(rows)
    assert "1D Constant" in out.loc[0, "tape_label"]
    assert "7W" not in out.loc[0, "tape_label"]


# ---------------------------------------------------------------------------
# Tenor label fallback
# ---------------------------------------------------------------------------


def test_fourteen_month_fallback_keeps_month_resolution():
    """Bug 29: 14.2 months reads '~14M', not '~1Y'."""
    label, matched = _standard_tenor_label(1.1836)
    assert label == "~14M"
    assert matched is False


def test_holiday_rolled_imm_date_labels():
    """Bug 26: Juneteenth-rolled June IMM effective dates still label IMM."""
    assert get_imm_label(pd.Timestamp("2041-06-20")) == "IMM_M2041"


# ---------------------------------------------------------------------------
# PTP group classification (gap-aware)
# ---------------------------------------------------------------------------


def test_ptp_group_same_tail_distinct_forwards_is_fly():
    g = pd.DataFrame({
        "trade_id": ["a", "b", "c"],
        "estimated_pv01": [15000.0, 30000.0, 15000.0],
        "tenor_years": [2.0, 2.0, 2.0],
        "forward_start_years": [4.2, 6.2, 8.2],
        "fixed_rate": [0.0398, 0.0417, 0.0437],
    })
    pkg_type, _ = _classify_single_group(g)
    assert pkg_type == "FLY"


def test_ptp_group_fomc_pair_is_curve():
    g = pd.DataFrame({
        "trade_id": ["a", "b"],
        "estimated_pv01": [10700.0, 10600.0],
        "tenor_years": [0.134, 0.134],
        "forward_start_years": [0.43, 0.56],
        "fixed_rate": [0.0394, 0.0397],
    })
    pkg_type, _ = _classify_single_group(g)
    assert pkg_type == "CURVE"


def test_ptp_group_identical_legs_stays_pkg_n():
    g = pd.DataFrame({
        "trade_id": ["a", "b", "c"],
        "estimated_pv01": [230600.0, 230600.0, 310100.0],
        "tenor_years": [9.61, 9.61, 9.61],
        "forward_start_years": [0.0, 0.0, 0.0],
        "fixed_rate": [0.0405, 0.0405, 0.0405],
    })
    pkg_type, _ = _classify_single_group(g)
    assert pkg_type == "PKG-3"


# ---------------------------------------------------------------------------
# Residual same-timestamp package grouper
# ---------------------------------------------------------------------------


def _residual_row(tid, **over):
    row = {
        "trade_id": tid,
        "execution_timestamp": pd.Timestamp("2026-07-06 06:24:27", tz="UTC"),
        "package_indicator": True,
        "package_type": "OUTRIGHT",
        "package_id": None,
        "package_legs": None,
        "platform_identifier": "TWSF",
        "unique_product_identifier": "UPI123",
        "invoice_swap_ticker": None,
    }
    row.update(over)
    return row


def test_residual_grouper_groups_cotimestamped_package_legs():
    df = pd.DataFrame([_residual_row("t1"), _residual_row("t2")])
    out = group_residual_package_trades(df)
    assert set(out["package_type"]) == {"PKG-2"}
    assert out["package_id"].nunique() == 1
    assert list(out["package_legs"].iloc[0]) == ["t1", "t2"]


def test_residual_grouper_ignores_spreadovers_and_unflagged():
    df = pd.DataFrame([
        _residual_row("t1", package_type="SPREADOVER"),
        _residual_row("t2", package_type="SPREADOVER"),
        _residual_row("t3", package_indicator=False),
        _residual_row("t4", package_indicator=False),
    ])
    out = group_residual_package_trades(df)
    assert (out["package_type"] != "PKG-2").all()


def test_residual_grouper_respects_timestamp_and_platform():
    df = pd.DataFrame([
        _residual_row("t1"),
        _residual_row("t2", execution_timestamp=pd.Timestamp("2026-07-06 06:24:28", tz="UTC")),
        _residual_row("t3", platform_identifier="BILT"),
    ])
    out = group_residual_package_trades(df)
    assert (out["package_type"] == "OUTRIGHT").all()


# ---------------------------------------------------------------------------
# Summary OPA = signed net
# ---------------------------------------------------------------------------


def test_fly_summary_opa_is_signed_net():
    g = pd.DataFrame({
        "trade_id": ["a", "b", "c"],
        "tenor_years": [3.0, 5.0, 30.0],
        "forward_start_years": [0.0, 0.0, 0.0],
        "fixed_rate": [0.04047, 0.04005, 0.04234],
        "risk": [15000.0, 30000.0, 15000.0],
        "other_payment_amount": [266253.0, 263176.0, 18939.0],
        "opa_sign": [-1, 1, -1],
        "opa_signed_net": [-22016.0, -22016.0, -22016.0],
        "execution_timestamp": pd.Timestamp("2026-07-06 10:00:00", tz="UTC"),
    })
    result = _compute_leg_summary(g, "FLY", "FLY")
    assert result["summary_opa"] == pytest.approx(-266253.0 + 263176.0 - 18939.0)
    # Fly rate convention unchanged: 2*belly - wings.
    assert result["summary_rate"] == pytest.approx(2 * 0.04005 - 0.04047 - 0.04234)


def test_curve_summary_opa_is_signed_net_matches_ptp():
    g = pd.DataFrame({
        "trade_id": ["a", "b"],
        "tenor_years": [5.0, 30.0],
        "forward_start_years": [0.0, 0.0],
        "fixed_rate": [0.03905, 0.04226],
        "risk": [50000.0, 50000.0],
        "other_payment_amount": [4100.0, 2600.0],
        "opa_sign": [-1, -1],
        "execution_timestamp": pd.Timestamp("2026-07-06 10:00:00", tz="UTC"),
    })
    result = _compute_leg_summary(g, "CURVE", "CURVE")
    assert result["summary_opa"] == pytest.approx(-6700.0)


def test_fomc_package_leg_order_follows_effective_date():
    """Bug 16: FOMC curve legs order chronologically, not by tenor."""
    df = pd.DataFrame([
        {
            "trade_id": "later",
            "package_id": "PKG1",
            "fomc_meeting_label": "MAR27",
            "tenor_years": 0.115,  # shorter period but LATER meeting
            "forward_start_years": 0.70,
            "effective_date": pd.Timestamp("2027-03-17"),
            "execution_timestamp": pd.Timestamp("2026-07-06 10:00:00", tz="UTC"),
        },
        {
            "trade_id": "earlier",
            "package_id": "PKG1",
            "fomc_meeting_label": "DEC26",
            "tenor_years": 0.134,
            "forward_start_years": 0.43,
            "effective_date": pd.Timestamp("2026-12-09"),
            "execution_timestamp": pd.Timestamp("2026-07-06 10:00:00", tz="UTC"),
        },
    ])
    order = _leg_order_series(df)
    assert order[df["trade_id"] == "earlier"].iloc[0] == 0
    assert order[df["trade_id"] == "later"].iloc[0] == 1


# ---------------------------------------------------------------------------
# Null-risk publish guardrail (2026-07-06 curve-failure incident)
# ---------------------------------------------------------------------------


def _risk_leg_rows(n, *, null_frac):
    n_null = int(round(n * null_frac))
    return [
        {"trade_id": str(i), "risk": (None if i < n_null else 30000.0)}
        for i in range(n)
    ]


def test_risk_guard_aborts_on_all_null_risk():
    # A failed curve build -> all-NULL risk. Publishing would clobber prod.
    with pytest.raises(TapeRiskValidationError):
        _assert_risk_populated(_risk_leg_rows(200, null_frac=1.0), "2026-07-06")


def test_risk_guard_allows_healthy_day():
    # 0% null risk -> no raise (zero-risk legs would be fine too; they are
    # not null).
    _assert_risk_populated(_risk_leg_rows(200, null_frac=0.0), "2026-07-06")


def test_risk_guard_ignores_small_batches():
    # Small incremental batches (< min legs) never trip the guard even if
    # fully null — avoids false alarms on tiny service cycles.
    _assert_risk_populated(_risk_leg_rows(10, null_frac=1.0), "2026-07-06")


def test_risk_guard_allows_partial_null():
    # Some null risk but below the pathological threshold still writes.
    _assert_risk_populated(_risk_leg_rows(200, null_frac=0.5), "2026-07-06")
