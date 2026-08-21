"""Bucket ladder, PRIMARY analysis: held-composition forward return + the w_i calendar null.

Why this file exists next to ``_run_ladder.py``
------------------------------------------------
The first pass (``_run_ladder.py``) scores a bucket's forward return as the change in
the MEDIAN residual of whatever bonds occupy that maturity slot at t and at t+h. That is
not a tradeable object at h=63 on a 0.25y-wide bucket: a bond rolls through a 3-month
bucket in about 63 business days, so at the 63d horizon the "return" is close to 100%
composition turnover, not price movement in bonds anyone actually held. A butterfly
holds three fixed CUSIPs; it does not roll its belly to whatever is now in the slot.
Measured consequence: the first pass found partial-IC t-stats up to 30-67 -- an order of
magnitude past anything in the per-CUSIP study -- which is the fingerprint of an
artefact, not a discovery.

The fix: **hold the CUSIP composition fixed at entry.** For every (date, bucket), take
the CUSIPs actually in the bucket at date t and average THEIR OWN per-CUSIP forward
residual return (``IC.forward_residual_return`` on the per-CUSIP universe, unchanged).
This is the apples-to-apples comparison the task asks for against the per-CUSIP result
(partial IC +0.012, t=+3.8 @ 63d): same return definition, only the SIGNAL is now
aggregated to the bucket.

The calendar null for the literal formulation
-----------------------------------------------
``bucket_hist_z`` is a bucket's own weight vs its own history. A tracking fund's weight
follows the index's weight mechanically, so the same statistic built on ``w_i`` (the
bucket's INDEX weight, zero holdings files) is the null: if it earns what the w_f version
earns, the scrape bought nothing. Run alongside, not after.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                       "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
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
from RVUtils.ETFRebalance._run_ladder import (  # noqa: E402
    build_bucket_panel, add_hist_z, cs_z_by_date, orthogonalise,
    ic_across_dates, bivariate, double_sort,
)

pd.set_option("display.width", 240)

HORIZONS = (5, 10, 21, 42, 63)
WIDTHS = (0.25, 0.5, 1.0)
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                        "notebooks", "backtests", "etf_rebalance", "_data")
os.makedirs(OUT_DIR, exist_ok=True)


def attach_held_fwd(g: pd.DataFrame, uni_fwd: pd.DataFrame, sp, width_y: float, horizons) -> pd.DataFrame:
    """Per (date, bucket): mean of the per-CUSIP fwd_h of the bonds IN the bucket at t.

    ``uni_fwd`` already carries ``fwd_5..fwd_63`` computed per CUSIP, shift(-h) along that
    CUSIP's own observation sequence -- unchanged from the per-CUSIP study. Bucketing
    happens after, so a bond's forward return is always its OWN forward return, whatever
    it does next (rolls out of the band, gets deleted, etc.) -- exactly what a fly on
    that belly would realise, complete-case caveats aside.
    """
    d = uni_fwd.copy()
    d["bucket"] = HP.bucket_index(d["ttm"], sp, width_y=width_y).astype(float)
    d = d[d["bucket"].notna()].copy()
    d["bucket"] = d["bucket"].astype(int)
    cols = [f"fwd_{h}" for h in horizons]
    agg = d.groupby(["date", "bucket"], as_index=False)[cols].mean()
    agg = agg.rename(columns={c: f"held_{c}" for c in cols})
    return g.merge(agg, on=["date", "bucket"], how="left")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", default="TLT")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    a = ap.parse_args()

    sp = spec(a.fund)
    print(f"loading panel/floats/holdings for {a.fund} ...", flush=True)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([a.fund], panel=panel)
    cfg = EN.merge_config({"fund": a.fund, "universe": {"start": a.start}})
    uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
    print(f"{a.fund}: {len(uni):,} gated bond-days, {uni['date'].nunique():,} dates, "
          f"{uni['cusip'].nunique():,} cusips\n", flush=True)

    uni_fwd = IC.forward_residual_return(uni, HORIZONS)

    n_configs = 0
    all_ic_rows = []
    all_biv_rows = []
    panels = {}

    for width in WIDTHS:
        g = build_bucket_panel(uni, sp, width)
        g = add_hist_z(g, col="w_f", out_col="raw_bucket_hist_z", lookback=250)
        g = add_hist_z(g, col="w_i", out_col="raw_bucket_hist_z_wi", lookback=250)
        g = attach_held_fwd(g, uni_fwd, sp, width, HORIZONS)

        g["z_bucket_active"] = cs_z_by_date(g["raw_bucket_active"], g["date"])
        g["z_bucket_hist_z"] = cs_z_by_date(g["raw_bucket_hist_z"], g["date"])
        g["z_bucket_hist_z_wi"] = cs_z_by_date(g["raw_bucket_hist_z_wi"], g["date"])
        g["z_resid"] = cs_z_by_date(g["resid_med"], g["date"])

        n_buckets_med = int(g.groupby("date")["bucket"].nunique().median())
        min_names = max(5, n_buckets_med // 3)
        print(f"width={width}y: {len(g):,} bucket-days, median {n_buckets_med} buckets/date, "
              f"min_names={min_names}", flush=True)

        gl = g.sort_values(["bucket", "date"]).copy()
        for c in ("z_bucket_active", "z_bucket_hist_z", "z_bucket_hist_z_wi", "z_resid"):
            gl[f"{c}_lag"] = gl.groupby("bucket")[c].shift(a.exec_lag)

        for sname, scol in (("bucket_active", "z_bucket_active_lag"),
                            ("bucket_hist_z", "z_bucket_hist_z_lag"),
                            ("bucket_hist_z_wi_NULL", "z_bucket_hist_z_wi_lag")):
            pcol = f"p_{sname}"
            gl[pcol] = orthogonalise(gl, scol, "z_resid_lag")
            for h in HORIZONS:
                retcol = f"held_fwd_{h}"
                for kind, use in (("raw", scol), ("partial", pcol)):
                    n_configs += 1
                    r = ic_across_dates(gl, use, retcol, min_names=min_names)
                    if r:
                        all_ic_rows.append({"width": width, "signal": sname,
                                             "horizon": h, "kind": kind,
                                             "return_def": "held", **r})
            # bivariate on the held-composition return specifically
            for h in HORIZONS:
                tmp = gl[["date", scol, "z_resid_lag", f"held_fwd_{h}"]].rename(
                    columns={f"held_fwd_{h}": f"fwd_{h}"})
                bv = bivariate(tmp, scol, "z_resid_lag", h, min_names=min_names)
                if bv:
                    all_biv_rows.append({"width": width, "signal": sname, "horizon": h,
                                         "return_def": "held", **bv})

        panels[width] = gl

    ic_df = pd.DataFrame(all_ic_rows)
    biv_df = pd.DataFrame(all_biv_rows)
    ic_df.to_csv(os.path.join(OUT_DIR, "ladder2_ic.csv"), index=False)
    biv_df.to_csv(os.path.join(OUT_DIR, "ladder2_bivariate.csv"), index=False)

    print("\n" + "=" * 110)
    print(f"1. PRIMARY (held-composition return) IC BY WIDTH x SIGNAL x HORIZON  exec_lag={a.exec_lag}")
    print("=" * 110)
    held = ic_df[ic_df["return_def"] == "held"]
    for kind in ("raw", "partial"):
        print(f"\n--- {kind} IC (held-composition return) ---")
        sub = held[held["kind"] == kind]
        print(sub.pivot_table(index=["width", "signal"], columns="horizon", values="ic").round(4).to_string())
        print("t:")
        print(sub.pivot_table(index=["width", "signal"], columns="horizon", values="t").round(2).to_string())

    print("\n" + "=" * 110)
    print("BIVARIATE, held-composition return (bp forward richening per unit z)")
    print("=" * 110)
    print(biv_df.round(4).to_string(index=False))

    # ------------------------------------------------------- double sort on held return
    print("\n" + "=" * 110)
    print("2. DOUBLE SORT (held-composition return) for cells with |t_partial| > 3")
    print("=" * 110)
    ds_summ = []
    flag = held[(held["kind"] == "partial") & (held["t"].abs() > 3)]
    checked = set()
    for _, row in flag.iterrows():
        key = (row["width"], row["signal"], row["horizon"])
        if key in checked:
            continue
        checked.add(key)
        width, sname, h = row["width"], row["signal"], int(row["horizon"])
        gl = panels[width]
        scol = {"bucket_active": "z_bucket_active_lag", "bucket_hist_z": "z_bucket_hist_z_lag",
                "bucket_hist_z_wi_NULL": "z_bucket_hist_z_wi_lag"}[sname]
        retcol = f"held_fwd_{h}"
        tab, cnt = double_sort(gl.rename(columns={retcol: f"fwd_{h}"}), scol, "z_resid_lag", h)
        if tab.empty:
            continue
        spread = (tab[tab.columns.max()] - tab[tab.columns.min()]) if tab.shape[1] >= 2 else pd.Series(dtype=float)
        print(f"\nwidth={width} signal={sname} h={h}d (held-composition), bp:")
        print(tab.round(4).to_string())
        print(f"n per cell (min {int(np.nanmin(cnt.to_numpy(float))):,}):")
        print(f"high-minus-low signal within each resid quintile: {spread.round(4).to_dict()}")
        signs = np.sign(spread.dropna().to_numpy())
        sign_consistent = bool(len(set(signs.tolist())) <= 1) if len(signs) else False
        ds_summ.append({"width": width, "signal": sname, "horizon": h,
                         "linear_t": row["t"], "linear_ic": row["ic"],
                         "sign_consistent_across_quintiles": sign_consistent,
                         "spread_values": spread.round(4).to_dict()})
    pd.DataFrame(ds_summ).to_csv(os.path.join(OUT_DIR, "ladder2_double_sort_held.csv"), index=False)
    if not ds_summ:
        print("No cell exceeded |t_partial|>3 on the held-composition return.")

    print(f"\nTotal (width x signal x horizon x kind x return_def) configs evaluated in IC pass: {n_configs}")
    print("DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
