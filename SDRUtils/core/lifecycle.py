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

# Event type constants
DEFAULT_EVENT_TYPE = "TRAD"
NON_DISSEMINATED_EVENT_TYPES: Set[str] = {"CLRG", "COMP", "ALOC", "PTNG"}
VOLUME_EXCLUDED_EVENT_TYPES: Set[str] = {"NOVA", "CLRG", "COMP", "ALOC", "PTNG"}


@dataclass(frozen=True)
class EventPolicy:
    """Classification of dissemination and market impact for a lifecycle event."""

    is_disseminated: bool
    affects_market_state: bool
    counts_volume: bool


@dataclass
class LifecycleEvent:
    """Detailed lifecycle event record with dissemination and state snapshots."""

    action: str
    event_type: Optional[str]
    event_timestamp: Any
    dissemination_id: Optional[str]
    original_dissemination_id: Optional[str]
    amendment_indicator: Optional[bool]
    is_disseminated: bool
    affects_market_state: bool
    counts_volume: bool
    prior_uti: Optional[str] = None
    prior_usi: Optional[str] = None
    event_identifier: Optional[str] = None
    new_sdr_identifier: Optional[str] = None
    regulatory_state: Optional[Dict[str, Any]] = None
    market_state: Optional[Dict[str, Any]] = None


@dataclass
class TradeLineage:
    """Tracks linkage fields used for trade lineage across lifecycle events."""

    prior_uti: Set[str] = field(default_factory=set)
    prior_usi: Set[str] = field(default_factory=set)
    event_identifier: Set[str] = field(default_factory=set)
    clearing_swap_uti: Set[str] = field(default_factory=set)
    original_swap_uti: Set[str] = field(default_factory=set)
    new_sdr_identifier: Set[str] = field(default_factory=set)


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
        current_state: Final canonical state after all lifecycle updates (regulatory)
        market_state: Latest market-facing state (disseminated events only)
        market_view_state: Regulatory metadata with market-facing economics
        status: Current trade status (ACTIVE, TERMINATED, ERRORED)
        is_lifecycle_update: True if trade has MODI/CORR events (not standalone)
        quality_flags: List of data quality warnings
        history: List of regulatory state snapshots after each event
        market_history: List of market state snapshots after each event
        events: Detailed lifecycle events with dissemination classification
        lineage: Linkage fields captured across lifecycle events
    """

    synthetic_uti: str
    message_ids: List[str] = field(default_factory=list)
    actions: List[Tuple[str, Any]] = field(default_factory=list)
    inception_state: Optional[Dict[str, Any]] = None
    current_state: Optional[Dict[str, Any]] = None
    market_state: Optional[Dict[str, Any]] = None
    status: str = "UNKNOWN"  # ACTIVE, TERMINATED, ERRORED, UNKNOWN
    is_lifecycle_update: bool = False
    quality_flags: List[str] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    market_history: List[Optional[Dict[str, Any]]] = field(default_factory=list)
    events: List[LifecycleEvent] = field(default_factory=list)
    lineage: TradeLineage = field(default_factory=TradeLineage)

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
    def market_notional(self) -> Optional[float]:
        """Get notional from the market-facing state."""
        if not self.market_state:
            return None
        return self.market_state.get("Notional amount-Leg 1")

    @property
    def execution_state(self) -> Optional[Dict[str, Any]]:
        """Alias for the market-observed state at execution (NEWT)."""
        return self.inception_state

    @property
    def market_view_state(self) -> Optional[Dict[str, Any]]:
        """Market-facing economics overlaid onto regulatory metadata."""
        return _merge_market_economics(self.current_state, self.market_state)

    def get_state(self, view: str = "regulatory") -> Optional[Dict[str, Any]]:
        """
        Return a state view for downstream analytics.

        Supported views:
        - regulatory/current: corrected regulatory state (CORR/MODI updates applied)
        - market: last disseminated market state (CORR excluded)
        - execution/inception: state from the first NEWT
        - market_view: regulatory metadata with market-facing economics
        """
        return _select_state_view(
            regulatory_state=self.current_state,
            market_state=self.market_state,
            inception_state=self.inception_state,
            view=view,
        )

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
        if any(action == "NEWT" for action, _ in self.actions):
            return True
        return any(event.action == "NEWT" for event in self.events)

    @property
    def has_market_events(self) -> bool:
        """Check if any disseminated market events were observed."""
        return any(event.affects_market_state for event in self.events)

    @property
    def counts_for_volume(self) -> bool:
        """Check if any lifecycle event counts toward market volume."""
        return any(event.counts_volume for event in self.events)

    @property
    def volume_events(self) -> List[LifecycleEvent]:
        """Return events that should be counted as market volume."""
        return [event for event in self.events if event.counts_volume]


@dataclass
class LifecycleReplayResult:
    """Lifecycle replay output with regulatory and market-facing views."""

    regulatory_state: Optional[Dict[str, object]]
    regulatory_history: List[Dict[str, object]] = field(default_factory=list)
    market_state: Optional[Dict[str, object]] = None
    market_history: List[Optional[Dict[str, object]]] = field(default_factory=list)
    inception_state: Optional[Dict[str, object]] = None

    def __iter__(self):
        return iter((self.regulatory_state, self.regulatory_history))

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int):
        if index == 0:
            return self.regulatory_state
        if index == 1:
            return self.regulatory_history
        raise IndexError("LifecycleReplayResult supports indices 0 and 1 only.")

    @property
    def execution_state(self) -> Optional[Dict[str, object]]:
        """Alias for the market-observed state at execution (NEWT)."""
        return self.inception_state

    @property
    def market_view_state(self) -> Optional[Dict[str, object]]:
        """Market-facing economics overlaid onto regulatory metadata."""
        return _merge_market_economics(self.regulatory_state, self.market_state)

    def get_state(self, view: str = "regulatory") -> Optional[Dict[str, object]]:
        """
        Return a state view for downstream analytics.

        Supported views:
        - regulatory/current: corrected regulatory state (CORR/MODI updates applied)
        - market: last disseminated market state (CORR excluded)
        - execution/inception: state from the first NEWT
        - market_view: regulatory metadata with market-facing economics
        """
        return _select_state_view(
            regulatory_state=self.regulatory_state,
            market_state=self.market_state,
            inception_state=self.inception_state,
            view=view,
        )


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


def _merge_market_economics(
    regulatory_state: Optional[Dict[str, object]],
    market_state: Optional[Dict[str, object]],
) -> Optional[Dict[str, object]]:
    """Overlay market-facing economics onto regulatory metadata."""
    if regulatory_state is None and market_state is None:
        return None
    if regulatory_state is None:
        return market_state.copy() if market_state is not None else None
    if market_state is None:
        return regulatory_state.copy()

    merged = regulatory_state.copy()
    for field in ECONOMICS_FIELDS:
        if field in market_state and not _is_null_value(market_state.get(field)):
            merged[field] = market_state[field]
    return merged


def _select_state_view(
    *,
    regulatory_state: Optional[Dict[str, object]],
    market_state: Optional[Dict[str, object]],
    inception_state: Optional[Dict[str, object]],
    view: str,
) -> Optional[Dict[str, object]]:
    """Select a state view for analytics."""
    normalized = (view or "regulatory").strip().lower()
    if normalized in {"regulatory", "current"}:
        return regulatory_state
    if normalized == "market":
        return market_state
    if normalized in {"execution", "inception"}:
        return inception_state
    if normalized in {"market_view", "market_economics"}:
        return _merge_market_economics(regulatory_state, market_state)
    raise ValueError(f"Unknown lifecycle state view: {view}")


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


def _normalize_action(value: Any) -> str:
    """Normalize an action type to uppercase string (or empty)."""
    if _is_null_value(value):
        return ""
    return str(value).strip().upper()


def _normalize_event_type(value: Any, *, default: Optional[str] = None) -> Optional[str]:
    """Normalize an event type to uppercase string (or default)."""
    if _is_null_value(value):
        return default
    normalized = str(value).strip().upper()
    return normalized if normalized else default


def _parse_bool(value: Any) -> Optional[bool]:
    """Parse boolean-like values from SDR fields."""
    if isinstance(value, bool):
        return value
    if _is_null_value(value):
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"TRUE", "T", "Y", "YES", "1"}:
            return True
        if normalized in {"FALSE", "F", "N", "NO", "0"}:
            return False
    return None


def _event_policy(action: str, event_type: Optional[str], is_amendment: Optional[bool]) -> EventPolicy:
    """Determine dissemination, market impact, and volume eligibility."""
    normalized_action = action or ""
    normalized_event = event_type or DEFAULT_EVENT_TYPE

    if normalized_action in {"CORR", "EROR", "REVI"}:
        is_disseminated = True
    elif normalized_action in {"VALU", "MARU", "PRTO", "UPDT"}:
        is_disseminated = False
    elif normalized_action == "NEWT":
        is_disseminated = normalized_event not in NON_DISSEMINATED_EVENT_TYPES
    elif normalized_action == "MODI":
        if normalized_event in NON_DISSEMINATED_EVENT_TYPES or normalized_event == "EXER":
            is_disseminated = False
        else:
            is_disseminated = bool(is_amendment)
    elif normalized_action == "TERM":
        is_disseminated = normalized_event not in NON_DISSEMINATED_EVENT_TYPES
    else:
        is_disseminated = False

    affects_market_state = is_disseminated and normalized_action != "CORR"

    counts_volume = False
    if normalized_action == "NEWT":
        counts_volume = normalized_event not in VOLUME_EXCLUDED_EVENT_TYPES

    return EventPolicy(
        is_disseminated=is_disseminated,
        affects_market_state=affects_market_state,
        counts_volume=counts_volume,
    )


def _should_overwrite_economics(
    action: str,
    event_type: Optional[str],
    is_amendment: Optional[bool],
) -> bool:
    """Determine if economics fields should be overwritten for a MODI event."""
    if action != "MODI":
        return False
    if is_amendment is True:
        return True
    if event_type == "EXER":
        return True
    return False


def _add_lineage_value(target: Set[str], value: Any) -> None:
    """Add a non-null lineage value to a set, handling list-like values."""
    if _is_null_value(value):
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _add_lineage_value(target, item)
        return
    normalized = str(value).strip()
    if normalized:
        target.add(normalized)


def _collect_lineage(
    lineage: TradeLineage,
    row: Dict[str, Any],
    *,
    prior_uti_col: str,
    prior_usi_col: str,
    event_identifier_col: str,
    clearing_swap_uti_col: str,
    original_swap_uti_col: str,
    new_sdr_identifier_col: str,
) -> None:
    """Collect lineage fields from a row into the lineage object."""
    _add_lineage_value(lineage.prior_uti, row.get(prior_uti_col))
    _add_lineage_value(lineage.prior_usi, row.get(prior_usi_col))
    _add_lineage_value(lineage.event_identifier, row.get(event_identifier_col))
    _add_lineage_value(lineage.clearing_swap_uti, row.get(clearing_swap_uti_col))
    _add_lineage_value(lineage.original_swap_uti, row.get(original_swap_uti_col))
    _add_lineage_value(lineage.new_sdr_identifier, row.get(new_sdr_identifier_col))


def replay_lifecycle(
    messages: pd.DataFrame,
    *,
    action_col: str = "Action type",
    event_type_col: str = "Event type",
    event_timestamp_col: str = "Event timestamp",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    sort: bool = True,
) -> LifecycleReplayResult:
    """
    Replay SDR lifecycle events to reconstruct regulatory and market-facing states.

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
        event_type_col: Column name for event type
        event_timestamp_col: Column name for event timestamp
        amendment_indicator_col: Column name for amendment indicator
        dissemination_col: Column name for dissemination identifier
        sort: Whether to sort messages by timestamp

    Returns:
        LifecycleReplayResult with:
        - regulatory_state: final corrected regulatory state (or None if errored)
        - regulatory_history: state snapshots after each event
        - market_state: last disseminated market state (CORR excluded)
        - market_history: market-facing snapshots per event
        - inception_state: state from the first NEWT (execution snapshot)

    Note:
        LifecycleReplayResult supports tuple-unpacking as (regulatory_state, regulatory_history).
    """
    if messages.empty:
        return LifecycleReplayResult(
            regulatory_state=None,
            regulatory_history=[],
            market_state=None,
            market_history=[],
            inception_state=None,
        )

    if sort and event_timestamp_col in messages.columns:
        messages = messages.sort_values(event_timestamp_col, kind="mergesort")

    state: Optional[Dict[str, object]] = None
    market_state: Optional[Dict[str, object]] = None
    inception_state: Optional[Dict[str, object]] = None
    last_valid_state: Optional[Dict[str, object]] = None
    last_valid_market_state: Optional[Dict[str, object]] = None
    history: List[Dict[str, object]] = []
    market_history: List[Optional[Dict[str, object]]] = []

    for _, row in messages.iterrows():
        action = _normalize_action(row.get(action_col))
        event_type = _normalize_event_type(
            row.get(event_type_col),
            default=DEFAULT_EVENT_TYPE if action in {"NEWT", "MODI", "TERM"} else None,
        )
        is_amendment = _parse_bool(row.get(amendment_indicator_col))
        policy = _event_policy(action, event_type, is_amendment)
        row_data = row.to_dict()

        if action == "NEWT":
            state = row_data.copy()
            state["Active"] = True
            # Store inception state marker for volume calculation
            state["_is_inception"] = True
            if inception_state is None:
                inception_state = state.copy()

            if policy.affects_market_state:
                market_state = row_data.copy()
                market_state["Active"] = True

        elif action == "MODI":
            overwrite_economics = _should_overwrite_economics(action, event_type, is_amendment)
            if overwrite_economics:
                state = _update_state(state, row_data, overwrite=True, economics_only=True)
                state = _update_state(state, row_data, overwrite=False)
            else:
                state = _update_state(state, row_data, overwrite=False)

            if policy.affects_market_state:
                if overwrite_economics:
                    market_state = _update_state(market_state, row_data, overwrite=True, economics_only=True)
                    market_state = _update_state(market_state, row_data, overwrite=False)
                else:
                    market_state = _update_state(market_state, row_data, overwrite=False)

        elif action == "CORR":
            # Correction overwrites all fields
            state = _update_state(state, row_data, overwrite=True)

        elif action == "TERM":
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = False

            if policy.affects_market_state:
                market_state = _update_state(market_state, row_data, overwrite=False)
                if market_state:
                    market_state["Active"] = False

        elif action == "EROR":
            # Error action invalidates the trade entirely
            if state is not None:
                last_valid_state = state.copy()
            if market_state is not None:
                last_valid_market_state = market_state.copy()
            state = None
            history = []
            market_history = []
            if policy.affects_market_state:
                market_state = None
            continue

        elif action in {"VALU", "MARU", "UPDT", "PRTO"}:
            # Valuation/margin updates - fill nulls only
            state = _update_state(state, row_data, overwrite=False)

        elif action == "REVI":
            # Revival - restore a previously errored/terminated trade
            if state is None and last_valid_state is not None:
                state = last_valid_state.copy()
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = True

            if policy.affects_market_state:
                if market_state is None and last_valid_market_state is not None:
                    market_state = last_valid_market_state.copy()
                market_state = _update_state(market_state, row_data, overwrite=False)
                if market_state:
                    market_state["Active"] = True

        else:
            # Unknown action - treat as update (fill nulls)
            logger.warning(f"Unknown action type: {action}")
            state = _update_state(state, row_data, overwrite=False)
            if policy.affects_market_state:
                market_state = _update_state(market_state, row_data, overwrite=False)

        if state is not None:
            history.append(state.copy())
        market_history.append(market_state.copy() if market_state is not None else None)

    return LifecycleReplayResult(
        regulatory_state=state,
        regulatory_history=history,
        market_state=market_state,
        market_history=market_history,
        inception_state=inception_state,
    )


def replay_lifecycle_full(
    messages: pd.DataFrame,
    synthetic_uti: str,
    *,
    action_col: str = "Action type",
    event_type_col: str = "Event type",
    event_timestamp_col: str = "Event timestamp",
    amendment_indicator_col: str = "Amendment indicator",
    dissemination_col: str = "Dissemination Identifier",
    original_dissemination_col: str = "Original Dissemination Identifier",
    prior_uti_col: str = "Prior UTI",
    prior_usi_col: str = "Prior USI",
    event_identifier_col: str = "Event identifier",
    clearing_swap_uti_col: str = "Clearing swap UTIs",
    original_swap_uti_col: str = "Original swap UTI",
    new_sdr_identifier_col: str = "New SDR identifier",
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
        event_type_col: Column name for event type
        event_timestamp_col: Column name for event timestamp
        amendment_indicator_col: Column name for amendment indicator
        dissemination_col: Column name for dissemination identifier
        original_dissemination_col: Column name for original dissemination identifier
        prior_uti_col: Column name for prior UTI (lineage)
        prior_usi_col: Column name for prior USI (lineage)
        event_identifier_col: Column name for event identifier (lineage)
        clearing_swap_uti_col: Column name for clearing swap UTIs (lineage)
        original_swap_uti_col: Column name for original swap UTI (lineage)
        new_sdr_identifier_col: Column name for new SDR identifier (lineage)
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
    market_state: Optional[Dict[str, object]] = None
    inception_state: Optional[Dict[str, object]] = None
    last_valid_state: Optional[Dict[str, object]] = None
    last_valid_market_state: Optional[Dict[str, object]] = None

    action_types: Set[str] = set()

    for _, row in messages.iterrows():
        row_data = row.to_dict()
        dissem_id = row.get(dissemination_col)
        if dissem_id and not pd.isna(dissem_id):
            resolved.message_ids.append(str(dissem_id))

        action = _normalize_action(row.get(action_col))
        event_type = _normalize_event_type(
            row.get(event_type_col),
            default=DEFAULT_EVENT_TYPE if action in {"NEWT", "MODI", "TERM"} else None,
        )
        timestamp = row.get(event_timestamp_col)
        is_amendment = _parse_bool(row.get(amendment_indicator_col))
        policy = _event_policy(action, event_type, is_amendment)

        resolved.actions.append((action, timestamp))
        action_types.add(action)

        _collect_lineage(
            resolved.lineage,
            row_data,
            prior_uti_col=prior_uti_col,
            prior_usi_col=prior_usi_col,
            event_identifier_col=event_identifier_col,
            clearing_swap_uti_col=clearing_swap_uti_col,
            original_swap_uti_col=original_swap_uti_col,
            new_sdr_identifier_col=new_sdr_identifier_col,
        )

        if action == "NEWT":
            state = row_data.copy()
            state["Active"] = True
            if inception_state is None:
                inception_state = state.copy()

            if policy.affects_market_state:
                market_state = row_data.copy()
                market_state["Active"] = True

        elif action == "MODI":
            overwrite_economics = _should_overwrite_economics(action, event_type, is_amendment)
            if overwrite_economics:
                state = _update_state(state, row_data, overwrite=True, economics_only=True)
                state = _update_state(state, row_data, overwrite=False)
            else:
                state = _update_state(state, row_data, overwrite=False)

            if policy.affects_market_state:
                if overwrite_economics:
                    market_state = _update_state(market_state, row_data, overwrite=True, economics_only=True)
                    market_state = _update_state(market_state, row_data, overwrite=False)
                else:
                    market_state = _update_state(market_state, row_data, overwrite=False)

        elif action == "CORR":
            state = _update_state(state, row_data, overwrite=True)

        elif action == "TERM":
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = False

            if policy.affects_market_state:
                market_state = _update_state(market_state, row_data, overwrite=False)
                if market_state:
                    market_state["Active"] = False

        elif action == "EROR":
            if state is not None:
                last_valid_state = state.copy()
            if market_state is not None:
                last_valid_market_state = market_state.copy()
            state = None
            if policy.affects_market_state:
                market_state = None

        elif action in {"VALU", "MARU", "UPDT", "PRTO"}:
            state = _update_state(state, row_data, overwrite=False)

        elif action == "REVI":
            if state is None and last_valid_state is not None:
                state = last_valid_state.copy()
            state = _update_state(state, row_data, overwrite=False)
            if state:
                state["Active"] = True

            if policy.affects_market_state:
                if market_state is None and last_valid_market_state is not None:
                    market_state = last_valid_market_state.copy()
                market_state = _update_state(market_state, row_data, overwrite=False)
                if market_state:
                    market_state["Active"] = True

        else:
            logger.warning(f"Unknown action type: {action}")
            state = _update_state(state, row_data, overwrite=False)
            if policy.affects_market_state:
                market_state = _update_state(market_state, row_data, overwrite=False)

        if state is not None:
            resolved.history.append(state.copy())

        resolved.market_history.append(market_state.copy() if market_state is not None else None)

        resolved.events.append(
            LifecycleEvent(
                action=action,
                event_type=event_type,
                event_timestamp=timestamp,
                dissemination_id=str(dissem_id) if dissem_id and not pd.isna(dissem_id) else None,
                original_dissemination_id=(
                    str(row.get(original_dissemination_col))
                    if row.get(original_dissemination_col) and not pd.isna(row.get(original_dissemination_col))
                    else None
                ),
                amendment_indicator=is_amendment,
                is_disseminated=policy.is_disseminated,
                affects_market_state=policy.affects_market_state,
                counts_volume=policy.counts_volume,
                prior_uti=row.get(prior_uti_col),
                prior_usi=row.get(prior_usi_col),
                event_identifier=row.get(event_identifier_col),
                new_sdr_identifier=row.get(new_sdr_identifier_col),
                regulatory_state=state.copy() if state is not None else None,
                market_state=market_state.copy() if market_state is not None else None,
            )
        )

    resolved.inception_state = inception_state
    resolved.current_state = state
    resolved.market_state = market_state

    resolved.is_lifecycle_update = bool(action_types & {"MODI", "CORR", "TERM"})
    if "NEWT" not in action_types:
        resolved.quality_flags.append("MISSING_NEWT")

    if state is None:
        resolved.status = "ERRORED"
    elif state.get("Active") is False:
        resolved.status = "TERMINATED"
    else:
        resolved.status = "ACTIVE"

    return resolved
