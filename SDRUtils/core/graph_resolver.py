from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import networkx as nx
import pandas as pd

logger = logging.getLogger(__name__)


def _normalize_identifier(value: object) -> Optional[str]:
    """Normalize an identifier value to a string or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized if normalized else None


def _select_semantic_anchor(
    component: set,
    id_to_action: Dict[str, str],
    id_to_timestamp: Dict[str, pd.Timestamp],
) -> str:
    """
    Select a semantic anchor for a connected component.

    Priority:
    1. First NEWT message by timestamp
    2. Earliest timestamp message (any action)
    3. Lexicographically smallest ID (fallback)

    Args:
        component: Set of dissemination IDs in the connected component
        id_to_action: Mapping from dissemination ID to action type
        id_to_timestamp: Mapping from dissemination ID to event timestamp

    Returns:
        The selected anchor ID for this component
    """
    # Filter to NEWT messages in this component
    newt_ids = [
        node for node in component
        if id_to_action.get(node) == "NEWT"
    ]

    if newt_ids:
        # Pick the earliest NEWT by timestamp
        newt_ids_with_ts = [
            (node, id_to_timestamp.get(node))
            for node in newt_ids
            if id_to_timestamp.get(node) is not None
        ]
        if newt_ids_with_ts:
            return min(newt_ids_with_ts, key=lambda x: x[1])[0]
        # If no timestamp info, fall back to min NEWT id
        return min(newt_ids)

    # No NEWT found - pick earliest timestamp message
    ids_with_ts = [
        (node, id_to_timestamp.get(node))
        for node in component
        if id_to_timestamp.get(node) is not None
    ]
    if ids_with_ts:
        return min(ids_with_ts, key=lambda x: x[1])[0]

    # Ultimate fallback - lexicographically smallest
    return min(component)


def build_synthetic_uti_mapping(
    messages: pd.DataFrame,
    *,
    dissemination_col: str = "Dissemination Identifier",
    original_col: str = "Original Dissemination Identifier",
    action_col: str = "Action type",
    event_timestamp_col: str = "Event timestamp",
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Build a mapping from dissemination IDs to synthetic UTIs.

    Uses graph-based clustering to group related messages into trade entities.
    The synthetic UTI is selected using semantic anchoring: prefer the first
    NEWT message by timestamp, then earliest timestamp, then lexicographic min.

    Args:
        messages: DataFrame containing SDR messages
        dissemination_col: Column name for dissemination identifiers
        original_col: Column name for original dissemination identifiers
        action_col: Column name for action type
        event_timestamp_col: Column name for event timestamp

    Returns:
        Tuple of:
        - mapping: Dict from dissemination ID to synthetic UTI
        - component_members: Dict from synthetic UTI to list of member IDs
    """
    if dissemination_col not in messages.columns:
        raise ValueError(f"Missing dissemination column: {dissemination_col}")

    dissemination_ids = messages[dissemination_col].apply(_normalize_identifier)
    original_ids = (
        messages[original_col].apply(_normalize_identifier)
        if original_col in messages.columns
        else pd.Series([None] * len(messages))
    )

    # Build lookup tables for semantic anchor selection
    id_to_action: Dict[str, str] = {}
    id_to_timestamp: Dict[str, pd.Timestamp] = {}

    for idx, dissemination_id in dissemination_ids.items():
        if dissemination_id:
            if action_col in messages.columns:
                id_to_action[dissemination_id] = messages.loc[idx, action_col]
            if event_timestamp_col in messages.columns:
                ts = messages.loc[idx, event_timestamp_col]
                if ts is not None and not pd.isna(ts):
                    id_to_timestamp[dissemination_id] = ts

    # Build graph of message relationships
    graph = nx.Graph()
    for dissemination_id in dissemination_ids:
        if dissemination_id:
            graph.add_node(dissemination_id)

    for dissemination_id, original_id in zip(dissemination_ids, original_ids):
        if not dissemination_id:
            continue
        if original_id:
            graph.add_edge(dissemination_id, original_id)
        else:
            graph.add_node(dissemination_id)

    # Build mapping using semantic anchor selection
    mapping: Dict[str, str] = {}
    component_members: Dict[str, List[str]] = {}

    for component in nx.connected_components(graph):
        synthetic_id = _select_semantic_anchor(
            component, id_to_action, id_to_timestamp
        )
        component_members[synthetic_id] = list(component)
        for node in component:
            mapping[node] = synthetic_id

    return mapping, component_members


def assign_synthetic_uti(
    messages: pd.DataFrame,
    *,
    dissemination_col: str = "Dissemination Identifier",
    original_col: str = "Original Dissemination Identifier",
    action_col: str = "Action type",
    event_timestamp_col: str = "Event timestamp",
    synthetic_col: str = "Synthetic UTI",
) -> pd.DataFrame:
    """
    Assign synthetic UTIs to SDR messages based on graph clustering.

    Groups related messages (NEWT, MODI, CORR, etc.) into trade entities
    and assigns a stable synthetic UTI to each message based on its component.

    Args:
        messages: DataFrame containing SDR messages
        dissemination_col: Column name for dissemination identifiers
        original_col: Column name for original dissemination identifiers
        action_col: Column name for action type (used for semantic anchor)
        event_timestamp_col: Column name for event timestamp (used for semantic anchor)
        synthetic_col: Column name to store the synthetic UTI

    Returns:
        DataFrame with synthetic UTI column added
    """
    if messages.empty:
        out = messages.copy()
        out[synthetic_col] = pd.Series(dtype="string")
        return out

    mapping, _ = build_synthetic_uti_mapping(
        messages,
        dissemination_col=dissemination_col,
        original_col=original_col,
        action_col=action_col,
        event_timestamp_col=event_timestamp_col,
    )
    dissemination_ids = messages[dissemination_col].apply(_normalize_identifier)

    results = []
    for idx, dissemination_id in dissemination_ids.items():
        if dissemination_id:
            results.append(mapping.get(dissemination_id, dissemination_id))
        else:
            results.append(f"orphan::{idx}")

    out = messages.copy()
    out[synthetic_col] = pd.Series(results, index=messages.index, dtype="string")
    return out
