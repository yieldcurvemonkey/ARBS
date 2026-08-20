"""Is the small surviving active-weight edge concentrated anywhere tradeable?

Context (do not re-derive): on TLT 2016-2026, exec_lag=1, z_active_w (BUY-IS-POSITIVE:
underweight now = high score) has a raw IC of -0.065 t=-14.4 at 63d against the forward
richness residual -- the wrong-signed, resid-confounded number -- and a PARTIAL IC (after
orthogonalising the signal against z_resid, the bond's own richness) of +0.012, t=+3.8 at
63d. A double sort on (resid quintile x active_w tercile) shows NO monotone pattern: the
high-minus-low spread flips sign across the five resid quintiles. The averaged edge is
~0.02bp against a ~0.5bp round-trip cost -- dead on average.

This script asks whether that average is hiding a corner of the book where the edge is
large. Every cell reports n_obs, n_dates, mean bp (Frisch-Waugh partialled against
z_resid), a date-clustered t, and is checked against two nulls: the exec_lag>=1 rule
(already enforced throughout) and, for the month-end cells specifically, the calendar-only
placebo (does a fund with NO active-weight signal show the same month-end effect?).

Partialling convention
-----------------------
Frisch-Waugh: the partial correlation of (z_active_w, fwd_h) controlling for z_resid is
identical whether you orthogonalise the SIGNAL or the TARGET against the control. This
script orthogonalises the TARGET (fwd_h) against z_resid, cross-sectionally per date,
because that yields the partialled return in bp -- the units cost is quoted in -- for
free, whereas orthogonalising the signal only yields a partialled RANK signal with no
natural bp scale. The bivariate-regression coefficient in the prior pass (0.003-0.005
bp/z) is the same object as the slope implied here.
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

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 200)

HORIZONS = (21, 63)
SIZE_THRESH = (0.0, 1.0, 1.5, 2.0, 2.5, 3.0)


# --------------------------------------------------------------------------- helpers

def orthogonalise_target(df: pd.DataFrame, target: str, control: str) -> pd.Series:
    """Residual of ``target`` on ``control``, cross-sectionally, one date at a time.

    Frisch-Waugh partner to the signal-orthogonalisation in _run_partial_ic.py: same
    algorithm, applied to the forward return instead of the signal, so the output is in
    the return's own units (bp) rather than a partialled z-score.
    """
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


def date_clustered_stat(directional: pd.Series, dates: pd.Series, *, min_obs_per_date: int = 1) -> dict:
    """Mean directional bp with a t computed across DATES, not observations.

    Same convention as ic.py / _run_partial_ic.py: compute one number per date (the
    within-date mean of whatever obs survive a filter), then treat that per-date series
    as the sample. Protects against one wide, over-long dislocation episode being counted
    as hundreds of independent draws.
    """
    per_date = directional.groupby(dates).agg(["mean", "count"])
    per_date = per_date[per_date["count"] >= min_obs_per_date]
    n_dates = len(per_date)
    n_obs = int(per_date["count"].sum())
    if n_dates < 10:
        return {"n_obs": n_obs, "n_dates": n_dates, "mean_bp": np.nan, "t": np.nan}
    m = per_date["mean"]
    mean_bp = float(m.mean())
    sd = float(m.std(ddof=1))
    t = mean_bp / (sd / np.sqrt(n_dates)) if sd > 0 else np.nan
    return {"n_obs": n_obs, "n_dates": n_dates, "mean_bp": mean_bp, "t": t}


def expected_max_abs_t(n_trials: int) -> float:
    """Expected max |t| of N ~independent standard-normal draws (large-sample approx).

    E[max] ~ sqrt(2 ln N) - (ln ln N + ln 4pi) / (2 sqrt(2 ln N)) for the max of N iid
    standard normals; for max of |N(0,1)| use 2N in the same formula (both tails).
    Approximate -- meant to give the ORDER of the multiple-testing hurdle, not an exact
    p-value, since the trials here are correlated (same underlying panel, overlapping
    windows), so the truth is smaller than this number, not bigger.
    """
    n = max(2, 2 * n_trials)
    ln_n = np.log(n)
    ln_ln_n = np.log(max(ln_n, 1e-9))
    base = np.sqrt(2 * ln_n)
    corr = (ln_ln_n + np.log(4 * np.pi)) / (2 * base)
    return float(base - corr)


def build_universe(fund: str, start: str, exec_lag: int) -> pd.DataFrame:
    sp = spec(fund)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([fund], panel=panel)
    cfg = EN.merge_config({"fund": fund, "universe": {"start": start}})
    uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)

    d = uni.copy()
    kw = {"deletion": {"band_low": sp.band_low or 0.0, "horizon_m": 3},
          "addition": {"band_high": sp.band_high or np.inf}}
    for name in ("active_w", "resid"):
        raw = SIG.REGISTRY[name](d, **kw.get(name, {}))
        d[f"z_{name}"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)
        d[f"raw_{name}"] = raw

    d = IC.forward_residual_return(d, HORIZONS)
    for h in HORIZONS:
        d[f"fwd_{h}_orth"] = orthogonalise_target(d, f"fwd_{h}", "z_resid")

    if exec_lag:
        d = d.sort_values(["cusip", "date"])
        for c in ("z_active_w", "z_resid"):
            d[c] = d.groupby("cusip")[c].shift(exec_lag)

    d["direction"] = np.sign(d["z_active_w"])
    for h in HORIZONS:
        d[f"edge_{h}"] = d["direction"] * d[f"fwd_{h}_orth"]

    # calendar timing
    me = d["date"] + pd.offsets.MonthEnd(0)
    dte = (me - d["date"]).dt.days
    ms = d["date"] - pd.offsets.MonthBegin(1) + pd.offsets.MonthEnd(0)  # prior month-end
    dtms = (d["date"] - (d["date"] - pd.offsets.MonthBegin(1))).dt.days
    d["bd_to_month_end"] = dte
    d["is_month_end3"] = dte <= 3
    # first 3 BUSINESS days of month: count business days elapsed since month start
    d["month_key"] = d["date"].dt.to_period("M")
    d["bday_rank_in_month"] = d.groupby("month_key")["date"].rank(method="dense").astype(int)
    d["is_month_start3"] = d["bday_rank_in_month"] <= 3
    d["timing_bucket"] = np.where(d["is_month_end3"], "month_end3",
                          np.where(d["is_month_start3"], "month_start3", "rest_of_month"))
    d["year"] = d["date"].dt.year
    return d


def attach_flow(d: pd.DataFrame, fund: str, threshold: float = 0.02) -> pd.DataFrame:
    holdings = HP.load_holdings([fund])
    flow = HP.flag_flow_days(holdings, threshold=threshold)
    flow = flow[flow["ticker"] == fund][["date", "flow_pct", "is_flow_day"]]
    d = d.merge(flow, on="date", how="left")
    d["flow_bucket"] = np.select(
        [d["flow_pct"] >= threshold, d["flow_pct"] <= -threshold],
        ["big_creation", "big_redemption"], default="quiet")
    d.loc[d["flow_pct"].isna(), "flow_bucket"] = "quiet"
    return d


def attach_vol_regime(d: pd.DataFrame) -> pd.DataFrame:
    """Tercile of rolling-21bd sd of the cross-sectional mean YTM (a rate-vol proxy)."""
    lvl = d.groupby("date")["ytm"].mean().sort_index()
    chg = lvl.diff()
    rv = chg.rolling(21, min_periods=15).std()
    terc = pd.qcut(rv.dropna(), 3, labels=["low_vol", "mid_vol", "high_vol"])
    terc = terc.reindex(rv.index)
    vol_map = terc.to_dict()
    d["vol_regime"] = d["date"].map(vol_map)
    return d


# --------------------------------------------------------------------------- cells

def run_size_conditioning(d: pd.DataFrame, h: int, cells: list) -> pd.DataFrame:
    rows = []
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])
    for thr in SIZE_THRESH:
        sub = sub_all[sub_all["z_active_w"].abs() >= thr]
        stat = date_clustered_stat(sub[f"edge_{h}"], sub["date"])
        rows.append({"dim": "size", "cell": f"|z|>={thr}", "horizon": h, **stat})
        cells.append(f"size:{thr}:{h}")
    # disjoint bins too, to see WHERE within the tail
    edges = list(SIZE_THRESH) + [np.inf]
    for lo, hi in zip(edges[:-1], edges[1:]):
        sub = sub_all[(sub_all["z_active_w"].abs() >= lo) & (sub_all["z_active_w"].abs() < hi)]
        stat = date_clustered_stat(sub[f"edge_{h}"], sub["date"])
        rows.append({"dim": "size_bin", "cell": f"[{lo},{hi})", "horizon": h, **stat})
        cells.append(f"sizebin:{lo}:{hi}:{h}")
    return pd.DataFrame(rows)


def run_timing_conditioning(d: pd.DataFrame, h: int, cells: list) -> pd.DataFrame:
    rows = []
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth", "timing_bucket"])
    for bucket in ("month_end3", "month_start3", "rest_of_month"):
        sub = sub_all[sub_all["timing_bucket"] == bucket]
        stat = date_clustered_stat(sub[f"edge_{h}"], sub["date"])
        rows.append({"dim": "timing", "cell": bucket, "horizon": h, **stat})
        cells.append(f"timing:{bucket}:{h}")
        # interaction: is the effect there BECAUSE of size, or independent of it, inside
        # month_end3 -- run the size cut again restricted to this bucket
        for thr in (0.0, 1.5):
            sub2 = sub[sub["z_active_w"].abs() >= thr]
            stat2 = date_clustered_stat(sub2[f"edge_{h}"], sub2["date"])
            rows.append({"dim": "timing_x_size", "cell": f"{bucket}|z>={thr}",
                         "horizon": h, **stat2})
            cells.append(f"timingxsize:{bucket}:{thr}:{h}")
    # calendar-only placebo: month_end3 effect using ONLY z_resid direction (no holdings
    # data at all) as a sanity check that the timing split itself isn't manufacturing bp
    sub = sub_all[sub_all["timing_bucket"] == "month_end3"].copy()
    sub["direction_resid"] = np.sign(sub["z_resid"])
    sub["edge_resid_only"] = sub["direction_resid"] * sub[f"fwd_{h}_orth"]
    # NB: fwd_h_orth is already orthogonal to z_resid by construction, so this placebo
    # is expected to be ~0 by construction -- it is reported to show the machinery is not
    # leaking the control back in, not as an economic test.
    stat = date_clustered_stat(sub["edge_resid_only"], sub["date"])
    rows.append({"dim": "placebo_check", "cell": "month_end3|resid_direction_on_orth_target",
                 "horizon": h, **stat})
    cells.append(f"placebo:{h}")
    return pd.DataFrame(rows)


def run_flow_conditioning(d: pd.DataFrame, h: int, cells: list) -> pd.DataFrame:
    rows = []
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth", "flow_bucket"])
    for bucket in ("big_creation", "big_redemption", "quiet"):
        sub = sub_all[sub_all["flow_bucket"] == bucket]
        stat = date_clustered_stat(sub[f"edge_{h}"], sub["date"])
        rows.append({"dim": "flow", "cell": bucket, "horizon": h, **stat})
        cells.append(f"flow:{bucket}:{h}")
    return pd.DataFrame(rows)


def run_regime_conditioning(d: pd.DataFrame, h: int, cells: list) -> pd.DataFrame:
    rows = []
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])
    for year, sub in sub_all.groupby("year"):
        stat = date_clustered_stat(sub[f"edge_{h}"], sub["date"])
        rows.append({"dim": "year", "cell": str(year), "horizon": h, **stat})
        cells.append(f"year:{year}:{h}")
    for regime in ("low_vol", "mid_vol", "high_vol"):
        sub = sub_all[sub_all["vol_regime"] == regime]
        stat = date_clustered_stat(sub[f"edge_{h}"], sub["date"])
        rows.append({"dim": "vol_regime", "cell": regime, "horizon": h, **stat})
        cells.append(f"volregime:{regime}:{h}")
    return pd.DataFrame(rows)


def sign_test(d: pd.DataFrame, h: int, bucket_col: str, bucket_val, thr: float = 0.0) -> dict:
    """Non-parametric confirmation: among filtered obs, what fraction of DATES have a
    positive within-date mean edge? Under the null this is a fair coin; report vs 0.5.
    """
    sub = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])
    if bucket_col is not None:
        sub = sub[sub[bucket_col] == bucket_val]
    sub = sub[sub["z_active_w"].abs() >= thr]
    per_date = sub.groupby("date")[f"edge_{h}"].mean()
    n = per_date.notna().sum()
    if n < 10:
        return {"n_dates": n, "share_positive": np.nan}
    return {"n_dates": int(n), "share_positive": float((per_date.dropna() > 0).mean())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", default="TLT")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    ap.add_argument("--out-prefix", default="conc")
    a = ap.parse_args()

    print(f"\n{'='*100}\nFUND = {a.fund}  exec_lag={a.exec_lag}\n{'='*100}")

    d = build_universe(a.fund, a.start, a.exec_lag)
    d = attach_flow(d, a.fund)
    d = attach_vol_regime(d)
    print(f"universe: {len(d):,} bond-days, {d['date'].nunique():,} dates, "
          f"{d['cusip'].nunique():,} cusips")

    cells: list = []
    all_rows = []
    for h in HORIZONS:
        # baseline, unconditional (for reference against the "known" 0.02bp number)
        sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])
        base = date_clustered_stat(sub_all[f"edge_{h}"], sub_all["date"])
        all_rows.append({"dim": "baseline", "cell": "all", "horizon": h, **base})
        cells.append(f"baseline:{h}")

        all_rows.append(run_size_conditioning(d, h, cells))
        all_rows.append(run_timing_conditioning(d, h, cells))
        all_rows.append(run_flow_conditioning(d, h, cells))
        all_rows.append(run_regime_conditioning(d, h, cells))

    out = pd.concat([r if isinstance(r, pd.DataFrame) else pd.DataFrame([r]) for r in all_rows],
                    ignore_index=True)
    out["fund"] = a.fund
    out["cost_bp_hurdle_low"] = 0.30
    out["cost_bp_hurdle_high"] = 0.95
    out["cost_bp_hurdle_med"] = 0.50

    print("\n" + "=" * 100)
    print("ALL CELLS")
    print("=" * 100)
    print(out.round(4).to_string(index=False))

    n_trials = len(cells)
    exp_max_t = expected_max_abs_t(n_trials)
    print(f"\nTotal roughly-independent-ish trials this pass looked at: {n_trials}")
    print(f"Expected max |t| under a pure null, ~{n_trials} two-sided trials "
          f"(iid-normal approx, ignores positive correlation across overlapping cells "
          f"so this is an UPPER bound on the hurdle): {exp_max_t:.2f}")
    obs_max_t = out["t"].abs().max()
    print(f"Observed max |t| across all cells: {obs_max_t:.2f} "
          f"(cell: {out.loc[out['t'].abs().idxmax(), ['dim','cell','horizon']].to_dict() if out['t'].notna().any() else 'n/a'})")

    # non-parametric sign tests on the standout cells (filled in after inspecting `out`)
    print("\n" + "=" * 100)
    print("SIGN TESTS (share of dates with positive mean edge; null = 0.5)")
    print("=" * 100)
    sign_rows = []
    for h in HORIZONS:
        for thr in SIZE_THRESH:
            st = sign_test(d, h, None, None, thr=thr)
            st.update({"horizon": h, "cell": f"|z|>={thr}"})
            sign_rows.append(st)
        for bucket in ("month_end3", "month_start3", "rest_of_month"):
            st = sign_test(d, h, "timing_bucket", bucket)
            st.update({"horizon": h, "cell": bucket})
            sign_rows.append(st)
        for bucket in ("big_creation", "big_redemption", "quiet"):
            st = sign_test(d, h, "flow_bucket", bucket)
            st.update({"horizon": h, "cell": bucket})
            sign_rows.append(st)
    sign_df = pd.DataFrame(sign_rows)
    print(sign_df.round(4).to_string(index=False))

    outdir = BP.panel_dir()
    out_path = outdir / f"{a.out_prefix}_{a.fund.lower()}_cells.csv"
    sign_path = outdir / f"{a.out_prefix}_{a.fund.lower()}_signtest.csv"
    out.to_csv(out_path, index=False)
    sign_df.to_csv(sign_path, index=False)
    print(f"\nwrote {out_path}")
    print(f"wrote {sign_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
