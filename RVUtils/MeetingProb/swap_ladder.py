"""FOMC-dated swap curves -> per-meeting jump lattice (the swap-side ladder).

The second linear source. The ZQ ladder (:mod:`RVUtils.MeetingProb.ladder`)
reads per-meeting jumps out of monthly EFFR averages through the FedWatch
bootstrap; this module reads the same object directly off a meeting-dated STIR
curve: the fair rate of the swap spanning meeting k -> meeting k+1 IS the
market's expected overnight level after meeting k, so consecutive period rates
difference into per-meeting jumps with no bootstrap at all.

Curves (built by ``IRSwapsMDP(source="BARCHART_STIRF-RL")``):

* ``USD-OIS-Q12xM12STIRT-SERFFX-MIX23`` — EFFR leg, directly comparable to ZQ.
* ``USD-SOFR-1D-Q12xM12STIRT`` — SOFR leg, basis-free input to anything SR3.

Conventions
-----------
Meeting dates come from the central-bank-dates registry via
:func:`SDRUtils.analytics.fomc.load_fomc_schedule`; the registry
``effective_date`` is used verbatim as :attr:`MeetingLattice.effective` — the
ZQ ladder emits exactly these dates (verified against the jul26–jan27 strip),
so the two ladders line up meeting-for-meeting.

The in-progress period (registry effective <= as_of) is never priced: its
fair rate blends realized fixings with the pending decision and, on the OIS
curve, trips the known rateslib fixings/holiday-calendar mismatch. The
pre-first-meeting level is the caller-supplied ``base_rate`` instead (the
overnight fixing: policy is constant until the next decision). Use the EFFR
fixing with the OIS curve and the SOFR fixing with the SOFR curve.

Unlike ZQ, a meeting near month-end never becomes unreadable here — there is
no contract-expiry seam, because the curve carries the full meeting-dated
strip on every build date.
"""
from __future__ import annotations

import datetime
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from RVUtils.FlyVsVol.baselines import mantissa_probs
from RVUtils.MeetingProb.ladder import MeetingLattice

__all__ = ["fomc_period_rates", "jumps_from_period_rates", "swap_meeting_ladder"]


def fomc_period_rates(
    as_of: datetime.date,
    pricer,
    fomc_schedule: pd.DataFrame,
    *,
    schedule_key: str = "USD-SOFR-1D",
    max_meetings: int = 12,
    price_fn: Optional[Callable[[datetime.date, datetime.date], float]] = None,
) -> pd.DataFrame:
    """Fair rate of each upcoming meeting-period swap on one curve.

    For every meeting with registry ``effective_date`` strictly after
    ``as_of`` (up to ``max_meetings``), prices the swap running from that
    meeting's effective date to the next meeting's — the expected overnight
    level *after* that meeting. No ``date.today()`` anywhere: the frame is a
    pure function of ``as_of`` and the curve.

    ``price_fn(effective, maturity) -> decimal rate`` overrides the pricer
    (test seam). Rates are returned as decimals (0.0374 = 3.74%).

    Returns a frame with ``meeting_label``, ``effective`` (datetime.date),
    ``maturity``, ``rate`` — sorted by effective, NaN rate on pricing failure
    (never silently dropped).
    """
    sched = fomc_schedule.sort_values("effective_date").reset_index(drop=True)
    eff = pd.to_datetime(sched["effective_date"]).dt.date
    upcoming = sched[eff > as_of].head(max_meetings)

    if price_fn is None:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        def price_fn(e: datetime.date, m: datetime.date) -> float:
            query = IRSwapQuery(
                curve=schedule_key, effective_date=e, maturity_date=m,
                value=IRSwapValue.RATE,
            )
            package, _ = query.resolve_package(pricer_or_curve=pricer)
            return float(pricer.fair_rate(package[0]))

    rows = []
    for _, r in upcoming.iterrows():
        e = pd.Timestamp(r["effective_date"]).date()
        m = pd.Timestamp(r["maturity_date"]).date()
        try:
            rate = float(price_fn(e, m))
        except Exception:
            rate = float("nan")
        rows.append({
            "meeting_label": r["meeting_label"],
            "effective": e, "maturity": m, "rate": rate,
        })
    return pd.DataFrame(rows)


def jumps_from_period_rates(period_rates: pd.Series, base_rate: float) -> pd.Series:
    """Per-meeting jumps in bp from consecutive period levels.

    ``jump_k = rate_k - rate_{k-1}`` with ``rate_0 = base_rate`` (all decimal
    in, bp out). The first jump is the next meeting's move off the current
    fixing; later jumps difference out any static overnight basis.
    """
    prev = period_rates.shift(1)
    prev.iloc[0] = base_rate
    return (period_rates - prev) * 1e4


def swap_meeting_ladder(
    as_of: datetime.date,
    pricer,
    fomc_schedule: pd.DataFrame,
    base_rate: float,
    *,
    schedule_key: str = "USD-SOFR-1D",
    max_meetings: int = 12,
    move_size_bp: float = 25.0,
    price_fn: Optional[Callable[[datetime.date, datetime.date], float]] = None,
) -> List[MeetingLattice]:
    """The per-meeting lattice as of one date, from a meeting-dated swap curve.

    Same reduction as the ZQ ladder: each jump maps to its two-point mantissa
    lattice. Meetings whose period failed to price are dropped along with all
    LATER meetings (a NaN level breaks every subsequent difference), never
    bridged over.
    """
    frame = fomc_period_rates(
        as_of, pricer, fomc_schedule,
        schedule_key=schedule_key, max_meetings=max_meetings, price_fn=price_fn,
    )
    if frame.empty:
        return []
    bad = frame["rate"].isna()
    if bad.any():
        frame = frame.iloc[: int(bad.idxmax())]
    if frame.empty:
        return []

    jumps = jumps_from_period_rates(frame["rate"], base_rate)
    out: List[MeetingLattice] = []
    for (_, row), jump in zip(frame.iterrows(), jumps):
        probs = mantissa_probs(float(jump), move_size_bp)
        keys = sorted(probs)
        if len(keys) == 1:
            support, q = (keys[0], keys[0]), 0.0
        else:
            support, q = (keys[0], keys[1]), probs[keys[1]]
        out.append(MeetingLattice(
            effective=row["effective"],
            decision=row["effective"] - datetime.timedelta(days=1),
            jump_bp=float(jump),
            support=support,
            q=float(q),
            contract=str(row["meeting_label"]),
        ))
    return out
