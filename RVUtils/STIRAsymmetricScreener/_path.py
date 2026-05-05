"""FOMC-dated path logic for the STIR Options Asymmetric Screener.

Spec §5: extract per-meeting marginal change, cumulative cuts/hikes by
horizon, terminal rate by horizon. Enumerate path scenarios. Compute
RND-implied probability of each scenario by integrating the rate-space
RND over the appropriate 25bp Fed-target bin.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord, payoff_zone_probability

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FOMCPath:
    """Cumulative + marginal Fed path implied by the OIS curve."""

    as_of: datetime.date
    meetings: Tuple[datetime.date, ...]
    meeting_labels: Tuple[str, ...]
    spot_target: float                          # decimal, e.g. 0.0425 for 425bp
    implied_meeting_rates: Tuple[float, ...]    # decimal per meeting
    cumulative_change_bp: Tuple[float, ...]     # bp vs spot
    marginal_change_bp: Tuple[float, ...]       # bp vs prior meeting

    def horizon_for_label(self, label: str) -> Optional[datetime.date]:
        for lab, m in zip(self.meeting_labels, self.meetings):
            if lab == label:
                return m
        return None


@dataclass(frozen=True)
class PathScenario:
    """A discrete cut/hike-count scenario for a given horizon."""

    name: str
    horizon: datetime.date
    cumulative_change_bp: float
    delta_from_implied_bp: float
    bin_lower_rate: float
    bin_upper_rate: float


# --- FOMC path extractor ------------------------------------------------------


def _default_forward_rate_fn(
    *,
    eff_date: datetime.date,
    mat_date: datetime.date,
    handle: Any,
) -> float:
    """Default forward-rate query against the OIS curve handle.

    Tries common method names in order: ``forward_rate``, ``meeting_implied_rate``,
    ``cumulative_rate``. Returns NaN if none are available.
    """
    eff_ts = pd.Timestamp(eff_date)
    mat_ts = pd.Timestamp(mat_date)
    for method in ("forward_rate", "meeting_implied_rate", "cumulative_rate"):
        fn = getattr(handle, method, None)
        if not callable(fn):
            continue
        try:
            return float(fn(eff_ts, mat_ts))
        except TypeError:
            try:
                return float(fn(start=eff_ts, end=mat_ts))
            except Exception:  # noqa: BLE001
                continue
        except Exception:  # noqa: BLE001
            continue
    return float("nan")


def extract_fomc_path(
    *,
    as_of: datetime.date,
    curve_handle: Any,
    fomc_schedule: pd.DataFrame,
    spot_target: float,
    forward_rate_fn: Optional[Callable[..., float]] = None,
) -> FOMCPath:
    """Build a ``FOMCPath`` from the OIS curve + FOMC schedule.

    The curve handle's per-meeting forward rate is queried via
    ``forward_rate_fn(eff_date, mat_date, handle)``; supply a custom
    function in tests to inject deterministic values.
    """
    if forward_rate_fn is None:
        forward_rate_fn = _default_forward_rate_fn

    if fomc_schedule is None or fomc_schedule.empty:
        return FOMCPath(
            as_of=as_of,
            meetings=(),
            meeting_labels=(),
            spot_target=spot_target,
            implied_meeting_rates=(),
            cumulative_change_bp=(),
            marginal_change_bp=(),
        )

    # Filter to forward meetings only
    sched = fomc_schedule.copy()
    sched["effective_date"] = pd.to_datetime(sched["effective_date"]).dt.date
    sched["maturity_date"] = pd.to_datetime(sched["maturity_date"]).dt.date
    sched = sched[sched["effective_date"] > as_of]
    sched = sched.sort_values("effective_date").reset_index(drop=True)

    meetings: List[datetime.date] = []
    labels: List[str] = []
    rates: List[float] = []
    for _, row in sched.iterrows():
        eff = row["effective_date"]
        mat = row["maturity_date"]
        try:
            r = float(
                forward_rate_fn(eff_date=eff, mat_date=mat, handle=curve_handle)
            )
        except Exception:  # noqa: BLE001
            r = float("nan")
        meetings.append(eff)
        labels.append(str(row.get("meeting_label", "")))
        rates.append(r)

    cumulative_bp: List[float] = []
    marginal_bp: List[float] = []
    prev = spot_target
    for r in rates:
        cumulative_bp.append((r - spot_target) * 10000.0)
        marginal_bp.append((r - prev) * 10000.0)
        prev = r

    return FOMCPath(
        as_of=as_of,
        meetings=tuple(meetings),
        meeting_labels=tuple(labels),
        spot_target=spot_target,
        implied_meeting_rates=tuple(rates),
        cumulative_change_bp=tuple(cumulative_bp),
        marginal_change_bp=tuple(marginal_bp),
    )


# --- Path scenario enumeration ----------------------------------------------


def enumerate_path_scenarios(
    *,
    fomc_path: FOMCPath,
    n_cuts_grid: Sequence[int] = (-4, -3, -2, -1, 0, 1, 2),
    bin_width_bp: float = 25.0,
) -> Tuple[PathScenario, ...]:
    """Enumerate cut/hike-count scenarios per horizon.

    For each (meeting horizon, n_cuts) pair, produce a ``PathScenario``
    with the corresponding 25bp rate bin centered on the implied target
    (``spot_target + n_cuts × 25bp``).
    """
    out: List[PathScenario] = []
    bin_half = bin_width_bp / 2.0
    for horizon, label, implied in zip(
        fomc_path.meetings,
        fomc_path.meeting_labels,
        fomc_path.implied_meeting_rates,
    ):
        for n in n_cuts_grid:
            change_bp = float(n) * bin_width_bp
            scen_rate = fomc_path.spot_target + change_bp / 10000.0
            implied_change_bp = (implied - fomc_path.spot_target) * 10000.0
            delta = change_bp - implied_change_bp
            out.append(
                PathScenario(
                    name=f"{n:+d}cuts_through_{label}",
                    horizon=horizon,
                    cumulative_change_bp=change_bp,
                    delta_from_implied_bp=delta,
                    bin_lower_rate=(scen_rate - bin_half / 10000.0) * 100.0,  # decimal → percent
                    bin_upper_rate=(scen_rate + bin_half / 10000.0) * 100.0,
                )
            )
    return tuple(out)


# --- Path-scenario probability under RND ------------------------------------


def path_scenario_probability_rnd(
    *,
    rnd_record: RNDRecord,
    scenario: PathScenario,
    convexity_adj_bp: float = 0.0,
) -> float:
    """Integrate the RND over ``scenario``'s rate bin.

    ``convexity_adj_bp`` shifts the bin labels in rate-space (spec §12.6).
    """
    lower = scenario.bin_lower_rate + convexity_adj_bp / 100.0
    upper = scenario.bin_upper_rate + convexity_adj_bp / 100.0
    return payoff_zone_probability(
        rnd_record, density="rnd", lower_rate=lower, upper_rate=upper
    )


def cumulative_path_mispricing_bp(
    *,
    fomc_path: FOMCPath,
    fair_path_bp: Sequence[float],
) -> float:
    """Largest |implied - fair| cumulative deviation across all horizons.

    ``fair_path_bp`` is per-meeting cumulative cuts/hikes (bp vs spot)
    matching ``fomc_path.meetings`` order. Pads/truncates as needed.
    """
    if not fomc_path.cumulative_change_bp:
        return 0.0
    n = min(len(fomc_path.cumulative_change_bp), len(fair_path_bp))
    if n == 0:
        return 0.0
    diffs = [
        abs(float(fomc_path.cumulative_change_bp[i]) - float(fair_path_bp[i]))
        for i in range(n)
    ]
    return float(max(diffs)) if diffs else 0.0
