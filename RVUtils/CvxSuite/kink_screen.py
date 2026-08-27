"""The kink-ledger screen: one row per KINK_GRID point, everything at bp/day.

C2 composition layer of the CvxSuite (docs/cvxsuite/DESIGN.md section 4;
schema: docs/convexityrv/kink_ledger.md section 6). This module composes the
C1 kernels — it prices nothing itself and re-derives nothing:

    grids       KINK_GRID / leg_label / k_coord / t1_t2 / classify_point
    residuals   convexity_adjustment_bp, adjusted_levels, xsec_residuals,
                walk_forward_pca_residuals, sign_agreement, fit_diagnostics
    vols        cube_atm_panel / cube_atm_bp_year / quoted_axes /
                realized_vol_bp_day / bp_year_to_day
    ou          calibrate_ou, fpt_sample, fpt_stats, p_fpt_exceeds,
                ou_conditional
    carry       carry_roll_bp (aged-rate identity, fly theta),
                leg_roll_bp (rolled-curve reprice, frontier abscissa)
    rent        package_gamma_usd + sigma_be_bp_day (composed here exactly as
                ``rent.rent_row`` composes them; the pieces are called
                directly so tests can plant the gamma — the task contract
                names the two pieces, not the wrapper)
    frontiers   daily_xfit + off_frontier (ING Fig 3/4 orientations)
    gates       support_gate (sigma_impl only — see below)
    books       classify_books over books.REQUIRED_COLUMNS, BookGates
    CurveFlyScreener.screener   Leg / Structure / neutral_weights

Row construction (binding conventions, in build order)
------------------------------------------------------
1.  **Convexity-adjusted levels.** ``adjusted = quoted + CA`` per point with
    ``CA = holee two-time form 0.5*sigma^2*t1*t2`` (bp), sigma read from the
    swaption cube at (expiry = fwd start, tail = tenor). The sigma HISTORY is
    read once as a ``cube_atm_panel`` over the leg-history dates
    (``cfg.ca_mode = "panel"``, the default and the honest choice: normal
    vols moved ~3x over 2019-2026 and a constant sigma writes today's vol
    regime into every historical fair curve). ``cfg.ca_mode = "latest"`` is
    the documented cheap fallback: ONE cube read at asof, the same sigma
    applied to every history date — z/OU then measure the raw curve plus a
    constant, and the CA's own vol-sensitivity (which at 30y10y/40y10y is
    material: d(CA) = sigma*t1*t2/1e4 bp per bp/yr of vol) is absent from
    the realized stats. CA sigma reads are CLAMPED at the day's quoted
    envelope (``clamp=True``): the support gate is deliberately NOT applied
    to the CA — a support-gated CA would NaN the whole 40y10y column and the
    ``xsec_residuals`` any-NaN-day rule would then erase EVERY day of the
    screen. The support gate governs ``sigma_impl_bp_day`` only, where
    40y10y is NaN BY DESIGN (expiry 40 > the cube's 30Y axis maximum).
    Missing cube days are forward-filled in SIGMA space up to
    ``cfg.ca_ffill_limit`` days (count reported in ``df.attrs``); beyond the
    limit the day's adjusted levels are NaN, never zero.
2.  **Residuals** on the ADJUSTED panel: per-day cross-sectional spline
    residual (``ks = grids.k_coord`` in column order, DESIGN section 6 knots
    (1,3,7,15,27) — 30y10y/40y10y sit on the cubic extension past the last
    knot with high leverage; ``fit_diagnostics`` is carried in ``df.attrs``
    so the CLI can print it) and the walk-forward 2-PC residual (window 756,
    monthly refits, loadings frozen strictly before each month).
    ``sign_agree``: +1 both cheap, -1 both rich, 0 disagree/small, NaN no
    data (residual > 0 = CHEAP, the CurvePCAModel convention).
3.  **Trailing stats at asof, per INTERIOR point, on the COMPOSED MICRO-FLY
    level** ``L_p(t) = 2*adj_belly(t) - adj_front(t) - adj_back(t)`` over
    the adjacent grid legs (bp; ``FLY_STATS_WEIGHTS``; windows end AT asof,
    inclusive; the asof composed level is printed as ``fly_bp``). The
    weights are the FIXED sum-zero rate-space fly ``(-1, +2, -1)`` — the
    pinned ``(-0.5, +1, -0.5)`` shape at the package's belly=+2 scale — so
    a common level move across the legs cancels EXACTLY: every trailing
    stat is duration-free BY CONSTRUCTION. (An outright level z is
    DURATION: on 2026-08-21 it put 15/17 points at z ~ +2 together and
    manufactured +23bp "dislocation edges" that were really "the belly is
    rich vs its own 3y level" — the recorded W4 failure mode, DESIGN
    section 0.) The belly=+2 scale is the one the theta/Gamma package pays
    ``cfg.dv01_usd`` dollars per bp of (exactly at same-tenor points; at
    tenor breaks to the printed ``w_sum`` annuity trim), so
    ``carry_bp_day`` and ``cfg.cost_bp`` are already denominated in this L;
    zs/pctl/half-life/p_hit are scale-invariant anyway.
    ``zs = (L_asof - mean_756)/std_756`` — POLARITY, pinned once in RATE
    space (kink_ledger section 0) and propagated to books and the QDB fade:
    positive = the fly level sits HIGH = the belly RATE is high vs the
    wings = the belly is CHEAP (an upward kink); the fade RECEIVES the
    belly (short local convexity — the side that collects rent). Negative
    = belly RICH; the fade PAYS the belly (long convexity, pays rent).
    Residual and zs polarities now AGREE: both are cheap-positive.
    ``pctl_3y`` = share of the trailing fly window at or below L_asof, in
    [0, 1]. OU fit (``calibrate_ou``) on the same 756-row fly tail.
    ENDPOINTS (spot 1y, 40y10y) have no adjacent fly: the whole stats
    block (fly_bp/zs/pctl/OU/FPT/e_rev/rev_drag) is NaN there and
    ``n_hist`` is 0. ``sigma_rlzd_bp_day`` DELIBERATELY stays the POINT's
    trailing std of daily diffs (bp/day, NOT annualised; ``ex_dates=None``
    — swap legs have no roll dates): sigma_BE is a breakeven on the
    PARALLEL curve shift, so ``be_over_rv`` needs a rate-level vol in its
    denominator, and a micro-fly's own level vol legitimately sits below
    the 0.5 bp/day units floor.
4.  **FPT** (H-S fn 24): target = halfway from the asof FLY level to the
    fly's OU mean; ``fpt_sample`` with the section-6 frozen config (sims 2000, steps
    504, dt 1.0, seed 20260826) and a FRESH ``default_rng(seed)`` PER POINT
    — common random numbers across the cross-section, deterministic and
    independent of point order. ``fpt_stats(hits, steps=cfg.fpt_steps)`` —
    the steps kwarg is REQUIRED by the ou contract whenever censoring
    occurs; ``e_fpt_d`` is biased LOW under censoring, so ``frac_censored``
    sits next to it. ``p_hit`` is the BOOK-CLOCK hit probability (DESIGN
    section 6a item 2): the fraction of MC paths hitting within
    ``cfg.max_hold_bd`` (63bd — the frozen dislocation exit), NOT within
    the 504-step cap; the cap-clock rate stays recoverable as
    ``1 - frac_censored``, and hit indices are read as business days under
    the frozen ``fpt_dt = 1.0`` (the same convention ``p_fpt_exceeds``
    consumes). ``e_rev_bp = |mu_L - L_asof| / 2`` is the FLY-level
    reversion the FPT clock measures — duration-free by construction, like
    every number derived from L. ``carry_be_days = e_rev_bp / |carry_bp_day|`` (the
    ING breakeven-horizon rule); a NON-NEGATIVE carry has no breakeven
    horizon — ``carry_be_days = inf`` and ``p_fpt_gt_carry_be = 0.0``,
    branched BEFORE ``p_fpt_exceeds`` (which returns NaN on non-finite
    days and would silently turn "no breakeven risk" into "unknown").
5.  **The micro-fly** at interior point i: legs (grid[i-1], grid[i],
    grid[i+1]), weights ``neutral_weights(pricer, legs, belly=1)`` — the
    DV01-neutral belly=+2 convention. ENDPOINTS (spot 1y, 40y10y) have no
    adjacent fly: every fly-derived column is NaN there and the books NaN
    refusal classifies them "none". Fly carry = ``carry_roll_bp`` (aged-rate
    identity) at ``cfg.carry_horizon_y``; the age-past-zero raise (the 1y1y
    fly's front leg is the SPOT 1y, which cannot age a full year) is caught
    PER ROW and retried at ``cfg.carry_horizon_fallback_y`` (0.25y — inside
    the spot-1y leg's life); the horizon actually used is printed in
    ``carry_horizon_y_used`` and the per-day normalisation divides by it
    (``carry_bp_day = CR_h / (252 * h)``). Still failing -> NaN, never a
    substituted zero.
6.  **Rent block, as-of only** (profiles are never run over history): the
    package is built ``pricer.build_irswap(fwd=..., tenor=...,
    bpv = w_i * cfg.dv01_usd)`` — the C1 rent recipe (bpv legs straight to
    the profile, NEVER ``resolve_pricable``: the bpv path already signs the
    notional). With bpv_i = w_i * D the package P&L is EXACTLY D dollars per
    bp of the neutral-weights fly level L = sum(w_i * r_i), so
    ``theta_usd_day = carry_bp_day * D`` is the package's own repriced daily
    carry and sigma_BE = sqrt(2|theta|/|Gamma|) is internally consistent.
    Documented caveat: this package's PARALLEL DV01 is D * sum(w_i)
    (``w_sum`` column) — zero only where adjacent unit DV01s match; at the
    tenor breaks (9y1y/10y2y/12y3y) it is material. The alternative
    (notionals proportional to w_i, exactly parallel-neutral) would price a
    package whose quoted level is NOT the L the carry describes, breaking
    theta/Gamma consistency — this trade-off is deliberate and printed.
    The screen prices the LONG-the-fly-level side (belly payer); sigma_BE
    is direction-symmetric, the harvest direction is the short side.
7.  **sigma_impl_bp_day**: cube ATM at (expiry = fwd, tail = tenor) as-of,
    support-gated per day against ``quoted_axes(asof)`` (the axes VARY BY
    DAY — never a hardcoded grid); converted bp/yr -> bp/day through the
    named converter. BOTH grid ends fail the gate BY DESIGN: 40y10y
    (expiry 40 > the 30Y axis maximum) and the SPOT 1y point (expiry 0 <
    the 1M axis minimum — there is no zero-expiry swaption; its CA is
    identically zero anyway since t1 = 0). Expect exactly two NaNs on a
    healthy day.
8.  **Frontiers** (as-of cross-section, 17 points): value-carry (y =
    residual_xsec, x = leg rolldown) and carry-vol (y = leg rolldown, x =
    sigma_impl bp/day). The rolldown abscissa is ``leg_roll_bp`` — the
    ROLLED-CURVE reprice, which prices spot legs too (the aged-rate identity
    cannot age the spot 1y by 1y), one consistent path across all 17 points;
    fit rows and the leg-roll path's forward-leg agreement with the identity
    (worst 0.44 bp measured) are in the carry module docstring. Off-frontier
    residuals: > 0 = cheap for its carry / carry-rich for its vol.
9.  **rac_net@FPT** (bp of L, defined precisely): ``rac_net = carry_bp_day
    * e_fpt_d + rev_drag_fpt_bp`` where ``rev_drag_fpt_bp = (mu_L - L_asof)
    * (1 - exp(-kappa_L * e_fpt_d))`` — the OU-expected move of the FLY
    level toward its own mean over the fly's FPT horizon
    (``ou_conditional``), signed for the LONG-the-fly-level holder. Both
    terms now describe ONE tradeable object; the only remaining gap is
    that ``carry_bp_day`` is repriced on the ``neutral_weights`` package,
    which equals the ``(-1, +2, -1)`` stats fly at same-tenor points (to
    ~2%) and differs at tenor breaks by the annuity trim (``w_sum``
    printed). Both NaN-propagate; endpoints are NaN throughout.
10. **edge_bp** (bp of L, net of ONE cost, on the BOOK'S OWN CLOCK — DESIGN
    section 6a item 2): ``e_rev_bp * p_hit - |carry_bp_day| *
    min(e_fpt_d, cfg.max_hold_bd) - cfg.cost_bp`` with ``p_hit`` the
    P(hit <= max_hold_bd) of item 4 and h = max_hold_bd = 63bd, the frozen
    dislocation exit. The pre-amendment edge credited reversion at the
    504bd cap and charged carry over the uncapped E[FPT] — pricing a
    hold-to-reversion trade the 63bd book cannot run (measured: 86/265
    gate rows and 3/23 episodes failed the hold-consistent gate, zero
    flipped in). Cost default 2.3 bp — the middle of the measured 2.0-2.6
    fly-package RT band; the package pays ``dv01_usd`` dollars per bp of
    L, so ``cost_bp = fee/dv01_usd`` is already in bp of L. e_rev and edge
    measure reversion of the FLY level to its own mean — duration-free by
    construction. NaN propagates (``np.minimum``, never Python ``min``, so
    a NaN e_fpt cannot silently become h); endpoints are NaN.
11. **book**: ``books.classify_books`` over the EXACT
    ``books.REQUIRED_COLUMNS`` (be_over_rv, zs, rac_net, sign_agree, tag,
    edge_bp) with ``cfg.gates`` (BookGates section-6 defaults). The harvest
    gates read the columns for the RECEIVE-belly side (DESIGN 6a item 5:
    ``-rac_net > min``, ``zs >= -max_z``) — the rac_net COLUMN stays
    long-the-level signed (item 9). be_over_rv = sigma_BE / sigma_rlzd —
    the fly-package PARALLEL-shift breakeven over the POINT's realized
    (rate-level) vol; this pairing is deliberate and stays (item 3), the
    one remaining cross-object ratio in the row.

Diagnostics travel in ``df.attrs`` (fit diagnostics/leverage, PCA info
summary, CA mode + ffill count, frontier fits, leg-roll errors) — the CLI
prints them as the ``=== GATE ... ===`` lines.

What this module does NOT do
----------------------------
* No aliveness claims and no entries — the books column labels screen rows
  (L-0088 stands; the dislocation book is machinery awaiting non-flow state
  data). QDB strategies re-derive entries at t-1.
* No vega: vol prices the rent; it is never the hedge pair (measured partial
  R^2 <= 0.044).
* Never ``resolve_pricable`` on package legs, never ``horizon_date`` into a
  payoff profile.  Carry comes from the repriced kernel here; since 2026-08-27
  ``CARRY_AND_ROLL_BPS_RUNNING`` agrees with it to 0.02 bp of MAE, but this
  module is not routed through it.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from Caching.swaption_cube_store import SwaptionCubeStore
from RVUtils.CurveFlyScreener.screener import Leg, Structure, neutral_weights
from RVUtils.CvxSuite import grids
from RVUtils.CvxSuite.books import REQUIRED_COLUMNS, BookGates, classify_books
from RVUtils.CvxSuite.carry import carry_roll_bp, leg_roll_bp
from RVUtils.CvxSuite.frontiers import daily_xfit, off_frontier
from RVUtils.CvxSuite.gates import support_gate
from RVUtils.CvxSuite.ou import (
    calibrate_ou,
    fpt_sample,
    fpt_stats,
    ou_conditional,
    p_fpt_exceeds,
)
from RVUtils.CvxSuite.rent import DEFAULT_SHIFTS_BP, package_gamma_usd, sigma_be_bp_day
from RVUtils.CvxSuite.residuals import (
    adjusted_levels,
    convexity_adjustment_bp,
    fit_diagnostics,
    sign_agreement,
    walk_forward_pca_residuals,
    xsec_residuals,
)
from RVUtils.CvxSuite.vols import (
    bp_year_to_day,
    cube_atm_bp_year,
    cube_atm_panel,
    quoted_axes,
    realized_vol_bp_day,
)

__all__ = ["KinkScreenCfg", "build_kink_screen", "SCREEN_COLUMNS",
           "FLY_STATS_WEIGHTS"]

BUSINESS_DAYS = 252.0

#: Fixed sum-zero rate-space weights of the composed stats fly
#: (front, belly, back): ``L = 2*belly - front - back`` in bp — the pinned
#: ``(-0.5, +1, -0.5)`` shape at the package's belly=+2 scale. Sum-zero is
#: load-bearing: it is what makes ``zs`` duration-free by construction (a
#: common level move across the three legs cancels EXACTLY). The theta/Gamma
#: package's ``neutral_weights`` differ from these at tenor breaks by the
#: annuity trim — that package-vs-stats gap is the printed ``w_sum`` column,
#: never hidden.
FLY_STATS_WEIGHTS: Tuple[float, float, float] = (-1.0, 2.0, -1.0)

#: Column order of the returned frame (index = leg label, name "point").
SCREEN_COLUMNS: Tuple[str, ...] = (
    "fwd", "tenor", "k_coord", "tag",
    "level_bp", "ca_bp", "adj_bp", "fly_bp",
    "residual_xsec", "residual_pca", "sign_agree",
    "zs", "pctl_3y", "n_hist",
    "ou_kappa", "ou_mu_bp", "half_life_d",
    "e_fpt_d", "p_hit", "frac_censored", "q50_fpt_d", "e_rev_bp",
    "carry_bp_day", "carry_horizon_y_used", "leg_roll_bp",
    "rev_drag_fpt_bp", "rac_net", "carry_be_days", "p_fpt_gt_carry_be",
    "w_front", "w_belly", "w_back", "w_sum", "w_pca_front", "w_pca_back",
    "gamma_usd_per_bp2", "theta_usd_day", "sigma_be_bp_day", "be_status",
    "sigma_impl_bp_day", "sigma_rlzd_bp_day", "be_over_rv",
    "off_value_carry", "off_carry_vol",
    "edge_bp", "book",
)


@dataclasses.dataclass(frozen=True)
class KinkScreenCfg:
    """Frozen screen config. Defaults are DESIGN.md section 6 verbatim where
    that section names a number; everything else is documented here.

    ``ca_mode``: "panel" (default — sigma history via one ``cube_atm_panel``
    read over the leg-history dates) or "latest" (constant asof sigma; the
    documented approximation — see the module docstring). An explicit
    ``sigma_panel_bp_year`` argument to :func:`build_kink_screen` overrides
    both.
    """

    # trailing stats (DESIGN section 6: z/pctl and OU on trailing 756)
    z_window: int = 756
    ou_window: int = 756
    stats_min_obs: int = 252          # below this the z/pctl/OU block is NaN
    # cross-sectional fit (DESIGN section 6)
    xsec_variant: str = "spline"
    xsec_knots: Tuple[float, ...] = (1.0, 3.0, 7.0, 15.0, 27.0)
    # walk-forward PCA (DESIGN section 6)
    n_pcs: int = 2
    pca_window: int = 756
    pca_min_window: int = 504
    pca_refit: str = "M"
    sign_min_abs_bp: float = 0.5
    # convexity adjustment
    ca_mode: str = "panel"            # "panel" | "latest"
    ca_ffill_limit: int = 5           # sigma-space ffill for missing cube days
    # fly carry / theta
    carry_horizon_y: float = 1.0
    carry_horizon_fallback_y: float = 0.25   # the meeting-zone shorter horizon
    frontier_roll_horizon: str = "1Y"        # leg_roll_bp grammar
    dv01_usd: float = 100_000.0
    shifts: Tuple[float, ...] = DEFAULT_SHIFTS_BP
    # realized vol (bp/day)
    rlzd_window: int = 252
    rlzd_min_periods: int = 100
    # FPT (DESIGN section 6 frozen: sims 2000, steps 504, seed 20260826)
    fpt_sims: int = 2000
    fpt_steps: int = 504
    fpt_dt: float = 1.0
    fpt_seed: int = 20260826
    # edge / books
    cost_bp: float = 2.3              # 1x package RT, middle of 2.0-2.6 band
    max_hold_bd: int = 63             # the frozen book's exit clock (DESIGN
                                      # section 6 max_hold; 6a item 2: p_hit
                                      # and the carry charge run on it)
    gates: BookGates = BookGates()
    frontier_min_n: int = 6
    # pricer sanity: |reference_date - asof| tolerance, calendar days
    max_ref_date_gap_d: int = 5


# ---------------------------------------------------------------------------
# helpers (module-level so tests can monkeypatch the composition seams)
# ---------------------------------------------------------------------------

def _store(cube_store):
    """The cube store to read from: the given one, else the default ONCE.

    Centralised so the default store is constructed a single time per build
    (``vols`` would otherwise construct one per read when passed ``None``)
    and so pure-logic tests can stub the store away entirely.
    """
    return cube_store if cube_store is not None else SwaptionCubeStore.default()


def _sigma_panel(hist_index: pd.DatetimeIndex, labels: Sequence[str],
                 points: Sequence[grids.KinkPoint], asof: pd.Timestamp,
                 store, cfg: KinkScreenCfg) -> Tuple[pd.DataFrame, int]:
    """date x point ATM sigma panel (bp/yr), columns = LEG labels.

    "panel": one ``cube_atm_panel`` read over the history dates (each day
    read once), clamped at the quoted envelope; missing days forward-filled
    in sigma space up to ``cfg.ca_ffill_limit`` (a vol surface is
    slow-moving; the fill count is returned, never hidden). "latest": one
    per-point read at asof broadcast to every date (documented fallback).
    Columns are RENAMED positionally from the cube's own "5yx10y" labels to
    the grid's leg labels — the order is the grid's, carried through both
    calls, and the rename is 1:1 by construction.
    """
    pts = [(float(p.fwd), float(p.tenor)) for p in points]
    if cfg.ca_mode == "panel":
        raw = cube_atm_panel(pts, list(hist_index), store=store, clamp=True)
        raw.columns = list(labels)   # positional: same order as `points`
        before = int(raw.notna().to_numpy().sum())
        filled = raw.ffill(limit=int(cfg.ca_ffill_limit))
        n_filled = int(filled.notna().to_numpy().sum()) - before
        return filled, n_filled
    if cfg.ca_mode == "latest":
        row = [cube_atm_bp_year(e, t, asof.date(), store=store, clamp=True)
               for e, t in pts]
        panel = pd.DataFrame([row] * len(hist_index), index=hist_index,
                             columns=list(labels))
        return panel, 0
    raise ValueError(f"unknown ca_mode {cfg.ca_mode!r}; use 'panel' or 'latest'")


def _ca_frame(sigma_bp_year: pd.DataFrame,
              points: Sequence[grids.KinkPoint]) -> pd.DataFrame:
    """Per-cell Ho-Lee two-time CA (bp) from the sigma panel.

    Column j uses ``t1_t2(points[j])``; every cell goes through the ONE
    formula home ``residuals.convexity_adjustment_bp`` (NaN sigma -> NaN CA,
    negative sigma raises loudly — a corrupt cube must not price quietly).
    """
    out = {}
    for lab, p in zip(sigma_bp_year.columns, points):
        t1, t2 = grids.t1_t2(p)
        out[lab] = [convexity_adjustment_bp(s, t1, t2)
                    for s in sigma_bp_year[lab].to_numpy(dtype=float)]
    return pd.DataFrame(out, index=sigma_bp_year.index,
                        columns=list(sigma_bp_year.columns))


def _fly_carry(pricer, structure: Structure, cfg: KinkScreenCfg,
               cache: Dict) -> Tuple[float, float]:
    """(carry_bp_day, horizon_used_y) with the age-past-zero raise caught.

    Tries ``cfg.carry_horizon_y`` then ``cfg.carry_horizon_fallback_y``
    (the spot-1y front leg of the 1y1y fly cannot age a full year — the
    aged-rate identity RAISES there by design); per-day normalisation
    divides by the horizon actually used. Both failing -> (NaN, NaN), never
    a substituted zero.
    """
    for h in (float(cfg.carry_horizon_y), float(cfg.carry_horizon_fallback_y)):
        try:
            cr = carry_roll_bp(pricer, structure, h, cache)
        except ValueError:
            continue
        return float(cr) / (BUSINESS_DAYS * h), h
    return float("nan"), float("nan")


def _pca_neutral_wings(loadings: Optional[pd.DataFrame], f: str, b: str,
                       k: str) -> Tuple[float, float]:
    """PC1/PC2-neutral wing weights (belly fixed at +2), or NaN.

    Solves ``w_f*V[f] + 2*V[b] + w_k*V[k] = 0`` over the first two PCs of
    the CURRENT refit's frozen loadings — the strategy sizing printed next
    to the DV01-neutral weights (DESIGN section 4: "the screen prints
    both"). Singular/ill-conditioned wing pair or absent loadings -> NaN.
    """
    if loadings is None or not {"PC1", "PC2"}.issubset(loadings.columns):
        return float("nan"), float("nan")
    try:
        A = np.array([[loadings.at[f, "PC1"], loadings.at[k, "PC1"]],
                      [loadings.at[f, "PC2"], loadings.at[k, "PC2"]]], dtype=float)
        rhs = -2.0 * np.array([loadings.at[b, "PC1"], loadings.at[b, "PC2"]],
                              dtype=float)
    except KeyError:
        return float("nan"), float("nan")
    if not (np.isfinite(A).all() and np.isfinite(rhs).all()):
        return float("nan"), float("nan")
    if np.linalg.cond(A) > 1e8:
        return float("nan"), float("nan")
    wf, wk = np.linalg.solve(A, rhs)
    return float(wf), float(wk)


def _trailing(series: pd.Series, window: int) -> pd.Series:
    """The last ``window`` rows up to and including the series end, no NaN."""
    return series.tail(int(window)).dropna()


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------

def build_kink_screen(asof, *, leg_hist_bp: pd.DataFrame, pricer: Any,
                      cube_store=None, cfg: Optional[KinkScreenCfg] = None,
                      sigma_panel_bp_year: Optional[pd.DataFrame] = None,
                      ) -> pd.DataFrame:
    """One row per KINK_GRID point as of ``asof`` — the kink-ledger screen.

    Parameters
    ----------
    asof : date-like — must be a row of ``leg_hist_bp`` (no lookahead: the
        history is truncated to ``index <= asof`` first; an absent asof
        raises naming the last available date).
    leg_hist_bp : date x leg-label frame in BP (lowercase CurveFlyScreener
        labels; every KINK_GRID label must be present).
    pricer : the as-of curve pricer (``IRSwapsMDP(source="CITIVELO_EXCEL")``
        offline). The store-backed assert (``meta().get("from_curve_store")``)
        belongs to the CALLER (the CLI does it); this function only checks
        the reference date sits within ``cfg.max_ref_date_gap_d`` of asof.
    cube_store : optional ``SwaptionCubeStore`` (default: the default store,
        constructed once).
    cfg : :class:`KinkScreenCfg` (default: the frozen section-6 config).
    sigma_panel_bp_year : optional date x point sigma panel in bp/yr with
        columns EXACTLY the grid leg labels — overrides ``cfg.ca_mode``
        (an explicit, spelled-out injection seam for precomputed panels and
        tests; never a silent fallback).

    Returns the 17-row frame (:data:`SCREEN_COLUMNS`, index name "point",
    grid order) with diagnostics in ``df.attrs``: ``fit_diag`` (leverage),
    ``pca_info`` (last refit month key, cos_prev, explained), ``ca_mode`` /
    ``ca_cells_ffilled``, ``frontier_value_carry`` / ``frontier_carry_vol``
    fit rows, ``leg_roll_errors``, ``asof``, ``cost_bp``, ``max_hold_bd``.
    """
    cfg = cfg or KinkScreenCfg()
    asof = pd.Timestamp(asof).normalize()
    points = list(grids.KINK_GRID)
    labels = [grids.leg_label(p) for p in points]
    ks = [grids.k_coord(p) for p in points]

    # ---- input discipline -------------------------------------------------
    missing = [c for c in labels if c not in leg_hist_bp.columns]
    if missing:
        raise ValueError(f"leg_hist_bp is missing KINK_GRID columns {missing}")
    if not isinstance(leg_hist_bp.index, pd.DatetimeIndex):
        raise TypeError("leg_hist_bp needs a DatetimeIndex")
    hist = leg_hist_bp.loc[leg_hist_bp.index <= asof, labels].copy()
    if len(hist) == 0:
        raise ValueError(f"leg history has no rows at or before {asof.date()}")
    if asof not in hist.index:
        raise ValueError(
            f"asof {asof.date()} is not a leg-history date; last available is "
            f"{hist.index[-1].date()}")
    ref = pd.Timestamp(pricer.reference_date()).normalize()
    if abs((ref - asof).days) > int(cfg.max_ref_date_gap_d):
        raise ValueError(
            f"pricer reference date {ref.date()} is {abs((ref - asof).days)} "
            f"calendar days from asof {asof.date()} (max "
            f"{cfg.max_ref_date_gap_d}) - wrong pricer for this screen date")

    # sigma_impl always reads the cube (quoted_axes), so the store is
    # resolved once regardless of the CA sigma source; tests stub _store.
    store = _store(cube_store)

    # ---- 1. convexity-adjusted panel --------------------------------------
    if sigma_panel_bp_year is not None:
        bad = [c for c in labels if c not in sigma_panel_bp_year.columns]
        if bad:
            raise ValueError(
                f"sigma_panel_bp_year is missing grid columns {bad}")
        sig = sigma_panel_bp_year.reindex(index=hist.index)[labels].astype(float)
        n_ffilled = 0
        ca_mode_used = "injected"
    else:
        sig, n_ffilled = _sigma_panel(hist.index, labels, points, asof, store, cfg)
        ca_mode_used = cfg.ca_mode
    ca = _ca_frame(sig, points)
    adj = adjusted_levels(hist, ca)

    # ---- 2. residual panels ------------------------------------------------
    resid_x = xsec_residuals(adj, ks, cfg.xsec_variant, knots=cfg.xsec_knots)
    resid_p, pca_info = walk_forward_pca_residuals(
        adj, n_pcs=cfg.n_pcs, window=cfg.pca_window,
        min_window=cfg.pca_min_window, refit=cfg.pca_refit)
    agree = sign_agreement(resid_x, resid_p, min_abs_bp=cfg.sign_min_abs_bp)
    diag = fit_diagnostics(ks, cfg.xsec_variant, knots=cfg.xsec_knots)

    info_keys = sorted(k for k in pca_info if k <= asof)
    last_loadings = pca_info[info_keys[-1]]["loadings"] if info_keys else None

    # ---- 3/4. per-point trailing stats + FPT on the COMPOSED MICRO-FLY ----
    # The stats series of interior point i is the FIXED sum-zero rate-space
    # fly of its adjacent grid legs (module docstring item 3):
    #     L_i(t) = 2*adj_i(t) - adj_{i-1}(t) - adj_{i+1}(t)
    # Sum-zero weights cancel a common level move EXACTLY — an outright-level
    # z is duration in disguise (the 2026-08-21 15/17-points-at-z~+2
    # artifact, DESIGN section 0 / the W4 failure mode). Endpoints have no
    # adjacent fly: their whole stats block is NaN and n_hist is 0.
    fly_level: Dict[str, pd.Series] = {}
    for i, lab in enumerate(labels):
        if 0 < i < len(labels) - 1:
            fly_level[lab] = (FLY_STATS_WEIGHTS[0] * adj[labels[i - 1]]
                              + FLY_STATS_WEIGHTS[1] * adj[lab]
                              + FLY_STATS_WEIGHTS[2] * adj[labels[i + 1]])

    rows: Dict[str, Dict[str, Any]] = {lab: {} for lab in labels}
    fpt_hits: Dict[str, np.ndarray] = {}
    _NAN_STATS = ("fly_bp", "zs", "pctl_3y", "ou_kappa", "ou_mu_bp",
                  "half_life_d", "e_fpt_d", "p_hit", "frac_censored",
                  "q50_fpt_d", "e_rev_bp", "rev_drag_fpt_bp")
    for lab in labels:
        r = rows[lab]
        # realized vol DELIBERATELY stays on the POINT series (docstring
        # item 3): sigma_BE is a breakeven on the PARALLEL curve shift, so
        # be_over_rv needs a rate-level vol in its denominator — a
        # micro-fly's own level vol legitimately sits below the 0.5 bp/day
        # units floor and would trip the guard.
        rv = realized_vol_bp_day(adj[lab], window=int(cfg.rlzd_window),
                                 min_periods=int(cfg.rlzd_min_periods))
        r["sigma_rlzd_bp_day"] = float(rv.loc[asof])
        if lab not in fly_level:            # endpoint: no fly, no stats
            r["n_hist"] = 0
            r.update({k: float("nan") for k in _NAN_STATS})
            fpt_hits[lab] = np.full(int(cfg.fpt_sims), np.nan)
            continue
        s = fly_level[lab]
        x0 = float(s.loc[asof]) if pd.notna(s.loc[asof]) else float("nan")
        r["fly_bp"] = x0
        w = _trailing(s, cfg.z_window)
        n_hist = int(len(w))
        r["n_hist"] = n_hist
        if n_hist >= int(cfg.stats_min_obs) and np.isfinite(x0):
            mean, std = float(w.mean()), float(w.std(ddof=1))
            r["zs"] = (x0 - mean) / std if std > 0 else float("nan")
            r["pctl_3y"] = float((w <= x0).mean())
        else:
            r["zs"] = float("nan")
            r["pctl_3y"] = float("nan")
        w_ou = _trailing(s, cfg.ou_window)
        params = (calibrate_ou(w_ou) if len(w_ou) >= int(cfg.stats_min_obs)
                  else {"mu": np.nan, "kappa": np.nan, "sigma": np.nan,
                        "phi": np.nan, "intercept": np.nan, "half_life": np.nan})
        r["ou_kappa"] = float(params["kappa"])
        r["ou_mu_bp"] = float(params["mu"])
        r["half_life_d"] = float(params["half_life"])
        mu = float(params["mu"])
        target = x0 + 0.5 * (mu - x0) if np.isfinite(mu) and np.isfinite(x0) else float("nan")
        r["e_rev_bp"] = (abs(mu - x0) / 2.0
                         if np.isfinite(mu) and np.isfinite(x0) else float("nan"))
        rng = np.random.default_rng(int(cfg.fpt_seed))  # fresh per point: CRN
        hits = fpt_sample(x0, target, params, sims=int(cfg.fpt_sims),
                          steps=int(cfg.fpt_steps), dt=float(cfg.fpt_dt), rng=rng)
        fpt_hits[lab] = hits
        st = fpt_stats(hits, steps=float(cfg.fpt_steps))
        r["e_fpt_d"] = float(st["e_fpt"])
        # p_hit runs on the BOOK'S OWN CLOCK (DESIGN 6a item 2): the fraction
        # of MC paths hitting within cfg.max_hold_bd, NOT within the 504-step
        # cap (that rate stays recoverable as 1 - frac_censored). Hit indices
        # are read as business days under the frozen fpt_dt=1.0 — the same
        # convention p_fpt_exceeds consumes below. Censored (inf) and
        # slower-than-h hits both count as misses; a no-fit array (NaN hits)
        # stays NaN — (NaN <= h) is False and would otherwise print a silent
        # p_hit of 0.
        r["p_hit"] = (float((hits <= float(cfg.max_hold_bd)).mean())
                      if not np.isnan(hits).any() else float("nan"))
        r["frac_censored"] = float(st["frac_censored"])
        r["q50_fpt_d"] = float(st["q50"])
        # OU-expected drag of the FLY level toward its mean over the FPT horizon
        if np.isfinite(st["e_fpt"]) and np.isfinite(x0):
            cond = ou_conditional(x0, params, st["e_fpt"])
            r["rev_drag_fpt_bp"] = (float(cond["mean"]) - x0
                                    if np.isfinite(cond["mean"]) else float("nan"))
        else:
            r["rev_drag_fpt_bp"] = float("nan")

    # ---- 5/6. micro-fly carry + rent block --------------------------------
    carry_cache: Dict = {}
    for i, lab in enumerate(labels):
        r = rows[lab]
        if i == 0 or i == len(labels) - 1:
            r.update(carry_bp_day=float("nan"), carry_horizon_y_used=float("nan"),
                     w_front=float("nan"), w_belly=float("nan"),
                     w_back=float("nan"), w_sum=float("nan"),
                     w_pca_front=float("nan"), w_pca_back=float("nan"),
                     gamma_usd_per_bp2=float("nan"), theta_usd_day=float("nan"),
                     sigma_be_bp_day=float("nan"), be_status="undefined")
            continue
        f_pt, b_pt, k_pt = points[i - 1], points[i], points[i + 1]
        legs = tuple(Leg(float(p.fwd), float(p.tenor)) for p in (f_pt, b_pt, k_pt))
        wgt = neutral_weights(pricer, legs, belly=1)
        s = Structure(f"fly:{lab}", legs, tuple(float(x) for x in wgt), "fly")
        carry_bp_day, h_used = _fly_carry(pricer, s, cfg, carry_cache)
        r["carry_bp_day"] = carry_bp_day
        r["carry_horizon_y_used"] = h_used
        r["w_front"], r["w_belly"], r["w_back"] = (float(wgt[0]), float(wgt[1]),
                                                   float(wgt[2]))
        r["w_sum"] = float(sum(wgt))
        pf, pk = _pca_neutral_wings(last_loadings, labels[i - 1], lab,
                                    labels[i + 1])
        r["w_pca_front"], r["w_pca_back"] = pf, pk
        package = [
            pricer.build_irswap(fwd=f"{p.fwd:g}Y", tenor=f"{p.tenor:g}Y",
                                bpv=float(wi) * float(cfg.dv01_usd))
            for p, wi in zip((f_pt, b_pt, k_pt), wgt)
        ]
        gamma = package_gamma_usd(pricer, package, shifts=cfg.shifts)
        theta = carry_bp_day * float(cfg.dv01_usd)   # NaN carry -> NaN theta
        be, status = sigma_be_bp_day(theta, gamma)
        r["gamma_usd_per_bp2"] = float(gamma)
        r["theta_usd_day"] = float(theta)
        r["sigma_be_bp_day"] = float(be)
        r["be_status"] = status

    # ---- 4b. carry-dependent FPT tails ------------------------------------
    for lab in labels:
        r = rows[lab]
        c = r["carry_bp_day"]
        e_rev = r["e_rev_bp"]
        if not np.isfinite(c):
            r["carry_be_days"] = float("nan")
            r["p_fpt_gt_carry_be"] = float("nan")
        elif c >= 0.0:
            # earning while waiting: carry never eats the reversion
            r["carry_be_days"] = float("inf")
            r["p_fpt_gt_carry_be"] = 0.0
        elif np.isfinite(e_rev):
            be_days = e_rev / abs(c)
            r["carry_be_days"] = be_days
            r["p_fpt_gt_carry_be"] = float(p_fpt_exceeds(fpt_hits[lab], be_days))
        else:
            r["carry_be_days"] = float("nan")
            r["p_fpt_gt_carry_be"] = float("nan")
        # rac_net@FPT: fly carry over the fly's own FPT clock + the fly's own
        # drag — one tradeable object (docstring item 9)
        r["rac_net"] = c * r["e_fpt_d"] + r["rev_drag_fpt_bp"]

    # ---- 7. sigma_impl (support-gated) ------------------------------------
    axes = quoted_axes(asof.date(), store=store)
    for p, lab in zip(points, labels):
        if axes is None:
            rows[lab]["sigma_impl_bp_day"] = float("nan")
            continue
        ok = support_gate(float(p.fwd), float(p.tenor),
                          expiries=axes[0], tenors=axes[1])
        rows[lab]["sigma_impl_bp_day"] = (
            float(bp_year_to_day(cube_atm_bp_year(
                float(p.fwd), float(p.tenor), asof.date(), store=store,
                clamp=True)))
            if ok else float("nan"))

    # ---- 8. frontiers (asof cross-section) --------------------------------
    leg_roll_errors: Dict[str, str] = {}
    roll_vals = {}
    for lab in labels:
        try:
            roll_vals[lab] = float(leg_roll_bp(pricer, lab,
                                               cfg.frontier_roll_horizon))
        except (ValueError, KeyError) as exc:
            roll_vals[lab] = float("nan")
            leg_roll_errors[lab] = str(exc)[:120]
    roll_row = pd.DataFrame([roll_vals], index=pd.DatetimeIndex([asof]),
                            columns=labels)
    x_row = resid_x.loc[[asof], labels]
    impl_row = pd.DataFrame(
        [{lab: rows[lab]["sigma_impl_bp_day"] for lab in labels}],
        index=pd.DatetimeIndex([asof]), columns=labels)
    fit_vc = daily_xfit(x_row, roll_row, min_n=int(cfg.frontier_min_n))
    off_vc = off_frontier(x_row, roll_row, fit_vc)
    fit_cv = daily_xfit(roll_row, impl_row, min_n=int(cfg.frontier_min_n))
    off_cv = off_frontier(roll_row, impl_row, fit_cv)

    # ---- assemble ----------------------------------------------------------
    for p, lab, k in zip(points, labels, ks):
        r = rows[lab]
        r["fwd"], r["tenor"], r["k_coord"] = float(p.fwd), float(p.tenor), float(k)
        r["tag"] = grids.classify_point(p)
        r["level_bp"] = float(hist.at[asof, lab])
        r["ca_bp"] = float(ca.at[asof, lab])
        r["adj_bp"] = float(adj.at[asof, lab])
        r["residual_xsec"] = float(resid_x.at[asof, lab])
        r["residual_pca"] = float(resid_p.at[asof, lab])
        r["sign_agree"] = float(agree.at[asof, lab])
        r["leg_roll_bp"] = roll_vals[lab]
        r["off_value_carry"] = float(off_vc.at[asof, lab])
        r["off_carry_vol"] = float(off_cv.at[asof, lab])
        be = r["sigma_be_bp_day"]
        rv = r["sigma_rlzd_bp_day"]
        r["be_over_rv"] = be / rv if np.isfinite(rv) and rv > 0 else float("nan")
        # DESIGN 6a item 2 — the edge runs on the book's own clock: reversion
        # credited only with P(hit <= h) (p_hit above), carry charged over
        # min(E[FPT], h), h = cfg.max_hold_bd. np.minimum NaN-propagates;
        # Python min(nan, h) would silently return h and price a no-fit row.
        r["edge_bp"] = (r["e_rev_bp"] * r["p_hit"]
                        - abs(r["carry_bp_day"])
                        * float(np.minimum(r["e_fpt_d"], float(cfg.max_hold_bd)))
                        - float(cfg.cost_bp))

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "point"
    df = df.loc[labels]

    # ---- 11. books --------------------------------------------------------
    df["book"] = classify_books(df[list(REQUIRED_COLUMNS)], cfg.gates)
    df = df[list(SCREEN_COLUMNS)]

    df.attrs["asof"] = asof
    df.attrs["cost_bp"] = float(cfg.cost_bp)
    df.attrs["max_hold_bd"] = int(cfg.max_hold_bd)
    df.attrs["ca_mode"] = ca_mode_used
    df.attrs["ca_cells_ffilled"] = int(n_ffilled)
    df.attrs["fit_diag"] = diag
    df.attrs["pca_info"] = {
        "n_refits": len(info_keys),
        "last_refit": info_keys[-1] if info_keys else None,
        "cos_prev": (pca_info[info_keys[-1]]["cos_prev"] if info_keys else {}),
        "explained": (pca_info[info_keys[-1]]["explained"].to_dict()
                      if info_keys else {}),
    }
    df.attrs["frontier_value_carry"] = fit_vc.iloc[0].to_dict()
    df.attrs["frontier_carry_vol"] = fit_cv.iloc[0].to_dict()
    df.attrs["leg_roll_errors"] = leg_roll_errors
    df.attrs["cube_axes_asof"] = axes
    return df
