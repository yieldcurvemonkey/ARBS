"""Day-weighted meeting-variance decomposition for SR3 reference periods."""

from __future__ import annotations

import datetime
import math
from typing import Dict, List, Tuple

from RVUtils.SR3ZQDistributionScreener._types import MeetingNode, MonthState


def meeting_nodes_from_states(
    states: Dict[str, MonthState],
    meetings: List[datetime.date],
) -> List[MeetingNode]:
    """Build per-meeting binary-tree nodes from per-month states.

    For each meeting date, look up its month state and compute:
        change_bp = (effr_end - effr_start) * 10000
        char = floor(change_bp / 25) (with sign-aware rounding)
        mantissa = remainder
        p_lower = 1 - mantissa, p_upper = mantissa
        var = binomial variance of the two-outcome distribution
    """
    out: List[MeetingNode] = []
    for meeting in meetings:
        label = f"{meeting:%b%y}".lower()
        if label not in states:
            continue
        s = states[label]
        if not s.has_meeting:
            continue
        change_bp = (s.effr_end - s.effr_start) * 10000.0
        if not math.isfinite(change_bp):
            continue
        n_25bp = change_bp / 25.0
        char = int(math.floor(n_25bp)) if change_bp >= 0 else int(math.ceil(n_25bp))
        mantissa = abs(n_25bp - char)
        p_lower = 1.0 - mantissa
        p_upper = mantissa
        if change_bp >= 0:
            outcome_lo_bp = char * 25.0
            outcome_hi_bp = (char + 1) * 25.0
        else:
            outcome_lo_bp = char * 25.0
            outcome_hi_bp = (char - 1) * 25.0
        mean_bp = p_lower * outcome_lo_bp + p_upper * outcome_hi_bp
        var_bp2 = (
            p_lower * (outcome_lo_bp - mean_bp) ** 2
            + p_upper * (outcome_hi_bp - mean_bp) ** 2
        )
        out.append(
            MeetingNode(
                label=label,
                date=meeting,
                prior_effr=s.effr_start,
                next_effr=s.effr_end,
                expected_change_bp=change_bp,
                char_25bp=char,
                mantissa=mantissa,
                p_lower=p_lower,
                p_upper=p_upper,
                variance_bp2=var_bp2,
            )
        )
    return out


def day_weighted_meeting_variance_bp2(
    nodes: List[MeetingNode],
    *,
    ref_start: datetime.date,
    ref_end: datetime.date,
) -> Tuple[float, List[Tuple[str, float, float, float]]]:
    """Sum meeting variances weighted by ((ref_end - meeting) / T)².

    A meeting on day t inside [ref_start, ref_end] contributes
    (T - t) / T to terminal compounded SOFR's mean and (((T - t) / T))²
    to its variance. Returns (total_var_bp2, per-meeting breakdown).
    """
    T = (ref_end - ref_start).days
    if T <= 0:
        return 0.0, []
    total = 0.0
    breakdown: List[Tuple[str, float, float, float]] = []
    for n in nodes:
        if n.date < ref_start or n.date > ref_end:
            continue
        days_after = (ref_end - n.date).days
        weight = days_after / T
        contribution = (weight ** 2) * n.variance_bp2
        total += contribution
        breakdown.append((n.label, weight, n.variance_bp2, contribution))
    return total, breakdown
