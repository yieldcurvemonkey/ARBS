r"""Citi's Figure-6 fair-value machinery, promoted out of the reproduction notebook.

Source: Citi Research, *North America Rates Trade Idea*, **09 Feb 2017**,
Bikbov & Williams, "Sell Blues convexity adjustments, hedged" (``print (12).pdf``);
and its origin note, *US Rates Weekly*, **13 Jan 2017**, "Swearing in huge
expectations" §*Smart convexity sells* (``print (15/18).pdf``).  Prose extraction
at ``docs/convexityrv/research/corpus2/g10-print-files.md`` §4 and §8.

The note's own words:

    "To build a more optimal hedging strategy, we regressed Blues CA on 2y, 5y
    and 10y swap rates.  Consistent with the intuition above, the CA are
    generally well explained by these three rates, with the fitted value
    effectively being a 2s5s10s fly with 0.705/-1/0.465 DV01 weights (Figure 6).
    The CA is about 3bp (about 2 sigmas) wide to the fly ... Our trade ... is
    constructed as a convergence trade between the Blues CA and the 2s5s10s fly,
    precisely as illustrated in Figure 6."

So **the weights are an OUTPUT of the regression, not an input**, and the traded
object is ``CA - (a + b*fly)``.  This module is that regression and nothing else:
it is pure arithmetic on an already-built panel of percent par rates and takes no
market data.

Units, stated once and never re-stated
--------------------------------------
* panel par rates are **percent**;
* the fly combination :func:`fly_combo` is therefore in **percent**, and Citi's
  printed fly level (``-18.2bp``) is that combination times 100;
* ``a`` is in **bp of CA**, ``b`` in **bp of CA per PERCENT of fly**, so the
  hedge ratio in bp-per-bp is ``b / 100`` (:func:`hedge_beta_bp_per_bp`) --
  Citi's printed ``b = 20.6`` is ``0.206`` bp of CA per bp of fly;
* a DV01 weight is dimensionless and a notional is in $mm.

The three fits, and why all three are kept
------------------------------------------
``free``
    Citi's own unconstrained 3-rate regression, renormalised to
    ``a + b*(-w2*r2 + r5 - w10*r10)``.  A 3-rate regression does not constrain
    the weights to sum to one and Citi's do not (``-0.705 + 1 - 0.465 = -0.17``),
    so the "fly" is 17% level by construction and the hedge inherits that as
    outright duration.  On SOFR 2022-2026 the three spot rates are nearly
    collinear (condition number ~1e3), the normalisation ``w = -beta/beta5``
    divides by a small noisy number, and the fitted weights leave butterfly
    territory entirely.  Kept because it is the note's own specification.

``fly``
    The same fit with ``w2 + w10 == 1``, so the fitted object is guaranteed to be
    a real butterfly and the hedge is DV01-neutral.  One shape parameter, found
    by a grid over ``w2``.  **This is the fit a tradeable ticket comes from.**

``citi``
    Citi's published ``0.705 / -1 / 0.465`` held fixed with level and scale
    refitted.  A reference line -- and, measured, the scheme with the *lowest*
    out-of-sample residual sd of any tried.

Causality
---------
:func:`imm_refit` re-estimates at every quarterly SR3 IMM roll on a trailing
window ending **strictly before** the roll, and the resulting parameters are in
force from the roll until the next one.  The CA structure itself switches
contracts on that date, so the hedge is re-struck with it and no estimation
window ever straddles a contract switch.

Known answer
------------
``tests/test_convexity_rv_citi_fv.py`` pins this module against the
reproduction's own recorded path on its own window (the mid-2023 sign reversal
of ``b``, the residual-sd ordering, the fly-start ranking) and against Citi's
printed arithmetic (the notionals reproduce the printed DV01 weights; the beta
reproduces the printed belly DV01; the two roll numbers reproduce the printed
$380k carry).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "CITI_FEB2017_A",
    "CITI_FEB2017_B",
    "CITI_FEB2017_W2",
    "CITI_FEB2017_W10",
    "CITI_JAN2017_A",
    "CITI_JAN2017_B",
    "CITI_JAN2017_W2",
    "CITI_JAN2017_W10",
    "FIT_KINDS",
    "FLY_STARTS",
    "MIN_FIT_OBS",
    "SPOT_COLS",
    "W2_GRID",
    "FairValueFit",
    "annuity",
    "dv01_weights_to_notionals",
    "fit_fair_value",
    "fitted_series",
    "fly_combo",
    "hedge_beta_bp_per_bp",
    "imm_refit",
    "refit_summary",
]

#: Citi's printed Figure-6 fit, 09 Feb 2017 (Eurodollars):
#: ``CA_bp = 9.7 + 20.6 * (-0.705*r2 + r5 - 0.465*r10)``, rates in PERCENT.
CITI_FEB2017_A = 9.7
CITI_FEB2017_B = 20.6
CITI_FEB2017_W2 = 0.705
CITI_FEB2017_W10 = 0.465

#: The same regression in the 13 Jan 2017 origin note:
#: ``CA_bp = 10.2 + 21.4 * (-0.73*r2 + r5 - 0.47*r10)``.
CITI_JAN2017_A = 10.2
CITI_JAN2017_B = 21.4
CITI_JAN2017_W2 = 0.73
CITI_JAN2017_W10 = 0.47

FIT_KINDS: Tuple[str, ...] = ("free", "fly", "citi")

#: Minimum overlapping observations for a fit to be returned at all.  The
#: reproduction's own rule, kept verbatim so the promoted module reproduces the
#: notebook path rather than a tidier one.
MIN_FIT_OBS = 60

#: The ``w2`` grid the constrained fit searches, with ``w10 = 1 - w2``.
#: 91 points at 0.01 spacing over [0.05, 0.95]; the endpoints are excluded
#: because a weight at 0 or 1 is a curve, not a butterfly, and the count of
#: refits that land ON the boundary is a reported diagnostic.
W2_GRID: Tuple[float, ...] = tuple(np.round(np.linspace(0.05, 0.95, 91), 10))

#: Default panel column names for the three regressors.  Citi's Figure 6 uses
#: SPOT 2y/5y/10y; the CA is a forward object, so spot is the one start
#: guaranteed not to sit where the risk is -- which is why the alternatives
#: below are carried and ranked rather than assumed away.
SPOT_COLS: Tuple[str, str, str] = ("r2y_pct", "r5y_pct", "r10y_pct")

#: Fly START conventions.  ``IMM_13`` starts at the Blues pack's own front
#: contract, i.e. the matched-expiry case.
FLY_STARTS: Dict[str, Tuple[str, str, str]] = {
    "spot (Citi's own)": SPOT_COLS,
    "IMM_1": ("imm1_2y_pct", "imm1_5y_pct", "imm1_10y_pct"),
    "IMM_2": ("imm2_2y_pct", "imm2_5y_pct", "imm2_10y_pct"),
    "IMM_5 (Reds front)": ("imm5_2y_pct", "imm5_5y_pct", "imm5_10y_pct"),
    "IMM_9 (Greens front)": ("imm9_2y_pct", "imm9_5y_pct", "imm9_10y_pct"),
    "IMM_13 (Blues front)": ("imm13_2y_pct", "imm13_5y_pct", "imm13_10y_pct"),
    "IMM_17 (Golds front)": ("imm17_2y_pct", "imm17_5y_pct", "imm17_10y_pct"),
    "1y fwd (CM)": ("cm1y_2y_pct", "cm1y_5y_pct", "cm1y_10y_pct"),
    "2y fwd (CM)": ("cm2y_2y_pct", "cm2y_5y_pct", "cm2y_10y_pct"),
    "3y fwd (CM)": ("cm3y_2y_pct", "cm3y_5y_pct", "cm3y_10y_pct"),
}


# ---------------------------------------------------------------------------
# 1. The fitted object
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FairValueFit:
    """One fit of ``y ~ a + b*(-w2*r2 + r5 - w10*r10)`` on one window.

    ``a`` is bp of CA, ``b`` is bp of CA per PERCENT of the combination, and
    ``r2`` is the in-sample coefficient of determination (not a 2y rate -- the
    collision of names is unavoidable and this is the only place it occurs).
    """

    a: float
    b: float
    w2: float
    w10: float
    r2: float
    n: int
    kind: str = ""

    @property
    def beta_bp_per_bp(self) -> float:
        """``b / 100`` -- bp of CA per bp of the quoted fly."""
        return self.b / 100.0

    @property
    def net_weight(self) -> float:
        """``-w2 + 1 - w10``: the residual level exposure per unit of belly DV01.

        Zero under the ``fly`` constraint; Citi's own published weights leave
        ``-0.17``, so their hedge is 17% outright duration by construction.
        """
        return -self.w2 + 1.0 - self.w10

    def as_dict(self) -> Dict[str, float]:
        return {"a": self.a, "b": self.b, "w2": self.w2, "w10": self.w10,
                "r2": self.r2, "n": self.n, "kind": self.kind}


def fly_combo(panel: pd.DataFrame, w2: float, w10: float,
              cols: Sequence[str] = SPOT_COLS) -> pd.Series:
    """``-w2*r2 + r5 - w10*r10`` in **percent**, Citi's own combination.

    With ``w2 = w10 = 0.5`` this is exactly half the house ``FLY RATE``
    convention (``2*belly - front - back``), which is the tie between this
    module's units and ``gv_universe``'s.
    """
    c0, c1, c2 = cols
    return (-float(w2) * panel[c0].astype(float)
            + panel[c1].astype(float)
            - float(w10) * panel[c2].astype(float)).rename("fly_pct")


def hedge_beta_bp_per_bp(fit: FairValueFit) -> float:
    return fit.beta_bp_per_bp


def _ols(y: np.ndarray, X: np.ndarray) -> Tuple[np.ndarray, float]:
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ c
    vy = y.var(ddof=0)
    r2 = 1.0 - e.var(ddof=0) / vy if vy > 0 else float("nan")
    return c, float(r2)


def fit_fair_value(y: pd.Series, panel: pd.DataFrame, kind: str,
                   cols: Sequence[str] = SPOT_COLS, *,
                   min_obs: int = MIN_FIT_OBS,
                   fixed_w2: float = CITI_FEB2017_W2,
                   fixed_w10: float = CITI_FEB2017_W10,
                   ) -> Optional[FairValueFit]:
    """One fit on one window.  ``None`` when the window cannot support one.

    ``free``  unconstrained OLS of ``y`` on ``[1, r2, r5, r10]``, renormalised
              to ``w2 = -b2/b5``, ``w10 = -b10/b5``, ``b = b5``;
    ``fly``   grid over ``w2`` with ``w10 = 1 - w2``, best in-sample R2;
    ``citi``  ``fixed_w2 / fixed_w10`` held, level and scale refitted.
    """
    k = str(kind)
    if k not in FIT_KINDS:
        raise ValueError(f"unknown fit kind {kind!r}; declared {FIT_KINDS}")
    cols = list(cols)
    missing = [c for c in cols if c not in panel.columns]
    if missing:
        raise KeyError(f"panel is missing {missing}")

    if k == "free":
        j = pd.concat([pd.Series(y).rename("y"), panel[cols]], axis=1).dropna()
        if len(j) < min_obs:
            return None
        X = np.column_stack([np.ones(len(j))] + [j[c].to_numpy() for c in cols])
        c, r2 = _ols(j["y"].to_numpy(), X)
        a, b2, b5, b10 = c
        if abs(b5) < 1e-9:
            return None
        return FairValueFit(float(a), float(b5), float(-b2 / b5),
                            float(-b10 / b5), r2, int(len(j)), k)

    grid = ([(float(fixed_w2), float(fixed_w10))] if k == "citi"
            else [(float(w), 1.0 - float(w)) for w in W2_GRID])
    best: Optional[FairValueFit] = None
    for w2, w10 in grid:
        x = fly_combo(panel, w2, w10, cols)
        j = pd.concat([pd.Series(y).rename("y"), x.rename("x")], axis=1).dropna()
        if len(j) < min_obs:
            continue
        X = np.column_stack([np.ones(len(j)), j["x"].to_numpy()])
        c, r2 = _ols(j["y"].to_numpy(), X)
        cand = FairValueFit(float(c[0]), float(c[1]), w2, w10, r2, int(len(j)), k)
        if best is None or cand.r2 > best.r2:
            best = cand
    return best


def fitted_series(panel: pd.DataFrame, fit: FairValueFit,
                  cols: Sequence[str] = SPOT_COLS) -> pd.Series:
    """``a + b * fly_combo`` over every date in *panel*."""
    return (fit.a + fit.b * fly_combo(panel, fit.w2, fit.w10, cols)
            ).rename("fitted_ca_bp")


# ---------------------------------------------------------------------------
# 2. The quarterly refit
# ---------------------------------------------------------------------------
def imm_refit(y: pd.Series, panel: pd.DataFrame, kind: str,
              window_bd: int, cols: Sequence[str] = SPOT_COLS, *,
              roll_dates: Optional[Sequence] = None,
              min_obs: int = MIN_FIT_OBS,
              fixed_w2: float = CITI_FEB2017_W2,
              fixed_w10: float = CITI_FEB2017_W10,
              ) -> Tuple[pd.DataFrame, pd.Series]:
    """Refit at every quarterly SR3 IMM roll; apply until the next one.

    Returns ``(weights_frame, fitted_series)``.  The weights frame is indexed by
    ``fit_asof`` -- the last mark the fit could see -- and carries
    ``in_force_from`` / ``in_force_to``, so a reader can check causality from the
    frame alone rather than trusting this docstring.

    **Causal by construction.**  The parameters in force on date ``t`` were
    estimated on marks ending strictly before the roll that put them in force:
    the window is ``panel.iloc[:pos].tail(window_bd)`` where ``pos`` is the
    roll's own position, so the roll date itself is excluded.  Dates before the
    first usable refit are ``NaN`` in the fitted series -- they are not
    back-filled, because a fitted value before its own fit exists is look-ahead
    wearing a convenient shape.

    The window is ``min(window_bd, available)``: early refits legitimately see
    less history, and ``n`` is carried per row so the reader can see it.
    """
    from RVUtils.ConvexityRV.gv_universe import ca_roll_dates

    idx = pd.DatetimeIndex(panel.index)
    rolls = ([pd.Timestamp(d) for d in roll_dates] if roll_dates is not None
             else list(ca_roll_dates(idx)))
    rolls = [r for r in rolls if r in idx]
    rows: List[dict] = []
    fitted = pd.Series(np.nan, index=idx, name="fitted_ca_bp")
    y = pd.Series(y)
    for i, r in enumerate(rolls):
        pos = int(idx.get_loc(r))
        if pos < min_obs:
            continue
        hist = panel.iloc[:pos].tail(int(window_bd))
        fit = fit_fair_value(y.reindex(hist.index), hist, kind, cols,
                             min_obs=min_obs, fixed_w2=fixed_w2,
                             fixed_w10=fixed_w10)
        if fit is None:
            continue
        if i + 1 < len(rolls):
            mask = (idx >= r) & (idx < rolls[i + 1])
        else:
            mask = idx >= r
        if not mask.any():
            continue
        sub = panel.loc[mask]
        fitted.loc[mask] = fitted_series(sub, fit, cols).to_numpy()
        rows.append({"fit_asof": idx[pos - 1], "in_force_from": r,
                     "in_force_to": idx[mask][-1],
                     "fit_start": hist.index[0], "fit_end": hist.index[-1],
                     **fit.as_dict()})
    frame = (pd.DataFrame(rows).set_index("fit_asof") if rows
             else pd.DataFrame(columns=["in_force_from", "in_force_to",
                                        "fit_start", "fit_end", "a", "b", "w2",
                                        "w10", "r2", "n", "kind"]))
    return frame, fitted


def refit_summary(frame: pd.DataFrame) -> Dict[str, float]:
    """The three numbers that decide whether a refit path is hedgeable.

    ``b_sign_flips`` is the one that matters: a fitted scale whose SIGN changes
    inside its own sample cannot be hedged with, however well it fits on
    average, because the hedge would have to be turned upside down mid-trade and
    nothing in the fit says in advance which side of the flip it is on.
    """
    if frame.empty:
        return {"n_refits": 0, "w2_median": float("nan"),
                "w2_range": float("nan"), "b_median": float("nan"),
                "b_sign_flips": 0, "n_boundary_w2": 0}
    w2 = frame["w2"].astype(float)
    b = frame["b"].astype(float)
    return {
        "n_refits": int(len(frame)),
        "w2_median": float(w2.median()),
        "w2_range": float(w2.max() - w2.min()),
        "b_median": float(b.median()),
        "b_sign_flips": int((np.sign(b).diff().abs() > 0).sum()),
        "n_boundary_w2": int(((w2 <= W2_GRID[0] + 1e-12)
                              | (w2 >= W2_GRID[-1] - 1e-12)).sum()),
    }


# ---------------------------------------------------------------------------
# 3. The ticket arithmetic the note prints
# ---------------------------------------------------------------------------
def annuity(rate_pct: float, years: float) -> float:
    """Flat-curve annual annuity factor; DV01 per $1mm is ``annuity * 100``.

    Deliberately the crudest possible discounting: it exists to reproduce the
    note's own printed notional/DV01 arithmetic to within a couple of percent
    and to convert a fitted DV01 weight into a quotable notional, not to price
    anything.  Every P&L number in this block comes from the engine.
    """
    r = float(rate_pct) / 100.0
    n = int(round(float(years)))
    if abs(r) < 1e-12:
        return float(n)
    return (1.0 - (1.0 + r) ** (-n)) / r


def dv01_weights_to_notionals(w2: float, w10: float, belly_dv01: float,
                              rates_pct: Tuple[float, float, float],
                              years: Tuple[float, float, float] = (2.0, 5.0, 10.0),
                              ) -> Tuple[float, float, float]:
    """``(n2, n5, n10)`` in $mm that carry ``(w2, 1, w10) * belly_dv01``.

    Sign convention is **the note's own printed ticket**: "notional weights of
    $147mm / -$85.6mm / $20.89mm (0.705/-1/0.465 DV01 weights)" alongside "we
    hedge the trade by paying the belly of the 2s5s10s swap fly".  So a POSITIVE
    ``belly_dv01`` -- meaning PAY the belly, i.e. +$ per bp of the combination
    ``r5 - w2*r2 - w10*r10`` -- returns a NEGATIVE 5y notional and positive
    wings, exactly as printed.
    """
    a2, a5, a10 = (annuity(r, y) for r, y in zip(rates_pct, years))
    n5 = -float(belly_dv01) / (a5 * 100.0)
    n2 = float(w2) * float(belly_dv01) / (a2 * 100.0)
    n10 = float(w10) * float(belly_dv01) / (a10 * 100.0)
    return n2, n5, n10
