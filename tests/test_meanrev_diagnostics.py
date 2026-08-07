"""Synthetic, no-network tests for the move-size ("pond") diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeanRev.diagnostics import (
    forward_move,
    move_profile,
    oracle_table,
    selectivity_table,
    signal_entry_mask,
    variance_decomposition,
)
from RVUtils.MeanRev.signals import scale_only_zscore


def _idx(n):
    return pd.bdate_range("2024-01-01", periods=n)


def test_forward_move_is_a_forward_difference():
    idx = _idx(6)
    lv = pd.DataFrame({"a": np.arange(6, dtype=float)}, index=idx)
    g = forward_move(lv, 2)
    assert g["a"].iloc[0] == pytest.approx(2.0)
    assert np.isnan(g["a"].iloc[-1]) and np.isnan(g["a"].iloc[-2])


def test_move_profile_on_a_deterministic_ramp():
    idx = _idx(50)
    lv = pd.DataFrame({"a": np.arange(50, dtype=float)}, index=idx)
    p = move_profile(lv, None, horizons=(5,), round_trip_bp=2.0)
    r = p.iloc[0]
    assert r["n"] == 45
    assert r["mean_abs_bp"] == pytest.approx(5.0)
    assert r["oracle_net_bp"] == pytest.approx(3.0)
    assert r["p_beat_cost"] == pytest.approx(1.0)


def test_p_beat_cost_is_zero_when_the_pond_is_smaller_than_the_boat():
    idx = _idx(60)
    lv = pd.DataFrame({"a": 0.1 * np.arange(60, dtype=float)}, index=idx)
    p = move_profile(lv, None, horizons=(5,), round_trip_bp=2.0)
    assert p.iloc[0]["mean_abs_bp"] == pytest.approx(0.5)
    assert p.iloc[0]["p_beat_cost"] == pytest.approx(0.0)
    assert p.iloc[0]["oracle_net_bp"] < 0


def test_signal_entry_mask_thresholds_both_tails():
    idx = _idx(5)
    sg = pd.DataFrame({"a": [-3.0, -1.0, 0.0, 1.0, 3.0]}, index=idx)
    m = signal_entry_mask(sg, 2.0)
    assert list(m["a"]) == [True, False, False, False, True]


def test_signal_entry_mask_honours_the_gate():
    idx = _idx(3)
    sg = pd.DataFrame({"a": [3.0, 3.0, 3.0]}, index=idx)
    gate = pd.DataFrame({"a": [True, False, True]}, index=idx)
    assert list(signal_entry_mask(sg, 2.0, gate=gate)["a"]) == [True, False, True]


def test_signal_entry_mask_drops_nan():
    idx = _idx(3)
    sg = pd.DataFrame({"a": [np.nan, 3.0, -3.0]}, index=idx)
    assert list(signal_entry_mask(sg, 2.0)["a"]) == [False, True, True]


def test_selectivity_is_one_for_an_all_true_mask():
    rng = np.random.default_rng(0)
    idx = _idx(200)
    lv = pd.DataFrame({"a": rng.normal(0, 1, 200).cumsum()}, index=idx)
    allsig = pd.DataFrame(np.full((200, 1), 9.0), index=idx, columns=["a"])
    t = oracle_table(lv, {"all": signal_entry_mask(allsig, 2.0)}, horizons=(5,))
    row = t[t["signal"] == "all"].iloc[0]
    assert row["selectivity"] == pytest.approx(1.0)


def test_selectivity_detects_a_signal_that_picks_bigger_moves():
    """Construct a panel where the flagged days really do move further."""
    n = 400
    idx = _idx(n)
    rng = np.random.default_rng(7)
    step = rng.normal(0, 0.2, n)
    flag = np.zeros(n, dtype=bool)
    flag[::20] = True
    step[flag] = rng.normal(0, 3.0, flag.sum())      # a big move STARTS here
    lv = pd.DataFrame({"a": np.concatenate([[0.0], step[:-1].cumsum()])}, index=idx)
    sig = pd.DataFrame({"a": np.where(flag, 5.0, 0.0)}, index=idx)
    t = selectivity_table(lv, {"flagged": sig}, entry_z=2.0, horizons=(1,))
    row = t[t["signal"] == "flagged"].iloc[0]
    assert row["selectivity"] > 2.0


def test_oracle_table_has_an_unconditional_row_per_horizon():
    rng = np.random.default_rng(1)
    idx = _idx(120)
    lv = pd.DataFrame(rng.normal(0, 1, (120, 3)).cumsum(axis=0), index=idx,
                      columns=list("abc"))
    t = oracle_table(lv, {}, horizons=(5, 10, 21))
    assert list(t["signal"].unique()) == ["unconditional"]
    assert sorted(t["horizon"]) == [5, 10, 21]


def test_move_profile_handles_an_empty_selection():
    idx = _idx(30)
    lv = pd.DataFrame({"a": np.arange(30, dtype=float)}, index=idx)
    mask = pd.DataFrame(False, index=idx, columns=["a"])
    p = move_profile(lv, mask, horizons=(5,))
    assert p.iloc[0]["n"] == 0
    # every column must still be present, or a table built from several signals
    # loses the column entirely and its consumers raise on the first live one
    for col in ("mean_abs_bp", "oracle_net_bp", "p_beat_cost", "median_abs_bp",
                "p90_abs_bp", "mean_bp", "sd_bp"):
        assert col in p.columns
        assert np.isnan(p.iloc[0][col])


def test_oracle_table_survives_a_signal_that_never_fires():
    """A dead signal must produce a NaN row, not a KeyError.

    ``pond_block`` scores several candidate definitions in one table, and a
    threshold that happens to be unreachable for one of them would otherwise
    take the whole diagnostic down -- right before the grids, which is the worst
    possible place for it.
    """
    idx = _idx(60)
    rng = np.random.default_rng(11)
    lv = pd.DataFrame({"a": rng.normal(0, 1, 60).cumsum()}, index=idx)
    live = pd.DataFrame({"a": np.full(60, 9.0)}, index=idx)
    dead = pd.DataFrame({"a": np.zeros(60)}, index=idx)
    t = oracle_table(lv, {"live": signal_entry_mask(live, 2.0),
                          "dead": signal_entry_mask(dead, 2.0)}, horizons=(5, 10))
    assert set(t["signal"]) == {"unconditional", "live", "dead"}
    d = t[t["signal"] == "dead"]
    assert (d["n"] == 0).all()
    assert d["mean_abs_bp"].isna().all()
    assert d["selectivity"].isna().all()
    assert t[t["signal"] == "live"]["mean_abs_bp"].notna().all()


def test_selectivity_table_survives_a_signal_that_never_fires():
    idx = _idx(60)
    rng = np.random.default_rng(12)
    lv = pd.DataFrame({"a": rng.normal(0, 1, 60).cumsum()}, index=idx)
    sigs = {"live": pd.DataFrame({"a": np.full(60, 9.0)}, index=idx),
            "dead": pd.DataFrame({"a": np.zeros(60)}, index=idx)}
    t = selectivity_table(lv, sigs, entry_z=2.0, horizons=(5,))
    assert set(t["signal"]) == {"unconditional", "live", "dead"}
    assert int(t[t["signal"] == "dead"]["n"].iloc[0]) == 0


def test_variance_decomposition_is_perfect_when_the_model_is_the_data():
    idx = _idx(60)
    rng = np.random.default_rng(2)
    a = pd.DataFrame(rng.normal(0, 3, (60, 2)), index=idx, columns=["x", "y"])
    d = variance_decomposition(a, a.copy())
    assert len(d) == 1
    assert d.iloc[0]["r2"] == pytest.approx(1.0)
    assert d.iloc[0]["sd_resid_bp"] == pytest.approx(0.0, abs=1e-12)


def test_variance_decomposition_reports_the_residual_share():
    idx = _idx(400)
    rng = np.random.default_rng(5)
    truth = pd.DataFrame(rng.normal(0, 4, (400, 1)), index=idx, columns=["x"])
    noise = pd.DataFrame(rng.normal(0, 3, (400, 1)), index=idx, columns=["x"])
    actual = truth + noise
    d = variance_decomposition(actual, truth).iloc[0]
    assert d["r2"] == pytest.approx(1 - 9.0 / 25.0, abs=0.08)
    assert d["resid_share"] == pytest.approx(3.0 / 5.0, abs=0.06)


def test_variance_decomposition_splits_by_group():
    idx = _idx(80)
    rng = np.random.default_rng(6)
    a = pd.DataFrame(rng.normal(0, 1, (80, 4)), index=idx, columns=list("abcd"))
    g = pd.Series({"a": "front", "b": "front", "c": "back", "d": "back"})
    d = variance_decomposition(a, a * 0.0, groups=g)
    assert sorted(d["group"]) == ["back", "front"]
    assert (d["r2"] < 0.05).all()


def test_scale_only_zscore_keeps_the_models_zero():
    """A constant positive deviation stays a positive signal.

    A full z-score would centre it on its own trailing mean and report ~0,
    throwing away exactly the information a fitted fair value provides.
    """
    idx = _idx(200)
    rng = np.random.default_rng(9)
    x = pd.DataFrame({"a": 4.0 + rng.normal(0, 1.0, 200)}, index=idx)
    s = scale_only_zscore(x, window=100)
    z = x.rolling(100, min_periods=33).apply(
        lambda w: (w.iloc[-1] - w.mean()) / w.std(ddof=0))
    assert s["a"].dropna().mean() > 3.0
    assert abs(z["a"].dropna().mean()) < 0.5
