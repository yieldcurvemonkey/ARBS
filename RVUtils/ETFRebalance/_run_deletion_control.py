"""Is the deletion effect index deletion, or is it the edge of the fitted curve?

The problem with the finding
----------------------------
With the repaired standardiser, ``deletion`` -- the CALENDAR-ONLY null, which reads no
holdings file at all -- has a partial IC of **+0.29 at 63 days (Newey-West t = +5.7)** and
a bivariate beta of **0.05bp per unit z (t = 3.5)**, roughly ten times any holdings-based
signal and the only thing in the study that survives a HAC correction.

It is also perfectly confounded. A bond about to fall below TLT's 20-year boundary is, by
construction, the **shortest bond in a curve fitted over 20-31 years** -- the extreme edge
of the fitting window, where a cubic is least constrained and most likely to leave a
one-sided residual. And when it finally crosses, it leaves the universe entirely. So
"bonds about to be deleted cheapen against the fitted curve" and "bonds at the bottom edge
of the fit have a downward-biased fit" are the same sentence until they are separated.

Three separations, in increasing strength
------------------------------------------
**1. Widen the fit.** Refit over 15-31 years so a 20-year bond is interior rather than
terminal, and re-measure. If the effect is an edge artefact it should shrink sharply.

**2. A PLACEBO boundary.** Score a fake deletion at 25 years -- a maturity at which nothing
whatsoever happens to any index -- using the identical function and the identical fitting
window. A bond approaching 25y is interior to the fit and no forced seller exists, so a
placebo that reproduces the real effect proves the effect is about the *shape* of the
signal, not about deletion. This is the test that decides it.

**3. Boundary distance as a plain control.** Regress the forward return on the real
deletion score AND on distance-to-the-bottom-of-the-fit, together. If the deletion score
loses its coefficient, it was carrying position-in-window.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 220)
HORIZONS = (5, 10, 21, 42, 63)


def universe(panel: pd.DataFrame, lo: float, hi: float, start: str) -> pd.DataFrame:
    u = panel[
        panel["ttm"].between(lo, hi, inclusive="left")
        & panel["ytm"].notna() & ~panel["yield_gate_fail"].fillna(True)
        & panel["price_source"].eq("mid")
        & panel["free_float"].fillna(0).ge(5e9)
        & panel["date"].ge(pd.Timestamp(start))
    ].copy()
    return CV.fit_residuals(u, deg=3, x_axis="ttm", include_coupon=True, robust=True)


def crossing_dummy(d: pd.DataFrame, boundary: float, horizon_m: int = 3) -> pd.Series:
    """-1 ramping to 0 for bonds whose maturity crosses ``boundary`` inside the horizon.

    A MATCHED placebo needs the same shape and the same rarity as the real signal, and
    ``sig_deletion`` gives neither away from the universe floor: it flags everything
    *below* the boundary, so at 25y inside a 15-31y universe it fires on 67% of bond-days
    and is a maturity tilt rather than an event. This flags only the narrow band a bond
    passes THROUGH, so a placebo at 23y fires on the same ~2% of bond-days as the real
    one at 20y and the comparison is between two events rather than between an event and
    a slope.
    """
    me = d["date"] + pd.offsets.MonthEnd(0)
    hit = pd.Series(np.nan, index=d.index)
    for m in range(horizon_m, -1, -1):
        rebal = me + pd.offsets.MonthEnd(int(m))
        ttm_at = d["ttm"] - (rebal - d["date"]).dt.days / 365.25
        crosses = (ttm_at < boundary) & (d["ttm"] >= boundary)
        hit = hit.mask(crosses, float(m))
    return -((horizon_m + 1 - hit) / (horizon_m + 1)).fillna(0.0)


def score_ic(u: pd.DataFrame, band_low: float, label: str, exec_lag: int = 1,
             matched: bool = False) -> pd.DataFrame:
    d = u.copy()
    raw = (crossing_dummy(d, band_low) if matched
           else SIG.sig_deletion(d, band_low=band_low, horizon_m=3))
    d["z_del"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)
    d["z_resid"] = SIG.cross_sectional_z(d["resid_bp"], d["date"], robust=True).clip(-5, 5)
    d = IC.forward_residual_return(d, HORIZONS).sort_values(["cusip", "date"])
    for c in ("z_del", "z_resid"):
        d[c] = d.groupby("cusip")[c].shift(exec_lag)

    rows = []
    for h in HORIZONS:
        b_s, b_r = [], []
        for _, g in d.groupby("date", sort=False):
            y = g[f"fwd_{h}"].to_numpy(float)
            X = np.column_stack([g["z_del"].to_numpy(float), g["z_resid"].to_numpy(float)])
            ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
            if ok.sum() < 10:
                continue
            A = np.column_stack([np.ones(ok.sum()), X[ok]])
            try:
                beta, *_ = np.linalg.lstsq(A, y[ok], rcond=None)
            except np.linalg.LinAlgError:
                continue
            b_s.append(beta[1])
            b_r.append(beta[2])
        b_s = np.array(b_s)
        if b_s.size < 20:
            continue
        rows.append({
            "variant": label, "horizon": h, "n_dates": b_s.size,
            "beta_bp_per_z": float(b_s.mean()),
            "t_hac": IC.newey_west_t(b_s, lags=max(1, h - 1)),
            "t_naive": float(b_s.mean() / (b_s.std(ddof=1) / np.sqrt(b_s.size))),
            "flagged_pct": float((raw < 0).mean() * 100),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    a = ap.parse_args()

    panel = FP.asof_join(BP.load(), FP.load())

    print("Building three universes (the fit window is what changes) ...", flush=True)
    u_narrow = universe(panel, 20.0, 31.0, a.start)     # TLT's own band: 20y is the EDGE
    u_wide = universe(panel, 15.0, 31.0, a.start)       # 20y is now INTERIOR
    print(f"  narrow 20-31y : {len(u_narrow):,} bond-days, "
          f"{u_narrow['cusip'].nunique()} cusips, median fit RMSE "
          f"{u_narrow.groupby('date')['fit_rmse_bp'].first().median():.3f}bp")
    print(f"  wide   15-31y : {len(u_wide):,} bond-days, "
          f"{u_wide['cusip'].nunique()} cusips, median fit RMSE "
          f"{u_wide.groupby('date')['fit_rmse_bp'].first().median():.3f}bp")

    out = []
    out.append(score_ic(u_narrow, 20.0, "REAL 20y, fit 20-31y (20y is the EDGE)"))
    out.append(score_ic(u_wide, 20.0, "REAL 20y, fit 15-31y (20y is INTERIOR)"))
    # MATCHED placebos: the same crossing shape, the same rarity, at maturities where no
    # index does anything at all. Run inside the WIDE fit so every one of them -- real
    # and placebo -- is interior and the only thing that differs is whether a $47bn
    # forced seller exists at that maturity.
    for b in (22.0, 24.0, 26.0, 28.0):
        out.append(score_ic(u_wide, b, f"PLACEBO crossing {b:.0f}y, fit 15-31y",
                            matched=True))
    out.append(score_ic(u_wide, 20.0, "REAL 20y crossing-matched, fit 15-31y",
                        matched=True))

    tab = pd.concat(out, ignore_index=True)
    print("\n" + "=" * 100)
    print("bivariate beta on the forward richness residual (bp per unit z), "
          "controlling for z_resid")
    print("=" * 100)
    print(tab.pivot_table(index="variant", columns="horizon",
                          values="beta_bp_per_z").round(4).to_string())
    print("\nNewey-West t (lags = horizon - 1):")
    print(tab.pivot_table(index="variant", columns="horizon",
                          values="t_hac").round(2).to_string())
    print("\nshare of bond-days the score flags:")
    print(tab.groupby("variant")["flagged_pct"].first().round(2).to_string())

    tab.to_csv(BP.panel_dir() / "deletion_control.csv", index=False)
    print(f"\nwrote {BP.panel_dir() / 'deletion_control.csv'}")

    print("\n" + "=" * 100)
    print("HOW TO READ THIS")
    print("=" * 100)
    print("If the REAL 20y boundary keeps its coefficient when the fit is widened AND the")
    print("PLACEBO boundaries show nothing, the effect is index deletion.")
    print("If the placebos reproduce it, the effect is position-in-the-fitting-window and")
    print("has nothing to do with ETFs, indices or forced selling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
