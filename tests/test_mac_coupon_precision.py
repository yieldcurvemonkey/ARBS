"""MAC coupon matching must require an EXACT coupon (no bp-rounding tolerance).

Regression: the previous detector bucketed rates at basis-point precision:

    (fixed_rate * 10000).round().astype("Int64")

so 3.999% (= 0.03999) rounded to 400 bp and matched a 4.000% MAC coupon.
That's wrong — MAC swaps have STANDARDIZED coupons (whole / half-percent
values like 3.00, 3.50, 4.00). A trade at 3.999% is an off-par swap, not a
MAC.

After the fix, MAC tagging requires the fixed rate to match a MAC coupon
at sub-bp precision so 3.999% ≠ 4.000%.
"""
from __future__ import annotations

import pandas as pd
import pytest

from SDRUtils.products.usd.usd_swaps import detect_mac_swaps


_IMM_EFF = pd.Timestamp("2026-06-16")
_MAC_EXP = pd.Timestamp("2056-06-16")


def _trade_row(trade_id: str, fixed_rate: float) -> dict:
    return {
        "trade_id": trade_id,
        "execution_timestamp": pd.Timestamp("2026-04-10 15:39:43", tz="UTC"),
        "effective_date": _IMM_EFF,
        "expiration_date": _MAC_EXP,
        "fixed_rate": fixed_rate,
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
        "tenor_label": "30Y",
        "tenor_years": 30.0,
        "notional": 15_000_000.0,
        "risk": 26_000.0,
        "forward_label": "IMM_M2026",
        "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
        "Platform identifier": "TW",
        "Cleared": "Y",
        "Unique Product Identifier": "QZXQ4R16245X",
    }


def _patch_mac_lookup(monkeypatch, coupons_pct: list[float]) -> None:
    """Replace fetch_mac_ref_data with a synthetic lookup that advertises
    MAC coupons at ``coupons_pct`` percent for the IMM_M2026 (eff, mat) pair."""
    rows = [
        {
            "imm_start_date": _IMM_EFF,
            "expiration_date": _MAC_EXP,
            "coupon": c,  # SDR stores coupons as percent (e.g. 4.0)
        }
        for c in coupons_pct
    ]
    df = pd.DataFrame(rows)
    monkeypatch.setattr(
        "SDRUtils.products.usd.usd_swaps.fetch_mac_ref_data",
        lambda effective_date: df,
    )


def test_exact_coupon_match_is_mac(monkeypatch):
    _patch_mac_lookup(monkeypatch, [4.00])
    df = pd.DataFrame([_trade_row("T1", 0.04)])
    out = detect_mac_swaps(df)
    assert bool(out.loc[0, "is_mac"]) is True


def test_off_par_3_999_is_NOT_mac(monkeypatch):
    """The reported screenshot case: 3.999% fixed rate must not be flagged
    as a 4.00% MAC."""
    _patch_mac_lookup(monkeypatch, [4.00])
    df = pd.DataFrame([_trade_row("T1", 0.03999)])
    out = detect_mac_swaps(df)
    assert bool(out.loc[0, "is_mac"]) is False


def test_off_par_4_001_is_NOT_mac(monkeypatch):
    _patch_mac_lookup(monkeypatch, [4.00])
    df = pd.DataFrame([_trade_row("T1", 0.04001)])
    out = detect_mac_swaps(df)
    assert bool(out.loc[0, "is_mac"]) is False


def test_tolerates_tiny_floating_point_noise_at_exact_coupon(monkeypatch):
    """A published 4.00% coupon that round-trips through the DB may come
    back as 0.039999999999 — still exact enough to flag as MAC."""
    _patch_mac_lookup(monkeypatch, [4.00])
    df = pd.DataFrame([_trade_row("T1", 0.040000000001)])
    out = detect_mac_swaps(df)
    assert bool(out.loc[0, "is_mac"]) is True


@pytest.mark.parametrize("coupon_pct,rate,expected", [
    (4.00,  0.04,    True),
    (4.00,  0.03999, False),
    (4.00,  0.04001, False),
    (3.50,  0.035,   True),
    (3.50,  0.03499, False),
    (3.25,  0.0325,  True),
    (3.25,  0.03251, False),
])
def test_parametric_exact_coupon_only(monkeypatch, coupon_pct, rate, expected):
    _patch_mac_lookup(monkeypatch, [coupon_pct])
    df = pd.DataFrame([_trade_row("T1", rate)])
    out = detect_mac_swaps(df)
    assert bool(out.loc[0, "is_mac"]) is expected, (
        f"coupon={coupon_pct}% rate={rate} expected is_mac={expected}"
    )
