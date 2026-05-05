"""Reusable library for SR3 RND vs ZQ FedWatch tree distribution comparison.

Extracted from `_sr3_zq_distribution_prototype_20260504.py` so the same
functions can be applied to multiple historical dates for backfill /
regime sensitivity analysis.

Public API:
    - ``build_fedwatch_tree(zq_prices, fomc_schedule, months_range)``
    - ``meeting_nodes_from_states(states, meetings)``
    - ``day_weighted_meeting_variance_bp2(nodes, ref_start, ref_end)``
    - ``compute_distribution_signals(as_of, sr3_contract, ref_start, ref_end,
        zq_months_range)`` — top-level entry point returning a SignalRecord
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
from SDRUtils.analytics.fomc import load_fomc_schedule


# --- Tree state types -------------------------------------------------------


@dataclass(frozen=True)
class MonthState:
    label: str
    contract: str
    avg_effr: float
    has_meeting: bool
    meeting_date: Optional[datetime.date]
    days_in_month: int
    days_before_meeting: int
    days_after_meeting: int
    effr_start: float = float("nan")
    effr_end: float = float("nan")


@dataclass(frozen=True)
class MeetingNode:
    label: str
    date: datetime.date
    prior_effr: float
    next_effr: float
    expected_change_bp: float
    char_25bp: int
    mantissa: float
    p_lower: float
    p_upper: float
    variance_bp2: float


# --- Calendar helpers -------------------------------------------------------


def months_in_range(start: datetime.date, end: datetime.date) -> List[Tuple[int, int]]:
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def contract_for_month(year: int, month: int) -> str:
    code = "FGHJKMNQUVXZ"[month - 1]
    return f"ZQ{code}{year % 100:02d}"


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (datetime.date(year + 1, 1, 1) - datetime.date(year, 12, 1)).days
    return (datetime.date(year, month + 1, 1) - datetime.date(year, month, 1)).days


# --- FedWatch tree builder --------------------------------------------------


def build_fedwatch_tree(
    *,
    zq_prices: Dict[str, float],
    fomc_schedule: pd.DataFrame,
    months_range: Tuple[Tuple[int, int], Tuple[int, int]],
) -> Dict[str, MonthState]:
    """Build per-month start/end EFFR per CME FedWatch methodology."""
    fomc_lookup: Dict[Tuple[int, int], datetime.date] = {}
    for _, row in fomc_schedule.iterrows():
        eff = row["effective_date"]
        if isinstance(eff, pd.Timestamp):
            eff = eff.date()
        fomc_lookup[(eff.year, eff.month)] = eff

    (y_lo, m_lo), (y_hi, m_hi) = months_range
    months = months_in_range(datetime.date(y_lo, m_lo, 1), datetime.date(y_hi, m_hi, 1))

    states: Dict[Tuple[int, int], MonthState] = {}
    for y, m in months:
        contract = contract_for_month(y, m)
        avg_pct = 100.0 - zq_prices.get(contract, float("nan"))
        avg = avg_pct / 100.0
        meeting = fomc_lookup.get((y, m))
        days_total = days_in_month(y, m)
        if meeting is None:
            days_before = days_after = 0
        else:
            days_before = (meeting - datetime.date(y, m, 1)).days
            days_after = days_total - days_before
        states[(y, m)] = MonthState(
            label=f"{datetime.date(y, m, 1):%b%y}".lower(),
            contract=contract,
            avg_effr=avg,
            has_meeting=meeting is not None,
            meeting_date=meeting,
            days_in_month=days_total,
            days_before_meeting=days_before,
            days_after_meeting=days_after,
        )

    # Find first non-FOMC anchor month
    anchor_idx = None
    for i, key in enumerate(months):
        if not states[key].has_meeting:
            anchor_idx = i
            break
    if anchor_idx is None:
        raise ValueError("No anchor non-FOMC month inside range")

    populated: Dict[Tuple[int, int], MonthState] = {}
    populated_keys: set = set()

    def _populate_anchor(idx: int):
        anchor_month = months[idx]
        anchor = states[anchor_month]
        populated[anchor_month] = MonthState(
            **{**anchor.__dict__, "effr_start": anchor.avg_effr, "effr_end": anchor.avg_effr}
        )
        populated_keys.add(anchor_month)

    def _walk_back(start_idx: int):
        for j in range(start_idx - 1, -1, -1):
            if months[j] in populated_keys:
                break
            cur = states[months[j]]
            next_state = populated[months[j + 1]]
            end = next_state.effr_start
            if cur.has_meeting:
                n = cur.days_before_meeting
                mm = cur.days_after_meeting
                if (n + mm) <= 0 or n == 0:
                    start = cur.avg_effr
                else:
                    start = (cur.avg_effr - (mm / (n + mm)) * end) / (n / (n + mm))
            else:
                start = cur.avg_effr
            populated[months[j]] = MonthState(
                **{**cur.__dict__, "effr_start": start, "effr_end": end}
            )
            populated_keys.add(months[j])

    def _walk_forward_one(idx: int):
        if idx + 1 >= len(months):
            return
        nm = months[idx + 1]
        if nm in populated_keys:
            return
        cur = states[nm]
        anchor = populated[months[idx]]
        start = anchor.avg_effr
        if cur.has_meeting:
            n = cur.days_before_meeting
            mm = cur.days_after_meeting
            if (n + mm) <= 0 or mm == 0:
                end = cur.avg_effr
            else:
                end = (cur.avg_effr - (n / (n + mm)) * start) / (mm / (n + mm))
        else:
            end = cur.avg_effr
        populated[nm] = MonthState(
            **{**cur.__dict__, "effr_start": start, "effr_end": end}
        )
        populated_keys.add(nm)

    _populate_anchor(anchor_idx)
    _walk_back(anchor_idx)
    _walk_forward_one(anchor_idx)

    while True:
        next_anchor = None
        for i in range(anchor_idx + 1, len(months)):
            if not states[months[i]].has_meeting and months[i] not in populated_keys:
                next_anchor = i
                break
        if next_anchor is None:
            break
        _populate_anchor(next_anchor)
        _walk_back(next_anchor)
        _walk_forward_one(next_anchor)
        anchor_idx = next_anchor

    return {s.label: s for s in populated.values()}


def meeting_nodes_from_states(
    states: Dict[str, MonthState], meetings: List[datetime.date]
) -> List[MeetingNode]:
    out = []
    for meeting in meetings:
        label = f"{meeting:%b%y}".lower()
        if label not in states:
            continue
        s = states[label]
        if not s.has_meeting:
            continue
        change_bp = (s.effr_end - s.effr_start) * 10000.0
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
    T = (ref_end - ref_start).days
    if T <= 0:
        return 0.0, []
    total = 0.0
    breakdown = []
    for n in nodes:
        if n.date < ref_start or n.date > ref_end:
            continue
        days_after = (ref_end - n.date).days
        weight = days_after / T
        contribution_bp2 = (weight ** 2) * n.variance_bp2
        total += contribution_bp2
        breakdown.append((n.label, weight, n.variance_bp2, contribution_bp2))
    return total, breakdown


# --- Top-level signal record ------------------------------------------------


@dataclass(frozen=True)
class SignalRecord:
    as_of: datetime.date
    sr3_contract: str
    sr3_dte: int
    ref_start: datetime.date
    ref_end: datetime.date
    forward_price: float
    forward_rate: float

    # ZQ tree
    n_meetings_in_period: int
    expected_changes_bp: Tuple[float, ...]
    fedwatch_probabilities: Tuple[Tuple[float, float], ...]  # (p_lower, p_upper) per meeting
    zq_day_weighted_var_bp2: float

    # SR3 RND
    sr3_total_var_bp2: float
    sr3_skew: float
    sr3_kurt: float
    sr3_stability_flag: str

    # Variance decomposition
    intermeeting_drift_var_bp2: float
    basis_var_bp2: float
    explained_var_bp2: float
    residual_var_bp2: float
    residual_to_explained_ratio: float

    # Tail mass
    tail_lower_50: float
    tail_lower_75: float
    tail_lower_100: float
    tail_upper_50: float
    tail_upper_75: float
    tail_upper_100: float

    warnings: Tuple[str, ...] = ()


def compute_distribution_signals(
    *,
    as_of: datetime.date,
    sr3_contract: str,
    ref_start: datetime.date,
    ref_end: datetime.date,
    zq_months_range: Tuple[Tuple[int, int], Tuple[int, int]],
    intermeeting_daily_vol_bp: float = 0.3,
) -> SignalRecord:
    """Run the full distribution-comparison pipeline on a single ``as_of``.

    Returns a SignalRecord with all four signal residuals + diagnostics.
    """
    warnings: List[str] = []
    ref_days = (ref_end - ref_start).days

    # 1. ZQ prices
    fut_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    months = months_in_range(
        datetime.date(zq_months_range[0][0], zq_months_range[0][1], 1),
        datetime.date(zq_months_range[1][0], zq_months_range[1][1], 1),
    )
    zq_symbols = [contract_for_month(y, m) for y, m in months]
    snap = fut_mdp.get_data({"symbols": zq_symbols, "timestamp": as_of})
    zq_prices: Dict[str, float] = {}
    for sym in zq_symbols:
        pricers = snap.get(sym) or []
        if pricers:
            p = pricers[0]
            price = getattr(p, "_price", None) or getattr(p, "price", None)
            if price is not None:
                try:
                    zq_prices[sym] = float(price)
                except (TypeError, ValueError):
                    pass

    if not zq_prices:
        raise RuntimeError(f"No ZQ prices for {as_of}")

    # 2. FOMC schedule
    fomc_full = load_fomc_schedule("USD-SOFR-1D")
    fomc_full["effective_date"] = pd.to_datetime(fomc_full["effective_date"]).dt.date
    period_lo = datetime.date(zq_months_range[0][0], zq_months_range[0][1], 1)
    period_hi = datetime.date(zq_months_range[1][0], zq_months_range[1][1], 28)
    fomc_in_range = fomc_full[
        (fomc_full["effective_date"] >= period_lo) & (fomc_full["effective_date"] <= period_hi)
    ]

    # 3. Build tree
    states = build_fedwatch_tree(
        zq_prices=zq_prices,
        fomc_schedule=fomc_in_range,
        months_range=zq_months_range,
    )

    # 4. Meeting nodes inside SR3 reference period
    meetings_in_period = sorted(
        m for m in fomc_in_range["effective_date"]
        if ref_start <= m <= ref_end
    )
    nodes = meeting_nodes_from_states(states, meetings_in_period)

    # 5. Day-weighted variance
    zq_var_bp2, _ = day_weighted_meeting_variance_bp2(nodes, ref_start=ref_start, ref_end=ref_end)

    # 6. SR3 smile + RND
    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    smile = opt_mdp.fetch_sabr_smile(
        {"symbol": sr3_contract, "as_of": as_of, "strike_offsets_bps": "listed"}
    )
    rnd = extract_per_expiry_rnd(
        smile=smile, leg_market={}, config=ScreenerConfig(), as_of=as_of
    )
    sr3_total_var_bp2 = (rnd.std_rate * 100.0) ** 2
    fwd_rate_pct = 100.0 - smile.params.forward_price

    # 7. Variance decomposition
    intermeeting_drift_var_bp2 = (intermeeting_daily_vol_bp ** 2) * ref_days
    basis_var_bp2 = 0.0  # constant basis assumption (refine in future iterations)
    explained = zq_var_bp2 + basis_var_bp2 + intermeeting_drift_var_bp2
    residual = sr3_total_var_bp2 - explained
    ratio = residual / explained if explained > 0 else float("nan")

    # 8. Tail mass
    grid = rnd.strike_grid_rate
    pdf = rnd.density_pdf

    def _tail_below(threshold_pct: float) -> float:
        mask = grid <= threshold_pct
        return float(trapezoid(pdf[mask], grid[mask])) if mask.any() else 0.0

    def _tail_above(threshold_pct: float) -> float:
        mask = grid >= threshold_pct
        return float(trapezoid(pdf[mask], grid[mask])) if mask.any() else 0.0

    return SignalRecord(
        as_of=as_of,
        sr3_contract=sr3_contract,
        sr3_dte=(smile.params.expiry_date - as_of).days,
        ref_start=ref_start,
        ref_end=ref_end,
        forward_price=float(smile.params.forward_price),
        forward_rate=fwd_rate_pct,
        n_meetings_in_period=len(nodes),
        expected_changes_bp=tuple(n.expected_change_bp for n in nodes),
        fedwatch_probabilities=tuple((n.p_lower, n.p_upper) for n in nodes),
        zq_day_weighted_var_bp2=float(zq_var_bp2),
        sr3_total_var_bp2=float(sr3_total_var_bp2),
        sr3_skew=float(rnd.skew),
        sr3_kurt=float(rnd.kurt),
        sr3_stability_flag=str(rnd.stability_flag),
        intermeeting_drift_var_bp2=float(intermeeting_drift_var_bp2),
        basis_var_bp2=float(basis_var_bp2),
        explained_var_bp2=float(explained),
        residual_var_bp2=float(residual),
        residual_to_explained_ratio=float(ratio),
        tail_lower_50=_tail_below(fwd_rate_pct - 0.50),
        tail_lower_75=_tail_below(fwd_rate_pct - 0.75),
        tail_lower_100=_tail_below(fwd_rate_pct - 1.00),
        tail_upper_50=_tail_above(fwd_rate_pct + 0.50),
        tail_upper_75=_tail_above(fwd_rate_pct + 0.75),
        tail_upper_100=_tail_above(fwd_rate_pct + 1.00),
        warnings=tuple(warnings),
    )
