from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd


def _update_state(state: Optional[Dict[str, object]], row: Dict[str, object], *, overwrite: bool) -> Dict[str, object]:
    if state is None:
        state = {}

    for key, value in row.items():
        if overwrite or (value is not None and not (isinstance(value, float) and pd.isna(value)) and not pd.isna(value)):
            state[key] = value
    return state


def replay_lifecycle(
    messages: pd.DataFrame,
    *,
    action_col: str = "Action type",
    event_timestamp_col: str = "Event timestamp",
    sort: bool = True,
) -> Tuple[Optional[Dict[str, object]], List[Dict[str, object]]]:
    """
    Replay SDR lifecycle events to reconstruct the current state.

    Returns the latest state dict (or None if deleted) and a history of states after each event.
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
            state = row_data
            state["Active"] = True
        elif action == "MODI":
            state = _update_state(state, row_data, overwrite=False)
        elif action == "CORR":
            state = _update_state(state, row_data, overwrite=True)
        elif action == "TERM":
            state = _update_state(state, row_data, overwrite=False)
            state["Active"] = False
        elif action == "EROR":
            state = None
            history = []
            continue
        elif action in {"VALU", "MARU"}:
            state = _update_state(state, row_data, overwrite=False)
        else:
            state = _update_state(state, row_data, overwrite=False)

        if state is not None:
            history.append(state.copy())

    return state, history
