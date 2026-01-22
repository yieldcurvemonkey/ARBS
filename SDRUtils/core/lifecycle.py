from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Fields that represent trade economics and should be overwritten on amendment
ECONOMICS_FIELDS: Set[str] = {
    # Notional
    "Notional amount-Leg 1",
    "Notional amount-Leg 2",
    "Notional amount in effect on associated effective date-Leg 1",
    "Notional amount in effect on associated effective date-Leg 2",
    # Rates
    "Fixed rate-Leg 1",
    "Fixed rate-Leg 2",
    "Spread-Leg 1",
    "Spread-Leg 2",
    # Option economics
    "Strike Price",
    "Option Premium Amount",
    "Price",
    # Package pricing
    "Package transaction price",
    "Package transaction spread",
    # Other payment
    "Other payment amount",
}


@dataclass
class ResolvedTrade:
    """
    Represents a resolved trade entity from SDR lifecycle events.

    This class tracks three distinct states to properly handle market vs regulatory data:

    1. inception_state: Original NEWT state (for volume calculation)
    2. market_state: What the market saw at execution time (for trading analytics)
    3. regulatory_state: Current official state after all corrections (for compliance)

    The distinction matters because CORR messages can arrive hours/days after execution
    to fix typos, but trading desks react to what they saw in real-time, not corrections.

    Attributes:
        synthetic_uti: Stable synthetic identifier for this trade entity
        message_ids: List of dissemination IDs that belong to this entity
        actions: List of (action_type, timestamp) tuples in order
        inception_state: State from the first NEWT message (for volume)
        market_state: State visible to market participants (updated by NEWT, MODI w/Amendment=True, TERM)
        regulatory_state: Final canonical state after all lifecycle updates (updated by all events)
        current_state: Alias for regulatory_state (backward compatibility)
        status: Current trade status (ACTIVE, TERMINATED, ERRORED)
        is_lifecycle_update: True if trade has MODI/CORR events (not standalone)
        quality_flags: List of data quality warnings
        history: List of state snapshots after each event
    """

    synthetic_uti: str
    message_ids: List[str] = field(default_factory=list)
    actions: List[Tuple[str, Any]] = field(default_factory=list)
    inception_state: Optional[Dict[str, Any]] = None
    market_state: Optional[Dict[str, Any]] = None
    regulatory_state: Optional[Dict[str, Any]] = None
    status: str = "UNKNOWN"  # ACTIVE, TERMINATED, ERRORED, UNKNOWN
    is_lifecycle_update: bool = False
    quality_flags: List[str] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def current_state(self) -> Optional[Dict[str, Any]]:
        """Alias for regulatory_state (backward compatibility)."""
        return self.regulatory_state

    @property
    def inception_notional(self) -> Optional[float]:
        """Get notional from inception state (NEWT) for volume calculation."""
        if not self.inception_state:
            return None
        return self.inception_state.get("Notional amount-Leg 1")

    @property
    def market_notional(self) -> Optional[float]:
        """Get notional from market state (what market saw at execution)."""
        if not self.market_state:
            return None
        return self.market_state.get("Notional amount-Leg 1")

    @property
    def regulatory_notional(self) -> Optional[float]:
        """Get notional from regulatory state (after all corrections)."""
        if not self.regulatory_state:
            return None
        return self.regulatory_state.get("Notional amount-Leg 1")

    @property
    def current_notional(self) -> Optional[float]:
        """Get notional from regulatory state (backward compatibility alias)."""
        return self.regulatory_notional

    @property
    def is_active(self) -> bool:
        """Check if trade is currently active."""
        return self.status == "ACTIVE"

    @property
    def is_new_trade(self) -> bool:
        """
        Check if this represents a genuinely new trade (not just lifecycle update).

        For volume counting, only count trades that have a NEWT action.
        """
        return any(action == "NEWT" for action, _ in self.actions)


def _is_null_value(value: Any) -> bool:
    """Check if a value is null/NA/empty."""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _update_state(
    state: Optional[Dict[str, object]],
    row: Dict[str, object],
    *,
    overwrite: bool,
    economics_only: bool = False,
) -> Dict[str, object]:
    """
    Update trade state with new row data.

    Args:
        state: Current trade state (or None to initialize)
        row: New row data to merge
        overwrite: If True, overwrite existing values; if False, only fill nulls
        economics_only: If True and overwrite=True, only overwrite economics fields

    Returns:
        Updated state dict
    """
    if state is None:
        state = {}

    for key, value in row.items():
        if _is_null_value(value):
            continue

        should_update = False
        if overwrite:
            if economics_only:
                # Only overwrite if this is an economics field
                should_update = key in ECONOMICS_FIELDS
            else:
                should_update = True
        else:
            # Only fill if current value is null
            should_update = key not in state or _is_null_value(state.get(key))

        if should_update:
            state[key] = value

    return state


def replay_lifecycle(
    messages: pd.DataFrame,
    *,
    action_col: str = "Action type",
    event_type_col: str = "Event type",
    event_timestamp_col: str = "Event timestamp",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    sort: bool = True,
) -> Tuple[Optional[Dict[str, object]], Optional[Dict[str, object]], List[Dict[str, object]]]:
    """
    Replay SDR lifecycle events to reconstruct market and regulatory states.

    This function processes SDR messages in timestamp order, maintaining two
    distinct states:

    1. market_state: What market participants saw (updated by NEWT, MODI w/Amendment=True, TERM)
    2. regulatory_state: Official state after corrections (updated by all events including CORR)

    State update rules by action type:

    - NEWT: Initialize both states
    - MODI (Amendment=True): Update economics in both states (market event)
    - MODI (Amendment=False): Update only regulatory_state (late data, not disseminated)
    - CORR: Update only regulatory_state (error correction, not market event)
    - TERM: Update both states, set Active=False
    - EROR: Invalidate trade entirely
    - VALU/MARU: Update only regulatory_state (valuations, not market events)

    Args:
        messages: DataFrame containing SDR messages for a single trade entity
        action_col: Column name for action type
        event_type_col: Column name for event type (TRAD, NOVA, etc.)
        event_timestamp_col: Column name for event timestamp
        amendment_indicator_col: Column name for amendment indicator
        dissemination_col: Column name for dissemination identifier
        sort: Whether to sort messages by timestamp

    Returns:
        Tuple of:
        - market_state dict (or None if trade was errored)
        - regulatory_state dict (or None if trade was errored)
        - History of state snapshots after each event
    """
    if messages.empty:
        return None, None, []

    if sort and event_timestamp_col in messages.columns:
        messages = messages.sort_values(event_timestamp_col, kind="mergesort")

    market_state: Optional[Dict[str, object]] = None
    regulatory_state: Optional[Dict[str, object]] = None
    history: List[Dict[str, object]] = []

    for _, row in messages.iterrows():
        action = row.get(action_col)
        event_type = row.get(event_type_col)
        row_data = row.to_dict()

        if action == "NEWT":
            # NEWT initializes both market and regulatory states identically
            initial_state = row_data.copy()
            initial_state["Active"] = True
            market_state = initial_state.copy()
            regulatory_state = initial_state.copy()

        elif action == "MODI":
            # Check for Amendment indicator
            is_amendment = row.get(amendment_indicator_col)
            is_true_amendment = is_amendment is True or (isinstance(is_amendment, str) and is_amendment.upper() == "TRUE")

            if is_true_amendment:
                # Amendment=True: Market event (mutually agreed change)
                # Update BOTH market_state and regulatory_state
                # Overwrite economics fields, fill other nulls
                market_state = _update_state(market_state, row_data, overwrite=True, economics_only=True)
                market_state = _update_state(market_state, row_data, overwrite=False)

                regulatory_state = _update_state(regulatory_state, row_data, overwrite=True, economics_only=True)
                regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
            else:
                # Amendment=False or None: Late-arriving data, NOT disseminated
                # Update ONLY regulatory_state (fill nulls)
                regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
                # market_state remains unchanged

        elif action == "CORR":
            # CORR: Error correction, NOT a market event
            # Update ONLY regulatory_state (overwrite all fields)
            regulatory_state = _update_state(regulatory_state, row_data, overwrite=True)
            # market_state remains unchanged

        elif action == "TERM":
            # TERM: Termination is a market event
            # Update BOTH states, set Active=False
            market_state = _update_state(market_state, row_data, overwrite=False)
            if market_state:
                market_state["Active"] = False

            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
            if regulatory_state:
                regulatory_state["Active"] = False

        elif action == "EROR":
            # Error action invalidates the trade entirely
            market_state = None
            regulatory_state = None
            history = []
            continue

        elif action in {"VALU", "MARU"}:
            # Valuation/margin updates - NOT market events, update regulatory only
            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)

        elif action == "REVI":
            # Revival - restore a previously errored/terminated trade
            # Update both states
            market_state = _update_state(market_state, row_data, overwrite=False)
            if market_state:
                market_state["Active"] = True

            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
            if regulatory_state:
                regulatory_state["Active"] = True

        else:
            # Unknown action - treat as regulatory update (fill nulls)
            logger.warning(f"Unknown action type: {action}")
            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)

        # Record both states in history
        if market_state is not None or regulatory_state is not None:
            history.append({
                "market_state": market_state.copy() if market_state else None,
                "regulatory_state": regulatory_state.copy() if regulatory_state else None,
            })

    return market_state, regulatory_state, history


def replay_lifecycle_full(
    messages: pd.DataFrame,
    synthetic_uti: str,
    *,
    action_col: str = "Action type",
    event_type_col: str = "Event type",
    event_timestamp_col: str = "Event timestamp",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    sort: bool = True,
) -> ResolvedTrade:
    """
    Replay SDR lifecycle events and return a full ResolvedTrade object.

    This is an enhanced version of replay_lifecycle that tracks additional
    metadata needed for volume calculation and trade classification.

    Maintains three distinct states:
    - inception_state: Original NEWT state (for volume)
    - market_state: What market saw (for trading analytics)
    - regulatory_state: Official state after corrections (for compliance)

    Args:
        messages: DataFrame containing SDR messages for a single trade entity
        synthetic_uti: The synthetic UTI for this trade entity
        action_col: Column name for action type
        event_type_col: Column name for event type (TRAD, NOVA, etc.)
        event_timestamp_col: Column name for event timestamp
        amendment_indicator_col: Column name for amendment indicator
        dissemination_col: Column name for dissemination identifier
        sort: Whether to sort messages by timestamp

    Returns:
        ResolvedTrade object with full lifecycle metadata
    """
    if messages.empty:
        return ResolvedTrade(synthetic_uti=synthetic_uti, status="UNKNOWN")

    if sort and event_timestamp_col in messages.columns:
        messages = messages.sort_values(event_timestamp_col, kind="mergesort")

    resolved = ResolvedTrade(synthetic_uti=synthetic_uti)
    market_state: Optional[Dict[str, object]] = None
    regulatory_state: Optional[Dict[str, object]] = None
    inception_state: Optional[Dict[str, object]] = None

    # Collect message IDs and actions
    for _, row in messages.iterrows():
        dissem_id = row.get(dissemination_col)
        if dissem_id and not pd.isna(dissem_id):
            resolved.message_ids.append(str(dissem_id))

        action = row.get(action_col)
        timestamp = row.get(event_timestamp_col)
        resolved.actions.append((action, timestamp))

    # Check for lifecycle updates (MODI/CORR without being the only action)
    action_types = {a for a, _ in resolved.actions}
    resolved.is_lifecycle_update = bool(action_types & {"MODI", "CORR", "TERM"})

    # Check for missing NEWT
    if "NEWT" not in action_types:
        resolved.quality_flags.append("MISSING_NEWT")

    # Replay lifecycle
    for _, row in messages.iterrows():
        action = row.get(action_col)
        event_type = row.get(event_type_col)
        row_data = row.to_dict()

        if action == "NEWT":
            # NEWT initializes all three states
            initial_state = row_data.copy()
            initial_state["Active"] = True
            inception_state = initial_state.copy()
            market_state = initial_state.copy()
            regulatory_state = initial_state.copy()

        elif action == "MODI":
            is_amendment = row.get(amendment_indicator_col)
            is_true_amendment = is_amendment is True or (isinstance(is_amendment, str) and is_amendment.upper() == "TRUE")

            if is_true_amendment:
                # Amendment=True: Market event, update both states
                market_state = _update_state(market_state, row_data, overwrite=True, economics_only=True)
                market_state = _update_state(market_state, row_data, overwrite=False)

                regulatory_state = _update_state(regulatory_state, row_data, overwrite=True, economics_only=True)
                regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
            else:
                # Amendment=False: Late data, update only regulatory_state
                regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)

        elif action == "CORR":
            # CORR: Error correction, update only regulatory_state
            regulatory_state = _update_state(regulatory_state, row_data, overwrite=True)

        elif action == "TERM":
            # TERM: Market event, update both states
            market_state = _update_state(market_state, row_data, overwrite=False)
            if market_state:
                market_state["Active"] = False

            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
            if regulatory_state:
                regulatory_state["Active"] = False

        elif action == "EROR":
            resolved.status = "ERRORED"
            resolved.market_state = None
            resolved.regulatory_state = None
            resolved.history = []
            return resolved

        elif action in {"VALU", "MARU"}:
            # Valuation: Not a market event, update only regulatory_state
            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)

        elif action == "REVI":
            # Revival: Update both states
            market_state = _update_state(market_state, row_data, overwrite=False)
            if market_state:
                market_state["Active"] = True

            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)
            if regulatory_state:
                regulatory_state["Active"] = True

        else:
            logger.warning(f"Unknown action type: {action}")
            regulatory_state = _update_state(regulatory_state, row_data, overwrite=False)

        # Record both states in history
        if market_state is not None or regulatory_state is not None:
            resolved.history.append({
                "market_state": market_state.copy() if market_state else None,
                "regulatory_state": regulatory_state.copy() if regulatory_state else None,
            })

    # Set final states
    resolved.inception_state = inception_state
    resolved.market_state = market_state
    resolved.regulatory_state = regulatory_state

    # Determine status based on regulatory_state (official status)
    if regulatory_state is None:
        resolved.status = "ERRORED"
    elif regulatory_state.get("Active") is False:
        resolved.status = "TERMINATED"
    else:
        resolved.status = "ACTIVE"

    return resolved
