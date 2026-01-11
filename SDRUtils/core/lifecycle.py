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

    This class tracks both the inception state (from NEWT) and the current
    canonical state after all lifecycle updates have been replayed.

    Attributes:
        synthetic_uti: Stable synthetic identifier for this trade entity
        message_ids: List of dissemination IDs that belong to this entity
        actions: List of (action_type, timestamp) tuples in order
        inception_state: State from the first NEWT message (for volume)
        current_state: Final canonical state after all lifecycle updates
        status: Current trade status (ACTIVE, TERMINATED, ERRORED)
        is_lifecycle_update: True if trade has MODI/CORR events (not standalone)
        quality_flags: List of data quality warnings
        history: List of state snapshots after each event
    """

    synthetic_uti: str
    message_ids: List[str] = field(default_factory=list)
    actions: List[Tuple[str, Any]] = field(default_factory=list)
    inception_state: Optional[Dict[str, Any]] = None
    current_state: Optional[Dict[str, Any]] = None
    status: str = "UNKNOWN"  # ACTIVE, TERMINATED, ERRORED, UNKNOWN
    is_lifecycle_update: bool = False
    quality_flags: List[str] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def inception_notional(self) -> Optional[float]:
        """Get notional from inception state (NEWT) for volume calculation."""
        if not self.inception_state:
            return None
        return self.inception_state.get("Notional amount-Leg 1")

    @property
    def current_notional(self) -> Optional[float]:
        """Get notional from current state after lifecycle updates."""
        if not self.current_state:
            return None
        return self.current_state.get("Notional amount-Leg 1")

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
    event_timestamp_col: str = "Event timestamp",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    sort: bool = True,
) -> Tuple[Optional[Dict[str, object]], List[Dict[str, object]]]:
    """
    Replay SDR lifecycle events to reconstruct the current state.

    This function processes SDR messages in timestamp order, applying the
    appropriate state transitions for each action type:

    - NEWT: Initialize new trade state
    - MODI: Update state (fill nulls only, unless Amendment indicator=True)
    - CORR: Correct state (overwrite all fields)
    - TERM: Terminate trade (update state, set Active=False)
    - EROR: Error - invalidate trade
    - VALU/MARU: Valuation updates (fill nulls only)

    Args:
        messages: DataFrame containing SDR messages for a single trade entity
        action_col: Column name for action type
        event_timestamp_col: Column name for event timestamp
        amendment_indicator_col: Column name for amendment indicator
        dissemination_col: Column name for dissemination identifier
        sort: Whether to sort messages by timestamp

    Returns:
        Tuple of:
        - Final state dict (or None if trade was errored)
        - History of state snapshots after each event
    """
    if messages.empty:
        return None, []

    if sort and event_timestamp_col in messages.columns:
        messages = messages.sort_values(event_timestamp_col, kind="mergesort")

    state: Optional[Dict[str, object]] = None
    history: List[Dict[str, object]] = []

    for _, row in messages.iterrows():
        action = row.get(action_col)
        row_data = row.to_dict()

        if action == "NEWT":
            state = row_data.copy()
            state["Active"] = True
            # Store inception state marker for volume calculation
            state["_is_inception"] = True

        elif action == "MODI":
            # Check for Amendment indicator - if True, overwrite economics
            is_amendment = row.get(amendment_indicator_col)
            if is_amendment is True or (isinstance(is_amendment, str) and is_amendment.upper() == "TRUE"):
                # Amendment modifies economics - overwrite economics fields only
                state = _update_state(state, row_data, overwrite=True, economics_only=True)
                # Also fill in any other null fields
                state = _update_state(state, row_data, overwrite=False)
            else:
                # Regular modification - just fill nulls
                state = _update_state(state, row_data, overwrite=False)

        elif action == "CORR":
            # Correction overwrites all fields
            state = _update_state(state, row_data, overwrite=True)

        elif action == "TERM":
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = False

        elif action == "EROR":
            # Error action invalidates the trade entirely
            state = None
            history = []
            continue

        elif action in {"VALU", "MARU"}:
            # Valuation/margin updates - fill nulls only
            state = _update_state(state, row_data, overwrite=False)

        elif action == "REVI":
            # Revival - restore a previously errored/terminated trade
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = True

        else:
            # Unknown action - treat as update (fill nulls)
            logger.warning(f"Unknown action type: {action}")
            state = _update_state(state, row_data, overwrite=False)

        if state is not None:
            history.append(state.copy())

    return state, history


def replay_lifecycle_full(
    messages: pd.DataFrame,
    synthetic_uti: str,
    *,
    action_col: str = "Action type",
    event_timestamp_col: str = "Event timestamp",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    sort: bool = True,
) -> ResolvedTrade:
    """
    Replay SDR lifecycle events and return a full ResolvedTrade object.

    This is an enhanced version of replay_lifecycle that tracks additional
    metadata needed for volume calculation and trade classification.

    Args:
        messages: DataFrame containing SDR messages for a single trade entity
        synthetic_uti: The synthetic UTI for this trade entity
        action_col: Column name for action type
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
    state: Optional[Dict[str, object]] = None
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
        row_data = row.to_dict()

        if action == "NEWT":
            state = row_data.copy()
            state["Active"] = True
            inception_state = state.copy()

        elif action == "MODI":
            is_amendment = row.get(amendment_indicator_col)
            if is_amendment is True or (isinstance(is_amendment, str) and is_amendment.upper() == "TRUE"):
                state = _update_state(state, row_data, overwrite=True, economics_only=True)
                state = _update_state(state, row_data, overwrite=False)
            else:
                state = _update_state(state, row_data, overwrite=False)

        elif action == "CORR":
            state = _update_state(state, row_data, overwrite=True)

        elif action == "TERM":
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = False

        elif action == "EROR":
            resolved.status = "ERRORED"
            resolved.current_state = None
            resolved.history = []
            return resolved

        elif action in {"VALU", "MARU"}:
            state = _update_state(state, row_data, overwrite=False)

        elif action == "REVI":
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = True

        else:
            logger.warning(f"Unknown action type: {action}")
            state = _update_state(state, row_data, overwrite=False)

        if state is not None:
            resolved.history.append(state.copy())

    # Set final state
    resolved.inception_state = inception_state
    resolved.current_state = state

    # Determine status
    if state is None:
        resolved.status = "ERRORED"
    elif state.get("Active") is False:
        resolved.status = "TERMINATED"
    else:
        resolved.status = "ACTIVE"

    return resolved
