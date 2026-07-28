"""Couplings that turn per-contract marginals into joint path scenarios.

``comonotone_grid`` implements the one-policy-factor model: every contract rate is
its own quantile function evaluated at a *common* uniform ``U`` (perfect rank
correlation). ``gaussian_copula_sample`` relaxes that to an arbitrary correlation
matrix (historically calibrated via :func:`historical_corr`); at rho -> 1 it
converges to the comonotone coupling.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm

from RVUtils.FlyVsVol._types import ContractMarginal

__all__ = ["comonotone_grid", "gaussian_copula_sample", "historical_corr"]


def comonotone_grid(
    marginals: Sequence[ContractMarginal], n: int = 20001
) -> np.ndarray:
    """Joint rates on a midpoint quantile grid; shape ``(n, len(marginals))``.

    Row ``i`` is the path scenario at common factor ``u_i = (i + 0.5) / n``; equal
    weights over rows integrate any path functional under the comonotone law.
    """
    u = (np.arange(n) + 0.5) / n
    return np.column_stack([m.quantile(u) for m in marginals])


def gaussian_copula_sample(
    marginals: Sequence[ContractMarginal],
    corr: np.ndarray,
    n_sim: int = 200_000,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Sample joint rates under a Gaussian copula; shape ``(n_sim, k)``.

    ``corr`` is symmetrized and eigenvalue-clipped so mildly non-PSD (or exactly
    singular, e.g. all-ones) matrices are handled.
    """
    rng = rng or np.random.default_rng()
    k = len(marginals)
    sub = np.asarray(corr, dtype=float)
    if sub.shape != (k, k):
        raise ValueError(f"corr must be ({k},{k}), got {sub.shape}")
    if not np.all(np.isfinite(sub)):
        raise ValueError("corr contains non-finite entries")
    sub = 0.5 * (sub + sub.T)
    eig, vec = np.linalg.eigh(sub)
    L = vec @ np.diag(np.sqrt(np.clip(eig, 1e-10, None)))
    z = rng.standard_normal(size=(n_sim, k)) @ L.T
    u = norm.cdf(z)
    return np.column_stack([m.quantile(u[:, i]) for i, m in enumerate(marginals)])


def historical_corr(panel: pd.DataFrame, *, min_overlap: int = 60) -> pd.DataFrame:
    """Correlation matrix of daily first differences of a rates panel.

    Pairs with fewer than ``min_overlap`` overlapping observations are NaN'd so a
    thin far-red contract cannot inject a noise correlation; diagonal stays 1
    wherever the column has any data at all.
    """
    diffs = panel.diff()
    corr = diffs.corr(min_periods=min_overlap)
    counts = diffs.notna().astype(int).T @ diffs.notna().astype(int)
    corr = corr.where(counts >= min_overlap)
    for col in corr.columns:
        if diffs[col].notna().sum() > 1:
            corr.loc[col, col] = 1.0
    return corr
