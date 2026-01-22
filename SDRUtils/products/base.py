"""
Base interface for SDR product modules.

This module defines the abstract base class that all product implementations
must inherit from. Products are organized by currency and product type.

The classify_messages() method processes new trade executions only:

- **Filtering**: Only processes messages with Action type="NEWT" and
  Event type="TRAD" to capture initial trade executions.
- **Direct Classification**: Each trade is classified as-is without lifecycle
  state resolution or replay.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from SDRUtils.core.classification import TradeClassification
from SDRUtils.core.lifecycle import ResolvedTrade

logger = logging.getLogger(__name__)


@dataclass
class ClassificationError:
    """Represents a failed trade classification attempt."""

    synthetic_uti: str
    dissemination_ids: List[str]
    error_type: str
    error_message: str
    action_types: List[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    """
    Result of classifying SDR messages with lifecycle resolution.

    Includes both successful classifications and error tracking for debugging.
    Volume semantics are tracked to distinguish inception vs current notional.
    """

    classifications: List[TradeClassification]
    resolved_trades: List[ResolvedTrade]
    errors: List[ClassificationError]

    @property
    def total_trades(self) -> int:
        """Total number of resolved trade entities."""
        return len(self.resolved_trades)

    @property
    def active_trades(self) -> int:
        """Number of currently active trades."""
        return sum(1 for t in self.resolved_trades if t.is_active)

    @property
    def new_trades(self) -> int:
        """Number of genuinely new trades (with NEWT action)."""
        return sum(1 for t in self.resolved_trades if t.is_new_trade)

    @property
    def lifecycle_updates(self) -> int:
        """Number of trades that had lifecycle updates (MODI/CORR/TERM)."""
        return sum(1 for t in self.resolved_trades if t.is_lifecycle_update)

    @property
    def error_count(self) -> int:
        """Number of classification errors."""
        return len(self.errors)


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
        action_col: str = "Action type",
        event_type_col: str = "Event type",
        **kwargs: Any,
    ) -> List[TradeClassification]:
        """
        Classify SDR messages for new trades only.

        This simplified method filters for new trade executions and classifies
        them directly without lifecycle replay:

        1. **Filtering**: Only processes messages with Action type="NEWT" and
           Event type="TRAD" to capture initial trade executions.
        2. **Direct Classification**: Each trade is classified as-is without
           lifecycle state resolution.

        Args:
            messages: SDR message DataFrame.
            dissemination_col: Column with dissemination identifiers.
            action_col: Column name for action type.
            event_type_col: Column name for event type.
            **kwargs: Additional arguments passed to classify_trade.

        Returns:
            List of TradeClassification objects for new trades.
        """
        if messages.empty:
            return []

        # Filter for new trades only (Action type="NEWT" and Event type="TRAD")
        filtered = messages[
            (messages[action_col] == "NEWT") & (messages[event_type_col] == "TRAD")
        ].copy()

        if filtered.empty:
            return []

        classifications: List[TradeClassification] = []

        for idx, row in tqdm(filtered.iterrows(), desc="Classifying Trades", unit="trade", total=len(filtered)):
            try:
                if not self.validate_row(row):
                    continue
                trade_id = row.get(dissemination_col, idx)
                classifications.append(self.classify_trade(row, trade_id=trade_id, **kwargs))
            except Exception as e:
                # Log error with context for debugging
                dissem_id = row.get(dissemination_col, "unknown")
                logger.error(
                    f"Failed to classify trade {dissem_id}: {type(e).__name__}: {e}"
                )

        return classifications

    def classify_messages_full(
        self,
        messages: pd.DataFrame,
        *,
        dissemination_col: str = "Dissemination Identifier",
        action_col: str = "Action type",
        event_type_col: str = "Event type",
        event_timestamp_col: str = "Event timestamp",
        **kwargs: Any,
    ) -> ClassificationResult:
        """
        Classify SDR messages for new trades with error tracking.

        This is an enhanced version of classify_messages() that returns:
        - All successful TradeClassification objects
        - Simplified ResolvedTrade objects (one per NEWT trade)
        - ClassificationError objects for failed classifications

        Only processes Action type="NEWT" and Event type="TRAD" messages.

        Args:
            messages: SDR message DataFrame.
            dissemination_col: Column with dissemination identifiers.
            action_col: Column name for action type.
            event_type_col: Column name for event type.
            event_timestamp_col: Column name for event timestamp.
            **kwargs: Additional arguments passed to classify_trade.

        Returns:
            ClassificationResult with classifications, resolved trades, and errors.
        """
        if messages.empty:
            return ClassificationResult(
                classifications=[],
                resolved_trades=[],
                errors=[],
            )

        # Filter for new trades only (Action type="NEWT" and Event type="TRAD")
        filtered = messages[
            (messages[action_col] == "NEWT") & (messages[event_type_col] == "TRAD")
        ].copy()

        if filtered.empty:
            return ClassificationResult(
                classifications=[],
                resolved_trades=[],
                errors=[],
            )

        classifications: List[TradeClassification] = []
        resolved_trades: List[ResolvedTrade] = []
        errors: List[ClassificationError] = []

        for idx, row in tqdm(filtered.iterrows(), desc="Classifying Trades", unit="trade", total=len(filtered)):
            dissem_id = row.get(dissemination_col, str(idx))

            try:
                # Create simplified ResolvedTrade for this new trade
                trade_state = row.to_dict()
                event_ts = row.get(event_timestamp_col)

                resolved_trade = ResolvedTrade(
                    synthetic_uti=dissem_id,
                    message_ids=[dissem_id],
                    actions=[("NEWT", event_ts)],
                    inception_state=trade_state,
                    current_state=trade_state,
                    status="ACTIVE",
                    is_lifecycle_update=False,
                    quality_flags=[],
                    history=[],
                )
                resolved_trades.append(resolved_trade)

                # Classify the trade
                if not self.validate_row(row):
                    continue

                classification = self.classify_trade(row, trade_id=dissem_id, **kwargs)
                classifications.append(classification)

            except Exception as e:
                # Track error with full context
                error = ClassificationError(
                    synthetic_uti=dissem_id,
                    dissemination_ids=[dissem_id],
                    error_type=type(e).__name__,
                    error_message=str(e),
                    action_types=["NEWT"],
                )
                errors.append(error)

                logger.error(
                    f"Failed to classify trade {dissem_id}: {type(e).__name__}: {e}"
                )

        return ClassificationResult(
            classifications=classifications,
            resolved_trades=resolved_trades,
            errors=errors,
        )

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
