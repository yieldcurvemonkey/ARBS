"""The REALISED trade: what the fund's daily holdings show it actually did.

Every other signal in this study infers a future rebalance from a snapshot of the book
(active weight, ownership). This one observes the change directly: the day-on-day move
in par-per-share, decomposed into the part explained by pure creation/redemption
(pro-rata scaling of yesterday's book by today's share-count change) and the residual
"active" trade the manager actually made.

Definitions used throughout, and the algebra behind them
----------------------------------------------------------
Let ``ppc_t = par_t / shares_t`` (par per ETF share). For a creation/redemption of
``d_shares`` on day t that is a perfect pro-rata slice of yesterday's book, the expected
par change in a CUSIP is ``expected_dpar_t = ppc_{t-1} * d_shares_t`` -- shares grow,
every position grows with them, ppc is unchanged. The realised trade is what is left:

    active_dpar_t = actual_dpar_t - expected_dpar_t
                   = par_t - par_{t-1} - ppc_{t-1} * (shares_t - shares_{t-1})
                   = shares_t * (ppc_t - ppc_{t-1})          <- exact identity, not an
                                                                  approximation

so ``active_dpar_t = shares_t * d(ppc)_t`` -- both "the fund's per-share holding
changed" and "the trade net of a pro-rata allocation of that day's flow", because it IS
the same number derived two ways.

A publication-lag artefact this module measures and corrects for
--------------------------------------------------------------------
Measured directly (``timing_diagnostic``): the fund-level SUM of a day's par change,
``d_par(t)``, correlates at **0.98** with the file's OWN "Shares Outstanding" field
published the NEXT day, ``d_shares(t+1)`` -- and only 0.05-0.12 with same-day or prior-day
shares. The "Shares Outstanding" figure stamped on file t is therefore not contemporaneous
with that file's own par positions; it is confirmed only once file t+1 exists. Using it
as-is manufactures a mechanical one-day round trip in ppc (par moves on t, the stale
denominator hasn't caught up, ppc spikes; the denominator catches up on t+1 and ppc gives
it back) that shows up as strongly NEGATIVE lag-1 autocorrelation and is not a manager
reversing a trade.

Two constructions are carried side by side rather than silently "fixed":

* **unaligned** (``active``/``raw``/``expected``): each file's own self-consistent
  (par, shares) pair, exactly as anyone reading the file in real time would see it. This
  is what a live signal is actually built from, oscillation and all -- it cannot be
  cleaned up in real time because the correction needs tomorrow's file.
* **aligned** (``aligned``): ``shares_true(t) := shares_out(t+1)``, i.e. the "Shares
  Outstanding" value the SAME quantity is confirmed at one file later, used as today's
  denominator. This removes the mechanical oscillation (measured lag-1 autocorr of
  d(ppc): -0.17 unaligned vs -0.004 aligned on TLT) and is the "cleanest available
  measure of manager intent" the task asks for in step 4 -- but it needs file t+1, so it
  is knowable only from t+2, one full day later than the unaligned construction. Every
  test below carries that as an extra day of ``true_lag`` on top of the stated
  ``exec_lag``, and it is used for the *contemporaneous* impact test (step 2, which is
  explicitly non-tradeable and has no lookahead constraint to respect) as the primary
  measure, with the unaligned version reported alongside for comparison.

Two more data-quality fixes worth stating plainly
----------------------------------------------------
**Entries and exits are the biggest realised trades and a holdings-only frame is blind
to them**: a first purchase has no prior row to diff against, and a full liquidation
leaves no row at all. The delta grid is built on the CROSS PRODUCT of every date the
fund's holdings file actually published and every CUSIP ever either held or eligible for
its index band (widened 1y both edges), with un-held cells filled to an explicit zero.

**TLT and TLH have a real hole in the scrape (2017-01 to 2017-06, no file at all -- 188
days between two consecutive rows).** Every delta whose row-to-row date gap exceeds 5
calendar days is set to NaN rather than diffed across, and ``rolling(min_periods=k)``
then correctly refuses to sum across it.

Exec lag
--------
A holdings file stamped "as of T" publishes overnight; the earliest close it could be
traded against is T+1. Every predictive test uses ``exec_lag in (1, 2)`` on top of the
``true_lag`` above, shifting the SIGNAL along that cusip's own row sequence (never the
return, which always starts from the file's own stamped date) -- the same convention
``ic.py``/``holdings_panel.py`` use everywhere else in this study. Lag-0 is never used
for a claim, only printed as a labelled diagnostic.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402
from RVUtils.ETFRebalance._run_partial_ic import orthogonalise  # noqa: E402

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 200)

TICKERS = ["TLT", "TLH", "GOVT", "IEF", "IEI"]
K_LIST = [1, 3, 5, 10]
EXEC_LAGS = [1, 2]
HORIZONS = [5, 10, 21, 42]
COST_BP = 0.5   # median measured DV01-neutral fly round trip, 20-31y (the hurdle)
MAX_GAP_DAYS = 5   # a scrape gap wider than this nulls the delta rather than diff-ing across it
GATE_GAP_DAYS = 4  # for the contemporaneous test: only true adjacent-date pairs count as "same-day"
FAMILIES = ["active", "raw", "expected", "aligned"]

OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "..", "notebooks", "backtests",
                                       "etf_rebalance", "_data"))
os.makedirs(OUT_DIR, exist_ok=True)


def _tprint(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================== vectorised stats
# (per-date Spearman IC and quintile spreads, computed with groupby aggregations rather
# than a Python loop over every date -- a Python-level loop over ~2,500 dates times the
# ~200 (k, family, lag, horizon, kind) cells this script evaluates does not finish in
# reasonable time once GOVT's ~900-cusip cross-section is in play.)


def spearman_ic_by_date(df: pd.DataFrame, xcol: str, ycol: str, min_n: int = 8) -> pd.Series:
    g = df[["date", xcol, ycol]].dropna()
    if g.empty:
        return pd.Series(dtype=float)
    g = g.copy()
    g["rx"] = g.groupby("date")[xcol].rank()
    g["ry"] = g.groupby("date")[ycol].rank()
    cnt = g.groupby("date")["rx"].transform("size")
    g = g[cnt >= min_n]
    if g.empty:
        return pd.Series(dtype=float)
    grp = g.groupby("date")
    n = grp.size().astype(float)
    sx, sy = grp["rx"].sum(), grp["ry"].sum()
    sxy = (g["rx"] * g["ry"]).groupby(g["date"]).sum()
    sxx = (g["rx"] ** 2).groupby(g["date"]).sum()
    syy = (g["ry"] ** 2).groupby(g["date"]).sum()
    num = sxy - sx * sy / n
    denx = (sxx - sx ** 2 / n).clip(lower=0)
    deny = (syy - sy ** 2 / n).clip(lower=0)
    denom = np.sqrt(denx * deny)
    ic = (num / denom.replace(0, np.nan)).dropna()
    return ic


def ic_mean_t(ic: pd.Series, min_dates: int = 20) -> dict:
    v = ic.to_numpy(float)
    v = v[np.isfinite(v)]
    if v.size < min_dates:
        return {"ic_mean": np.nan, "ic_t": np.nan, "ic_n_dates": int(v.size)}
    return {"ic_mean": float(v.mean()),
           "ic_t": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
           "ic_n_dates": int(v.size)}


def quintile_spread(d: pd.DataFrame, sig_col: str, fwd_col: str, n: int = 5) -> dict:
    """Fama-MacBeth: top-minus-bottom quintile mean fwd bp PER DATE, then mean/t across
    dates -- not a single pooled regression, which overstates the SE at long, overlapping
    horizons by counting each overlapping observation as independent.
    """
    dd = d[["date", sig_col, fwd_col]].dropna()
    if dd.empty:
        return {}
    dd = dd.copy()
    cnt = dd.groupby("date")[sig_col].transform("size")
    dd = dd[cnt >= 2 * n]
    if dd.empty:
        return {}
    rnk = dd.groupby("date")[sig_col].rank(method="first")
    grp_n = dd.groupby("date")[sig_col].transform("size")
    bucket = np.floor(n * (rnk - 1) / grp_n).clip(upper=n - 1).astype(int)
    piv = dd.assign(bucket=bucket).groupby(["date", "bucket"])[fwd_col].mean().unstack("bucket")
    if piv.shape[1] < 2:
        return {}
    top_col, bot_col = piv.columns.max(), piv.columns.min()
    spread = (piv[top_col] - piv[bot_col]).dropna()
    if spread.empty:
        return {}
    v = spread.to_numpy(float)
    out = {"q_spread_bp": float(v.mean()), "q_n_dates": int(v.size)}
    out["q_spread_t"] = float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))) if v.size >= 20 else np.nan
    return out


# ============================================================== build the per-fund frame


def build_full_grid(ticker: str, panel: pd.DataFrame, sp) -> pd.DataFrame:
    """Full (obs_date x cusip) grid with explicit zeros, so entries/exits are visible.

    Carries BOTH the unaligned (as-published) and aligned (shares confirmed one file
    later) constructions -- see module docstring.
    """
    h = HP.load_holdings([ticker])
    obs_dates = np.sort(h["date"].unique())

    lo = sp.band_low if sp.band_low is not None else 0.0
    hi = sp.band_high if sp.band_high is not None else np.inf
    lo2 = max(0.0, lo - 1.0)
    hi2 = (hi + 1.0) if np.isfinite(hi) else np.inf

    p = panel[panel["date"].isin(obs_dates)]
    eligible = p.loc[p["ttm"].between(lo2, hi2), "cusip"].unique()
    held = h["cusip"].unique()
    universe_cusips = np.union1d(eligible, held)
    _tprint(f"  {ticker}: grid {len(obs_dates)} dates x {len(universe_cusips)} cusips "
           f"= {len(obs_dates) * len(universe_cusips):,} rows (band [{lo:.0f},{hi if np.isfinite(hi) else 'inf'}) "
           f"widened to [{lo2:.1f},{hi2 if np.isfinite(hi2) else 'inf'}])")

    shares_series = h.groupby("date")["shares_out"].first().sort_index()
    fwd_gap_days = pd.Series(np.append(np.diff(obs_dates).astype("timedelta64[D]").astype(float), np.nan),
                             index=obs_dates)
    shares_true_series = shares_series.shift(-1).where(fwd_gap_days <= MAX_GAP_DAYS)

    idx = pd.MultiIndex.from_product([obs_dates, universe_cusips], names=["date", "cusip"])
    grid = idx.to_frame(index=False)
    grid = grid.merge(h[["date", "cusip", "par"]], on=["date", "cusip"], how="left")
    grid["par"] = grid["par"].fillna(0.0)
    grid["shares_out"] = grid["date"].map(shares_series)
    grid["shares_true"] = grid["date"].map(shares_true_series)
    grid["par_per_share"] = grid["par"] / grid["shares_out"].replace(0, np.nan)
    grid["par_per_share_true"] = grid["par"] / grid["shares_true"].replace(0, np.nan)

    grid = grid.sort_values(["cusip", "date"]).reset_index(drop=True)
    g = grid.groupby("cusip")
    grid["gap_days"] = g["date"].diff().dt.days
    grid["d_par"] = g["par"].diff()
    grid["d_ppc"] = g["par_per_share"].diff()
    grid["d_ppc_true"] = g["par_per_share_true"].diff()
    d_shares_by_date = shares_series.diff()
    grid["d_shares"] = grid["date"].map(d_shares_by_date)

    big_gap = grid["gap_days"] > MAX_GAP_DAYS
    for c in ("d_par", "d_shares", "d_ppc", "d_ppc_true"):
        grid.loc[big_gap, c] = np.nan

    ppc_prev = g["par_per_share"].shift(1)
    grid["expected_dpar"] = ppc_prev * grid["d_shares"]
    grid["active_dpar"] = grid["shares_out"] * grid["d_ppc"]        # exact identity
    grid["active_dpar_true"] = grid["shares_true"] * grid["d_ppc_true"]   # same identity, clean shares
    grid.loc[big_gap, ["expected_dpar", "active_dpar", "active_dpar_true"]] = np.nan

    ff = panel[["date", "cusip", "free_float", "ttm"]].drop_duplicates(["date", "cusip"])
    grid = grid.merge(ff, on=["date", "cusip"], how="left")

    fdenom = grid["free_float"].where(grid["free_float"] > 0)
    grid["active_bp"] = grid["active_dpar"] / fdenom * 1e4
    grid["aligned_bp"] = grid["active_dpar_true"] / fdenom * 1e4
    grid["raw_bp"] = grid["d_par"] / fdenom * 1e4
    grid["expected_bp"] = grid["expected_dpar"] / fdenom * 1e4

    flows = HP.flag_flow_days(h.assign(ticker=ticker), threshold=0.02)
    flow_map = flows.set_index("date")["is_flow_day"]
    grid["is_flow_day"] = grid["date"].map(flow_map).fillna(False)

    grid["par_prev"] = g["par"].shift(1)
    grid["ever_relevant"] = (grid["par"] > 0) | (grid["par_prev"] > 0)

    gg = grid.groupby("cusip")
    for k in K_LIST:
        for fam, col in (("active", "active_bp"), ("raw", "raw_bp"), ("expected", "expected_bp"),
                         ("aligned", "aligned_bp")):
            grid[f"{fam}_bp_{k}"] = gg[col].transform(lambda s, k=k: s.rolling(k, min_periods=k).sum())

    return grid


def build_fund_frame(ticker: str, panel: pd.DataFrame):
    sp = spec(ticker)
    grid = build_full_grid(ticker, panel, sp)

    cfg = EN.merge_config({"fund": ticker})
    act, funnel = EN.prepare_universe(cfg, panel=panel)

    flow_cols = (["date", "cusip", "d_par", "d_shares", "d_ppc", "expected_dpar", "active_dpar",
                  "active_dpar_true", "active_bp", "aligned_bp", "raw_bp", "expected_bp",
                  "is_flow_day", "gap_days"]
                 + [f"{fam}_bp_{k}" for k in K_LIST for fam in FAMILIES])
    act = act.merge(grid[flow_cols], on=["date", "cusip"], how="left")
    act = act.sort_values(["cusip", "date"]).reset_index(drop=True)
    act["resid_gap_days"] = act.groupby("cusip")["date"].diff().dt.days
    act["z_resid"] = SIG.cross_sectional_z(act["resid_bp"], act["date"], robust=True).clip(-5, 5)

    return sp, grid, act, funnel


# ============================================================== 1. basic facts


def basic_facts(ticker: str, grid: pd.DataFrame) -> list[dict]:
    rows = []
    d = grid[grid["ever_relevant"] & grid["d_par"].notna()].copy()
    n = len(d)

    frac_dpar_zero = float((d["d_par"] == 0).mean())
    for thr in (1.0, 5.0, 10.0, 25.0):
        frac_active = float((d["active_bp"].abs() > thr).mean())
        frac_active_nonflow = float((d.loc[~d["is_flow_day"], "active_bp"].abs() > thr).mean())
        rows.append({"ticker": ticker, "metric": "frac_cells_active_gt_bp", "threshold_bp": thr,
                     "all_days": frac_active, "non_flow_days": frac_active_nonflow, "n": n})

    rows.append({"ticker": ticker, "metric": "frac_dpar_exactly_zero", "threshold_bp": np.nan,
                 "all_days": frac_dpar_zero,
                 "non_flow_days": float((d.loc[~d["is_flow_day"], "d_par"] == 0).mean()), "n": n})

    q = d["active_bp"].quantile([.01, .05, .25, .5, .75, .95, .99]).to_dict()
    for p, v in q.items():
        rows.append({"ticker": ticker, "metric": f"active_bp_pctile_{p}", "threshold_bp": np.nan,
                     "all_days": float(v),
                     "non_flow_days": float(d.loc[~d["is_flow_day"], "active_bp"].quantile(p)), "n": n})

    frac_flow_days = float(grid.groupby("date")["is_flow_day"].first().mean())
    rows.append({"ticker": ticker, "metric": "frac_dates_flagged_flow_day", "threshold_bp": np.nan,
                 "all_days": frac_flow_days, "non_flow_days": np.nan, "n": grid["date"].nunique()})

    dd = d.sort_values(["cusip", "date"]).copy()
    for col, label in (("active_bp", "unaligned"), ("aligned_bp", "aligned")):
        dd[f"{col}_dm"] = dd[col] - dd.groupby("cusip")[col].transform("mean")
        for lag in (1, 2, 3, 5):
            lagged = dd.groupby("cusip")[f"{col}_dm"].shift(lag)
            ok = dd[f"{col}_dm"].notna() & lagged.notna()
            corr = float(np.corrcoef(dd.loc[ok, f"{col}_dm"], lagged[ok])[0, 1]) if ok.sum() > 100 else np.nan
            rows.append({"ticker": ticker, "metric": f"pooled_autocorr_lag{lag}_cusip_demeaned_{label}",
                         "threshold_bp": np.nan, "all_days": corr, "non_flow_days": np.nan, "n": int(ok.sum())})

    def _ac1(s):
        s = s.dropna()
        return s.autocorr(1) if len(s) > 250 else np.nan
    per_cusip = d.groupby("cusip")["active_bp"].apply(_ac1).dropna()
    rows.append({"ticker": ticker, "metric": "mean_per_cusip_autocorr_lag1", "threshold_bp": np.nan,
                 "all_days": float(per_cusip.mean()) if len(per_cusip) else np.nan,
                 "non_flow_days": np.nan, "n": int(per_cusip.size)})
    rows.append({"ticker": ticker, "metric": "median_per_cusip_autocorr_lag1", "threshold_bp": np.nan,
                 "all_days": float(per_cusip.median()) if len(per_cusip) else np.nan,
                 "non_flow_days": np.nan, "n": int(per_cusip.size)})

    dd["sign_today"] = np.sign(dd["active_bp"].where(dd["active_bp"].abs() > 1.0))
    dd["sign_tmrw"] = dd.groupby("cusip")["sign_today"].shift(-1)
    both = dd.dropna(subset=["sign_today", "sign_tmrw"])
    p_same = float((both["sign_today"] == both["sign_tmrw"]).mean()) if len(both) else np.nan
    rows.append({"ticker": ticker, "metric": "P(same_sign_trade_next_day | |active_bp|>1bp today, unaligned)",
                 "threshold_bp": np.nan, "all_days": p_same, "non_flow_days": np.nan, "n": len(both)})

    dd["sign_today_al"] = np.sign(dd["aligned_bp"].where(dd["aligned_bp"].abs() > 1.0))
    dd["sign_tmrw_al"] = dd.groupby("cusip")["sign_today_al"].shift(-1)
    both_al = dd.dropna(subset=["sign_today_al", "sign_tmrw_al"])
    p_same_al = float((both_al["sign_today_al"] == both_al["sign_tmrw_al"]).mean()) if len(both_al) else np.nan
    rows.append({"ticker": ticker, "metric": "P(same_sign_trade_next_day | |aligned_bp|>1bp today, aligned)",
                 "threshold_bp": np.nan, "all_days": p_same_al, "non_flow_days": np.nan, "n": len(both_al)})

    return rows


# ============================================================== timing diagnostic


def timing_diagnostic(ticker: str) -> dict:
    """Fund-level: does today's total par change line up with TODAY's, YESTERDAY's, or
    TOMORROW's shares-outstanding change? See module docstring for what this settles.
    """
    h = HP.load_holdings([ticker])
    fund = h.groupby("date", as_index=False).agg(total_par=("par", "sum"), shares_out=("shares_out", "first"))
    fund = fund.sort_values("date")
    fund["d_par"] = fund["total_par"].diff()
    fund["d_shares"] = fund["shares_out"].diff()
    fund["d_shares_fwd1"] = fund["d_shares"].shift(-1)
    fund["d_shares_lag1"] = fund["d_shares"].shift(1)

    def _corr(a, b):
        ok = a.notna() & b.notna()
        return float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 30 else np.nan

    return {
        "ticker": ticker,
        "corr_dpar_t_vs_dshares_t": _corr(fund["d_par"], fund["d_shares"]),
        "corr_dpar_t_vs_dshares_tplus1": _corr(fund["d_par"], fund["d_shares_fwd1"]),
        "corr_dpar_t_vs_dshares_tminus1": _corr(fund["d_par"], fund["d_shares_lag1"]),
        "n_dates": int(fund["d_par"].notna().sum()),
    }


# ============================================================== 2. contemporaneous price impact


def _slope_and_ic(dd: pd.DataFrame, xcol: str, ycol: str) -> dict:
    ic = spearman_ic_by_date(dd, xcol, ycol)
    icr = ic_mean_t(ic)

    g = dd[["date", xcol, ycol]].dropna().copy()
    grp = g.groupby("date")
    n = grp[xcol].transform("size")
    g = g[n >= 8]
    grp = g.groupby("date")
    nn = grp.size().astype(float)
    sx, sy = grp[xcol].sum(), grp[ycol].sum()
    sxy = (g[xcol] * g[ycol]).groupby(g["date"]).sum()
    sxx = (g[xcol] ** 2).groupby(g["date"]).sum()
    xbar, ybar = sx / nn, sy / nn
    num = sxy - nn * xbar * ybar
    den = (sxx - nn * xbar ** 2)
    slope = (num / den.replace(0, np.nan)).dropna()
    v = slope.to_numpy(float)
    v = v[np.isfinite(v)]
    out = {"n_dates": icr["ic_n_dates"], "ic_mean": icr["ic_mean"], "ic_t": icr["ic_t"]}
    out["slope_mean"] = float(v.mean()) if v.size else np.nan
    out["slope_t"] = float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))) if v.size > 5 else np.nan
    return out


def price_impact(ticker: str, act: pd.DataFrame) -> list[dict]:
    d = act.sort_values(["cusip", "date"]).copy()
    d["resid_chg_bp"] = d.groupby("cusip")["resid_bp"].diff()
    # only a TRUE adjacent-date pair is a valid same-day impact observation -- a gap left
    # by a gated-out day would otherwise attenuate the slope toward zero.
    d.loc[d["resid_gap_days"] > GATE_GAP_DAYS, "resid_chg_bp"] = np.nan
    d["richening_bp"] = -d["resid_chg_bp"]
    d["pct_float_aligned"] = d["aligned_bp"] / 100.0     # PRIMARY: clean flow, no lookahead constraint here
    d["pct_float_unaligned"] = d["active_bp"] / 100.0    # secondary, for comparison

    dd = d.dropna(subset=["richening_bp"])
    aligned_all = _slope_and_ic(dd, "pct_float_aligned", "richening_bp")
    aligned_nonflow = _slope_and_ic(dd[~dd["is_flow_day"]], "pct_float_aligned", "richening_bp")
    unaligned_all = _slope_and_ic(dd, "pct_float_unaligned", "richening_bp")

    row = {"ticker": ticker,
          "n_dates": aligned_all["n_dates"],
          "slope_bp_richening_per_pct_float_aligned": aligned_all["slope_mean"],
          "slope_t_aligned": aligned_all["slope_t"],
          "ic_mean_aligned": aligned_all["ic_mean"], "ic_t_aligned": aligned_all["ic_t"],
          "slope_bp_richening_per_pct_float_aligned_nonflow": aligned_nonflow["slope_mean"],
          "slope_t_aligned_nonflow": aligned_nonflow["slope_t"],
          "n_dates_nonflow": aligned_nonflow["n_dates"],
          "slope_bp_richening_per_pct_float_UNALIGNED": unaligned_all["slope_mean"],
          "slope_t_UNALIGNED": unaligned_all["slope_t"]}
    return [row]


# ============================================================== 3/4. reversal / continuation


def reversal_tests(ticker: str, act: pd.DataFrame) -> tuple[list[dict], int]:
    d = IC.forward_residual_return(act, HORIZONS, resid_col="resid_bp")
    d = d.sort_values(["cusip", "date"]).reset_index(drop=True)
    fh_cols = [f"fwd_{h}" for h in HORIZONS]

    rows = []
    n_configs = 0
    for k in K_LIST:
        for fam in FAMILIES:
            raw_col = f"{fam}_bp_{k}"
            zc = f"z_{fam}_{k}"
            d[zc] = SIG.cross_sectional_z(d[raw_col], d["date"], robust=True).clip(-5, 5)

        for lag in EXEC_LAGS:
            for fam in FAMILIES:
                zc = f"z_{fam}_{k}"
                # 'aligned' needs file t+1 to exist -> one extra day of true latency on
                # top of the stated exec_lag (see module docstring). The control
                # (z_resid) MUST be shifted by the SAME true_lag as the signal it is
                # orthogonalised against -- shifting it by the plain `lag` instead would
                # date-mismatch signal and control for every 'aligned' cell.
                true_lag = lag + 1 if fam == "aligned" else lag
                dl = d[["cusip", "date", zc, "z_resid"] + fh_cols].copy()
                dl[zc] = dl.groupby("cusip")[zc].shift(true_lag)
                dl["z_resid"] = dl.groupby("cusip")["z_resid"].shift(true_lag)
                pc = f"p_{fam}_{k}"
                dl[pc] = orthogonalise(dl, zc, "z_resid")

                for h in HORIZONS:
                    n_configs += 1
                    fh = f"fwd_{h}"
                    for kind, col in (("raw", zc), ("partial", pc)):
                        gg = dl.dropna(subset=[col, fh])
                        icr = ic_mean_t(spearman_ic_by_date(gg, col, fh))
                        qs = quintile_spread(gg, col, fh)
                        rows.append({
                            "ticker": ticker, "k_days": k, "family": fam, "exec_lag": lag,
                            "true_lag": true_lag, "horizon": h, "kind": kind,
                            "ic_mean": icr["ic_mean"], "ic_t": icr["ic_t"], "ic_n_dates": icr["ic_n_dates"],
                            "q_spread_bp": qs.get("q_spread_bp", np.nan),
                            "q_spread_t": qs.get("q_spread_t", np.nan),
                            "q_n_dates": qs.get("q_n_dates", np.nan),
                        })
    return rows, n_configs


# ============================================================== 5. lookahead sanity


def lookahead_check(ticker: str, act: pd.DataFrame) -> list[dict]:
    d = IC.forward_residual_return(act, [21], resid_col="resid_bp")
    d = d.sort_values(["cusip", "date"]).reset_index(drop=True)
    d["z_active_5"] = SIG.cross_sectional_z(d["active_bp_5"], d["date"], robust=True).clip(-5, 5)

    rows = []
    for lag in (0, 1, 2):
        dl = d.copy()
        if lag:
            dl["z_active_5"] = dl.groupby("cusip")["z_active_5"].shift(lag)
        gg = dl.dropna(subset=["z_active_5", "fwd_21"])
        icr = ic_mean_t(spearman_ic_by_date(gg, "z_active_5", "fwd_21"))
        qs = quintile_spread(gg, "z_active_5", "fwd_21")
        rows.append({"ticker": ticker, "family": "active_unaligned_k5", "exec_lag": lag, "legal": lag >= 1,
                     "ic_mean": icr["ic_mean"], "ic_t": icr["ic_t"],
                     "q_spread_bp": qs.get("q_spread_bp", np.nan), "n_dates": icr["ic_n_dates"]})
    return rows


# ============================================================== 3b. calendar-only null


def calendar_null(ticker: str, act: pd.DataFrame, sp) -> list[dict]:
    d = IC.forward_residual_return(act, HORIZONS, resid_col="resid_bp")
    d = d.sort_values(["cusip", "date"]).reset_index(drop=True)
    kw = {"deletion": {"band_low": sp.band_low or 0.0, "horizon_m": 3},
          "addition": {"band_high": sp.band_high or np.inf, "horizon_m": 3}}
    rows = []
    for name in ("deletion", "addition"):
        raw = SIG.REGISTRY[name](d, **kw[name])
        d[f"z_{name}"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)
        for lag in EXEC_LAGS:
            dl = d.copy()
            dl[f"z_{name}"] = dl.groupby("cusip")[f"z_{name}"].shift(lag)
            for h in HORIZONS:
                fh = f"fwd_{h}"
                gg = dl.dropna(subset=[f"z_{name}", fh])
                icr = ic_mean_t(spearman_ic_by_date(gg, f"z_{name}", fh))
                qs = quintile_spread(gg, f"z_{name}", fh)
                rows.append({"ticker": ticker, "signal": name, "exec_lag": lag, "horizon": h,
                             "ic_mean": icr["ic_mean"], "ic_t": icr["ic_t"],
                             "q_spread_bp": qs.get("q_spread_bp", np.nan), "n_dates": icr["ic_n_dates"]})
    return rows


# ============================================================== double sort + per-year stability


def double_sort(ticker: str, act: pd.DataFrame, k: int, fam: str, lag: int, h: int) -> pd.DataFrame:
    d = IC.forward_residual_return(act, [h], resid_col="resid_bp")
    d = d.sort_values(["cusip", "date"]).reset_index(drop=True)
    true_lag = lag + 1 if fam == "aligned" else lag
    d["z_sig"] = SIG.cross_sectional_z(d[f"{fam}_bp_{k}"], d["date"], robust=True).clip(-5, 5)
    d["z_sig"] = d.groupby("cusip")["z_sig"].shift(true_lag)
    d["z_resid_l"] = d.groupby("cusip")["z_resid"].shift(true_lag)
    g = d.dropna(subset=["z_sig", "z_resid_l", f"fwd_{h}"]).copy()
    if g.empty:
        return pd.DataFrame()
    g["qr"] = g.groupby("date")["z_resid_l"].transform(
        lambda x: pd.qcut(x.rank(method="first"), 5, labels=False, duplicates="drop"))
    g["qs"] = g.groupby(["date", "qr"])["z_sig"].transform(
        lambda x: pd.qcut(x.rank(method="first"), 3, labels=False, duplicates="drop"))
    tab = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="mean")
    tab.insert(0, "ticker", ticker)
    tab.insert(1, "config", f"{fam}_k{k}_lag{lag}_h{h}")
    return tab.reset_index()


def yearly_stability(ticker: str, act: pd.DataFrame, k: int, fam: str, lag: int, h: int) -> list[dict]:
    d = IC.forward_residual_return(act, [h], resid_col="resid_bp")
    d = d.sort_values(["cusip", "date"]).reset_index(drop=True)
    true_lag = lag + 1 if fam == "aligned" else lag
    d["z_sig"] = SIG.cross_sectional_z(d[f"{fam}_bp_{k}"], d["date"], robust=True).clip(-5, 5)
    d["z_sig"] = d.groupby("cusip")["z_sig"].shift(true_lag)
    d["year"] = d["date"].dt.year
    rows = []
    for yr, gy in d.groupby("year"):
        gg = gy.dropna(subset=["z_sig", f"fwd_{h}"])
        icr = ic_mean_t(spearman_ic_by_date(gg, "z_sig", f"fwd_{h}"), min_dates=5)
        qs = quintile_spread(gg, "z_sig", f"fwd_{h}")
        rows.append({"ticker": ticker, "config": f"{fam}_k{k}_lag{lag}_h{h}", "year": int(yr),
                     "ic_mean": icr["ic_mean"], "n_dates": icr["ic_n_dates"],
                     "q_spread_bp": qs.get("q_spread_bp", np.nan)})
    return rows


def flow_day_robustness(ticker: str, act: pd.DataFrame, k: int, fam: str, lag: int, h: int) -> dict:
    """Re-run the best cell excluding every flow day's row entirely, so a 'signal' that
    only works because a big flow day's basket effect hit an untouched dust bond cannot
    pass as a real prediction."""
    d = IC.forward_residual_return(act, [h], resid_col="resid_bp")
    d = d.sort_values(["cusip", "date"]).reset_index(drop=True)
    true_lag = lag + 1 if fam == "aligned" else lag
    d["z_sig"] = SIG.cross_sectional_z(d[f"{fam}_bp_{k}"], d["date"], robust=True).clip(-5, 5)
    d["z_sig"] = d.groupby("cusip")["z_sig"].shift(true_lag)
    d = d[~d["is_flow_day"].fillna(False)]
    gg = d.dropna(subset=["z_sig", f"fwd_{h}"])
    icr = ic_mean_t(spearman_ic_by_date(gg, "z_sig", f"fwd_{h}"))
    qs = quintile_spread(gg, "z_sig", f"fwd_{h}")
    return {"ticker": ticker, "config": f"{fam}_k{k}_lag{lag}_h{h}", "excl_flow_days": True,
           "ic_mean": icr["ic_mean"], "n_dates": icr["ic_n_dates"],
           "q_spread_bp": qs.get("q_spread_bp", np.nan)}


# ============================================================== main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=TICKERS)
    ap.add_argument("--out-suffix", default="")
    a = ap.parse_args()

    def outpath(name: str) -> str:
        suf = f"_{a.out_suffix}" if a.out_suffix else ""
        return os.path.join(OUT_DIR, f"realized{suf}_{name}.csv")

    panel = FP.asof_join(BP.load(), FP.load())
    _tprint(f"panel: {len(panel):,} rows, {panel['date'].nunique():,} dates, "
           f"{panel['cusip'].nunique():,} cusips")

    (all_basic, all_impact, all_ic, all_lookahead, all_null, all_ds,
     all_yearly, all_robust, all_curve_qc, all_timing) = ([], [], [], [], [], [], [], [], [], [])
    n_configs_total = 0
    funnels = []

    for t in a.tickers:
        print("=" * 100)
        _tprint(t)
        print("=" * 100)
        t0 = time.time()
        sp, grid, act, funnel = build_fund_frame(t, panel)
        funnel["ticker"] = t
        funnels.append(funnel)
        _tprint(f"  full grid rows: {len(grid):,}  dates: {grid['date'].nunique():,}  cusips: {grid['cusip'].nunique():,}")
        _tprint(f"  gated/curve-fit universe rows: {len(act):,}  dates: {act['date'].nunique():,}  "
               f"[{time.time()-t0:.1f}s]")

        rq = CV.residual_quality(act)
        curve_row = {"ticker": t, "median_sd_bp": float(rq["sd_bp"].median()),
                    "median_autocorr_1": float(rq["autocorr_1"].median()),
                    "median_fit_rmse_bp": float(act.groupby("date")["fit_rmse_bp"].first().median()),
                    "n_cusips_in_fit": int(rq.shape[0]),
                    "note": ("whole-curve fit (band ~unbounded)"
                            if (sp.band_high is None or not np.isfinite(sp.band_high or np.inf))
                            and (sp.band_low or 0) <= 1.0 else "")}
        all_curve_qc.append(curve_row)
        _tprint(f"  curve QC: median resid sd={curve_row['median_sd_bp']:.3f}bp, "
               f"median autocorr1={curve_row['median_autocorr_1']:.3f}, "
               f"median fit rmse={curve_row['median_fit_rmse_bp']:.3f}bp"
               f"{('  ** ' + curve_row['note'] + ' **') if curve_row['note'] else ''}")

        tdiag = timing_diagnostic(t)
        all_timing.append(tdiag)
        _tprint(f"  [timing] corr(d_par(t),d_shares(t))={tdiag['corr_dpar_t_vs_dshares_t']:.3f}  "
               f"vs d_shares(t+1)={tdiag['corr_dpar_t_vs_dshares_tplus1']:.3f}  "
               f"vs d_shares(t-1)={tdiag['corr_dpar_t_vs_dshares_tminus1']:.3f}")

        rows = basic_facts(t, grid)
        all_basic += rows
        for r in rows:
            if r["metric"].startswith(("frac_cells_active_gt_bp", "frac_dates_flagged_flow_day",
                                       "mean_per_cusip_autocorr_lag1", "pooled_autocorr_lag1_cusip_demeaned",
                                       "P(same_sign_trade_next_day")):
                extra = f"  nonflow={r['non_flow_days']:.4f}" if r["non_flow_days"] == r["non_flow_days"] else ""
                _tprint(f"  [1] {r['metric']} thr={r.get('threshold_bp')}: all={r['all_days']:.4f}{extra}")

        imp_rows = price_impact(t, act)
        all_impact += imp_rows
        ir = imp_rows[0]
        _tprint(f"  [2] impact (ALIGNED/clean): {ir['slope_bp_richening_per_pct_float_aligned']:.4f} bp "
               f"richening/1%float (t={ir['slope_t_aligned']:.2f}, n={ir['n_dates']}); "
               f"non-flow: {ir['slope_bp_richening_per_pct_float_aligned_nonflow']:.4f}bp "
               f"(t={ir['slope_t_aligned_nonflow']:.2f}); UNALIGNED: "
               f"{ir['slope_bp_richening_per_pct_float_UNALIGNED']:.4f}bp (t={ir['slope_t_UNALIGNED']:.2f})")

        t1 = time.time()
        ic_rows, n_cfg = reversal_tests(t, act)
        all_ic += ic_rows
        n_configs_total += n_cfg
        _tprint(f"  [3/4] reversal tests done in {time.time()-t1:.1f}s, {len(ic_rows)} rows")
        icdf = pd.DataFrame(ic_rows)
        icdf_valid = icdf.dropna(subset=["q_spread_bp"])
        # 'raw'/'expected' are NULLS (a pure creation/redemption pro-rata placebo and a
        # non-normalised control) -- they must never win the "best cell" slot, or the
        # confirmation battery (double sort / yearly / flow-day robustness) below runs
        # on a placebo instead of on the actual thesis. Track the best THESIS cell for
        # each of the two competing constructions separately -- that comparison (does the
        # active/manager-intent component predict better than the raw/mechanical one) is
        # exactly what step 4 asks for.
        thesis = icdf_valid[icdf_valid["family"].isin(["active", "aligned"])]
        bests = {}
        for fam_name, sub in thesis.groupby("family"):
            if sub.empty:
                continue
            bests[fam_name] = sub.loc[sub["q_spread_bp"].abs().idxmax()]
            b = bests[fam_name]
            _tprint(f"  [3/4] best |quintile spread| ({fam_name}): k={b['k_days']} "
                   f"lag={b['exec_lag']} true_lag={b['true_lag']} h={b['horizon']} kind={b['kind']} "
                   f"q_spread={b['q_spread_bp']:.4f}bp (t={b['q_spread_t']:.2f}, n_dates={b['q_n_dates']}) "
                   f"vs cost {COST_BP}bp")
        null_best = (icdf_valid[icdf_valid["family"].isin(["raw", "expected"])]
                    .pipe(lambda x: x.loc[x["q_spread_bp"].abs().idxmax()] if not x.empty else None))
        if null_best is not None:
            _tprint(f"  [3/4] (null, for reference) best |quintile spread| among raw/expected: "
                   f"family={null_best['family']} q_spread={null_best['q_spread_bp']:.4f}bp "
                   f"(t={null_best['q_spread_t']:.2f})")

        la_rows = lookahead_check(t, act)
        all_lookahead += la_rows
        for r in la_rows:
            _tprint(f"  [5] lag={r['exec_lag']} legal={r['legal']}: ic={r['ic_mean']}, q_spread={r['q_spread_bp']}")

        null_rows = calendar_null(t, act, sp)
        all_null += null_rows

        for fam_name, b in bests.items():
            k_b, lag_b, h_b = int(b["k_days"]), int(b["exec_lag"]), int(b["horizon"])
            ds = double_sort(t, act, k_b, fam_name, lag_b, h_b)
            all_ds.append(ds)
            all_yearly += yearly_stability(t, act, k_b, fam_name, lag_b, h_b)
            robust_row = flow_day_robustness(t, act, k_b, fam_name, lag_b, h_b)
            all_robust.append(robust_row)
            _tprint(f"  [robust] best-{fam_name} cell excl. flow days: ic={robust_row['ic_mean']}, "
                   f"q_spread={robust_row['q_spread_bp']}, n={robust_row['n_dates']}")
        _tprint(f"  {t} total: {time.time()-t0:.1f}s")

    basic_df = pd.DataFrame(all_basic)
    impact_df = pd.DataFrame(all_impact)
    ic_df = pd.DataFrame(all_ic)
    lookahead_df = pd.DataFrame(all_lookahead)
    null_df = pd.DataFrame(all_null)
    ds_df = pd.concat(all_ds, ignore_index=True) if all_ds else pd.DataFrame()
    yearly_df = pd.DataFrame(all_yearly)
    robust_df = pd.DataFrame(all_robust)
    curve_qc_df = pd.DataFrame(all_curve_qc)
    timing_df = pd.DataFrame(all_timing)
    funnel_df = pd.DataFrame(funnels)

    basic_df.to_csv(outpath("basic_facts"), index=False)
    impact_df.to_csv(outpath("price_impact"), index=False)
    ic_df.to_csv(outpath("ic_table"), index=False)
    lookahead_df.to_csv(outpath("lookahead_check"), index=False)
    null_df.to_csv(outpath("calendar_null"), index=False)
    ds_df.to_csv(outpath("double_sort"), index=False)
    yearly_df.to_csv(outpath("yearly_stability"), index=False)
    robust_df.to_csv(outpath("flow_day_robustness"), index=False)
    curve_qc_df.to_csv(outpath("curve_qc"), index=False)
    timing_df.to_csv(outpath("timing_diagnostic"), index=False)
    funnel_df.to_csv(outpath("funnel"), index=False)

    with open(outpath("config_count").replace(".csv", ".txt"), "w") as f:
        f.write(f"reversal/continuation IC cells evaluated (ticker x k x family x lag x horizon): "
               f"{n_configs_total}\n")
        f.write(f"  = {len(a.tickers)} tickers x {len(K_LIST)} k x {len(FAMILIES)} families x "
               f"{len(EXEC_LAGS)} lags x {len(HORIZONS)} horizons\n")
        f.write(f"each cell reported both raw and partial (orthogonalised vs z_resid) -> "
               f"{len(ic_df)} total rows in ic_table.csv\n")
        f.write(f"plus {len(null_df)} calendar-null rows, {len(lookahead_df)} lookahead-diagnostic rows, "
               f"{len(impact_df)} price-impact rows, {len(yearly_df)} yearly-stability rows.\n")

    print("\n" + "=" * 100)
    _tprint("SAVED:")
    for name in ("basic_facts", "price_impact", "ic_table", "lookahead_check", "calendar_null",
                "double_sort", "yearly_stability", "flow_day_robustness", "curve_qc",
                "timing_diagnostic", "funnel"):
        print(f"  {outpath(name)}")
    print(f"  {outpath('config_count').replace('.csv', '.txt')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
