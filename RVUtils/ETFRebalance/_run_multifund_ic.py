"""Cross-fund, whole-curve IC surface: does the headline TLT active-weight story
generalise to any other ICE US Treasury band, and does a SMALLER fund in a THINNER
sector move a yield more because it owns more of the float?

Run: for each fund with landed holdings data, prepare its own index-band universe,
compute the fund's ownership share of the free float in its band, the measured
butterfly round-trip cost in that band, and the raw + resid-partialled IC surface for
every signal in SIG.HOLDINGS_BASED at horizons 5/10/21/42/63 with exec_lag=1.

A date is only ever counted for a fund if a holdings document was actually scraped for
it. Filling the outer-join gap with active_w = -w_index (which is what happens if a date
is in the priced panel but not in the holdings store) is not "underweight" -- it is "no
data" mis-typed as a position, and it would inject spurious cross-sectional variation
for the exact stretches (TLT/TLH H1 2017; every fund before its scrape started) where
the flag is most likely to fire, IEF/IEI/GOVT/SHY before 2018-01-02 above all.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings import store as HS  # noqa: E402
from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import costs as C  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 30)

HORIZONS = (5, 10, 21, 42, 63)
FUNDS = ["TLT", "TLH", "IEF", "IEI", "GOVT", "SHY"]
CANDIDATES = sorted(SIG.HOLDINGS_BASED)
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                      "notebooks", "backtests", "etf_rebalance", "_data")
os.makedirs(OUTDIR, exist_ok=True)


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


def spearman_ic(d: pd.DataFrame, sig_col: str, ret_col: str, min_names: int = 8) -> np.ndarray:
    per = []
    for _, g in d.groupby("date", sort=False):
        if len(g) < min_names:
            continue
        per.append(IC._spearman(g[sig_col].to_numpy(float), g[ret_col].to_numpy(float)))
    return np.array([x for x in per if np.isfinite(x)], float)


def bivariate(df: pd.DataFrame, sig: str, ctrl: str, h: int) -> dict:
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
    return {
        "signal": sig, "horizon": h, "n_dates": b_sig.size,
        "beta_signal_bp": float(b_sig.mean()),
        "t_signal": float(b_sig.mean() / (b_sig.std(ddof=1) / np.sqrt(b_sig.size))),
        "beta_resid_bp": float(b_ctl.mean()),
        "t_resid": float(b_ctl.mean() / (b_ctl.std(ddof=1) / np.sqrt(b_ctl.size))),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", default=",".join(FUNDS))
    ap.add_argument("--exec-lag", type=int, default=1)
    a = ap.parse_args()
    funds = [f.strip().upper() for f in a.funds.split(",") if f.strip()]

    panel = FP.asof_join(BP.load(), FP.load())
    print(f"panel: {len(panel):,} rows, {panel['date'].nunique():,} dates, "
          f"{panel['cusip'].nunique():,} cusips\n")

    coverage_rows, ownership_rows, cost_rows = [], [], []
    ic_rows, biv_rows, dsort_rows, funnel_rows = [], [], [], []
    n_configs = 0

    for fund in funds:
        print("=" * 100)
        print(fund)
        print("=" * 100)
        sp = spec(fund)
        cov = HS.coverage(fund)
        if cov.empty:
            print(f"  NO HOLDINGS DATA landed for {fund} -- skipped.\n")
            coverage_rows.append({"fund": fund, "status": "no_data"})
            continue

        first_date, last_date = cov["first"].min(), cov["last"].max()
        n_holding_dates = int(cov["dates"].sum())
        gap_years = cov[cov["dates"] < cov["dates"].median() * 0.6]
        print(f"  band: {sp.band_low}-{sp.band_high}y   holdings coverage: "
              f"{first_date.date()} .. {last_date.date()}, {n_holding_dates:,} scraped dates")
        if not gap_years.empty:
            print(f"  THIN YEARS (partial coverage, likely a scrape gap): "
                  f"{gap_years[['year','dates']].to_dict('records')}")
        coverage_rows.append({
            "fund": fund, "status": "ok", "band_low": sp.band_low, "band_high": sp.band_high,
            "first_date": first_date, "last_date": last_date,
            "n_holding_dates": n_holding_dates,
            "thin_years": ",".join(str(y) for y in gap_years["year"]) if not gap_years.empty else "",
        })

        joined = HP.build([fund], panel=panel)
        valid_dates = set(pd.to_datetime(joined.loc[joined["ticker"] == fund, "date"].unique()))

        cfg = EN.merge_config({"fund": fund, "universe": {"start": first_date.strftime("%Y-%m-%d")}})
        uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
        funnel["fund"] = fund
        funnel_rows.append(funnel)
        before = len(uni)
        uni = uni[uni["date"].isin(valid_dates)].copy()
        print(f"  gated universe: {before:,} bond-days before holdings-date filter -> "
              f"{len(uni):,} after; {uni['date'].nunique():,} dates, {uni['cusip'].nunique():,} cusips")

        if uni.empty or uni["date"].nunique() < 60:
            print("  too little data after gating -- skipped.\n")
            continue

        # -------------------------------------------------------- 1. ownership of float
        own_by_date = uni.groupby("date").apply(
            lambda g: g["par"].sum() / g["free_float"].sum() if g["free_float"].sum() > 0 else np.nan)
        own_by_date = own_by_date.dropna()
        own_summary = {
            "fund": fund, "median_pct": float(own_by_date.median() * 100),
            "p90_pct": float(own_by_date.quantile(0.90) * 100),
            "latest_pct": float(own_by_date.iloc[-1] * 100) if len(own_by_date) else np.nan,
            "n_cusips_median": int(uni.groupby("date")["cusip"].nunique().median()),
        }
        ownership_rows.append(own_summary)
        print(f"  fund's share of free float in its band: median {own_summary['median_pct']:.2f}%, "
              f"p90 {own_summary['p90_pct']:.2f}%, latest {own_summary['latest_pct']:.2f}%, "
              f"median cusips/day {own_summary['n_cusips_median']}")

        # -------------------------------------------------------- 2. measured cost
        lo = sp.band_low or 0.0
        hi = min(sp.band_high or 31.0, 31.0)
        cost_tab = C.measured_spread_summary(panel[panel["date"] >= first_date],
                                             bands=((lo, hi),))
        cost_tab.insert(0, "fund", fund)
        cost_rows.append(cost_tab)
        if not cost_tab.empty:
            rt_med = cost_tab["fly_rt_bp_med"].median()
            rt_lo, rt_hi = cost_tab["fly_rt_bp_med"].min(), cost_tab["fly_rt_bp_med"].max()
            print(f"  measured butterfly round-trip cost in {lo}-{hi}y: "
                  f"median {rt_med:.3f}bp across years, range {rt_lo:.3f}-{rt_hi:.3f}bp")
        else:
            rt_med = np.nan
            print("  measured cost table empty (no priced two-sided quotes in band)")

        # -------------------------------------------------------- signals + IC
        kw = {"flow": {"window": 5}, "active_chg": {"window": 5},
              "ownership_chg": {"window": 21}}
        d = uni.copy()
        for name in list(CANDIDATES) + ["resid"]:
            raw = SIG.REGISTRY[name](d, **kw.get(name, {}))
            d[f"z_{name}"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)

        d = IC.forward_residual_return(d, HORIZONS)
        lagcols = [f"z_{c}" for c in CANDIDATES + ["resid"]]
        d = d.sort_values(["cusip", "date"])
        d_lag0 = d.copy()  # diagnostic only, exec_lag=0, kept separate and labelled
        for c in lagcols:
            d[c] = d.groupby("cusip")[c].shift(a.exec_lag)

        for c in CANDIDATES:
            col, pcol = f"z_{c}", f"p_{c}"
            d[pcol] = orthogonalise(d, col, "z_resid")
            for h in HORIZONS:
                for lbl, use in (("raw", col), ("partial", pcol)):
                    v = spearman_ic(d, use, f"fwd_{h}")
                    n_configs += 1
                    if v.size < 20:
                        continue
                    ic_rows.append({
                        "fund": fund, "signal": c, "kind": lbl, "horizon": h,
                        "exec_lag": a.exec_lag,
                        "ic": float(v.mean()),
                        "t": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
                        "n_dates": v.size,
                    })

        # lag-0 diagnostic, clearly labelled, only for active_w and ownership at 63d
        d0 = d_lag0
        for c in ("active_w", "ownership"):
            col = f"z_{c}"
            v0 = spearman_ic(d0, col, "fwd_63")
            n_configs += 1
            if v0.size >= 20:
                ic_rows.append({
                    "fund": fund, "signal": c, "kind": "raw_LAG0_DIAGNOSTIC", "horizon": 63,
                    "exec_lag": 0,
                    "ic": float(v0.mean()),
                    "t": float(v0.mean() / (v0.std(ddof=1) / np.sqrt(v0.size))),
                    "n_dates": v0.size,
                })

        for c in CANDIDATES:
            for h in HORIZONS:
                r = bivariate(d, f"z_{c}", "z_resid", h)
                n_configs += 1
                if r:
                    r["fund"] = fund
                    r["cost_rt_bp_med"] = rt_med
                    biv_rows.append(r)

        # -------------------------------------------------------- double sort, best signal
        fund_ic = pd.DataFrame([r for r in ic_rows if r["fund"] == fund and r["kind"] == "partial"])
        if not fund_ic.empty:
            best = fund_ic.loc[fund_ic["ic"].abs().idxmax()]
            bc, bh = best["signal"], int(best["horizon"])
            g = d.dropna(subset=[f"z_{bc}", "z_resid", f"fwd_{bh}"]).copy()
            if not g.empty:
                g["qr"] = g.groupby("date")["z_resid"].transform(
                    lambda x: pd.qcut(x.rank(method="first"), 5, labels=False, duplicates="drop"))
                g["qs"] = g.groupby(["date", "qr"])[f"z_{bc}"].transform(
                    lambda x: pd.qcut(x.rank(method="first"), 3, labels=False, duplicates="drop"))
                tab = g.pivot_table(index="qr", columns="qs", values=f"fwd_{bh}", aggfunc="mean")
                cnt = g.pivot_table(index="qr", columns="qs", values=f"fwd_{bh}", aggfunc="size")
                if tab.shape[1] >= 2:
                    spread = tab[tab.columns.max()] - tab[tab.columns.min()]
                    print(f"\n  BEST partial-IC cell: {bc} @ {bh}d  ic={best['ic']:.4f}  t={best['t']:.2f}")
                    print(f"  double sort (resid quintile x {bc} tercile), fwd_{bh} bp, high-minus-low "
                          f"by resid quintile: {spread.round(4).to_dict()}")
                    for qr_i, sv in spread.items():
                        dsort_rows.append({"fund": fund, "signal": bc, "horizon": bh,
                                           "resid_quintile": qr_i, "hml_bp": sv,
                                           "n_min": int(cnt.loc[qr_i].min())})
        print()

    # ---------------------------------------------------------------- write outputs
    cov_df = pd.DataFrame(coverage_rows)
    own_df = pd.DataFrame(ownership_rows)
    cost_df = pd.concat(cost_rows, ignore_index=True) if cost_rows else pd.DataFrame()
    ic_df = pd.DataFrame(ic_rows)
    biv_df = pd.DataFrame(biv_rows)
    dsort_df = pd.DataFrame(dsort_rows)
    funnel_df = pd.DataFrame(funnel_rows)

    cov_df.to_csv(os.path.join(OUTDIR, "multifund_coverage.csv"), index=False)
    own_df.to_csv(os.path.join(OUTDIR, "multifund_ownership.csv"), index=False)
    cost_df.to_csv(os.path.join(OUTDIR, "multifund_cost.csv"), index=False)
    ic_df.to_csv(os.path.join(OUTDIR, "multifund_ic.csv"), index=False)
    biv_df.to_csv(os.path.join(OUTDIR, "multifund_bivariate.csv"), index=False)
    dsort_df.to_csv(os.path.join(OUTDIR, "multifund_doublesort.csv"), index=False)
    funnel_df.to_csv(os.path.join(OUTDIR, "multifund_funnel.csv"), index=False)

    # ---------------------------------------------------------------- ranking table
    print("=" * 100)
    print(f"CONFIGS EVALUATED: {n_configs}")
    print("=" * 100)

    if not biv_df.empty:
        # best |beta_signal_bp| among partial-surviving cells per fund at any horizon
        best_rows = []
        for fund, g in biv_df.groupby("fund"):
            gg = g.reindex(g["beta_signal_bp"].abs().sort_values(ascending=False).index)
            best_rows.append(gg.iloc[0])
        best_df = pd.DataFrame(best_rows)
        best_df = best_df.merge(own_df[["fund", "median_pct"]], on="fund", how="left")
        best_df["edge_over_cost"] = best_df["beta_signal_bp"].abs() / best_df["cost_rt_bp_med"]
        best_df = best_df.sort_values("edge_over_cost", ascending=False)
        best_df.to_csv(os.path.join(OUTDIR, "multifund_ranking.csv"), index=False)
        print("\nRANKING -- best per-z bivariate bp (partialled vs resid) / measured RT cost:")
        print(best_df[["fund", "signal", "horizon", "beta_signal_bp", "t_signal",
                       "cost_rt_bp_med", "edge_over_cost", "median_pct"]].round(4).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
