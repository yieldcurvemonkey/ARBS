"""ZQ settles -> per-meeting jump lattice (the FedWatch ladder), with gates.

Wraps the committed CME-methodology tree builder
(:func:`RVUtils.SR3ZQDistributionScreener._fedwatch.build_fedwatch_tree`) and
reduces its month states to the one object this framework consumes: per meeting,
the ZQ-implied jump in bp and its two-point mantissa lattice.

Conventions
-----------
``effective_date`` in the FOMC schedule is the **first day at the new rate**
(the CME Sep-2022 worked example splits September 21/9, which requires
effective = Sep 22 for a Sep 20-21 meeting). The decision date is taken as
``effective - 1 day`` and is what option-expiry comparisons use.

Staleness gate: FedWatch will happily manufacture probabilities from a dead
quote. A ZQ contract is flagged stale when its price is bit-identical to the
adjacent month's for that session AND the pair has shown no daily change for
``stale_run`` sessions. Meetings whose months touch a stale contract carry
``stale=True`` and are excluded from signals (never silently dropped).
"""
from __future__ import annotations

import dataclasses
import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.FlyVsVol.baselines import mantissa_probs
from RVUtils.SR3ZQDistributionScreener._fedwatch import build_fedwatch_tree

__all__ = ["MeetingLattice", "zq_settle_panel", "meeting_ladder", "ladder_history"]

_MONTH_CODE = "FGHJKMNQUVXZ"


@dataclasses.dataclass(frozen=True)
class MeetingLattice:
    """One meeting's ZQ-implied jump and its two-point lattice."""

    effective: datetime.date          # first day at the new rate
    decision: datetime.date           # effective - 1
    jump_bp: float                    # ZQ-implied expected jump
    support: Tuple[int, int]          # (characteristic, characteristic +/- 1)
    q: float                          # prob of the SECOND support point (mantissa)
    contract: str                     # ZQ contract of the meeting month
    stale: bool = False

    @property
    def probs(self) -> Dict[int, float]:
        a, b = self.support
        if a == b:
            return {a: 1.0}
        return {a: 1.0 - self.q, b: self.q}

    @property
    def e_moves(self) -> float:
        a, b = self.support
        return a * (1.0 - self.q) + b * self.q

    def variance_bp2(self, weight: float = 1.0, move_size_bp: float = 25.0) -> float:
        """Bernoulli event variance in bp^2 at the given day weight."""
        a, b = self.support
        span = (b - a) * move_size_bp * weight
        return span * span * self.q * (1.0 - self.q)


def zq_settle_panel(
    symbols: Sequence[str], *, base_cache_dir=None
) -> pd.DataFrame:
    """Wide date x contract panel of ZQ settles from the serff cache (no network)."""
    from BT.serff.futures_data import load_cached

    cols = {}
    for s in symbols:
        df = load_cached(s, base_cache_dir)
        if df is None or df.empty:
            continue
        col = next((c for c in ("Close", "Last", "Settle", "close") if c in df.columns),
                   None)
        if col is None:
            continue
        cols[s] = pd.to_numeric(df[col], errors="coerce")
    panel = pd.DataFrame(cols).sort_index()
    panel.index = pd.to_datetime(panel.index).normalize()
    return panel


def _contract_for(year: int, month: int) -> str:
    return f"ZQ{_MONTH_CODE[month - 1]}{year % 100:02d}"


def _stale_pairs(panel: pd.DataFrame, as_of: pd.Timestamp, run: int) -> set:
    """Contracts whose price equals the adjacent month's, unchanged for ``run`` days."""
    window = panel.loc[:as_of].tail(run)
    if window.empty:
        return set()
    out = set()
    cols = list(window.columns)
    for a, b in zip(cols[:-1], cols[1:]):
        sub = window[[a, b]].dropna()
        if len(sub) < run:
            continue
        if (sub[a] == sub[b]).all() and sub[a].nunique() == 1:
            out.update((a, b))
    return out


def meeting_ladder(
    as_of: datetime.date,
    zq_panel: pd.DataFrame,
    fomc_schedule: pd.DataFrame,
    *,
    horizon_months: int = 14,
    move_size_bp: float = 25.0,
    stale_run: int = 5,
) -> List[MeetingLattice]:
    """The per-meeting lattice as of one date, from ZQ settles on that date.

    Months run from the month AFTER ``as_of``'s month (the current delivery
    month's average is contaminated by realized fixings) out ``horizon_months``.
    """
    ts = pd.Timestamp(as_of)
    row = zq_panel.loc[:ts]
    if row.empty:
        return []
    last = row.iloc[-1]
    if (ts - row.index[-1]) > pd.Timedelta(days=5):
        return []                      # no fresh ZQ session near this date

    y, m = as_of.year, as_of.month + 1
    if m == 13:
        y, m = y + 1, 1
    start_ym = (y, m)
    y2, m2 = y, m + horizon_months
    while m2 > 12:
        y2, m2 = y2 + 1, m2 - 12
    prices = {}
    yy, mm = start_ym
    while (yy, mm) <= (y2, m2):
        c = _contract_for(yy, mm)
        v = last.get(c, np.nan)
        if np.isfinite(v):
            prices[c] = float(v)
        mm += 1
        if mm == 13:
            yy, mm = yy + 1, 1

    if len(prices) < 3:
        return []
    try:
        tree = build_fedwatch_tree(
            zq_prices=prices, fomc_schedule=fomc_schedule,
            months_range=(start_ym, (y2, m2)),
        )
    except ValueError:
        return []

    stale = _stale_pairs(zq_panel, ts, stale_run)
    out: List[MeetingLattice] = []
    for st in tree.values():
        d = st.__dict__
        if not d.get("has_meeting"):
            continue
        start_r, end_r = d.get("effr_start"), d.get("effr_end")
        if start_r is None or end_r is None or not (
            np.isfinite(start_r) and np.isfinite(end_r)
        ):
            continue
        jump = (end_r - start_r) * 10000.0
        probs = mantissa_probs(jump, move_size_bp)
        keys = sorted(probs)
        if len(keys) == 1:
            support, q = (keys[0], keys[0]), 0.0
        else:
            support, q = (keys[0], keys[1]), probs[keys[1]]
        eff = d["meeting_date"]
        if isinstance(eff, pd.Timestamp):
            eff = eff.date()
        out.append(MeetingLattice(
            effective=eff,
            decision=eff - datetime.timedelta(days=1),
            jump_bp=float(jump),
            support=support,
            q=float(q),
            contract=d["contract"],
            stale=d["contract"] in stale,
        ))
    out.sort(key=lambda x: x.effective)
    return out


def ladder_history(
    dates: Sequence[datetime.date],
    zq_panel: pd.DataFrame,
    fomc_schedule: pd.DataFrame,
    **kw,
) -> Dict[datetime.date, List[MeetingLattice]]:
    """``meeting_ladder`` fanned over dates (pure lookups; no network)."""
    return {d: meeting_ladder(d, zq_panel, fomc_schedule, **kw) for d in dates}
