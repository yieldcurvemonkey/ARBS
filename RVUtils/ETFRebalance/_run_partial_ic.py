"""Does the ETF data add anything the bond's own richness does not already say?

The question this file exists to answer
---------------------------------------
The first IC pass found that ``active_w`` predicts the forward richness residual with
t = -14 at 63 days -- **in the opposite direction to the stated hypothesis**: the bonds
TLT is OVER-weight subsequently richen, and the ones it is under-weight cheapen. It also
found ``ownership`` pointing the same way (t = +15), which is the same statement made a
second way, and ``resid`` -- the control, which reads no holdings file at all --
predicting far harder than either (t = +51).

That last number is the problem. Cash-Treasury richness mean-reverts for reasons that
have nothing to do with ETFs, and a fund that overweights large, liquid, recently issued
bonds is overweighting a set that is *also* systematically rich. So the raw IC on
``active_w`` may be nothing but a noisy re-reading of ``resid``, and the whole scrape
would have bought a worse version of a number already in the panel.

Three ways of asking, because one is not enough
-----------------------------------------------
**Partial IC.** Orthogonalise each signal against ``resid`` cross-sectionally, date by
date, then re-run the IC. What survives is what the holdings data knows and the price
does not.

**Double sort.** Inside each residual quintile, sort on the signal. Non-parametric, so
it does not assume the relationship is linear, and it shows whether any surviving effect
is spread across the book or lives in one corner of it.

**Bivariate regression.** Both signals in one cross-sectional regression per date, with
the t-statistic taken across dates. Gives the coefficients in the units the decision is
made in: basis points of forward richening per unit of z.

The calendar null is repaired here too
---------------------------------------
``deletion`` and ``month_end`` were dropped from the first pass for having no
cross-sectional variation to standardise. ``month_end`` genuinely has none -- it is the
same for every bond on a given day -- so it is a **timing** overlay and not a signal, and
it is scored that way. ``deletion`` does vary across bonds and was simply mis-built; it
is rebuilt and re-tested here, because it is the null that says whether the scrape was
necessary: it needs no holdings file whatsoever.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 220)
HORIZONS = (5, 10, 21, 42, 63)
CANDIDATES = ["active_w", "active_rel", "active_chg", "flow", "ownership",
              "ownership_chg", "deletion"]


def orthogonalise(df: pd.DataFrame, target: str, control: str) -> pd.Series:
    """Residual of ``target`` on ``control``, cross-sectionally, one date at a time."""
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.groupby("date", sort=False):
        x = g[control].to_numpy(float)
        y = g[target].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 8:
            continue
        xc = x[ok] - x[ok].mean()
        den = float(np.dot(xc, xc))
        if den <= 0:
            continue
        b = float(np.dot(xc, y[ok] - y[ok].mean()) / den)
        r = np.full(len(g), np.nan)
        r[ok] = y[ok] - (y[ok].mean() + b * xc)
        out.loc[g.index] = r
    return out


def bivariate(df: pd.DataFrame, sig: str, ctrl: str, h: int) -> dict:
    """Per-date cross-sectional OLS of forward return on [signal, control]."""
    b_sig, b_ctl = [], []
    for _, g in df.groupby("date", sort=False):
        y = g[f"fwd_{h}"].to_numpy(float)
        X = np.column_stack([g[sig].to_numpy(float), g[ctrl].to_numpy(float)])
        ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
        if ok.sum() < 10:
            continue
        A = np.column_stack([np.ones(ok.sum()), X[ok]])
        try:
            beta, *_ = np.linalg.lstsq(A, y[ok], rcond=None)
        except np.linalg.LinAlgError:
            continue
        b_sig.append(beta[1])
        b_ctl.append(beta[2])
    b_sig, b_ctl = np.array(b_sig), np.array(b_ctl)
    if b_sig.size < 20:
        return {}
    # Same overlap problem as the IC: the per-date betas of an h-day forward return are
    # not independent draws, so the t is Newey-West at h-1 lags.
    return {
        "signal": sig, "horizon": h, "n_dates": b_sig.size,
        "beta_signal_bp": float(b_sig.mean()),
        "t_signal": IC.newey_west_t(b_sig, lags=max(1, h - 1)),
        "t_signal_naive": float(b_sig.mean() / (b_sig.std(ddof=1) / np.sqrt(b_sig.size))),
        "beta_resid_bp": float(b_ctl.mean()),
        "t_resid": IC.newey_west_t(b_ctl, lags=max(1, h - 1)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", default="TLT")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    a = ap.parse_args()

    sp = spec(a.fund)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([a.fund], panel=panel)
    cfg = EN.merge_config({"fund": a.fund, "universe": {"start": a.start}})
    uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)
    print(f"{a.fund}: {len(uni):,} gated bond-days, {uni['date'].nunique():,} dates\n")

    kw = {"deletion": {"band_low": sp.band_low or 0.0, "horizon_m": 3},
          "addition": {"band_high": sp.band_high or np.inf},
          "flow": {"window": 5}, "active_chg": {"window": 5},
          "ownership_chg": {"window": 21}}

    d = uni.copy()
    for name in CANDIDATES + ["resid"]:
        raw = SIG.REGISTRY[name](d, **kw.get(name, {}))
        d[f"z_{name}"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)

    # --- the repaired calendar null -------------------------------------------------
    del_raw = SIG.REGISTRY["deletion"](d, band_low=sp.band_low or 0.0, horizon_m=3)
    print("calendar null 'deletion' -- share of bond-days flagged for removal at a "
          f"rebalance inside 3 months: {float((del_raw < 0).mean()) * 100:.2f}%")
    print(f"  distinct values: {sorted(np.unique(np.round(del_raw.dropna(), 3)))[:8]}")
    n_var = d.groupby("date")["z_deletion"].apply(lambda s: s.notna().sum())
    print(f"  dates with a usable cross-section: {int((n_var > 0).sum())} of {len(n_var)}\n")

    d = IC.forward_residual_return(d, HORIZONS)
    lagcols = [f"z_{c}" for c in CANDIDATES + ["resid"]]
    if a.exec_lag:
        d = d.sort_values(["cusip", "date"])
        for c in lagcols:
            d[c] = d.groupby("cusip")[c].shift(a.exec_lag)

    print("=" * 100)
    print("1. RAW vs PARTIAL IC -- partial = orthogonalised against z_resid, per date")
    print("=" * 100)
    rows = []
    for c in CANDIDATES:
        col, pcol = f"z_{c}", f"p_{c}"
        d[pcol] = orthogonalise(d, col, "z_resid")
        for h in HORIZONS:
            for lbl, use in (("raw", col), ("partial", pcol)):
                per = []
                for _, g in d.groupby("date", sort=False):
                    if len(g) < 8:
                        continue
                    per.append(IC._spearman(g[use].to_numpy(float),
                                            g[f"fwd_{h}"].to_numpy(float)))
                v = np.array([x for x in per if np.isfinite(x)], float)
                if v.size < 20:
                    continue
                rows.append({"signal": c, "kind": lbl, "horizon": h,
                             "ic": float(v.mean()),
                             # Newey-West: an h-day forward return sampled daily shares
                             # h-1 days with its neighbour, so the naive t treats ~2,400
                             # overlapping windows as ~2,400 independent draws.
                             "t": IC.newey_west_t(v, lags=max(1, h - 1)),
                             "t_naive": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
                             "n_dates": v.size})
    ic = pd.DataFrame(rows)
    if not ic.empty:
        print("\nIC:")
        print(ic.pivot_table(index=["signal", "kind"], columns="horizon", values="ic").round(4).to_string())
        print("\nt across dates:")
        print(ic.pivot_table(index=["signal", "kind"], columns="horizon", values="t").round(2).to_string())
        ic.to_parquet(BP.panel_dir() / "partial_ic.parquet", index=False)

    print("\n" + "=" * 100)
    print("2. BIVARIATE REGRESSION -- forward bp per unit z, signal AND resid together")
    print("=" * 100)
    biv = pd.DataFrame([r for c in CANDIDATES for h in HORIZONS
                        if (r := bivariate(d, f"z_{c}", "z_resid", h))])
    if not biv.empty:
        print(biv.round(4).to_string(index=False))
        biv.to_parquet(BP.panel_dir() / "bivariate.parquet", index=False)

    print("\n" + "=" * 100)
    print("3. DOUBLE SORT -- mean forward bp by (resid quintile x signal quintile)")
    print("=" * 100)
    for c, h in (("active_w", 63), ("ownership", 63), ("active_w", 21)):
        g = d.dropna(subset=[f"z_{c}", "z_resid", f"fwd_{h}"]).copy()
        if g.empty:
            continue
        g["qr"] = g.groupby("date")["z_resid"].transform(
            lambda x: pd.qcut(x.rank(method="first"), 5, labels=False, duplicates="drop"))
        g["qs"] = g.groupby(["date", "qr"])[f"z_{c}"].transform(
            lambda x: pd.qcut(x.rank(method="first"), 3, labels=False, duplicates="drop"))
        tab = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="mean")
        cnt = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="size")
        print(f"\n{c} @ {h}d  (rows = resid quintile 0=rich..4=cheap, "
              f"cols = signal tercile 0=low..2=high), bp:")
        print(tab.round(4).to_string())
        print(f"  n per cell (min {int(cnt.min().min()):,}):")
        spread = (tab[tab.columns.max()] - tab[tab.columns.min()])
        print(f"  high-minus-low signal within each resid quintile: "
              f"{spread.round(4).to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
