from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd


class PackageDetector(ABC):
    """Base interface for SDR package detectors."""

    package_type: str

    @abstractmethod
    def detect(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Return a dataframe with package annotations applied."""

    def metadata(self) -> Dict[str, str]:
        return {"package_type": self.package_type}
