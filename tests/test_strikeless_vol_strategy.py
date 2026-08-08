import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.strategy import SignalConfig, build_signals, signal_state


def _row(**kw):
    base = {"be_over_realized": 1.0, "drift_t": 0.0, "residual_z": 0.0,
            "spread_vol_bp_day": 1.65, "iv_z": 0.0}
    base.update(kw)
    return pd.Series(base)


def test_cheap_breakeven_buys_convexity():
    st = signal_state(_row(be_over_realized=0.45, residual_z=2.0), SignalConfig())
    assert st["sign"] == FLATTENER
    assert st["size"] > 0


def test_rich_breakeven_sells_convexity():
    st = signal_state(_row(be_over_realized=1.6, residual_z=-2.0), SignalConfig())
    assert st["sign"] == STEEPENER


def test_fair_breakeven_is_flat():
    st = signal_state(_row(be_over_realized=1.0, residual_z=3.0), SignalConfig())
    assert st["sign"] == 0
    assert st["size"] == 0.0


def test_positive_drift_vetoes_a_mildly_cheap_flattener():
    cfg = SignalConfig()
    st = signal_state(_row(be_over_realized=0.78, drift_t=3.0, residual_z=2.0), cfg)
    assert st["sign"] == 0
    assert "drift" in st["reason"]


def test_positive_drift_does_not_veto_a_deeply_cheap_flattener():
    st = signal_state(
        _row(be_over_realized=0.35, drift_t=3.0, residual_z=2.0), SignalConfig()
    )
    assert st["sign"] == FLATTENER


def test_drift_does_not_veto_a_rich_steepener():
    # The `sign == FLATTENER and` scope on the drift veto (strategy.py:89) is
    # correct today, but a mutation dropping that scope passes all other
    # drift tests unnoticed -- every one of them uses a flattener-range
    # be_over_realized. Drift is a structural cost to flatteners specifically
    # (a positively-sloped carry curve hurts the long-convexity receiver);
    # vetoing a steepener for the same reason would be economically
    # backwards, since a positive drift is what a rich-side carry steepener
    # is collecting.
    st = signal_state(
        _row(be_over_realized=1.6, drift_t=5.0, residual_z=-2.0), SignalConfig()
    )
    assert st["sign"] == STEEPENER


def test_nan_drift_vetoes_a_mildly_cheap_flattener_fail_closed():
    # Drift's isfinite guard is separate from be's and z's -- reproduced
    # missing before this fix: a NaN drift_t compared with `>` is always
    # False, so `drift_t > cfg.drift_t_gate` silently fails to veto, exactly
    # when the gate has no information to confirm the position is safe.
    st = signal_state(
        _row(be_over_realized=0.78, drift_t=float("nan"), residual_z=2.0),
        SignalConfig(),
    )
    assert st["sign"] == 0
    assert "drift" in st["reason"]


def test_nan_drift_does_not_veto_a_deeply_cheap_flattener():
    # Fail-closed on NaN must still respect the deep-cheap bypass: a NaN
    # drift on a deeply cheap flattener behaves like any other drift value
    # here, i.e. it does not reach the veto check at all.
    st = signal_state(
        _row(be_over_realized=0.35, drift_t=float("nan"), residual_z=2.0),
        SignalConfig(),
    )
    assert st["sign"] == FLATTENER


def test_nan_iv_z_gates_the_steepener_fail_closed():
    # Same fail-closed rationale as drift, for the short-side vol-spike gate:
    # a NaN iv_z cannot confirm the steepener is safe to hold, so it must
    # gate the position rather than let a `>` comparison silently pass it.
    st = signal_state(
        _row(be_over_realized=1.6, residual_z=-2.0, iv_z=float("nan")),
        SignalConfig(),
    )
    assert st["sign"] == 0


def test_small_residual_z_means_no_new_risk():
    st = signal_state(_row(be_over_realized=0.45, residual_z=0.3), SignalConfig())
    assert st["size"] == 0.0


def test_vol_spike_gates_the_short_convexity_side_only():
    cfg = SignalConfig()
    short = signal_state(_row(be_over_realized=1.6, residual_z=-2.0, iv_z=3.0), cfg)
    long_ = signal_state(_row(be_over_realized=0.45, residual_z=2.0, iv_z=3.0), cfg)
    assert short["sign"] == 0
    assert long_["sign"] == FLATTENER


def test_short_side_can_be_disabled_entirely():
    cfg = SignalConfig(short_side_enabled=False)
    st = signal_state(_row(be_over_realized=1.6, residual_z=-2.0), cfg)
    assert st["sign"] == 0


def test_size_is_inverse_to_spread_vol():
    cfg = SignalConfig()
    quiet = signal_state(_row(be_over_realized=0.45, residual_z=2.0,
                              spread_vol_bp_day=1.0), cfg)
    noisy = signal_state(_row(be_over_realized=0.45, residual_z=2.0,
                              spread_vol_bp_day=4.0), cfg)
    assert quiet["size"] > noisy["size"]


def test_size_scales_with_residual_stretch():
    # Added post-mutation-testing: the brief's tests establish that size is
    # zero below z_entry and positive above it, but none of them pin the
    # *magnitude* of the z-scaling -- a mutation that hardcoded z_scale=1.0
    # for any |z| >= z_entry passed all 10 brief tests unnoticed. This test
    # holds be_over_realized and spread_vol_bp_day fixed and varies only
    # |z|, so it fails under that exact mutation (both sizes come out equal)
    # and passes under the real risk-parity-times-stretch formula.
    cfg = SignalConfig()
    mildly_stretched = signal_state(
        _row(be_over_realized=0.45, residual_z=1.6), cfg
    )
    deeply_stretched = signal_state(
        _row(be_over_realized=0.45, residual_z=3.0), cfg
    )
    assert deeply_stretched["size"] > mildly_stretched["size"]


def test_size_matches_the_documented_risk_parity_formula():
    # Strengthens test_size_scales_with_residual_stretch, which only pins an
    # ordering: a mutation that replaces the z_size_cap normaliser with an
    # unrelated constant (e.g. `z_scale = min(abs(z), cap) / 10.0`) still
    # passes that ordering test while landing 3-5x off the intended
    # risk-parity size. This test pins the formula itself against a known
    # row, computed by hand from SignalConfig()'s defaults
    # (target_vol_bp_day=1.32, this row's spread_vol_bp_day=1.65,
    # z_size_cap=3.0):
    #   vol_scale = 1.32 / 1.65        = 0.8
    #   z_scale   = min(1.6, 3.0) / 3.0 = 0.533333...
    #   size      = 0.8 * 0.533333...   = 0.426667 (well under size_cap=1.0)
    cfg = SignalConfig()
    st = signal_state(_row(be_over_realized=0.45, residual_z=1.6), cfg)
    assert st["size"] == pytest.approx(0.4266667, abs=1e-4)


def test_build_signals_is_row_wise_and_lagged():
    panel = pd.DataFrame(
        {
            "be_over_realized": [0.45, 0.45],
            "drift_t": [0.0, 0.0],
            "residual_z": [2.0, 2.0],
            "spread_vol_bp_day": [1.65, 1.65],
            "iv_z": [0.0, 0.0],
        },
        index=pd.bdate_range("2026-08-03", periods=2),
    )
    out = build_signals(panel, SignalConfig())
    # Not `list(out.columns) >= [...]` -- that is a Python list comparison
    # (lexicographic), not a "contains at least" check, and only happens to
    # pass because insertion order matches; a column reorder would fail it
    # even with every required column present. This is the brief's own
    # defect, carried verbatim into the original spec.
    assert set(["sign", "size", "reason", "dv01_usd"]).issubset(out.columns)
    # lag-1: the first row cannot act on its own day's information
    assert out["sign"].iloc[0] == 0
    assert out["sign"].iloc[1] == FLATTENER
