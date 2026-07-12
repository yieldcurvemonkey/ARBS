# tests/test_tape_curve_pkg_0712.py
"""07/12/2026 tape bugs — PTP 2-leg CURVE vs PKG-2 discrimination.

Ground truth pulled read-only from the prod tape DB (trade_ids in the bug
screenshots). The common thread: a genuine curve carries ONE package spread
(stamped on every leg) that TIES OUT to the legs' fixed-rate spread at some
clean scale factor, and is DV01-neutral in *relative* terms. The old code
demoted such curves to PKG-2 because their absolute DV01 gap exceeded the
flat $500 abs gate (calibrated for small-DV01 legs). The PTS tie-out is
affirmative evidence that overrides the abs gate.

Counter-cases that must STAY / BECOME PKG-2:
  * Bug 5  : price-keyed 1Y2Y vs 10Y20Y — forward starts AND tails differ,
             no PTS to tie -> PKG-2 (was wrongly CURVE).
  * Bug 12 : 4.70Y(~5Y off-date) vs 5.0Y — near-same broken tenor, PTS ties
             only because the spread is trivially small -> PKG-2.
"""
import pandas as pd

from SDRUtils.packages.curve import detect_curve_trades_df
from SDRUtils.packages.ptp_grouper import classify_ptp_groups, group_by_ptp

_SNAKE = dict(underlier_col="upi_underlier_name", platform_col="platform_identifier",
              cleared_col="cleared", upi_col="unique_product_identifier")


def _np_leg(tid, ts, tenor_lbl, tenor_yrs, pv01, rate, pts=None, pkg_ind=False):
    """A non-PTP (detect_curve_trades_df) candidate leg."""
    return dict(
        trade_id=tid, execution_timestamp=ts, product_type="OIS_SWAP",
        package_type="OUTRIGHT", estimated_pv01=pv01, tenor_label=tenor_lbl,
        tenor_years=tenor_yrs, effective_date="2026-07-08", forward_label="spot",
        forward_start_years=0.0, notional_currency="USD",
        upi_underlier_name="USD-SOFR-COMPOUND", unique_product_identifier="UPI-OIS",
        platform_identifier="TWSF", cleared="I", rate_index="SOFR_COMPOUND",
        tenor_segment="MEDIUM", special_tenor_type="STANDARD", fixed_rate=rate,
        package_transaction_spread=pts, package_indicator=pkg_ind,
    )


def _leg(tid, ts, tenor_yrs, pv01, rate, pts=None, ptp=None, fwd_yrs=0.0,
         tenor_label=None, platform="TWSF"):
    return dict(
        trade_id=tid, execution_timestamp=ts,
        package_transaction_price=ptp, package_transaction_spread=pts,
        package_indicator=True, unique_product_identifier="UPI-OIS",
        platform_identifier=platform, estimated_pv01=pv01,
        tenor_years=tenor_yrs, tenor_label=(tenor_label or f"{tenor_yrs:g}Y"),
        forward_start_years=fwd_yrs, fixed_rate=rate, product_type="OIS_SWAP",
    )


def _classify(rows):
    df = pd.DataFrame(rows)
    grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
    if grouped.empty:
        out = remainder.copy()
        if "package_type" not in out.columns:
            out["package_type"] = "OUTRIGHT"
        return out
    return classify_ptp_groups(grouped)


def _types(rows):
    return sorted(set(_classify(rows)["package_type"].astype(str).tolist()))


# ── PROMOTE: PKG-2 -> CURVE (PTS ties out, rel-DV01-neutral, abs gap > $500) ──

def test_bug16_2y5y_ties_out_is_curve():
    # 5Y pv01 148600 / 2Y pv01 152800 (abs gap $4200 >> $500), PTS -0.0004813
    # ties the -4.81bp rate spread at 10000x.
    rows = [
        _leg("A", "2026-07-10 17:44:32Z", 5.00274, 148600.0, 0.040159, pts=-0.0004813),
        _leg("B", "2026-07-10 17:44:32Z", 2.00274, 152800.0, 0.040640, pts=-0.0004813),
    ]
    assert _types(rows) == ["CURVE"]


def test_bug14_2y30y_ties_out_is_curve():
    rows = [
        _leg("A", "2026-07-10 18:03:24Z", 30.021918, 8400.0, 0.043216, pts=0.0025554),
        _leg("B", "2026-07-10 18:03:24Z", 2.002740, 7600.0, 0.040660, pts=0.0025554),
    ]
    assert _types(rows) == ["CURVE"]


def test_bug1b_a_4y5y_ties_out_is_curve():
    # rel DV01 gap 12.3% (< 15% belly tol), abs gap $31300, PTS 0.00002 ties 0.2bp.
    rows = [
        _leg("A", "2026-07-10 19:16:56Z", 5.00274, 270100.0, 0.040147, pts=0.00002),
        _leg("B", "2026-07-10 19:16:56Z", 4.00274, 238800.0, 0.040127, pts=0.00002),
    ]
    assert _types(rows) == ["CURVE"]


def test_bug1b_b_6m1y_ties_out_is_curve():
    rows = [
        _leg("A", "2026-07-10 18:49:31Z", 1.00000, 48700.0, 0.040518, pts=0.00159),
        _leg("B", "2026-07-10 18:49:31Z", 0.50411, 50100.0, 0.038928, pts=0.00159,
             tenor_label="6M"),
    ]
    assert _types(rows) == ["CURVE"]


def test_clean_spot_2s10s_stays_curve():
    rows = [
        _leg("A", "2026-07-10 19:15:49Z", 2.00274, 15000.0, 0.04060, pts=0.0825),
        _leg("B", "2026-07-10 19:15:49Z", 10.00822, 15000.0, 0.04143, pts=0.0825),
    ]
    assert _types(rows) == ["CURVE"]


# ── DEMOTE / KEEP PKG-2 ──────────────────────────────────────────────────────

def test_bug5_forward_mismatch_no_pts_is_pkg2():
    # price-keyed (ptp 298), no PTS. 1Y2Y vs 10Y20Y: forwards 1y vs 10y AND
    # tails 2y vs 20y both differ -> not a curve.
    rows = [
        _leg("A", "2026-07-06 15:33:11Z", 2.0, 9000.0, 0.03926, ptp=298.0, fwd_yrs=1.0,
             tenor_label="2Y"),
        _leg("B", "2026-07-06 15:33:11Z", 20.0, 9000.0, 0.04428, ptp=298.0, fwd_yrs=10.0,
             tenor_label="20Y"),
    ]
    assert _types(rows) == ["PKG-2"]


def test_bug12_near_same_broken_tenor_is_pkg2():
    # 4.70Y (~5Y off-date) vs 5.0Y, DV01 293500/277700 (abs $15800), PTS 0.0075
    # ties only because the spread is trivially small. Broken tenor -> PKG-2.
    rows = [
        _leg("A", "2026-07-06 18:58:26Z", 5.00274, 293500.0, 0.039192, pts=0.0075),
        _leg("B", "2026-07-06 18:58:26Z", 4.70137, 277700.0, 0.039117, pts=0.0075,
             tenor_label="~5Y"),
    ]
    assert _types(rows) == ["PKG-2"]


def test_bug4_two_outrights_same_pts_is_pkg2():
    # distinct tenors 2Y/10Y, same PTS 0.1257, but DV01 4000/2400 (rel 40%,
    # not neutral) -> PKG-2 (already correct; lock it).
    rows = [
        _leg("A", "2026-07-06 13:02:53Z", 10.008219, 4000.0, 0.040697, pts=0.1257),
        _leg("B", "2026-07-06 13:02:53Z", 2.002740, 2400.0, 0.039440, pts=0.1257),
    ]
    assert _types(rows) == ["PKG-2"]


# ── Bug 6: non-PTP strict same-second gate for unflagged legs ─────────────────

def _curve_types(rows):
    out = detect_curve_trades_df(pd.DataFrame(rows), **_SNAKE)
    return sorted(set(out["package_type"].astype(str).tolist()))


def test_bug6_unflagged_diff_second_is_not_curve():
    # pkg_indicator False, legs 42s apart -> coincidental, not a curve.
    rows = [
        _np_leg("A", "2026-07-06 16:01:49Z", "10Y", 10.008, 2000.0, 0.04064, pkg_ind=False),
        _np_leg("B", "2026-07-06 16:01:07Z", "2Y", 2.003, 2000.0, 0.04078, pkg_ind=False),
    ]
    assert "CURVE" not in _curve_types(rows)


def test_bug7_unflagged_same_second_is_curve():
    # pkg_indicator False but EXACT same second -> genuine curve (bug 7 accepts).
    rows = [
        _np_leg("A", "2026-07-06 18:16:03Z", "10Y", 10.008, 2000.0, 0.04064, pkg_ind=False),
        _np_leg("B", "2026-07-06 18:16:03Z", "2Y", 2.003, 2000.0, 0.04078, pkg_ind=False),
    ]
    assert _curve_types(rows) == ["CURVE"]


def test_nonptp_pts_tie_out_overrides_abs_gate():
    # Large abs DV01 gap ($4200) but PTS ties the rate spread -> still CURVE.
    rows = [
        _np_leg("A", "2026-07-06 17:44:32Z", "5Y", 5.003, 148600.0, 0.040159,
                pts=-0.0004813, pkg_ind=True),
        _np_leg("B", "2026-07-06 17:44:32Z", "2Y", 2.003, 152800.0, 0.040640,
                pts=-0.0004813, pkg_ind=True),
    ]
    assert _curve_types(rows) == ["CURVE"]
