# tests/test_tape_fly_pkg_0712.py
"""07/12/2026 tape bug 11 — a fly requires package_indicator=True on every leg
AND an exact shared execution second. Legs 30-60s apart or unflagged are
coincidental co-execution, not a fly."""
import pandas as pd

from SDRUtils.packages.fly import detect_fly_trades_df

_SNAKE = dict(underlier_col="upi_underlier_name", platform_col="platform_identifier",
              cleared_col="cleared", upi_col="unique_product_identifier")


def _leg(tid, ts, tenor_lbl, tenor_yrs, pv01, rate, pkg_ind=True):
    return dict(
        trade_id=tid, execution_timestamp=ts, product_type="OIS_SWAP",
        package_type="OUTRIGHT", estimated_pv01=pv01, tenor_label=tenor_lbl,
        tenor_years=tenor_yrs, effective_date="2026-07-14", forward_label="spot",
        forward_start_years=0.0, notional_currency="USD",
        upi_underlier_name="USD-SOFR-COMPOUND", unique_product_identifier="UPI-OIS",
        platform_identifier="TWSF", cleared="I", rate_index="SOFR_COMPOUND",
        tenor_segment="MEDIUM", special_tenor_type="STANDARD", fixed_rate=rate,
        package_indicator=pkg_ind,
    )


def _fly_count(rows):
    out = detect_fly_trades_df(pd.DataFrame(rows), **_SNAKE)
    return int((out["package_type"].astype(str) == "FLY").sum())


def test_bug11_unflagged_multisecond_is_not_fly():
    # Spot 10Y/20Y/30Y, pkg_indicator False, legs 51s apart -> NOT a fly.
    rows = [
        _leg("A", "2026-07-06 19:44:40Z", "10Y", 10.008, 82000.0, 0.04053, pkg_ind=False),
        _leg("B", "2026-07-06 19:45:11Z", "20Y", 20.014, 176000.0, 0.04283, pkg_ind=False),
        _leg("C", "2026-07-06 19:45:31Z", "30Y", 30.022, 85000.0, 0.04245, pkg_ind=False),
    ]
    assert _fly_count(rows) == 0


def test_flagged_same_second_belly_balanced_is_fly():
    # Spot 5Y/8Y/15Y, pkg_indicator True, SAME second, belly = 2x wing -> FLY.
    rows = [
        _leg("A", "2026-07-06 18:55:47Z", "5Y", 5.003, 10000.0, 0.04016),
        _leg("B", "2026-07-06 18:55:47Z", "8Y", 8.005, 20000.0, 0.04083),
        _leg("C", "2026-07-06 18:55:47Z", "15Y", 15.011, 10000.0, 0.04292),
    ]
    assert _fly_count(rows) == 3


def test_flagged_but_multisecond_is_not_fly():
    # Even flagged legs must share the exact second.
    rows = [
        _leg("A", "2026-07-06 18:55:47Z", "5Y", 5.003, 10000.0, 0.04016),
        _leg("B", "2026-07-06 18:55:59Z", "8Y", 8.005, 20000.0, 0.04083),
        _leg("C", "2026-07-06 18:56:10Z", "15Y", 15.011, 10000.0, 0.04292),
    ]
    assert _fly_count(rows) == 0
