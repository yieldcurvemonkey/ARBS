"""Priority tests for detect_special_tenor.

Priority order (highest first):
  1. CONSECUTIVE FOMC meetings on eff and mat => FOMC
  2. Quarterly IMM effective + constant-maturity tenor => IMM
  else => STANDARD (with IMM_/FOMC_ label fallbacks)

An FOMC-dated swap is DEFINED by spanning exactly one meeting-to-meeting
window; a swap merely starting on a meeting date is not FOMC-typed.
Especially critical: when eff is both an IMM quarterly AND an FOMC meeting
(dates coincide), and mat is constant tenor, the IMM tier wins => IMM.
"""
import pandas as pd
import pytest

from SDRUtils.core.tenors import detect_special_tenor


# Fixture FOMC meeting pair: Apr 2026 and Jun 2026 (typical spacing).
# Real schedule values should come from load_fomc_schedule in integration
# tests; here we monkeypatch for unit isolation.
APR_EFF = pd.Timestamp("2026-04-28")
APR_MAT = pd.Timestamp("2026-06-16")   # next meeting eff
JUN_EFF = pd.Timestamp("2026-06-16")
JUN_MAT = pd.Timestamp("2026-07-28")
DEC_EFF = pd.Timestamp("2026-12-15")

IMM_Z26 = pd.Timestamp("2026-12-16")  # 3rd Wed of Dec 2026 = IMM Z26


def _patch_fomc(monkeypatch, meeting_dates):
    """Force get_fomc_label to return a label for dates in ``meeting_dates``,
    and align the meeting calendar so consecutiveness resolves against the
    same fixture dates."""
    def _fake(dt, tolerance_days=1):
        if dt is None:
            return None
        ts = pd.to_datetime(dt, errors="coerce")
        if pd.isna(ts):
            return None
        return f"FOMC_{ts.strftime('%Y%m%d')}" if ts.normalize() in meeting_dates else None
    monkeypatch.setattr("SDRUtils.core.tenors.get_fomc_label", _fake)
    monkeypatch.setattr(
        "SDRUtils.core.tenors._fomc_meeting_dates_sorted",
        lambda: sorted(d.date() for d in meeting_dates),
    )


def test_tier1_consecutive_fomc_both(monkeypatch):
    _patch_fomc(monkeypatch, {APR_EFF.normalize(), APR_MAT.normalize()})
    kind, conf, tags = detect_special_tenor(
        tenor_label="~2M",
        forward_label="spot",
        effective_date=APR_EFF,
        expiration_date=APR_MAT,
        is_forward=False,
    )
    assert kind == "FOMC"
    assert "FOMC" in tags


def test_tier2_imm_quarterly_plus_constant_tenor_wins(monkeypatch):
    # eff is IMM quarterly (Z26). Not an FOMC meeting in this fixture.
    _patch_fomc(monkeypatch, set())
    kind, conf, tags = detect_special_tenor(
        tenor_label="10Y",
        forward_label="IMM_Z2026",
        effective_date=IMM_Z26,
        expiration_date=pd.Timestamp("2036-12-16"),
        is_forward=True,
    )
    assert kind == "IMM"


def test_tier2_wins_over_tier3_when_eff_is_both_imm_and_fomc(monkeypatch):
    # IMM_Z26 happens to coincide with an FOMC meeting; mat is constant 10Y.
    # Must resolve to IMM (tier 2), not FOMC (tier 3).
    _patch_fomc(monkeypatch, {IMM_Z26.normalize()})
    kind, conf, tags = detect_special_tenor(
        tenor_label="10Y",
        forward_label="IMM_Z2026",
        effective_date=IMM_Z26,
        expiration_date=pd.Timestamp("2036-12-16"),
        is_forward=True,
    )
    assert kind == "IMM"


def test_fomc_eff_constant_tenor_mat_is_not_fomc(monkeypatch):
    # A swap merely STARTING on a meeting date (Apr 2026, not an IMM
    # quarterly) with a constant-maturity tail is not FOMC-dated — the
    # old tier 3 mislabeled these.
    _patch_fomc(monkeypatch, {APR_EFF.normalize()})
    kind, conf, tags = detect_special_tenor(
        tenor_label="10Y",
        forward_label="spot",
        effective_date=APR_EFF,
        expiration_date=pd.Timestamp("2036-04-28"),
        is_forward=True,
    )
    assert kind == "STANDARD"


def test_tier3_fomc_eff_nonconsecutive_fomc_mat(monkeypatch):
    _patch_fomc(monkeypatch, {APR_EFF.normalize(), DEC_EFF.normalize()})
    # Note: our tier1 check requires consecutive — patching
    # consecutive_meeting_pair to False would be cleaner, but the tier
    # resolver uses get_fomc_label presence only. Full consecutive logic
    # is exercised by the trade_tape-level tests.
    kind, _, tags = detect_special_tenor(
        tenor_label="FOMC_20261215",
        forward_label="spot",
        effective_date=APR_EFF,
        expiration_date=DEC_EFF,
        is_forward=True,
    )
    assert kind == "FOMC"


def test_standard_when_no_rules_match(monkeypatch):
    _patch_fomc(monkeypatch, set())
    kind, _, _ = detect_special_tenor(
        tenor_label="10Y",
        forward_label="spot",
        effective_date=pd.Timestamp("2026-04-15"),
        expiration_date=pd.Timestamp("2036-04-15"),
        is_forward=False,
    )
    assert kind == "STANDARD"
