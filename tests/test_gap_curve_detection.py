"""Forward gap curves: two legs with the SAME tail tenor but DIFFERENT forward
starts (e.g. 7Y11M·1Y vs 8Y11M·1Y) are a curve on the forward rate. They must be
detected as CURVE even though their effective dates differ. The curve detector's
same-effective-date guard previously had no allow_gap_curves exception (unlike
the forward guards), so these fell through as two OUTRIGHTs.
"""
import pandas as pd

from SDRUtils.packages.curve import detect_curve_trades_df

_SNAKE = dict(underlier_col="upi_underlier_name", platform_col="platform_identifier",
              cleared_col="cleared", upi_col="unique_product_identifier")


def _leg(tid, eff, exp, tenor, fwd_lbl, fwd_yrs, pv01):
    return dict(
        trade_id=tid, execution_timestamp="2026-05-29T16:00:09Z",
        effective_date=eff, expiration_date=exp, tenor_label=tenor,
        forward_label=fwd_lbl, forward_start_years=fwd_yrs, estimated_pv01=pv01,
        product_type="OIS_SWAP", package_type="OUTRIGHT", notional_currency="USD",
        platform_identifier="TWSF", cleared="I", unique_product_identifier="UPI-1Y",
        upi_underlier_name="USD-SOFR-COMPOUND", rate_index="SOFR_COMPOUND",
        tenor_segment="SHORT",
    )


def test_forward_gap_curve_is_detected():
    df = pd.DataFrame([
        _leg("A", "2035-04-22", "2036-04-22", "1Y", "8Y11M", 8.92, 20000.0),
        _leg("B", "2034-04-23", "2035-04-23", "1Y", "7Y11M", 7.92, 20000.0),
    ])
    out = detect_curve_trades_df(df, **_SNAKE)
    assert out["package_type"].astype(str).str.upper().str.contains("CURVE").all()
    assert out["package_id"].dropna().nunique() == 1


def test_normal_spot_curve_still_detected():
    # different tenor, SAME effective date -> classic curve, unaffected
    df = pd.DataFrame([
        _leg("C", "2026-06-01", "2031-06-01", "5Y", "spot", 0.0, 45000.0),
        _leg("D", "2026-06-01", "2036-06-01", "10Y", "spot", 0.0, 45000.0),
    ])
    out = detect_curve_trades_df(df, **_SNAKE)
    assert out["package_type"].astype(str).str.upper().str.contains("CURVE").all()


def test_different_tenor_and_different_eff_not_paired():
    # NOT a gap curve (different tail tenors AND different eff): must stay OUTRIGHT
    df = pd.DataFrame([
        _leg("E", "2035-04-22", "2040-04-22", "5Y", "8Y11M", 8.92, 45000.0),
        _leg("F", "2034-04-23", "2035-04-23", "1Y", "7Y11M", 7.92, 20000.0),
    ])
    out = detect_curve_trades_df(df, **_SNAKE)
    assert (out["package_type"].astype(str).str.upper() == "OUTRIGHT").all()
