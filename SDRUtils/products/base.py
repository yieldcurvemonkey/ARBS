"""
Base interface for SDR product modules.

This module defines the abstract base class that all product implementations
must inherit from. Products are organized by currency and product type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd
from tqdm import tqdm

from SDRUtils.core.classification import TradeClassification
from SDRUtils.core.graph_resolver import assign_synthetic_uti
from SDRUtils.core.lifecycle import replay_lifecycle


class ProductModule(ABC):
    """
    Base interface for SDR product modules.

    All product implementations (USD SOFR swaps, EUR ESTR swaps, swaptions, etc.)
    must inherit from this class and implement the required methods.

    Attributes:
        name: Unique identifier for the product (e.g., "USD-SOFR-OIS")
        product_type: Type of product (e.g., "OIS_SWAP", "SWAPTION")
        currency: Currency of the product (optional, used for multi-currency products)
    """

    name: str
    product_type: str
    currency: Optional[str] = None

    @abstractmethod
    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs: Any) -> TradeClassification:
        """
        Classify a single SDR trade row.

        This is the main entry point for trade classification. Implementations
        should extract all relevant trade characteristics and return a
        TradeClassification object.

        Args:
            row: SDR data row as pandas Series
            trade_id: Unique identifier for the trade
            **kwargs: Additional arguments (e.g., curve for PV01 calculation)

        Returns:
            TradeClassification object with all trade details
        """
        pass

    def classify_product_type(self, row: pd.Series) -> Optional[str]:
        """
        Infer product type from SDR row.

        Optional hook for product-specific type inference. Default returns None.

        Args:
            row: SDR data row

        Returns:
            Product type string or None
        """
        return None

    def validate_row(self, row: pd.Series) -> bool:
        """
        Validate that a row can be classified by this product module.

        Optional hook for input validation. Default returns True.

        Args:
            row: SDR data row

        Returns:
            True if row can be classified, False otherwise
        """
        return True

    def classify_messages(
        self,
        messages: pd.DataFrame,
        *,
        dissemination_col: str = "Dissemination Identifier",
        original_col: str = "Original Dissemination Identifier",
        synthetic_col: str = "Synthetic UTI",
        action_col: str = "Action type",
        event_timestamp_col: str = "Event timestamp",
        **kwargs: Any,
    ) -> List[TradeClassification]:
        """
        Classify a set of SDR messages by resolving lifecycle state.

        Args:
            messages: SDR message DataFrame containing lifecycle updates.
            dissemination_col: Column with dissemination identifiers.
            original_col: Column with original dissemination identifiers.
            synthetic_col: Column name for resolved synthetic UTI.
            action_col: Column name for action type.
            event_timestamp_col: Column name for event timestamp.
            **kwargs: Additional arguments passed to classify_trade.

        Returns:
            List of TradeClassification objects for active trades.
        """
        if messages.empty:
            return []

        messages = messages.sort_values(by=event_timestamp_col)

        resolved = assign_synthetic_uti(
            messages,
            dissemination_col=dissemination_col,
            original_col=original_col,
            synthetic_col=synthetic_col,
        )

        classifications: List[TradeClassification] = []
        groups = resolved.groupby(synthetic_col, dropna=False)
        # for _, group in resolved.groupby(synthetic_col, dropna=False):
        for _, group in tqdm(groups, desc="Classifying Trades", unit="trade"):
            try:
                state, _ = replay_lifecycle(group, action_col=action_col, event_timestamp_col=event_timestamp_col)
                if state is None:
                    continue
                row = pd.Series(state)
                if not self.validate_row(row):
                    continue
                trade_id = row.get(dissemination_col) or row.get(synthetic_col)
                classifications.append(self.classify_trade(row, trade_id=trade_id, **kwargs))
            except Exception as e:
                # TODO handle errors
                pass

        return classifications

    def metadata(self) -> Dict[str, Any]:
        """
        Return metadata for discovery and registry documentation.

        Returns:
            Dict with product metadata
        """
        return {
            "name": self.name,
            "product_type": self.product_type,
            "currency": self.currency,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"
