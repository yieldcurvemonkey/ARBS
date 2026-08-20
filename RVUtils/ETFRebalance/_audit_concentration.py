"""Independent adversarial re-implementation of _run_concentration_search.py.

Re-derives the same cells with an independently-written statistics pipeline (z-score,
forward residual, orthogonalization, exec_lag, date-clustered stat, Newey-West t), using
only the shared RAW data loaders (bond_panel, float_panel, holdings_panel, universe spec)
-- not the report's own helper functions -- so a bug specific to
_run_concentration_search.py would show up as a discrepancy.

Also runs the checks the report did NOT run: exclude-2020, exclude-best-year, and a
Newey-West corrected t on the two deciding cells.
"""
from __future__ import annotations

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

pd.set_option("display.width", 240)


# --------------------------------------------------------------------------- own stats


def my_cs_z(raw: pd.Series, dates: pd.Series) -> pd.Series:
    """My own cross-sectional robust z (median/MAD, fallback sd), independent of signals.py."""
    df = pd.DataFrame({"raw": raw.to_numpy(), "date": dates.to_numpy()})
    med = df.groupby("date")["raw"].transform("median")
    mad = (df["raw"] - med).abs().groupby(df["date"]).transform("median") * 1.4826
    sd = df.groupby("date")["raw"].transform("std")
    scale = mad.where(mad > 0, sd).replace(0.0, np.nan)
    z = (df["raw"] - med) / scale
    return pd.Series(z.to_numpy(), index=raw.index).clip(-5, 5)


def my_fwd_resid(df: pd.DataFrame, h: int) -> pd.Series:
    d = df.sort_values(["cusip", "date"])
    fwd = -(d.groupby("cusip")["resid_bp"].shift(-h) - d["resid_bp"])
    return fwd.reindex(df.index)


def my_orth(df: pd.DataFrame, target: str, control: str) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _, g in df.groupby("date", sort=False):
        x = g[control].to_numpy(float)
        y = g[target].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 8:
            continue
        xc = x[ok] - x[ok].mean()
        den = float(xc @ xc)
        if den <= 0:
            continue
        b = float(xc @ (y[ok] - y[ok].mean()) / den)
        r = np.full(len(g), np.nan)
        r[ok] = y[ok] - (y[ok].mean() + b * xc)
        out.loc[g.index] = r
    return out


def my_date_clustered(edge: pd.Series, dates: pd.Series) -> dict:
    per_date = edge.groupby(dates).mean()
    per_date = per_date.dropna()
    n_dates = len(per_date)
    if n_dates < 10:
        return dict(n_dates=n_dates, mean_bp=np.nan, t=np.nan)
    m = float(per_date.mean())
    sd = float(per_date.std(ddof=1))
    t = m / (sd / np.sqrt(n_dates)) if sd > 0 else np.nan
    return dict(n_dates=n_dates, mean_bp=m, t=t)


def newey_west_t(x: np.ndarray, lags: int) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 10:
        return np.nan
    e = x - x.mean()
    gamma0 = float(e @ e) / n
    var = gamma0
    for L in range(1, min(int(lags), n - 1) + 1):
        cov = float(e[L:] @ e[:-L]) / n
        var += 2.0 * (1.0 - L / (lags + 1.0)) * cov
    if var <= 0:
        return np.nan
    return float(x.mean() / np.sqrt(var / n))


def build(fund: str, exec_lag: int = 1) -> pd.DataFrame:
    sp = spec(fund)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([fund], panel=panel)
    cfg = EN.merge_config({"fund": fund, "universe": {"start": "2016-01-01"}})
    uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)
    d = uni.copy()

    # raw active_w signal (buy-is-positive == underweight): reimplemented directly, not
    # imported from signals.py
    raw_aw = -d["active_w"]
    d["z_active_w_raw"] = my_cs_z(raw_aw, d["date"])
    d["z_resid_raw"] = my_cs_z(d["resid_bp"], d["date"])

    for h in (21, 63):
        d[f"fwd_{h}"] = my_fwd_resid(d, h)
        d[f"fwd_{h}_orth"] = my_orth(d, f"fwd_{h}", "z_resid_raw")

    d = d.sort_values(["cusip", "date"])
    d["z_active_w"] = d.groupby("cusip")["z_active_w_raw"].shift(exec_lag)
    d["z_resid"] = d.groupby("cusip")["z_resid_raw"].shift(exec_lag)
    d["direction"] = np.sign(d["z_active_w"])
    for h in (21, 63):
        d[f"edge_{h}"] = d["direction"] * d[f"fwd_{h}_orth"]
    d["year"] = d["date"].dt.year
    return d


def report(fund: str) -> None:
    print(f"\n{'='*90}\n{fund}\n{'='*90}")
    d = build(fund)
    h = 63
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])
    print(f"universe: {len(sub_all):,} obs, {sub_all['date'].nunique():,} dates, "
          f"{sub_all['cusip'].nunique()} cusips")

    base = my_date_clustered(sub_all[f"edge_{h}"], sub_all["date"])
    print("baseline (unconditional, 63d):", base)

    for thr in (2.0, 2.5, 3.0):
        sub = sub_all[sub_all["z_active_w"].abs() >= thr]
        st = my_date_clustered(sub[f"edge_{h}"], sub["date"])
        per_date = sub.groupby("date")[f"edge_{h}"].mean().dropna()
        nw_t = newey_west_t(per_date.to_numpy(), lags=h - 1)
        print(f"|z|>={thr}: n_obs={len(sub)} n_dates={st['n_dates']} mean_bp={st['mean_bp']:.4f} "
              f"naive_t={st['t']:.2f} NW_t(lags={h-1})={nw_t:.2f}")

    # year-conditioned, |z|>=2.5
    sub25 = sub_all[sub_all["z_active_w"].abs() >= 2.5]
    print("\nper-year, |z|>=2.5, 63d:")
    for year, g in sub25.groupby("year"):
        st = my_date_clustered(g[f"edge_{h}"], g["date"])
        print(f"  {year}: n_obs={len(g)} n_dates={st['n_dates']} mean_bp={st['mean_bp']:.4f} t={st['t']:.2f}")

    # cusip concentration within |z|>=2.5
    bc = sub25.groupby("cusip").agg(n=("date", "size"), mean_edge=(f"edge_{h}", "mean")).sort_values("n", ascending=False)
    if len(bc):
        top5 = bc["n"].head(5).sum() / bc["n"].sum() * 100
        top10 = bc["n"].head(10).sum() / bc["n"].sum() * 100
        print(f"\ncusip concentration |z|>=2.5: n_cusips={len(bc)} top5_share={top5:.1f}% top10_share={top10:.1f}%")
        print(bc.head(6).round(4).to_string())

    # exclude 2020
    sub_ex2020 = sub_all[sub_all["year"] != 2020]
    st = my_date_clustered(sub_ex2020[f"edge_{h}"], sub_ex2020["date"])
    print(f"\nbaseline excl-2020 (unconditional): mean_bp={st['mean_bp']:.4f} t={st['t']:.2f} n_dates={st['n_dates']}")
    sub25_ex2020 = sub25[sub25["year"] != 2020]
    st = my_date_clustered(sub25_ex2020[f"edge_{h}"], sub25_ex2020["date"])
    print(f"|z|>=2.5 excl-2020: mean_bp={st['mean_bp']:.4f} t={st['t']:.2f} n_dates={st['n_dates']}")

    # exclude best year (by |z|>=2.5 cell mean)
    yr_stats = sub25.groupby("year").apply(lambda g: my_date_clustered(g[f"edge_{h}"], g["date"])["mean_bp"])
    best_year = yr_stats.idxmax()
    sub25_exbest = sub25[sub25["year"] != best_year]
    st = my_date_clustered(sub25_exbest[f"edge_{h}"], sub25_exbest["date"])
    print(f"|z|>=2.5 excl-best-year({best_year}, {yr_stats[best_year]:.4f}bp): mean_bp={st['mean_bp']:.4f} t={st['t']:.2f} n_dates={st['n_dates']}")

    # month_end3 vs rest
    me = d["date"] + pd.offsets.MonthEnd(0)
    dte = (me - d["date"]).dt.days
    d2 = sub_all.copy()
    d2["is_month_end3"] = dte.loc[d2.index] <= 3
    for flag, g in d2.groupby("is_month_end3"):
        st = my_date_clustered(g[f"edge_{h}"], g["date"])
        print(f"month_end3={flag}: mean_bp={st['mean_bp']:.4f} t={st['t']:.2f} n_dates={st['n_dates']}")

    return d


for fund in ("TLT", "TLH"):
    report(fund)
