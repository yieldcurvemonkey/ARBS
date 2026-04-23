"""Street-convention package DV01 for the front-of-tape RISK cell.

Desk convention:

* OUTRIGHT: the trade's own signed DV01.
* CURVE: sum of absolute leg DV01s (both wings roughly equal, so the
  headline is ~2x a single leg). A 2Y/10Y curve with legs +25.1k / +24.9k
  reports as 50k, not 24.9k.
* FLY: sum of absolute leg DV01s (= 2x the belly DV01 since wings ≈
  belly/2 each). A 50k belly + two 25k wings reports as 100k.

Why not signed sums: CURVE / FLY legs carry opposite signs by
construction, so a signed sum cancels out. Gross (abs) sum gives the
traded size the desk actually headlines.
"""
from __future__ import annotations

import pandas as pd
import pytest

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import _structural_risk


def _risk(values):
    return pd.Series(values, dtype="float64")


def _tenors(values):
    return pd.Series(values, dtype="float64")


def test_outright_uses_signed_sum():
    """Single-leg trade — sum preserves sign."""
    assert _structural_risk(_risk([+50_100.0]), _tenors([10.0]), "OUTRIGHT") == pytest.approx(50_100.0)
    assert _structural_risk(_risk([-41_500.0]), _tenors([10.0]), "OUTRIGHT") == pytest.approx(-41_500.0)


def test_curve_uses_max_absolute_leg_dv01():
    """User spec (revised): CURVE headline = single leg risk, not the sum.
    Pick the largest-|DV01| leg — that's how the desk quotes the size.
    5Y/30Y curve with 5Y=25k / 30Y=24k reports 25k, not 49k."""
    result = _structural_risk(
        _risk([+25_000.0, +24_000.0]), _tenors([5.0, 30.0]), "CURVE"
    )
    assert result == pytest.approx(25_000.0)


def test_curve_with_opposite_signed_legs_uses_max_absolute():
    """A real CURVE in SDR has legs with opposite signs (pay one,
    receive the other). Still use max absolute, not signed."""
    result = _structural_risk(
        _risk([+25_100.0, -24_900.0]), _tenors([2.0, 10.0]), "CURVE"
    )
    assert result == pytest.approx(25_100.0)


def test_curve_matches_observed_5y_30y():
    """Regression fixture for the 2026-04-10 15:39:43 IMM_M2026 5Y/30Y
    UFRO curve: +24k (30Y leg) and +25k (5Y leg). Headline = 25k."""
    result = _structural_risk(
        _risk([+25_000.0, +24_000.0]), _tenors([5.0, 30.0]), "CURVE"
    )
    assert result == pytest.approx(25_000.0)


def test_fly_uses_belly_dv01():
    """User spec update: RISK for a FLY = belly DV01 (middle-tenor leg),
    NOT the sum. 50k belly + 25k + 25k wings -> headline 50k.

    Rationale: the desk quotes flies by belly size. Wings are auto-
    implied (= belly/2 each), so surfacing the belly alone is the least
    ambiguous headline. Sign is dropped so the column always shows a
    positive size for multi-leg structures."""
    result = _structural_risk(
        _risk([+25_000.0, -50_000.0, +25_000.0]),
        _tenors([5.0, 7.0, 9.0]),
        "FLY",
    )
    assert result == pytest.approx(50_000.0)


def test_fly_matches_observed_3y5y7y_imm():
    """Regression fixture for the 2026-04-10 IMM_M2026 3Y/5Y/7Y fly:
    belly +19.9k, wings +10.1k and +9.8k. Headline = belly = 19.9k."""
    result = _structural_risk(
        _risk([+10_100.0, +19_900.0, +9_800.0]),
        _tenors([3.0, 5.0, 7.0]),
        "FLY",
    )
    assert result == pytest.approx(19_900.0)


def test_fly_belly_uses_middle_tenor_even_when_unsorted():
    """Legs may arrive in any order — belly selection must key off tenor
    ranking, not input order."""
    result = _structural_risk(
        _risk([-50_000.0, +25_000.0, +25_000.0]),  # belly first in input
        _tenors([7.0, 5.0, 9.0]),                  # tenors: middle=7Y (belly)
        "FLY",
    )
    assert result == pytest.approx(50_000.0)


def test_fly_two_leg_input_picks_longer_tenor_as_belly():
    """Degenerate 2-leg 'fly' (shouldn't happen in practice but could
    sneak through a detector bug) — len // 2 picks index 1 (the longer
    tenor)."""
    result = _structural_risk(
        _risk([+12_000.0, +18_000.0]),
        _tenors([5.0, 10.0]),
        "FLY",
    )
    assert result == pytest.approx(18_000.0)


def test_unknown_trade_type_falls_back_to_signed_sum():
    """Anything that isn't CURVE/FLY keeps the legacy sum behaviour."""
    result = _structural_risk(
        _risk([+10_000.0, +20_000.0]), _tenors([5.0, 10.0]), "MATCHED_MATURITY"
    )
    assert result == pytest.approx(30_000.0)


def test_empty_risk_returns_none():
    assert _structural_risk(_risk([]), _tenors([]), "CURVE") is None
