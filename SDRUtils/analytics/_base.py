"""
Abstract base class for SDR analytics modules.

Provides the compute/summary pattern for DataFrame-in, DataFrame-out analyzers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd


class SDRAnalyzer(ABC):
    """Base class for stateful SDR analyzers.

    Subclasses implement compute() to produce a result DataFrame
    and optionally override summary() for key metrics.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df.copy()
        self._result: pd.DataFrame | None = None

    @property
    def df(self) -> pd.DataFrame:
        """Input DataFrame."""
        return self._df

    @abstractmethod
    def compute(self) -> pd.DataFrame:
        """Run the analysis and return result DataFrame."""
        ...

    def summary(self) -> Dict[str, Any]:
        """Return key metrics as a dict. Override in subclasses."""
        if self._result is None:
            self._result = self.compute()
        return {"n_rows": len(self._result)}
