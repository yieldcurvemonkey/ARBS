"""Seasonality of the ETF-rebalance signal, of its null, and of the opportunity itself.

Three separate questions, deliberately kept apart because they have different answers:

1. **Is the SIGNAL seasonal?**  The most-underweight-minus-most-overweight decile spread,
   cut by business day relative to month end, by day of month, by day of week and by
   month.  Carried alongside a **maturity-matched placebo**: the same selection rule
   applied to a signal permuted *within* (date, TTM stratum), so the placebo legs have
   the same maturity profile as the real ones and no holdings content whatsoever.

2. **Is the FUND'S OWN BEHAVIOUR seasonal?**  Sum of ``|d par per share|`` by business
   day relative to month end, across every scraped fund.  This one is measured in the
   holdings themselves rather than inferred from a price, and it is the part that is
   real.

3. **Is the OPPORTUNITY seasonal?**  Cross-sectional dispersion of the richness residual.
   If the dispersion is seasonal then the strategy's *ceiling* is seasonal, which is
   worth knowing whether or not any signal works.

Three measurement rules that are not optional
----------------------------------------------
**The month-end anchor is the panel's own last trading date of the month**, not
``bdate_range``'s.  FedInvest observes holidays that a naive business-day calendar does
not, and an anchor that is off by one day smears the single most important cell.

**``|d par per share|`` must see entries and exits.**  A diff taken on rows present in
both files misses a bond that ENTERS the book and one that LEAVES it -- and a
reconstitution is precisely entries and exits.  Each fund is therefore pivoted to a
dense (date x cusip) frame with absent holdings filled as zero inside the bond's own
observation window, so a deletion registers its full size on the day it happens.

**The Newey-West lag is set by the CELL's own spacing, not by the horizon.**  A 10-day
forward return sampled once a month does not overlap at all; the same return sampled on
consecutive days inside a calendar month overlaps nine times.  Using ``h-1`` lags
everywhere would over-correct the monthly cells by a factor of twenty and would read as
"nothing survives" for purely arithmetic reasons -- which is the opposite failure to the
one §3.4 of RESULTS.md corrects, and just as wrong.
"""

from __future__ import annotations

import argparse
import os
import pathlib

os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")

import numpy as np
import pandas as pd

from MDP.ETFHoldings.universe import REGISTRY
from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import engine as EN
from RVUtils.ETFRebalance import float_panel as FP
from RVUtils.ETFRebalance import holdings_panel as HP
from RVUtils.ETFRebalance import ic as IC
from RVUtils.ETFRebalance import signals as SIG

DATA = pathlib.Path(__file__).resolve().parents[2] / "notebooks/backtests/etf_rebalance/_data"
HORIZONS = (1, 5, 10, 21)
HEADLINE = 10
N_PERM = 100
#: How many of the permutation draws are kept as COMPLETE alternative series. All of
#: them: the draws are computed either way, and 100 is what takes the resolution of a
#: "how often did a holdings-free series beat this?" p-value from 0.05 to 0.01.
N_KEEP = 100
N_STRATA = 5
SEED = 20260820


# ------------------------------------------------------------------ calendar keys

def calendar_keys(dates) -> pd.DataFrame:
    """Signed business-day distance to the nearest month-end anchor, plus the plain cuts.

    The anchor is the last *observed* trading date of each month, and the distance is
    counted in positions along the panel's own sorted date index -- so a Thanksgiving or
    a Good Friday cannot shift a bond into the wrong cell.
    """
    d = pd.DatetimeIndex(pd.Series(pd.to_datetime(pd.Series(dates))).unique()).sort_values()
    pos = np.arange(len(d))
    ym = pd.Series(d, index=d).dt.to_period("M")
    anchors = pd.Series(pos, index=d).groupby(ym.to_numpy()).max().to_numpy()
    anchors = np.sort(anchors)

    i = np.searchsorted(anchors, pos)
    prev_ = np.clip(i - 1, 0, len(anchors) - 1)
    next_ = np.clip(i, 0, len(anchors) - 1)
    dp = pos - anchors[prev_]
    dn = pos - anchors[next_]
    bd_me = np.where(np.abs(dp) <= np.abs(dn), dp, dn)

    out = pd.DataFrame({"date": d})
    out["pos"] = pos
    out["bd_me"] = bd_me
    #: Which month-end cycle each date belongs to. The pre/post contrast is averaged
    #: WITHIN a cycle before it is averaged across cycles, so nine consecutive days of
    #: overlapping 10-day returns count as one observation rather than nine.
    out["anchor_id"] = np.where(np.abs(dp) <= np.abs(dn), prev_, next_)
    out["dom"] = out["date"].dt.day
    out["dow"] = out["date"].dt.dayofweek                       # 0 = Monday
    out["moy"] = out["date"].dt.month
    out["year"] = out["date"].dt.year
    return out


# ------------------------------------------------------- decile spread + placebo

def _spread(sig: np.ndarray, fwd: np.ndarray, n_buckets: int = 10) -> float:
    """Top-decile minus bottom-decile mean forward bp for one date.

    A decile of a ~32-name cross-section is ~3 names, which is the same granularity the
    backtest trades at.  That is stated in every caption rather than hidden behind the
    word "decile".
    """
    ok = np.isfinite(sig) & np.isfinite(fwd)
    if ok.sum() < 2 * n_buckets:
        return np.nan
    s, f = sig[ok], fwd[ok]
    k = max(1, int(round(s.size / n_buckets)))
    order = np.argsort(s, kind="stable")
    return float(f[order[-k:]].mean() - f[order[:k]].mean())


def per_date_spreads(uni: pd.DataFrame, sig_col: str, *, exec_lag: int = 1,
                     horizons=HORIZONS, n_perm: int = N_PERM, n_keep: int = N_KEEP,
                     n_strata: int = N_STRATA, seed: int = SEED) -> pd.DataFrame:
    """Per-date decile spread of ``sig_col``, plus a maturity-matched placebo.

    The placebo permutes the signal within (date, TTM stratum).  The permuted legs draw
    from the same maturity strata in the same proportions as the real legs, so anything
    the real spread earns *because of where on the curve it sits* is reproduced by the
    placebo and only the holdings content is destroyed.
    """
    d = IC.forward_residual_return(uni, list(horizons)).sort_values(["cusip", "date"])
    if exec_lag:
        d[sig_col] = d.groupby("cusip")[sig_col].shift(exec_lag)
    d = d.sort_values("date", kind="stable").reset_index(drop=True)

    dates = d["date"].to_numpy()
    bounds = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1], True])
    sig = d[sig_col].to_numpy(float)
    ttm = d["ttm"].to_numpy(float)
    fwds = {h: d[f"fwd_{h}"].to_numpy(float) for h in horizons}

    rng = np.random.default_rng(seed)
    rows = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        n = b - a
        if n < 20:
            continue
        s = sig[a:b]
        nf = int(np.isfinite(s).sum())
        rec = {"date": pd.Timestamp(dates[a]), "n_names": nf,
               "n_leg": max(1, int(round(nf / 10)))}
        for h in horizons:
            rec[f"real_{h}"] = _spread(s, fwds[h][a:b])

        if n_perm:
            t = ttm[a:b]
            try:
                strat = pd.qcut(t, n_strata, labels=False, duplicates="drop")
            except ValueError:
                strat = np.zeros(n, int)
            strat = np.asarray(strat, float)
            strat = np.where(np.isfinite(strat), strat, -1).astype(int)
            groups = [np.flatnonzero(strat == k) for k in np.unique(strat)]
            groups = [g for g in groups if g.size > 1]
            draws = {h: np.empty(n_perm) for h in horizons}
            for r in range(n_perm):
                sp = s.copy()
                for idx in groups:
                    sp[idx] = s[rng.permutation(idx)]
                for h in horizons:
                    draws[h][r] = _spread(sp, fwds[h][a:b])
            for h in horizons:
                rec[f"plc_{h}"] = float(np.nanmean(draws[h])) if np.isfinite(draws[h]).any() else np.nan
                rec[f"plc_sd_{h}"] = float(np.nanstd(draws[h], ddof=1)) if np.isfinite(draws[h]).sum() > 1 else np.nan
                # INDIVIDUAL draws, kept as ``n_keep`` complete placebo SERIES.
                #
                # The mean of 100 permutations is the right thing to PLOT -- it is the
                # placebo's expected value and it is smooth -- but it is the wrong thing
                # to run a t-statistic on, because averaging 100 draws divides the
                # within-date variance by 100 and hands the placebo a t-statistic that
                # is small for arithmetic reasons rather than because the placebo found
                # nothing. Each stored draw is one full alternative history with exactly
                # the same statistical character as the real series, so a cell t
                # computed on it is directly comparable, and the spread of ``max |t|``
                # across them is the multiple-comparison null this pack's own §3.5
                # lesson demands.
                for r in range(n_keep):
                    rec[f"p{r:02d}_{h}"] = float(draws[h][r])
        rows.append(rec)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ cell statistics

def _hac_t(x: np.ndarray, gap_bd: float, horizon: int) -> float:
    lags = int(max(1, np.ceil(horizon / max(1.0, gap_bd))))
    return IC.newey_west_t(x, lags=lags)


def cell_table(spreads: pd.DataFrame, cal: pd.DataFrame, key: str, *,
               horizon: int = HEADLINE, n_boot: int = 2000) -> pd.DataFrame:
    """Mean real spread, mean placebo spread, bootstrap band and HAC t, per calendar cell."""
    df = spreads.merge(cal, on="date", how="left")
    rc, pc = f"real_{horizon}", f"plc_{horizon}"
    has_plc = pc in df.columns
    rng = np.random.default_rng(SEED)
    rows = []
    for k, g in df.groupby(key, sort=True):
        g = g.sort_values("pos")
        m = np.isfinite(g[rc].to_numpy(float))
        v = g[rc].to_numpy(float)[m]
        if v.size < 12:
            continue
        p = g["pos"].to_numpy(float)[m]
        gap = float(np.median(np.diff(p))) if v.size > 1 else 1.0
        boot = rng.choice(v, size=(n_boot, v.size), replace=True).mean(axis=1)
        row = {key: k, "n": int(v.size), "gap_bd": gap,
               "mean_bp": float(v.mean()), "sd_bp": float(v.std(ddof=1)),
               "t_naive": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
               "t_hac": _hac_t(v, gap, horizon),
               "lo": float(np.percentile(boot, 5)), "hi": float(np.percentile(boot, 95))}
        if has_plc:
            q = g[pc].to_numpy(float)
            q = q[np.isfinite(q)]
            row["plc_mean_bp"] = float(q.mean()) if q.size else np.nan
            # The band is the spread of the placebo SERIES' cell means, i.e. what a
            # holdings-free selection with the same maturity profile would have printed
            # in this cell. Not a bootstrap of the smoothed placebo, which would be far
            # too tight -- see the note in ``per_date_spreads``.
            ms = [float(np.nanmean(g[f"p{r:02d}_{horizon}"].to_numpy(float)))
                  for r in range(N_KEEP) if f"p{r:02d}_{horizon}" in g.columns]
            ts = [_hac_t(g[f"p{r:02d}_{horizon}"].to_numpy(float), gap, horizon)
                  for r in range(N_KEEP) if f"p{r:02d}_{horizon}" in g.columns]
            if ms:
                row["plc_lo"] = float(np.nanpercentile(ms, 5))
                row["plc_hi"] = float(np.nanpercentile(ms, 95))
                row["plc_t_hac_max"] = float(np.nanmax(np.abs(ts)))
        rows.append(row)
    return pd.DataFrame(rows)


def placebo_null(spreads: pd.DataFrame, cal: pd.DataFrame, key: str, *,
                 horizon: int = HEADLINE, cells=None) -> pd.DataFrame:
    """One row per stored placebo series: its largest |HAC t| across the same cells.

    This is what charges the search. Reading a table of 21 business-day cells and
    reporting the biggest t is a 21-trial selection, and §3.5 of RESULTS.md is the
    cautionary case: a five-boundary search bought the calendar signal its entire
    apparent significance. Running the identical read over holdings-free series with the
    same maturity profile says how big a ``max |t|`` that search produces by itself.
    """
    df = spreads.merge(cal, on="date", how="left")
    rows = []
    for r in range(N_KEEP):
        col = f"p{r:02d}_{horizon}"
        if col not in df.columns:
            continue
        best_t, best_m, best_k = 0.0, np.nan, None
        for k, g in df.groupby(key, sort=True):
            if cells is not None and k not in cells:
                continue
            g = g.sort_values("pos")
            m = np.isfinite(g[col].to_numpy(float))
            v = g[col].to_numpy(float)[m]
            if v.size < 12:
                continue
            p = g["pos"].to_numpy(float)[m]
            gap = float(np.median(np.diff(p))) if v.size > 1 else 1.0
            t = _hac_t(v, gap, horizon)
            if np.isfinite(t) and abs(t) > best_t:
                best_t, best_m, best_k = abs(t), float(v.mean()), k
        rows.append({"draw": r, "max_abs_t": best_t, "at_cell": best_k, "mean_bp": best_m})
    return pd.DataFrame(rows)


def me_contrast(spreads: pd.DataFrame, cal: pd.DataFrame, *, horizon: int = HEADLINE,
                pre=range(-9, 0), post=range(1, 10)) -> pd.DataFrame:
    """Pre-month-end minus post-month-end, real and placebo. A TWO-cell contrast.

    Stated separately from the 21-cell table on purpose. Reading the largest of 21 cells
    is a search; asking one pre-specified question -- "does the sign of the spread differ
    either side of the reconstitution?" -- is not, and it is the question the fund's own
    measured turnover profile (figure 3) actually poses.

    **Blocked by month-end cycle.** The pre window is nine consecutive business days and
    the forward return is ten days long, so a Welch t across raw days treats nine views
    of one month as nine independent draws -- the same overlap error §3.4 of RESULTS.md
    corrects at the top level. The difference is formed inside each cycle first, and the
    t is taken across the ~120 cycles with a one-lag HAC on top.
    """
    df = spreads.merge(cal, on="date", how="left")
    out = []
    cols = [("real", f"real_{horizon}")] + [
        (f"p{r:02d}", f"p{r:02d}_{horizon}") for r in range(N_KEEP)
        if f"p{r:02d}_{horizon}" in df.columns]
    pre_m = df["bd_me"].isin(list(pre))
    post_m = df["bd_me"].isin(list(post))
    for name, c in cols:
        a = df[pre_m].groupby("anchor_id")[c].mean()
        b = df[post_m].groupby("anchor_id")[c].mean()
        j = pd.concat([a.rename("pre"), b.rename("post")], axis=1).dropna()
        if len(j) < 20:
            continue
        dif = (j["pre"] - j["post"]).to_numpy(float)
        out.append({"series": name, "n_cycles": int(len(j)),
                    "pre_bp": float(j["pre"].mean()), "post_bp": float(j["post"].mean()),
                    "diff_bp": float(dif.mean()),
                    "t_naive": float(dif.mean() / (dif.std(ddof=1) / np.sqrt(dif.size))),
                    "t_hac": IC.newey_west_t(dif, lags=1)})
    return pd.DataFrame(out)


def yearly_cell(spreads: pd.DataFrame, cal: pd.DataFrame, key: str, value,
                *, horizon: int = HEADLINE) -> pd.DataFrame:
    """Year-by-year mean of ONE calendar cell, real and placebo, with n annotated."""
    df = spreads.merge(cal, on="date", how="left")
    df = df[df[key] == value]
    rc, pc = f"real_{horizon}", f"plc_{horizon}"
    rows = []
    for y, g in df.groupby("year", sort=True):
        v = g[rc].to_numpy(float)
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        q = g[pc].to_numpy(float) if pc in g.columns else np.array([])
        q = q[np.isfinite(q)]
        rows.append({"year": int(y), "n": int(v.size), "mean_bp": float(v.mean()),
                     "se_bp": float(v.std(ddof=1) / np.sqrt(v.size)) if v.size > 1 else np.nan,
                     "plc_mean_bp": float(q.mean()) if q.size else np.nan})
    return pd.DataFrame(rows)


# ------------------------------------------------------------- fund flow intensity

def fund_intensity(tickers) -> pd.DataFrame:
    """Per (ticker, date) sum of |d par per share|, on a DENSE bond x date frame.

    Dense is the whole point.  A diff over rows that appear in both files cannot see a
    bond entering or leaving the book, and a reconstitution is entries and exits.
    """
    h = HP.load_holdings(list(tickers))
    if h.empty:
        return h
    out = []
    for tkr, g in h.groupby("ticker"):
        w = g.pivot_table(index="date", columns="cusip", values="par_per_share",
                          aggfunc="sum").sort_index()
        if w.shape[0] < 20 or w.shape[1] == 0:
            continue
        seen = w.notna().to_numpy()
        nrow = seen.shape[0]
        arr = w.to_numpy(float)
        filled = np.full_like(arr, np.nan)
        for c in range(seen.shape[1]):
            col = seen[:, c]
            if not col.any():
                continue
            lo = max(0, int(np.argmax(col)) - 1)
            hi = min(nrow - 1, nrow - 1 - int(np.argmax(col[::-1])) + 1)
            seg = arr[lo:hi + 1, c]
            filled[lo:hi + 1, c] = np.where(np.isfinite(seg), seg, 0.0)
        dv = np.abs(np.diff(filled, axis=0))
        inten = np.r_[np.nan, np.nansum(dv, axis=1)]
        allnan = np.r_[True, np.all(~np.isfinite(dv), axis=1)]
        inten[allnan] = np.nan
        out.append(pd.DataFrame({
            "ticker": tkr, "date": w.index,
            "intensity": inten,
            "n_pos": np.nansum(filled > 0, axis=1),
            "gap_days": pd.Series(w.index).diff().dt.days.to_numpy(),
        }))
    return pd.concat(out, ignore_index=True)


# ------------------------------------------------------------------------- driver

def build_universe(fund: str, ttm_max, panel, floats):
    cfg = EN.merge_config({"fund": fund,
                           "universe": {"ttm_max": ttm_max, "start": "2016-01-01"}})
    uni, funnel = EN.prepare_universe(cfg, panel=panel, floats=floats)
    # RANK-based selection, so the raw score is used directly: a decile of a monotone
    # transform of a score is the same decile, and the robust z has a documented failure
    # mode (MAD exactly zero) that has nothing to do with this question.
    uni["sig_active_w"] = SIG.sig_active_w(uni)
    uni["sig_resid"] = SIG.sig_resid(uni)
    return uni, funnel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="tlt | tlh | flow")
    args = ap.parse_args()
    only = args.only.lower()

    DATA.mkdir(parents=True, exist_ok=True)

    if only in ("", "tlt", "tlh"):
        print("loading panel ...", flush=True)
        floats = FP.load()
        # Join the float panel ONCE here.  ``prepare_universe`` only runs the as-of join
        # itself when it is handed no panel at all; hand it a bare price panel and the
        # benchmark weights have no ``outstanding_amt`` to weight on.  ``asof_join`` is
        # idempotent, so passing the joined frame down is safe.
        panel = FP.asof_join(BP.load(), floats)

        funds = [("TLT", 31.0), ("TLH", None)]
        if only == "tlt":
            funds = funds[:1]
        elif only == "tlh":
            funds = funds[1:]

        for fund, ttm_max in funds:
            print(f"--- {fund} ---", flush=True)
            uni, funnel = build_universe(fund, ttm_max, panel, floats)
            print(f"  {funnel['rows_final']} rows, {funnel['dates']} dates, "
                  f"{funnel['cusips']} cusips", flush=True)
            cal = calendar_keys(uni["date"])
            cal.to_csv(DATA / f"seas_calendar_{fund}.csv", index=False)

            disp = (uni.groupby("date")["resid_bp"]
                    .agg(disp_bp="std", n="size").reset_index())
            disp.to_csv(DATA / f"seas_dispersion_{fund}.csv", index=False)

            print("  spreads: thesis (with maturity-matched placebo) ...", flush=True)
            sp_th = per_date_spreads(uni, "sig_active_w")
            sp_th.to_parquet(DATA / f"seas_spread_thesis_{fund}.parquet", index=False)
            print("  spreads: richness control ...", flush=True)
            sp_ct = per_date_spreads(uni, "sig_resid", n_perm=0)
            sp_ct.to_parquet(DATA / f"seas_spread_control_{fund}.parquet", index=False)

            nulls = []
            for key in ("bd_me", "dom", "dow", "moy"):
                for h in HORIZONS:
                    t = cell_table(sp_th, cal, key, horizon=h)
                    t.insert(0, "horizon", h)
                    t.insert(0, "fund", fund)
                    t.to_csv(DATA / f"seas_cells_{fund}_{key}_h{h}.csv", index=False)
                c = cell_table(sp_ct, cal, key, horizon=HEADLINE)
                c.insert(0, "fund", fund)
                c.to_csv(DATA / f"seas_cells_control_{fund}_{key}.csv", index=False)
                dd = disp.merge(cal, on="date", how="left")
                g = (dd.groupby(key)["disp_bp"]
                     .agg(["mean", "median", "std", "size"]).reset_index())
                g.to_csv(DATA / f"seas_disp_{fund}_{key}.csv", index=False)
                cells = list(range(-10, 11)) if key == "bd_me" else None
                nl = placebo_null(sp_th, cal, key, horizon=HEADLINE, cells=cells)
                nl.insert(0, "key", key)
                nulls.append(nl)
            pd.concat(nulls, ignore_index=True).to_csv(
                DATA / f"seas_placebo_null_{fund}.csv", index=False)

            for h in HORIZONS:
                mc = me_contrast(sp_th, cal, horizon=h)
                mc.insert(0, "horizon", h)
                mc.to_csv(DATA / f"seas_me_contrast_{fund}_h{h}.csv", index=False)

            # year-by-year stability of the strongest cell, selected on HAC t at the
            # headline horizon only (extending the search across horizons would be a
            # 4x wider trial count for a figure whose whole point is stability).
            best_key, best_val, best_t = None, None, 0.0
            for key in ("bd_me", "dom", "dow", "moy"):
                t = pd.read_csv(DATA / f"seas_cells_{fund}_{key}_h{HEADLINE}.csv")
                if key == "bd_me":
                    t = t[t["bd_me"].between(-10, 10)]
                if t.empty:
                    continue
                i = t["t_hac"].abs().idxmax()
                if abs(t.loc[i, "t_hac"]) > best_t:
                    best_t = abs(t.loc[i, "t_hac"])
                    best_key, best_val = key, t.loc[i, key]
            yb = yearly_cell(sp_th, cal, best_key, best_val, horizon=HEADLINE)
            yb.insert(0, "cell_value", best_val)
            yb.insert(0, "cell_key", best_key)
            yb.insert(0, "cell_t_hac", best_t)
            yb.to_csv(DATA / f"seas_yearly_best_{fund}.csv", index=False)
            print(f"  wrote cells for {fund}; strongest cell "
                  f"{best_key}={best_val} at HAC t {best_t:.2f}", flush=True)

    if only in ("", "flow"):
        print("--- fund trading intensity, all scraped funds ---", flush=True)
        fi = fund_intensity(sorted(REGISTRY))
        fi.to_csv(DATA / "seas_fund_intensity.csv", index=False)
        cal_all = calendar_keys(fi["date"])
        cal_all.to_csv(DATA / "seas_calendar_ALL.csv", index=False)
        print(f"  {len(fi)} fund-days, {fi['ticker'].nunique()} funds", flush=True)

    print("done", flush=True)


if __name__ == "__main__":
    main()
