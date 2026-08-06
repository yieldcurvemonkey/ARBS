"""Three ways to express the same view, compared on carry per unit of vega.

* TWO_LEG      -- the plain DV01-neutral forward flattener.
* FLY_HEDGED   -- the flattener plus a received 1y-forward 2-7-30 fly at PCA
                  weights, which neutralises residual level/slope exposure and
                  can flip theta positive: long far-dated vega, short near
                  gamma, a calendar built from delta instruments. It needs
                  disciplined wing hedges, and the wings cost money.
* SAME_SECTOR  -- 15y5y/20y10y, both legs inside the ultra-long sector, so no
                  fly leg is needed and the market is tighter.

The metric is carry per unit of vega, reported next to the residual factor
exposure. A construction that wins on carry while still carrying PC1 has not
won; it has changed the question.

**"After costs" is not one number, and this module says so rather than picking
one.** The brief calls the metric "carry per unit of vega AFTER costs" while
specifying, in its own test block, the cost-free
``daily_roll_usd / (|beta| * spread_dv01)``. Both cannot be true: carry is a
rate per day and a round trip is a one-off, and netting them requires a HOLDING
PERIOD, which this study has not established. So both forms are reported:

* :func:`carry_per_vega` -- the brief's formula, cost-free, the column named
  ``carry_per_vega``;
* :func:`carry_per_vega_after_costs` -- the round trip amortised over an
  explicit ``holding_days``, the column ``carry_per_vega_after_costs``, which
  is NaN unless a holding period is passed.

The cost-free number is never the whole answer here. On real curves the fly
improves the daily roll by $59.5 and costs $33,501 more to put on and take off,
so its carry advantage does not repay its own spread until roughly day 563.

**How much of H9 this module can actually test, stated up front.**

* "Neutralises residual level/slope exposure" is *partly* checkable and, as
  specified, partly false by construction. The 2-7-30 fly is BPV-neutral (each
  wing carries half the belly's BPV, opposite sign -- the constraint
  ``_solve_fly_ls_pca`` enforces), and it is a **one-parameter** family: one
  free scalar ``a``, three legs pinned to it. One scalar can zero at most one
  linear functional of the residual, so the fly cannot generally zero both PC1
  and PC2. What it does is minimise the PCA-metric norm of the residual along
  its own single direction. Both components are therefore reported side by
  side and neither is asserted to be zero. See
  :func:`fly_hedge_weights`.
* **Whatever this module concludes about "the fly" is about H9's NAMED fly.**
  ``solve_best_n_leg_hedge_pca`` does two things: it enumerates
  ``itertools.combinations(tenors, 3)`` and ranks the triples by residual PCA
  norm, and it solves each one. Only the SOLVE is reused here (see below), so
  the tenor SEARCH is not run. A verdict from this module is therefore "this
  fly, at these tenors, fails" -- never "no fly can do it". Restoring the
  ranking over triples needs a solver-free ladder for each candidate, which
  this module now has; it was simply not in scope for H9, which names the
  structure.
* "Flips theta positive" is checkable and is checked -- ``daily_roll_usd`` is
  repriced for the flattener and for the fly legs on the same curve roll
  (:func:`legs_roll_usd`, pinned against ``greeks.daily_roll_usd``).
* "The market is tighter" for the same-sector pair is **not modelled here**,
  because nothing in this study has measured it. ``cost_bp_round_trip``
  charges every construction at the same per-unit-of-traded-DV01 rate, so
  SAME_SECTOR is given no cost credit it has not earned. If a measured
  sector-tightness discount ever arrives, pass it as a ``CostSchedule`` per
  construction rather than hard-coding a prior here.

**Why this does not call** ``rl_swap_risk_ladder_utils.solve_best_n_leg_hedge_pca``
**end to end, and what it reuses instead.** That function was read first and
driven against this package's own curve objects before anything here was
written. Two stages of it are unreachable from here, measured rather than
assumed:

* ``ladder_from_pkg`` is ``rl.Portfolio(pkg).delta(solver=solver)``, and with
  ``solver=None`` rateslib raises ``AttributeError: 'NoneType' object has no
  attribute 'fx'`` (``instruments/protocols/pricing.py``). It needs a
  calibrated ``rl.Solver``. ``RLIRSwapCurve`` carries none -- its
  ``_rl_curve_solver_handle`` is commented out -- which is the same reason
  ``greeks`` bumps and reprices instead of calling ``curve.dv01``.
* ``build_unit_bpv_basis`` resolves ``IRSwapQuery`` packages against
  ``pricer_or_curve``, and handed the bare ``rl.Curve`` handle it raises
  ``AttributeError: 'Curve' object has no attribute 'reference_date'``. It
  also only builds SPOT outrights, not the 1y-forward legs H9 names.

Adopting a ``Solver`` to reach them would put a **second, different DV01
measure** into this package -- exactly the divergence ``greeks.build_leg``'s
docstring exists to prevent (sizing on one measure while checking neutrality
on another lets a directional residual into what is meant to be a pure
convexity package). So the ladder is built here in the package's own repriced
measure (:func:`key_rate_ladder`), and the *solver* -- the part that is
actually a solver -- is reused verbatim: ``_build_pca_metric_matrix`` for the
metric ``G`` and ``_solve_fly_ls_pca`` for the constrained least squares. No
new optimiser is written here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import rateslib as rl

from RVUtils.StrikelessVol import greeks as _greeks
from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.universe import ALL_PAIRS, ForwardLeg, ForwardPair, tenor_years
from RVUtils.rl_swap_risk_ladder_utils import _build_pca_metric_matrix, _solve_fly_ls_pca

__all__ = [
    "CONSTRUCTIONS",
    "FLY_HEDGED",
    "HEDGED_FACTORS",
    "LADDER_BUMP_BP",
    "SAME_SECTOR",
    "Shocks",
    "TWO_LEG",
    "UNIT_LEG_DV01_USD",
    "build_shocks",
    "carry_per_vega",
    "carry_per_vega_after_costs",
    "compare_constructions",
    "cost_bp_round_trip",
    "factor_exposures",
    "fly_hedge_weights",
    "key_rate_ladder",
    "ladder_tenor_years",
    "legs_roll_usd",
    "pca_metric",
    "same_sector_pair",
]

TWO_LEG = "two_leg"
FLY_HEDGED = "fly_hedged"
SAME_SECTOR = "same_sector"

#: The three constructions, in the order :func:`compare_constructions` reports
#: them. TWO_LEG is first because it is the incumbent every other row has to
#: beat, not because it is expected to win.
CONSTRUCTIONS = (TWO_LEG, FLY_HEDGED, SAME_SECTOR)

#: Key-rate bump size, in bp. A central difference at +/-1bp, the same size
#: and the same units ``greeks._reprice_dv01`` uses, so a ladder and a DV01
#: are directly comparable rather than approximately so.
LADDER_BUMP_BP: float = 1.0

#: DV01 each unit hedge basis leg is sized to. The solver's weights come back
#: as multiples of this, so it cancels out of the weights; it is here so the
#: basis ladder ``B`` is in dollars rather than in an unnamed unit.
UNIT_LEG_DV01_USD: float = 100_000.0

#: How many components the fly is solved against by default. Two -- level and
#: slope -- because that is the pair H9 names. See :func:`pca_metric` for why
#: this is not simply "all of them": at uniform weights the PCA metric is the
#: identity and the hedge stops being a PCA hedge at all.
HEDGED_FACTORS: int = 2


def carry_per_vega(*, daily_roll_usd: float, beta: float, spread_dv01: float) -> float:
    """Dollars of daily carry per dollar of vega.

    vega$ ~ |beta| * spread DV01, where ``beta`` is the pair's ROLLING
    changes-regression beta on vol -- never a global constant, because every
    coefficient in this study is regime-local.
    """
    vega = abs(float(beta)) * abs(float(spread_dv01))
    if vega == 0.0:
        return float("nan")
    return float(daily_roll_usd) / vega


def carry_per_vega_after_costs(
    *,
    daily_roll_usd: float,
    beta: float,
    spread_dv01: float,
    cost_bp_round_trip: float,
    holding_days: float,
    package_dv01_usd: float = 100_000.0,
) -> float:
    """The same number with the round trip amortised over ``holding_days``.

    ``(daily_roll_usd - cost_usd / holding_days) / (|beta| * spread_dv01)``,
    where ``cost_usd = cost_bp_round_trip * package_dv01_usd``.

    **The holding period is required and has no default**, because there is no
    honest one. Carry is a rate per day, a round trip is a one-off, and the
    ratio between them is entirely a function of how long the book is held --
    which is exactly the quantity this study has not established. A default
    would turn a modelling assumption into a printed number. The brief's
    "carry per unit of vega AFTER costs" is this function; the brief's own
    formula, and :func:`carry_per_vega`, is the cost-free one. Both are
    reported.

    ``holding_days <= 0`` is NaN, not infinite cost: a position held for no
    time has no carry either, and the ratio is undefined rather than terrible.
    """
    h = float(holding_days)
    if not (h > 0.0):
        return float("nan")
    cost_usd = float(cost_bp_round_trip) * abs(float(package_dv01_usd))
    return carry_per_vega(
        daily_roll_usd=float(daily_roll_usd) - cost_usd / h,
        beta=beta,
        spread_dv01=spread_dv01,
    )


# --------------------------------------------------------------- the ladder


def ladder_tenor_years(pca_model) -> pd.Series:
    """The PCA model's columns as a strictly increasing grid of years.

    The ladder basis IS ``pca_model.columns``, in that order, because
    ``pca_model.loadings`` is indexed by them and every projection below is a
    plain ``L.T @ x``. Column labels may be bare tenors (``"30Y"``) or the
    full instrument labels ``fit_curve_pca_from_timeseries`` produces
    (``"USD-OIS 30Y OUTRIGHT RATE"``); the tenor is the second whitespace
    field, or the whole label when there is only one.

    Parsed with :func:`universe.tenor_years`, **not** with
    ``df_based_pca_risk_model._tenor_to_years``. The latter maps ``1D`` to
    ``1/252`` and ``1W`` to ``7/252`` -- business-day counts, which its own
    docstring says are "good enough for sorting columns". They are not good
    enough for a tent grid, whose knot positions have to be real year
    fractions on the same clock as the curve's node times. For ``1Y`` and
    longer -- everything this package's ladders actually use -- the two agree
    exactly.

    Three refusals, all fail-closed, because each failure mode produces a
    plausible-looking ladder rather than an error:

    * a label that does not parse (the grid would silently lose a knot);
    * a non-increasing grid (``fit_curve_pca_from_timeseries`` sorts by tenor
      only when ``sort_by_tenor=True``, and an unsorted model would make the
      tents overlap backwards and the ladder meaningless);
    * ``loadings.index`` not equal to ``columns`` (``L.T @ x`` would then
      silently pair each loading with the wrong bucket).
    """
    cols = list(pca_model.columns)
    if not cols:
        raise ValueError("pca_model has no columns, so there is no ladder basis")
    years = []
    for col in cols:
        parts = str(col).split()
        label = parts[1] if len(parts) >= 2 else str(col)
        try:
            years.append(tenor_years(label))
        except ValueError as exc:
            raise ValueError(
                f"pca_model column {col!r} does not carry a parseable tenor "
                f"(read {label!r}). The ladder basis is the model's own "
                "columns, so an unparseable label is a missing knot, not a "
                "cosmetic problem."
            ) from exc
    arr = np.asarray(years, dtype=float)
    if not np.all(np.diff(arr) > 0.0):
        raise ValueError(
            f"pca_model columns are not strictly increasing in tenor: {years}. "
            "The tent basis needs a monotone grid; fit the model with "
            "sort_by_tenor=True (the default) or reorder the columns."
        )
    if list(pca_model.loadings.index) != cols:
        raise ValueError(
            "pca_model.loadings.index does not match pca_model.columns, so a "
            "loadings-transpose projection would pair each component with the "
            "wrong ladder bucket"
        )
    scales = getattr(pca_model, "scales", None)
    if scales is not None and not np.allclose(np.asarray(scales, dtype=float), 1.0):
        raise ValueError(
            "pca_model was fitted with matrix='corr' (non-unit `scales`). "
            "`_build_pca_metric_matrix` builds G = L diag(w) L^T from the "
            "LOADINGS ALONE and never reads `scales`, so the metric would be "
            "in standardised units while the ladder is in dollars -- a silent "
            "unit mismatch, not a small one. Fit with matrix='cov'."
        )
    return pd.Series(arr, index=pd.Index(cols, name="bucket"), name="tenor_years")


def _tent_matrix(node_years: np.ndarray, grid_years: np.ndarray) -> np.ndarray:
    """``(n_nodes, K)`` triangular weights whose rows sum to exactly 1.

    Knot ``k`` gets weight 1 at ``grid[k]`` and falls linearly to 0 at its
    neighbours; the first and last knots extend flat beyond the ends of the
    grid. Rows summing to one is the load-bearing property: it makes the sum
    of the K bucket shocks exactly a parallel shock, so ``ladder.sum()`` is a
    parallel DV01 by construction rather than by luck, which is what
    ``test_ladder_sums_to_the_parallel_dv01`` checks.
    """
    n, k = len(node_years), len(grid_years)
    w = np.zeros((n, k), dtype=float)
    for i, u in enumerate(node_years):
        if u <= grid_years[0]:
            w[i, 0] = 1.0
        elif u >= grid_years[-1]:
            w[i, -1] = 1.0
        else:
            j = int(np.searchsorted(grid_years, u, side="right") - 1)
            span = grid_years[j + 1] - grid_years[j]
            frac = (u - grid_years[j]) / span
            w[i, j] = 1.0 - frac
            w[i, j + 1] = frac
    return w


def _shock_handle(handle, node_dates, node_years, weights, bump_bp: float):
    """``handle`` with its zero rates moved by ``bump_bp * weights``.

    Built as ``rl.CompositeCurve([handle, tent])`` rather than by rebuilding
    the node dict, because rebuilding **loses the source curve's spline**. The
    GS Quant curves this study prices on are log-cubic splines
    (``interpolator.spline`` is populated); re-instantiating ``rl.Curve`` from
    their nodes drops it and moves an off-node discount factor by 5.8e-4
    relative -- measured on the real 2026-07-31 USD-OIS curve, at a 20y point.
    That is a 0.06% error in the very thing being differenced, and it is
    silent.

    Composition instead reproduces rateslib's own ``Curve.shift``: for a flat
    (all-ones) tent at 1bp, ``CompositeCurve([handle, tent])`` and
    ``handle.shift(1.0)`` agree to 3e-10 relative on the same real curve.
    """
    scale = float(bump_bp) * 1e-4
    tent_nodes = {
        d: float(np.exp(-scale * float(wi) * float(u)))
        for d, u, wi in zip(node_dates, node_years, weights)
    }
    tent = rl.Curve(
        nodes=tent_nodes,
        convention=handle.meta.convention,
        calendar=handle.meta.calendar,
        modifier=handle.meta.modifier,
        id="sv_tent",
    )
    return rl.CompositeCurve([handle, tent])


@dataclass(frozen=True)
class Shocks:
    """Prebuilt ``(up, down)`` curve handles, carrying the bump they were built at.

    The bump travels WITH the handles rather than being passed again alongside
    them. ``key_rate_ladder`` divides by ``2 * bump_bp``, so a caller who built
    shocks at 5bp and then asked for a ladder at the default 1bp would get every
    bucket scaled by five, silently and in the right shape. Carrying the number
    on the object makes that unrepresentable rather than merely unlikely.
    """

    bump_bp: float
    pairs: list

    def __len__(self) -> int:
        return len(self.pairs)


def build_shocks(curve, tenor_grid: pd.Series, *, bump_bp: float = LADDER_BUMP_BP) -> Shocks:
    """The ``2K`` shocked curve handles a ladder needs, built once.

    Returned as a :class:`Shocks` carrying ``(up, down)`` pairs in the grid's
    own order. Repricing every instrument against one prebuilt set is what keeps
    :func:`compare_constructions` from rebuilding the same curves three times.
    """
    handle = curve.handle()
    dcf = _greeks.daily_dcf(handle)
    ref = pd.Timestamp(handle.nodes.initial)
    node_dates = list(handle.nodes.nodes)
    node_years = np.array(
        [(pd.Timestamp(d) - ref).days * dcf for d in node_dates], dtype=float
    )
    tents = _tent_matrix(node_years, np.asarray(tenor_grid, dtype=float))
    return Shocks(
        bump_bp=float(bump_bp),
        pairs=[
            (
                _shock_handle(handle, node_dates, node_years, tents[:, k], +bump_bp),
                _shock_handle(handle, node_dates, node_years, tents[:, k], -bump_bp),
            )
            for k in range(tents.shape[1])
        ],
    )


def key_rate_ladder(
    curve,
    instruments: Sequence[Any],
    *,
    tenor_grid: pd.Series,
    bump_bp: float = LADDER_BUMP_BP,
    shocks=None,
) -> pd.Series:
    """Dollars per bp of each ladder bucket, by bump-and-reprice.

    One central difference per bucket, at the same ``+/-1bp`` and in the same
    repriced measure as ``greeks._reprice_dv01`` -- so a ladder and a package
    DV01 are the same kind of number, and ``ladder.sum()`` ties out against
    ``greeks.package_dv01`` rather than merely resembling it (measured: a
    single 10y10y leg sized to $100,000 of shift-DV01 gives $100,010.74 summed
    over a full-grid ladder, 1.1e-4 relative -- the continuous-vs-discrete
    compounding of the two bump conventions, and second order in the bump).

    **The bucket shock is a zero-rate tent, and the PCA must be fitted on zero
    rates too. This is not a second-order caveat.** A risk ladder is a gradient
    with respect to whatever variable was bumped, and ``factor_exposures``
    computes ``L^T x``, which is ``dPV/d(PC score)`` ONLY if ``L`` and ``x``
    are gradients in the same variable. Pairing par-fitted loadings with this
    zero-rate ladder is not "working in par coordinates" -- it is a mismatch.
    The par-to-zero Jacobian is essentially triangular for a key-rate
    decomposition (a 30y par rate depends on every zero out to 30y), nothing
    like the identity.

    Measured, and the reason an earlier version of this docstring calling the
    gap "second order in curve shape" was wrong: on 116 real month-end USD-OIS
    curves the solved fly's own DIRECTION flips with the choice -- belly
    received on 116/116 dates against zero-fitted loadings, PAID on 116/116
    against par-fitted ones. A sign flip in the derived hedge on every date in
    the sample is not second order.

    **Adopting par coordinates requires a par-rate ladder as well** -- bump each
    grid par swap rate and re-solve, or apply ``J = dz/dp`` and project
    ``J^T x``. Neither is implemented here and neither was attempted; this
    module is coherent in zero coordinates and inconsistent in any other, and
    that is a limit rather than a preference.
    """
    if shocks is None:
        shocks = build_shocks(curve, tenor_grid, bump_bp=bump_bp)
    elif float(shocks.bump_bp) != float(bump_bp):
        raise ValueError(
            f"prebuilt shocks were bumped at {shocks.bump_bp}bp but this ladder "
            f"was asked for at {bump_bp}bp. The central difference divides by "
            "the bump, so every bucket would be scaled by the ratio -- in the "
            "right shape, with the right signs, and wrong by a constant factor."
        )
    insts = list(instruments)
    vals = []
    for up, dn in shocks.pairs:
        pv_up = sum(float(i.npv(curves=up).real) for i in insts)
        pv_dn = sum(float(i.npv(curves=dn).real) for i in insts)
        vals.append((pv_up - pv_dn) / (2.0 * float(shocks.bump_bp)))
    return pd.Series(vals, index=tenor_grid.index, name="dv01_usd")


def factor_exposures(pca_model, ladder: pd.Series) -> pd.Series:
    """``L.T @ ladder`` -- the position's dollars per bp of each component.

    Deliberately **not** ``pca_model.transform``. ``transform`` subtracts the
    fitted mean before projecting, which is right for a curve snapshot and
    wrong for a risk vector: it destroys the homogeneity that makes an
    exposure an exposure. A flat zero position would report a non-zero PC1,
    and doubling a package would not double its PC1. Both are pinned by
    ``test_factor_exposures_are_linear_in_the_position`` and
    ``test_a_zero_ladder_has_zero_factor_exposure``.

    Same projection ``_build_pca_projection`` uses inside the hedge solver
    (``S = W^{1/2} L^T`` at unit weights), so the exposures reported here and
    the norm the solver minimises are the same object seen twice.
    """
    x = pd.Series(ladder).reindex(pca_model.columns)
    if x.isna().any():
        raise ValueError(
            "ladder does not cover every pca_model column: missing "
            f"{sorted(x.index[x.isna()])}"
        )
    scores = pca_model.loadings.values.T @ x.to_numpy(dtype=float)
    return pd.Series(scores, index=pca_model.loadings.columns, name="factor_dv01_usd")


# ------------------------------------------------------------------ the fly


def pca_metric(pca_model, *, pca_weights=None, n_factors: int = HEDGED_FACTORS) -> np.ndarray:
    """``G = L diag(w) L^T``, with the degenerate uniform case refused.

    **Uniform weights make G the identity, and that is not a small
    approximation -- it is the PCA doing nothing at all.** ``eigh`` returns an
    orthonormal ``L``, so ``L I L^T = I`` exactly, and a hedge advertised as
    "PCA-neutralising" would in fact be plain unweighted least squares on the
    raw dollar ladder. Measured on this module's own fixture before the guard
    existed: ``target_pca_norm`` 478,545 against the plain Euclidean norm of
    the same ladder, 478,517 -- the same number, and the fly removed 0.16% of
    it. That is the signature of a metric that is not a metric.

    ``_build_pca_metric_matrix`` never reads ``pca_weights=None`` as anything
    but ones, so the default here is **not** ``None``: it is
    ``w = [1]*n_factors + [0]*rest``, which makes ``G`` the orthogonal
    projector onto the first ``n_factors`` components. Minimising ``x^T G x``
    is then literally "minimise the level and slope exposure of the residual",
    which is the claim H9 makes.

    Pass ``pca_weights`` explicitly to weight differently (e.g. by eigenvalue);
    the identity refusal still applies, because it is about what the metric
    does, not about how it was asked for.
    """
    K = pca_model.loadings.shape[1]
    if pca_weights is None:
        n = int(n_factors)
        if not 1 <= n <= K:
            raise ValueError(f"n_factors must be in 1..{K}, got {n_factors}")
        w = np.zeros(K, dtype=float)
        w[:n] = 1.0
    else:
        w = np.asarray(pca_weights, dtype=float)
    G = _build_pca_metric_matrix(pca_model, w)
    if np.allclose(G, np.eye(K), atol=1e-8):
        raise ValueError(
            "the PCA metric came back as the identity, so this hedge would be "
            "plain unweighted least squares on the dollar ladder while "
            "reporting itself as PCA-neutralising. `eigh` gives an orthonormal "
            "L, so L diag(w) L^T = I whenever w is all-ones -- which is exactly "
            f"what `_build_pca_metric_matrix` does for uniform weights. Weights: "
            f"{np.asarray(w).round(4).tolist()}. Pass n_factors (default "
            f"{HEDGED_FACTORS}) or non-uniform pca_weights."
        )
    return G


def _refuse_legs_past_the_curve(curve, legs, fly_tenors, fly_fwd) -> None:
    """Refuse a fly whose longest leg matures beyond the curve's last node.

    **The default H9 structure over-runs a real USD curve by a year.** A
    1y-forward 30y wing matures at 31 years; the GS Quant USD-OIS curve's final
    node is 30 years out (measured: reference 2026-07-31, final node
    2056-08-04), and USD publishes no 31y instrument -- the same fact that
    keeps ``10y10y/25y10y`` out of ``universe.USD_PAIRS`` by construction.
    Pricing it anyway means extrapolating past the last quote and then hedging
    against the extrapolation.

    Checked on the BUILT swaps' own maturity dates rather than on a
    ``fwd + tail`` year count, because a year count needs a day-count
    convention to compare against a node date and would be approximately right
    at exactly the boundary this guard exists to police. Use wings that fit
    (e.g. ``("2Y", "7Y", "29Y")`` at ``fly_fwd="1Y"``) and say so in the
    write-up, rather than quietly extrapolating.
    """
    final = pd.Timestamp(curve.handle().nodes.final)
    over = [
        (t, pd.Timestamp(_greeks._as_dt(curve.maturity_date(leg))))
        for t, leg in zip(fly_tenors, legs)
    ]
    over = [(t, m) for t, m in over if m > final]
    if over:
        raise ValueError(
            f"fly leg(s) {[t for t, _ in over]} at fwd {fly_fwd!r} mature "
            f"{[m.date().isoformat() for _, m in over]}, beyond the curve's "
            f"final node {final.date().isoformat()}. Pricing them extrapolates "
            "past the last quoted point and the hedge would be solved against "
            "that extrapolation. Choose wings that fit inside the curve."
        )


def fly_hedge_weights(
    curve,
    package,
    *,
    pca_model,
    fly_tenors: Sequence[str] = ("2Y", "7Y", "30Y"),
    fly_fwd: str = "1Y",
    pca_weights=None,
    n_factors: int = HEDGED_FACTORS,
    unit_leg_dv01_usd: float = UNIT_LEG_DV01_USD,
    shocks=None,
) -> dict:
    """PCA-neutralising weights for a 1y-forward 2-7-30 fly against ``package``.

    The basis is three 1y-forward par swaps, each sized to
    ``+unit_leg_dv01_usd`` of PAYER repriced DV01 by ``greeks.build_leg``, so
    the returned ``weights_bpv`` are signed dollars per bp per leg and the
    unit cancels. ``_solve_fly_ls_pca`` then solves

        min_a (r + B (a q))^T G (r + B (a q)),
        q = [-0.5 d1/d0, 1, -0.5 d1/d2]

    -- the classic wing-BPV = half-belly-BPV fly -- with ``G = L diag(w) L^T``
    from ``_build_pca_metric_matrix``. Both are imported, not reimplemented.

    **Whether the fly is received or paid is an output, not an input.** H9
    names a *received* fly; the sign is determined by the package's own
    residual ladder and is reported as ``belly_direction``. Forcing it would
    make the hedge an assertion rather than a solution.

    **One scalar, so at most one functional zeroed.** ``a`` is the only free
    number: three legs, two BPV constraints. The residual's PC1 and PC2 are
    therefore both reported, and ``residual_pca_norm`` against
    ``target_pca_norm`` says how much of the *whole* PCA-metric risk the fly
    removed. A caller reading only PC2 and concluding "level and slope are
    neutralised" is reading a number this function cannot deliver.
    """
    grid = ladder_tenor_years(pca_model)
    if shocks is None:
        shocks = build_shocks(curve, grid)
    fly_tenors = tuple(fly_tenors)
    if len(fly_tenors) != 3:
        raise ValueError(
            f"a fly is three legs; got {len(fly_tenors)}: {fly_tenors}. "
            "`_solve_fly_ls_pca`'s wing/belly constraint is defined for n=3 "
            "only and falls back to a generic BPV-neutral solve otherwise."
        )

    target_legs = [package.short, package.long]
    r = key_rate_ladder(curve, target_legs, tenor_grid=grid, shocks=shocks)

    unit_legs = [
        _greeks.build_leg(
            curve, ForwardLeg(fly_fwd, t), dv01_usd=unit_leg_dv01_usd, direction=+1
        )
        for t in fly_tenors
    ]
    _refuse_legs_past_the_curve(curve, unit_legs, fly_tenors, fly_fwd)
    basis = [
        key_rate_ladder(curve, [leg], tenor_grid=grid, shocks=shocks)
        for leg in unit_legs
    ]
    B = np.column_stack([b.to_numpy(dtype=float) for b in basis])
    d = B.sum(axis=0)
    G = pca_metric(pca_model, pca_weights=pca_weights, n_factors=n_factors)
    w = _solve_fly_ls_pca(B, r.to_numpy(dtype=float), d, G)

    hedge_ladder = pd.Series(B @ w, index=grid.index, name="dv01_usd")
    residual = r + hedge_ladder
    legs = {
        t: _greeks.build_leg(
            curve,
            ForwardLeg(fly_fwd, t),
            dv01_usd=float(wk) * unit_leg_dv01_usd,
            direction=+1,
        )
        for t, wk in zip(fly_tenors, w)
    }
    weights_bpv = {t: float(wk) * unit_leg_dv01_usd for t, wk in zip(fly_tenors, w)}
    return {
        "fly_tenors": fly_tenors,
        "fly_fwd": str(fly_fwd),
        "unit_weights": {t: float(wk) for t, wk in zip(fly_tenors, w)},
        "weights_bpv": weights_bpv,
        "legs": legs,
        "basis_dv01_usd": {t: float(dk) for t, dk in zip(fly_tenors, d)},
        # w[1] is the belly. build_leg's direction=+1 pays fixed, so a negative
        # weight is a received belly.
        "belly_direction": "received" if w[1] < 0.0 else "paid",
        "target_ladder": r,
        "hedge_ladder": hedge_ladder,
        "residual_ladder": residual,
        "target_pc": factor_exposures(pca_model, r),
        "residual_pc": factor_exposures(pca_model, residual),
        "target_pca_norm": _pca_norm(G, r),
        "residual_pca_norm": _pca_norm(G, residual),
        "traded_dv01_usd": float(np.abs(list(weights_bpv.values())).sum()),
    }


def _pca_norm(G: np.ndarray, ladder: pd.Series) -> float:
    """``sqrt(x^T G x)`` -- the objective ``_solve_fly_ls_pca`` minimises.

    **The square root is load-bearing and is pinned as an identity, not as an
    inequality.** At the default metric ``G`` is the orthogonal projector onto
    the first ``n_factors`` components and ``L`` is orthonormal, so
    ``_pca_norm(G, x) == hypot(*factor_exposures(model, x)[:n_factors])``
    exactly. Found by a reviewer's mutation: dropping the ``sqrt`` left all 59
    tests green -- both tests that touched this were a ratio and an inequality
    -- while turning the published headline "the fly removes 5.3% of the
    level+slope norm" into 10.2%, because the reported cut is
    ``residual/target`` and ``0.9475**2 = 0.8978``. A number that reaches a
    write-up has to be pinned by an equality somewhere. See
    ``test_the_pca_norm_is_the_hypotenuse_of_the_hedged_components``, which
    doubles as an independent check that ``G`` really is that projector.
    """
    x = ladder.to_numpy(dtype=float)
    return float(np.sqrt(max(float(x @ (G @ x)), 0.0)))


# ------------------------------------------------------------------- carry


def legs_roll_usd(curve, instruments: Sequence[Any], *, next_date) -> float:
    """Carry+roll to ``next_date`` for an arbitrary list of legs, in dollars.

    Exactly ``greeks.daily_roll_usd``'s mechanic -- ``rl.Curve.roll`` slides
    the curve's shape forward while the instruments' own cashflow dates stay
    put -- generalised off ``greeks.Package``, which only holds two legs and
    cannot carry a fly. Pinned to reproduce ``greeks.daily_roll_usd`` to the
    cent on ``[package.short, package.long]`` by
    ``test_legs_roll_reproduces_the_package_roll``, so the two can never drift
    into two different roll conventions.
    """
    handle = curve.handle()
    insts = list(instruments)
    base = sum(float(i.npv(curves=handle).real) for i in insts)
    rolled_handle = handle.roll(next_date)
    rolled = sum(float(i.npv(curves=rolled_handle).real) for i in insts)
    return rolled - base


def cost_bp_round_trip(
    leg_dv01_usd: Sequence[float],
    *,
    schedule: CostSchedule | None = None,
    package_dv01_usd: float = 100_000.0,
) -> float:
    """Round-trip cost in bp of package DV01, from measured traded risk.

    ``CostSchedule`` charges ``initiate_bp`` once against
    ``replication``'s ``initiate_dv01_usd``, which ``simulate`` records as the
    whole package's DV01 -- i.e. the study's convention is that the standard
    TWO-LEG package costs ``initiate_bp`` one way. Two legs at $100k each is
    $200k of traded risk, so the implied rate is ``initiate_bp / 2`` per unit
    of traded leg DV01, and

        round trip = 2 * (initiate_bp / 2) * sum|leg dv01| / package dv01
                   = initiate_bp * sum|leg dv01| / package dv01

    which returns exactly ``2 * initiate_bp`` for the two-leg package -- 1.75bp
    at the default schedule -- and scales a fly by the risk it actually trades
    rather than by a per-leg flat fee. The fly's weights are a solver output,
    so its cost is measured here, not assumed.

    No sector-tightness discount is applied to any construction; see the module
    docstring.
    """
    sched = CostSchedule() if schedule is None else schedule
    traded = float(np.abs(np.asarray(list(leg_dv01_usd), dtype=float)).sum())
    return float(sched.multiplier) * float(sched.initiate_bp) * traded / abs(float(package_dv01_usd))


# --------------------------------------------------------- the comparison


def same_sector_pair(pair: ForwardPair, pairs: Sequence[ForwardPair] = ALL_PAIRS) -> ForwardPair:
    """The 15y5y/20y10y pair in ``pair``'s own market.

    Both legs end inside the ultra-long sector, which is the whole point of
    the construction: no fly leg is needed to keep the package in one sector.
    Raises rather than falling back to ``pair`` itself -- a SAME_SECTOR row
    that is secretly the TWO_LEG row is the failure mode this study has
    already seen once, in a placebo leg that reproduced the real number
    because it ran on the real contexts.
    """
    for cand in pairs:
        if cand.market == pair.market and cand.short.label == "15Y5Y" and cand.long.label == "20Y10Y":
            return cand
    raise ValueError(
        f"no 15Y5Y/20Y10Y pair for market {pair.market!r} in the supplied "
        "universe, so the SAME_SECTOR construction has nothing to compare"
    )


def _beta_for(beta, construction: str) -> float:
    if isinstance(beta, Mapping):
        if construction not in beta:
            raise ValueError(
                f"beta has no entry for construction {construction!r}; got "
                f"{sorted(beta)}"
            )
        return float(beta[construction])
    return float(beta)


def compare_constructions(
    curve,
    pair: ForwardPair,
    *,
    pca_model,
    beta,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
    next_date=None,
    schedule: CostSchedule | None = None,
    fly_tenors: Sequence[str] = ("2Y", "7Y", "30Y"),
    fly_fwd: str = "1Y",
    pca_weights=None,
    n_factors: int = HEDGED_FACTORS,
    same_sector: ForwardPair | None = None,
    holding_days: float | None = None,
) -> pd.DataFrame:
    """One row per construction: carry per vega, beside the risk it still runs.

    **A scalar ``beta`` is almost always the wrong call for this table, and it
    fails silently.** ``carry_per_vega``'s denominator is ``|beta| * spread
    DV01``; with one scalar and one sizing constant that denominator is the
    SAME NUMBER on every row, and the whole per-unit-of-vega normalisation --
    the reason the brief chose this metric, so that differently-sized
    constructions could be compared -- collapses into a rescaled roll. Measured
    on this study's own comparison: USD 10Y10Y/20Y10Y has beta -0.4373 while
    USD 15Y5Y/20Y10Y has **-0.2644** (60% of it, and 73% of the gamma). Lending
    the first pair's beta to the second turned "same-sector bleeds 38.6% less
    per unit of vega, on 99.1% of dates" into "1.6% MORE, on 62.1%" -- a sign
    flip in the headline. **Pass a ``{construction: beta}`` mapping whenever any
    row is a different pair**, which is always true of SAME_SECTOR.

    A scalar is still accepted, because FLY_HEDGED shares TWO_LEG's pair and a
    two-row comparison genuinely has one beta; it is echoed in the ``beta``
    column so a reader can see which rows share one.

    ``holding_days`` turns on ``carry_per_vega_after_costs``; without it that
    column is NaN, because netting a one-off round trip against a daily carry
    needs a holding period this study has not established. See the module
    docstring.

    ``beta`` is the pair's rolling changes-regression coefficient of the spread
    on vol. A scalar is applied to every row and echoed in the ``beta`` column,
    so a reader can see that one pair's beta was used for another pair's
    construction; pass a ``{construction: beta}`` mapping to give SAME_SECTOR
    its own. There is no default beta and there will not be one -- every
    coefficient in this study is regime-local.

    ``next_date`` defaults to exactly one CALENDAR day forward, matching
    ``greeks.compute_greeks``: a business-day step would make the dollar roll,
    and the carry-per-vega built on it, jump by the size of the weekend.

    Rank on ``carry_per_vega`` **with** ``residual_pc1``/``residual_pc2`` in
    view. A construction that wins on carry while carrying PC1 has changed the
    question, not answered it. No Sharpe is computed here, deliberately: both
    of this study's placebo pairs out-Sharpe every real pair while running the
    opposite carry sign.
    """
    grid = ladder_tenor_years(pca_model)
    shocks = build_shocks(curve, grid)
    G = pca_metric(pca_model, pca_weights=pca_weights, n_factors=n_factors)
    if next_date is None:
        next_date = curve.reference_date() + pd.Timedelta(days=1)
    sched = CostSchedule() if schedule is None else schedule
    sector = same_sector_pair(pair) if same_sector is None else same_sector

    rows = []

    def _row(name: str, this_pair: ForwardPair, legs, ladder: pd.Series, leg_dv01s):
        pcs = factor_exposures(pca_model, ladder)
        roll = legs_roll_usd(curve, legs, next_date=next_date)
        b = _beta_for(beta, name)
        cost_bp = cost_bp_round_trip(
            leg_dv01s, schedule=sched, package_dv01_usd=package_dv01_usd
        )
        return {
            "construction": name,
            "pair": this_pair.name,
            "n_legs": len(legs),
            "carry_per_vega": carry_per_vega(
                daily_roll_usd=roll, beta=b, spread_dv01=package_dv01_usd
            ),
            "carry_per_vega_after_costs": (
                float("nan")
                if holding_days is None
                else carry_per_vega_after_costs(
                    daily_roll_usd=roll,
                    beta=b,
                    spread_dv01=package_dv01_usd,
                    cost_bp_round_trip=cost_bp,
                    holding_days=holding_days,
                    package_dv01_usd=package_dv01_usd,
                )
            ),
            "daily_roll_usd": roll,
            "beta": b,
            "spread_dv01": float(package_dv01_usd),
            "residual_pc1": float(pcs.iloc[0]),
            "residual_pc2": float(pcs.iloc[1]),
            "residual_pca_norm": _pca_norm(G, ladder),
            "net_dv01_usd": float(ladder.sum()),
            "traded_dv01_usd": float(np.abs(np.asarray(leg_dv01s, dtype=float)).sum()),
            "cost_bp_round_trip": cost_bp,
        }

    pkg = _greeks.build_package(curve, pair, package_dv01_usd=package_dv01_usd, sign=sign)
    base_ladder = key_rate_ladder(
        curve, [pkg.short, pkg.long], tenor_grid=grid, shocks=shocks
    )
    base_dv01s = [pkg.short_dv01, pkg.long_dv01]
    rows.append(_row(TWO_LEG, pair, [pkg.short, pkg.long], base_ladder, base_dv01s))

    fly = fly_hedge_weights(
        curve,
        pkg,
        pca_model=pca_model,
        fly_tenors=fly_tenors,
        fly_fwd=fly_fwd,
        pca_weights=pca_weights,
        n_factors=n_factors,
        shocks=shocks,
    )
    fly_legs = list(fly["legs"].values())
    rows.append(
        _row(
            FLY_HEDGED,
            pair,
            [pkg.short, pkg.long] + fly_legs,
            fly["residual_ladder"],
            base_dv01s + list(fly["weights_bpv"].values()),
        )
    )

    sec_pkg = _greeks.build_package(
        curve, sector, package_dv01_usd=package_dv01_usd, sign=sign
    )
    sec_ladder = key_rate_ladder(
        curve, [sec_pkg.short, sec_pkg.long], tenor_grid=grid, shocks=shocks
    )
    rows.append(
        _row(
            SAME_SECTOR,
            sector,
            [sec_pkg.short, sec_pkg.long],
            sec_ladder,
            [sec_pkg.short_dv01, sec_pkg.long_dv01],
        )
    )

    out = pd.DataFrame(rows).set_index("construction").reindex(list(CONSTRUCTIONS))
    out.attrs.update(
        {
            "fly": fly,
            "reference_date": curve.reference_date(),
            "next_date": next_date,
            "schedule": sched,
            "n_factors": int(n_factors),
            "pca_weights": pca_weights,
            "holding_days": holding_days,
            # True when every row shares one beta -- i.e. when carry_per_vega
            # is a rescaled roll rather than a per-vega comparison.
            "shared_beta": not isinstance(beta, Mapping),
            # `residual_pca_norm` is sqrt(x^T G x) with G the projector onto
            # the first `n_factors` components -- NOT a whole-ladder norm.
            "sector_tightness_modelled": False,
        }
    )
    return out
