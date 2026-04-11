from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional, Set


@dataclass(frozen=True)
class LifecycleEvent:
    action_type: str
    event_type: Optional[str]
    amendment_indicator: Optional[bool]
    event_timestamp: datetime
    execution_timestamp: datetime
    dissemination_id: str
    original_dissemination_id: Optional[str]
    file_date: date
    changed_economics: dict[str, Any] = field(default_factory=dict)


@dataclass
class LifecycleSummary:
    chain: list[LifecycleEvent] = field(default_factory=list)

    was_corrected: bool = False
    was_economically_modified: bool = False
    was_null_filled: bool = False
    was_errored: bool = False
    was_revived: bool = False
    is_terminated: bool = False

    original_execution_timestamp: Optional[datetime] = None
    latest_update_timestamp: Optional[datetime] = None
    correction_lag_seconds: int = 0
    arrived_in_later_file: bool = False

    fields_changed: Set[str] = field(default_factory=set)
    economics_changed: bool = False


def build_summary(chain: list[LifecycleEvent]) -> LifecycleSummary:
    """Build a LifecycleSummary from an ordered list of LifecycleEvents."""
    from SDRUtils.core.lifecycle import ECONOMICS_FIELDS

    summary = LifecycleSummary(chain=list(chain))

    if not chain:
        return summary

    newt_event = None
    newt_file_date = None
    terminated = False

    for evt in chain:
        if evt.action_type == "NEWT" and newt_event is None:
            newt_event = evt
            newt_file_date = evt.file_date
            summary.original_execution_timestamp = evt.execution_timestamp

        elif evt.action_type == "CORR":
            summary.was_corrected = True

        elif evt.action_type == "MODI":
            if evt.amendment_indicator is True:
                summary.was_economically_modified = True
            else:
                summary.was_null_filled = True

        elif evt.action_type == "EROR":
            summary.was_errored = True

        elif evt.action_type == "TERM":
            terminated = True

        elif evt.action_type == "REVI":
            summary.was_revived = True
            terminated = False

        # Track field-level changes
        if evt.changed_economics:
            for field_name in evt.changed_economics:
                summary.fields_changed.add(field_name)
                if field_name in ECONOMICS_FIELDS:
                    summary.economics_changed = True

        # Check if arrived in later file
        if newt_file_date is not None and evt.file_date > newt_file_date:
            summary.arrived_in_later_file = True

    summary.is_terminated = terminated

    # Set fallback if no NEWT found
    if summary.original_execution_timestamp is None and chain:
        summary.original_execution_timestamp = chain[0].execution_timestamp
        newt_file_date = chain[0].file_date

    # Compute latest update and lag
    summary.latest_update_timestamp = chain[-1].event_timestamp
    if summary.original_execution_timestamp and len(chain) > 1:
        delta = summary.latest_update_timestamp - summary.original_execution_timestamp
        summary.correction_lag_seconds = max(0, int(delta.total_seconds()))

    return summary
