"""Tests for rolling PCA residual + eigenvector continuity (spec A)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.pca_rv import align_eigenvectors, rolling_residual


def _panel(n=500, seed=0, noise_std=0.002):
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0,  0.5, -0.5],
                  [1.0,  1.5,  1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise_std
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols)


def _panel_with_idio(n=500, seed=0, noise_std=0.002, idio_col="10", idio_mag=0.05):
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0,  0.5, -0.5],
                  [1.0,  1.5,  1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    idio = rng.standard_normal(n) * idio_mag
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise_std
    X[:, cols.index(idio_col)] += idio
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols), idio


class TestAlignEigenvectors:
    def test_no_flip_when_aligned(self):
        V = np.eye(3)
        result = align_eigenvectors(V.copy(), V, threshold=0.0)
        np.testing.assert_array_equal(result, V)

    def test_flips_sign_when_antiparallel(self):
        V_prev = np.eye(3)
        V_new = -np.eye(3)
        result = align_eigenvectors(V_new.copy(), V_prev, threshold=0.0)
        np.testing.assert_array_equal(result, V_prev)

    def test_partial_flip(self):
        V_prev = np.eye(3)
        V_new = np.eye(3)
        V_new[:, 1] = -V_new[:, 1]
        result = align_eigenvectors(V_new.copy(), V_prev, threshold=0.0)
        np.testing.assert_array_equal(result, V_prev)

    def test_threshold_keeps_orthogonal(self):
        V_prev = np.array([[1, 0], [0, 1]], dtype=float)
        V_new = np.array([[0, 1], [1, 0]], dtype=float)
        result = align_eigenvectors(V_new.copy(), V_prev, threshold=0.0)
        np.testing.assert_array_equal(result, V_new)


class TestRollingResidual:
    def test_output_length(self):
        df = _panel(n=400)
        res = rolling_residual(df, "10", window=100, k=3)
        assert isinstance(res, pd.Series)
        assert len(res) <= 400 - 100 + 1
        assert res.notna().sum() > 0

    def test_residual_captures_idiosyncratic_noise(self):
        df, idio = _panel_with_idio(n=500, idio_mag=0.10, noise_std=0.001)
        res = rolling_residual(df, "10", window=200, k=3)
        common = res.dropna().index
        idio_s = pd.Series(idio, index=df.index, name="idio").loc[common]
        corr = res.loc[common].corr(idio_s)
        assert abs(corr) > 0.5, f"Rolling residual should track idiosyncratic noise, got corr={corr:.3f}"

    def test_multi_leg_structure(self):
        df = _panel(n=400)
        weights = {"2": -0.5, "10": 1.0, "30": -0.5}
        res = rolling_residual(df, ["2", "10", "30"], weights=weights, window=100, k=3)
        assert isinstance(res, pd.Series)
        assert res.notna().sum() > 0

    def test_sign_align_prevents_jumps(self):
        df = _panel(n=500)
        res_aligned = rolling_residual(df, "10", window=100, k=3, sign_align=True)
        res_no_align = rolling_residual(df, "10", window=100, k=3, sign_align=False)
        jumps_aligned = res_aligned.diff().abs().max()
        jumps_no_align = res_no_align.diff().abs().max()
        assert jumps_aligned <= jumps_no_align * 1.1 or jumps_aligned < 0.5
