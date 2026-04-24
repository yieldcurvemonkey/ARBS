from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set


# Action types treated as valuation updates: do NOT count toward the
# lifecycle event chain; they are periodic post-trade reports (§45.4(c))
# not state transitions. See finding B7.
VALUATION_ACTIONS: frozenset[str] = frozenset({"VALU", "MARU"})


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
    # H13: MODI rows that advance a scheduled notional/effective-date step
    # are NOT amendments — they are the swap performing its own schedule.
    is_schedule_step: bool = False


@dataclass
class LifecycleSummary:
    # Split chains: economic events drive aggregators; valuation events
    # are counted separately and don't inflate lc_n_events (B7).
    economic_chain: List[LifecycleEvent] = field(default_factory=list)
    valuation_chain: List[LifecycleEvent] = field(default_factory=list)
    # DEPRECATED: retained for back-compat; removed in Phase 6.
    chain: list[LifecycleEvent] = field(default_factory=list)

    was_corrected: bool = False
    was_economically_modified: bool = False
    was_null_filled: bool = False
    was_scheduled_amortization: bool = False
    was_errored: bool = False
    was_revived: bool = False
    is_terminated: bool = False

    original_execution_timestamp: Optional[datetime] = None
    latest_update_timestamp: Optional[datetime] = None
    correction_lag_seconds: int = 0
    arrived_in_later_file: bool = False

    fields_changed: Set[str] = field(default_factory=set)
    economics_changed: bool = False

    # State-machine validator output (H5, M9). One entry per violating
    # transition; consumers decide whether to drop or include (D4).
    state_machine_violations: List[str] = field(default_factory=list)


def validate_transition(
    prev_status: str,
    action: str,
    amendment: Optional[bool],
) -> Optional[str]:
    """Check a transition against Figure 1/2 of the Tech Spec.

    Returns the violation reason, or ``None`` if the transition is legal.
    Permissive per D4: the pipeline logs; it never silently coerces.
    """
    if prev_status == "ERRORED" and action == "MODI":
        return "MODI_ON_ERRORED_WITHOUT_REVI"
    if prev_status == "TERMINATED" and action == "MODI":
        return "MODI_ON_TERMINATED"
    if action == "MODI" and amendment is None:
        return "MODI_AMENDMENT_NONE"
    return None


def build_summary(chain: list[LifecycleEvent]) -> LifecycleSummary:
    """Build a LifecycleSummary from an ordered list of LifecycleEvents.

    Splits chain into economic_chain and valuation_chain (B7). Runs the
    state-machine validator per event (H5, M9). MODI events marked
    ``is_schedule_step`` are classified as scheduled amortization, not
    amendment or null-fill (H13).
    """
    from SDRUtils.core.lifecycle import ECONOMICS_FIELDS

    summary = LifecycleSummary(chain=list(chain))

    if not chain:
        return summary

    newt_event = None
    newt_file_date = None
    terminated = False
    errored = False

    for evt in chain:
        if evt.action_type in VALUATION_ACTIONS:
            summary.valuation_chain.append(evt)
            continue

        summary.economic_chain.append(evt)

        # Track the logical status before applying this event so the
        # validator can see "the previous state".
        if errored and not (evt.action_type == "REVI"):
            prev_status = "ERRORED"
        elif terminated:
            prev_status = "TERMINATED"
        else:
            prev_status = "ACTIVE"

        reason = validate_transition(prev_status, evt.action_type, evt.amendment_indicator)
        if reason is not None:
            summary.state_machine_violations.append(reason)

        if evt.action_type == "NEWT" and newt_event is None:
            newt_event = evt
            newt_file_date = evt.file_date
            summary.original_execution_timestamp = evt.execution_timestamp

        elif evt.action_type == "CORR":
            summary.was_corrected = True

        elif evt.action_type == "MODI":
            if evt.is_schedule_step:
                summary.was_scheduled_amortization = True
            elif evt.amendment_indicator is True:
                summary.was_economically_modified = True
            else:
                summary.was_null_filled = True

        elif evt.action_type == "EROR":
            summary.was_errored = True
            errored = True

        elif evt.action_type == "TERM":
            terminated = True

        elif evt.action_type == "REVI":
            summary.was_revived = True
            terminated = False
            errored = False

        if evt.changed_economics:
            for field_name in evt.changed_economics:
                summary.fields_changed.add(field_name)
                if field_name in ECONOMICS_FIELDS:
                    summary.economics_changed = True

        if newt_file_date is not None and evt.file_date > newt_file_date:
            summary.arrived_in_later_file = True

    summary.is_terminated = terminated

    if summary.original_execution_timestamp is None and summary.economic_chain:
        summary.original_execution_timestamp = summary.economic_chain[0].execution_timestamp
        newt_file_date = summary.economic_chain[0].file_date

    if summary.economic_chain:
        summary.latest_update_timestamp = summary.economic_chain[-1].event_timestamp
    elif chain:
        summary.latest_update_timestamp = chain[-1].event_timestamp

    if summary.original_execution_timestamp and len(summary.economic_chain) > 1:
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

    ``lc_n_events_economic`` counts economic transitions only (B7);
    ``lc_n_valuation_events`` counts VALU/MARU separately.
    ``lc_n_events`` is retained as a back-compat alias and is equal to
    ``lc_n_events_economic`` — removed in Phase 6.
    """
    fields_str = ",".join(sorted(summary.fields_changed)) if summary.fields_changed else ""
    violations = summary.state_machine_violations
    violation_reason = ",".join(violations) if violations else ""

    # Back-compat: LifecycleSummary constructed directly (tests, legacy
    # callers) may carry only `chain`. Derive the split on the fly.
    econ_chain = summary.economic_chain if summary.economic_chain else [
        e for e in summary.chain if getattr(e, "action_type", None) not in VALUATION_ACTIONS
    ]
    valu_chain = summary.valuation_chain if summary.valuation_chain else [
        e for e in summary.chain if getattr(e, "action_type", None) in VALUATION_ACTIONS
    ]

    return {
        "lc_n_events": len(econ_chain),
        "lc_n_events_economic": len(econ_chain),
        "lc_n_valuation_events": len(valu_chain),
        "lc_status": getattr(resolved, "status", "UNKNOWN"),
        "lc_is_corrected": summary.was_corrected,
        "lc_was_amended": summary.was_economically_modified,
        "lc_was_null_filled": summary.was_null_filled,
        "lc_was_scheduled_amortization": summary.was_scheduled_amortization,
        "lc_was_revived": summary.was_revived,
        "lc_has_economics_change": summary.economics_changed,
        "lc_correction_crossed_day": summary.arrived_in_later_file,
        "lc_correction_lag_seconds": summary.correction_lag_seconds,
        "lc_fields_changed": fields_str,
        "state_machine_violation": bool(violations),
        "violation_reason": violation_reason,
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

    # Back-compat: if the caller built a LifecycleSummary directly without
    # running build_summary(), economic_chain will be empty but chain has
    # the full event list. Fall back to chain in that case.
    econ_chain = summary.economic_chain if summary.economic_chain else [
        e for e in summary.chain if getattr(e, "action_type", None) not in VALUATION_ACTIONS
    ]
    valu_chain = summary.valuation_chain if summary.valuation_chain else [
        e for e in summary.chain if getattr(e, "action_type", None) in VALUATION_ACTIONS
    ]

    return {
        "xd_n_events": len(econ_chain),
        "xd_n_events_economic": len(econ_chain),
        "xd_n_valuation_events": len(valu_chain),
        "xd_status": status,
        "xd_inception_notional": inception_notional,
        "xd_current_notional": current_notional,
        "xd_notional_pct_remaining": pct_remaining,
        "xd_is_terminated": summary.is_terminated,
        "xd_has_partial_unwind": has_partial_unwind,
        "xd_was_corrected": summary.was_corrected,
        "xd_was_amended": summary.was_economically_modified,
        "xd_was_scheduled_amortization": summary.was_scheduled_amortization,
        "xd_fields_changed": fields_str,
        "xd_correction_lag_seconds": summary.correction_lag_seconds,
        "xd_n_days_spanned": n_days,
    }
