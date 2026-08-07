"""The FOMC meeting calendar, and what it does to a butterfly.

This module exists because of one fact about the instrument:

    **SR3 settles on the day-weighted compounded average of overnight SOFR over
    its IMM reference quarter.** A contract whose quarter contains two policy
    meetings is legitimately priced differently from one containing one, and a
    meeting late in the quarter moves the contract by only a fraction of its
    jump.

So a butterfly on three consecutive contracts is *not* a clean curvature
measure. Part of it is the calendar. Under a perfectly smooth policy path --
one where every meeting moves the target by the same amount -- the strip is
still kinked, because the meeting calendar is lumpy against the IMM grid.
Fading that kink is fading the calendar.

The objects here separate the two:

``meeting_weight_matrix``
    ``W[i, m]`` = the share of contract ``i``'s reference quarter spent at the
    post-meeting-``m`` rate. Pure arithmetic: no market data, no estimation.
    (Delegates to :func:`RVUtils.SFRRVLab.lattice.day_weight_matrix`, which is
    the same construction the FedWatch lattice null uses.)

``calendar_fly_loading``
    ``Phi_m = 2*W[belly, m] - W[front, m] - W[back, m]`` -- how much of meeting
    ``m``'s jump lands in a given butterfly. ``sum_m Phi_m`` is the butterfly a
    **1bp-per-meeting** path would print, in bp: the calendar's own curvature.

``solve_smooth_path`` / ``meeting_residual``
    fit per-meeting jumps to the observed strip with a penalty on the *second
    difference* of the jump sequence, then take the residual. The penalty is the
    whole point: it shrinks toward a **smooth policy path**, not toward no
    policy change, so the fitted strip reproduces the calendar's lumpiness and
    the residual is the curvature the calendar cannot explain.

    (:func:`RVUtils.SFRRVLab.lattice.solve_meeting_jumps` uses a plain ridge on
    the jumps themselves, which shrinks toward "the Fed does nothing". That is
    the right prior for a FedWatch lattice and the wrong one here.)

Sign conventions follow the rest of the lab: rates in **bp**, a butterfly is
``2*belly - front - back``, and "high means rich".
"""
from __future__ import annotations

import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "FOMC_DECISIONS", "LAST_ACTUAL_YEAR", "LAST_PUBLISHED_YEAR",
    "PROJECTION_GAPS_WEEKS", "project_year", "fomc_decisions", "fomc_schedule",
    "meeting_weight_matrix", "effective_meeting_count", "calendar_fly_loading",
    "contract_weight_table", "solve_smooth_path", "meeting_residual_panel",
    "calendar_fly_panel", "calendar_tilted_fly", "meeting_count_gaps",
    "UNSCHEDULED_2020",
]

# ---------------------------------------------------------------------------
# the calendar
# ---------------------------------------------------------------------------

#: FOMC **decision** dates -- the second day of each scheduled two-day meeting,
#: which is when the target range is announced. The new range is effective the
#: following business day, which is why every weight function here takes an
#: ``effective_lag_days`` (default 1).
#:
#: 2018-2026 are the actual scheduled calendar. They are cross-checked in
#: ``tests/test_meanrev_meetings.py`` against two independent in-repo sources:
#: ``Query/IRSwaps/_CENTRAL_BANK_DATES._FALLBACK_DATES['USD-SOFR-1D']`` (which
#: stores each meeting window as ``(decision, next_decision)`` from Feb-2023 on)
#: and the 2026 list hardcoded in
#: ``MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/stir_curve_building_utils.py``.
#: The regime boundaries in ``RVUtils/MeanRev/panel.py`` are a third check:
#: HIKING starts 2022-03-17 (the day after the 2022-03-16 liftoff), PLATEAU
#: 2023-07-27 (after the last hike on 2023-07-26) and CUTTING 2024-09-18 (the
#: first cut).
#:
#: **2020 is the scheduled calendar, not the realised one.** The 2020-03-15
#: emergency cut replaced the scheduled 2020-03-17/18 meeting, and 2020-03-03
#: was an unscheduled intermeeting cut. Neither was knowable ex ante, and this
#: module models what the strip could price, so both are excluded. See
#: ``UNSCHEDULED_2020``.
FOMC_DECISIONS: Dict[int, Tuple[datetime.date, ...]] = {
    2018: (datetime.date(2018, 1, 31), datetime.date(2018, 3, 21),
           datetime.date(2018, 5, 2), datetime.date(2018, 6, 13),
           datetime.date(2018, 8, 1), datetime.date(2018, 9, 26),
           datetime.date(2018, 11, 8), datetime.date(2018, 12, 19)),
    2019: (datetime.date(2019, 1, 30), datetime.date(2019, 3, 20),
           datetime.date(2019, 5, 1), datetime.date(2019, 6, 19),
           datetime.date(2019, 7, 31), datetime.date(2019, 9, 18),
           datetime.date(2019, 10, 30), datetime.date(2019, 12, 11)),
    2020: (datetime.date(2020, 1, 29), datetime.date(2020, 3, 18),
           datetime.date(2020, 4, 29), datetime.date(2020, 6, 10),
           datetime.date(2020, 7, 29), datetime.date(2020, 9, 16),
           datetime.date(2020, 11, 5), datetime.date(2020, 12, 16)),
    2021: (datetime.date(2021, 1, 27), datetime.date(2021, 3, 17),
           datetime.date(2021, 4, 28), datetime.date(2021, 6, 16),
           datetime.date(2021, 7, 28), datetime.date(2021, 9, 22),
           datetime.date(2021, 11, 3), datetime.date(2021, 12, 15)),
    2022: (datetime.date(2022, 1, 26), datetime.date(2022, 3, 16),
           datetime.date(2022, 5, 4), datetime.date(2022, 6, 15),
           datetime.date(2022, 7, 27), datetime.date(2022, 9, 21),
           datetime.date(2022, 11, 2), datetime.date(2022, 12, 14)),
    2023: (datetime.date(2023, 2, 1), datetime.date(2023, 3, 22),
           datetime.date(2023, 5, 3), datetime.date(2023, 6, 14),
           datetime.date(2023, 7, 26), datetime.date(2023, 9, 20),
           datetime.date(2023, 11, 1), datetime.date(2023, 12, 13)),
    2024: (datetime.date(2024, 1, 31), datetime.date(2024, 3, 20),
           datetime.date(2024, 5, 1), datetime.date(2024, 6, 12),
           datetime.date(2024, 7, 31), datetime.date(2024, 9, 18),
           datetime.date(2024, 11, 7), datetime.date(2024, 12, 18)),
    2025: (datetime.date(2025, 1, 29), datetime.date(2025, 3, 19),
           datetime.date(2025, 5, 7), datetime.date(2025, 6, 18),
           datetime.date(2025, 7, 30), datetime.date(2025, 9, 17),
           datetime.date(2025, 10, 29), datetime.date(2025, 12, 10)),
    2026: (datetime.date(2026, 1, 28), datetime.date(2026, 3, 18),
           datetime.date(2026, 4, 29), datetime.date(2026, 6, 17),
           datetime.date(2026, 7, 29), datetime.date(2026, 9, 16),
           datetime.date(2026, 10, 28), datetime.date(2026, 12, 9)),
    2027: (datetime.date(2027, 1, 27), datetime.date(2027, 3, 17),
           datetime.date(2027, 4, 28), datetime.date(2027, 6, 16),
           datetime.date(2027, 7, 28), datetime.date(2027, 9, 22),
           datetime.date(2027, 11, 3), datetime.date(2027, 12, 15)),
}

#: 2020's realised intermeeting actions, kept for the record and deliberately
#: **not** in the schedule: an emergency cut is not in anyone's day-weight
#: matrix the day before it happens.
UNSCHEDULED_2020: Tuple[datetime.date, ...] = (
    datetime.date(2020, 3, 3), datetime.date(2020, 3, 15),
)

#: Through this year the dates above are the published, realised calendar.
LAST_ACTUAL_YEAR = 2026

#: Through this year the dates above are the Fed's published forward calendar.
#: Beyond it :func:`project_year` takes over and every row is flagged.
LAST_PUBLISHED_YEAR = 2027

#: Inter-meeting gaps in weeks used by :func:`project_year`, taken from the
#: 2026 calendar (7, 6, 7, 6, 7, 6, 6 weeks, summing to 45, with a 7-week jump
#: into the next January -- 52 in total). Measured fidelity against every year we
#: do know, anchoring on the last Wednesday of January
#: (``test_projection_fidelity_against_every_known_year`` pins this table):
#:
#: ===== ============== ===================
#: year  meetings wrong max error (days)
#: ===== ============== ===================
#: 2018  4 of 8         8
#: 2019  0 of 8         0
#: 2020  3 of 8         8
#: 2021  3 of 8         7
#: 2022  4 of 8         7
#: 2023  6 of 8         7
#: 2024  3 of 8         8
#: 2025  1 of 8         7
#: 2026  0 of 8         0
#: 2027  3 of 8         7
#: ===== ============== ===================
#:
#: So the rule is exact in two of ten years and out by at most a week in the
#: rest -- it gets the *rhythm* right and the phase sometimes wrong. A 7-day
#: error moves a meeting's day weight inside a 91-day quarter by ~0.077 of one
#: jump. That is small per meeting and it is **not** negligible in aggregate for
#: contracts deep enough to be priced mostly off projected meetings, so the
#: notebook re-runs with the projection shifted a week each way and reports the
#: correlation of the worst affected key rather than asking anyone to take it on
#: trust.
PROJECTION_GAPS_WEEKS: Tuple[int, ...] = (7, 6, 7, 6, 7, 6, 6)


def _last_wednesday_of_january(year: int) -> datetime.date:
    d = datetime.date(year, 1, 31)
    while d.weekday() != 2:                      # Monday=0 ... Wednesday=2
        d -= datetime.timedelta(days=1)
    return d


def project_year(year: int, *, shift_weeks: int = 0) -> List[datetime.date]:
    """Projected FOMC decision dates for a year beyond the published calendar.

    Anchored on the last Wednesday of January, then :data:`PROJECTION_GAPS_WEEKS`.

    ``shift_weeks`` translates the **whole year uniformly**, which is the
    perturbation a sensitivity check wants: "what if the Fed's 2030 calendar sits
    a week later than we guessed". Adding the shift to each *gap* instead would
    displace meeting ``k`` by ``k * shift_weeks``, so a nominal one-week probe
    would move the December meeting by seven weeks and overstate how fragile the
    projection is.
    """
    d = _last_wednesday_of_january(int(year)) + datetime.timedelta(weeks=int(shift_weeks))
    out = [d]
    for g in PROJECTION_GAPS_WEEKS:
        d = d + datetime.timedelta(weeks=int(g))
        out.append(d)
    return out


def fomc_decisions(
    start: Optional[datetime.date] = None, end: Optional[datetime.date] = None,
    *, project_through: int = 2035, shift_weeks: int = 0,
) -> List[datetime.date]:
    """Every scheduled FOMC decision date in ``[start, end]``, sorted.

    Years past :data:`LAST_PUBLISHED_YEAR` come from :func:`project_year`.
    """
    years = sorted(FOMC_DECISIONS)
    out: List[datetime.date] = []
    for y in years:
        out.extend(FOMC_DECISIONS[y])
    for y in range(max(years) + 1, int(project_through) + 1):
        out.extend(project_year(y, shift_weeks=shift_weeks))
    out = sorted(out)
    if start is not None:
        out = [d for d in out if d >= start]
    if end is not None:
        out = [d for d in out if d <= end]
    return out


def fomc_schedule(
    start: Optional[datetime.date] = None, end: Optional[datetime.date] = None,
    *, effective_lag_days: int = 1, project_through: int = 2035,
    shift_weeks: int = 0,
) -> pd.DataFrame:
    """The calendar as a frame: decision date, effective date and provenance.

    ``source`` is ``'actual'`` (realised), ``'published'`` (the Fed's forward
    calendar) or ``'projected'``. Any result that leans on ``projected`` rows
    has to say so, which is why the column exists.
    """
    ds = fomc_decisions(start, end, project_through=project_through,
                        shift_weeks=shift_weeks)
    rows = []
    for d in ds:
        src = ("actual" if d.year <= LAST_ACTUAL_YEAR
               else "published" if d.year <= LAST_PUBLISHED_YEAR else "projected")
        rows.append({
            "decision_date": pd.Timestamp(d),
            "effective_date": pd.Timestamp(d + datetime.timedelta(days=int(effective_lag_days))),
            "year": d.year, "source": src,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["seq"] = np.arange(len(out))
    return out


# ---------------------------------------------------------------------------
# day weights
# ---------------------------------------------------------------------------

def meeting_weight_matrix(
    windows: Sequence[Tuple[datetime.date, datetime.date]],
    meetings: Sequence[datetime.date], *, effective_lag_days: int = 1,
) -> np.ndarray:
    """``W[i, m]``: the share of window ``i`` spent at the post-meeting-``m`` rate.

    Thin wrapper over :func:`RVUtils.SFRRVLab.lattice.day_weight_matrix` so this
    lab and the options lab cannot drift apart on the one piece of arithmetic
    they share.
    """
    from RVUtils.SFRRVLab.lattice import day_weight_matrix

    return day_weight_matrix(windows, meetings, effective_lag_days=effective_lag_days)


def effective_meeting_count(W: np.ndarray) -> np.ndarray:
    """``M_i = sum_m W[i, m]`` -- the day-weighted **cumulative** meeting count.

    Read the definition carefully, because the natural misreading is wrong.
    ``W[i, m]`` is 1 for every meeting that took effect *before* window ``i``
    starts, so ``M_i`` counts all of those at full weight plus the fractional
    contribution of the meetings inside the window. It is a running total from
    wherever the supplied meeting list begins, **not** "how many meetings this
    contract spans", and its absolute level therefore depends on that list.

    Only **differences** of it are meaningful, and differences are all anything
    here uses: ``M_back - M_front`` is the day-weighted meeting count between two
    windows, and ``2*M_belly - M_front - M_back`` is the butterfly's calendar
    curvature. Both are invariant to where the meeting list starts, because the
    common prefix cancels.
    """
    return np.asarray(W, dtype=float).sum(axis=1)


def in_window_meeting_count(W: np.ndarray, windows, meetings, *,
                            effective_lag_days: int = 1) -> np.ndarray:
    """Day-weighted meeting count **inside** each window, i.e. excluding the prefix.

    ``sum_m W[i, m] * 1{meeting m is effective after window i starts}``. This is
    the quantity :func:`effective_meeting_count` is usually mistaken for, and it
    is the one to quote when describing a single contract rather than a spread.
    """
    Wm = np.asarray(W, dtype=float)
    out = np.zeros(Wm.shape[0])
    eff = [pd.Timestamp(m) + pd.Timedelta(days=int(effective_lag_days))
           for m in meetings]
    for i, (start, _end) in enumerate(windows):
        s = pd.Timestamp(start)
        inside = np.array([e > s for e in eff])
        out[i] = float(Wm[i, inside].sum())
    return out


def calendar_fly_loading(
    W: np.ndarray, legs: Sequence[int], weights: Sequence[float] = (-1.0, 2.0, -1.0),
) -> np.ndarray:
    """``Phi_m = sum_j weight_j * W[leg_j, m]`` -- meeting ``m``'s loading on a package.

    With the default weights and ``legs=(front, belly, back)`` this is
    ``2*W[belly] - W[front] - W[back]``: how much of meeting ``m``'s jump the
    butterfly inherits. ``Phi.sum()`` is the butterfly, in bp, that a path of
    **1bp per meeting** would print -- the calendar's own curvature, carrying no
    market information whatsoever.
    """
    Wm = np.asarray(W, dtype=float)
    return sum(float(w) * Wm[int(i)] for w, i in zip(weights, legs))


def meeting_count_gaps(
    starts: Sequence[datetime.date], meetings: Sequence[datetime.date],
    legs: Sequence[int] = (0, 1, 2), *, effective_lag_days: int = 1,
) -> Tuple[int, int, int]:
    """Integer meeting counts in the two inter-leg gaps, and their asymmetry.

    Returns ``(near_gap, far_gap, asym)`` where ``near_gap`` counts meetings
    between the front and belly leg *starts* and ``far_gap`` between the belly
    and back. This is the quantity the existing screener calls
    ``fomc_near_gap`` / ``fomc_far_gap`` / ``fomc_asym``.

    The interval is **half-open on the right**, ``(a, b]``, on the *effective*
    date -- matching :func:`meeting_weight_matrix`, where a meeting effective
    exactly on a window's start contributes weight 1 to that window (it is
    already in force for the whole quarter) and one effective exactly on the
    end contributes 0. Using ``[a, b)`` here instead would put a boundary
    meeting in the wrong gap and disagree with the day weights the rest of the
    module is built on -- so the two conventions are pinned together by
    ``test_gap_counts_and_day_weights_use_the_same_boundary``.
    """
    a, b, c = (starts[int(i)] for i in legs)
    eff = [m + datetime.timedelta(days=int(effective_lag_days)) for m in meetings]
    near = sum(1 for d in eff if a < d <= b)
    far = sum(1 for d in eff if b < d <= c)
    return near, far, abs(near - far)


def contract_weight_table(
    contracts: pd.DataFrame, meetings: Sequence[datetime.date], *,
    id_col: str = "code", start_col: str = "imm_start", end_col: str = "imm_end",
    effective_lag_days: int = 1,
) -> pd.DataFrame:
    """``contract code x meeting`` day-weight table, computed **once**.

    A contract's IMM reference quarter is a property of the contract, not of the
    date it is observed on, so this is 55 rows rather than 66,000 -- and every
    date's matrix is a row selection out of it. (Every contract in the strip is
    pre-accrual by construction: the panel builder drops a contract once its
    quarter starts, so no window is ever partially realised.)
    """
    c = contracts.drop_duplicates(id_col)[[id_col, start_col, end_col]]
    codes = list(c[id_col])
    windows = [(pd.Timestamp(a).date(), pd.Timestamp(b).date())
               for a, b in zip(c[start_col], c[end_col])]
    W = meeting_weight_matrix(windows, meetings, effective_lag_days=effective_lag_days)
    return pd.DataFrame(W, index=pd.Index(codes, name=id_col),
                        columns=pd.Index([pd.Timestamp(m) for m in meetings],
                                         name="meeting"))


# ---------------------------------------------------------------------------
# the smooth-path fit
# ---------------------------------------------------------------------------

def _second_difference_matrix(n: int) -> np.ndarray:
    """``D`` with ``(D x)_k = x[k] - 2 x[k+1] + x[k+2]``; shape ``(n-2, n)``."""
    if n < 3:
        return np.zeros((0, n))
    D = np.zeros((n - 2, n))
    for k in range(n - 2):
        D[k, k] = 1.0
        D[k, k + 1] = -2.0
        D[k, k + 2] = 1.0
    return D


def solve_smooth_path(
    rates_bp: Sequence[float], W: np.ndarray, *, lam: float = 10.0,
    base_bp: Optional[float] = None, ridge: float = 1e-6,
    fit_base: bool = True,
) -> Dict[str, np.ndarray]:
    """Per-meeting jumps that fit the strip, penalised for *roughness*.

    Solves

    .. code-block:: text

        min_{base, delta}  || base + W delta - r ||^2  +  lam * || D delta ||^2

    where ``D`` is the second difference along the meeting sequence. ``lam`` is
    the only real knob and it is interpretable at both ends:

    * ``lam -> 0``     -- fit every jump; the residual goes to zero and the
      "kink" disappears along with it.
    * ``lam -> inf``   -- force ``delta`` onto a straight line in meeting index,
      i.e. a constant acceleration of policy. The fitted strip is then the
      lumpiest curve a *perfectly regular* Fed could produce, and the residual
      is everything else.

    That second limit is the honest null for a butterfly: not "the strip is
    smooth", but "the policy path is smooth **and the calendar is not**".

    Returns ``{'delta', 'base', 'fitted', 'resid'}`` in bp. ``resid`` is
    ``r - fitted`` per contract, which is the panel a structure signal is built
    from.

    ``ridge`` is a small conditioning term on ``delta`` only -- the base rate is
    never shrunk toward zero, which would be shrinking a 4% policy rate toward
    0%. With ``fit_base=False`` the base must be supplied; there is no sensible
    default, and guessing one silently is how a fitted level ends up meaning
    nothing.
    """
    y = np.asarray(rates_bp, dtype=float)
    Wm = np.asarray(W, dtype=float)
    n_obs, n_mtg = Wm.shape
    ok = np.isfinite(y)
    if ok.sum() < 3 or n_mtg == 0:
        nan = np.full(n_obs, np.nan)
        return {"delta": np.full(n_mtg, np.nan), "base": np.nan,
                "fitted": nan, "resid": nan}

    D = _second_difference_matrix(n_mtg)
    if fit_base and base_bp is None:
        X = np.column_stack([np.ones(n_obs), Wm])
        P = np.zeros((n_mtg + 1, n_mtg + 1))
        R = np.eye(n_mtg + 1)
        R[0, 0] = 0.0          # never shrink the base rate toward zero
        if D.size:
            P[1:, 1:] = D.T @ D
        A = X[ok].T @ X[ok] + float(lam) * P + float(ridge) * R
        try:
            sol = np.linalg.solve(A, X[ok].T @ y[ok])
        except np.linalg.LinAlgError:
            nan = np.full(n_obs, np.nan)
            return {"delta": np.full(n_mtg, np.nan), "base": np.nan,
                    "fitted": nan, "resid": nan}
        base, delta = float(sol[0]), sol[1:]
    else:
        if base_bp is None:
            raise ValueError("base_bp is required when fit_base=False")
        base = float(base_bp)
        z = y - base
        P = D.T @ D if D.size else np.zeros((n_mtg, n_mtg))
        A = Wm[ok].T @ Wm[ok] + float(lam) * P + float(ridge) * np.eye(n_mtg)
        try:
            delta = np.linalg.solve(A, Wm[ok].T @ z[ok])
        except np.linalg.LinAlgError:
            nan = np.full(n_obs, np.nan)
            return {"delta": np.full(n_mtg, np.nan), "base": np.nan,
                    "fitted": nan, "resid": nan}
    fitted = base + Wm @ delta
    return {"delta": delta, "base": base, "fitted": fitted, "resid": y - fitted}


def meeting_residual_panel(
    contracts: pd.DataFrame, *, meetings: Optional[Sequence[datetime.date]] = None,
    lam: float = 10.0, date_col: str = "as_of", slot_col: str = "slot",
    value_col: str = "rate_pct", id_col: str = "code",
    start_col: str = "imm_start", end_col: str = "imm_end",
    scale: float = 100.0, max_slot: int = 16, effective_lag_days: int = 1,
    return_extras: bool = False,
):
    """``date x slot`` panel of each contract's residual from the smooth path, in bp.

    On each date only the meetings the strip can actually resolve are carried --
    those falling strictly inside ``(front quarter start, back quarter end]``.
    A meeting before the whole strip shifts every contract equally and is
    therefore collinear with the base rate; one after it moves nothing. Either
    would be an unidentified column asking the penalty to invent a jump.

    With ``return_extras`` also returns ``{'fitted', 'n_meetings', 'path_bp',
    'proj_share'}``. ``proj_share`` is the share of each date's fitted jump
    magnitude sitting on *projected* meeting dates, and is the number that
    decides how far down the strip a result can be believed.
    """
    df = contracts.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    if slot_col not in df.columns:
        # The raw contract panel carries every listed contract, including ones
        # already accruing. add_strip_slots is the canonical place that both
        # drops those and numbers the rest, so the strip here is bit-identical
        # to the one the structures were enumerated from.
        from RVUtils.MeanRev.panel import add_strip_slots

        df = add_strip_slots(df, date_col=date_col, order_col=start_col,
                             start_col=start_col, slot_col=slot_col)
    df = df[df[slot_col] <= int(max_slot)]
    dates = sorted(pd.DatetimeIndex(df[date_col].unique()))
    if not dates:
        empty = pd.DataFrame()
        return (empty, {}) if return_extras else empty

    if meetings is None:
        lo = pd.Timestamp(min(dates)).date()
        hi = pd.Timestamp(df[end_col].max()).date()
        meetings = fomc_decisions(lo - datetime.timedelta(days=400), hi)
    meetings = list(meetings)
    m_eff = np.array([pd.Timestamp(m) + pd.Timedelta(days=int(effective_lag_days))
                      for m in meetings])
    is_proj = np.array([m.year > LAST_PUBLISHED_YEAR for m in meetings])

    wt = contract_weight_table(df, meetings, id_col=id_col, start_col=start_col,
                               end_col=end_col,
                               effective_lag_days=effective_lag_days)
    Wall = wt.to_numpy(dtype=float)
    row_of = {c: i for i, c in enumerate(wt.index)}
    starts = df.drop_duplicates(id_col).set_index(id_col)[start_col].map(pd.Timestamp)
    ends = df.drop_duplicates(id_col).set_index(id_col)[end_col].map(pd.Timestamp)

    slots_all = sorted(int(s) for s in df[slot_col].unique())
    resid = pd.DataFrame(np.nan, index=pd.DatetimeIndex(dates), columns=slots_all)
    fitted = pd.DataFrame(np.nan, index=pd.DatetimeIndex(dates), columns=slots_all)
    n_mtg, proj_share, path_bp = {}, {}, {}

    for d, g in df.groupby(date_col, sort=True):
        g = g.sort_values(slot_col)
        codes = list(g[id_col])
        if not codes:
            continue
        rows = [row_of[c] for c in codes if c in row_of]
        if len(rows) != len(codes):
            continue
        lo = min(starts[c] for c in codes)
        hi = max(ends[c] for c in codes)
        sel = np.flatnonzero((m_eff > lo) & (m_eff <= hi))
        if sel.size == 0:
            continue
        W = Wall[np.ix_(rows, sel)]
        y = g[value_col].to_numpy(dtype=float) * float(scale)
        fit = solve_smooth_path(y, W, lam=lam)
        d = pd.Timestamp(d)
        resid.loc[d, [int(s) for s in g[slot_col]]] = fit["resid"]
        fitted.loc[d, [int(s) for s in g[slot_col]]] = fit["fitted"]
        n_mtg[d] = int(sel.size)
        dm = np.abs(np.asarray(fit["delta"], dtype=float))
        tot = float(np.nansum(dm))
        proj_share[d] = (float(np.nansum(dm[is_proj[sel]])) / tot) if tot > 0 else 0.0
        path_bp[d] = float(np.nansum(np.asarray(fit["delta"], dtype=float)))

    if not return_extras:
        return resid
    extras = {
        "fitted": fitted,
        "n_meetings": pd.Series(n_mtg).sort_index(),
        "proj_share": pd.Series(proj_share).sort_index(),
        "path_bp": pd.Series(path_bp).sort_index(),
    }
    return resid, extras


def calendar_fly_panel(
    struct: pd.DataFrame, contracts: pd.DataFrame, *,
    meetings: Optional[Sequence[datetime.date]] = None, n_legs: int = 3,
    weights: Sequence[float] = (-1.0, 2.0, -1.0), date_col: str = "as_of",
    id_col: str = "code", start_col: str = "imm_start", end_col: str = "imm_end",
    effective_lag_days: int = 1,
) -> pd.DataFrame:
    """Per (date, structure) calendar quantities. **No market data is used.**

    Columns:

    ``phi_sum``
        ``sum_m Phi_m`` -- the butterfly in bp that a **1bp-per-meeting** path
        prints. The calendar's own curvature, known years in advance.
    ``mtg_fly``
        the same number read as a day-weighted meeting count,
        ``2*M_belly - M_front - M_back``. Algebraically identical to
        ``phi_sum`` (both are emitted because they are read differently, and
        because their equality is a useful self-check).
    ``mtg_front/belly/back``
        the **cumulative** day-weighted meeting count at each leg -- a running
        total from the start of the supplied meeting list, not an in-quarter
        count (see :func:`effective_meeting_count`). Only differences of these
        are meaningful, which is all ``mtg_fly`` and ``dM`` use.
    ``near_gap``/``far_gap``/``asym``
        integer meeting counts between consecutive leg *starts* on the
        half-open interval ``(a, b]``, and ``|near - far|`` -- the screener's
        ``fomc_asym``.
    ``proj_any``
        True if any meeting inside the structure's span is projected rather
        than published.

    **Every column is a function of the leg triple alone.** A key's legs are
    fixed contracts, so its meeting counts never change over its life: this
    frame is broadcast from one row per key, and any "gate" built on ``asym`` is
    a **static partition of keys**, not a time-varying condition. That is not a
    bug, but it changes how such a gate must be read.
    """
    s = struct.copy()
    s[date_col] = pd.to_datetime(s[date_col])
    c = contracts.drop_duplicates(id_col)[[id_col, start_col, end_col]].copy()

    if meetings is None:
        lo = pd.Timestamp(s[date_col].min()).date() - datetime.timedelta(days=400)
        hi = pd.Timestamp(c[end_col].max()).date()
        meetings = fomc_decisions(lo, hi)
    meetings = list(meetings)
    m_eff = [pd.Timestamp(m) + pd.Timedelta(days=int(effective_lag_days))
             for m in meetings]
    is_proj = np.array([m.year > LAST_PUBLISHED_YEAR for m in meetings])

    wt = contract_weight_table(c, meetings, id_col=id_col, start_col=start_col,
                               end_col=end_col,
                               effective_lag_days=effective_lag_days)
    W_of = {code: wt.loc[code].to_numpy(dtype=float) for code in wt.index}
    M_of = {code: float(v.sum()) for code, v in W_of.items()}
    start_of = dict(zip(c[id_col], pd.to_datetime(c[start_col])))
    end_of = dict(zip(c[id_col], pd.to_datetime(c[end_col])))
    eff_arr = np.array(m_eff)

    # The whole table is a function of the leg TRIPLE, not of the date: a key's
    # legs never change. So it is computed once per key and broadcast.
    leg_cols = [f"leg{j}_id" for j in range(n_legs)]
    keys = s.drop_duplicates("key")[["key", *leg_cols]]
    per_key = {}
    for r in keys.itertuples(index=False):
        key, legs = r[0], list(r[1:])
        if any(l not in W_of for l in legs):
            continue
        Wl = np.vstack([W_of[l] for l in legs])
        phi = sum(float(w) * Wl[j] for j, w in enumerate(weights))
        Ms = [M_of[l] for l in legs]
        a, b, k = (start_of[legs[0]], start_of[legs[1]], start_of[legs[-1]])
        near = int(((eff_arr > a) & (eff_arr <= b)).sum())
        far = int(((eff_arr > b) & (eff_arr <= k)).sum())
        span_hi = end_of[legs[-1]]
        proj_any = bool(((eff_arr > a) & (eff_arr <= span_hi) & is_proj).any())
        per_key[key] = {
            "phi_sum": float(np.sum(phi)),
            "mtg_fly": float(sum(float(w) * m for w, m in zip(weights, Ms))),
            "mtg_front": Ms[0], "mtg_belly": Ms[1], "mtg_back": Ms[-1],
            "near_gap": near, "far_gap": far, "asym": abs(near - far),
            "proj_any": proj_any,
        }
    out = s[[date_col, "key"]].copy()
    tbl = pd.DataFrame.from_dict(per_key, orient="index")
    return out.merge(tbl, left_on="key", right_index=True, how="inner")


def calendar_tilted_fly(
    struct: pd.DataFrame, cal: pd.DataFrame, *, n_legs: int = 3,
    date_col: str = "as_of", scale: float = 100.0, min_dm: float = 0.5,
    max_tilt: float = 0.35,
) -> Dict[str, pd.DataFrame]:
    """Remove the butterfly a **locally uniform** policy path would print.

    Using only the structure's own two wings, the average jump per effective
    meeting between them is ``pace = (r_back - r_front) / dM`` with
    ``dM = M_back - M_front``. The butterfly that pace implies is
    ``phi_sum * pace``, so::

        fly_adj = (2 r_b - r_f - r_k) - phi * (r_k - r_f) / dM
                = 2 r_b - (1 - phi/dM) r_f - (1 + phi/dM) r_k

    The weights still sum to zero, so this is **still a butterfly** -- a
    calendar-tilted one, with wing shares ``(1 -/+ phi/dM) / 2``. Nothing is
    fitted and nothing is estimated from history: ``phi`` and ``dM`` are
    arithmetic on the meeting calendar, known years ahead.

    With ``sd(phi) ~ 0.135`` and ``dM ~ 4`` the tilt moves the wing split by
    about +/-0.034 around 0.5. That is the same order as the fitted
    level-neutral split the prior lab measured (0.463 / 0.537) and could not
    explain, which is a claim this returns the ingredients to test.

    ``max_tilt`` caps ``|phi/dM|`` so a near-degenerate ``dM`` cannot turn the
    package into something that is no longer recognisably a butterfly; ``min_dm``
    drops those rows outright. Both are reported in the returned ``'tilt'``
    frame rather than applied silently.

    Returns ``{'level', 'tilt', 'front_share', 'phi'}`` as wide ``date x key``
    frames, ``level`` in bp.
    """
    s = struct.copy()
    s[date_col] = pd.to_datetime(s[date_col])
    c = cal.copy()
    c[date_col] = pd.to_datetime(c[date_col])
    m = s[[date_col, "key", "leg0_value", "leg1_value", f"leg{n_legs-1}_value"]].merge(
        c[[date_col, "key", "phi_sum", "mtg_front", "mtg_back"]],
        on=[date_col, "key"], how="inner")

    dM = (m["mtg_back"] - m["mtg_front"]).astype(float)
    tilt = (m["phi_sum"] / dM.where(dM.abs() >= float(min_dm))).clip(
        -float(max_tilt), float(max_tilt))
    f = m["leg0_value"].astype(float)
    b = m["leg1_value"].astype(float)
    k = m[f"leg{n_legs-1}_value"].astype(float)
    m["_lvl"] = (2.0 * b - (1.0 - tilt) * f - (1.0 + tilt) * k) * float(scale)
    m["_tilt"] = tilt
    m["_fs"] = (1.0 - tilt) / 2.0

    def wide(col):
        return m.pivot_table(index=date_col, columns="key", values=col,
                             aggfunc="first").sort_index()

    return {"level": wide("_lvl"), "tilt": wide("_tilt"),
            "front_share": wide("_fs"), "phi": wide("phi_sum")}
