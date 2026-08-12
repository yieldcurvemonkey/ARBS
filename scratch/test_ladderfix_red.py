"""RED tests for the ladder-module review fixes. Ported into
tests/test_dealer_direction_ladder.py once green."""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import health, ladder, provenance
from SDRUtils.dealer_direction import types as T

from tests.test_dealer_direction_ladder import (
    _call, _krd, _ny, _series, _unit,
)


# --- A2: ladder-stage exclusions must reach the coverage table -------------

def _prov_frame(units, calls):
    return provenance.to_frame([
        provenance.build(u, None, c, pricing_clock_field="event_timestamp")
        for u, c in zip(units, calls)
    ])


def test_a_unit_the_ladder_threw_out_is_not_reported_in_ladder():
    units = [_unit("A"), _unit("B")]
    calls = [_call("A", 0.9), _call("B", 0.9)]
    rows, excluded = ladder.unit_ladder_rows(units, calls, _krd("A"))
    assert list(excluded["failure_reason"]) == [T.EXCL_PRICING_ERROR]

    prov = _prov_frame(units, calls)
    assert list(prov["failure_reason"]) == [None, None]      # the whole defect

    table = provenance.coverage_table(
        prov, dv01=pd.Series({"A": 1000.0, "B": 1000.0}),
        ladder_excluded=excluded)
    by = table.set_index("reason")["dv01_share"]
    assert by[T.EXCL_PRICING_ERROR] == pytest.approx(0.5)
    assert by[provenance.IN_LADDER] == pytest.approx(0.5)


def test_coverage_cannot_be_computed_without_the_ladder_exclusions():
    prov = pd.DataFrame([{"unit_key": "A", "failure_reason": None}])
    with pytest.raises(TypeError):
        provenance.coverage_table(prov, dv01=pd.Series({"A": 1.0}))


def test_a_ladder_exclusion_that_contradicts_the_call_is_loud():
    prov = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_NO_CURVE}])
    excl = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_DEAD_ZONE}])
    with pytest.raises(ValueError, match="disagree"):
        provenance.coverage_table(prov, dv01=pd.Series({"A": 1.0}),
                                  ladder_excluded=excl)
    # ...and re-applying the SAME reason is a no-op, so the join is idempotent
    same = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_NO_CURVE}])
    out = provenance.coverage_table(prov, dv01=pd.Series({"A": 1.0}),
                                    ladder_excluded=same)
    assert list(out["reason"]) == [T.EXCL_NO_CURVE]


def test_an_excluded_unit_missing_from_the_provenance_population_is_loud():
    prov = pd.DataFrame([{"unit_key": "A", "failure_reason": None}])
    excl = pd.DataFrame([{"unit_key": "GHOST", "failure_reason": T.EXCL_DEAD_ZONE}])
    with pytest.raises(ValueError, match="not in the coverage population"):
        provenance.coverage_table(prov, dv01=pd.Series({"A": 1.0}),
                                  ladder_excluded=excl)


# --- A3: a risk row for a unit not in `units` ------------------------------

def test_a_risk_row_for_a_unit_that_is_not_in_the_population_is_loud():
    ghost = pd.concat([_krd("A"), _krd("GHOST", value=9_000_000.0)])
    with pytest.raises(ValueError, match="not in"):
        ladder.unit_ladder_rows([_unit("A")], [_call("A", 0.9)], ghost)


# --- A4: the same unit twice -----------------------------------------------

def test_the_same_unit_passed_twice_is_loud_rather_than_double_counted():
    with pytest.raises(ValueError, match="twice"):
        ladder.unit_ladder_rows([_unit("A"), _unit("A")],
                                [_call("A", 0.9)], _krd("A"))


# --- A1: a renamed UnitPricing field must not read as never-priced ---------

class _RenamedPricing:
    unit_key = "U"
    curve_name = "USD-SOFR-1D"
    curve_timestamp = pd.Timestamp("2026-06-10T13:59:00Z")
    lag_seconds = 41.0                       # was snapshot_lag_seconds
    policy = "method=asof max_lag=60s allow_future=False on_miss=raise"


def test_a_renamed_pricing_field_raises_instead_of_reporting_never_priced():
    with pytest.raises(ValueError, match="snapshot_policy"):
        provenance.build(_unit("U"), _RenamedPricing(), _call("U", 0.9),
                         pricing_clock_field="execution_timestamp")


def test_a_priced_unit_with_no_recorded_policy_is_loud():
    priced = T.UnitPricing(
        unit_key="U", curve_name="USD-SOFR-1D",
        curve_timestamp=pd.Timestamp("2026-06-10T13:59:00Z"),
        snapshot_lag_seconds=41.0, snapshot_policy="",
        leg_mid_pct=[3.94], leg_pv01=[4500.0], structure_dv01=4500.0,
    )
    with pytest.raises(ValueError, match="no snapshot policy"):
        provenance.build(_unit("U"), priced, _call("U", 0.9),
                         pricing_clock_field="execution_timestamp")


# --- A5: rolling kappa on a short history ----------------------------------

def test_the_rolling_monitor_reports_no_data_rather_than_a_missing_column():
    rng = np.random.default_rng(3)
    signs = np.where(rng.random(30) < 0.5, 1.0, -1.0)
    out = health.rolling_recycling_kappa(_series(signs),
                                         _series(np.r_[0.0, signs[:-1]]),
                                         window_days=90)
    assert len(out) == 0
    assert list(out.columns) == ["window_end", "kappa", "hit_rate",
                                 "placebo_kappa_p95", "n_pairs",
                                 "reference_kappa", "status"]
    assert list(out["kappa"]) == []


# --- A6 / A7: the _require doctrine, applied to the value side -------------

def test_a_renamed_imputed_flag_column_is_loud_not_no_data():
    prov = pd.DataFrame({"unit_key": list("ABCD"),
                         "notional_imputed_flag": [True, False, False, False]})
    with pytest.raises(ValueError, match="notional_imputed"):
        health.imputed_notional_fraction(prov)
    with pytest.raises(ValueError, match="notional_imputed"):
        health.imputed_notional_fraction(
            prov, weights=pd.Series([700.0, 100.0, 100.0, 100.0],
                                    index=list("ABCD")))


def test_a_renamed_index_column_cannot_silently_disable_the_basis_alarm():
    as_of = datetime.date(2026, 6, 10)
    legs = pd.DataFrame({
        "as_of_date": [as_of] * 2, "effective_date": [as_of] * 2,
        "is_capped_flag": [False] * 2,           # was is_capped
        "index_name": ["BASIS", "BASIS"],        # was rate_index
        "priced": [True, True],
    })
    with pytest.raises(ValueError, match="is_capped"):
        health.pricing_success_by_stratum(legs)


# --- C: the degenerate marginal --------------------------------------------

def test_a_one_sided_classifier_alarms_even_with_no_placebo():
    """px = 1 forces kappa to exactly 0 whatever the other marginal does.

    On a series short enough that the placebo cannot be built, the only
    remaining test is the 0.10 warn floor, so a fully one-sided classifier
    reports WARN unless the degenerate flag fires.
    """
    rng = np.random.default_rng(5)
    n = 40
    x = np.ones(n)                                    # every day the same call
    y = np.where(rng.random(n) < 0.5, 1.0, -1.0)
    res = health.d2d_recycling_kappa(_series(x), _series(np.r_[0.0, y[:-1]]),
                                     horizon_days=1, n_bootstrap=0,
                                     placebo_shift_days=20, min_pairs=10)
    assert res.placebo_kappa_p95 is None, "the hole needs no placebo"
    assert res.kappa == pytest.approx(0.0)
    assert res.degenerate is True
    assert res.status == health.ALARM


# --- G: guards that cannot fire --------------------------------------------

def test_a_bounded_nearest_policy_is_not_the_strict_in_session_branch():
    """`method=nearest` serves a future curve to 1.09% of legs; a 60s bound
    does not make it the strict branch."""
    assert health.is_overnight_hole(
        "method=nearest max_lag=60s allow_future=True on_miss=none") is True
    assert health.is_overnight_hole(
        "method=asof max_lag=60s allow_future=True on_miss=raise") is True
    assert health.is_overnight_hole(
        "method=asof max_lag=60s allow_future=False on_miss=raise") is False


def test_a_horizon_longer_than_the_history_is_no_data_not_a_crash():
    res = health.d2d_recycling_kappa(_series([1.0, -1.0]), _series([1.0, -1.0]),
                                     horizon_days=10, n_bootstrap=0)
    assert res.status == health.NO_DATA


# --- C: the numbers in the reported rationale ------------------------------

def test_the_overnight_rationale_cites_the_measured_truncated_day_count():
    r = health._overnight_threshold().rationale
    assert "161" in r and "128" not in r
