"""Build the AGGREGATE long-end ladder and measure it, before any P&L is computed.

The order is deliberate. The user's hypothesis is that aggregating across issuers beats
one fund, so the first question is not "what Sharpe does the aggregate print" -- it is
whether the aggregate ladder is a *different signal* from TLT's at all. If the two
ladders correlate at 0.99 then every downstream difference is noise and the grid will
find one anyway, given enough cells.

So this script answers, in order:

1. **Coverage.** Which funds contribute on which dates, how stale each contribution is,
   and what share of the eligible 20y+ board each holds. Computed over days a book
   exists, never over all panel dates -- that is how the parent study's 127-day 2017 hole
   read as "TLT held nothing in 2017" rather than "no file".
2. **The off-slice residual** that construction (b) discards by renormalising.
3. **How many independent views this really is** -- correlation of the bucket measure
   across fund sets, and of the per-fund active weights inside the common slice.
4. **The footprint uplift**, re-measured on the right scope and stated with the
   VGLT whole-fund caveat attached rather than in a footnote.
5. **The IC surface** for every aggregate column against the forward richness residual,
   with the calendar-only and float-twin nulls in the same table.

Everything is written to ``_data/`` as CSV for the notebook to read.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import aggregate as AG  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
os.makedirs(DATA_DIR, exist_ok=True)

FUND_SETS = ("tlt_only", "coupon_long", "coupon_long_govt", "daily_only")
WIDTHS = (0.25, 0.5, 1.0)
COMBINES = ("book", "equal")
HORIZONS = (5, 10, 21, 42, 63)


def banner(s: str) -> None:
    print("\n" + "=" * 100)
    print(s)
    print("=" * 100, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    ap.add_argument("--prefix", default="mi")
    a = ap.parse_args()
    t0 = time.time()

    banner("STEP 0: the 20y+ universe, prepared once")
    panel = FP.asof_join(BP.load(), FP.load())
    cfg = EN.merge_config({"fund": "TLT",
                           "universe": {"start": a.start, "ttm_min": AG.COMMON_BAND[0],
                                        "ttm_max": AG.COMMON_BAND[1]}})
    uni, funnel = EN.prepare_universe(cfg, panel=panel)
    #: prepare_universe's own start filter trims only the BENCHMARK side; the holdings
    #: outer-join drags the fund's full history back in. Filter explicitly or the ladder
    #: silently carries pre-window dates.
    uni = uni[uni["date"] >= pd.Timestamp(a.start)].reset_index(drop=True)
    print(f"universe {len(uni):,} bond-days, {uni['date'].nunique():,} dates, "
          f"{uni['cusip'].nunique()} cusips, "
          f"{uni['date'].min().date()}..{uni['date'].max().date()}  [{time.time()-t0:.0f}s]")
    print("median eligible bonds per date: "
          f"{uni.groupby('date')['cusip'].nunique().median():.0f}")

    banner("STEP 0b: how many bonds does a constant-maturity bucket actually hold?")
    #: The structural fact that decides what "3-month bucket" can even mean here. At the
    #: front end a 3-month bucket holds a dozen bonds and aggregating removes real
    #: substitution noise. At 20y+ the Treasury issues about four bonds a year into a
    #: ten-year window, so a 0.25y bucket holds ONE.
    occ_rows = []
    for w in WIDTHS:
        b = AG.bucket_of(uni["ttm"], band_low=AG.COMMON_BAND[0],
                         band_high=AG.COMMON_BAND[1], width_y=w)
        n = uni.groupby([uni["date"], b])["cusip"].nunique()
        occ_rows.append({"width_y": w, "bonds_per_bucket_med": float(n.median()),
                         "bonds_per_bucket_mean": float(n.mean()),
                         "bonds_per_bucket_p90": float(n.quantile(0.90)),
                         "bonds_per_bucket_max": int(n.max()),
                         "occupied_buckets_med": float(
                             uni.assign(_b=b).groupby("date")["_b"].nunique().median())})
    occ = pd.DataFrame(occ_rows)
    print(occ.to_string(index=False))
    occ.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_bucket_occupancy.csv"), index=False)

    banner("STEP 1: build every ladder (fund set x width x construction)")
    built = AG.build_ladders(uni, fund_sets=FUND_SETS, widths=WIDTHS,
                             combines=COMBINES, verbose=True)
    start = built["ladder_start"]
    print(f"\n{len(built['specs'])} signal columns  [{time.time()-t0:.0f}s]")

    cov = pd.concat([v.assign(fund_set=k) for k, v in built["coverage"].items()],
                    ignore_index=True)
    cov.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_coverage.csv"), index=False)
    banner("STEP 2: coverage, and how stale each fund's contribution is")
    print(cov.to_string(index=False))

    banner("STEP 3: the OFF-SLICE residual construction (b) renormalises away")
    key = AG.column_name("act", "coupon_long_govt", 0.25, "book")
    off = built["offslice"][key]
    off = off[off["date"] >= start]
    off_sum = off.groupby("ticker").agg(
        n_dates=("date", "nunique"),
        inslice_share_par_med=("inslice_share_par", "median"),
        inslice_share_par_min=("inslice_share_par", "min"),
        offslice_share_par_med=("offslice_share_par", "median"),
        inslice_dv01_med=("inslice_amt", "median"),
        n_inslice_med=("n_inslice", "median"),
        stale_days_med=("stale_days", "median"),
        stale_days_max=("stale_days", "max"),
    ).reset_index()
    print(off_sum.to_string(index=False))
    print("\nREAD THIS AS: the share of each fund's book that construction (b) keeps. "
          "\nWhat is dropped is the fund's view on HOW MUCH long end to hold at all, "
          "which\ncannot be measured on a common board because TLT's board has no "
          "10-20y half.")
    off_sum.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_offslice.csv"), index=False)

    banner("STEP 4: how many INDEPENDENT views is the aggregate, really?")
    #: If the aggregate ladder correlates ~1.0 with the TLT-only ladder then every
    #: downstream difference in P&L is noise, and a grid will still find a "winner".
    rows = []
    for cons, col in (("own", "own_z"), ("act", "active_z")):
        for w in WIDTHS:
            sel = {}
            for fs in FUND_SETS:
                k = AG.column_name(cons, fs, w, "book" if cons == "act" else "")
                if k in built["ladders"]:
                    sel[fs] = built["ladders"][k]
            if len(sel) < 2:
                continue
            c = AG.independence(sel, col)
            for i in c.index:
                for j in c.columns:
                    if i < j:
                        rows.append({"construction": cons, "width_y": w,
                                     "a": i, "b": j, "corr": float(c.loc[i, j])})
    indep = pd.DataFrame(rows)
    print(indep.pivot_table(index=["construction", "width_y"], columns=["a", "b"],
                            values="corr").round(3).to_string())
    indep.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_independence.csv"), index=False)

    banner("STEP 4b: the same question on the RAW (un-z'd) measure, and per fund")
    #: The z-score is a monotone-ish transform of a persistent series, so correlating the
    #: z's can flatter or flatten. Correlate the level too.
    raw_rows = []
    for w in WIDTHS:
        sel = {fs: built["ladders"][AG.column_name("own", fs, w)] for fs in FUND_SETS}
        c = AG.independence(sel, "own")
        for i in c.index:
            for j in c.columns:
                if i < j:
                    raw_rows.append({"width_y": w, "a": i, "b": j,
                                     "corr_level": float(c.loc[i, j])})
    raw = pd.DataFrame(raw_rows)
    print(raw.pivot_table(index="width_y", columns=["a", "b"],
                          values="corr_level").round(4).to_string())
    raw.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_independence_level.csv"), index=False)

    banner("STEP 5: the FOOTPRINT -- what the aggregate actually owns")
    foot_rows = []
    for fs in FUND_SETS:
        l = built["ladders"][AG.column_name("own", fs, 0.25)]
        l = l[l["date"] >= start]
        foot_rows.append({
            "fund_set": fs, "funds": ",".join(AG.FUND_SETS[fs].tickers),
            "own_med_pct": float(l["own"].median() * 100),
            "own_p90_pct": float(l["own"].quantile(0.90) * 100),
            "own_max_pct": float(l["own"].max() * 100),
            "par_bn_med": float(l.groupby("date")["agg_par"].sum().median() / 1e9),
        })
    foot = pd.DataFrame(foot_rows)
    base = foot.loc[foot["fund_set"] == "tlt_only", "own_med_pct"].iloc[0]
    foot["uplift_vs_tlt"] = foot["own_med_pct"] / base
    print(foot.round(4).to_string(index=False))
    print("\nSCOPE CAVEAT, stated with the number and not in a footnote: VGLT's N-PORT "
          "book is\nthe WHOLE multi-share-class fund, not the ETF share class -- measured "
          "net assets\n$14.599bn against $10.368bn of ETF AUM, a ratio of 1.408. SPTL's "
          "ratio is 0.965,\ni.e. the ETF. So any ownership number including VGLT measures "
          "INDEX-FUND-FAMILY\nfootprint, ~1.4x the ETF's, not ETF footprint. The demand is "
          "real and lands on the\nsame bonds; the label is what has to be right.")
    foot.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_footprint.csv"), index=False)

    banner("STEP 6: the IC surface -- does ANY of this predict forward richness?")
    u2 = AG.attach_many(uni, built["specs"])
    u2 = u2[u2["date"] >= start].reset_index(drop=True)

    #: The nulls belong in the SAME table as the signal, computed on the same rows with
    #: the same standardisation, or the comparison is between two tables.
    for name, kwargs in (("deletion", {"band_low": AG.COMMON_BAND[0], "horizon_m": 3}),
                         ("cross22", {"boundary": 22.0}),
                         ("cross24", {"boundary": 24.0}),
                         ("cross26", {"boundary": 26.0}),
                         ("cross28", {"boundary": 28.0})):
        fn = SIG.sig_deletion if name == "deletion" else SIG.sig_crossing
        raw_s = fn(u2, **kwargs)
        u2[f"null_{name}"] = SIG.cross_sectional_z(raw_s, u2["date"], robust=True).clip(-5, 5)
    u2["ctrl_resid"] = SIG.cross_sectional_z(u2["resid_bp"], u2["date"],
                                             robust=True).clip(-5, 5)

    sig_cols = sorted(built["specs"]) + [c for c in u2.columns if c.startswith("null_")] \
        + ["ctrl_resid"]
    tab = IC.ic_table(u2, sig_cols, horizons=HORIZONS, exec_lag=a.exec_lag)
    tab.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_ic.csv"), index=False)

    piv = tab.pivot_table(index="signal", columns="horizon", values="ic_mean")
    pt = tab.pivot_table(index="signal", columns="horizon", values="ic_t")
    print("mean cross-sectional Spearman IC (exec_lag=%d):" % a.exec_lag)
    print(piv.round(4).to_string())
    print("\nNewey-West t (lags = horizon - 1) -- the one to read:")
    print(pt.round(2).to_string())

    banner("STEP 7: the same thing in BASIS POINTS, against the cost")
    #: An IC is a rank statistic. The decision is made in bp, so translate: the spread of
    #: the long-short book against the measured round trip.
    ls_rows = []
    for c in sorted(built["specs"]):
        s = IC.long_short_series(u2, c, horizon=21, n_names=3, exec_lag=a.exec_lag)
        if len(s) < 50:
            continue
        ls_rows.append({"signal": c, "n_dates": len(s), "mean_bp": float(s.mean()),
                        "sd_bp": float(s.std(ddof=1)),
                        "t_hac": IC.newey_west_t(s.to_numpy(float), lags=20)})
    ls = pd.DataFrame(ls_rows).sort_values("mean_bp", ascending=False)
    print("21-day long-short (top3 - bottom3), bp of richness residual:")
    print(ls.round(4).to_string(index=False))
    ls.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_longshort.csv"), index=False)

    from RVUtils.ETFRebalance import costs as C
    cm = C.CostModel(basis="measured", multiplier=1.0)
    leg = cm.leg_round_trip_yield_bp(u2)
    print(f"\nmeasured leg round trip, median {leg.median():.4f} yield bp; "
          f"a 3-leg DV01-neutral fly pays ~2x = {2*leg.median():.4f} bp.")
    disp = u2.groupby("date")["resid_bp"].std().median()
    print(f"median cross-sectional richness dispersion {disp:.4f} bp -> the whole "
          f"dispersion is {disp/(2*leg.median()):.2f}x one round trip.")

    print(f"\nwrote {DATA_DIR}\\{a.prefix}_*.csv   [{time.time()-t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
