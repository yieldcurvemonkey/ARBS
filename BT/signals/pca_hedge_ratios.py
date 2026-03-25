"""PCA-implied hedge ratio matrix and portfolio factor decomposition.

Derives hedge ratios between any pair of securities from PC loadings and
eigenvalues. Also computes portfolio exposure to each PC factor.

Reference: Credit Suisse "PCA Unleashed" (Pelata, Giannopoulos, Haworth -- Oct 2012),
Exhibit 32 (hedge ratio matrices) and Section 6 (portfolio risk).

Hedge ratio against PC1 only (level-neutral):
    gamma(x,y) = u1_x / u1_y

Hedge ratio against PC1 and PC2 (level-and-slope-neutral):
    gamma(x,y) = (u1_x * u1_y * lam1^2 + u2_x * u2_y * lam2^2) /
                 (u1_y^2 * lam1^2 + u2_y^2 * lam2^2)
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def hedge_ratio_matrix(
    loadings: pd.DataFrame,
    eigenvalues: pd.Series,
    neutralize_factors: List[int] = [1],
) -> pd.DataFrame:
    """Compute NxN hedge ratio matrix from PCA loadings and eigenvalues.

    Parameters
    ----------
    loadings : DataFrame [n_tenors x n_components], columns = ["PC1","PC2",...]
    eigenvalues : Series [n_components], index = ["PC1","PC2",...]
    neutralize_factors : list of ints (1-indexed)
        Which PCs to neutralize. [1] = level-neutral, [1,2] = level-and-slope-neutral.

    Returns
    -------
    DataFrame [n_tenors x n_tenors] where entry (x, y) is the hedge ratio of
    security x per unit of security y to achieve neutralization.
    """
    tenors = loadings.index
    n = len(tenors)
    hrm = np.ones((n, n))

    # Factor indices (0-indexed internally)
    factor_idx = [f - 1 for f in neutralize_factors]
    u = loadings.values  # (n_tenors x n_components)
    lam = eigenvalues.values  # (n_components,)

    for i in range(n):
        for j in range(n):
            if i == j:
                hrm[i, j] = 1.0
                continue

            if len(factor_idx) == 1:
                # PC1 only: gamma = u1_x / u1_y
                k = factor_idx[0]
                if abs(u[j, k]) < 1e-15:
                    hrm[i, j] = np.nan
                else:
                    hrm[i, j] = u[i, k] / u[j, k]
            else:
                # Multi-factor: gamma = sum_k(u_ik * u_jk * lam_k^2) / sum_k(u_jk^2 * lam_k^2)
                numerator = sum(u[i, k] * u[j, k] * lam[k] ** 2 for k in factor_idx)
                denominator = sum(u[j, k] ** 2 * lam[k] ** 2 for k in factor_idx)
                if abs(denominator) < 1e-15:
                    hrm[i, j] = np.nan
                else:
                    hrm[i, j] = numerator / denominator

    return pd.DataFrame(hrm, index=tenors, columns=tenors)


def portfolio_factor_exposure(
    positions: pd.Series,
    loadings: pd.DataFrame,
) -> pd.Series:
    """Compute portfolio exposure to each PC factor.

    exposure_to_PC_k = sum_i(position_DV01(i) * loading(i, k))

    Parameters
    ----------
    positions : Series [n_tenors] of DV01 bucket exposures (same index as loadings).
    loadings : DataFrame [n_tenors x n_components].

    Returns
    -------
    Series [n_components] of factor exposures.
    """
    pos = positions.reindex(loadings.index).fillna(0.0).values
    u = loadings.values  # (n_tenors x n_components)
    exposure = pos @ u  # (n_components,)
    return pd.Series(exposure, index=loadings.columns, name="factor_exposure")


def portfolio_variance_decomposition(
    positions: pd.Series,
    loadings: pd.DataFrame,
    eigenvalues: pd.Series,
) -> Dict[str, float]:
    """Decompose portfolio variance by PC factor.

    Var(portfolio) = sum_k[lam_k^2 * (sum_i position_DV01(i) * loading(i,k))^2]

    Returns dict with PC1, PC2, ..., and "total" keys.
    """
    exposure = portfolio_factor_exposure(positions, loadings)
    lam = eigenvalues.reindex(loadings.columns).values

    decomp = {}
    total = 0.0
    for k, pc_name in enumerate(loadings.columns):
        var_k = lam[k] ** 2 * exposure.iloc[k] ** 2
        decomp[pc_name] = float(var_k)
        total += var_k
    decomp["total"] = total
    return decomp


def suggested_hedge(
    positions: pd.Series,
    loadings: pd.DataFrame,
    hedge_instrument: str,
    neutralize_factors: List[int] = [1, 2],
) -> float:
    """Compute DV01 needed in hedge_instrument to neutralize specified factors.

    Parameters
    ----------
    positions : Series of current DV01 bucket exposures.
    loadings : DataFrame of PCA loadings.
    hedge_instrument : tenor label (must be in loadings.index).
    neutralize_factors : which PCs to neutralize.

    Returns
    -------
    float: DV01 to add in the hedge instrument (negative = pay, positive = receive).
    """
    exposure = portfolio_factor_exposure(positions, loadings)
    u = loadings.values
    hedge_idx = list(loadings.index).index(hedge_instrument)
    factor_idx = [f - 1 for f in neutralize_factors]

    # For single-factor: hedge_dv01 = -exposure_k / loading(hedge, k)
    # For multi-factor: solve least-squares to zero out specified exposures
    if len(factor_idx) == 1:
        k = factor_idx[0]
        if abs(u[hedge_idx, k]) < 1e-15:
            return np.nan
        return -float(exposure.iloc[k] / u[hedge_idx, k])
    else:
        # For multi-factor with single hedge instrument, minimize sum of squared exposures
        target_exposures = np.array([exposure.iloc[k] for k in factor_idx])
        hedge_loadings = np.array([u[hedge_idx, k] for k in factor_idx])
        if np.dot(hedge_loadings, hedge_loadings) < 1e-15:
            return np.nan
        h = -np.dot(target_exposures, hedge_loadings) / np.dot(hedge_loadings, hedge_loadings)
        return float(h)
