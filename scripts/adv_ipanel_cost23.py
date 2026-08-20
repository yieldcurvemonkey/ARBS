r"""ADVERSARIAL CHECK 6+7: the 2023 anomaly, the cost anchor, and one hand-checked trade.

2023: my 15-min strike grid returns RMSE(citi-fed) ~7.1 bp at EVERY candidate time in
2023, against 0.2-0.4 bp in every other year, and flat. Flat means the disagreement is
not a timing disagreement. Something in 2023 is broken and the report never split by
year, so its pooled RMSE contest (0.2023 vs 0.2066, a 2% margin) is dominated by it.

COST: the headline 0.99 bp fly round trip is 2 x the median FedInvest full spread of
7.55 price bp. Check it is not manufactured by costs.py's MIN_SPREAD_PRICE_BP floor or
its sector-median fallback, and that it is measured on the bonds/dates actually studied.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")


def main() -> int:
    pd.set_option("display.width", 260)
    p = pd.read_parquet(DATA / "ipanel_mi01.parquet")
    p["date"] = pd.to_datetime(p["date"])

    # ------------------------------------------------------------------ THE 2023 HOLE
    q = p[p["mark_time"].eq("11:00") & p["ytm"].notna() & p["ytm_fedinvest"].notna()
          & p["stale_min_ytm"].le(30)].copy()
    q["diff_bp"] = (q["ytm"] - q["ytm_fedinvest"]) * 100.0
    q["year"] = q["date"].dt.year
    print("=== |citi 11:00 - fedinvest| BY YEAR")
    y = q.groupby("year")["diff_bp"].agg(
        n="size", mean="mean", sd="std",
        p50=lambda x: float(x.abs().median()), p99=lambda x: float(x.abs().quantile(.99)),
        mx=lambda x: float(x.abs().max()))
    print(y.round(3).to_string())

    bad = q[q["diff_bp"].abs() > 5]
    print(f"\nbond-days disagreeing by >5 bp: {len(bad):,} of {len(q):,} "
          f"({len(bad)/len(q)*100:.2f}%)")
    bd = bad.groupby(bad["date"].dt.date).size().sort_values(ascending=False)
    print(f"concentrated on {len(bd)} dates; worst 12:")
    print(bd.head(12).to_string())
    print(f"\nfraction of ALL >5bp rows falling on the worst 10 dates: "
          f"{bd.head(10).sum()/len(bad)*100:.1f}%")
    bcu = bad.groupby("cusip").size().sort_values(ascending=False)
    print(f"\nconcentrated on {len(bcu)} cusips; worst 8:\n{bcu.head(8).to_string()}")
    bad.groupby([bad["date"].dt.date, "cusip"]).size().rename("n").reset_index().to_csv(
        DATA / "adv_citi_fed_disagreements.csv", index=False)

    # which side is wrong? compare each to its own neighbours via the fitted curve
    print("\n=== ON THE WORST DATE, WHICH SOURCE IS THE OUTLIER?")
    if len(bd):
        wd = pd.Timestamp(bd.index[0])
        z = q[q["date"].eq(wd)].copy()
        print(f"{wd.date()}: n={len(z)}  mean diff {z['diff_bp'].mean():.2f} bp  "
              f"sd {z['diff_bp'].std():.2f}  -> "
              f"{'WHOLE-CURVE level shift (a timing/settle difference)' if abs(z['diff_bp'].mean()) > 2*z['diff_bp'].std() else 'idiosyncratic per bond'}")

    # -------------------------------------------------------------------- THE COST
    print("\n=== COST ANCHOR: FedInvest published full bid-offer, on the studied set")
    c = p[p["mark_time"].eq("15:00") & p["spread_price_bp"].notna()
          & p["mod_dur"].notna()].copy()
    c["yield_bp"] = c["spread_price_bp"] / c["mod_dur"]
    print(f"bond-days with a published spread: {len(c):,}")
    print(f"  spread == 0 exactly            : {int(c['spread_price_bp'].eq(0).sum()):,}")
    print(f"  spread < 0.5 (the floor)       : {int(c['spread_price_bp'].lt(0.5).sum()):,}")
    print(f"  median full spread, PRICE bp   : {c['spread_price_bp'].median():.4f}")
    print(f"  median mod_dur                 : {c['mod_dur'].median():.4f}")
    print(f"  median full spread, YIELD bp   : {c['yield_bp'].median():.4f}")
    print(f"  => fly round trip (2x)         : {2*c['yield_bp'].median():.4f} bp")
    print(f"  mean   full spread, YIELD bp   : {c['yield_bp'].mean():.4f} "
          f"=> fly {2*c['yield_bp'].mean():.4f}")
    # restricted to TLT's own band, which is where the ceiling was measured
    t = c[c["ttm"].ge(19)]
    print(f"\n  ttm>=19y only: n={len(t):,}  median price bp {t['spread_price_bp'].median():.4f}"
          f"  yield bp {t['yield_bp'].median():.4f}  => fly {2*t['yield_bp'].median():.4f} bp")
    held = c[c["held_by_tlt"].fillna(False) & c["ttm"].ge(19)]
    print(f"  ttm>=19y AND held by TLT: n={len(held):,}  "
          f"=> fly {2*held['yield_bp'].median():.4f} bp")
    rows = []
    for lab, g in (("all", c), ("ttm>=19y", t), ("ttm>=19y & held", held)):
        rows.append({"set": lab, "n": len(g),
                     "price_bp_med": float(g["spread_price_bp"].median()),
                     "yield_bp_med": float(g["yield_bp"].median()),
                     "yield_bp_p25": float(g["yield_bp"].quantile(.25)),
                     "yield_bp_p75": float(g["yield_bp"].quantile(.75)),
                     "fly_rt_bp": 2 * float(g["yield_bp"].median())})
    ct = pd.DataFrame(rows)
    print("\n" + ct.round(4).to_string(index=False))
    ct.to_csv(DATA / "adv_cost_anchor.csv", index=False)

    # ---------------------------------------------------- HAND CHECK: one seam trade
    print("\n=== HAND CHECK: one 15:00->16:00 butterfly, end to end")
    w = p[p["mark_time"].isin(("15:00", "16:00")) & p["resid_bp_tlt19"].notna()
          & p["stale_min_ytm"].le(5)]
    piv = w.pivot_table(index=["date", "cusip"], columns="mark_time",
                        values="resid_bp_tlt19").dropna()
    ttm = w.groupby(["date", "cusip"])["ttm"].first()
    dd = (piv["16:00"] - piv["15:00"]).rename("d").to_frame().join(ttm)
    date = dd.index.get_level_values(0)[len(dd) // 2]
    g = dd.loc[date].sort_values("ttm")
    i = len(g) // 2
    trio = g.iloc[i - 1:i + 2]
    print(f"date {pd.Timestamp(date).date()}, three maturity-adjacent bonds:")
    raw = p[p["date"].eq(date) & p["cusip"].isin(trio.index)
            & p["mark_time"].isin(("15:00", "16:00"))]
    print(raw[["cusip", "mark_time", "ttm", "ytm", "ts_ytm", "stale_min_ytm",
               "resid_bp_tlt19"]].sort_values(["cusip", "mark_time"]).round(5).to_string(index=False))
    v = trio["d"].to_numpy()
    print(f"\n  d(resid) per bond, bp: {np.round(v, 5)}")
    print(f"  fly = 2*belly - wings = 2*{v[1]:.5f} - {v[0]:.5f} - {v[2]:.5f} = "
          f"{2*v[1]-v[0]-v[2]:.5f} bp")
    print(f"  cost of that fly (FedInvest, measured)                 = 0.9915 bp")
    print(f"  NET under PERFECT foresight on this one fly            = "
          f"{abs(2*v[1]-v[0]-v[2]) - 0.9915:.5f} bp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
