from __future__ import annotations

from typing import Dict, Optional

import networkx as nx
import pandas as pd


def _normalize_identifier(value: object) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized if normalized else None


def build_synthetic_uti_mapping(
    messages: pd.DataFrame,
    *,
    dissemination_col: str = "Dissemination Identifier",
    original_col: str = "Original Dissemination Identifier",
) -> Dict[str, str]:
    if dissemination_col not in messages.columns:
        raise ValueError(f"Missing dissemination column: {dissemination_col}")

    dissemination_ids = messages[dissemination_col].apply(_normalize_identifier)
    original_ids = messages[original_col].apply(_normalize_identifier) if original_col in messages.columns else pd.Series([None] * len(messages))

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

    mapping: Dict[str, str] = {}
    for component in nx.connected_components(graph):
        synthetic_id = min(component)
        for node in component:
            mapping[node] = synthetic_id

    return mapping


def assign_synthetic_uti(
    messages: pd.DataFrame,
    *,
    dissemination_col: str = "Dissemination Identifier",
    original_col: str = "Original Dissemination Identifier",
    synthetic_col: str = "Synthetic UTI",
) -> pd.DataFrame:
    if messages.empty:
        out = messages.copy()
        out[synthetic_col] = pd.Series(dtype="string")
        return out

    mapping = build_synthetic_uti_mapping(messages, dissemination_col=dissemination_col, original_col=original_col)
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
