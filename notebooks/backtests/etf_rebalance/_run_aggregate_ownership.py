"""Aggregate ETF ownership (the scarcity channel) vs the CTRL richness residual and SOMA.

Task: sum par held across every scraped fund (TLT, TLH, IEF, IEI, SHY, GOVT) per
(date, cusip) -- GOVT overlaps every band, the maturity-specific funds are mutually
exclusive by construction (SHY[1,3) IEI[3,7) IEF[7,10) TLH[10,20) TLT[20,inf) are a
contiguous, non-overlapping partition of 1-30y) -- divide by free float to get total
passive ownership share, and test level + change against forward richness, controlling
for float size / age / rank / OTR status, benchmarked against SOMA (Fed) ownership.

GOVZ is excluded from the aggregation: it holds principal STRIPS, whose CUSIPs never
enter the FedInvest coupon-bond panel this study prices off, so its par cannot be joined
to a bond-day.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

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
pd.set_option("display.max_columns", 30)

OUT_DIR = BP.panel_dir()
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
os.makedirs(DATA_DIR, exist_ok=True)

HORIZONS = (5, 10, 21, 42, 63)
#: The five iShares maturity-band funds partition 1-30y with no gaps and no overlap.
#: GOVT is the sixth ownership contributor but is NOT used to build the universe/curve
#: (its own band is [1, inf) -- it would just duplicate the other five).
BAND_FUNDS = ["SHY", "IEI", "IEF", "TLH", "TLT"]
#: Every scraped fund with coupon-bond (FedInvest-joinable) holdings, for the ownership
#: aggregation itself. GOVZ (STRIPS) and the target-maturity iBonds funds are excluded --
#: GOVZ's CUSIPs are STRIPS and never join the panel; the iBonds funds are unscraped here.
OWNERSHIP_FUNDS = ["TLT", "TLH", "IEF", "IEI", "SHY", "GOVT"]


def t_stat(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if x.size < 2:
        return np.nan
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(x.size)))


def fm_regress(df: pd.DataFrame, y_col: str, x_cols: list[str], *, min_n: int = 15) -> pd.DataFrame:
    """Fama-MacBeth: one cross-sectional OLS per date, mean/t of each coefficient."""
    rows = []
    for dt, g in df.groupby("date", sort=False):
        cols = [y_col] + x_cols
        gg = g[cols].replace([np.inf, -np.inf], np.nan).dropna()
        if len(gg) < min_n:
            continue
        y = gg[y_col].to_numpy(float)
        X = np.column_stack([np.ones(len(gg))] + [gg[c].to_numpy(float) for c in x_cols])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        rows.append({"date": dt, "n": len(gg), **{f"b_{c}": beta[i + 1] for i, c in enumerate(x_cols)},
                     "b_const": beta[0]})
    coefs = pd.DataFrame(rows)
    if coefs.empty:
        return pd.DataFrame()
    out = []
    for c in x_cols:
        v = coefs[f"b_{c}"].to_numpy(float)
        out.append({"x": c, "n_dates": len(coefs), "mean_beta": float(np.nanmean(v)),
                     "t_stat": t_stat(v)})
    return pd.DataFrame(out), coefs


def build_full_curve_universe(start: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Concatenate the 5 band-fund runs of ``engine.prepare_universe`` -> one 1-30y panel.

    Each band gets its OWN local cubic-in-ttm (+coupon) fit, exactly as the existing
    20-31y study does, rather than one whole-curve spline dominated by shape it cannot
    bend to. Bands are mutually exclusive by ttm so there is no double counting.
    """
    panel = FP.asof_join(BP.load(), FP.load())
    frames, funnels = [], []
    for f in BAND_FUNDS:
        sp = spec(f)
        cfg = EN.merge_config({"fund": f, "universe": {"start": start}})
        uni, funnel = EN.prepare_universe(cfg, panel=panel)
        uni = uni.copy()
        uni["band_fund"] = f
        uni["band_lo"], uni["band_hi"] = sp.band_low, sp.band_high
        frames.append(uni)
        funnel["fund"] = f
        funnels.append(funnel)
    full = pd.concat(frames, ignore_index=True)
    # prepare_universe's own "start" filter only trims the BENCHMARK side (the
    # ttm/price panel) before joining -- HP.build/with_active_weight join the fund's
    # FULL holdings history (via an outer join) back onto it regardless, so TLT/TLH rows
    # from 2016-17 (before IEF/IEI/SHY/GOVT were scraped) leak back in. Filter explicitly
    # here or the aggregate-ownership panel silently understates ownership pre-2018 for
    # every long bond that GOVT also holds but whose GOVT holding is missing that early.
    before = len(full)
    full = full[full["date"] >= pd.Timestamp(start)]
    print(f"explicit start-date filter: dropped {before - len(full):,} rows before {start} "
          f"that leaked through prepare_universe's join (kept {len(full):,})")
    # sanity: bands must not overlap on ttm
    dup = full.duplicated(subset=["date", "cusip"]).sum()
    print(f"band overlap check: {dup} duplicate (date,cusip) rows across the 5 bands "
          f"(should be 0)")
    return full.sort_values(["cusip", "date"]).reset_index(drop=True), pd.DataFrame(funnels)


def build_aggregate_ownership(start: str) -> pd.DataFrame:
    """Per (date, cusip): summed par across every coupon-holding fund, and fund count."""
    h = HP.load_holdings(OWNERSHIP_FUNDS, start=start)
    agg = h.groupby(["date", "cusip"], as_index=False).agg(
        agg_par=("par", "sum"), agg_mv=("mv", "sum"), n_funds=("ticker", "nunique"))
    per_fund = h.pivot_table(index=["date", "cusip"], columns="ticker", values="par",
                             aggfunc="sum", fill_value=0.0)
    per_fund.columns = [f"par_{c}" for c in per_fund.columns]
    agg = agg.merge(per_fund.reset_index(), on=["date", "cusip"], how="left")
    return agg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    ap.add_argument("--prefix", default="aggown")
    a = ap.parse_args()
    t0 = time.time()

    print("=" * 100)
    print("STEP 1: build the full 1-30y curve universe (5 mutually-exclusive band fits)")
    print("=" * 100)
    full, funnels = build_full_curve_universe(a.start)
    print(funnels[["fund", "rows_all", "rows_after_gates", "rows_final", "dates", "cusips"]]
          .to_string(index=False))
    print(f"\nfull universe: {len(full):,} bond-days, {full['date'].nunique():,} dates, "
          f"{full['cusip'].nunique():,} cusips, {time.time()-t0:.0f}s")

    print("\n" + "=" * 100)
    print("STEP 2: aggregate ETF ownership across every coupon-holding fund")
    print("=" * 100)
    agg = build_aggregate_ownership(a.start)
    print(f"aggregate holdings: {len(agg):,} (date,cusip) rows, "
          f"{agg['date'].nunique():,} dates, {agg['cusip'].nunique():,} cusips, "
          f"funds={OWNERSHIP_FUNDS}")
    print(agg[[c for c in agg.columns if c.startswith('par_')]].gt(0).sum()
          .rename('n_bond_days_held').to_string())

    d = full.merge(agg[["date", "cusip", "agg_par", "agg_mv", "n_funds"]
                       + [c for c in agg.columns if c.startswith("par_")]],
                   on=["date", "cusip"], how="left")
    for c in ["agg_par", "agg_mv", "n_funds"] + [c for c in d.columns if c.startswith("par_")]:
        d[c] = d[c].fillna(0.0)
    d["ownership_agg"] = (d["agg_par"] / d["free_float"].replace(0.0, np.nan)).clip(lower=0.0)
    d["soma_share"] = (d["soma_holdings"].fillna(0.0) / d["outstanding_amt"].replace(0.0, np.nan)).clip(lower=0.0)
    d["log_float"] = np.log(d["free_float"].clip(lower=1e6))
    d["otr"] = (d["rank"] == 0).astype(float)

    print(f"\nownership_agg coverage: {d['ownership_agg'].notna().mean()*100:.1f}% of bond-days")
    print("ownership_agg distribution (%):")
    print((d["ownership_agg"] * 100).describe(percentiles=[.05, .1, .25, .5, .75, .9, .95, .99]).round(3).to_string())
    print("\nsoma_share distribution (%):")
    print((d["soma_share"] * 100).describe(percentiles=[.05, .1, .25, .5, .75, .9, .95, .99]).round(3).to_string())

    print("\nownership_agg by band_fund (mean %, median %):")
    print(d.groupby("band_fund")["ownership_agg"].agg(["mean", "median", "std", "count"]).mul(
        [100, 100, 100, 1]).round(3).to_string())

    d.sort_values(["cusip", "date"], inplace=True)
    d["ownership_agg_chg_21"] = d.groupby("cusip")["ownership_agg"].diff(21)
    d["ownership_agg_chg_63"] = d.groupby("cusip")["ownership_agg"].diff(63)
    d["soma_share_chg_21"] = d.groupby("cusip")["soma_share"].diff(21)

    dist_path = os.path.join(DATA_DIR, f"{a.prefix}_ownership_distribution.csv")
    d[["ownership_agg", "soma_share"]].describe(
        percentiles=[.01, .05, .1, .25, .5, .75, .9, .95, .99]).to_csv(dist_path)
    print(f"\nwrote {dist_path}")

    d.to_parquet(os.path.join(DATA_DIR, f"{a.prefix}_full_panel.parquet"), index=False)
    print(f"wrote {a.prefix}_full_panel.parquet  ({len(d):,} rows), t={time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
