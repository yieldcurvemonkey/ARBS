"""ZQ-anchored FedWatch tree builder per CME methodology.

For each month inside the configured range:
- Determine whether it has an FOMC meeting (from the FOMC schedule).
- Pull avg EFFR from ZQ contract price: avg = 100 - price.
- Find the nearest non-FOMC anchor month, set start = end = avg there.
- Walk backward filling end[T-1] = avg[T] (anchor); solve start[T-1] from
  the FOMC formula avg = (n/(n+m))*start + (m/(n+m))*end.
- Walk forward by exactly one month from each anchor (per CME footnote 2).

Reference: ``cmegroup.com/articles/.../understanding-the-cme-group-fedwatch-tool-methodology.html``.
"""

from __future__ import annotations

import datetime
import math
from typing import Dict, List, Tuple

import pandas as pd

from RVUtils.SR3ZQDistributionScreener._types import MonthState


_MONTH_CODE = "FGHJKMNQUVXZ"


def months_in_range(
    start: datetime.date, end: datetime.date
) -> List[Tuple[int, int]]:
    """Inclusive list of (year, month) tuples in [start, end]."""
    out: List[Tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def contract_for_month(year: int, month: int) -> str:
    return f"ZQ{_MONTH_CODE[month - 1]}{year % 100:02d}"


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (
            datetime.date(year + 1, 1, 1) - datetime.date(year, 12, 1)
        ).days
    return (
        datetime.date(year, month + 1, 1) - datetime.date(year, month, 1)
    ).days


def build_fedwatch_tree(
    *,
    zq_prices: Dict[str, float],
    fomc_schedule: pd.DataFrame,
    months_range: Tuple[Tuple[int, int], Tuple[int, int]],
) -> Dict[str, MonthState]:
    """Build per-month ``MonthState`` keyed by month label (e.g. "jun26").

    Walk backwards from each non-FOMC anchor month (avg = start = end), then
    forward exactly one month per CME methodology.
    """
    fomc_lookup: Dict[Tuple[int, int], datetime.date] = {}
    for _, row in fomc_schedule.iterrows():
        eff = row["effective_date"]
        if isinstance(eff, pd.Timestamp):
            eff = eff.date()
        fomc_lookup[(eff.year, eff.month)] = eff

    (y_lo, m_lo), (y_hi, m_hi) = months_range
    months = months_in_range(
        datetime.date(y_lo, m_lo, 1), datetime.date(y_hi, m_hi, 1)
    )

    # Initialize states from ZQ prices
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

    # Find first anchor non-FOMC month
    anchor_idx = None
    for i, key in enumerate(months):
        if not states[key].has_meeting and not math.isnan(states[key].avg_effr):
            anchor_idx = i
            break
    if anchor_idx is None:
        raise ValueError(
            "No anchor non-FOMC month inside range — cannot build FedWatch tree"
        )

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
                    start = (
                        cur.avg_effr - (mm / (n + mm)) * end
                    ) / (n / (n + mm))
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
                end = (
                    cur.avg_effr - (n / (n + mm)) * start
                ) / (mm / (n + mm))
        else:
            end = cur.avg_effr
        populated[nm] = MonthState(
            **{**cur.__dict__, "effr_start": start, "effr_end": end}
        )
        populated_keys.add(nm)

    # First anchor pass
    _populate_anchor(anchor_idx)
    _walk_back(anchor_idx)
    _walk_forward_one(anchor_idx)

    # Subsequent anchors
    while True:
        next_anchor = None
        for i in range(anchor_idx + 1, len(months)):
            if (
                not states[months[i]].has_meeting
                and months[i] not in populated_keys
                and not math.isnan(states[months[i]].avg_effr)
            ):
                next_anchor = i
                break
        if next_anchor is None:
            break
        _populate_anchor(next_anchor)
        _walk_back(next_anchor)
        _walk_forward_one(next_anchor)
        anchor_idx = next_anchor

    return {s.label: s for s in populated.values()}
