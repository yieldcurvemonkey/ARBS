"""MMS detector must not tag IMM-to-IMM forward-starting swaps.

Regression: the matched-maturity detector fires any time a swap's
``expiration_date`` coincides with a UST coupon. But IMM dates
(3rd Wed of Mar/Jun/Sep/Dec) frequently coincide with on-the-run
UST coupon maturities by calendar accident. A trade that starts
on IMM H2028 and matures on IMM H2029 is an IMM forward-starting
1Y swap, NOT a swap-vs-UST spread.

User spec: if BOTH the effective date AND the maturity date land
on IMM dates, the trade cannot be MATCHED_MATURITY.
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from SDRUtils.packages.mms import _match_swaps_to_ust_by_maturity


_IMM_EFF = pd.Timestamp("2028-03-15")   # IMM H2028 (3rd Wed of Mar 2028)
_IMM_MAT = pd.Timestamp("2029-03-21")   # IMM H2029 (3rd Wed of Mar 2029)
_NON_IMM_EFF = pd.Timestamp("2026-04-17")


def _trade(
    *,
    trade_id: str,
    effective_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    forward_label: str = "spot",
) -> dict:
    return {
        "trade_id": trade_id,
        "execution_timestamp": pd.Timestamp("2026-04-10 16:00:19", tz="UTC"),
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
        "notional_currency": "USD",
        "forward_label": forward_label,
        "tenor_years": max(1.0, (expiration_date - effective_date).days / 365.0),
    }


@pytest.fixture
def fake_ust_ref():
    """Simulate TreasuryDirect having a UST that matures on IMM H2029.
    This is the failure mode: IMM dates sometimes coincide with a UST
    coupon schedule, tricking the matcher."""

    def _loader(*args, **kwargs):
        return pd.DataFrame(
            [
                {
                    "cusip": "IMM_COINCIDENT_UST",
                    "maturity_date": _IMM_MAT.date(),
                    "issue_date": pd.Timestamp("2027-03-15").date(),
                    "oi": "2-Year",
                    "security_type": "Treasury Note",
                    "coupon": 4.0,
                    "original_security_term": "2-Year",
                }
            ]
        )

    with patch(
        "SDRUtils.packages.mms._load_ust_reference_data",
        side_effect=_loader,
    ):
        yield


def test_imm_to_imm_trade_is_not_matched_maturity(fake_ust_ref):
    df = pd.DataFrame([
        _trade(
            trade_id="IMM_FWD_1Y",
            effective_date=_IMM_EFF,
            expiration_date=_IMM_MAT,
            forward_label="IMM_H2028",
        )
    ])
    out = _match_swaps_to_ust_by_maturity(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is False


def test_spot_to_imm_trade_is_still_matched(fake_ust_ref):
    """Only the IMM-to-IMM pair is suspect. A spot-start that happens
    to mature on an IMM/UST-coupon date is still a plausible MMS."""
    df = pd.DataFrame([
        _trade(
            trade_id="SPOT_MAT_IMM",
            effective_date=_NON_IMM_EFF,
            expiration_date=_IMM_MAT,
            forward_label="spot",
        )
    ])
    out = _match_swaps_to_ust_by_maturity(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True


def test_imm_forward_label_with_offset_maturity_is_NOT_mms(fake_ust_ref):
    """User screenshot: IMM_H2028 1Y forward — eff = 2028-03-15 (IMM H2028),
    mat = 2029-03-15 = eff + 1Y. Mat is NOT on the strict IMM anchor for
    H2029 (which is 2029-03-21) but the trade is still an IMM forward —
    forward_label starts with "IMM_". Must NOT be MMS."""
    off_anchor_mat = pd.Timestamp("2029-03-15")
    with patch(
        "SDRUtils.packages.mms._load_ust_reference_data",
        return_value=pd.DataFrame(
            [
                {
                    "cusip": "IMM_FWD_OFFSET_UST",
                    "maturity_date": off_anchor_mat.date(),
                    "issue_date": pd.Timestamp("2027-03-15").date(),
                    "oi": "2-Year",
                    "security_type": "Treasury Note",
                    "coupon": 4.0,
                    "original_security_term": "2-Year",
                }
            ]
        ),
    ):
        df = pd.DataFrame([
            _trade(
                trade_id="IMM_FWD_1Y_OFFSET",
                effective_date=_IMM_EFF,
                expiration_date=off_anchor_mat,
                forward_label="IMM_H2028",
            )
        ])
        out = _match_swaps_to_ust_by_maturity(df)
        assert bool(out.loc[0, "matched_ust_maturity"]) is False


def test_spot_forward_label_is_still_eligible_for_mms(fake_ust_ref):
    """Safety: if forward_label is 'spot', the IMM-forward exclusion
    must NOT fire, even if the maturity happens to be an IMM date."""
    df = pd.DataFrame([
        _trade(
            trade_id="SPOT_MAT_IMM",
            effective_date=_NON_IMM_EFF,
            expiration_date=_IMM_MAT,
            forward_label="spot",
        )
    ])
    out = _match_swaps_to_ust_by_maturity(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True


def test_mms_detector_survives_pandas_copy_on_write(fake_ust_ref):
    """Under pandas copy-on-write, .values from isin() yields a read-only view;
    the old in-place ``m &= ...`` on line 332 raised
    ValueError: assignment destination is read-only.
    This regression test confirms the fix (``m = m & (...)``) holds when CoW
    is active.  The autouse conftest fixture resets CoW to False before every
    test, so we set it back to True here explicitly and restore in finally."""
    pd.options.mode.copy_on_write = True
    try:
        df = pd.DataFrame([
            _trade(
                trade_id="SPOT_MAT_IMM_COW",
                effective_date=_NON_IMM_EFF,
                expiration_date=_IMM_MAT,
                forward_label="spot",
            )
        ])
        out = _match_swaps_to_ust_by_maturity(df)
        assert bool(out.loc[0, "matched_ust_maturity"]) is True
    finally:
        pd.options.mode.copy_on_write = False
