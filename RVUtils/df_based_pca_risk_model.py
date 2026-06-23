from dataclasses import dataclass
from typing import Sequence, Optional

import numpy as np
import pandas as pd
import re


_TENOR_RE = re.compile(r"^(\d+)([DWMY])$")


def _tenor_to_years(tenor: str) -> float:
    """
    Rough mapping from '1D','1W','1M','3M','6M','9M','1Y',...,'30Y' to years.
    Good enough for sorting columns.
    """
    m = _TENOR_RE.match(tenor)
    if not m:
        return np.nan
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "D":
        return n / 252.0
    if unit == "W":
        return 7 * n / 252.0
    if unit == "M":
        return n / 12.0
    if unit == "Y":
        return float(n)
    return np.nan


def _extract_tenor(col: str) -> str:
    # e.g. "USD-SOFR-1D 10Y OUTRIGHT RATE" -> "10Y"
    parts = str(col).split()
    if len(parts) >= 2:
        return parts[1]
    return str(col)


@dataclass
class CurvePCAModel:
    """
    PCA model for a single curve.

    columns:    list of original df columns used for PCA (ordered)
    mean:       mean of the input *changes* used in PCA, per column
    loadings:   DataFrame, index=columns, columns=['PC1','PC2',...],
                each column = eigenvector (PC loading)
    eigenvalues:Series, index=['PC1','PC2',...]
    """

    columns: list
    mean: pd.Series
    loadings: pd.DataFrame
    eigenvalues: pd.Series
    scales: Optional[pd.Series] = None  # per-column std for corr-PCA; None => ones (cov-PCA)

    # ---------- internal ----------
    def _scales_vec(self) -> pd.Series:
        if self.scales is None:
            return pd.Series(1.0, index=self.columns)
        return self.scales.reindex(self.columns).fillna(1.0)

    # ---------- transforms ----------

    def transform(self, x: pd.Series) -> pd.Series:
        """
        Project a single curve snapshot (levels or changes) with the same
        columns as the original df onto PC coordinates.

        x: Series indexed by the same column labels as df (or a subset/superset
           that can be reindexed).

        Returns: Series of PC exposures (PC1, PC2, ...).
        """
        x = x.reindex(self.columns)
        x_std = (x - self.mean) / self._scales_vec()
        scores = x_std.values @ self.loadings.values  # (K,) = (1xK)@(KxK)
        return pd.Series(scores, index=self.loadings.columns, name="pc_scores")

    def inverse_transform(self, scores: pd.Series) -> pd.Series:
        """
        Reconstruct approximate curve from PC scores.
        """
        scores = scores.reindex(self.loadings.columns)
        x_rec = (scores.values @ self.loadings.values.T) * self._scales_vec().values + self.mean.values
        return pd.Series(x_rec, index=self.columns, name="reconstructed")

    # ---------- PCA-norm ----------

    def pca_norm(
        self,
        x: pd.Series,
        *,
        weights: Optional[Sequence[float]] = None,
    ) -> float:
        """
        Compute a PCA-norm of a vector x.

        1. Project x into PC space.
        2. Weight each PC exposure.
        3. Return sqrt(sum_i w_i * score_i^2).

        weights:
            - None: all PCs equally weighted (w_i = 1).
            - list/array of length K: custom weights.
              Common choices:
                * w_i = 1               -> plain L2 in PC space
                * w_i = 1/eigenvalue_i  -> Mahalanobis-like
                * w_i = eigenvalue_i    -> emphasize high-variance PCs
        """
        scores = self.transform(x).values
        K = len(scores)
        if weights is None:
            w = np.ones(K)
        else:
            w = np.asarray(weights, dtype=float)
            if w.shape[0] != K:
                raise ValueError(f"weights must have length {K}, got {w.shape[0]}")
        return float(np.sqrt(np.sum(w * scores**2)))

    # ---------- reconstruction / residual ----------

    def reconstruct(self, x: pd.Series, k: Optional[int] = None) -> pd.Series:
        """k-factor reconstruction of a snapshot x (same space the model was fit on)."""
        K = self.loadings.shape[1]
        k = K if k is None else int(min(max(k, 1), K))
        A = self.loadings.values[:, :k]  # (K x k)
        sc = self._scales_vec().values
        xv = x.reindex(self.columns).values
        x_std = (xv - self.mean.values) / sc
        proj = A @ (A.T @ x_std)
        x_rec = proj * sc + self.mean.values
        return pd.Series(x_rec, index=self.columns, name="reconstructed")

    def residual(self, x: pd.Series, k: Optional[int] = None) -> pd.Series:
        """x - reconstruct(x, k); >0 => actual above PCA fair value (cheap for yields)."""
        xv = x.reindex(self.columns)
        return xv - self.reconstruct(x, k=k)

    def explained_variance(self) -> pd.Series:
        ev = self.eigenvalues / self.eigenvalues.sum()
        ev.name = "explained_variance_ratio"
        return ev


def fit_curve_pca_from_timeseries(
    df: pd.DataFrame,
    *,
    use_changes: bool = True,
    sort_by_tenor: bool = True,
    matrix: str = "cov",
    pin_signs: bool = False,
) -> tuple[CurvePCAModel, pd.DataFrame]:
    """
    Build a PCA model from your IRSwapsTB.get_timeseries DataFrame.

    df:
        Wide DataFrame:
            index = Date
            columns = "USD-SOFR-1D 10Y OUTRIGHT RATE", etc.
        Values are rates (levels).

    use_changes:
        True  -> run PCA on daily changes (df.diff()).
        False -> run PCA on levels (not usually recommended for curve).

    sort_by_tenor:
        If True, reorder columns in increasing maturity (1D,1W,1M,...,30Y).

    Returns:
        (model, scores_df), where:
          - model: CurvePCAModel
          - scores_df: time series of PC scores for each date
    """
    # --- 1) Choose columns & sort by tenor if desired ---
    cols = list(df.columns)

    if sort_by_tenor:
        tenors = [_extract_tenor(c) for c in cols]
        tenors_years = np.array([_tenor_to_years(t) for t in tenors], dtype=float)
        order = np.argsort(tenors_years)
        cols = [cols[i] for i in order]

    df_ord = df[cols].copy()

    # --- 2) Build data matrix X: levels or daily changes ---
    if use_changes:
        X = df_ord.sort_index().diff().dropna(how="any")
    else:
        X = df_ord.sort_index().dropna(how="any")

    # --- 3) Demean (and standardize if matrix='corr') ---
    mean_vec = X.mean(axis=0)
    if matrix == "corr":
        scales = X.std(axis=0, ddof=1).replace(0, np.nan).fillna(1.0)
    elif matrix == "cov":
        scales = pd.Series(1.0, index=X.columns)
    else:
        raise ValueError("matrix must be 'cov' or 'corr'")
    X_std = (X - mean_vec) / scales

    # --- 4) Covariance and eigen-decomposition ---
    X_mat = X_std.values  # T x K
    T_obs, K = X_mat.shape
    cov = (X_mat.T @ X_mat) / (T_obs - 1)  # K x K

    # Eigen-decomposition (symmetric -> eigh), then sort descending
    evals, evecs = np.linalg.eigh(cov)
    idx = np.argsort(evals)[::-1]
    evals = evals[idx]
    evecs = evecs[:, idx]  # columns = PCs

    # Pin eigenvector signs so the largest-abs loading is positive (deterministic).
    if pin_signs:
        for j in range(evecs.shape[1]):
            colj = evecs[:, j]
            if colj[np.argmax(np.abs(colj))] < 0:
                evecs[:, j] = -colj

    pc_names = [f"PC{i+1}" for i in range(K)]
    loadings = pd.DataFrame(evecs, index=cols, columns=pc_names)
    eigenvalues = pd.Series(evals, index=pc_names, name="eigenvalue")

    # --- 5) PC scores for each date ---
    scores = X_mat @ evecs  # T x K
    scores_df = pd.DataFrame(scores, index=X_std.index, columns=pc_names)

    # --- 6) Wrap in model object ---
    model = CurvePCAModel(
        columns=cols,
        mean=mean_vec,
        loadings=loadings,
        eigenvalues=eigenvalues,
        scales=scales,
    )

    return model, scores_df
