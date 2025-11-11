# ABOUTME: Abstract base class for all portfolio optimizers
# ABOUTME: Defines standard interface for optimize() method and constraint handling
"""
BaseOptimizer - Abstract base class for portfolio optimization

All optimizers should inherit from this class and implement
the optimize() method to convert alphas + covariance → weights.

Input format:
- alphas: pandas Series (asset → expected return/alpha)
- covariance: pandas DataFrame (N×N, asset×asset)

Output format:
- weights: pandas Series (asset → portfolio weight)
- Sum of weights = 1.0 (for long-only) or constrained by leverage
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np
import pandas as pd


class BaseOptimizer(ABC):
    """
    Abstract base class for portfolio optimizers.

    All optimizers must implement optimize() which takes alphas
    and covariance and produces optimal portfolio weights.
    """

    def __init__(
        self,
        risk_aversion: float = 1.0,
        long_only: bool = True,
    ):
        """
        Initialize optimizer.

        Args:
            risk_aversion: Risk aversion parameter (λ)
                - Higher values → more conservative
                - λ = 1.0 is typical default
            long_only: If True, only allow positive weights
        """
        self.risk_aversion = risk_aversion
        self.long_only = long_only
        self.weights_: Optional[pd.Series] = None

    @abstractmethod
    def optimize(
        self,
        alphas: pd.Series,
        covariance: pd.DataFrame,
    ) -> pd.Series:
        """
        Optimize portfolio weights given alphas and covariance.

        Args:
            alphas: Expected returns or alpha signals (asset → value)
            covariance: Covariance matrix (N×N DataFrame)

        Returns:
            Optimal portfolio weights (asset → weight)

        Raises:
            ValueError: If alphas and covariance have mismatched assets
        """
        pass

    def get_weights(self) -> pd.Series:
        """
        Get the optimized portfolio weights.

        Returns:
            Portfolio weights (asset → weight)

        Raises:
            ValueError: If optimize() hasn't been called yet
        """
        if self.weights_ is None:
            raise ValueError("Must call optimize() before get_weights()")
        return self.weights_

    def _validate_inputs(
        self,
        alphas: pd.Series,
        covariance: pd.DataFrame,
    ) -> None:
        """
        Validate that alphas and covariance are compatible.

        Args:
            alphas: Alpha signals
            covariance: Covariance matrix

        Raises:
            ValueError: If inputs are incompatible
        """
        # Check that assets match
        alpha_assets = set(alphas.index)
        cov_assets = set(covariance.index)

        if alpha_assets != cov_assets:
            raise ValueError(
                f"alphas and covariance must have same assets. "
                f"Alphas: {alpha_assets}, Covariance: {cov_assets}"
            )

        # Check covariance is square
        if covariance.shape[0] != covariance.shape[1]:
            raise ValueError(
                f"Covariance must be square, got {covariance.shape}"
            )

        # Check for NaN values
        if alphas.isna().any():
            raise ValueError("Alphas contain NaN values")

        if covariance.isna().any().any():
            raise ValueError("Covariance contains NaN values")

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(risk_aversion={self.risk_aversion}, long_only={self.long_only})"
        )
