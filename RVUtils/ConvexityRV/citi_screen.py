r"""Citi's Figure-20 convexity screen, as a per-date panel rather than one print.

Source: Citi Research, *US Rates Weekly*, **13 Jan 2017**, "Swearing in huge
expectations" §*Smart convexity sells*, Figure 20; reprinted with the same
columns in the *US Rates Vol Lab* of 19 Apr 2018 (Figure 56).  The note's own
description:

    "Figure 20 offers a systematic analysis of the valuation in convexity
    adjustments across the curve.  We analyze 1y packs (four consecutive
    contracts) because individual ED/FRA spreads are noisy and hard to trade.
    We compute z-scores of CAs and rich/cheap on the fair value model (based on
    cap/floor vols), together with the z-scores of the dislocations from the
    model.  We also compute volatilities implied from CAs and compare them to
    the recent realized volatilities."

The note prints one date.  A backtest needs the same object on **every** date,
because the screen is what chooses which structure to trade -- so this module
returns one ``DataFrame`` per column, indexed by date with one column per
structure, and a renderer that prints the note's own table for a single date.

The columns, and how each is built here
---------------------------------------
=================== =========================================== ==================
column              the note's definition                       here
=================== =========================================== ==================
``ca``              pack rate - matched fwd 1y swap             ``sfr_cvx_adj``
``chg_1w``          1-week change in the CA                     5 business days
``ca_z_3m``         3m z-score of the CA                        63 bd rolling
``ca_z_1y``         1Y z-score of the CA                        252 bd rolling
``model``           Ho-Lee ``sigma^2*mean(T1^2)/2e4``           swaption ATMF
``vs_model``        identity ``CA - Model``                     identity
``vs_model_z_3m``   3m z of the dislocation                     63 bd rolling
``vs_model_z_1y``   1Y z of the dislocation                     252 bd rolling
``roll_3m``         3m roll of a SHORT convexity position       ``-theta/4``
``implied``         Ho-Lee inverted on the observed CA          ``sqrt(2e4*CA/w)``
``realized``        3m realized vol of the pack rate            63 bd, roll-free
``impl_rlzd``       ``implied / realized``                      ratio
=================== =========================================== ==================

Two substitutions are named rather than assumed away
----------------------------------------------------
1. **The model vol.**  The note calibrates its Ho-Lee level to CAP/FLOOR
   volatilities.  This machine has the swaption cube, so the model level uses
   the ATMF normal vol of the straddle whose expiry sits at the structure's own
   mean contract expiry against a 1y tenor -- ``4Yx1Y`` for BLUES.  A different
   surface, so a level disagreement of a basis point or two is expected.
2. **The roll column.**  The note's ``3m Roll`` is the CA rolling down its own
   term structure: ``Roll(p) = CA(p) - CA(p one contract nearer)``.  Colour
   packs are four contracts (one year) apart, so the adjacent-quarter neighbour
   does not exist in the tradeable set.  The declared column is therefore the
   ANALYTIC equivalent, one quarter of the CA's own decay
   ``dCA/dt = -sigma^2*mean(T1)/1e4``, which is defined for every structure --
   and :func:`roll_identity` measures it against the term-structure form
   ``[CA(p) - CA(p one YEAR nearer)] / 4`` rather than asserting an equality the
   granularity cannot support.  The two agreed to 2-11% when this package
   derived the same quantity from the measured IMM-roll jump.

Units: CA, model, roll and the z-inputs in **bp**; implied and realized vol in
**bp/yr**; ``w`` in years^2; ``impl_rlzd`` dimensionless.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "COLUMNS",
    "SCREEN_STRUCTURES",
    "VOL_COL",
    "ScreenConfig",
    "build_screen",
    "implied_vol_bp",
    "model_ca_bp",
    "nearer_colour",
    "pack_rate_bp",
    "realized_vol_bp",
    "roll_3m_bp",
    "roll_identity",
    "rolling_z",
    "screen_table",
    "verify_identities",
]

#: The five 1y colour packs, front to back.  These are the note's own rows and
#: the only CA structures the engine can build from a contract list.
SCREEN_STRUCTURES: Tuple[str, ...] = ("WHITES", "REDS", "GREENS", "BLUES",
                                      "GOLDS")

#: One ATMF straddle per structure: expiry at the structure's own mean contract
#: expiry, tenor = the matched 1y swap.  Both the model level and the vega are
#: taken against the SAME vol, which is what makes them comparable at all.
VOL_COL: Dict[str, str] = {
    "WHITES": "nvol_1y1y", "REDS": "nvol_2y1y", "GREENS": "nvol_3y1y",
    "BLUES": "nvol_4y1y", "GOLDS": "nvol_5y1y",
}

#: Every column the screen produces, in the note's own print order.
COLUMNS: Tuple[str, ...] = (
    "ca", "chg_1w", "ca_z_3m", "ca_z_1y", "model", "vs_model",
    "vs_model_z_3m", "vs_model_z_1y", "roll_3m", "implied", "realized",
    "impl_rlzd",
)


@dataclass(frozen=True)
class ScreenConfig:
    """Every window the screen uses, with the note's own value beside it."""

    #: "z-scores of CAs" -- the note prints a 3m and a 1Y column.
    z_short_bd: int = 63
    z_long_bd: int = 252
    #: "recent realized volatilities" -- 3m, close-to-close, annualised.
    realized_bd: int = 63
    #: "1wk chg".
    chg_bd: int = 5
    #: A rolling statistic needs half its window before it is quoted.
    min_periods_frac: float = 0.5
    #: Business days per year for the annualisation of realized vol.
    ann: float = 252.0
    #: Exclude IMM-roll returns from realized vol.  A constant-rank pack rate
    #: jumps at the roll because the contracts change, and a realized-vol
    #: column that counts that jump measures the roll, not the market.
    exclude_roll_returns: bool = True


# ---------------------------------------------------------------------------
# 1. The individual columns
# ---------------------------------------------------------------------------
def model_ca_bp(nvol_bp: pd.Series, w: pd.Series) -> pd.Series:
    """Ho-Lee fair value ``sigma_bp^2 * mean(T1^2) / 2e4`` in bp."""
    return (pd.Series(nvol_bp).astype(float) ** 2
            * pd.Series(w).astype(float) / 2e4)


def roll_3m_bp(nvol_bp: pd.Series, t1_mean: pd.Series) -> pd.Series:
    r"""One quarter of the CA's own decay, positive for a SHORT position.

    ``dCA/dt = -sigma^2 * mean(T1) / 1e4`` bp per year, so a short earns
    ``+sigma^2*mean(T1)/1e4 * 0.25`` over three months.  Note ``mean(T1)``, not
    ``mean(T1^2)``: the level uses the second moment and the decay the first,
    and confusing them is a Jensen-sized error in a first-order term.
    """
    return (pd.Series(nvol_bp).astype(float) ** 2
            * pd.Series(t1_mean).astype(float) / 1e4) * 0.25


def implied_vol_bp(ca_bp: pd.Series, w: pd.Series) -> pd.Series:
    """``sqrt(2e4 * CA / w)``, NaN where the adjustment is non-positive.

    A negative CA has no real implied vol and the front packs go negative
    often, so the NaN is the honest answer and its count is reported rather
    than clipped to zero.
    """
    v = 2e4 * pd.Series(ca_bp).astype(float) / pd.Series(w).astype(float)
    return np.sqrt(v.where(v > 0))


def pack_rate_bp(ca_bp: pd.Series, fwd1y_pct: pd.Series) -> pd.Series:
    """The traded pack rate in bp: ``CA/100 + matched fwd 1y`` back to bp."""
    return (pd.Series(ca_bp).astype(float) / 100.0
            + pd.Series(fwd1y_pct).astype(float)) * 100.0


def realized_vol_bp(rate_bp: pd.Series, *, window: int, ann: float,
                    is_roll: Optional[pd.Series] = None,
                    min_periods: Optional[int] = None) -> pd.Series:
    """Annualised close-to-close realized vol of a rate series, in bp/yr."""
    d = pd.Series(rate_bp).astype(float).diff()
    if is_roll is not None:
        d = d.where(~pd.Series(is_roll).reindex(d.index).fillna(False)
                    .astype(bool))
    mp = min_periods if min_periods is not None else max(20, int(window * 0.6))
    return d.rolling(window, min_periods=mp).std(ddof=1) * float(np.sqrt(ann))


def rolling_z(s: pd.Series, window: int, *, min_periods_frac: float = 0.5
              ) -> pd.Series:
    """Causal rolling z-score: ``(x - mean) / sd`` over a trailing window."""
    x = pd.Series(s).astype(float)
    mp = max(2, int(round(window * float(min_periods_frac))))
    mu = x.rolling(window, min_periods=mp).mean()
    sd = x.rolling(window, min_periods=mp).std(ddof=1)
    return (x - mu) / sd.replace(0.0, np.nan)


def nearer_colour(label: str) -> Optional[str]:
    """The colour one YEAR nearer, or ``None`` for the front pack."""
    i = SCREEN_STRUCTURES.index(label.upper())
    return SCREEN_STRUCTURES[i - 1] if i > 0 else None


# ---------------------------------------------------------------------------
# 2. The screen
# ---------------------------------------------------------------------------
def build_screen(panel: pd.DataFrame, *,
                 structures: Sequence[str] = SCREEN_STRUCTURES,
                 cfg: ScreenConfig = ScreenConfig(),
                 roll_col: str = "is_roll",
                 vol_col: Mapping[str, str] = VOL_COL,
                 ) -> Dict[str, pd.DataFrame]:
    """The whole Figure-20 screen, every date, every structure.

    ``panel`` must carry, for each structure ``L`` (lower-cased):
    ``{l}_ca_bp``, ``{l}_w``, ``{l}_t1mean``, ``{l}_fwd1y_pct``, plus the
    structure's vol column from *vol_col* and a boolean ``roll_col``.

    Returns ``{column_name: DataFrame(index=dates, columns=structures)}``.
    Every column is causal: nothing is centred, nothing is back-filled.
    """
    structures = [s.upper() for s in structures]
    out: Dict[str, Dict[str, pd.Series]] = {c: {} for c in COLUMNS}
    idx = panel.index
    is_roll = (panel[roll_col] if (cfg.exclude_roll_returns
                                   and roll_col in panel.columns) else None)
    for lab in structures:
        l = lab.lower()
        need = [f"{l}_ca_bp", f"{l}_w", f"{l}_t1mean", f"{l}_fwd1y_pct",
                vol_col[lab]]
        missing = [c for c in need if c not in panel.columns]
        if missing:
            raise KeyError(f"{lab}: panel is missing {missing}")
        ca = panel[f"{l}_ca_bp"].astype(float)
        w = panel[f"{l}_w"].astype(float)
        t1m = panel[f"{l}_t1mean"].astype(float)
        sig = panel[vol_col[lab]].astype(float)

        model = model_ca_bp(sig, w)
        vs = ca - model
        impl = implied_vol_bp(ca, w)
        rlzd = realized_vol_bp(pack_rate_bp(ca, panel[f"{l}_fwd1y_pct"]),
                               window=cfg.realized_bd, ann=cfg.ann,
                               is_roll=is_roll)
        out["ca"][lab] = ca
        out["chg_1w"][lab] = ca.diff(cfg.chg_bd)
        out["ca_z_3m"][lab] = rolling_z(ca, cfg.z_short_bd,
                                        min_periods_frac=cfg.min_periods_frac)
        out["ca_z_1y"][lab] = rolling_z(ca, cfg.z_long_bd,
                                        min_periods_frac=cfg.min_periods_frac)
        out["model"][lab] = model
        out["vs_model"][lab] = vs
        out["vs_model_z_3m"][lab] = rolling_z(
            vs, cfg.z_short_bd, min_periods_frac=cfg.min_periods_frac)
        out["vs_model_z_1y"][lab] = rolling_z(
            vs, cfg.z_long_bd, min_periods_frac=cfg.min_periods_frac)
        out["roll_3m"][lab] = roll_3m_bp(sig, t1m)
        out["implied"][lab] = impl
        out["realized"][lab] = rlzd
        out["impl_rlzd"][lab] = impl / rlzd.where(rlzd > 0)
    return {c: pd.DataFrame(out[c], index=idx)[structures] for c in COLUMNS}


def screen_table(screen: Mapping[str, pd.DataFrame], date, *,
                 structures: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """The note's own table, for one date: structures down, columns across."""
    d = pd.Timestamp(date)
    cols = list(structures) if structures is not None else list(
        screen["ca"].columns)
    return pd.DataFrame({c: screen[c].loc[d, cols] for c in COLUMNS},
                        index=cols)


# ---------------------------------------------------------------------------
# 3. The identities the note's own table satisfies
# ---------------------------------------------------------------------------
def verify_identities(screen: Mapping[str, pd.DataFrame],
                      panel: pd.DataFrame) -> Dict[str, float]:
    """``CA - Model - VsModel == 0`` and ``implied^2*w/2e4 == CA``.

    Returns the max absolute error of each, so a caller asserts on a number it
    can also print.  The second identity only binds where the CA is positive,
    which is where the inversion is defined at all.
    """
    err_vs = float((screen["ca"] - screen["model"] - screen["vs_model"])
                   .abs().to_numpy().max())
    errs = []
    for lab in screen["ca"].columns:
        w = panel[f"{lab.lower()}_w"].astype(float)
        recon = screen["implied"][lab] ** 2 * w / 2e4
        errs.append(float((recon - screen["ca"][lab]).abs().max()))
    return {"ca_minus_model_minus_vsmodel": err_vs,
            "implied_reconstructs_ca": float(np.nanmax(errs))}


def roll_identity(screen: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """The analytic roll against the term-structure roll, per structure.

    ``analytic`` is the declared column, ``-theta/4``.  ``term_structure`` is
    ``[CA(p) - CA(p one YEAR nearer)] / 4`` -- the note's own definition at the
    only granularity the colour packs offer.  The ratio is the content: these
    are two estimates of the same quantity and their agreement (or lack of it)
    is a measurement, not an assumption.
    """
    rows = []
    ca, roll = screen["ca"], screen["roll_3m"]
    for lab in ca.columns:
        near = nearer_colour(lab)
        if near is None or near not in ca.columns:
            continue
        ts = (ca[lab] - ca[near]) / 4.0
        an = roll[lab]
        j = pd.concat([an.rename("a"), ts.rename("t")], axis=1).dropna()
        if j.empty:
            continue
        rows.append({
            "structure": lab, "nearer": near, "n": int(len(j)),
            "analytic_mean_bp": float(j["a"].mean()),
            "term_structure_mean_bp": float(j["t"].mean()),
            "ratio": float(j["a"].mean() / j["t"].mean())
            if j["t"].mean() else float("nan"),
            "corr": float(j["a"].corr(j["t"])),
        })
    return pd.DataFrame(rows).set_index("structure") if rows else pd.DataFrame()
