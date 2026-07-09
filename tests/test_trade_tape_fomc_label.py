"""End-to-end labeling tests against the 3-tier priority.

Feeds hand-built DataFrames through TradeTape._enrich_context and
_build_enriched_label and asserts the final ``tape_label`` string.
"""
import pandas as pd
import pytest

from SDRUtils.analytics.trade_tape import TradeTape


@pytest.fixture
def base_row():
    return {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-03-15 14:30:00", tz="UTC"),
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
        "package_tenors": "10Y",
        "cleared": "Y",
        "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2026-03-18"),
        "expiration_date": pd.Timestamp("2036-03-18"),
        "is_unwind": False,
        "is_mac": False,
        "is_ufro": False,
        "is_block": False,
    }


def _compute(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    out = tape._build_enriched_label(out)
    return out


def test_tier1_consecutive_fomc_produces_short_label(base_row, monkeypatch):
    """eff=2026-04-29 (Apr26 FOMC), mat=2026-06-17 (apr26.mat / jun26.eff).
    Expect: 'FOMC APR26' in tape_label, no 10Y suffix."""
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-04-29"),
        "expiration_date": pd.Timestamp("2026-06-17"),
        "tenor_label": "~2M",
        "tenor_display": "~2M",
        "package_tenors": "~2M",
        "special_tenor_type": "FOMC",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == "APR26"
    assert "FOMC APR26" in out.loc[0, "tape_label"]
    # Short-hand: no trailing tenor on consecutive-FOMC trades
    assert "10Y" not in out.loc[0, "tape_label"]


def test_tier2_imm_quarterly_constant_tenor(base_row):
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-12-16"),  # IMM Z26
        "expiration_date": pd.Timestamp("2036-12-16"),
        "forward_label": "IMM_Z2026",
        "forward_start_years": 0.67,
        "special_tenor_type": "IMM",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == ""
    label = out.loc[0, "tape_label"]
    assert "IMM_Z2026" in label
    assert "10Y" in label
    assert "FOMC" not in label


def test_tier3_fomc_eff_constant_tenor_uses_imm_fallback(base_row):
    """Non-consecutive FOMC trades fall through to IMM forward labeling."""
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-04-29"),  # Apr26 FOMC, not IMM-Q
        "expiration_date": pd.Timestamp("2036-04-29"),
        "forward_label": "FOMC_APR2026",
        "special_tenor_type": "FOMC",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == ""


def test_tier3_fomc_to_fomc_nonconsecutive_uses_imm_fallback(base_row):
    """Non-consecutive FOMC-to-FOMC trades should NOT get FOMC labels."""
    row = dict(base_row)
    row.update({
        "effective_date": pd.Timestamp("2026-04-29"),
        "expiration_date": pd.Timestamp("2026-12-09"),  # Dec26 FOMC — skip
        "tenor_label": "FOMC_20261209",
        "tenor_display": "FOMC_20261209",
        "package_tenors": "FOMC_20261209",
        "special_tenor_type": "FOMC",
    })
    out = _compute([row])
    assert out.loc[0, "fomc_meeting_label"] == ""
    assert "FOMC APR26 DEC26" not in out.loc[0, "tape_label"]
