"""Forward gap flies: three legs with the SAME tail tenor but DIFFERENT forward
starts (e.g. IMM_M2027/IMM_M2028/IMM_M2029 all 1Y) are a butterfly on the forward
rate. The gap-fly pass matches on the forward axis and requires the same tail
tenor — but it compared tenor_years with EXACT equality, so day-count/leap-year
noise (a 1Y spanning Feb 29 = 1.0027 vs 1.0) split the structure into outrights.
"""
import pandas as pd

from SDRUtils.packages.fly import detect_fly_trades_df

_SNAKE = dict(underlier_col="upi_underlier_name", platform_col="platform_identifier",
              cleared_col="cleared", upi_col="unique_product_identifier")


def _leg(tid, ten_yrs, fwd_yrs, pv01, fwd_lbl="spot", eff="2026-06-01"):
    return dict(
        trade_id=tid, execution_timestamp="2026-05-29T15:58:51Z",
        effective_date=eff, tenor_years=ten_yrs, tenor_label="1Y",
        forward_label=fwd_lbl, forward_start_years=fwd_yrs, estimated_pv01=pv01,
        product_type="OIS_SWAP", package_type="OUTRIGHT", notional_currency="USD",
        platform_identifier="TWSF", cleared="I", unique_product_identifier="UPI-1Y",
        upi_underlier_name="USD-SOFR-OIS Compound", rate_index="SOFR",
        tenor_segment="SHORT", package_transaction_spread=-0.1028,
    )


def test_forward_gap_fly_detected():
    # belly M2028 (fwd 2y, 12K) ; wings M2027 (fwd 1y, 6K, tenor 1.0027) + M2029 (fwd 3y, 6K)
    df = pd.DataFrame([
        _leg("W1", 1.0027, 1.05, 6000.0),
        _leg("BELLY", 1.0, 2.06, 12000.0),
        _leg("W2", 1.0, 3.06, 6000.0),
    ])
    out = detect_fly_trades_df(df, **_SNAKE)
    assert out["package_type"].astype(str).str.upper().str.contains("FLY").all()
    assert out["package_id"].dropna().nunique() == 1


def test_normal_spot_fly_still_detected():
    # classic 5Y/7Y/10Y spot fly (different tail tenors, same eff) — unaffected
    def leg(tid, ten, pv):
        d = _leg(tid, ten, 0.0, pv)
        d["tenor_label"] = f"{int(ten)}Y"
        return d
    df = pd.DataFrame([leg("A", 5.0, 45000.0), leg("B", 7.0, 90000.0), leg("C", 10.0, 45000.0)])
    out = detect_fly_trades_df(df, **_SNAKE)
    assert out["package_type"].astype(str).str.upper().str.contains("FLY").all()


def test_gap_fly_rejects_mismatched_tail_tenor():
    # one wing has a genuinely different tail (2Y, not 1Y) -> not a same-tail gap fly
    df = pd.DataFrame([
        _leg("W1", 2.0, 1.05, 6000.0),     # 2Y tail wing — does not belong
        _leg("BELLY", 1.0, 2.06, 12000.0),
        _leg("W2", 1.0, 3.06, 6000.0),
    ])
    out = detect_fly_trades_df(df, **_SNAKE)
    assert not out["package_type"].astype(str).str.upper().str.contains("FLY").any()
