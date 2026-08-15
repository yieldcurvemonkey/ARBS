"""The butterfly universe for the SOFR pack-convexity hedge -- spot and forward.

Citi hedges a short pack-convexity position by **paying the belly of a 2s5s10s
swap fly**, sized to a regression beta rather than DV01-matched. Verbatim
([W-JAN13] p.13, and §5.2 of
``docs/convexityrv/research/01-citi-stir-convexity-vs-butterfly.md``):

    "One way to hedge this risk is to buy vol, such as a 3y1y swaption or a 3x4
    cap, against selling Blues CA. But this will obviously reduce the total
    carry of the package. **Instead, we propose hedging our short Blues CA by
    selling a 2s5s10s fly.** The motivation for this hedging strategy is that
    **3y1y vol is mostly driven by expectations of monetary policy, and
    therefore should be directional with the valuations of 5s on the curve.**"

    "Importantly, **selling the 2s5s10s fly as a hedge has the advantage of
    positive carry, unlike buying volatility.** The 3m carry/roll on the short
    2s5s10s fly is about +4bp over 3m."

THE HYPOTHESIS THIS MODULE EXISTS TO TEST
=========================================
Citi's choice of a **spot** 2s5s10s is an assertion about *where on the vol
surface* the pack's convexity lives. A pack's convexity adjustment is
``0.5 * sigma^2 * mean(T1^2)`` -- it is driven by volatility at the pack's own
expiry, ``T1`` years out. A spot fly is a proxy for vol at the *front*. So:

    **A forward-starting fly whose forward start matches the pack's expiry
    should hedge that pack better than the spot fly, and the improvement should
    grow with T1.**

That is directly falsifiable, and the universe here is built so it can be read
off a ``(pack T1) x (fly forward start)`` matrix rather than a flat table of
cells. :mod:`RVUtils.ConvexityRV.strat2_grid` computes that matrix.

**Scope limit, stated up front.** The SR3 daily store reaches pack windows 1..10
over 2019-01..2023-09, so the deepest testable pack has ``T1 ~ 2.5y``. Forward
starts of 1Y/2Y/3Y bracket that range; the 5Y start is carried as a deliberate
*over-shoot control* -- no pack in reach has an expiry near it, so if the
hypothesis is real the 5Y column should be WORSE than 2Y/3Y, not better. Blues
(T1~3.25y) and Golds (T1~4.25y), which is where Citi actually traded this, are
not in daily offline reach and the hypothesis is NOT tested at that depth.

WHY THE STORED PRIMITIVE IS LEG RATES, NOT FLY RATES
====================================================
``IRSwapValue.RATE`` on ``IRSwapStructure.FLY`` is, exactly::

    fly_bp = 1e4 * sum_i sign_mapped_w_i * fair_rate_i        (fair_rate decimal)
           = 100 * ( -|w_f|*r_f + |w_b|*r_b - |w_k|*r_k )     (r in percent)

-- a pure linear form in the three leg rates, with the sign mapper forcing
``[-|w0|, +|w1|, -|w2|]`` (belly positive, wings negative) whenever the belly
carries the ``bpv``. Measured on 2023-06-09 against three OUTRIGHT par rates,
the agreement is at machine precision:

======================================  ==================  ============
fly                                     engine - manual     weights
======================================  ==================  ============
2s5s10s, 0.5/1/0.5                      -1.99e-13 bp        [-.5,1,-.5]
2s5s10s, 0.73/1/0.47                    -9.95e-14 bp        [-.73,1,-.47]
2Yx2Y / 2Yx5Y / 2Yx10Y, 0.5/1/0.5       -1.24e-14 bp        [-.5,1,-.5]
2s7s30s, 0.6/1/0.4                      -5.68e-14 bp        [-.6,1,-.4]
======================================  ==================  ============

So the panel stores **par rates per leg tenor** (40 of them) and every fly, at
every weighting, is arithmetic on top. That is what makes a 45-fly x 2-weighting
x N-window grid affordable at all: re-weighting a fly costs nothing, and the
regression weights change every day.

Leg carry-and-roll is linear in the weights too --
``IRSwapValue._carry_and_roll_bps_running`` is literally
``sum(risk_weights[i] * curve.carry_and_roll_bps_running(leg_i, horizon))``
with the *already sign-mapped* weights -- so the fly's carry is derived the same
way, from a per-leg carry column.

*** THE RISK-WEIGHT LANDMINE ***
``IRSwapStructure._build_fly`` MUTATES the ``risk_weights`` list IN PLACE::

    >>> w = [0.73, 1.0, 0.47]
    >>> IRSwapQuery(structure=FLY, structure_kwargs={"risk_weights": w, ...})\\
    ...     .resolve_package(pricer_or_curve=pricer)
    >>> w
    [-0.73, 1.0, -0.47]

Measured, on this repo, today. Every weight in this module is therefore stored
as a **tuple** on a frozen dataclass, and :func:`fly_query_kwargs` builds a
fresh ``list`` on every call. A tuple cannot be mutated in place, which turns a
silent corruption into a ``TypeError``.

DV01 IDENTITY (verified, not assumed)
=====================================
With ``bpv`` on the belly, the resolved package's per-leg PV01 is exactly
``sign_mapped_w_i * bpv``. Measured 2023-06-09, 2s5s10s at 0.73/1/0.47 and
``bpv=$21,400``: legs came back at ``-15,622 / +21,400 / -10,058`` against
``-15,622 / +21,400 / -10,058`` expected -- exact. Hence, for a **paid belly**,

    dP&L = sum_i PV01_i * d r_i,bp = belly_DV01 * d(fly_bp)          [+ sign]

**The paid-belly P&L is PLUS ``belly_DV01 * d fly_bp``, not minus.** Confirmed
independently by repricing the resolved package on a shifted handle: at
0.73/1/0.47 a +1bp parallel shift moves the fly by ``1 - 0.73 - 0.47 = -0.20``
bp and the package NPV by ``-$4,489`` against ``-$4,280`` predicted (the ~5%
gap is the zero-shift/par-shift mapping, and it is linear in the shift: -4.6% at
+10bp, -5.2% at -10bp -- not convexity). The sign is unambiguous.

That sign is also the only one that hedges: ``CA_fitted = alpha + beta*fly``
with ``beta = +21.4``, so CA and the fly move together; a SHORT-CA position
loses when the fly rises, and a paid belly gains when the fly rises.
"""

from __future__ import annotations

import datetime
import math
import os
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "FLY_SHAPES",
    "FORWARD_STARTS",
    "SPOT_TENORS",
    "DV01_NEUTRAL_WINGS",
    "FlySpec",
    "FlyFit",
    "tenor_key",
    "parse_tenor_key",
    "fly_universe",
    "fly_by_id",
    "universe_tenors",
    "probe_priceable_tenors",
    "fly_query_kwargs",
    "fly_rate_bp",
    "fly_rate_series",
    "fly_carry_series",
    "fly_regression",
    "annuity_duration",
    "fly_gamma_per_bp2",
    "leg_metrics_for_date",
    "build_fly_leg_panel",
    "legs_wide",
    "fly_panel_from_legs",
    "build_and_write_panels",
    "PANEL_DIR",
    "LEGS_PARQUET",
    "FLY_PARQUET",
]

_REPO = pathlib.Path(__file__).resolve().parents[2]
PANEL_DIR = _REPO / "notebooks" / "data" / "convexity_rv"
LEGS_PARQUET = PANEL_DIR / "strat2_fly_legs.parquet"
FLY_PARQUET = PANEL_DIR / "strat2_fly_panel.parquet"


# ===========================================================================
# The catalogue
# ===========================================================================
#: ``name -> (front, belly, back)`` in YEARS. Nine shapes, chosen to span three
#: distinct questions rather than to fill a grid:
#:
#: ``1s2s3s``      the pure front fly -- policy-path curvature, no duration.
#: ``2s3s5s``      front-belly, the shape closest to a Whites/Reds pack expiry.
#: ``2s5s10s``     **Citi's**. The published hedge, weights -0.73/1/-0.47.
#: ``3s5s7s``      tight, symmetric around 5s -- Citi's belly with less wing risk.
#: ``5s7s10s``     the same idea one step out the curve.
#: ``2s10s30s``    the classic whole-curve fly; 10s belly, long-end wing.
#: ``5s10s30s``    belly-back, no front-end leg at all -- a negative control for
#:                 the "3y1y vol drives 5s" story: if the hedge works here too,
#:                 the mechanism is duration, not policy expectations.
#: ``10s20s30s``   pure long-end curvature; should NOT hedge a 1-3y pack.
#: ``2s7s30s``     the PM's ask.
FLY_SHAPES: Tuple[Tuple[str, Tuple[float, float, float]], ...] = (
    ("1s2s3s", (1.0, 2.0, 3.0)),
    ("2s3s5s", (2.0, 3.0, 5.0)),
    ("2s5s10s", (2.0, 5.0, 10.0)),
    ("3s5s7s", (3.0, 5.0, 7.0)),
    ("5s7s10s", (5.0, 7.0, 10.0)),
    ("2s10s30s", (2.0, 10.0, 30.0)),
    ("5s10s30s", (5.0, 10.0, 30.0)),
    ("10s20s30s", (10.0, 20.0, 30.0)),
    ("2s7s30s", (2.0, 7.0, 30.0)),
)

#: Forward starts in years. ``0`` is spot. 1/2/3 bracket the reachable pack
#: expiries (T1 ~ 0.3 .. 2.5y for windows 1..10); 5 is the over-shoot control.
FORWARD_STARTS: Tuple[float, ...] = (0.0, 1.0, 2.0, 3.0, 5.0)

#: Every distinct underlying tenor across the shapes.
SPOT_TENORS: Tuple[float, ...] = tuple(
    sorted({t for _, legs in FLY_SHAPES for t in legs}))

#: The wings of a DV01-neutral ("50/50") fly, belly normalised to 1. The package
#: DV01 is then ``belly*(1 - 0.5 - 0.5) = 0``: a pure curvature trade with no
#: outright duration. This is what "DV01 weights" means when nobody has run a
#: regression; Citi's Figure 21 3y1y-vol chart uses a fly "with DV01 weights",
#: and its *fitted* CA chart (Figure 22) uses the regression weights instead.
DV01_NEUTRAL_WINGS: Tuple[float, float] = (0.5, 0.5)


def _fmt_years(y: float) -> str:
    """``5.0 -> '5Y'``; a non-integer year count is refused rather than rounded."""
    if abs(y - round(y)) > 1e-9:
        raise ValueError(f"non-integral tenor {y}; the curve is quoted in whole years here")
    return f"{int(round(y))}Y"


def tenor_key(start_y: float, tenor_y: float) -> str:
    """``(0, 5) -> '5Y'``; ``(2, 5) -> '2Yx5Y'`` -- the engine's own tenor grammar.

    ``AYxBY`` is a B-year swap starting A years forward, verified priceable on
    ``USD-SOFR-1D`` for every combination this module uses.
    """
    if start_y <= 0:
        return _fmt_years(tenor_y)
    return f"{_fmt_years(start_y)}x{_fmt_years(tenor_y)}"


def parse_tenor_key(key: str) -> Tuple[float, float]:
    """``'2Yx5Y' -> (2.0, 5.0)``; ``'5Y' -> (0.0, 5.0)``."""
    k = str(key).strip().upper()
    if "X" in k:
        a, b = k.split("X", 1)
        return float(a.rstrip("Y")), float(b.rstrip("Y"))
    return 0.0, float(k.rstrip("Y"))


@dataclass(frozen=True)
class FlySpec:
    """One butterfly: three tenor keys plus the geometry needed to score it.

    Frozen, and every weight that ever reaches the query builder is carried as a
    tuple -- see the module docstring on ``_build_fly``'s in-place mutation.
    """

    fly_id: str                 # "2s5s10s" (spot) or "2s5s10s@2Y" (forward)
    shape: str                  # "2s5s10s"
    forward_start_y: float      # 0.0 for spot
    front: str                  # tenor key, e.g. "2Y" or "2Yx2Y"
    belly: str
    back: str
    front_y: float              # underlying tenor in years
    belly_y: float
    back_y: float

    @property
    def tenors(self) -> Tuple[str, str, str]:
        return (self.front, self.belly, self.back)

    @property
    def is_spot(self) -> bool:
        return self.forward_start_y <= 0.0

    def label(self, w_front: float, w_back: float) -> str:
        """``'2s5s10s@2Y -0.73/1/-0.47'`` -- the way Citi annotates its charts."""
        return f"{self.fly_id} -{w_front:.3g}/1/-{w_back:.3g}"


def fly_universe(
    shapes: Sequence[Tuple[str, Tuple[float, float, float]]] = FLY_SHAPES,
    forward_starts: Sequence[float] = FORWARD_STARTS,
) -> List[FlySpec]:
    """The full catalogue: every shape at every forward start.

    ``len(FLY_SHAPES) * len(FORWARD_STARTS)`` = 9 x 5 = **45 flies**, spanning
    **40 distinct leg tenors** (8 underlying tenors x 5 starts). All 40 were
    probed priceable on ``USD-SOFR-1D``; :func:`probe_priceable_tenors` re-runs
    that check against a live pricer and reports any that are not.
    """
    out: List[FlySpec] = []
    for name, (f, b, k) in shapes:
        for s in forward_starts:
            fid = name if s <= 0 else f"{name}@{_fmt_years(s)}"
            out.append(FlySpec(
                fly_id=fid, shape=name, forward_start_y=float(s),
                front=tenor_key(s, f), belly=tenor_key(s, b), back=tenor_key(s, k),
                front_y=float(f), belly_y=float(b), back_y=float(k)))
    return out


def fly_by_id(fly_id: str,
              specs: Optional[Sequence[FlySpec]] = None) -> FlySpec:
    """Look one fly up by id, with a listing in the error rather than a KeyError."""
    specs = list(specs) if specs is not None else fly_universe()
    for s in specs:
        if s.fly_id == fly_id:
            return s
    raise KeyError(f"unknown fly_id {fly_id!r}; known: {[s.fly_id for s in specs]}")


def universe_tenors(specs: Optional[Sequence[FlySpec]] = None) -> Tuple[str, ...]:
    """Every distinct leg tenor the universe needs, in curve order.

    This is the thing the panel builder prices -- 40 par rates per date, not
    45 flies x 3 legs = 135, because the legs are shared.
    """
    specs = list(specs) if specs is not None else fly_universe()
    seen: Dict[str, Tuple[float, float]] = {}
    for s in specs:
        for key in s.tenors:
            seen[key] = parse_tenor_key(key)
    return tuple(sorted(seen, key=lambda k: (seen[k][0], seen[k][1])))


def probe_priceable_tenors(pricer: Any, tenors: Sequence[str],
                           curve: str = "USD-SOFR-1D") -> Tuple[List[str], Dict[str, str]]:
    """``(priceable, {tenor: error})``. Call this before trusting a universe.

    The catalogue is a wish; the curve decides. Any tenor that raises is dropped
    from the build and REPORTED, never silently filled.
    """
    from RVUtils.ConvexityRV.strat2_sofr_convexity import _swap_par_rate

    ok: List[str] = []
    bad: Dict[str, str] = {}
    for t in tenors:
        try:
            r = _swap_par_rate(pricer, curve, tenor=t)
            if not np.isfinite(r):
                bad[t] = "non-finite rate"
            else:
                ok.append(t)
        except Exception as exc:                              # noqa: BLE001
            bad[t] = f"{type(exc).__name__}: {exc}"
    return ok, bad


def fly_query_kwargs(spec: FlySpec, w_front: float, w_back: float,
                     bpv: float) -> Dict[str, Any]:
    """``structure_kwargs`` for an ``IRSwapStructure.FLY`` query.

    A **fresh list** is constructed here on every call. ``_build_fly`` rewrites
    ``risk_weights`` in place, so handing it a shared or stored list silently
    corrupts every later query that reuses it. This is the one API in the repo
    where passing your own container is a bug.
    """
    return {
        "front_tenor": spec.front,
        "belly_tenor": spec.belly,
        "back_tenor": spec.back,
        "risk_weights": [float(w_front), 1.0, float(w_back)],   # fresh, deliberately
        "bpv": float(bpv),
    }


# ===========================================================================
# Fly arithmetic on the leg panel
# ===========================================================================
def fly_rate_bp(rates: Any, spec: FlySpec, w_front: float, w_back: float) -> float:
    """``100 * (-w_f*r_f + r_b - w_k*r_k)`` with leg rates in PERCENT -> bp.

    Identical to ``IRSwapValue.RATE`` on the FLY structure to ~1e-13 bp
    (measured; see the module docstring). Citi's chart annotation is the same
    quantity in percent: ``fly = -0.73*2y + 5y - 0.47*10y``, so ``fly_bp`` here
    is 100x Citi's ``fly``, and their ``beta`` (21.4 bp of CA per PERCENT of
    fly) becomes ``beta/100`` bp of CA per bp of ``fly_bp``.
    """
    rf, rb, rk = (float(rates[spec.front]), float(rates[spec.belly]),
                  float(rates[spec.back]))
    return 100.0 * (-abs(float(w_front)) * rf + rb - abs(float(w_back)) * rk)


def fly_rate_series(legs: pd.DataFrame, spec: FlySpec,
                    w_front: float, w_back: float) -> pd.Series:
    """Daily fly rate in bp from a wide ``date x tenor`` leg-rate frame (percent).

    ``w_front``/``w_back`` may be scalars (fixed weights, e.g. a held epoch) or
    Series aligned to ``legs.index`` (a rolling re-estimate). **Inside a held
    epoch the weights must be scalars fixed at entry** -- a fly whose weights
    move daily is not a tradeable instrument, and its "P&L" would include the
    re-weighting, which nobody executed.
    """
    missing = [t for t in spec.tenors if t not in legs.columns]
    if missing:
        raise KeyError(f"{spec.fly_id}: leg panel is missing {missing}")
    wf = w_front if np.isscalar(w_front) else pd.Series(w_front).reindex(legs.index)
    wk = w_back if np.isscalar(w_back) else pd.Series(w_back).reindex(legs.index)
    return 100.0 * (-np.abs(wf) * legs[spec.front] + legs[spec.belly]
                    - np.abs(wk) * legs[spec.back])


def fly_carry_series(carry: pd.DataFrame, spec: FlySpec,
                     w_front: float, w_back: float) -> pd.Series:
    """Fly carry+roll in bp, from a wide ``date x tenor`` per-leg carry frame.

    ``IRSwapValue._carry_and_roll_bps_running`` is
    ``sum(risk_weights[i] * curve.carry_and_roll_bps_running(leg_i, horizon))``
    over the ALREADY SIGN-MAPPED weights ``[-w_f, +1, -w_k]``, so the fly's carry
    is exactly this weighted sum of the per-leg numbers -- the same linearity
    the rate has.

    **Sign convention.** The per-leg number is the carry+roll of a payer of that
    leg. So this is the carry of a **paid belly** (Citi's hedge). A positive
    number means the hedge earns; Citi claims *"+4bp over 3m"* on the short
    2s5s10s fly.
    """
    missing = [t for t in spec.tenors if t not in carry.columns]
    if missing:
        raise KeyError(f"{spec.fly_id}: carry panel is missing {missing}")
    wf = w_front if np.isscalar(w_front) else pd.Series(w_front).reindex(carry.index)
    wk = w_back if np.isscalar(w_back) else pd.Series(w_back).reindex(carry.index)
    return (-np.abs(wf) * carry[spec.front] + carry[spec.belly]
            - np.abs(wk) * carry[spec.back])


# ===========================================================================
# Weighting mode 2: the regression
# ===========================================================================
@dataclass(frozen=True)
class FlyFit:
    """One trailing regression ``CA(bp) ~ a + b_f*r_f + b_b*r_b + b_k*r_k``.

    Citi's own method, §5.2: *"we regressed Blues CA on 2y, 5y and 10y swap
    rates ... with the fitted value effectively being a 2s5s10s fly with
    -0.73/1/-0.47 DV01 weights"*. Re-estimated, never frozen: the same note
    reprinted -0.705/1/-0.465 and beta 20.6 three weeks later.
    """

    fly_id: str
    alpha: float
    beta: float          # = b_belly, bp of CA per PERCENT of fly
    w_front: float       # = -b_front/beta, belly normalised to 1
    w_back: float
    r2: float
    n_obs: int
    ok: bool
    reason: str = ""

    def fitted_ca_bp(self, r_front: float, r_belly: float, r_back: float) -> float:
        """``alpha + beta * (-w_f*r_f + r_b - w_k*r_k)``, rates in percent."""
        return self.alpha + self.beta * (-self.w_front * r_front + r_belly
                                         - self.w_back * r_back)

    @property
    def wings(self) -> Tuple[float, float]:
        return (self.w_front, self.w_back)


def fly_regression(
    ca: pd.Series,
    legs: pd.DataFrame,
    spec: FlySpec,
    *,
    window_days: int = 252,
    require_positive_wings: bool = False,
    min_abs_beta: float = 1.0,
    basis: str = "levels",
) -> FlyFit:
    """Citi's regression, generalised to any fly -- **delegated, not re-derived**.

    The estimator itself is
    :func:`RVUtils.ConvexityRV.strat2_sofr_convexity.hedge_regression`, which is
    already tested against Citi's published chart annotations. All this does is
    hand it a config whose ``hedge_tenors`` are this fly's three leg keys, so
    "2Yx2Y / 2Yx5Y / 2Yx10Y" runs through exactly the code path "2Y / 5Y / 10Y"
    does. A second implementation of the same least squares would be a second
    thing to get wrong.

    ``basis``
        ``"levels"`` is Citi's, verbatim: *"we regressed Blues CA on 2y, 5y and
        10y swap rates"*, and its chart annotation is a level fit
        (``10.2 + 21.4*fly``). ``"changes"`` runs the identical estimator on
        first differences of both sides.

        This is not a cosmetic option. On 2019-2023 SOFR data the LEVEL fit is
        the textbook spurious regression -- both sides are near-unit-root, the
        reported ``R^2`` is 0.21-0.74, and yet the fitted ``beta`` changes SIGN
        on 11-77% of re-estimations depending on rank and window (measured; see
        the grid's weights table). A hedge ratio whose sign is a coin flip is
        not a hedge, and the level ``R^2`` gives no warning. The changes fit
        estimates the thing the P&L actually depends on -- ``dCA`` per ``dfly``
        -- so it is the control that says whether Citi's *instrument* fails here
        or only Citi's *estimator*.

    ``require_positive_wings=False`` by default here, unlike the strategy
    config: across 45 flies a negative fitted wing is a *finding* about that
    fly's relationship to the CA, and the grid needs to see it scored rather
    than dropped. A fly with a negative wing cannot be expressed through
    ``IRSwapStructure.FLY`` (the sign mapper forces wings opposite the belly),
    so ``ok=False`` still marks it untradeable as a fly -- it is simply not
    excluded from the diagnostics.

    The window is strictly trailing and must END at or before the entry date;
    the caller owns that slice. Nothing here looks forward.
    """
    from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config, hedge_regression

    if basis not in ("levels", "changes"):
        raise ValueError(f"bad regression basis {basis!r}")
    if basis == "changes":
        ca = ca.diff()
        legs = legs.diff()
    cfg = Strat2Config(
        hedge_tenors=spec.tenors,
        hedge_regression_days=int(window_days),
        hedge_min_abs_beta=float(min_abs_beta),
        hedge_require_positive_wings=bool(require_positive_wings),
    )
    fit = hedge_regression(ca, legs, cfg)
    return FlyFit(
        fly_id=spec.fly_id, alpha=fit.alpha, beta=fit.beta,
        w_front=fit.w2, w_back=fit.w10, r2=fit.r2, n_obs=fit.n_obs,
        ok=bool(fit.ok), reason=fit.reason,
    )


# ===========================================================================
# Second-order (gamma) coefficients
# ===========================================================================
def annuity_duration(start_y: float, tenor_y: float, rate_pct: float) -> float:
    """DF-weighted mean payment time of a swap's annuity, in years.

    ``d(PV01)/d(rate)`` is what makes a swap's P&L second-order, and it is
    ``-PV01 * D`` with ``D`` this duration. The closed form for a continuously
    discounted annuity over ``[s, s+n]`` is

        D = s + 1/r - n / (exp(r*n) - 1)

    plus ``+0.125`` for quarterly-in-arrears payment timing (the mean of
    ``0.25, 0.5, ... , n`` sits an eighth of a year past the mid-accrual point).
    The naive ``s + n/2 + 0.125`` is *wrong at the long end* -- it ignores
    discounting entirely.

    **Measured against ``rl.IRS.analytic_delta`` at 0 and +25bp on 2023-06-09**
    (``D_measured = -(A(25) - A(0)) / A(0) / 25bp``):

    ==========  ==========  ===========  ========  ==========  ========
    leg         D measured  D this form  error     D naive     error
    ==========  ==========  ===========  ========  ==========  ========
    2Y             1.133       1.110      -2.03%     1.125      -0.71%
    5Y             2.585       2.548      -1.43%     2.625      +1.55%
    10Y            4.889       4.836      -1.09%     5.125      +4.83%
    30Y           12.697      12.757      +0.47%    15.125     +19.12%
    2Yx2Y          3.152       3.115      -1.19%     3.125      -0.86%
    2Yx5Y          4.603       4.560      -0.94%     4.625      +0.48%
    2Yx10Y         6.890       6.857      -0.48%     7.125      +3.41%
    3Yx5Y          5.605       5.560      -0.81%     5.625      +0.36%
    5Yx5Y          7.594       7.558      -0.48%     7.625      +0.41%
    ==========  ==========  ===========  ========  ==========  ========

    i.e. within 2.1% everywhere, against up to 19.1% for the naive form. Good
    enough for a *correction term*; it is not a substitute for repricing.
    """
    r = float(rate_pct) / 100.0
    n = float(tenor_y)
    s = float(start_y)
    if n <= 0:
        return s
    if abs(r) < 1e-8:
        return s + n / 2.0 + 0.125
    return s + 1.0 / r - n / (math.expm1(r * n)) + 0.125


def fly_gamma_per_bp2(spec: FlySpec, rates: Any, w_front: float, w_back: float,
                      belly_dv01: float) -> float:
    """$ of second-order P&L per (bp of parallel rate move)^2, for a PAID belly.

    A par swap's NPV in a rate move ``x`` bp is ``PV01*x - PV01*D*1e-4*x^2``
    (the ``1/2`` cancels against the ``2A'`` in ``d^2NPV/dr^2 = 2A'``): a payer
    is CONCAVE in rates, which is exactly why long-futures-versus-pay-fixed is
    short convexity. Summing over the three legs at ``PV01_i = w_i * bpv``::

        gamma_$ per bp^2 = -belly_DV01 * 1e-4 * ( D_belly - w_f*D_f - w_k*D_k )

    For a 50/50 2s5s10s the bracket is ``2.585 - 0.5*1.133 - 0.5*4.889 = -0.426``
    -> the paid belly is slightly LONG gamma, a small offset to the CA leg's
    short-gamma bleed. Reported, not assumed.
    """
    d_f = annuity_duration(spec.forward_start_y, spec.front_y, float(rates[spec.front]))
    d_b = annuity_duration(spec.forward_start_y, spec.belly_y, float(rates[spec.belly]))
    d_k = annuity_duration(spec.forward_start_y, spec.back_y, float(rates[spec.back]))
    bracket = d_b - abs(float(w_front)) * d_f - abs(float(w_back)) * d_k
    return -float(belly_dv01) * 1e-4 * bracket


# ===========================================================================
# The panel builder
# ===========================================================================
#: Horizon for the per-leg carry-and-roll column. Citi quotes the fly's carry
#: *"over a 3m term"*, and the CA leg's carry is the ``3m Roll`` column.
CARRY_HORIZON = "3M"


def leg_metrics_for_date(pricer: Any, tenors: Sequence[str], *, curve: str,
                         carry_horizon: Optional[str] = CARRY_HORIZON) -> Dict[str, Dict[str, float]]:
    """Par rate (percent) and carry+roll (bp) for every tenor, off ONE pricer.

    One curve build per date, then ~19ms per par rate and ~34ms per carry query
    (measured, 2023-06-09, ``USD-SOFR-1D``). A tenor that raises is omitted from
    the result rather than filled -- a missing leg must propagate as NaN into
    the fly, not as a stale rate.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from RVUtils.ConvexityRV.strat2_sofr_convexity import _swap_par_rate

    out: Dict[str, Dict[str, float]] = {}
    for t in tenors:
        row: Dict[str, float] = {}
        try:
            r = _swap_par_rate(pricer, curve, tenor=t)
            if np.isfinite(r):
                row["rate_pct"] = float(r)
        except Exception:                                     # noqa: BLE001
            pass
        if carry_horizon:
            try:
                q = IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING,
                    curve=curve, tenor=t,
                    structure_kwargs={"bpv": 1.0, "horizon": carry_horizon})
                pkg, w = q.resolve_package(pricer_or_curve=pricer)
                pkg = [pricer.resolve_pricable(p, ww) for p, ww in zip(pkg, w)]
                vm = q.build_value_map(pricer_or_curve=pricer, package=pkg, risk_weights=w)
                c = float(vm.apply(value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING,
                                   horizon=carry_horizon))
                if np.isfinite(c):
                    row["carry_roll_bp"] = c
            except Exception:                                 # noqa: BLE001
                pass
        if row:
            out[t] = row
    return out


def _to_date(d: Any) -> datetime.date:
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, datetime.date):
        return d
    return pd.Timestamp(d).date()


def _legs_chunk(args: Tuple[Sequence[Any], Tuple[str, ...], str, str, Optional[str]]) -> List[Dict[str, Any]]:
    """Worker: one contiguous block of dates. Module-level, because Windows spawn.

    Each date gets ONE ``get_pricer`` call and every tenor is evaluated off it.
    The holiday-ghost filter (``reference_date() != requested``) is applied here
    -- the store serves the previous close for a non-business day, which would
    duplicate a day of rates into the panel.
    """
    days, tenors, curve, source, horizon = args
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source=source)
    rows: List[Dict[str, Any]] = []
    for d in days:
        day = _to_date(d)
        try:
            pricer = mdp.get_pricer({"curve_name": curve, "timestamp": day, "offline": True})
            ref = pricer.reference_date()
            ref = ref.date() if hasattr(ref, "date") else ref
            if ref != day:
                continue
            metrics = leg_metrics_for_date(pricer, tenors, curve=curve, carry_horizon=horizon)
        except Exception:                                     # noqa: BLE001
            continue
        for t, m in metrics.items():
            rows.append({"date": pd.Timestamp(day), "tenor": t,
                         "rate_pct": m.get("rate_pct", np.nan),
                         "carry_roll_bp": m.get("carry_roll_bp", np.nan)})
    return rows


def build_fly_leg_panel(
    dates: Sequence[Any],
    *,
    tenors: Optional[Sequence[str]] = None,
    curve: str = "USD-SOFR-1D",
    source: str = "CITIVELO_EXCEL",
    carry_horizon: Optional[str] = CARRY_HORIZON,
    workers: int = 6,
    chunk: int = 60,
    progress: bool = True,
) -> pd.DataFrame:
    """Long panel ``(date, tenor) -> rate_pct, carry_roll_bp``, multiprocess.

    This is the expensive artifact and the only one that touches market data.
    Everything else in this module -- every fly, every weighting, every carry --
    is arithmetic on top of it, which is the whole point of storing legs rather
    than flies.

    Cost, measured: ~0.7s to build a curve, ~19ms per par rate, ~34ms per carry
    query. 40 tenors with carry is ~2.8s/date single-threaded.
    """
    tenors = tuple(tenors) if tenors is not None else universe_tenors()
    days = list(dates)
    blocks = [days[i:i + chunk] for i in range(0, len(days), chunk)]
    if progress:
        print(f"fly legs: {len(days)} dates x {len(tenors)} tenors in {len(blocks)} "
              f"blocks, {workers} workers", flush=True)
    t0 = time.time()
    rows: List[Dict[str, Any]] = []
    args = [(b, tenors, curve, source, carry_horizon) for b in blocks]
    if workers <= 1:
        for i, a in enumerate(args):
            rows.extend(_legs_chunk(a))
            if progress:
                print(f"  block {i + 1}/{len(blocks)} ({time.time() - t0:.0f}s)", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_legs_chunk, a): i for i, a in enumerate(args)}
            done = 0
            for fut in as_completed(futs):
                rows.extend(fut.result())
                done += 1
                if progress:
                    print(f"  block {done}/{len(blocks)} ({time.time() - t0:.0f}s)", flush=True)
    if not rows:
        return pd.DataFrame(columns=["date", "tenor", "rate_pct", "carry_roll_bp"])
    out = (pd.DataFrame(rows).drop_duplicates(subset=["date", "tenor"])
           .sort_values(["date", "tenor"]).reset_index(drop=True))
    if progress:
        print(f"fly legs {out.shape} in {time.time() - t0:.0f}s "
              f"({out['date'].nunique()} dates, {out['tenor'].nunique()} tenors)", flush=True)
    return out


def legs_wide(legs: pd.DataFrame, value: str = "rate_pct") -> pd.DataFrame:
    """Long leg panel -> wide ``date x tenor``."""
    return legs.pivot_table(index="date", columns="tenor", values=value,
                            aggfunc="last").sort_index()


def fly_panel_from_legs(
    legs: pd.DataFrame,
    specs: Optional[Sequence[FlySpec]] = None,
    *,
    w_front: float = DV01_NEUTRAL_WINGS[0],
    w_back: float = DV01_NEUTRAL_WINGS[1],
) -> pd.DataFrame:
    """Long panel ``(date, fly_id) -> fly_bp, carry_roll_3m_bp`` + geometry.

    **The stored weighting is DV01-neutral (50/50 wings, belly 1).** The
    regression weighting is not storable as a panel: its weights depend on which
    pack's CA you regress on and on the estimation window, so it is computed by
    the grid at each entry and applied to the *leg* panel. Storing one weighting
    and deriving the other is the only arrangement that cannot go stale.
    """
    specs = list(specs) if specs is not None else fly_universe()
    rates = legs_wide(legs, "rate_pct")
    carry = legs_wide(legs, "carry_roll_bp") if "carry_roll_bp" in legs.columns else None
    parts: List[pd.DataFrame] = []
    for s in specs:
        if any(t not in rates.columns for t in s.tenors):
            continue
        df = pd.DataFrame(index=rates.index)
        df["fly_bp"] = fly_rate_series(rates, s, w_front, w_back)
        if carry is not None and all(t in carry.columns for t in s.tenors):
            df["carry_roll_3m_bp"] = fly_carry_series(carry, s, w_front, w_back)
        else:
            df["carry_roll_3m_bp"] = np.nan
        df["fly_id"] = s.fly_id
        df["shape"] = s.shape
        df["forward_start_y"] = s.forward_start_y
        df["front"] = s.front
        df["belly"] = s.belly
        df["back"] = s.back
        df["w_front"] = float(w_front)
        df["w_back"] = float(w_back)
        parts.append(df.reset_index())
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    cols = ["date", "fly_id", "shape", "forward_start_y", "front", "belly", "back",
            "w_front", "w_back", "fly_bp", "carry_roll_3m_bp"]
    return out[cols].sort_values(["date", "fly_id"]).reset_index(drop=True)


def build_and_write_panels(
    dates: Sequence[Any],
    *,
    workers: int = 6,
    curve: str = "USD-SOFR-1D",
    source: str = "CITIVELO_EXCEL",
    out_dir: Optional[pathlib.Path] = None,
    progress: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build both panels and write them. Returns ``(legs, flies)``."""
    out_dir = pathlib.Path(out_dir) if out_dir is not None else PANEL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    legs = build_fly_leg_panel(dates, curve=curve, source=source, workers=workers,
                               progress=progress)
    flies = fly_panel_from_legs(legs)
    legs.to_parquet(out_dir / LEGS_PARQUET.name, index=False)
    flies.to_parquet(out_dir / FLY_PARQUET.name, index=False)
    if progress:
        print(f"wrote {out_dir / LEGS_PARQUET.name} {legs.shape}", flush=True)
        print(f"wrote {out_dir / FLY_PARQUET.name} {flies.shape}", flush=True)
    return legs, flies
