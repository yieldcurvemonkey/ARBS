"""Place one session's SR3 risk-neutral density on the copula (lambda) coordinate.

The ZQ strip fixes the marginal hike probability at each FOMC meeting. The SR3 option
surface prices the law of the day-weighted sum. Marginals fix ``E[K]`` and say nothing about
``Var(K)``, so what is left over is the coupling -- see :mod:`._copula` for the coordinate
itself. This module is the measurement: it turns (ZQ settles, FOMC calendar, one BL density)
into a :class:`LambdaMeasurement`.

Naming: the ``lambda`` here is the COPULA coordinate. It is unrelated to
:mod:`._lambda_opt`, whose lambda is the Breeden-Litzenberger smoothing parameter. The two
never appear in the same namespace on purpose.

Conventions this module commits to, because the repo carries two and mixing them is worth
about 0.8bp of implied jump per meeting:

* An FOMC ``effective_date`` from ``load_fomc_schedule`` is treated as the FIRST day at the
  new rate, matching :func:`.._fedwatch.build_fedwatch_tree`. It is NOT advanced by a
  business day. ``BT.serff.mechanics.fomc_effective_date`` takes the other view; do not mix
  a weight from there with a jump from here.
* Marginals are anchored on months with no meeting, so no marginal is read off a month whose
  average is itself contaminated by a partial-month jump.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from RVUtils.SR3ZQDistributionScreener._copula import (
    CouplingBounds,
    coupling_bounds,
    lambda_from_statistic,
    sum_variance,
    wing_mass,
)

__all__ = [
    "MeetingSet",
    "LambdaMeasurement",
    "build_meeting_set",
    "atom_rates_percent",
    "observed_atom_probabilities",
    "density_modes",
    "measure_lambda",
    "MOVE_SIZE_BP",
]

#: One policy step. The SR3 lattice spacing is this, in bp of rate.
MOVE_SIZE_BP = 25.0

#: Peak prominence for mode detection, as a fraction of the density maximum. Reported as
#: colour only: the peak COUNT is threshold-dependent, which is exactly why lambda_wing --
#: threshold-free -- is the headline statistic and this is not.
_MODE_PROMINENCE_FRAC = 0.05


@dataclass(frozen=True)
class MeetingSet:
    """The FOMC meetings an SR3 contract's option resolves, and the ones it only drifts on.

    ``marginals`` are the probabilities of the *extra* 25bp step beyond a certain
    ``char_25bp`` baseline, which is how ``MeetingNode`` reports them. Writing the meeting as
    "``char`` certain steps plus a Bernoulli" keeps the framework valid in a cutting cycle:
    the certain part shifts the lattice, the Bernoulli part is what the coupling acts on.
    """

    as_of: datetime.date
    symbol: str
    spot_effr_pct: float

    resolved_labels: Tuple[str, ...]
    resolved_effective: Tuple[datetime.date, ...]
    resolved_marginals: Tuple[float, ...]
    resolved_char_25bp: Tuple[int, ...]
    resolved_weights: Tuple[float, ...]
    resolved_step_signs: Tuple[int, ...]

    unresolved_labels: Tuple[str, ...]
    unresolved_weights: Tuple[float, ...]
    unresolved_expected_bp: Tuple[float, ...]

    window_start: datetime.date
    window_end: datetime.date
    expiry: datetime.date

    jumps: Tuple["MeetingJump", ...] = ()

    @property
    def n_resolved(self) -> int:
        return len(self.resolved_labels)

    @property
    def step_sign(self) -> int:
        """+1 when every uncertain resolved step is a hike, -1 when every one is a cut.

        0 means the set is mixed. A mixed set has no scalar move COUNT -- the atoms are no
        longer equally spaced -- so the atom framework does not apply and callers must say so
        rather than silently summing signed steps.
        """
        signs = {s for s, p in zip(self.resolved_step_signs, self.resolved_marginals) if p > 1e-9}
        if not signs:
            return 1
        return signs.pop() if len(signs) == 1 else 0

    @property
    def all_weights_unit(self) -> bool:
        """True when every resolved meeting is fully accrued inside the reference window.

        The move COUNT is only a sufficient statistic when this holds: with unit weights
        every ORDERING of the same number of moves lands on one settlement rate, so the
        ``2**k`` paths collapse to ``k + 1`` atoms. With a fractional weight they do not, and
        a lambda read off the atoms would be measuring the calendar, not the coupling.
        """
        return all(abs(w - 1.0) < 1e-9 for w in self.resolved_weights)

    @property
    def certain_shift_bp(self) -> float:
        """The deterministic part of the lattice: certain steps plus unresolved drift."""
        certain = MOVE_SIZE_BP * float(sum(self.resolved_char_25bp))
        drift = float(sum(w * e for w, e in zip(self.unresolved_weights, self.unresolved_expected_bp)))
        return certain + drift


@dataclass(frozen=True)
class LambdaMeasurement:
    """One session, one contract, placed on the lambda coordinate."""

    as_of: datetime.date
    symbol: str
    ok: bool
    reason: str = ""

    marginals: Tuple[float, ...] = ()
    expected_k: float = float("nan")

    # Lattice geometry
    atom_rates_pct: Tuple[float, ...] = ()
    atom_prices: Tuple[float, ...] = ()
    basis_bp: float = float("nan")
    zq_window_rate_pct: float = float("nan")
    sr3_forward_rate_pct: float = float("nan")

    # Observed law of K
    observed_atoms: Tuple[float, ...] = ()
    observed_atoms_strict: Tuple[float, ...] = ()
    off_lattice_below: float = float("nan")
    off_lattice_above: float = float("nan")

    # The coordinate
    wing_observed_raw: float = float("nan")
    wing_observed_renorm: float = float("nan")
    wing_observed_absorbed: float = float("nan")
    wing_comonotone: float = float("nan")
    wing_independent: float = float("nan")
    wing_min_variance: float = float("nan")
    lambda_wing_raw: float = float("nan")
    lambda_wing_renorm: float = float("nan")
    lambda_wing: float = float("nan")
    lambda_atoms: Tuple[float, ...] = ()
    lambda_atom_spread: float = float("nan")

    var_observed_bp2: float = float("nan")
    var_comonotone_bp2: float = float("nan")
    var_independent_bp2: float = float("nan")
    var_min_variance_bp2: float = float("nan")
    lambda_var: float = float("nan")
    lambda_var_sensitivity: float = float("nan")
    non_meeting_var_bp2: float = float("nan")
    basis_var_share: float = float("nan")
    hard_violation_bp2: float = float("nan")

    # Shape colour
    n_modes: int = -1
    mode_prices: Tuple[float, ...] = ()
    trough_peak_ratio: float = float("nan")

    # Fit quality -- a lambda from a broken fit is not a measurement
    forward_residual_bp: float = float("nan")
    pre_normalization_mass: float = float("nan")
    ghost_mass_fraction: float = float("nan")
    strike_source: str = ""
    n_strikes: int = -1

    lp_feasible: bool = False
    lp_status: str = ""

    def to_row(self) -> Dict[str, object]:
        row: Dict[str, object] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, tuple):
                row[key] = list(value)
            else:
                row[key] = value
        return row


@dataclass(frozen=True)
class MeetingJump:
    """One meeting's implied jump, and which ZQ contract paid for it."""

    label: str
    effective: datetime.date
    level_start_pct: float
    level_end_pct: float
    jump_bp: float
    char_25bp: int
    marginal: float
    step_sign: int
    solved_from: str
    consistency_residual_bp: float = float("nan")


def clean_anchored_jumps(
    *,
    zq_prices: Dict[str, float],
    fomc_effectives: Sequence[datetime.date],
    months: Sequence[Tuple[int, int]],
) -> List[MeetingJump]:
    """Per-meeting implied jumps, anchored on months that contain no meeting.

    A month with no meeting carries a flat EFFR, so its ZQ contract reads the level directly
    with nothing to disentangle. Those months are the anchors. A meeting month is then solved
    from the NEXT month's clean level whenever there is one, and only falls back to its own
    partial-month average when the following month also holds a meeting.

    That ordering is the whole point. Reading a meeting month off its own contract mixes the
    jump with the pre-meeting level, and for October -- 4 of 31 days at the new rate -- the
    27/31 lever amplifies any error in the assumed starting level by a factor of about seven.
    Solving October from November's clean average instead costs nothing and is exact.
    ``consistency_residual_bp`` records what the discarded equation would have said, which is
    the same residual the V/X/F fly reconstruction reports.
    """
    by_month: Dict[Tuple[int, int], datetime.date] = {}
    for eff in fomc_effectives:
        key = (eff.year, eff.month)
        if key in by_month:
            raise ValueError(f"two FOMC meetings inside {key}; the month equation is underdetermined")
        by_month[key] = eff

    avg: Dict[Tuple[int, int], float] = {}
    for y, m in months:
        price = zq_prices.get(_zq_symbol(y, m))
        if price is not None and math.isfinite(price):
            avg[(y, m)] = 100.0 - float(price)

    ordered = list(months)
    start_idx = next(
        (i for i, k in enumerate(ordered) if k not in by_month and k in avg),
        None,
    )
    if start_idx is None:
        raise ValueError("no meeting-free month with a ZQ price to anchor on")

    level = avg[ordered[start_idx]]
    out: List[MeetingJump] = []
    for i in range(start_idx, len(ordered)):
        key = ordered[i]
        eff = by_month.get(key)
        if eff is None:
            if key in avg:
                level = avg[key]  # re-anchor: a clean month IS the level
            continue

        days_total = _days_in_month(*key)
        n_before = (eff - datetime.date(key[0], key[1], 1)).days
        n_after = days_total - n_before

        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        clean_next = nxt is not None and nxt not in by_month and nxt in avg
        if clean_next:
            end = avg[nxt]
            solved_from = f"next clean month {_zq_symbol(*nxt)}"
            residual = float("nan")
            if key in avg and days_total > 0:
                implied_avg = (n_before * level + n_after * end) / days_total
                residual = (implied_avg - avg[key]) * 100.0
        else:
            if key not in avg or n_after <= 0:
                continue
            end = (avg[key] * days_total - n_before * level) / n_after
            solved_from = f"own contract {_zq_symbol(*key)}"
            residual = float("nan")

        jump_bp = (end - level) * 100.0
        steps = jump_bp / MOVE_SIZE_BP
        char = int(math.floor(abs(steps)))
        marginal = abs(steps) - char
        out.append(
            MeetingJump(
                label=f"{datetime.date(key[0], key[1], 1):%b%y}".lower(),
                effective=eff,
                level_start_pct=level,
                level_end_pct=end,
                jump_bp=jump_bp,
                char_25bp=char * (1 if jump_bp >= 0 else -1),
                marginal=marginal,
                step_sign=1 if jump_bp >= 0 else -1,
                solved_from=solved_from,
                consistency_residual_bp=residual,
            )
        )
        level = end
    return out


def _zq_symbol(year: int, month: int) -> str:
    return f"ZQ{'FGHJKMNQUVXZ'[month - 1]}{year % 100:02d}"


def _days_in_month(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]


def _month_range(start: datetime.date, horizon_months: int) -> List[Tuple[int, int]]:
    base = start.year * 12 + (start.month - 1)
    return [((base + k) // 12, (base + k) % 12 + 1) for k in range(horizon_months + 1)]


def build_meeting_set(
    *,
    as_of: datetime.date,
    symbol: str,
    zq_prices: Dict[str, float],
    fomc_schedule,
    expiry: datetime.date,
    horizon_months: int = 12,
) -> MeetingSet:
    """Resolve the meeting structure behind one SR3 contract on one session.

    ``zq_prices`` maps full ZQ symbols to settle prices; ``fomc_schedule`` is the frame from
    ``SDRUtils.analytics.fomc.load_fomc_schedule`` verbatim.
    """
    import pandas as pd

    from BT.serff.mechanics import contract_window, fomc_window_weight

    window = contract_window(_sr3_symbol(symbol))
    months = _month_range(datetime.date(as_of.year, as_of.month, 1), horizon_months)
    lo = datetime.date(*months[0], 1)
    hi = datetime.date(*months[-1], 1)

    effectives = [
        d.date() if hasattr(d, "date") else d
        for d in pd.to_datetime(fomc_schedule["effective_date"])
    ]
    meetings = [d for d in effectives if lo <= d <= hi]

    jumps = clean_anchored_jumps(zq_prices=zq_prices, fomc_effectives=meetings, months=months)

    # The spot anchor is the first meeting-free month that actually has a price. Taking the
    # first meeting-free month regardless would KeyError on a thin strip, and defaulting it to
    # a meeting month would put a jump inside the level.
    meeting_months = {(e.year, e.month) for e in meetings}
    spot = float("nan")
    for key in months:
        if key in meeting_months:
            continue
        price = zq_prices.get(_zq_symbol(*key))
        if price is not None and math.isfinite(price):
            spot = 100.0 - float(price)
            break

    resolved: List[MeetingJump] = []
    resolved_weights: List[float] = []
    unresolved: List[Tuple[str, float, float]] = []
    for jump in jumps:
        weight = float(fomc_window_weight(window, jump.effective))
        if weight <= 0.0:
            continue  # entirely after the reference window: it cannot touch settlement
        if jump.effective <= expiry:
            resolved.append(jump)
            resolved_weights.append(weight)
        else:
            unresolved.append((jump.label, weight, jump.jump_bp))

    return MeetingSet(
        as_of=as_of,
        symbol=symbol,
        spot_effr_pct=spot,
        resolved_labels=tuple(j.label for j in resolved),
        resolved_effective=tuple(j.effective for j in resolved),
        resolved_marginals=tuple(j.marginal for j in resolved),
        resolved_char_25bp=tuple(j.char_25bp for j in resolved),
        resolved_weights=tuple(resolved_weights),
        resolved_step_signs=tuple(j.step_sign for j in resolved),
        unresolved_labels=tuple(u[0] for u in unresolved),
        unresolved_weights=tuple(u[1] for u in unresolved),
        unresolved_expected_bp=tuple(u[2] for u in unresolved),
        window_start=window.start,
        window_end=window.end,
        expiry=expiry,
        jumps=tuple(jumps),
    )


def _sr3_symbol(symbol: str) -> str:
    token = str(symbol).upper().strip()
    if token.startswith("SFR"):
        return "SR3" + token[3:]
    return token


def zq_implied_window_rate_pct(meeting_set: MeetingSet) -> float:
    """The ZQ strip's own expectation of the SR3 reference-window average rate, in percent.

    This is the number the SOFR-EFFR basis is measured against, so it carries every term the
    lattice carries: the certain steps, the expected number of uncertain ones, and the
    day-weighted drift from meetings that land inside the window but after option expiry.
    """
    expected_uncertain_bp = MOVE_SIZE_BP * float(sum(meeting_set.resolved_marginals))
    return meeting_set.spot_effr_pct + (meeting_set.certain_shift_bp + expected_uncertain_bp) / 100.0


def atom_rates_percent(
    meeting_set: MeetingSet,
    *,
    basis_bp: float,
    include_unresolved_drift: bool = True,
) -> np.ndarray:
    """Settlement-rate location of each move-count atom, in percent, ascending in ``k``.

    ``include_unresolved_drift=False`` reproduces the bare ``r0 + 25k + basis`` pin ladder;
    the default also carries the day-weighted expectation of meetings that fall inside the
    reference window but after option expiry (for SFRZ26 that is Jan-27 at 49/91 of the
    window, worth a couple of bp). It shifts every atom equally, so it moves the lattice, not
    its spacing -- but it moves it by more than the bucket edges tolerate.
    """
    n = meeting_set.n_resolved
    shift = MOVE_SIZE_BP * float(sum(meeting_set.resolved_char_25bp))
    if include_unresolved_drift:
        shift = meeting_set.certain_shift_bp
    base = meeting_set.spot_effr_pct + (shift + float(basis_bp)) / 100.0
    sign = meeting_set.step_sign or 1
    return base + sign * np.arange(n + 1, dtype=float) * MOVE_SIZE_BP / 100.0


def observed_atom_probabilities(
    bl_result,
    atom_rates_pct: Sequence[float],
    *,
    absorb_tails: bool = True,
) -> Tuple[np.ndarray, float, float]:
    """Bucket the BL density onto the move-count lattice, in ``k`` order.

    Returns ``(atom_probabilities, mass_below_lattice, mass_above_lattice)``. Buckets are
    the midpoints between adjacent atoms, extended by half a step at each end.

    ``absorb_tails=True`` folds the mass outside the lattice into the nearest end atom, so
    the result is a probability law on the same support as the copula bounds and the two are
    compared like for like. That mass is not a state -- the count cannot go below zero or
    above ``n`` -- it is the non-meeting diffusion the framework treats as a convolution
    kernel, and the nearest-atom assignment is where it came from. Set ``False`` to leave it
    outside, which is what the strict reading does; the strict wings are then biased LOW,
    because the end atoms leak outward while the interior atoms leak into their neighbours.
    Either way the returned tail masses are the raw, unabsorbed ones.

    Integration differences the CDF at the bucket edges. It never masks the density grid and
    applies a trapezoid rule: the mask drops the two partial intervals at the edges and
    returns exactly zero for any bucket that contains a single grid node.
    """
    rates = np.asarray(atom_rates_pct, dtype=float)
    if rates.size < 2:
        raise ValueError("need at least two atoms to build bucket edges")
    descending = rates[-1] < rates[0]
    ordered = rates[::-1] if descending else rates

    half = 0.5 * MOVE_SIZE_BP / 100.0
    edges = np.concatenate(
        [[ordered[0] - half], 0.5 * (ordered[:-1] + ordered[1:]), [ordered[-1] + half]]
    )

    grid = np.asarray(bl_result.strike_grid_rate, dtype=float)
    cdf = np.asarray(bl_result.rnd_cumulative, dtype=float)
    at_edges = np.interp(edges, grid, cdf, left=0.0, right=1.0)
    probs = np.diff(at_edges)
    below = float(at_edges[0])
    above = float(1.0 - at_edges[-1])

    if absorb_tails:
        probs = probs.copy()
        probs[0] += below
        probs[-1] += above

    if descending:
        probs = probs[::-1]
        below, above = above, below
    return probs, below, above


def density_modes(bl_result, *, prominence_frac: float = _MODE_PROMINENCE_FRAC):
    """Local maxima of the density, in PRICE space, plus the deepest trough-to-peak ratio.

    Returns ``(mode_prices, trough_peak_ratio, n_modes)``. ``trough_peak_ratio`` is the
    minimum density between the two tallest peaks divided by the smaller of them, so 1.0 is
    a flat shoulder and 0.0 is full separation; NaN when there is only one peak.

    Convolution with a log-concave kernel is variation-diminishing, so smoothing can only
    destroy modes and fill troughs. Observed bimodality therefore implies underlying
    bimodality; the converse does not hold, and a unimodal session does not refute a lattice.
    """
    from scipy.signal import find_peaks

    rates = np.asarray(bl_result.strike_grid_rate, dtype=float)
    density = np.asarray(bl_result.rnd_density, dtype=float)
    if density.size < 3 or not np.any(np.isfinite(density)):
        return (), float("nan"), 0

    peaks, _ = find_peaks(density, prominence=float(prominence_frac) * float(np.nanmax(density)))
    if peaks.size == 0:
        peaks = np.array([int(np.nanargmax(density))])

    mode_prices = tuple(float(100.0 - rates[i]) for i in peaks)

    ratio = float("nan")
    if peaks.size >= 2:
        order = np.argsort(density[peaks])[::-1]
        i, j = sorted((int(peaks[order[0]]), int(peaks[order[1]])))
        trough = float(np.min(density[i : j + 1]))
        ratio = trough / float(min(density[i], density[j]))
    return mode_prices, ratio, int(peaks.size)


def measure_lambda(
    *,
    meeting_set: MeetingSet,
    bl_result,
    sr3_forward_rate_pct: float,
    non_meeting_vol_bp_per_sqrt_year: Optional[float] = None,
    include_unresolved_drift: bool = True,
) -> LambdaMeasurement:
    """Place one session's density on the lambda coordinate.

    ``non_meeting_vol_bp_per_sqrt_year`` is the assumed annualised volatility of everything
    that is NOT a meeting step -- term premium, r*, SOFR-EFFR basis drift. It is not
    identified by anything here, which is precisely the weakness of the variance route, so
    ``lambda_var_sensitivity`` reports ``d lambda_var / d(that assumption)`` per bp/yr and
    should be read next to the number itself.
    """
    ms = meeting_set
    if ms.n_resolved < 2:
        return LambdaMeasurement(
            as_of=ms.as_of, symbol=ms.symbol, ok=False,
            reason=f"only {ms.n_resolved} resolved meeting(s); the coupling is not identified",
        )
    if not ms.all_weights_unit:
        return LambdaMeasurement(
            as_of=ms.as_of, symbol=ms.symbol, ok=False,
            reason=(
                "resolved meetings do not all carry day-weight 1 "
                f"({[round(w, 3) for w in ms.resolved_weights]}); the move count is not a "
                "sufficient statistic and an atom-based lambda would be measuring the calendar"
            ),
        )

    if ms.step_sign == 0:
        return LambdaMeasurement(
            as_of=ms.as_of, symbol=ms.symbol, ok=False,
            reason=(
                "resolved meetings mix hikes and cuts; the atoms are no longer equally spaced "
                "and there is no scalar move count for the coupling to act on"
            ),
        )

    bounds = coupling_bounds(ms.resolved_marginals)

    zq_rate = zq_implied_window_rate_pct(ms)
    basis_bp = (float(sr3_forward_rate_pct) - zq_rate) * 100.0
    rates = atom_rates_percent(ms, basis_bp=basis_bp, include_unresolved_drift=include_unresolved_drift)
    probs, below, above = observed_atom_probabilities(bl_result, rates, absorb_tails=True)
    strict, _, _ = observed_atom_probabilities(bl_result, rates, absorb_tails=False)

    wing_absorbed = wing_mass(probs)
    wing_strict = wing_mass(strict)
    on_lattice = float(np.sum(strict))
    wing_renorm = wing_strict / on_lattice if on_lattice > 0 else float("nan")

    # Cross-statistic lambda profile. Both the wing mass and every individual atom are LINEAR
    # along the mixture family, so a density that lies inside the family returns the same
    # lambda from each. The spread across atoms is the cross-strike inconsistency: the market
    # cannot be coupling at two rates at once, so a wide spread says the RND has left the
    # family and a single headline lambda is an average of things that disagree.
    atom_lambdas: List[float] = []
    for k in range(probs.size):
        span = float(bounds.probs_comonotone[k] - bounds.probs_independent[k])
        # The comonotone law puts almost nothing on interior atoms, so those denominators are
        # tiny and their lambda is numerically meaningless. Gate rather than emit noise.
        if abs(span) < 0.02:
            atom_lambdas.append(float("nan"))
            continue
        atom_lambdas.append(float((probs[k] - bounds.probs_independent[k]) / span))
    finite = [x for x in atom_lambdas if math.isfinite(x)]
    lambda_atom_spread = (max(finite) - min(finite)) if len(finite) >= 2 else float("nan")

    # --- variance route -------------------------------------------------------------
    # Everything in bp^2 of settlement rate.
    std_pct = float(getattr(bl_result, "std_rate", float("nan")))
    var_observed = (std_pct * 100.0) ** 2 if math.isfinite(std_pct) else float("nan")

    scale = MOVE_SIZE_BP ** 2
    var_com = bounds.var_comonotone * scale
    var_ind = bounds.var_independent * scale
    var_min = bounds.var_min_variance * scale

    tte = float(getattr(bl_result.input, "time_to_expiry", float("nan")))
    if non_meeting_vol_bp_per_sqrt_year is None or not math.isfinite(tte):
        non_meeting_var = float("nan")
    else:
        non_meeting_var = float(non_meeting_vol_bp_per_sqrt_year) ** 2 * max(tte, 0.0)

    var_meeting_observed = var_observed - non_meeting_var
    lam_var = lambda_from_statistic(
        var_meeting_observed, independent=var_ind, comonotone=var_com, min_variance=var_min
    )
    # d lambda / d(non-meeting vol), per bp/yr: d(var)/d(vol) = 2*vol*tte, over the span.
    sens = float("nan")
    if (
        non_meeting_vol_bp_per_sqrt_year is not None
        and math.isfinite(tte)
        and math.isfinite(var_meeting_observed)
    ):
        span = (var_com - var_ind) if var_meeting_observed >= var_ind else (var_ind - var_min)
        if abs(span) > 1e-12:
            sens = -2.0 * float(non_meeting_vol_bp_per_sqrt_year) * max(tte, 0.0) / span

    basis_share = (
        float(non_meeting_var / var_observed)
        if math.isfinite(non_meeting_var) and math.isfinite(var_observed) and var_observed > 0
        else float("nan")
    )

    hard = float("nan")
    if math.isfinite(var_meeting_observed):
        if var_meeting_observed > var_com:
            hard = var_meeting_observed - var_com
        elif var_meeting_observed < var_min:
            hard = var_meeting_observed - var_min
        else:
            hard = 0.0

    mode_prices, trough_peak, n_modes = density_modes(bl_result)

    return LambdaMeasurement(
        as_of=ms.as_of,
        symbol=ms.symbol,
        ok=True,
        marginals=ms.resolved_marginals,
        expected_k=bounds.expected_k,
        atom_rates_pct=tuple(float(x) for x in rates),
        atom_prices=tuple(float(100.0 - x) for x in rates),
        basis_bp=basis_bp,
        zq_window_rate_pct=zq_rate,
        sr3_forward_rate_pct=float(sr3_forward_rate_pct),
        observed_atoms=tuple(float(x) for x in probs),
        observed_atoms_strict=tuple(float(x) for x in strict),
        off_lattice_below=below,
        off_lattice_above=above,
        wing_observed_raw=wing_strict,
        wing_observed_renorm=wing_renorm,
        wing_observed_absorbed=wing_absorbed,
        wing_comonotone=bounds.wing_comonotone,
        wing_independent=bounds.wing_independent,
        wing_min_variance=bounds.wing_min_variance,
        lambda_wing_raw=bounds.lambda_wing(wing_strict),
        lambda_wing_renorm=bounds.lambda_wing(wing_renorm),
        lambda_wing=bounds.lambda_wing(wing_absorbed),
        lambda_atoms=tuple(atom_lambdas),
        lambda_atom_spread=lambda_atom_spread,
        var_observed_bp2=var_observed,
        var_comonotone_bp2=var_com,
        var_independent_bp2=var_ind,
        var_min_variance_bp2=var_min,
        lambda_var=lam_var,
        lambda_var_sensitivity=sens,
        non_meeting_var_bp2=non_meeting_var,
        basis_var_share=basis_share,
        hard_violation_bp2=hard,
        n_modes=n_modes,
        mode_prices=mode_prices,
        trough_peak_ratio=trough_peak,
        forward_residual_bp=float(getattr(bl_result, "forward_residual_bp", float("nan"))),
        pre_normalization_mass=float(getattr(bl_result, "pre_normalization_mass", float("nan"))),
        ghost_mass_fraction=float(getattr(bl_result, "ghost_mass_fraction", float("nan"))),
        strike_source=str(getattr(bl_result.input, "strike_source", "")),
        n_strikes=int(len(getattr(bl_result.input, "strikes_price", ()))),
        lp_feasible=bounds.lp_feasible,
        lp_status=bounds.lp_status,
    )
