"""
Base interface for SDR product modules.

This module defines the abstract base class that all product implementations
must inherit from. Products are organized by currency and product type.

The classify_messages() method handles SDR lifecycle event resolution to avoid
double counting/phantom trades. Key concepts:

- **Synthetic UTI**: A stable identifier for a trade entity, computed by
  clustering related dissemination IDs via graph analysis.
- **Lifecycle Replay**: Processes NEWT/MODI/CORR/TERM/EROR actions in
  timestamp order to reconstruct the canonical trade state.
- **Amendment Handling**: MODI with Amendment indicator=True overwrites
  economics fields; otherwise only fills nulls.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from SDRUtils.core.classification import TradeClassification
from SDRUtils.core.graph_resolver import assign_synthetic_uti
from SDRUtils.core.lifecycle import ResolvedTrade, replay_lifecycle, replay_lifecycle_full

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
        original_col: str = "Original Dissemination Identifier",
        synthetic_col: str = "Synthetic UTI",
        action_col: str = "Action type",
        event_timestamp_col: str = "Event timestamp",
        amendment_indicator_col: str = "Amendment indicator",
        **kwargs: Any,
    ) -> List[TradeClassification]:
        """
        Classify a set of SDR messages by resolving lifecycle state.

        This method handles SDR lifecycle event resolution to avoid double
        counting/phantom trades:

        1. **Clustering**: Groups related messages (NEWT→MODI→CORR chains)
           into trade entities using graph analysis on dissemination IDs.
        2. **Lifecycle Replay**: Processes actions in timestamp order to
           reconstruct the canonical trade state.
        3. **Classification**: Classifies the resolved state.

        For each trade entity, only the canonical state after all lifecycle
        updates is classified. MODI messages fill missing fields (or overwrite
        economics if Amendment indicator=True), CORR messages overwrite all
        fields, and EROR messages invalidate the trade.

        Args:
            messages: SDR message DataFrame containing lifecycle updates.
            dissemination_col: Column with dissemination identifiers.
            original_col: Column with original dissemination identifiers.
            synthetic_col: Column name for resolved synthetic UTI.
            action_col: Column name for action type.
            event_timestamp_col: Column name for event timestamp.
            amendment_indicator_col: Column name for amendment indicator.
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
            action_col=action_col,
            event_timestamp_col=event_timestamp_col,
            synthetic_col=synthetic_col,
        )

        classifications: List[TradeClassification] = []
        groups = resolved.groupby(synthetic_col, dropna=False)

        for synthetic_uti, group in tqdm(groups, desc="Classifying Trades", unit="trade"):
            try:
                # replay_lifecycle now returns (market_state, regulatory_state, history)
                # Use regulatory_state for classification (official corrected state)
                _, regulatory_state, _ = replay_lifecycle(
                    group,
                    action_col=action_col,
                    event_timestamp_col=event_timestamp_col,
                    amendment_indicator_col=amendment_indicator_col,
                    dissemination_col=dissemination_col,
                )
                if regulatory_state is None:
                    # Trade was errored or has no valid state
                    continue
                state = regulatory_state
                row = pd.Series(state)
                if not self.validate_row(row):
                    continue
                trade_id = row.get(dissemination_col) or synthetic_uti
                classifications.append(self.classify_trade(row, trade_id=trade_id, **kwargs))
            except Exception as e:
                # Log error with context for debugging
                dissem_ids = group[dissemination_col].dropna().astype(str).tolist()
                action_types = group[action_col].dropna().astype(str).tolist()
                logger.error(
                    f"Failed to classify trade entity {synthetic_uti}: {type(e).__name__}: {e}. "
                    f"Dissemination IDs: {dissem_ids[:5]}{'...' if len(dissem_ids) > 5 else ''}, "
                    f"Actions: {action_types}"
                )

        return classifications

    def classify_messages_full(
        self,
        messages: pd.DataFrame,
        *,
        dissemination_col: str = "Dissemination Identifier",
        original_col: str = "Original Dissemination Identifier",
        synthetic_col: str = "Synthetic UTI",
        action_col: str = "Action type",
        event_timestamp_col: str = "Event timestamp",
        amendment_indicator_col: str = "Amendment indicator",
        **kwargs: Any,
    ) -> ClassificationResult:
        """
        Classify SDR messages with full lifecycle metadata and error tracking.

        This is an enhanced version of classify_messages() that returns:
        - All successful TradeClassification objects
        - Full ResolvedTrade objects with lifecycle metadata
        - ClassificationError objects for failed classifications

        Use this method when you need:
        - Volume semantics (inception_notional vs current_notional)
        - Error tracking and debugging
        - Trade status tracking (ACTIVE/TERMINATED/ERRORED)

        Args:
            messages: SDR message DataFrame containing lifecycle updates.
            dissemination_col: Column with dissemination identifiers.
            original_col: Column with original dissemination identifiers.
            synthetic_col: Column name for resolved synthetic UTI.
            action_col: Column name for action type.
            event_timestamp_col: Column name for event timestamp.
            amendment_indicator_col: Column name for amendment indicator.
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

        messages = messages.sort_values(by=event_timestamp_col)

        resolved = assign_synthetic_uti(
            messages,
            dissemination_col=dissemination_col,
            original_col=original_col,
            action_col=action_col,
            event_timestamp_col=event_timestamp_col,
            synthetic_col=synthetic_col,
        )

        classifications: List[TradeClassification] = []
        resolved_trades: List[ResolvedTrade] = []
        errors: List[ClassificationError] = []

        groups = resolved.groupby(synthetic_col, dropna=False)

        for synthetic_uti, group in tqdm(groups, desc="Classifying Trades", unit="trade"):
            try:
                # Use full lifecycle replay to get ResolvedTrade with metadata
                resolved_trade = replay_lifecycle_full(
                    group,
                    synthetic_uti=str(synthetic_uti),
                    action_col=action_col,
                    event_timestamp_col=event_timestamp_col,
                    amendment_indicator_col=amendment_indicator_col,
                    dissemination_col=dissemination_col,
                )
                resolved_trades.append(resolved_trade)

                # Skip errored/invalid trades
                if resolved_trade.current_state is None:
                    continue

                row = pd.Series(resolved_trade.current_state)
                if not self.validate_row(row):
                    continue

                trade_id = row.get(dissemination_col) or synthetic_uti
                classification = self.classify_trade(row, trade_id=trade_id, **kwargs)
                classifications.append(classification)

            except Exception as e:
                # Track error with full context
                dissem_ids = group[dissemination_col].dropna().astype(str).tolist()
                action_types = group[action_col].dropna().astype(str).tolist()

                error = ClassificationError(
                    synthetic_uti=str(synthetic_uti),
                    dissemination_ids=dissem_ids,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    action_types=action_types,
                )
                errors.append(error)

                logger.error(
                    f"Failed to classify trade entity {synthetic_uti}: {type(e).__name__}: {e}. "
                    f"Dissemination IDs: {dissem_ids[:5]}{'...' if len(dissem_ids) > 5 else ''}, "
                    f"Actions: {action_types}"
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
