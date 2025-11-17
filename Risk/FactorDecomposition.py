# ABOUTME: PCA-based factor decomposition for yield curves (level/slope/curvature)
# ABOUTME: Implements Litterman & Scheinkman methodology for rates factor models

"""
PCA Factor Decomposition for Yield Curves

This module implements Principal Component Analysis (PCA) for decomposing
yield curve movements into interpretable factors:

- PC1 (Level): Parallel shifts across all maturities (~85-90% of variance)
- PC2 (Slope): Short vs long rate movements (~8-12% of variance)
- PC3 (Curvature): Butterfly/middle vs wings movements (~1-3% of variance)

Based on:
- Litterman & Scheinkman (1991): "Common Factors Affecting Bond Returns"
- Applications: P&L attribution, risk management, hedging, relative value

Usage:
    >>> from Risk.FactorDecomposition import PCAFactorModel
    >>> import polars as pl
    >>> from datetime import date, timedelta
    >>>
    >>> # Create yield curve changes DataFrame
    >>> dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(252)]
    >>> tenors = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]
    >>> changes_df = pl.DataFrame({
    ...     "date": dates,
    ...     **{tenor: np.random.randn(252) for tenor in tenors}
    ... })
    >>>
    >>> # Fit PCA model
    >>> model = PCAFactorModel(n_components=3)
    >>> model.fit(changes_df, date_column="date")
    >>>
    >>> # Get factor loadings
    >>> loadings = model.get_loadings()
    >>> print(f"PC1 (Level) loadings: {loadings[0, :]}")
    >>>
    >>> # Get factors for a specific date
    >>> factors = model.get_factors(date(2024, 6, 1))
    >>> print(f"Level: {factors['level']:.4f}")
    >>>
    >>> # Calculate factor hedges
    >>> portfolio_pv01 = {"1Y": 0, "2Y": 0, "3Y": 0, "5Y": 100000, "7Y": 0, "10Y": 0}
    >>> hedges = model.factor_hedge_ratios(portfolio_pv01)
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import polars as pl
from sklearn.decomposition import PCA


@dataclass
class PCAFactorModel:
    """
    PCA-based factor model for yield curve decomposition.

    Decomposes yield curve changes into orthogonal factors using PCA.
    The first three components typically represent level, slope, and curvature.

    Attributes:
        n_components: Number of principal components to extract (default: 3)
        is_fitted: Whether the model has been fitted to data
        tenors: List of tenor labels (e.g., ["1Y", "2Y", "3Y", ...])
        pca: Scikit-learn PCA object (fitted)
        factor_scores: Factor values for each date in training data
        dates: Dates corresponding to factor scores
    """

    n_components: int = 3
    is_fitted: bool = field(default=False, init=False)
    tenors: List[str] = field(default_factory=list, init=False)
    pca: Optional[PCA] = field(default=None, init=False)
    factor_scores: Optional[np.ndarray] = field(default=None, init=False)
    dates: Optional[List[date]] = field(default=None, init=False)

    def fit(self, changes_df: pl.DataFrame, date_column: str = "date") -> "PCAFactorModel":
        """
        Fit PCA model on yield curve changes.

        Args:
            changes_df: DataFrame with date column and tenor columns (yield changes in bps or %)
            date_column: Name of the date column

        Returns:
            self (fitted model)

        Raises:
            ValueError: If DataFrame is empty or has insufficient data
        """
        if changes_df.height < self.n_components:
            raise ValueError(
                f"Insufficient data: need at least {self.n_components} observations, got {changes_df.height}"
            )

        # Extract dates and tenor columns
        self.dates = changes_df[date_column].to_list()
        tenor_columns = [col for col in changes_df.columns if col != date_column]
        self.tenors = tenor_columns

        if len(self.tenors) < self.n_components:
            raise ValueError(
                f"Insufficient tenors: need at least {self.n_components} tenors, got {len(self.tenors)}"
            )

        # Extract yield curve changes matrix (observations x tenors)
        changes_matrix = changes_df.select(tenor_columns).to_numpy()

        # Fit PCA
        self.pca = PCA(n_components=self.n_components)
        self.factor_scores = self.pca.fit_transform(changes_matrix)

        self.is_fitted = True
        return self

    def get_loadings(self) -> np.ndarray:
        """
        Get factor loadings (eigenvectors).

        Returns:
            Array of shape (n_components, n_tenors) with factor loadings

        Raises:
            ValueError: If model not fitted
        """
        self._check_fitted()
        return self.pca.components_

    def get_explained_variance_ratio(self) -> np.ndarray:
        """
        Get explained variance ratio for each component.

        Returns:
            Array of length n_components with variance ratios

        Raises:
            ValueError: If model not fitted
        """
        self._check_fitted()
        return self.pca.explained_variance_ratio_

    def get_factors(self, target_date: date) -> Dict[str, float]:
        """
        Get factor values for a specific date.

        Args:
            target_date: Date to retrieve factors for

        Returns:
            Dictionary with keys "level", "slope", "curvature" (for n_components=3)

        Raises:
            ValueError: If model not fitted or date not in training data
        """
        self._check_fitted()

        if target_date not in self.dates:
            raise ValueError(f"Date {target_date} not in training data")

        idx = self.dates.index(target_date)
        factors = self.factor_scores[idx, :]

        # Standard naming for first 3 PCs
        factor_names = ["level", "slope", "curvature"]
        return {
            factor_names[i] if i < len(factor_names) else f"PC{i+1}": float(factors[i])
            for i in range(self.n_components)
        }

    def transform(self, changes: Dict[str, float]) -> np.ndarray:
        """
        Transform new yield curve changes to factor space.

        Args:
            changes: Dictionary mapping tenor -> yield change (e.g., {"1Y": 0.01, "2Y": 0.015, ...})

        Returns:
            Array of factor values (length n_components)

        Raises:
            ValueError: If model not fitted or tenors don't match
        """
        self._check_fitted()

        if set(changes.keys()) != set(self.tenors):
            raise ValueError(f"Changes keys {set(changes.keys())} don't match fitted tenors {set(self.tenors)}")

        # Convert to array in same order as training data
        changes_array = np.array([changes[tenor] for tenor in self.tenors]).reshape(1, -1)

        return self.pca.transform(changes_array)[0]

    def factor_hedge_ratios(self, portfolio_pv01: Dict[str, float], factors_to_hedge: Optional[List[int]] = None) -> Dict[str, float]:
        """
        Calculate hedge ratios to neutralize factor exposures.

        Given a portfolio's PV01 profile, computes hedge ratios that neutralize
        exposure to specified factors (default: all factors).

        Args:
            portfolio_pv01: Dictionary mapping tenor -> PV01 (e.g., {"1Y": 0, "2Y": 0, "5Y": 100000, ...})
            factors_to_hedge: Which factors to hedge (default: all)

        Returns:
            Dictionary mapping tenor -> hedge ratio (negative values indicate short position)

        Raises:
            ValueError: If model not fitted or tenors don't match

        Example:
            >>> # Portfolio long 100k PV01 in 5Y
            >>> pv01 = {"1Y": 0, "2Y": 0, "3Y": 0, "5Y": 100000, "7Y": 0, "10Y": 0}
            >>> hedges = model.factor_hedge_ratios(pv01, factors_to_hedge=[0, 1])
            >>> # hedges will show positions to neutralize level and slope exposures
        """
        self._check_fitted()

        if set(portfolio_pv01.keys()) != set(self.tenors):
            raise ValueError(f"Portfolio PV01 keys don't match fitted tenors")

        # Convert PV01 to array (in same order as training data)
        pv01_array = np.array([portfolio_pv01[tenor] for tenor in self.tenors])

        # Default: hedge all factors
        if factors_to_hedge is None:
            factors_to_hedge = list(range(self.n_components))

        # Get factor loadings (components)
        loadings = self.pca.components_  # shape: (n_components, n_tenors)

        # Project portfolio PV01 into factor space
        factor_exposure = pv01_array @ loadings.T  # shape: (n_components,)

        # Zero out factors we don't want to hedge
        hedge_exposure = np.zeros(self.n_components)
        for i in factors_to_hedge:
            hedge_exposure[i] = -factor_exposure[i]  # Negate to offset exposure

        # Project back to tenor space
        hedge_pv01 = hedge_exposure @ loadings  # shape: (n_tenors,)

        return {tenor: float(hedge_pv01[i]) for i, tenor in enumerate(self.tenors)}

    def get_model_state(self) -> Dict:
        """
        Get complete model state for persistence or inspection.

        Returns:
            Dictionary with model parameters and fitted values
        """
        self._check_fitted()

        return {
            "n_components": self.n_components,
            "tenors": self.tenors,
            "loadings": self.pca.components_.tolist(),
            "explained_variance_ratio": self.pca.explained_variance_ratio_.tolist(),
            "explained_variance": self.pca.explained_variance_.tolist(),
            "mean": self.pca.mean_.tolist(),
            "n_samples": len(self.dates),
            "date_range": (min(self.dates), max(self.dates)),
        }

    def summary(self) -> str:
        """
        Generate human-readable summary of the model.

        Returns:
            Formatted string with model summary
        """
        self._check_fitted()

        lines = [
            "PCA Factor Model Summary",
            "=" * 60,
            f"Number of components: {self.n_components}",
            f"Number of tenors: {len(self.tenors)}",
            f"Tenors: {', '.join(self.tenors)}",
            f"Training samples: {len(self.dates)}",
            f"Date range: {min(self.dates)} to {max(self.dates)}",
            "",
            "Explained Variance:",
        ]

        factor_names = ["Level (PC1)", "Slope (PC2)", "Curvature (PC3)"]
        for i, var in enumerate(self.pca.explained_variance_ratio_):
            name = factor_names[i] if i < len(factor_names) else f"PC{i+1}"
            lines.append(f"  {name}: {var*100:.2f}%")

        cumsum = np.cumsum(self.pca.explained_variance_ratio_)
        lines.append(f"  Cumulative: {cumsum[-1]*100:.2f}%")
        lines.append("")
        lines.append("Factor Loadings:")

        for i in range(self.n_components):
            name = factor_names[i] if i < len(factor_names) else f"PC{i+1}"
            loadings = self.pca.components_[i, :]
            lines.append(f"  {name}:")
            for j, tenor in enumerate(self.tenors):
                lines.append(f"    {tenor}: {loadings[j]:+.4f}")

        return "\n".join(lines)

    def _check_fitted(self):
        """Raise error if model not fitted."""
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call fit() first.")
