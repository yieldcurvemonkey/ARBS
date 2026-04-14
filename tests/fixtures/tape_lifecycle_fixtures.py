"""Sample DataFrames covering every lifecycle type for tape ingest tests.

Used by tape schema / write-path / API integration tests to exercise the
full lifecycle surface without pulling a real SDR dump.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pandas as pd


def _row(**kw) -> dict:
    base = {
        "trade_id": "T_0",
        "package_id": "P_0",
        "execution_timestamp": datetime(2026, 4, 14, 14, 30, tzinfo=timezone.utc),
        "effective_date": "2026-04-16",
        "expiration_date": "2031-04-16",
        "notional": 100_000_000.0,
        "notional_currency": "USD",
        "risk": 50_000.0,
        "fixed_rate": 0.045,
        "tenor_years": 5.0,
        "tenor_label": "5Y",
        "forward_start_years": 0.0,
        "forward_label": "Spot",
        "is_forward": False,
        "event_action": "NEWT",
        "event_type": None,
        "platform_identifier": "BLOOM-SEF",
        "cleared": "CLEARED",
        "upi_underlier_name": "USD-SOFR-COMPOUND",
        "unique_product_identifier": "QWERTYUIOP",
        "package_type": "OUTRIGHT",
        "package_indicator": False,
        "package_transaction_spread": None,
        "block_trade_election_indicator": False,
        "is_notional_capped": False,
        "non_standardized_term_indicator": False,
        "other_payment_type": None,
        "other_payment_amount": None,
        "estimated_pv01": 50_000.0,
        "product_type": "IRS",
    }
    base.update(kw)
    return base


def sample_classified_df() -> pd.DataFrame:
    """Return a DF with one row per lifecycle type the tape must show."""
    rows: List[dict] = [
        # NEW_RISK (baseline NEWT)
        _row(trade_id="T_NEWT_1", package_id="P_NEWT_1"),
        # UNWIND (forward_start_years < -0.02)
        _row(
            trade_id="T_UNW_1",
            package_id="P_UNW_1",
            forward_start_years=-0.05,
            forward_label="Unwind",
        ),
        # COMPRESSION via event_type
        _row(
            trade_id="T_CMP_1",
            package_id="P_CMP_1",
            event_action="TERM",
            event_type="COMP",
        ),
        # TERMINATION (non-compression TERM)
        _row(
            trade_id="T_TERM_1",
            package_id="P_TERM_1",
            event_action="TERM",
            event_type=None,
        ),
        # NOVATION_BORN (NOVA + NEWT)
        _row(
            trade_id="T_NOVA_BORN_1",
            package_id="P_NOVA_1",
            event_action="NEWT",
            event_type="NOVA",
        ),
        # NOVATION_TERMINATED (NOVA + TERM)
        _row(
            trade_id="T_NOVA_TERM_1",
            package_id="P_NOVA_1",
            event_action="TERM",
            event_type="NOVA",
        ),
        # RESET_OPTIMIZATION (short-dated compression-spec-like payload)
        _row(
            trade_id="T_RST_1",
            package_id="P_RST_1",
            tenor_years=0.25,
            tenor_label="3M",
            forward_start_years=0.0,
        ),
        # CORRECTION
        _row(
            trade_id="T_CORR_1",
            package_id="P_CORR_1",
            event_action="CORR",
        ),
        # CLEARING_TERMINATION
        _row(
            trade_id="T_CLR_1",
            package_id="P_CLR_1",
            event_action="TERM",
            event_type="CLRG",
        ),
        # EXERCISE_BORN
        _row(
            trade_id="T_XERC_1",
            package_id="P_XERC_1",
            event_action="NEWT",
            event_type="EXER",
        ),
        # Block
        _row(
            trade_id="T_BLK_1",
            package_id="P_BLK_1",
            block_trade_election_indicator=True,
        ),
        # Capped
        _row(
            trade_id="T_CAP_1",
            package_id="P_CAP_1",
            is_notional_capped=True,
        ),
        # Off-date (non-round tenor)
        _row(
            trade_id="T_ODT_1",
            package_id="P_ODT_1",
            tenor_years=6.87,
            tenor_label="7Y",
            expiration_date="2032-07-22",
        ),
        # 2-leg CURVE package
        _row(
            trade_id="T_CURVE_2Y",
            package_id="P_CURVE_1",
            tenor_years=2.0,
            tenor_label="2Y",
            package_type="CURVE",
            package_indicator=True,
        ),
        _row(
            trade_id="T_CURVE_10Y",
            package_id="P_CURVE_1",
            tenor_years=10.0,
            tenor_label="10Y",
            package_type="CURVE",
            package_indicator=True,
        ),
        # FOMC-dated (spot/effective immediately prior to a meeting date)
        _row(
            trade_id="T_FOMC_1",
            package_id="P_FOMC_1",
            effective_date="2026-04-29",
            expiration_date="2026-06-17",
        ),
    ]
    return pd.DataFrame(rows)


__all__ = ["sample_classified_df"]
