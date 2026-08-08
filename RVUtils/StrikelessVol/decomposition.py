"""The exact decomposition and spot-fly replication of a forward-slope package.

Task 24 (H11). A DV01-neutral forward-slope package (e.g. the USD
10y10y/20y10y flattener) is, in spot-curve coordinates, a misweighted
butterfly. Under a flat-annuity, zero-discounting approximation
``f(a,b) = (b*s_b - a*s_a)/(b-a)``, so for 10y10y/20y10y::

    spread = 20y10y - 10y10y ~= 1*s10 - 4*s20 + 3*s30

-- the flattener is receive 1x10s, pay 4x20s, receive 3x30s: a **1:4:3**
long-wings-short-belly fly, nothing like 1:2:1. That formula is narrative and
unit-test material ONLY (:func:`duration_weights`); discounting tilts it
materially, so the tradeable replication is solved off the package's
**bucketed DV01 ladder** by repricing (:func:`ladder_replication`), and the
toy is pinned solely as the zero-discounting limit in
``tests/test_strikeless_vol_decomposition.py``.

Conventions (load-bearing):

* **Bucketed ladder = zero-tent bump-and-reprice.** Bucket ``i``'s bump
  multiplies every node discount factor by ``(1 + d*h/10000)**(-days * phi_i)``
  where ``d`` is the curve's own daily DCF (:func:`greeks.daily_dcf` -- the
  same time measure ``rl.Curve.shift`` uses, so a parallel tent reproduces
  ``shift`` exactly on a log-linear curve) and ``phi_i`` is a piecewise-linear
  tent peaking at bucket ``i``'s pillar, flat-extended at both ends. The tents
  are a **partition of unity**, so the bucket ladder sums to the parallel
  repriced DV01 -- the cross-check the tests pin, per leg (the package's own
  parallel DV01 is ~0 by construction, so the per-leg check is the
  non-degenerate one).
* **Weights are payer-positive DV01 dollars per bp**: ``w_T > 0`` means pay
  fixed at tenor ``T`` with ``|w_T|`` of repriced DV01 (a payer gains when
  rates rise; ``greeks.PAYER_NOTIONAL_SIGN`` pins the underlying rateslib
  sign). For the default $100k flattener the zero-discount limit is
  ``{10Y: -100k, 20Y: +400k, 30Y: -300k}``.
* **Basis = package P&L - replication P&L**, both entry-vintage: weights
  solved and instruments struck on the PREVIOUS date's curve, both repriced on
  the current date's curve. :func:`replication_basis` re-strikes daily
  (constant-maturity, one-day holding) -- it measures the replication's daily
  tracking, not an aged book (aging lives in ``replication.CurvePricer`` and
  only there).

Why this module builds its own ladders instead of calling
``RVUtils.rl_swap_risk_ladder_utils.solve_best_n_leg_hedge_pca``: that solver
routes every ladder through ``rl.Portfolio.delta(solver=...)``, which needs a
calibrated ``rl.Solver`` the store-served ``RLIRSwapCurve`` objects do not
carry (``RLIRSwapCurve.dv01`` raises ``NotImplementedError`` for exactly this
reason). The same weighted-least-squares mathematics is applied here to the
tent ladders, and the PCA *metric* construction IS consumed from that module
via :func:`pca_metric` -- including its refusal of uniform/None ``pca_weights``
(a uniform-weight "PCA metric" is arithmetically the identity and the hedge
silently degrades to unweighted least squares; see
``_refuse_degenerate_pca_metric`` there).

Structures. ``EXACT_10_20_30`` is the exact spot replication;
``PROXY_5_10_30`` the liquid spot proxy; ``PROXY_1YFWD_2_7_30`` and
``PROXY_1YFWD_2_7_29`` the 1y-forward fly proxies. Plan collision 1 recorded
the 1y-forward 2-7-30 fly as unpriceable on the GS-built USD curve (the
30y wing matures at 31y against a 30y final node); on the Citi Velocity
curves the 50Y point exists, so 2-7-30 IS priceable there. Both presets are
therefore provided and results must report both rather than substituting
silently -- the 2-7-29 substitution's cost is measurable as the difference of
their bases.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.greeks import (
    build_leg,
    build_package,
    daily_dcf,
    package_npv,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

__all__ = [
    "DEFAULT_BUCKETS",
    "EXACT_10_20_30",
    "PROXY_5_10_30",
    "PROXY_1YFWD_2_7_30",
    "PROXY_1YFWD_2_7_29",
    "UNIT_DV01_USD",
    "bucket_pillar_dates",
    "duration_weights",
    "initiate_cost_usd",
    "ladder_replication",
    "pca_metric",
    "replication_basis",
    "structure_legs",
    "swap_bucket_ladder",
    "tent_shifted_handle",
]

#: The bucket grid the plan names for the bucketed DV01 ladder.
DEFAULT_BUCKETS: Tuple[str, ...] = ("2Y", "5Y", "7Y", "10Y", "20Y", "30Y")

#: Exact spot replication of a 10y10y/20y10y package.
EXACT_10_20_30: Tuple[str, ...] = ("10Y", "20Y", "30Y")

#: Liquid spot proxy fly.
PROXY_5_10_30: Tuple[str, ...] = ("5Y", "10Y", "30Y")

#: 1y-forward fly proxies. 2-7-30's far wing matures at 31y: priceable on the
#: Citi curves (50Y final node), NOT on the GS-built USD curve (30y final
#: node) -- report both, never substitute silently (plan collision 1).
PROXY_1YFWD_2_7_30: Tuple[Tuple[str, str], ...] = (
    ("1Y", "2Y"), ("1Y", "7Y"), ("1Y", "30Y"),
)
PROXY_1YFWD_2_7_29: Tuple[Tuple[str, str], ...] = (
    ("1Y", "2Y"), ("1Y", "7Y"), ("1Y", "29Y"),
)

#: Sizing of each unit replication instrument. Any positive value gives the
#: same solved weights (the solve is linear); this only conditions the matrix.
UNIT_DV01_USD: float = 10_000.0


# ---------------------------------------------------------------------------
# The zero-discounting toy (narrative + unit-test material only)


def _year_label(years: float) -> str:
    if abs(years - round(years)) > 1e-9:
        raise ValueError(
            f"duration_weights only labels whole-year tenors, got {years!r} "
            "years -- extend _year_label if a sub-annual pair ever enters the "
            "universe."
        )
    return f"{int(round(years))}Y"


def duration_weights(pair: ForwardPair) -> Dict[str, float]:
    """Zero-discounting flat-annuity spot-rate weights of the pair's spread.

    Under ``annuity(a,b) ~ (b-a)`` (flat annuity, no discounting) a forward
    par rate decomposes exactly as ``f(a,b) = (b*s_b - a*s_a)/(b-a)``, so the
    spread ``long - short`` is a fixed linear combination of spot par rates.
    Returns ``{tenor_label: coefficient}`` with
    ``spread ~= sum_T w_T * s_T``, keys sorted by tenor, exact zeros dropped.

    Sign reading: the flattener's P&L per bp is ``-package_dv01 * d(spread)``,
    so it RECEIVES the positive-weight tenors and PAYS the negative-weight
    ones. For 10y10y/20y10y: ``{10Y: +1, 20Y: -4, 30Y: +3}`` -- receive
    1x10s, pay 4x20s, receive 3x30s, the misweighted 1:4:3 fly.

    **Toy only.** Discounting tilts these weights materially; anything traded
    is solved off the repriced bucket ladder (:func:`ladder_replication`).
    The tests pin this formula solely as the zero-discounting limit of that
    solve.
    """
    acc: Dict[float, float] = {}

    def _add(years: float, coef: float) -> None:
        key = round(years, 9)
        acc[key] = acc.get(key, 0.0) + coef

    for leg, sgn in ((pair.long, +1.0), (pair.short, -1.0)):
        a, t = leg.fwd_years, leg.tail_years
        b = a + t
        _add(b, sgn * b / t)
        if a != 0.0:
            _add(a, -sgn * a / t)
    return {
        _year_label(y): acc[y]
        for y in sorted(acc)
        if abs(acc[y]) > 1e-12
    }


# ---------------------------------------------------------------------------
# Bucketed (zero-tent) DV01 ladders by repricing


def _as_dt(date: Any):
    return pd.Timestamp(date).to_pydatetime()


def _leg_label(leg: ForwardLeg) -> str:
    """'10Y' for a spot leg, '1Y30Y' for a forward one."""
    return leg.tail.upper() if leg.fwd.upper() in ("0D",) else leg.label


def structure_legs(structure: Sequence[Union[str, Tuple[str, str], ForwardLeg]]) -> List[ForwardLeg]:
    """Normalise a structure spec into ``ForwardLeg``s.

    A bare tenor string is a SPOT instrument (``fwd='0D'``); a ``(fwd, tail)``
    tuple or ``ForwardLeg`` is taken as given.
    """
    legs: List[ForwardLeg] = []
    for item in structure:
        if isinstance(item, ForwardLeg):
            legs.append(item)
        elif isinstance(item, str):
            legs.append(ForwardLeg("0D", item))
        else:
            fwd, tail = item
            legs.append(ForwardLeg(str(fwd), str(tail)))
    if not legs:
        raise ValueError("structure is empty")
    return legs


def bucket_pillar_dates(curve, buckets: Sequence[str]) -> List[Any]:
    """Pillar dates: the maturity of the spot par swap at each bucket tenor.

    Taken off the same ``build_irswap`` path the replication instruments use,
    so each spot instrument's risk peaks at its own bucket's pillar by
    construction rather than by a separate date convention.
    """
    out = []
    for b in buckets:
        swap = curve.build_irswap(fwd="0D", tenor=b, notional=1.0)
        out.append(_as_dt(curve.maturity_date(swap)))
    days = [(p - _as_dt(curve.reference_date())).days for p in out]
    if sorted(days) != days or len(set(days)) != len(days):
        raise ValueError(f"buckets must be strictly increasing, got {list(buckets)} -> {days}")
    return out


def _phi(days: float, i: int, pillar_days: Sequence[float]) -> float:
    """Tent ``i``'s weight at ``days`` from the curve's initial node.

    Piecewise linear, peak 1.0 at pillar ``i``, zero at the adjacent pillars;
    the first tent is flat 1.0 before its pillar and the last flat 1.0 after,
    so the family is a partition of unity on the whole curve span (which is
    what makes the ladder sum to the parallel DV01). A single bucket is the
    degenerate parallel case, ``phi == 1`` everywhere.
    """
    p = pillar_days
    last = len(p) - 1
    t = float(days)
    if last == 0:
        return 1.0
    if i == 0:
        if t <= p[0]:
            return 1.0
        if t >= p[1]:
            return 0.0
        return (p[1] - t) / (p[1] - p[0])
    if i == last:
        if t >= p[last]:
            return 1.0
        if t <= p[last - 1]:
            return 0.0
        return (t - p[last - 1]) / (p[last] - p[last - 1])
    if t <= p[i - 1] or t >= p[i + 1]:
        return 0.0
    if t <= p[i]:
        return (t - p[i - 1]) / (p[i] - p[i - 1])
    return (p[i + 1] - t) / (p[i + 1] - p[i])


def tent_shifted_handle(handle, pillar_dates: Sequence[Any], i: int, h_bp: float):
    """A copy of ``handle`` with bucket ``i``'s tent bump of ``h_bp`` applied.

    Node ``T`` (at ``n`` days from the initial node) has its discount factor
    multiplied by ``(1 + d*h/10000) ** (-n * phi_i(n))`` with ``d`` the
    curve's own daily DCF -- exactly ``rl.Curve.shift``'s discrete bump scaled
    by the tent, so at ``phi == 1`` everywhere (one bucket) this reproduces
    ``shift(h_bp)`` on a log-linear curve. Positive ``h_bp`` bumps zero rates
    UP (discount factors down), matching ``shift``'s sign.

    Built with ``handle.copy()`` + ``update_node`` so convention, calendar and
    interpolation are inherited rather than re-guessed.
    """
    d = daily_dcf(handle)
    base = 1.0 + d * float(h_bp) / 10_000.0
    initial = handle.nodes.initial
    p_days = [(_as_dt(p) - _as_dt(initial)).days for p in pillar_dates]
    out = handle.copy()
    for node_date, df in handle.nodes.nodes.items():
        n = (_as_dt(node_date) - _as_dt(initial)).days
        if n <= 0:
            continue
        phi = _phi(n, i, p_days)
        if phi == 0.0:
            continue
        out.update_node(node_date, float(df) * base ** (-n * phi))
    return out


def _bucket_ladder(
    curve,
    npv_of_handle: Callable[[Any], float],
    *,
    buckets: Sequence[str],
    h_bp: float = 1.0,
    pillar_dates: Optional[Sequence[Any]] = None,
) -> pd.Series:
    """Central-difference bucketed DV01 ladder of any handle->NPV functional."""
    handle = curve.handle()
    pillars = list(pillar_dates) if pillar_dates is not None else bucket_pillar_dates(curve, buckets)
    if len(pillars) != len(buckets):
        raise ValueError("pillar_dates and buckets disagree in length")
    vals = {}
    for i, b in enumerate(buckets):
        up = npv_of_handle(tent_shifted_handle(handle, pillars, i, +h_bp))
        dn = npv_of_handle(tent_shifted_handle(handle, pillars, i, -h_bp))
        vals[str(b)] = (up - dn) / (2.0 * float(h_bp))
    out = pd.Series(vals, name="dv01_usd")
    out.index.name = "bucket"
    return out


def swap_bucket_ladder(
    curve,
    swap,
    *,
    buckets: Sequence[str] = DEFAULT_BUCKETS,
    h_bp: float = 1.0,
    pillar_dates: Optional[Sequence[Any]] = None,
) -> pd.Series:
    """Bucketed DV01 ladder (USD per bp per bucket) of one rateslib swap."""
    return _bucket_ladder(
        curve,
        lambda hd: float(swap.npv(curves=hd).real),
        buckets=buckets,
        h_bp=h_bp,
        pillar_dates=pillar_dates,
    )


def package_bucket_ladder(
    curve,
    package,
    *,
    buckets: Sequence[str] = DEFAULT_BUCKETS,
    h_bp: float = 1.0,
    pillar_dates: Optional[Sequence[Any]] = None,
) -> pd.Series:
    """Bucketed DV01 ladder of a :class:`greeks.Package` (both legs)."""
    return _bucket_ladder(
        curve,
        lambda hd: package_npv(hd, package),
        buckets=buckets,
        h_bp=h_bp,
        pillar_dates=pillar_dates,
    )


# ---------------------------------------------------------------------------
# The solve


def _solve_weighted_ls(B: np.ndarray, r: np.ndarray, metric: Optional[np.ndarray]) -> np.ndarray:
    """``argmin_w (r - B w)^T G (r - B w)``; ``metric=None`` is plain LS.

    Same normal-equation mathematics as the ``rl_swap_risk_ladder_utils``
    solvers, applied to the tent ladders (see the module docstring for why
    that module's ``solve_best_n_leg_hedge_pca`` itself cannot run on
    store-served curves). No BPV-neutrality constraint: the target ladder is
    already the ladder of a DV01-neutral package, and constraining the solve
    would forbid the exact square replication from matching it.
    """
    if metric is None:
        w, *_ = np.linalg.lstsq(B, r, rcond=None)
        return w
    G = np.asarray(metric, dtype=float)
    if G.shape != (B.shape[0], B.shape[0]):
        raise ValueError(f"metric must be {B.shape[0]}x{B.shape[0]}, got {G.shape}")
    BTGB = B.T @ (G @ B)
    BTGr = B.T @ (G @ r)
    w, *_ = np.linalg.lstsq(BTGB, BTGr, rcond=None)
    return w


def pca_metric(pca_model, pca_weights, *, buckets: Optional[Sequence[str]] = None) -> np.ndarray:
    """The PCA quadratic form ``G = L diag(w) L^T`` for :func:`replication_basis`.

    Thin pass-through to ``rl_swap_risk_ladder_utils._build_pca_metric_matrix``
    so this module inherits, rather than re-implements, its refusal of
    ``pca_weights=None``/uniform weights (for an orthonormal loadings matrix
    those make ``G`` the identity and the "PCA metric" silently degrades to
    unweighted least squares). Pass explicit weights naming the components to
    neutralise, e.g. ``[1, 1, 0, ...]`` for a level+slope metric.

    ``buckets``, when given, must match the model's ladder basis in length --
    the metric is meaningless on a differently-bucketed ladder.
    """
    from RVUtils.rl_swap_risk_ladder_utils import _build_pca_metric_matrix

    G = _build_pca_metric_matrix(pca_model, pca_weights)
    if buckets is not None and G.shape[0] != len(buckets):
        raise ValueError(
            f"PCA model is fitted on {G.shape[0]} ladder buckets but the solve "
            f"uses {len(buckets)}: {list(buckets)}. Refit or re-bucket."
        )
    return G


def _solve_replication(
    curve,
    pair: ForwardPair,
    *,
    buckets: Sequence[str],
    legs: Sequence[ForwardLeg],
    metric: Optional[np.ndarray],
    package_dv01_usd: float,
    sign: int,
    h_bp: float,
):
    """Shared solve: package, unit instruments, ladders, weights.

    Returns ``(package, unit_swaps, weights_clips, r, B, labels)`` where
    ``weights_clips[j]`` scales unit instrument ``j`` (each sized to
    ``UNIT_DV01_USD`` of payer DV01), so the solved DV01 weight in dollars is
    ``weights_clips * UNIT_DV01_USD``.
    """
    pkg = build_package(curve, pair, package_dv01_usd=package_dv01_usd, sign=sign)
    pillars = bucket_pillar_dates(curve, buckets)
    r = package_bucket_ladder(curve, pkg, buckets=buckets, h_bp=h_bp, pillar_dates=pillars)

    labels = [_leg_label(leg) for leg in legs]
    if len(set(labels)) != len(labels):
        raise ValueError(f"structure has duplicate legs: {labels}")
    unit_swaps = [
        build_leg(curve, leg, dv01_usd=UNIT_DV01_USD, direction=+1) for leg in legs
    ]
    cols = [
        swap_bucket_ladder(curve, s, buckets=buckets, h_bp=h_bp, pillar_dates=pillars)
        for s in unit_swaps
    ]
    B = np.column_stack([c.to_numpy() for c in cols])
    w = _solve_weighted_ls(B, r.to_numpy(), metric)
    return pkg, unit_swaps, w, r, B, labels


def ladder_replication(
    pair: ForwardPair,
    curve,
    *,
    buckets: Sequence[str] = DEFAULT_BUCKETS,
    structure: Optional[Sequence[Union[str, Tuple[str, str], ForwardLeg]]] = None,
    metric: Optional[np.ndarray] = None,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
    h_bp: float = 1.0,
) -> pd.Series:
    """Solve the spot-curve replication of the pair's package on one curve.

    Builds the DV01-neutral package (``sign=+1`` is the flattener), takes its
    bucketed tent ladder, and solves for the portfolio of par swaps -- one per
    ``structure`` entry, spot instruments at the bucket tenors when
    ``structure`` is None -- whose ladders best reproduce it (least squares;
    exact when the structure spans the buckets square).

    Returns the solved weights as **payer-positive DV01 dollars per bp**,
    indexed by instrument label. ``attrs`` carry the audit trail:

    * ``package_ladder`` / ``residual_ladder`` -- target and ``r - B w``;
    * ``residual_norm`` -- L2 norm of the residual in dollars;
    * ``notionals`` -- rateslib notional per instrument at the solved size
      (unit notional x solved clips), for building the actual trade;
    * ``buckets``, ``h_bp``, ``package_dv01_usd``, ``sign``.
    """
    legs = structure_legs(structure if structure is not None else list(buckets))
    pkg, unit_swaps, w, r, B, labels = _solve_replication(
        curve, pair, buckets=buckets, legs=legs, metric=metric,
        package_dv01_usd=package_dv01_usd, sign=sign, h_bp=h_bp,
    )
    out = pd.Series(w * UNIT_DV01_USD, index=pd.Index(labels, name="instrument"),
                    name="replication_dv01_usd")
    resid = r.to_numpy() - B @ w
    out.attrs.update({
        "package_ladder": r,
        "residual_ladder": pd.Series(resid, index=r.index, name="residual_dv01_usd"),
        "residual_norm": float(np.linalg.norm(resid)),
        "notionals": {
            lab: float(curve.notional(s)) * float(wj)
            for lab, s, wj in zip(labels, unit_swaps, w)
        },
        "buckets": tuple(str(b) for b in buckets),
        "h_bp": float(h_bp),
        "package_dv01_usd": float(package_dv01_usd),
        "sign": int(sign),
    })
    return out


# ---------------------------------------------------------------------------
# The daily basis panel


def replication_basis(
    pair: ForwardPair,
    curve_panel: dict,
    *,
    structure: Sequence[Union[str, Tuple[str, str], ForwardLeg]],
    buckets: Sequence[str] = DEFAULT_BUCKETS,
    metric: Optional[np.ndarray] = None,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
    h_bp: float = 1.0,
) -> pd.DataFrame:
    """Daily basis of a replication ``structure`` against the package.

    For each consecutive stored-date pair ``(d0, d1)``: the package and the
    replication weights are built and solved on ``d0``'s curve (entry-vintage,
    par-struck), both are repriced on ``d1``'s curve, and

        ``basis = package P&L - replication P&L``

    is recorded on ``d1``. Re-struck every day: constant-maturity, one-day
    holding -- this measures the replication's tracking, not an aged book.
    Positive basis means the package outperformed its replication.

    One row per priced ``d1``, columns: ``package_pnl_usd``,
    ``replication_pnl_usd``, ``basis_usd``, ``basis_bp`` (basis per dollar of
    ``package_dv01_usd``, in bp), ``residual_norm`` (the solve's ladder
    residual on ``d0``), and one ``w_<label>`` column per instrument (solved
    DV01 dollars). Proxies (structures that cannot span the buckets) should be
    solved under an explicit PCA ``metric`` (:func:`pca_metric`) -- the plan's
    "at PCA weights"; the default is plain least squares on the dollar ladder.

    Failure handling follows ``greeks.greeks_panel``: a date pair that fails
    to price is dropped and recorded in ``attrs['dropped']``; if EVERY pair
    fails, that is systematic and raises with the first error as cause.
    ``attrs['dates_in']`` counts candidate date pairs, ``attrs['structure']``
    the instrument labels.
    """
    legs = structure_legs(structure)
    labels = [_leg_label(leg) for leg in legs]
    curves = {pd.Timestamp(k): v for k, v in curve_panel.items()
              if v is not None and k != "live"}
    dates = sorted(curves)

    rows = []
    dropped: dict = {}
    first_error: Optional[Exception] = None
    candidates = 0
    for d0, d1 in zip(dates[:-1], dates[1:]):
        candidates += 1
        try:
            c0, c1 = curves[d0], curves[d1]
            pkg, unit_swaps, w, r, B, _ = _solve_replication(
                c0, pair, buckets=buckets, legs=legs, metric=metric,
                package_dv01_usd=package_dv01_usd, sign=sign, h_bp=h_bp,
            )
            h0, h1 = c0.handle(), c1.handle()
            pkg_pnl = package_npv(h1, pkg) - package_npv(h0, pkg)
            rep_pnl = float(sum(
                wj * (float(s.npv(curves=h1).real) - float(s.npv(curves=h0).real))
                for wj, s in zip(w, unit_swaps)
            ))
            basis = pkg_pnl - rep_pnl
            rec = {
                "date": pd.Timestamp(d1),
                "package_pnl_usd": pkg_pnl,
                "replication_pnl_usd": rep_pnl,
                "basis_usd": basis,
                "basis_bp": basis / float(package_dv01_usd),
                "residual_norm": float(np.linalg.norm(r.to_numpy() - B @ w)),
            }
            for lab, wj in zip(labels, w):
                rec[f"w_{lab}"] = float(wj) * UNIT_DV01_USD
            rows.append(rec)
        except Exception as exc:  # one bad date must not lose the panel
            dropped[pd.Timestamp(d1)] = repr(exc)
            if first_error is None:
                first_error = exc
            continue

    if candidates and not rows:
        raise ValueError(
            f"replication_basis priced 0 of {candidates} date pairs for "
            f"{pair.name} / {labels}. Every pair raised, so this is a "
            f"systematic failure, not a data gap -- the first error is "
            f"attached as __cause__. Distinct errors: "
            f"{sorted(set(dropped.values()))[:3]}"
        ) from first_error

    if not rows:
        panel = pd.DataFrame(columns=["date"]).set_index("date")
    else:
        panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.attrs.update({
        "structure": tuple(labels),
        "buckets": tuple(str(b) for b in buckets),
        "dates_in": candidates,
        "n_dropped": len(dropped),
        "dropped": dropped,
    })
    return panel


# ---------------------------------------------------------------------------
# Per-leg initiation cost (collision 3: charge the legs, not the package)


def initiate_cost_usd(weights, schedule) -> float:
    """Dollars to initiate a replication portfolio, charged PER TRADED LEG.

    ``weights`` maps instrument label -> signed DV01 dollars (the
    :func:`ladder_replication` output); each leg is charged
    ``schedule.cost_usd('initiate', |w|)`` separately. This is the per-leg
    convention plan collision 3 makes binding -- charging the net package
    DV01 (which is ~0 for a fly against a neutral package) would price the
    round trip at nearly nothing. Use it to compare the spot-fly hedge path
    against the forward-space path under one cost model.
    """
    w = pd.Series(dict(weights), dtype=float)
    return float(sum(schedule.cost_usd("initiate", abs(v)) for v in w))
