"""Tests for screener_rv (Task 8): cross-structure composite rank + dislocation index."""
import numpy as np
import pandas as pd

from RVUtils.screener_rv import make_rv_screener


def _ou_col(n, seed, kappa=0.05, sigma=1.0, mu=0.0):
    r = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + sigma * r.standard_normal()
    return x


def _structs(n=400):
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"2s5s10s": _ou_col(n, 1), "5s10s30s": _ou_col(n, 2), "2s10s": _ou_col(n, 3)},
        index=idx,
    )


def test_to_dataframe_shape_and_columns():
    df = _structs()
    build, rank, to_dataframe, rv_dislocation_index, get_data = make_rv_screener(df)
    out = to_dataframe()
    assert len(out) == 3
    for col in ["level", "chg_1d", "zscore", "percentile", "vol", "half_life", "composite", "direction", "actionable"]:
        assert col in out.columns


def test_most_extreme_z_ranks_first():
    df = _structs().copy()
    sd = df["2s5s10s"].diff().std()
    df.iloc[-1, df.columns.get_loc("2s5s10s")] = df["2s5s10s"].iloc[-2] + 12 * sd  # big dislocation
    build, rank, to_dataframe, rv_dislocation_index, get_data = make_rv_screener(df)
    top = rank(3)
    assert top.index[0] == "2s5s10s"
    assert abs(to_dataframe().loc["2s5s10s", "zscore"]) > 3


def test_dislocation_index_spikes_on_common_jump():
    df = _structs().copy()
    for c in df.columns:
        sd = df[c].diff().std()
        df.iloc[-3:, df.columns.get_loc(c)] = df[c].iloc[-4] + 8 * sd  # common late spike
    build, rank, to_dataframe, rv_dislocation_index, get_data = make_rv_screener(df)
    di = rv_dislocation_index().dropna()
    assert di.iloc[-1] > di.median()


def test_direction_sign():
    df = _structs()
    build, rank, to_dataframe, rv_dislocation_index, get_data = make_rv_screener(df)
    out = to_dataframe()
    for s, row in out.iterrows():
        if row["zscore"] > 0:
            assert row["direction"] == "SELL"
        elif row["zscore"] < 0:
            assert row["direction"] == "BUY"
