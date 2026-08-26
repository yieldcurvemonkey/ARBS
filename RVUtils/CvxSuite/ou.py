"""OU / first-passage layer for the kink screen — canonical re-exports plus a
distribution-preserving FPT sampler.

Everything mean-reversion-shaped in CvxSuite flows through this module so the
screen has ONE fit convention. The fit/analytic kernels are re-exported
**unchanged** from :mod:`RVUtils.mean_reversion` (the canonical home — its
``half_life`` docstring records that eleven independent half-life
implementations with three different non-reverting sentinels existed across
the repo before consolidation; ``rolling_ar1`` is the vectorised fit, measured
62x faster than looping ``calibrate_ou`` — 0.091s vs 5.66s on 2,074 bars x 26
keys at window 120, ``notebooks/rv/_profile_meanrev.py``).

What is NEW here, and why
-------------------------
``mean_reversion.first_passage_time`` (mean_reversion.py:154) is a correct MC
expected-FPT kernel, but it reads the **global** numpy RNG ("Seed numpy
(np.random.seed) before calling" — its own docstring) and **discards the
per-path hit times** at mean_reversion.py:177, returning only their mean with
censored paths already folded in as ``steps``. The kink screen needs the hit
*distribution* (quantiles, P(hit), P(tau > breakeven horizon)) and the
explicit-``np.random.Generator`` policy of ``RVUtils.StatisticalFinance``. So
:func:`fpt_sample` re-implements the **exact same discretisation**
(``phi = exp(-kappa*dt)``, exact conditional step std
``sigma*sqrt((1-exp(-2*kappa*dt))/(2*kappa))`` — the transition density is
exact at the grid times, not an Euler scheme) but takes an explicit Generator
and returns the per-path array with ``np.inf`` marking censored paths.
``mean_reversion.first_passage_time`` is left untouched.

**What this is NOT:** not a wrapper over ``mean_reversion.first_passage_time``
(global RNG, per-path hits discarded), and that name is deliberately NOT
re-exported here — importing it from this module would silently reintroduce
the global-RNG seeding trap (`reference_seeded_rng_row_order`).

Verified anchors carried by the tests
-------------------------------------
* ``expected_passage_time`` (Bertram 2010 series, Gamma in the NUMERATOR) is
  MC-verified in its own docstring: E[tau(-1 -> +1)] on the standardized OU
  measures 3.042 by Monte Carlo against 2.995 from the series (residual =
  Euler overshoot at dt=5e-4); the Gamma-in-denominator variant previously
  shipped gave 1.366 (mean_reversion.py:333-345). :func:`fpt_sample` re-run
  on this machine at dt=1e-3, sims=2000, seed 20260826 measures 3.0146 —
  inside the same overshoot band.
* Single-step law: with kappa=1, dt=0.5, sigma=sqrt(2), x0=-1, target=+1 the
  exact one-step hit probability is Phi-complement((1+0.6065)/0.7951) =
  0.021658; the Euler step-std variant would give 0.054079. Measured here:
  0.02173 at 200k sims (seed 20260826).

Units (binding)
---------------
Hit times are **step indices** (1..steps): time = hits * dt. Calibrated on
daily data with ``dt=1.0`` (the section-6 frozen config: sims 2000, steps 504,
seed 20260826) a hit of 63.0 IS 63 business days. ``sigma`` in ``params`` is
the OU diffusion sigma (per sqrt(unit time)), NOT the equilibrium sigma_eq =
sigma/sqrt(2*kappa).

Censoring bias (stated, as in the source docstring): treating censored paths
as ``steps`` biases ``e_fpt`` LOW whenever censoring is material (small kappa
/ far target) — the canonical kernel carries the same caveat ("censoring bias
at small kappa"). ``frac_censored`` is printed next to ``e_fpt`` so the bias
is never invisible.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np

# Canonical re-exports — unchanged, per docs/cvxsuite/DESIGN.md section 3.
from RVUtils.mean_reversion import (  # noqa: F401
    calibrate_ou,
    ou_mle,
    half_life,
    rolling_ar1,
    rolling_half_life,
    ou_conditional,
    ou_ex_ante_sharpe,
    expected_passage_time,
)

__all__ = [
    # re-exports
    "calibrate_ou",
    "ou_mle",
    "half_life",
    "rolling_ar1",
    "rolling_half_life",
    "ou_conditional",
    "ou_ex_ante_sharpe",
    "expected_passage_time",
    # new
    "fpt_sample",
    "fpt_stats",
    "carry_over_horizon",
    "p_fpt_exceeds",
]


def fpt_sample(x0: float, target: float, params: Mapping[str, float], *,
               sims: int = 2000, steps: int = 504, dt: float = 1.0,
               rng: np.random.Generator) -> np.ndarray:
    """Per-path first-passage times from ``x0`` to ``target`` under the OU fit.

    Same discretisation as ``mean_reversion.first_passage_time``: exact AR(1)
    transition ``x_{t+1} = mu + phi*(x_t - mu) + s_step*Z`` with
    ``phi = exp(-kappa*dt)`` and ``s_step = sigma*sqrt((1-exp(-2*kappa*dt)) /
    (2*kappa))`` — the grid marginals are exactly OU, so the only bias against
    the continuous-time passage law is discrete monitoring (overshoot),
    measured at +0.047 on E[tau(-1 -> +1)] at dt=5e-4 (mean_reversion.py:341).

    Differences from the canonical kernel, by design:

    * draws come from the **explicit** ``rng`` (required, keyword-only) — the
      canonical reads the global numpy RNG;
    * returns the full ``(sims,)`` array of hit step-indices; paths that never
      reach ``target`` within ``steps`` are ``np.inf`` (the canonical folds
      them in as ``steps`` and returns only the mean);
    * non-finite ``x0``/``target`` or unusable params (kappa not finite/<=0,
      sigma not finite/<0, mu not finite — e.g. a ``calibrate_ou`` NaN fit)
      return an all-NaN array of length ``sims``, mirroring the canonical's
      scalar NaN. NaN means "no fit", inf means "did not hit": the two are
      distinct and neither is a silent zero.

    Units: hit times are step indices (1..steps); multiply by ``dt`` for time
    units. With ``dt=1.0`` on a daily calibration they are business days.
    The barrier side is decided once from ``x0 <= target`` (upcrossing) —
    ``t=0`` is not checked, matching the canonical kernel.
    """
    if not isinstance(rng, np.random.Generator):
        raise TypeError(
            "rng must be a numpy.random.Generator (e.g. np.random.default_rng(20260826)); "
            "got %r — this module never reads the global numpy RNG" % type(rng).__name__
        )
    sims_i = int(sims)
    steps_i = int(steps)
    if sims_i < 1:
        raise ValueError(f"sims must be >= 1, got {sims}")
    if steps_i < 1:
        raise ValueError(f"steps must be >= 1, got {steps}")
    if not (np.isfinite(dt) and dt > 0):
        raise ValueError(f"dt must be finite and > 0, got {dt}")

    kappa = params.get("kappa", np.nan)
    mu = params.get("mu", np.nan)
    sigma = params.get("sigma", np.nan)
    usable = (np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma >= 0
              and np.isfinite(mu) and np.isfinite(x0) and np.isfinite(target))
    if not usable:
        return np.full(sims_i, np.nan)

    # --- exact-discretisation step, copied from mean_reversion.first_passage_time ---
    phi = np.exp(-kappa * dt)
    s_step = sigma * np.sqrt(max(0.0, (1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa)))
    x = np.full(sims_i, float(x0))
    hit = np.full(sims_i, np.inf)          # censored sentinel: inf (NOT steps)
    done = np.zeros(sims_i, dtype=bool)
    up = x0 <= target
    for t in range(1, steps_i + 1):
        x = mu + phi * (x - mu) + s_step * rng.standard_normal(sims_i)
        newly = (~done) & ((x >= target) if up else (x <= target))
        hit[newly] = t
        done |= newly
        if done.all():
            break
    return hit


def fpt_stats(hits: np.ndarray, *, steps: float | None = None) -> dict:
    """Summary of a :func:`fpt_sample` hit array.

    Returns ``{e_fpt, p_hit, q25, q50, q75, frac_censored}``.

    * ``e_fpt`` treats censored paths as ``steps`` — the same convention as
      ``mean_reversion.first_passage_time`` — so it is biased LOW whenever
      censoring is material (the source docstring's "censoring bias at small
      kappa" caveat; read it next to ``frac_censored``). ``steps`` must be
      passed (in the same units as ``hits``, i.e. step indices) whenever any
      path is censored; a censored array with ``steps=None`` raises rather
      than guessing the cap. With no censoring ``steps`` is unused.
    * ``p_hit`` = fraction of paths that hit within the cap.
    * Quantiles are defined over ALL paths, censored included, so ``inf`` is a
      legal answer (q50 = inf means the median path never reverted inside the
      cap — that IS the finding, not an error). They are order statistics
      (``np.quantile(..., method="lower")``): linear interpolation is
      undefined between two censored paths (inf - inf = NaN on numpy 2.2.6,
      measured), and an interpolated quantile into the censored region would
      manufacture a finite number for a path that never hit.
    * An input containing NaN (the :func:`fpt_sample` no-fit path) returns all
      fields NaN — checked FIRST, so a no-fit array is never misread as
      0%-censored/0%-hit.
    """
    h = np.asarray(hits, dtype=float)
    if h.size == 0:
        raise ValueError("fpt_stats: empty hits array")
    nan_out = {"e_fpt": np.nan, "p_hit": np.nan, "q25": np.nan, "q50": np.nan,
               "q75": np.nan, "frac_censored": np.nan}
    if np.isnan(h).any():
        return nan_out
    censored = np.isinf(h)
    frac_censored = float(censored.mean())
    if censored.any():
        if steps is None:
            raise ValueError(
                "fpt_stats: %d of %d paths are censored (inf) and steps=None — "
                "pass steps=<the fpt_sample cap> so e_fpt can apply the "
                "censored->steps convention" % (int(censored.sum()), h.size)
            )
        e_fpt = float(np.where(censored, float(steps), h).mean())
    else:
        e_fpt = float(h.mean())
    q25, q50, q75 = (float(np.quantile(h, q, method="lower")) for q in (0.25, 0.50, 0.75))
    return {"e_fpt": e_fpt, "p_hit": 1.0 - frac_censored, "q25": q25, "q50": q50,
            "q75": q75, "frac_censored": frac_censored}


def carry_over_horizon(carry_bp_day: float, horizon_days: float) -> float:
    """Signed carry accrued over a horizon: ``carry_bp_day * horizon_days`` (bp).

    Pure arithmetic on the ledger-boundary unit (bp/day — DESIGN section 1);
    there is no annualisation and no sqrt anywhere in this function. Negative
    carry over a positive horizon is negative bp. NaN in, NaN out.
    """
    return float(carry_bp_day) * float(horizon_days)


def p_fpt_exceeds(hits: np.ndarray, days: float) -> float:
    """P(first passage takes longer than ``days``) — Huggins-Schaller fn 24.

    The pre-entry question: what fraction of simulated reversions take longer
    than the carry breakeven horizon. Strictly ``hits > days``; censored paths
    (``inf``) always count as exceeding — a path that never reverted inside
    the cap certainly took longer than the horizon. ``days`` must be in the
    SAME units as ``hits`` — step indices, which are business days under the
    dt=1.0 daily convention; at any other ``dt`` convert with time = hits*dt
    before calling, or pass ``days`` in steps.

    NaN anywhere in ``hits`` (the no-fit path) or a non-finite ``days``
    returns NaN — checked FIRST, because ``NaN > days`` is False and would
    otherwise silently undercount.
    """
    h = np.asarray(hits, dtype=float)
    if h.size == 0:
        raise ValueError("p_fpt_exceeds: empty hits array")
    if np.isnan(h).any() or not np.isfinite(days):
        return float("nan")
    return float((h > float(days)).mean())
