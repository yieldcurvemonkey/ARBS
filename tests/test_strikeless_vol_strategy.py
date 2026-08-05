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
    assert list(out.columns) >= ["sign", "size", "reason", "dv01_usd"]
    # lag-1: the first row cannot act on its own day's information
    assert out["sign"].iloc[0] == 0
    assert out["sign"].iloc[1] == FLATTENER
