"""Answer the three measurement questions the lambda framework rests on.

    python notebooks/rv/sr3_zq_lambda_analysis.py --panel notebooks/data/sr3_zq_lambda/panel.csv

1. Does the +/-0.44 error bar on the VARIANCE route reproduce?
2. Across sessions, is lambda_wing = 0.54 the favourable end of the range or the centre?
3. Do the mode LOCATIONS regress flat against the forward on a longer history? Mass shifting
   between fixed locations while the forward translates is the signature of a state lattice;
   a smooth unimodal law drags its peak with the forward.

Plus two the RV structure of the problem demands: the cross-strike consistency of lambda, and
how far lambda moves once 50bp meeting outcomes are allowed.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from RVUtils.SR3ZQDistributionScreener._copula import (  # noqa: E402
    categorical_comonotone_sum,
    categorical_independent_sum,
    coupling_bounds,
    fold_to_binary_support,
    lambda_from_statistic,
    three_point_marginal,
    wing_mass,
)

PUBLISHED_LAMBDA = 0.54


def parse_list(x):
    if isinstance(x, (list, tuple, np.ndarray)):
        return list(x)
    if not isinstance(x, str) or not x.strip():
        return []
    try:
        return list(ast.literal_eval(x))
    except (ValueError, SyntaxError):
        return []


def hac_slope(y: np.ndarray, x: np.ndarray, lags: int = 5):
    """OLS slope with a Newey-West standard error. Returns (beta, se, t, n, r2)."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    good = np.isfinite(y) & np.isfinite(x)
    y, x = y[good], x[good]
    n = y.size
    if n < 8 or np.std(x) < 1e-12:
        return (float("nan"),) * 3 + (n, float("nan"))
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    xtx_inv = np.linalg.inv(X.T @ X)
    s = X * resid[:, None]
    omega = s.T @ s
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1.0 - lag / (lags + 1.0)
        gamma = s[lag:].T @ s[:-lag]
        omega += w * (gamma + gamma.T)
    cov = xtx_inv @ omega @ xtx_inv
    se = float(np.sqrt(max(cov[1, 1], 0.0)))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    t = float(beta[1] / se) if se > 0 else float("nan")
    return float(beta[1]), se, t, n, r2


def demean_within(df: pd.DataFrame, cols, key="symbol") -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = out[c] - out.groupby(key)[c].transform("mean")
    return out


def describe(name: str, s: pd.Series) -> None:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        print(f"  {name:26s} (empty)")
        return
    print(f"  {name:26s} n={len(s):4d}  mean {s.mean():+.3f}  sd {s.std():.3f}  "
          f"min {s.min():+.3f}  p10 {s.quantile(.10):+.3f}  med {s.median():+.3f}  "
          f"p90 {s.quantile(.90):+.3f}  max {s.max():+.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="notebooks/data/sr3_zq_lambda/panel.csv")
    ap.add_argument("--max-fwd-resid-bp", type=float, default=1.0)
    ap.add_argument("--max-pre-norm-mass", type=float, default=1.02)
    ap.add_argument("--max-ghost", type=float, default=0.05)
    args = ap.parse_args()

    df = pd.read_csv(args.panel)
    df["as_of"] = pd.to_datetime(df["as_of"])
    for col in ("marginals", "observed_atoms", "observed_atoms_strict", "mode_prices",
                "atom_prices", "lambda_atoms"):
        if col in df.columns:
            df[col] = df[col].map(parse_list)

    print(f"\n=== panel: {len(df)} rows, {df.symbol.nunique()} contracts, "
          f"{df.as_of.min().date()} .. {df.as_of.max().date()} ===")
    if "is_model_density" in df.columns:
        n_model = int(df["is_model_density"].fillna(False).astype(bool).sum())
        print(f"  SABR model densities in the panel: {n_model} (must be 0)")

    ok = df[df.ok.astype(bool)].copy()
    gate = (
        ok.forward_residual_bp.abs().le(args.max_fwd_resid_bp)
        & ok.pre_normalization_mass.le(args.max_pre_norm_mass)
        & ok.ghost_mass_fraction.le(args.max_ghost)
    )
    g = ok[gate].copy()
    print(f"  ok={len(ok)}  admissible after the pre-registered fit gate={len(g)} "
          f"({100 * len(g) / max(len(ok), 1):.0f}%)")
    print("  admissible sessions per contract:")
    for sym, n in g.symbol.value_counts().sort_index().items():
        sub = g[g.symbol == sym]
        print(f"    {sym}  n={n:3d}  {sub.as_of.min().date()} .. {sub.as_of.max().date()}  "
              f"n_meetings {sorted(sub.n_meetings.unique())}")

    # ---------------------------------------------------------------------------------
    print("\n--- Q1. the variance route ---")
    describe("lambda_var", g.lambda_var)
    describe("non-meeting var share", g.basis_var_share)
    sens = pd.to_numeric(g.lambda_var_sensitivity, errors="coerce").dropna()
    if len(sens):
        print(f"  a +/-10 bp/yr error on the non-meeting vol assumption moves lambda_var by "
              f"{abs(10 * sens.mean()):.2f} on average (range "
              f"{abs(10 * sens.max()):.2f}..{abs(10 * sens.min()):.2f})")
    over = (pd.to_numeric(g.lambda_var, errors="coerce") > 1.0).mean()
    print(f"  fraction of sessions with lambda_var ABOVE the comonotone bound: {over:.1%}")
    # How much non-meeting variance would be needed just to bring it on scale?
    need = (g.var_observed_bp2 - g.var_comonotone_bp2).clip(lower=0.0)
    tte = pd.to_numeric(g.time_to_expiry, errors="coerce")
    implied_vol = np.sqrt((need / tte.replace(0, np.nan)).clip(lower=0.0))
    describe("non-meeting vol bp/yr NEEDED", implied_vol)

    # ---------------------------------------------------------------------------------
    print("\n--- Q2. lambda_wing across sessions ---")
    describe("lambda_wing (absorbed)", g.lambda_wing)
    describe("lambda_wing (renorm)", g.lambda_wing_renorm)
    describe("lambda_wing (strict)", g.lambda_wing_raw)
    lw = pd.to_numeric(g.lambda_wing, errors="coerce").dropna()
    if len(lw):
        pct = float((lw < PUBLISHED_LAMBDA).mean())
        print(f"  the published {PUBLISHED_LAMBDA} sits at the {100 * pct:.0f}th percentile "
              f"of the admissible sample (median {lw.median():+.3f})")
        print("  -> " + (
            "0.54 is near the LOW end: the published session was not the favourable one"
            if pct < 0.35 else
            "0.54 is near the HIGH end: the published session WAS the favourable one"
            if pct > 0.65 else
            "0.54 is close to the centre of the range"))
    print("  by contract:")
    for sym, sub in g.groupby("symbol"):
        s = pd.to_numeric(sub.lambda_wing, errors="coerce").dropna()
        if len(s):
            print(f"    {sym}  n={len(s):3d}  mean {s.mean():+.3f}  sd {s.std():.3f}  "
                  f"[{s.min():+.3f}, {s.max():+.3f}]")
    print("  cross-strike consistency:")
    describe("lambda_atom_spread", g.lambda_atom_spread)
    describe("trough/peak ratio", g.trough_peak_ratio)
    if "n_modes" in g:
        print(f"  modal count: {g.n_modes.value_counts().sort_index().to_dict()}")

    # ---------------------------------------------------------------------------------
    print("\n--- Q3. do the modes stay put while the forward moves? ---")
    # Gated on FIT QUALITY ONLY. Mode location versus the forward needs none of the copula
    # machinery -- a well-fitted density, two peaks and the pin control are enough -- so
    # applying the copula-applicability gates here would throw away most of the evidence for
    # the strongest claim in the thesis.
    fit_gate = (
        ok.forward_residual_bp.abs().le(args.max_fwd_resid_bp)
        & ok.pre_normalization_mass.le(args.max_pre_norm_mass)
        & ok.ghost_mass_fraction.le(args.max_ghost)
    )
    shape = ok[fit_gate].copy()
    if "n_modes" in df.columns:
        all_fit = df[
            df.forward_residual_bp.abs().le(args.max_fwd_resid_bp)
            & df.pre_normalization_mass.le(args.max_pre_norm_mass)
            & df.ghost_mass_fraction.le(args.max_ghost)
            & df.n_modes.ge(0)
        ].copy()
        if len(all_fit) > len(shape):
            shape = all_fit
    print(f"  sessions with a well-fitted density (copula applicability NOT required): {len(shape)}")
    rows = []
    for r in shape.itertuples():
        modes = sorted([float(x) for x in (r.mode_prices or [])], reverse=True)
        pins = [float(x) for x in (getattr(r, "atom_prices", None) or [])]
        if len(modes) < 2:
            continue
        rows.append({
            "symbol": r.symbol, "as_of": r.as_of, "forward_price": float(r.forward_price),
            "mode_hi": modes[0], "mode_lo": modes[1],
            # The pins only exist where the copula measurement completed. The mode-vs-forward
            # regression does not need them; the pin CONTROL does, and it runs on the subset.
            "pin_hi": max(pins) if pins else float("nan"),
            "pin_lo": min(pins) if pins else float("nan"),
            "n_meetings": int(r.n_meetings) if pd.notna(r.n_meetings) else -1,
        })
    md = pd.DataFrame(rows)
    print(f"  bimodal admissible sessions: {len(md)} of {len(g)}")
    if len(md) >= 10:
        dm = demean_within(md, ["forward_price", "mode_hi", "mode_lo", "pin_hi", "pin_lo"])
        for label, ycol, xcol in (
            ("mode_hi ~ forward", "mode_hi", "forward_price"),
            ("mode_lo ~ forward", "mode_lo", "forward_price"),
            ("pin_hi  ~ forward", "pin_hi", "forward_price"),
            ("mode_hi ~ pin_hi ", "mode_hi", "pin_hi"),
            ("mode_lo ~ pin_lo ", "mode_lo", "pin_lo"),
        ):
            b, se, t, n, r2 = hac_slope(dm[ycol].to_numpy(), dm[xcol].to_numpy())
            print(f"    {label}  beta {b:+.3f} (NW se {se:.3f}, t {t:+.2f})  n={n}  R2 {r2:.3f}")
        print("    beta ~ 0 against the forward = a state lattice; beta ~ 1 = a translating "
              "smooth density.")
        print("    The pin row is the control: the pins are ZQ-anchored, so if they also move "
              "one-for-one with the forward the mode test says nothing.")
        for sym, sub in md.groupby("symbol"):
            if len(sub) >= 10:
                b, _, t, n, _ = hac_slope(sub.mode_hi.to_numpy(), sub.forward_price.to_numpy())
                bl, _, tl, _, _ = hac_slope(sub.mode_lo.to_numpy(), sub.forward_price.to_numpy())
                print(f"      {sym}: mode_hi beta {b:+.3f} (t {t:+.2f}), "
                      f"mode_lo beta {bl:+.3f} (t {tl:+.2f}), n={n}, "
                      f"forward range {100 * (sub.forward_price.max() - sub.forward_price.min()):.1f}bp")

    # ---------------------------------------------------------------------------------
    print("\n--- Q4. what 50bp outcomes do to lambda (pre-registered kill test) ---")
    print("  ZQ pins only the MEAN of each marginal. Allowing 50bp steps adds dispersion to")
    print("  the sum that a binary model books as dependence, so the bias runs UPWARD.")
    mixes = (0.0, 0.10, 0.25, 0.40)
    per_mix: dict[float, list[float]] = {m: [] for m in mixes}
    for r in g.itertuples():
        p = [float(x) for x in (r.marginals or [])]
        obs = [float(x) for x in (r.observed_atoms or [])]
        if len(p) < 2 or len(obs) != len(p) + 1:
            continue
        n = len(p)
        w_obs = wing_mass(obs)
        for mix in mixes:
            try:
                pmfs = [three_point_marginal(e, mix) for e in p]
            except ValueError:
                continue
            com = fold_to_binary_support(categorical_comonotone_sum(pmfs), n)
            ind = fold_to_binary_support(categorical_independent_sum(pmfs), n)
            lam = lambda_from_statistic(w_obs, independent=wing_mass(ind), comonotone=wing_mass(com))
            if np.isfinite(lam):
                per_mix[mix].append(lam)
    base = np.array(per_mix[0.0], dtype=float)
    for mix in mixes:
        vals = np.array(per_mix[mix], dtype=float)
        if vals.size == 0:
            print(f"    size_mix {mix:.2f}: no admissible sessions")
            continue
        shift = float(np.mean(vals[: base.size] - base[: vals.size])) if base.size else float("nan")
        print(f"    size_mix {mix:.2f}:  mean lambda {vals.mean():+.3f}  med {np.median(vals):+.3f}"
              f"  sd {vals.std(ddof=1) if vals.size > 1 else float('nan'):.3f}"
              f"  mean shift vs binary {shift:+.3f}")
    print("\n--- Q5. term structure of dependence (same date, across contracts) ---")
    print("  Dependence should be higher near-dated -- one decision, clearly framed -- and")
    print("  decay out the strip. Deviations from that shape are the screen.")
    wide = (
        g.pivot_table(index="as_of", columns="symbol", values="lambda_wing", aggfunc="last")
        if g.symbol.nunique() > 1 else pd.DataFrame()
    )
    if wide.shape[1] < 2:
        print("  needs >= 2 contracts with overlapping admissible sessions; panel has "
              f"{g.symbol.nunique()}")
    else:
        pairs = 0
        for a, b in zip(wide.columns[:-1], wide.columns[1:]):
            both = wide[[a, b]].dropna()
            if len(both) < 5:
                continue
            pairs += 1
            d = both[a] - both[b]
            dte = g.groupby("symbol")["time_to_expiry"].median()
            near, far = (a, b) if dte.get(a, np.inf) <= dte.get(b, np.inf) else (b, a)
            sign = 1.0 if near == a else -1.0
            print(f"    {near} (near) - {far} (far): n={len(both)}  mean {sign * d.mean():+.3f}  "
                  f"sd {d.std():.3f}  corr {both[a].corr(both[b]):+.3f}  "
                  f"{'near > far, as expected' if sign * d.mean() > 0 else 'INVERTED'}")
        if pairs == 0:
            print("  no adjacent pair has >= 5 overlapping admissible sessions")

    if base.size and per_mix[0.25]:
        a = base
        b = np.array(per_mix[0.25], dtype=float)
        m = min(a.size, b.size)
        rho = float(np.corrcoef(a[:m], b[:m])[0, 1]) if m > 2 else float("nan")
        print(f"    rank stability binary vs 25% 50s: corr {rho:.3f} "
              f"({'ordering preserved' if rho > 0.9 else 'ORDERING NOT PRESERVED - kill criterion'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
