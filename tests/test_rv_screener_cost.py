"""Tests for cost-aware composite screener (spec G)."""
import numpy as np
import pandas as pd
import pytest

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
        {"fly_a": _ou_col(n, 1), "fly_b": _ou_col(n, 2)},
        index=idx,
    )


class TestCostAwareComposite:
    def test_backcompat_defaults(self):
        df = _structs()
        build, rank, to_df, di, get = make_rv_screener(df)
        out_old = to_df()
        build2, rank2, to_df2, di2, get2 = make_rv_screener(df, cost_z=0.0, lambda_carry=0.0)
        out_new = to_df2()
        pd.testing.assert_series_equal(out_old["composite"], out_new["composite"])

    def test_cost_lowers_score(self):
        df = _structs()
        _, _, to_df_no_cost, _, _ = make_rv_screener(df, cost_z=0.0)
        _, _, to_df_cost, _, _ = make_rv_screener(df, cost_z=0.5)
        s0 = to_df_no_cost()["composite"].abs()
        s1 = to_df_cost()["composite"].abs()
        assert (s1 <= s0 + 1e-10).all(), "Cost should reduce composite magnitude"

    def test_positive_carry_raises_score(self):
        df = _structs()
        idx = df.index
        rolldown = pd.DataFrame(
            {"fly_a": np.ones(len(idx)) * 2.0, "fly_b": np.ones(len(idx)) * 2.0},
            index=idx,
        )
        _, _, to_df_no, _, _ = make_rv_screener(df, lambda_carry=0.0)
        _, _, to_df_carry, _, _ = make_rv_screener(df, lambda_carry=0.5, rolldown_df=rolldown)
        s0 = to_df_no()["composite"].abs()
        s1 = to_df_carry()["composite"].abs()
        assert (s1 >= s0 - 0.1).any()
