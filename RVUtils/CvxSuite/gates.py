"""Entry gates for the CvxSuite screens: degeneracy, support, compose-price,
eigenvector continuity, and the Huggins-Schaller cloud diagnostic.

Every gate is fail-closed: a NaN or missing input FAILS the gate (returns
False), it never passes silently — a gate that waves through the rows it
could not evaluate is the silent-fallback trap
(``reference_silent_fallback_mislabels``). Structural errors (empty axes,
empty mapping) raise ``ValueError`` loudly instead. All thresholds are
INCLUSIVE at the boundary (``>= floor``, ``<= tol_bp``, ``>= min_cos``,
``<= max_abs_corr``, closed envelope ends).

Evidence behind the defaults (all measured or quoted with attribution)
----------------------------------------------------------------------
* ``degeneracy_gate`` floor **0.25 bp/day**: the CurveFlyScreener gate
  (``scripts/_curvefly_screen.py:58-72``) — 47 structures whose legs span no
  curve node have near-constant levels and their rac explodes; "the
  highest-ranked rows if you do not remove them, and they are not trades".
* ``compose_price_gate`` tolerance **3.0 bp**
  (``scripts/_curvefly_screen.py:39-54``): the level composed from the
  warmed leg history against the same level priced off the live curve — "a
  big gap means two vintages and untrustworthy z".
* ``support_gate``: never price outside the day's quoted envelope —
  "extrapolating a vol surface off the end of its own grid is how a backtest
  acquires prices no one quoted" (``RVUtils/BasisVsVol/v3_panel.py:135-136``).
  The cube's axes VARY BY DAY (measured 2026-08-24: 8 tenors against the
  historical 9) and the expiry axis has NO 25Y node anywhere
  (``MDP/CitiVelocityExcel/vol/cube_data.py:136-140``) — so feed this gate
  from ``vols.quoted_axes(date)``, never a hardcoded grid. A 25y expiry is
  INSIDE the 1M..30Y envelope (interior interpolation, passes); the
  KINK_GRID point 40y10y is OUTSIDE (40 > 30) and fails BY DESIGN — the
  screen must expect a NaN sigma_impl there.
* ``eigenvector_gap_gate``: ``pca_rv.align_eigenvectors`` (pca_rv.py:230)
  "fixes SIGN flips, which is the common case and not the dangerous one. The
  dangerous case is a ROTATION: on a short early window PC2 and PC3 can swap
  rank, and an eigenvalue-ordered pick would then call curvature 'slope' and
  hedge the wrong factor with the right arithmetic"
  (``ConvexityRV/factor_neutral_sizing._match_pcs``,
  factor_neutral_sizing.py:1104-1127). This gate is the thresholded check
  the recon found missing everywhere: it consumes the per-PC |cos| vs the
  previous refit (``residuals.walk_forward_pca_residuals`` info["cos_prev"],
  produced AFTER greedy |cos| permutation matching) and fails any PC below
  ``min_cos``. |cos| is taken here too, so a raw signed feed cannot fail on
  a benign sign flip — only a genuine rotation (small |cos|) fails.
* ``cloud_diagnostic``: the Huggins-Schaller pre-entry test — trailing
  correlation of the candidate structure's changes against PC1's changes;
  screening out candidates that are the level factor in disguise is the
  H-S 82-to-90 percent hit-rate device (recon "stats" note; H-S, Fixed
  Income Relative Value Analysis). A structure passing PCA-residual math can
  still be a directional cloud; this measures it pre-entry.

What this is NOT
----------------
* ``eigenvector_gap_gate`` is NOT ``align_eigenvectors`` (sign-only repair)
  and NOT ``_match_pcs`` (the matcher). It neither repairs nor matches — it
  REFUSES: matching/aligning happens upstream in residuals.py; this gate
  says whether the matched factors are still the same factors.
* ``cloud_diagnostic`` is NOT a hedge-ratio estimator: vol/level betas here
  gate entry only; a fly is not a vol proxy and PC1 is not a hedge pair at
  the trade horizon (``reference_fly_not_a_vol_proxy``,
  ``reference_hedge_ratio_horizon``).
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Union

import numpy as np
import pandas as pd

__all__ = [
    "degeneracy_gate",
    "support_gate",
    "compose_price_gate",
    "eigenvector_gap_gate",
    "cloud_diagnostic",
]

_TENOR_RE = re.compile(r"^(\d+)\s*([MY])$")


def _years(x, axis_name: str) -> float:
    """Axis element -> years. Strings via the 1M/18M/5Y grammar; numerics pass.

    Mirrors ``vols.tenor_years`` / ``v3_panel.tenor_years`` (duplicated here
    because C1 modules may not import each other — DESIGN section 3). Unlike
    the vols version, an unparseable AXIS element raises: a support gate fed
    a corrupt axis must not quietly shrink its envelope.
    """
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    m = _TENOR_RE.match(str(x).strip().upper())
    if not m:
        raise ValueError(
            f"support_gate: unparseable {axis_name} element {x!r} "
            "(expected years as a number or a '1M'/'18M'/'5Y' label)")
    n, unit = int(m.group(1)), m.group(2)
    return n / 12.0 if unit == "M" else float(n)


def _axis(values: Iterable, axis_name: str) -> np.ndarray:
    vals = [_years(v, axis_name) for v in values]
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError(
            f"support_gate: empty {axis_name} axis - a gate with no quoted "
            "axis cannot answer; feed it vols.quoted_axes(date) for the day.")
    return arr


def degeneracy_gate(realized_bp_day: Union[pd.Series, float],
                    floor: float = 0.25) -> Union[bool, pd.Series]:
    """True where realized vol clears the floor (tradeable), False below/NaN.

    The CurveFlyScreener VOL_FLOOR gate (0.25 bp/day,
    ``scripts/_curvefly_screen.py:58-72``): a near-constant level series
    makes every risk-adjusted ranking explode and its rows are not trades.
    Inclusive at the floor (``>= floor`` passes). NaN fails — an unmeasured
    vol is not evidence of a tradeable one.

    Scalar in -> plain ``bool`` out; Series in -> boolean Series out.
    """
    f = float(floor)
    if isinstance(realized_bp_day, pd.Series):
        v = pd.to_numeric(realized_bp_day, errors="coerce")
        return v.ge(f).fillna(False).astype(bool)
    v = float(realized_bp_day)
    return bool(np.isfinite(v) and v >= f)


def support_gate(expiry_y, tail_y, *, expiries, tenors) -> bool:
    """Is (expiry_y, tail_y) inside the quoted axes' envelope? Fail-closed.

    "Inside" means within the CLOSED interval [min, max] of each axis —
    interior interpolation between quoted nodes is allowed (the no-25Y-node
    expiry axis is the canonical case: 25y sits between 20Y and 30Y and
    passes), extrapolation past either end is not (40y10y fails by design).
    Axes accept years as numbers or '1M'/'18M'/'5Y' labels (the cube's own
    ``expiries()``/``tenors()`` are labels); empty axes raise; NaN
    coordinates fail.
    """
    e_axis = _axis(expiries, "expiries")
    t_axis = _axis(tenors, "tenors")
    try:
        e, t = float(expiry_y), float(tail_y)
    except (TypeError, ValueError):
        return False
    if not (np.isfinite(e) and np.isfinite(t)):
        return False
    return bool(e_axis.min() <= e <= e_axis.max()
                and t_axis.min() <= t <= t_axis.max())


def compose_price_gate(composed_bp: float, priced_bp: float,
                       tol_bp: float = 3.0) -> bool:
    """True when |composed - priced| <= tol_bp; False on any NaN. Fail-closed.

    The two-vintage gate (``scripts/_curvefly_screen.py:39-54``, tolerance
    3.0 bp): the level composed from the warmed leg history against the same
    level priced off the as-of curve. "A big gap means two vintages and
    untrustworthy z" — and a NaN on either side means one vintage is missing
    entirely, which is worse, so it fails too. Inclusive at the tolerance.
    """
    try:
        c, p = float(composed_bp), float(priced_bp)
    except (TypeError, ValueError):
        return False
    if not (np.isfinite(c) and np.isfinite(p)):
        return False
    return bool(abs(c - p) <= float(tol_bp))


def eigenvector_gap_gate(cos_prev: Mapping[str, float], *,
                         min_cos: float = 0.90) -> dict:
    """Per-PC continuity gate on |cos| vs the previous refit's eigenvectors.

    Feed: ``residuals.walk_forward_pca_residuals`` info[month]["cos_prev"] —
    per-PC |cos| AFTER greedy permutation matching (the ``_match_pcs``
    device). A PC passes iff ``|cos| >= min_cos``; the overall gate passes
    iff every PC does. |cos| is applied here as well, so a signed feed can
    only fail on a rotation (small magnitude), never on a benign sign flip —
    sign repair is ``align_eigenvectors``'s job upstream, refusal is this
    gate's. NaN fails that PC (a first refit month has no previous vintage:
    no continuity evidence is not continuity). An empty mapping raises.

    Returns ``{"per_pc": {name: bool}, "pass": bool, "worst_pc": name,
    "worst_cos": float, "min_cos": float}`` (worst = smallest |cos|, NaN
    ranked worst of all).
    """
    if not cos_prev:
        raise ValueError(
            "eigenvector_gap_gate: empty cos_prev mapping - an overall pass "
            "over zero PCs would be vacuous; feed it walk-forward info "
            "['cos_prev'] or do not call it for the first refit.")
    thr = float(min_cos)
    per_pc: dict = {}
    abs_cos: dict = {}
    for name, c in cos_prev.items():
        try:
            cf = float(c)
        except (TypeError, ValueError):
            cf = float("nan")
        a = abs(cf) if np.isfinite(cf) else float("nan")
        abs_cos[name] = a
        per_pc[name] = bool(np.isfinite(a) and a >= thr)
    worst_pc = min(
        abs_cos,
        key=lambda k: abs_cos[k] if np.isfinite(abs_cos[k]) else float("-inf"))
    return {
        "per_pc": per_pc,
        "pass": bool(all(per_pc.values())),
        "worst_pc": worst_pc,
        "worst_cos": abs_cos[worst_pc],
        "min_cos": thr,
    }


def cloud_diagnostic(structure_bp: pd.Series, pc1_scores: pd.Series, *,
                     window: int = 126, max_abs_corr: float = 0.45,
                     min_n: int = 63) -> dict:
    """H-S pre-entry cloud test: trailing corr of structure vs PC1 CHANGES.

    Both inputs are LEVEL-like series (structure in bp, PC1 scores in the
    model's own units — correlation is scale-invariant); they are diffed,
    inner-aligned on their common index, and the LAST ``window`` paired
    changes are correlated (Pearson). Pass iff ``|corr| <= max_abs_corr``
    AND at least ``min_n`` paired changes exist (min_n defaults to half the
    window — the ``rolling_z`` min_periods_frac=0.5 convention in
    citi_screen). Fewer pairs, or a degenerate/NaN correlation (e.g. a
    constant structure), FAILS — an unmeasurable cloud is not a clean one.

    Returns ``{"corr": float, "pass": bool, "n": int, "window": int,
    "max_abs_corr": float}``. Pass=True means the candidate is NOT the level
    factor in disguise — the filter behind the Huggins-Schaller 82-to-90
    percent hit-rate improvement (recon "stats" note).
    """
    ds = pd.Series(structure_bp).astype(float).diff().rename("ds")
    dp = pd.Series(pc1_scores).astype(float).diff().rename("dp")
    both = pd.concat([ds, dp], axis=1).dropna()
    tail = both.tail(int(window))
    n = int(len(tail))
    if n >= 2 and tail["ds"].std(ddof=1) > 0 and tail["dp"].std(ddof=1) > 0:
        corr = float(tail["ds"].corr(tail["dp"]))
    else:
        corr = float("nan")   # degenerate (constant) input: unmeasurable
    ok = bool(n >= int(min_n) and np.isfinite(corr)
              and abs(corr) <= float(max_abs_corr))
    return {"corr": corr, "pass": ok, "n": n, "window": int(window),
            "max_abs_corr": float(max_abs_corr)}
