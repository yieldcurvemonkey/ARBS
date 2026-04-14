from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Optional, Set


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


def flatten_lifecycle_summary(
    summary: LifecycleSummary,
    resolved: Any,
) -> Dict[str, Any]:
    """Flatten LifecycleSummary + ResolvedTrade status into a dict of lc_* columns.

    These columns are simple types (bool, int, str) suitable for
    parquet serialization and DataFrame merge.
    """
    fields_str = ",".join(sorted(summary.fields_changed)) if summary.fields_changed else ""

    return {
        "lc_n_events": len(summary.chain),
        "lc_status": getattr(resolved, "status", "UNKNOWN"),
        "lc_is_corrected": summary.was_corrected,
        "lc_was_amended": summary.was_economically_modified,
        "lc_was_null_filled": summary.was_null_filled,
        "lc_was_revived": summary.was_revived,
        "lc_has_economics_change": summary.economics_changed,
        "lc_correction_crossed_day": summary.arrived_in_later_file,
        "lc_correction_lag_seconds": summary.correction_lag_seconds,
        "lc_fields_changed": fields_str,
    }


def _safe_notional(state: Optional[Dict[str, Any]]) -> float:
    """Extract Notional amount-Leg 1 from state dict, coercing to float."""
    import math

    if state is None:
        return float("nan")
    raw = state.get("Notional amount-Leg 1")
    if raw is None:
        return float("nan")
    try:
        val = float(str(raw).replace(",", ""))
        return val
    except (ValueError, TypeError):
        return float("nan")


def flatten_cross_day_summary(
    summary: LifecycleSummary,
    resolved: Any,
) -> Dict[str, Any]:
    """Flatten LifecycleSummary + ResolvedTrade into xd_* columns for cross-day resolution.

    Same structure as flatten_lifecycle_summary but with additional notional
    tracking and partial-unwind detection for multi-day lifecycle chains.
    """
    import math

    fields_str = ",".join(sorted(summary.fields_changed)) if summary.fields_changed else ""

    # Notional extraction with numeric coercion
    inception_notional = _safe_notional(resolved.inception_state)
    current_notional = _safe_notional(resolved.current_state)

    # Pct remaining — guard division by zero/None
    if math.isnan(inception_notional) or inception_notional == 0:
        pct_remaining = float("nan")
    else:
        pct_remaining = current_notional / inception_notional

    # Partial unwind: notional decreased (regardless of terminated or active)
    has_partial_unwind = (
        not math.isnan(inception_notional)
        and not math.isnan(current_notional)
        and inception_notional > 0
        and current_notional < inception_notional
    )

    # Status: ERRORED > TERMINATED > PARTIAL_UNWIND > ACTIVE
    status = getattr(resolved, "status", "UNKNOWN")
    if status == "ACTIVE" and has_partial_unwind:
        status = "PARTIAL_UNWIND"

    # Days spanned: count distinct file_dates in chain
    n_days = len({evt.file_date for evt in summary.chain}) if summary.chain else 1

    return {
        "xd_n_events": len(summary.chain),
        "xd_status": status,
        "xd_inception_notional": inception_notional,
        "xd_current_notional": current_notional,
        "xd_notional_pct_remaining": pct_remaining,
        "xd_is_terminated": summary.is_terminated,
        "xd_has_partial_unwind": has_partial_unwind,
        "xd_was_corrected": summary.was_corrected,
        "xd_was_amended": summary.was_economically_modified,
        "xd_fields_changed": fields_str,
        "xd_correction_lag_seconds": summary.correction_lag_seconds,
        "xd_n_days_spanned": n_days,
    }
