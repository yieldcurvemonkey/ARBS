"""Fly detector must be order-independent.

Regression: the original streaming detector only found flys where the belly
arrived LAST in time order (so both wings were already stored). A belly-first
or belly-middle arrival would fall through undetected and get paired as a
2-leg curve instead, with the belly dangling as an orphan outright.

Observed 2026-04-10 16:48:13 IMM_M2026 3Y/5Y/7Y UFRO set matched exactly
this pattern — 3Y (wing), 5Y (belly), 7Y (wing) executed in that order.
Detector found the 3Y/7Y pair as a CURVE and left the 5Y as an outright.
After the fix, all three should be grouped as a FLY.
"""
from __future__ import annotations

import pandas as pd
import pytest

from SDRUtils.packages.fly import detect_fly_trades_df


_BASE = pd.Timestamp("2026-04-10 16:48:13", tz="UTC")
_UPI = "QZF08M5TR8H3"


def _leg(trade_id: str, t_offset_s: int, tenor_years: float, tenor_label: str, pv01: float) -> dict:
    return {
        "trade_id": trade_id,
        "execution_timestamp": _BASE + pd.Timedelta(seconds=t_offset_s),
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
        "estimated_pv01": pv01,
        "tenor_label": tenor_label,
        "tenor_years": tenor_years,
        "notional_currency": "USD",
        "effective_date": pd.Timestamp("2026-06-16"),
        "forward_label": "IMM_M2026",
        "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
        "Platform identifier": "TW",
        "Cleared": "Y",
        "Unique Product Identifier": _UPI,
    }


def _legs_ordered(order: list[str]) -> pd.DataFrame:
    """Build the 3Y/5Y/7Y IMM_M2026 fly with legs executed in ``order``."""
    lookup = {
        "wing_short": _leg("T_SHORT", 0, 3.0, "3Y", 10_100.0),  # 3Y wing
        "belly":      _leg("T_BELLY", 0, 5.0, "5Y", 19_900.0),  # 5Y belly
        "wing_long":  _leg("T_LONG",  0, 7.0, "7Y", 9_800.0),   # 7Y wing
    }
    rows = []
    for i, key in enumerate(order):
        row = dict(lookup[key])
        row["execution_timestamp"] = _BASE + pd.Timedelta(seconds=i * 5)
        rows.append(row)
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    "order",
    [
        ["wing_short", "wing_long", "belly"],    # belly last — always worked
        ["belly", "wing_short", "wing_long"],    # belly first — the bug
        ["wing_short", "belly", "wing_long"],    # belly middle — also fails
        ["belly", "wing_long", "wing_short"],    # belly first, wings reversed
        ["wing_long", "belly", "wing_short"],    # belly middle, wings reversed
        ["wing_long", "wing_short", "belly"],    # belly last, wings reversed
    ],
)
def test_fly_detected_regardless_of_arrival_order(order):
    df = _legs_ordered(order)
    out = detect_fly_trades_df(df, require_same_upi=True)
    fly_count = int((out["package_type"] == "FLY").sum())
    assert fly_count == 3, (
        f"Expected all 3 legs to be paired as FLY for arrival order {order}, "
        f"got {fly_count}. package_type column:\n{out['package_type'].tolist()}"
    )


def test_fly_detected_preserves_other_economic_guards():
    """The order-independent second pass MUST still honour the UPI gate and
    the belly/wing DV01 tolerances. A fly with one leg on a different UPI
    should NOT be flagged as a fly even with the expanded detection."""
    df = _legs_ordered(["belly", "wing_short", "wing_long"])
    df.loc[df["trade_id"] == "T_BELLY", "Unique Product Identifier"] = "DIFFERENT_UPI"
    out = detect_fly_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "FLY").sum() == 0
