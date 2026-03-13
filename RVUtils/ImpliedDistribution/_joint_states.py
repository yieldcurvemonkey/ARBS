"""Common-state FOMC path generation and contract projection utilities."""

from __future__ import annotations

import datetime
from typing import Dict, Sequence, Tuple

import numpy as np

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import get_fomc_meetings_list
from MDP.STIRFutures._sofr_option_contracts import quarterly_reference_window
from RVUtils.ImpliedDistribution._types import FOMCPathState, FOMCPathStateConfig


def _as_date(value: datetime.date | datetime.datetime) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    return value


def _move_label(move_bps: int, *, cut_size_bps: float) -> str:
    steps = int(round(abs(int(move_bps)) / float(cut_size_bps)))
    if steps == 0:
        return "flat"
    if move_bps < 0:
        return f"{steps} cut{'s' if steps != 1 else ''}"
    return f"{steps} hike{'s' if steps != 1 else ''}"


def _meeting_sort_key(index: int, n_meetings: int, profile: str) -> tuple[float, int]:
    if profile == "front":
        return float(index), index
    if profile == "back":
        return float(n_meetings - index - 1), index
    center = (n_meetings - 1) / 2.0
    return abs(index - center), index


def _allocate_monotone_steps(n_meetings: int, total_steps: int, profile: str) -> Tuple[int, ...]:
    if n_meetings <= 0:
        return tuple()
    order = [idx for _, idx in sorted((_meeting_sort_key(i, n_meetings, profile), i) for i in range(n_meetings))]
    steps = [0] * n_meetings
    for i in range(total_steps):
        steps[order[i % len(order)]] += 1
    return tuple(int(x) for x in steps)


def _levels_from_step_allocation(
    *,
    initial_rate: float,
    move_bps: int,
    cut_size_bps: float,
    step_allocation: Sequence[int],
) -> Tuple[float, ...]:
    direction = 1.0 if move_bps > 0 else -1.0
    step_rate = float(cut_size_bps) / 100.0
    cumulative = 0.0
    levels = []
    for step_count in step_allocation:
        cumulative += direction * step_rate * float(step_count)
        levels.append(float(initial_rate + cumulative))
    return tuple(levels)


def _state_key(state: FOMCPathState) -> Tuple[datetime.date, ...] | Tuple[str, ...]:
    rounded = tuple(f"{x:.8f}" for x in state.meeting_rates)
    return tuple(str(x) for x in rounded)


def _validate_explicit_states(
    states: Sequence[FOMCPathState],
    *,
    config_meeting_dates: Tuple[datetime.date, ...] | None,
) -> Tuple[Tuple[datetime.date, ...], Tuple[FOMCPathState, ...]]:
    if not states:
        raise ValueError("Explicit FOMCPathStateConfig.states must not be empty")
    ref_meetings = tuple(states[0].meeting_dates)
    for state in states:
        if tuple(state.meeting_dates) != ref_meetings:
            raise ValueError("All explicit FOMCPathState entries must share the same meeting_dates grid")
    if config_meeting_dates is not None and tuple(config_meeting_dates) != ref_meetings:
        raise ValueError("Explicit config.meeting_dates must match the meeting grid carried by explicit states")
    return ref_meetings, tuple(states)


def _resolve_meeting_dates(
    config: FOMCPathStateConfig,
    *,
    as_of: datetime.date,
    symbols: Sequence[str],
) -> Tuple[datetime.date, ...]:
    if config.meeting_dates is not None:
        return tuple(sorted(_as_date(x) for x in config.meeting_dates if _as_date(x) > as_of))

    horizon_end = max(quarterly_reference_window(str(sym).upper())[1] for sym in symbols)
    n_plus_years = max(int(config.n_plus_years), max(horizon_end.year - as_of.year, 0))
    meetings = [_as_date(x) for x in get_fomc_meetings_list(as_of=as_of, n_plus_years=n_plus_years)]
    return tuple(sorted(d for d in meetings if as_of < d < horizon_end))


def _build_templated_states(
    config: FOMCPathStateConfig,
    *,
    as_of: datetime.date,
    symbols: Sequence[str],
) -> Tuple[Tuple[datetime.date, ...], Tuple[FOMCPathState, ...]]:
    meeting_dates = _resolve_meeting_dates(config, as_of=as_of, symbols=symbols)
    states: list[FOMCPathState] = []
    seen: set[Tuple[str, ...]] = set()

    def _append_state(state: FOMCPathState) -> None:
        key = _state_key(state)
        if key in seen:
            return
        seen.add(key)
        states.append(state)

    _append_state(
        FOMCPathState(
            label=f"Flat ({config.current_rate:.2f}%)",
            initial_rate=float(config.current_rate),
            meeting_dates=meeting_dates,
            meeting_rates=tuple(float(config.current_rate) for _ in meeting_dates),
            metadata={"template": "flat", "terminal_move_bps": 0},
        )
    )

    if meeting_dates:
        for move_bps in tuple(int(x) for x in config.terminal_move_grid_bps):
            if move_bps == 0:
                continue
            steps = max(int(round(abs(move_bps) / float(config.cut_size_bps))), 1)
            move_label = _move_label(move_bps, cut_size_bps=config.cut_size_bps)

            for idx, meeting_date in enumerate(meeting_dates):
                step_allocation = [0] * len(meeting_dates)
                step_allocation[idx] = steps
                meeting_rates = _levels_from_step_allocation(
                    initial_rate=config.current_rate,
                    move_bps=move_bps,
                    cut_size_bps=config.cut_size_bps,
                    step_allocation=step_allocation,
                )
                _append_state(
                    FOMCPathState(
                        label=f"One-and-done {move_label} @ {meeting_date.isoformat()}",
                        initial_rate=float(config.current_rate),
                        meeting_dates=meeting_dates,
                        meeting_rates=meeting_rates,
                        metadata={
                            "template": "one_and_done",
                            "terminal_move_bps": move_bps,
                            "pivot_meeting": meeting_date.isoformat(),
                        },
                    )
                )

            for profile in ("front", "middle", "back"):
                step_allocation = _allocate_monotone_steps(len(meeting_dates), steps, profile)
                meeting_rates = _levels_from_step_allocation(
                    initial_rate=config.current_rate,
                    move_bps=move_bps,
                    cut_size_bps=config.cut_size_bps,
                    step_allocation=step_allocation,
                )
                _append_state(
                    FOMCPathState(
                        label=f"{profile.title()} {move_label}",
                        initial_rate=float(config.current_rate),
                        meeting_dates=meeting_dates,
                        meeting_rates=meeting_rates,
                        metadata={
                            "template": profile,
                            "terminal_move_bps": move_bps,
                        },
                    )
                )

    if config.max_states is not None:
        states = states[: int(config.max_states)]
    return meeting_dates, tuple(states)


def resolve_fomc_path_states(
    config: FOMCPathStateConfig,
    *,
    as_of: datetime.date,
    symbols: Sequence[str],
) -> Tuple[Tuple[datetime.date, ...], Tuple[FOMCPathState, ...]]:
    """Resolve the concrete meeting grid and states for a valuation date."""
    normalized_symbols = [str(sym).upper() for sym in symbols]
    if not normalized_symbols:
        raise ValueError("symbols must not be empty when resolving FOMC path states")
    if config.states is not None:
        return _validate_explicit_states(config.states, config_meeting_dates=config.meeting_dates)
    return _build_templated_states(config, as_of=as_of, symbols=normalized_symbols)


def average_rate_over_window(
    state: FOMCPathState,
    *,
    start: datetime.date,
    end: datetime.date,
) -> float:
    """Average the path's piecewise-constant rate across a contract reference window."""
    if end <= start:
        raise ValueError("Window end must be after start")
    meeting_dates = [d for d in state.meeting_dates if start < d < end]
    breakpoints = [start, *meeting_dates, end]
    total_days = max((end - start).days, 1)
    weighted = 0.0
    for left, right in zip(breakpoints[:-1], breakpoints[1:]):
        days = max((right - left).days, 0)
        if days == 0:
            continue
        weighted += float(days) * state.rate_on(left)
    return float(weighted / total_days)


def contract_rate_matrix(
    states: Sequence[FOMCPathState],
    *,
    symbols: Sequence[str],
) -> Tuple[np.ndarray, Dict[str, Tuple[datetime.date, datetime.date]]]:
    """Project each common state into each requested contract's average rate."""
    normalized_symbols = [str(sym).upper() for sym in symbols]
    windows = {sym: quarterly_reference_window(sym) for sym in normalized_symbols}
    matrix = np.zeros((len(states), len(normalized_symbols)), dtype=float)
    for state_idx, state in enumerate(states):
        for sym_idx, sym in enumerate(normalized_symbols):
            start, end = windows[sym]
            matrix[state_idx, sym_idx] = average_rate_over_window(state, start=start, end=end)
    return matrix, windows
