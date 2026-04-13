from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
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


def build_lifecycle_summary_from_resolved(
    resolved: ResolvedTrade,
    file_dates: Optional[Dict[str, date]] = None,
    *,
    execution_timestamp_col: str = "Execution Timestamp",
    event_timestamp_col: str = "Event timestamp",
    action_col: str = "Action type",
    event_type_col: str = "Event type",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    original_dissemination_col: str = "Original Dissemination Identifier",
) -> "LifecycleSummary":
    """
    Build a LifecycleSummary from a ResolvedTrade's history.

    Converts the ResolvedTrade's history snapshots into LifecycleEvents
    and delegates to build_summary(). This is a bridge between the
    existing lifecycle pipeline and the new V2 correction tracking.

    Args:
        resolved: ResolvedTrade with populated history
        file_dates: Mapping of dissemination_id -> file_date. If None,
            all events get a default date from execution timestamp.

    Returns:
        LifecycleSummary with correction flags and field-level diffs
    """
    from SDRUtils.core.lifecycle_v2 import LifecycleEvent, LifecycleSummary, build_summary

    if not resolved.history:
        return LifecycleSummary()

    if file_dates is None:
        file_dates = {}

    events: list[LifecycleEvent] = []
    prev_state: Optional[Dict[str, Any]] = None

    # Use resolved.actions for authoritative per-event action types,
    # since history snapshots accumulate state and may not reflect
    # the action that produced each snapshot.
    actions_list = resolved.actions  # list of (action_type, timestamp)

    message_ids = resolved.message_ids  # list of dissemination IDs in order

    for idx, snapshot in enumerate(resolved.history):
        # Use authoritative per-event data from actions/message_ids,
        # since history snapshots accumulate state.
        if idx < len(message_ids):
            dissem_id = message_ids[idx]
        else:
            dissem_id = str(snapshot.get(dissemination_col, ""))

        if idx < len(actions_list):
            action = actions_list[idx][0]
        else:
            action = snapshot.get(action_col, "")
        event_type = snapshot.get(event_type_col)
        if isinstance(event_type, float) and pd.isna(event_type):
            event_type = None

        amendment = snapshot.get(amendment_indicator_col)
        if isinstance(amendment, str):
            amendment = amendment.upper() == "TRUE"
        elif not isinstance(amendment, bool):
            amendment = None

        event_ts_raw = snapshot.get(event_timestamp_col)
        exec_ts_raw = snapshot.get(execution_timestamp_col)
        event_ts = pd.Timestamp(event_ts_raw) if event_ts_raw is not None else pd.Timestamp.now()
        exec_ts = pd.Timestamp(exec_ts_raw) if exec_ts_raw is not None else event_ts

        # Convert to datetime
        event_dt = event_ts.to_pydatetime() if hasattr(event_ts, "to_pydatetime") else datetime.now()
        exec_dt = exec_ts.to_pydatetime() if hasattr(exec_ts, "to_pydatetime") else event_dt

        # Determine file_date
        fd = file_dates.get(dissem_id)
        if fd is None:
            fd = event_ts.date() if hasattr(event_ts, "date") else date.today()

        # Compute changed economics by diffing with previous state
        changed: Dict[str, Any] = {}
        if prev_state is not None:
            for field_name in ECONOMICS_FIELDS:
                old_val = prev_state.get(field_name)
                new_val = snapshot.get(field_name)
                if new_val is not None and not _is_null_value(new_val):
                    if old_val is None or _is_null_value(old_val) or str(old_val) != str(new_val):
                        changed[field_name] = new_val

        orig_dissem = snapshot.get(original_dissemination_col)
        if isinstance(orig_dissem, float) and pd.isna(orig_dissem):
            orig_dissem = None
        elif orig_dissem is not None:
            orig_dissem = str(orig_dissem)

        events.append(LifecycleEvent(
            action_type=str(action),
            event_type=str(event_type) if event_type is not None else None,
            amendment_indicator=amendment,
            event_timestamp=event_dt,
            execution_timestamp=exec_dt,
            dissemination_id=dissem_id,
            original_dissemination_id=orig_dissem,
            file_date=fd,
            changed_economics=changed,
        ))

        prev_state = snapshot

    return build_summary(events)


def group_by_uti(
    df: pd.DataFrame,
    dissemination_col: str = "Dissemination Identifier",
    original_dissemination_col: str = "Original Dissemination Identifier",
) -> Dict[str, pd.DataFrame]:
    """Group raw SDR rows into lifecycle chains using Union-Find on dissemination IDs.

    Each row's ``dissemination_col`` is linked to its ``original_dissemination_col``.
    Connected components form UTI groups.  The root of each group (typically the
    NEWT's dissemination ID) is used as the group key.

    Returns:
        Mapping of root dissemination ID -> sub-DataFrame of all rows in that chain.
    """
    # --- Union-Find ---
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])  # path compression
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Build union-find from dissemination -> original links
    dissem_ids = df[dissemination_col].astype(str)
    orig_ids = df[original_dissemination_col]

    for dissem, orig in zip(dissem_ids, orig_ids):
        parent.setdefault(dissem, dissem)
        if pd.notna(orig):
            orig_str = str(orig)
            parent.setdefault(orig_str, orig_str)
            union(orig_str, dissem)

    # Assign each row to its root
    roots = dissem_ids.map(find)

    # Group by root
    groups: Dict[str, pd.DataFrame] = {}
    for root, sub_df in df.groupby(roots.values):
        groups[root] = sub_df

    return groups
