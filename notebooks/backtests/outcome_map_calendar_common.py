"""Harness for the adjacent-expiry (vol-vs-vol) leg.

Builds, once per contract-day, everything a config might ask for: the mirrored
package on the adjacent expiry, the tree ratio over shared meetings, a causal
trailing empirical ratio, the exposure the hedge leaves behind, and the marks
and signals for both. The grid then only chooses among precomputed objects, so
no config can quietly recompute a different pairing from another.

Two things the engine needs that a single-expiry package did not:

* marks that span two symbols (``make_calendar_mark_fn``), and
* a contract count that nets **per expiry** — strikes on different expiries are
  different instruments and must never telescope into each other.
"""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

import famb_common as fc
import outcome_map_common as omc
from RVUtils.OutcomeMap import (
    adjacent, align_exposure, empirical_ratio, mirror_package,
    package_contracts, package_hedge_ratios, residual_exposure, tree_ratio,
)

#: sessions of history the causal empirical ratio is fitted on
CAL_WINDOW = 40

CAL_SIGNALS = ("map_odd", "calendar")
CAL_LAMBDAS = ("none", "one", "tree", "emp")


def expiry_map(ctx: omc.Context) -> Dict[str, datetime.date]:
    if not hasattr(ctx, "_expiry_map_cache"):
        ctx._expiry_map_cache = {s: ctx.expiry(s)
                                 for s in fc.quarterly_symbols()}
    return ctx._expiry_map_cache


def calendar_frame(ctx: omc.Context, panel: pd.DataFrame, base: pd.DataFrame,
                   *, side: str = "far", convention: str = "abs_rate",
                   window: int = CAL_WINDOW,
                   progress: int = 0) -> pd.DataFrame:
    """Pair each base-signal package with its mirror on the adjacent expiry."""
    exp = expiry_map(ctx)
    rows: List[dict] = []
    for i, (_, r) in enumerate(base.iterrows()):
        if progress and i % progress == 0:
            print(f"  cal [{i}/{len(base)}] rows={len(rows)}", flush=True)
        ts, sym = r["as_of"], r["symbol"]
        d = ts.date()
        prev, nxt = adjacent(exp, d, sym)
        other = nxt if side == "far" else prev
        if other is None:
            continue
        a1, a2 = ctx.atoms(ts, sym), ctx.atoms(ts, other)
        cm1, cm2 = ctx.tree.cm(d, sym), ctx.tree.cm(d, other)
        if a1 is None or a2 is None or cm1 is None or cm2 is None:
            continue
        if cm2.n_resolved == 0:
            continue
        _, _, sm1, f1 = a1
        _, _, sm2, f2 = a2
        shift = 0.0 if convention == "abs_rate" else (f1 - f2)
        cal_centers = []
        ok = True
        for c in r["cell_centers"]:
            legs_one = mirror_package([c], [1.0], ctx.strikes(ts, other),
                                      shift=shift)
            if not legs_one:
                ok = False
                break
            cal_centers.append(sorted({k for _, k, _ in legs_one})[1])
        if not ok:
            continue
        legs2 = mirror_package(r["cell_centers"], r["cell_weights"],
                               ctx.strikes(ts, other), shift=shift)
        if not legs2:
            continue
        h1 = package_hedge_ratios(cm1, f1, list(r["legs"]), sm1)
        h2 = package_hedge_ratios(cm2, f2, legs2, sm2)
        v1, v2, shared, extra = align_exposure(cm1, h1, cm2, h2)
        lam_tree = tree_ratio(v1, v2)
        if not np.isfinite(lam_tree):
            continue
        # causal empirical ratio: history strictly BEFORE the signal day
        hist = ctx.dates[ctx.dates < ts][-(window + 5):]
        s1 = pd.Series({t: ctx.mark_any(t, sym, list(r["legs"])) for t in hist},
                       dtype=float).dropna()
        s2 = pd.Series({t: ctx.mark_any(t, other, legs2) for t in hist},
                       dtype=float).dropna()
        lam_emp = empirical_ratio(s1, s2, window=window)
        extra_set = set(extra)
        rows.append({
            **{k: r[k] for k in r.index},
            "other": other, "legs2": legs2, "cal_centers": cal_centers,
            "shift": float(shift), "lam_tree": float(lam_tree),
            "lam_emp": float(lam_emp) if np.isfinite(lam_emp) else np.nan,
            "n_shared": len(shared), "n_extra": len(extra),
            "resid_frac": residual_exposure(v1, v2, lam_tree),
            "h1_abs": float(np.abs(v1).sum()),
            "h2_abs": float(np.abs(v2).sum()),
            "extra_exposure": float(sum(
                abs(h2[i]) for i, rr in enumerate(cm2.resolved)
                if rr.effective in extra_set)),
            "con1": package_contracts(list(r["legs"])),
            "con2": package_contracts(legs2),
            "fwd2": float(f2),
            "dte2": (ctx.expiry(other) - d).days,
        })
    return pd.DataFrame(rows)


def resolve_lambda(row, mode: str) -> float:
    """The ratio a config asks for; NaN means the row is unusable for it."""
    if mode == "none":
        return 0.0
    if mode == "one":
        return 1.0
    if mode == "tree":
        return float(row["lam_tree"])
    if mode == "emp":
        return float(row["lam_emp"])
    raise ValueError(mode)


def make_calendar_mark_fn(ctx: omc.Context, mode: str):
    """Daily mark of the two-expiry package ``orient * (pkg1 - lambda*pkg2)``."""
    def _fn(ts: pd.Timestamp, row) -> float:
        m1 = ctx.mark_any(ts, row["symbol"], row["legs"])
        if not np.isfinite(m1):
            return np.nan
        lam = resolve_lambda(row, mode)
        if not np.isfinite(lam):
            return np.nan
        o = float(row.get("orient", 1.0))
        if lam == 0.0:
            return o * m1
        m2 = ctx.mark_any(ts, row["other"], row["legs2"])
        if not np.isfinite(m2):
            return np.nan
        return o * (m1 - lam * m2)
    return _fn


def make_calendar_contracts_fn(mode: str):
    """Contracts net PER EXPIRY — different expiries are different instruments."""
    def _fn(row) -> float:
        lam = resolve_lambda(row, mode)
        n1 = package_contracts(row["legs"])
        if not np.isfinite(lam) or lam == 0.0:
            return n1
        return n1 + abs(lam) * package_contracts(row["legs2"])
    return _fn


def _odd_value(ctx, ts, sym, legs, centers, weights, fit, bbar) -> float:
    """A package's richness with its own standing premium and tilt removed."""
    if fit is None:
        return np.nan
    m = ctx.mark_any(ts, sym, legs)
    f = ctx.fair(ts, sym, legs)
    if not (np.isfinite(m) and np.isfinite(f)):
        return np.nan
    a, b, c = fit
    try:
        fwd = float(ctx.fwd_idx.loc[(ts, sym)])
    except KeyError:
        return np.nan
    d = (100.0 - np.asarray(centers, dtype=float) - fwd) / 0.25
    w = np.asarray(weights, dtype=float)
    if not np.isfinite(bbar):
        return np.nan
    return float((m - f) - np.dot(w, a + c * d ** 2) - bbar * np.dot(w, d))


def make_calendar_signal_fn(ctx: omc.Context, panel: pd.DataFrame,
                            signal: str, mode: str,
                            b_bar: Optional[pd.Series] = None):
    """The signal a calendar config enters AND exits on.

    ``map_odd``   the near package's own odd-deviation signal. A hedge changes
                  the P&L, not the thing being traded, so the unhedged arm must
                  reproduce the outcome-map study exactly — that is the control.
    ``calendar``  the CROSS-EXPIRY residual: each leg measured against its own
                  standing premium and its own trailing tilt, then differenced at
                  the config's ratio. The common part of the market-vs-lattice
                  distortion cancels; what is left is the disagreement about the
                  meetings only the far expiry resolves.
    """
    fits = (panel.drop_duplicates(["as_of", "symbol"])
            .set_index(["as_of", "symbol"])[["fit_a", "fit_b", "fit_c"]])
    fit_map = {k: tuple(v) for k, v in zip(fits.index, fits.to_numpy())}
    bb = omc.trailing_tilt(panel) if b_bar is None else b_bar
    bb_map = bb.dropna().to_dict()

    def _fn(ts: pd.Timestamp, row) -> float:
        o = float(row.get("orient", 1.0))
        s1 = _odd_value(ctx, ts, row["symbol"], row["legs"],
                        row["cell_centers"], row["cell_weights"],
                        fit_map.get((ts, row["symbol"])),
                        bb_map.get((ts, row["symbol"]), np.nan))
        if signal == "map_odd":
            return s1
        if not np.isfinite(s1):
            return np.nan
        lam = resolve_lambda(row, mode)
        if not np.isfinite(lam):
            return np.nan
        if lam == 0.0:
            return o * s1
        s2 = _odd_value(ctx, ts, row["other"], row["legs2"],
                        row["cal_centers"], row["cell_weights"],
                        fit_map.get((ts, row["other"])),
                        bb_map.get((ts, row["other"]), np.nan))
        if not np.isfinite(s2):
            return np.nan
        return o * (s1 - lam * s2)
    return _fn


def orient_calendar(frame: pd.DataFrame, ctx: omc.Context, panel: pd.DataFrame,
                    mode: str, b_bar: Optional[pd.Series] = None
                    ) -> pd.DataFrame:
    """Sign each calendar package so its entry signal is negative.

    The engine's convention throughout this program is that a package is built
    long-the-cheap-thing, so its richness starts negative and converges toward
    zero. A cross-expiry residual has no natural side, so the orientation is set
    from the signal itself and recorded, rather than left implicit in the sign of
    a P&L.
    """
    out = frame.copy()
    out["orient"] = 1.0
    fn = make_calendar_signal_fn(ctx, panel, "calendar", mode, b_bar=b_bar)
    vals = []
    for _, r in out.iterrows():
        vals.append(fn(r["as_of"], r))
    v = np.asarray(vals, dtype=float)
    out["cal_signal_bp"] = v
    out["orient"] = np.where(np.isfinite(v) & (v > 0), -1.0, 1.0)
    out["strength_bp"] = np.abs(v)
    return out[np.isfinite(v)]
