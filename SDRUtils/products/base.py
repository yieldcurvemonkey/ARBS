from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import pandas as pd

from SDRUtils.core.classification import TradeClassification


class ProductModule(ABC):
    """Base interface for SDR product modules."""

    name: str
    product_type: str

    @abstractmethod
    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs: Any) -> TradeClassification:
        """Return a structured classification for a single trade."""

    def classify_product_type(self, row: pd.Series) -> Optional[str]:
        """Optional hook for product-specific type inference."""
        return None

    def metadata(self) -> Dict[str, str]:
        """Metadata for discovery and registry documentation."""
        return {"name": self.name, "product_type": self.product_type}
