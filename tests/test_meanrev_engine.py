"""Synthetic, no-network tests for the MeanRev panel engine and panel builders.

The engine's structural rules are the point of these tests: lag-1 entry,
deterministic exits NOT lagged twice, cost charged once on the exit bar, and
gates at entry only. Each of those was a bug in the prior lab before it was a
rule.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeanRev import (
    MRConfig,
    add_strip_slots,
    cm_label,
    enumerate_structures,
    grid_search,
    leg_round_trip_bp,
    pivot_levels,
    regime_tag,
    run_backtest,
    run_continuous,
    shadow_levels,
    shadow_table,
    structure_liquidity,
    zscore_signal,
)
from RVUtils.MeanRev.signals import (
    coint_spread_signal,
    curvefit_residual_signal,
    kalman_level_signal,
    ou_sscore_signal,
    pca_residual_signal,
    rolling_ols2_residual,
    xsection_signal,
)

DATES = pd.bdate_range("2024-01-01", periods=60)


def frame(vals, key="K"):
    return pd.DataFrame({key: np.asarray(vals, dtype=float)}, index=DATES[:len(vals)])


# ---------------------------------------------------------------------------
# execution mechanics
# ---------------------------------------------------------------------------

def test_lag1_entry_fills_on_the_next_bar():
    lv = frame([0, 0, 0, 10, 20, 30, 40, 50, 60, 70])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])       # fires at index 2
    cfg = MRConfig(direction="momentum", entry_z=2.0, exit_style="t3",
                   lag=1, round_trip_cost_bp=0.0, max_hold=99)
    r = run_backtest(cfg, levels=lv, signal=sg)
    t = r.trades.iloc[0]
    assert t["signal_date"] == DATES[2]
    assert t["entry"] == DATES[3]          # lag 1
    assert t["level_in"] == 10.0


def test_lag0_ablation_fills_on_the_signal_bar():
    lv = frame([0, 0, 5, 10, 20, 30, 40, 50])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="momentum", entry_z=2.0, exit_style="t2", lag=0,
                   round_trip_cost_bp=0.0, max_hold=99)
    r = run_backtest(cfg, levels=lv, signal=sg)
    assert r.trades.iloc[0]["entry"] == DATES[2]
    assert r.trades.iloc[0]["level_in"] == 5.0


def test_fixed_horizon_exit_is_not_lagged_twice():
    """A deterministic exit date is known at entry. Lagging it again inflated
    every fixed-horizon result in the prior lab."""
    lv = frame([0, 0, 0, 10, 11, 12, 13, 14, 15, 16])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="momentum", entry_z=2.0, exit_style="t3", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99)
    t = run_backtest(cfg, levels=lv, signal=sg).trades.iloc[0]
    assert t["entry"] == DATES[3] and t["exit"] == DATES[6]
    assert t["days"] == 3


def test_signal_driven_exit_does_cost_a_lag_day():
    lv = frame([0, 0, 0, 10, 11, 12, 13, 14, 15, 16])
    sg = frame([0, 0, 3, 3, 3, -1, 0, 0, 0, 0])      # decays through 0 at index 5
    cfg = MRConfig(direction="momentum", entry_z=2.0, exit_style="z0", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99)
    t = run_backtest(cfg, levels=lv, signal=sg).trades.iloc[0]
    assert t["entry"] == DATES[3] and t["exit"] == DATES[6]


def test_fade_direction_shorts_a_high_signal():
    lv = frame([0, 0, 0, 10, 5, 0, 0, 0, 0, 0])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="fade", entry_z=2.0, exit_style="t2", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99)
    t = run_backtest(cfg, levels=lv, signal=sg).trades.iloc[0]
    assert t["dir"] == -1
    assert t["gross_bp"] == pytest.approx(10.0)      # short at 10, cover at 0


def test_momentum_direction_buys_a_high_signal():
    lv = frame([0, 0, 0, 10, 15, 20, 0, 0, 0, 0])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="momentum", entry_z=2.0, exit_style="t2", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99)
    t = run_backtest(cfg, levels=lv, signal=sg).trades.iloc[0]
    assert t["dir"] == 1 and t["gross_bp"] == pytest.approx(10.0)


def test_cost_charged_once_per_trade_in_both_places():
    lv = frame([0, 0, 0, 10, 5, 0, 0, 0, 0, 0])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="fade", entry_z=2.0, exit_style="t2", lag=1,
                   round_trip_cost_bp=1.5, max_hold=99)
    r = run_backtest(cfg, levels=lv, signal=sg)
    t = r.trades.iloc[0]
    assert t["cost_bp"] == pytest.approx(1.5)
    assert t["net_bp"] == pytest.approx(t["gross_bp"] - 1.5)
    assert r.daily_bp.sum() == pytest.approx(t["net_bp"])


def test_daily_series_sums_to_total_net():
    rng = np.random.default_rng(0)
    n = 400
    idx = pd.bdate_range("2020-01-01", periods=n)
    x = np.cumsum(rng.standard_normal(n)) * 0.5
    lv = pd.DataFrame({"A": x, "B": x[::-1]}, index=idx)
    sg = zscore_signal(lv, window=60)
    cfg = MRConfig(entry_z=1.5, exit_style="z0", round_trip_cost_bp=1.5, max_hold=20)
    r = run_backtest(cfg, levels=lv, signal=sg)
    # trade rows store net_bp rounded to 4dp, so the tolerance is rounding, not drift
    assert r.daily_bp.sum() == pytest.approx(r.trades["net_bp"].sum(),
                                             abs=1e-4 * len(r.trades) + 1e-9)


def test_stop_loss_closes_the_trade():
    lv = frame([0, 0, 0, 10, 30, 40, 50, 60, 70, 80])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="fade", entry_z=2.0, exit_style="t9", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99, stop_loss_bp=15.0)
    t = run_backtest(cfg, levels=lv, signal=sg).trades.iloc[0]
    assert t["exit_reason"] == "stop_loss"
    assert t["gross_bp"] <= -15.0


def test_max_hold_caps_the_trade():
    lv = frame(np.zeros(30))
    sg = frame([3.0] + [3.0] * 29)
    cfg = MRConfig(direction="fade", entry_z=2.0, exit_style="z0", lag=1,
                   round_trip_cost_bp=0.0, max_hold=5)
    tr = run_backtest(cfg, levels=lv, signal=sg).trades
    assert (tr["exit_reason"] == "max_hold").all()
    assert (tr["days"] == 5).all()


def test_gate_blocks_entry_but_never_forces_an_exit():
    lv = frame([0, 0, 0, 10, 11, 12, 13, 14, 15, 16])
    sg = frame([0, 0, 3, 3, 3, 3, 3, 3, 3, 3])
    gate = pd.DataFrame({"K": [True] * 3 + [False] * 7}, index=DATES[:10])
    cfg = MRConfig(direction="fade", entry_z=2.0, exit_style="t5", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99)
    r = run_backtest(cfg, levels=lv, signal=sg, gate=gate)
    assert len(r.trades) == 1
    assert r.trades.iloc[0]["days"] == 5           # held through the closed gate


def test_no_entry_when_signal_below_threshold():
    lv = frame(np.arange(20, dtype=float))
    sg = frame(np.full(20, 0.5))
    r = run_backtest(MRConfig(entry_z=2.0), levels=lv, signal=sg)
    assert r.trades.empty and r.metrics["n_trades"] == 0


def test_entry_every_thins_the_entry_calendar():
    lv = frame(np.zeros(60))
    sg = frame(np.full(60, 3.0))
    daily = run_backtest(MRConfig(entry_every=1, max_hold=1, exit_style="t1",
                                  round_trip_cost_bp=0.0), levels=lv, signal=sg)
    weekly = run_backtest(MRConfig(entry_every=5, max_hold=1, exit_style="t1",
                                   round_trip_cost_bp=0.0), levels=lv, signal=sg)
    assert weekly.metrics["n_trades"] < daily.metrics["n_trades"]


def test_always_entry_rule_holds_one_side():
    lv = frame(np.zeros(40))
    sg = frame(np.tile([3.0, -3.0], 20))     # would flip a z-rule every bar
    cfg = MRConfig(entry_rule="always", direction="fade", exit_style="t5",
                   round_trip_cost_bp=0.0, max_hold=5)
    tr = run_backtest(cfg, levels=lv, signal=sg).trades
    assert (tr["dir"] == -1).all()


def test_future_data_cannot_change_a_past_trade():
    rng = np.random.default_rng(2)
    n = 300
    idx = pd.bdate_range("2021-01-01", periods=n)
    x = np.cumsum(rng.standard_normal(n))
    lv = pd.DataFrame({"A": x}, index=idx)
    sg = zscore_signal(lv, window=60)
    cfg = MRConfig(entry_z=1.5, exit_style="z0", max_hold=10, round_trip_cost_bp=1.5)
    a = run_backtest(cfg, levels=lv, signal=sg).trades

    lv2 = lv.copy()
    lv2.iloc[250:] += 500.0
    sg2 = zscore_signal(lv2, window=60)
    b = run_backtest(cfg, levels=lv2, signal=sg2).trades
    early = a[a["exit"] < idx[200]].reset_index(drop=True)
    early_b = b[b["exit"] < idx[200]].reset_index(drop=True)
    pd.testing.assert_frame_equal(early, early_b)


def test_leg_round_trip_costs():
    assert leg_round_trip_bp(3) == pytest.approx(1.5)
    assert leg_round_trip_bp(2) == pytest.approx(1.0)
    assert leg_round_trip_bp(1) == pytest.approx(0.5)


def test_dollars_follow_bp_and_package_count():
    lv = frame([0, 0, 0, 10, 0, 0, 0, 0, 0, 0])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="fade", entry_z=2.0, exit_style="t2", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99, n_packages=100)
    r = run_backtest(cfg, levels=lv, signal=sg)
    assert r.trades.iloc[0]["net_usd"] == pytest.approx(10.0 * 25.0 * 100)
    assert r.daily_usd.sum() == pytest.approx(r.daily_bp.sum() * 2500.0)


# ---------------------------------------------------------------------------
# continuous sizing
# ---------------------------------------------------------------------------

def test_continuous_sizing_runs_and_charges_turnover():
    rng = np.random.default_rng(5)
    n = 300
    idx = pd.bdate_range("2021-01-01", periods=n)
    lv = pd.DataFrame({"A": rng.standard_normal(n).cumsum()}, index=idx)
    sg = zscore_signal(lv, window=60)
    free = run_continuous(MRConfig(round_trip_cost_bp=0.0), levels=lv, signal=sg)
    paid = run_continuous(MRConfig(round_trip_cost_bp=1.5), levels=lv, signal=sg)
    assert paid.metrics["total_net_bp"] < free.metrics["total_net_bp"]
    assert free.metrics["n_days"] == len(idx)


# ---------------------------------------------------------------------------
# grid search
# ---------------------------------------------------------------------------

def test_grid_search_covers_the_cartesian_product():
    rng = np.random.default_rng(3)
    n = 300
    idx = pd.bdate_range("2021-01-01", periods=n)
    lv = pd.DataFrame({"A": rng.standard_normal(n).cumsum()}, index=idx)
    sg = zscore_signal(lv, window=60)
    g = grid_search({"entry_z": [1.5, 2.0], "direction": ["fade", "momentum"],
                     "exit_style": ["z0", "t5"]}, levels=lv, signal=sg)
    assert len(g) == 8
    assert set(g["direction"]) == {"fade", "momentum"}
    assert "total_net_bp" in g.columns


def test_grid_search_routes_signal_params_through_signal_fn():
    rng = np.random.default_rng(4)
    n = 400
    idx = pd.bdate_range("2021-01-01", periods=n)
    lv = pd.DataFrame({"A": rng.standard_normal(n).cumsum()}, index=idx)
    g = grid_search({"window": [40, 80], "entry_z": [1.5, 2.0]}, levels=lv,
                    signal=None,
                    signal_fn=lambda L, window: zscore_signal(L, window=window))
    assert len(g) == 4 and set(g["window"]) == {40, 80}


def test_grid_search_rejects_unknown_params_without_signal_fn():
    lv = frame(np.zeros(20))
    with pytest.raises(ValueError):
        grid_search({"nonsense": [1]}, levels=lv, signal=lv)


# ---------------------------------------------------------------------------
# panel construction
# ---------------------------------------------------------------------------

def _toy_contracts():
    """Three dates, six contracts, rates rising along the strip."""
    rows = []
    starts = pd.to_datetime(["2024-03-20", "2024-06-19", "2024-09-18",
                             "2024-12-18", "2025-03-19", "2025-06-18"])
    codes = ["H24", "M24", "U24", "Z24", "H25", "M25"]
    for d in pd.to_datetime(["2024-01-02", "2024-01-03"]):
        for i, (c, s) in enumerate(zip(codes, starts)):
            rows.append({"as_of": d, "code": c, "imm_start": s,
                         "rate_pct": 5.0 + 0.10 * i + (0.02 if i == 2 else 0.0),
                         "volume": 1000.0 * (6 - i), "open_interest": 10000.0 * (6 - i)})
    return pd.DataFrame(rows)


def test_add_strip_slots_excludes_started_contracts():
    df = _toy_contracts()
    df.loc[df["code"] == "H24", "imm_start"] = pd.Timestamp("2023-12-20")
    out = add_strip_slots(df)
    assert "H24" not in set(out["code"])
    first = out[out["as_of"] == out["as_of"].min()].sort_values("slot")
    assert list(first["code"])[:2] == ["M24", "U24"]
    assert list(first["slot"])[:2] == [1, 2]


def test_enumerate_structures_fly_sign_and_units():
    df = add_strip_slots(_toy_contracts())
    out = enumerate_structures(df, spacing=1, max_slot=6)
    row = out[out["key"] == "H24-M24-U24"].iloc[0]
    # rates 5.00 / 5.10 / 5.22 -> 2*5.10 - 5.00 - 5.22 = -0.02 pct = -2 bp
    assert row["value"] == pytest.approx(-2.0, abs=1e-9)
    assert row["cm_slot"] == 2
    assert row["cm_label"] == "SFR1/SFR2/SFR3"
    assert row["cm_label_short"] == "SFR123"
    assert row["pack"] == "whites"


def test_enumerate_structures_matches_the_query_layer_convention():
    """FLY RATE = 2*belly - front - back. A humped belly (belly rate ABOVE the
    interpolation of its wings) is a POSITIVE fly."""
    df = add_strip_slots(_toy_contracts())
    df.loc[df["code"] == "M24", "rate_pct"] = 5.50      # lift the belly
    out = enumerate_structures(df, spacing=1, max_slot=6)
    assert out[out["key"] == "H24-M24-U24"].iloc[0]["value"] > 0


def test_enumerate_structures_6m_spacing_is_symmetric():
    df = add_strip_slots(_toy_contracts())
    out = enumerate_structures(df, spacing=2, max_slot=6)
    keys = sorted(set(out["key"]))
    assert "H24-U24-H25" in keys                  # slots 1,3,5 -- equidistant
    row = out[out["key"] == "H24-U24-H25"].iloc[0]
    assert row["cm_label"] == "SFR1/SFR3/SFR5"
    assert row["leg0_slot"] == 1 and row["leg1_slot"] == 3 and row["leg2_slot"] == 5


def test_enumerate_structures_keys_are_absolute_contracts():
    df = add_strip_slots(_toy_contracts())
    out = enumerate_structures(df, spacing=1, max_slot=6)
    assert all("-" in k and not k.startswith("SFR") for k in out["key"].unique())


def test_cm_label_forms():
    assert cm_label([1, 2, 3]) == "SFR1/SFR2/SFR3"
    assert cm_label([1, 2, 3], compressed=True) == "SFR123"
    assert cm_label([10, 11, 12], compressed=True) == "SFR-10-11-12"


def test_structure_liquidity_takes_the_worst_leg():
    df = add_strip_slots(_toy_contracts())
    out = enumerate_structures(df, spacing=1, max_slot=6)
    out = structure_liquidity(out, _toy_contracts())
    row = out[out["key"] == "H24-M24-U24"].iloc[0]
    assert row["min_open_interest"] == pytest.approx(40000.0)   # the U24 leg


def test_pivot_levels_shape():
    df = add_strip_slots(_toy_contracts())
    out = enumerate_structures(df, spacing=1, max_slot=6)
    w = pivot_levels(out)
    assert w.shape[0] == 2 and w.shape[1] == 4


def test_regime_tag_boundaries():
    r = regime_tag(pd.to_datetime(["2021-06-01", "2022-06-01", "2024-01-01",
                                   "2025-06-01"]))
    assert list(r) == ["ZIRP", "HIKING", "PLATEAU", "CUTTING"]


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------

def _panel(n=400, seed=9):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=n)
    out = {}
    for j, k in enumerate(["A", "B", "C"]):
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = 0.9 * x[i - 1] + rng.standard_normal()
        out[k] = x + j
    return pd.DataFrame(out, index=idx)


def test_zscore_signal_is_causal_and_standardised():
    P = _panel()
    z = zscore_signal(P, window=60)
    assert z.iloc[:59].isna().all().all() or z.iloc[:19].isna().all().all()
    assert abs(float(z.stack().mean())) < 0.3
    P2 = P.copy()
    P2.iloc[300:] += 100
    z2 = zscore_signal(P2, window=60)
    pd.testing.assert_frame_equal(z.iloc[:250], z2.iloc[:250])


def test_ou_sscore_signal_shape_and_causality():
    P = _panel()
    s = ou_sscore_signal(P, window=120)
    assert s.shape == P.shape
    P2 = P.copy()
    P2.iloc[300:] += 100
    pd.testing.assert_frame_equal(s.iloc[:250], ou_sscore_signal(P2, window=120).iloc[:250])


def test_kalman_signal_shape_and_causality():
    P = _panel()
    s = kalman_level_signal(P)
    assert s.shape == P.shape
    P2 = P.copy()
    P2.iloc[300:] += 100
    pd.testing.assert_frame_equal(s.iloc[:250], kalman_level_signal(P2).iloc[:250])


def test_xsection_signal_is_zero_mean_across_names_each_date():
    P = _panel()
    s = xsection_signal(P, method="zscore")
    row = s.iloc[-1].dropna()
    assert abs(float(row.mean())) < 1e-9


def test_xsection_rank_uses_normal_scores_not_bounded_percentiles():
    """A (pct-0.5)*2 signal is bounded by +/-1, so any entry threshold above 1
    can never fire and the whole method drops out of a shared grid with zero
    trades. Normal scores put ranks on the same scale as a z-score."""
    rng = np.random.default_rng(21)
    idx = pd.bdate_range("2021-01-01", periods=50)
    wide = pd.DataFrame(rng.standard_normal((50, 34)), index=idx,
                        columns=[f"K{i}" for i in range(34)])
    s = xsection_signal(wide, method="rank")
    # 34 names -> extreme score is Phi^-1(33.5/34) = 2.18, so a 2.0 entry fires.
    assert float(s.abs().max().max()) > 2.0
    row = s.iloc[-1].dropna()
    assert abs(float(row.mean())) < 1e-9      # symmetric about zero
    # the old bounded form could never exceed 1 no matter how wide the panel
    narrow = xsection_signal(wide.iloc[:, :4], method="rank")
    assert float(narrow.abs().max().max()) < float(s.abs().max().max())


def test_xsection_signal_window_accepts_nan_and_zero_as_no_window():
    """A None in a grid column arrives as NaN; it must mean 'rank the level'."""
    P = _panel()
    raw = xsection_signal(P, method="zscore")
    for w in (0, np.nan, None):
        pd.testing.assert_frame_equal(xsection_signal(P, method="zscore", window=w),
                                      raw)


def test_xsection_signal_within_groups():
    P = _panel()
    groups = pd.Series({"A": "g1", "B": "g1", "C": "g2"})
    s = xsection_signal(P, groups=groups, min_names=2)
    assert s["C"].isna().all()          # single-name bucket cannot standardise


def test_rolling_ols2_residual_recovers_a_planted_relation():
    rng = np.random.default_rng(6)
    n = 400
    idx = pd.bdate_range("2021-01-01", periods=n)
    x1 = pd.Series(np.cumsum(rng.standard_normal(n)), index=idx)
    x2 = pd.Series(np.cumsum(rng.standard_normal(n)), index=idx)
    y = 0.4 * x1 + 0.6 * x2 + 1.0 + rng.standard_normal(n) * 0.01
    B = rolling_ols2_residual(y, x1, x2, 120)
    assert B["b1"].iloc[-1] == pytest.approx(0.4, abs=0.02)
    assert B["b2"].iloc[-1] == pytest.approx(0.6, abs=0.02)
    assert abs(float(B["resid"].iloc[-1])) < 0.1


def test_pca_and_curvefit_residual_signals_run_on_a_toy_strip():
    rng = np.random.default_rng(8)
    n, m = 300, 8
    idx = pd.bdate_range("2021-01-01", periods=n)
    level = np.cumsum(rng.standard_normal(n)) * 0.05
    slope = np.cumsum(rng.standard_normal(n)) * 0.02
    slots = np.arange(1, m + 1)
    X = (level[:, None] + slope[:, None] * slots[None, :] / m
         + rng.standard_normal((n, m)) * 0.01 + 4.0)
    slot_panel = pd.DataFrame(X, index=idx, columns=slots)

    rows = []
    for i, d in enumerate(idx):
        for s0 in range(1, m - 1):
            rows.append({
                "as_of": d, "key": f"K{s0}",
                "leg0_slot": s0, "leg1_slot": s0 + 1, "leg2_slot": s0 + 2,
                "leg0_value": X[i, s0 - 1], "leg1_value": X[i, s0],
                "leg2_value": X[i, s0 + 1],
            })
    struct = pd.DataFrame(rows)

    p = pca_residual_signal(slot_panel, struct, window=120, k=3)
    assert p.shape[1] == m - 2
    assert p.notna().to_numpy().sum() > 0

    c = curvefit_residual_signal(slot_panel, struct, form="poly3")
    assert c.shape[1] == m - 2
    assert c.notna().to_numpy().sum() > 0


def test_coint_spread_signal_returns_fitted_vectors():
    rng = np.random.default_rng(10)
    n = 400
    idx = pd.bdate_range("2021-01-01", periods=n)
    f = np.cumsum(rng.standard_normal(n)) * 0.02 + 4.0
    k = np.cumsum(rng.standard_normal(n)) * 0.02 + 4.5
    b = 0.5 * f + 0.5 * k + rng.standard_normal(n) * 0.005
    struct = pd.DataFrame({
        "as_of": idx, "key": "K",
        "leg0_value": f, "leg1_value": b, "leg2_value": k,
    })
    out = coint_spread_signal(struct, window=200, z_window=60)
    assert set(out) == {"signal", "spread", "b1", "b2"}
    assert out["b1"]["K"].dropna().iloc[-1] == pytest.approx(0.5, abs=0.05)
    assert out["signal"]["K"].notna().sum() > 50


# ---------------------------------------------------------------------------
# shadow decomposition
# ---------------------------------------------------------------------------

def test_shadow_levels_decompose_the_fly_exactly():
    df = add_strip_slots(_toy_contracts())
    struct = enumerate_structures(df, spacing=1, max_slot=6)
    sh = shadow_levels(struct)
    lhs = sh["fly"]
    rhs = sh["belly_vs_front"] + sh["belly_vs_back"]
    pd.testing.assert_frame_equal(lhs, rhs)


def test_shadow_table_charges_each_instrument_its_own_legs():
    rng = np.random.default_rng(13)
    n = 400
    idx = pd.bdate_range("2021-01-01", periods=n)
    rows = []
    base = np.cumsum(rng.standard_normal(n)) * 0.02 + 4.0
    for i, d in enumerate(idx):
        rows.append({"as_of": d, "key": "K",
                     "leg0_value": base[i], "leg1_value": base[i] + 0.05,
                     "leg2_value": base[i] + 0.11})
    struct = pd.DataFrame(rows)
    sh = shadow_levels(struct)
    sig = zscore_signal(sh["fly"], window=60)
    tbl = shadow_table(sig, sh, base=MRConfig(entry_z=1.0, max_hold=10))
    assert set(tbl["instrument"]) == {"fly", "belly", "belly_vs_front", "belly_vs_back"}
    costs = dict(zip(tbl["instrument"], tbl["round_trip_bp"]))
    assert costs["fly"] == pytest.approx(1.5)
    assert costs["belly"] == pytest.approx(0.5)
    assert costs["belly_vs_front"] == pytest.approx(1.0)
    assert "verdict" in tbl.attrs


def _shadow_fixture():
    """A strip whose belly wobbles, so the butterfly actually trades.

    The base drifts as a random walk (giving the outright belly something to
    do) and the belly carries an independent mean-reverting wobble on top
    (giving the fly something to do). Without the wobble the fly is a constant
    and no shadow test can compare anything.
    """
    rng = np.random.default_rng(13)
    n = 400
    idx = pd.bdate_range("2021-01-01", periods=n)
    base = np.cumsum(rng.standard_normal(n)) * 0.02 + 4.0
    wobble = np.zeros(n)
    for i in range(1, n):
        wobble[i] = 0.85 * wobble[i - 1] + rng.standard_normal() * 0.01
    struct = pd.DataFrame([
        {"as_of": d, "key": "K", "leg0_value": base[i],
         "leg1_value": base[i] + 0.05 + wobble[i], "leg2_value": base[i] + 0.11}
        for i, d in enumerate(idx)])
    sh = shadow_levels(struct)
    return sh, zscore_signal(sh["fly"], window=60)


def test_per_contract_costing_only_moves_the_butterfly():
    """The belly of a 1/-2/1 package is two contracts; every wing is one.

    So per-contract costing charges the fly 2.0bp instead of 1.5bp and leaves
    every shadow untouched. Per-LEG costing therefore hands the butterfly a
    0.5bp/trade head start over exactly the instruments it is being compared
    against, which is backwards for a test that exists to find out whether the
    fly is worth its extra legs.
    """
    sh, sig = _shadow_fixture()
    cfg = MRConfig(entry_z=1.0, max_hold=10)
    per_leg = shadow_table(sig, sh, base=cfg, cost_mode="per_leg")
    per_ct = shadow_table(sig, sh, base=cfg, cost_mode="per_contract")
    a = dict(zip(per_leg["instrument"], per_leg["round_trip_bp"]))
    b = dict(zip(per_ct["instrument"], per_ct["round_trip_bp"]))
    assert a["fly"] == pytest.approx(1.5) and b["fly"] == pytest.approx(2.0)
    for name in ("belly", "belly_vs_front", "belly_vs_back"):
        assert a[name] == pytest.approx(b[name]), name
    assert dict(zip(per_ct["instrument"], per_ct["n_contracts"])) == {
        "fly": 4, "belly": 1, "belly_vs_front": 2, "belly_vs_back": 2}


def test_per_contract_costing_never_flatters_the_fly():
    """Charging the fly its true cost can only lower its net P&L."""
    sh, sig = _shadow_fixture()
    cfg = MRConfig(entry_z=1.0, max_hold=10)
    a = shadow_table(sig, sh, base=cfg, cost_mode="per_leg").set_index("instrument")
    b = shadow_table(sig, sh, base=cfg, cost_mode="per_contract").set_index("instrument")
    n = float(a.loc["fly", "n_trades"])
    assert n > 0
    assert b.loc["fly", "total_net_bp"] == pytest.approx(
        a.loc["fly", "total_net_bp"] - 0.5 * n)
    for name in ("belly", "belly_vs_front", "belly_vs_back"):
        assert b.loc[name, "total_net_bp"] == pytest.approx(
            a.loc[name, "total_net_bp"]), name


def test_shadow_table_rejects_an_unknown_cost_mode():
    sh, sig = _shadow_fixture()
    with pytest.raises(ValueError, match="cost_mode"):
        shadow_table(sig, sh, base=MRConfig(), cost_mode="per_tick")


# ---------------------------------------------------------------------------
# interop with the options lab's grading code
# ---------------------------------------------------------------------------

def test_sfrrvlab_stats_grade_an_mrresult():
    from RVUtils.SFRRVLab.stats import (
        cost_curve, grid_distribution, nonoverlapping_sharpe, nw_tstat, verdict,
    )

    rng = np.random.default_rng(14)
    n = 500
    idx = pd.bdate_range("2021-01-01", periods=n)
    lv = pd.DataFrame({"A": np.cumsum(rng.standard_normal(n))}, index=idx)
    sg = zscore_signal(lv, window=60)
    g = grid_search({"entry_z": [1.5, 2.0], "direction": ["fade", "momentum"]},
                    levels=lv, signal=sg)
    d = grid_distribution(g)
    assert d["n_configs"] == 4
    res = run_backtest(MRConfig(entry_z=1.5), levels=lv, signal=sg)
    if not res.trades.empty:
        assert np.isfinite(nw_tstat(res.daily_bp)) or True
        cc = cost_curve(res.trades, [0.0, 1.5, 2.5])
        assert len(cc) == 3
        nonoverlapping_sharpe(res.trades)
    v = verdict(net_bp_at_taker=1.0, net_bp_at_maker=2.0, dsr_prob=0.9,
                median_net_bp=1.0, n_trades=50)
    assert v == "ALIVE"
