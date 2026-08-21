r"""Three cost anchors for a 20-31y UST butterfly, side by side, by year and sector.

The level of the cost is the parameter that decides this study, so it gets three
independent estimates rather than one, and the credibility argument is written down
BEFORE the numbers are seen so it cannot be fitted to them:

**FedInvest bid/offer.** Dated, per-CUSIP, per-day, two-sided. It is a *quote* from the
Federal Investments Program, not an interdealer execution, and it is the *retail-facing*
side of a government programme. Direction of its error is unknown a priori: a programme
quote can be wider than an interdealer market (no competition) or tighter (no inventory
risk being priced). What is certain is that it is a real, dated, two-sided quote on the
exact CUSIP.

**Roll (1984), from this tape.** ``S = 2 sqrt(-cov(dP_t, dP_{t-1}))``. Roll's estimator
identifies the spread from the negative autocovariance that bid-ask BOUNCE induces in
transaction prices. Citi's tape is a tape of **marks, not executions**. That matters in
both directions and neither is a get-out:

* if the marks are a mid, there is no bounce to find and Roll measures whatever
  microstructure noise the mark process has -- which is a *lower* bound on a real spread;
* if the marks alternate between sides, Roll measures a real spread.

Two further deflators, both measured here rather than argued: a **stale** mark repeated
across minutes injects zero changes, which pull the autocovariance toward zero and so
pull Roll *down*; and with a finite number of pairs Roll returns a positive number from a
spreadless random walk purely by sampling error, which pulls it *up*. The second is
calibrated by simulation at this study's own pair counts and reported as a NOISE FLOOR,
so a Roll estimate below its floor is read as "no measurable spread", not as a cheap one.

**SR1170 Table 3.** Executions, from the NY Fed, keyed on off-the-run rank -- the right
axis. Its 30y "further off-the-run" bucket, which every bond here sits in, is 166.98
price bp, dominated by odd lots in genuinely dead issues. The pessimistic bound.

Everything is reported in BOTH price bp and yield bp, and as a BUTTERFLY round trip,
because that is the object being traded: three legs whose DV01 weights sum to twice the
belly's, so the fly pays ~2x the average leg's full spread, charged once at the unwind.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import costs as CO  # noqa: E402
from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402
from RVUtils.ETFRebalance.intraday_panel import roll_spread  # noqa: E402

DATA = IP.DATA
SECTORS = (("20-25y", 20.0, 25.0), ("25-31y", 25.0, 31.0), ("12-20y", 12.0, 20.0))
FLY_MULT = 2.0          # a DV01-neutral fly pays ~2x the average leg's full spread


def noise_floor(n_pairs_grid=(50, 100, 250, 500, 1000, 2500, 5000, 10000),
                sigma_bp=3.0, reps=400, seed=20260820) -> pd.DataFrame:
    """What Roll returns on a SPREADLESS random walk, by sample size.

    Roll takes a square root of a noisy covariance, so its sampling distribution is
    one-sided: a spreadless series still yields a positive estimate whenever the sample
    autocovariance happens to be negative, which is half the time. Any real estimate
    below this floor is indistinguishable from no spread at all.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for n in n_pairs_grid:
        est = []
        for _ in range(reps):
            w = 100.0 * np.exp(np.cumsum(rng.normal(0, sigma_bp * 1e-4, n + 2)))
            s, _, _ = roll_spread(w, np.ones(n + 2, bool))
            est.append(s)
        e = np.array(est, float)
        fin = e[np.isfinite(e)]
        rows.append({"n_pairs": n, "frac_defined": float(np.isfinite(e).mean()),
                     "roll_median_price_bp": float(np.median(fin)) if len(fin) else np.nan,
                     "roll_p90_price_bp": float(np.quantile(fin, .90)) if len(fin) else np.nan})
    return pd.DataFrame(rows)


def sector_of(ttm: float) -> str:
    for name, lo, hi in SECTORS:
        if lo <= ttm < hi:
            return name
    return "other"


def main() -> int:
    pd.set_option("display.width", 260)

    p = IP.load_panel("MI01")
    p16 = p[p["mark_time"].eq("16:00") & p["is_fresh"]].copy()
    p16["sector"] = p16["ttm"].map(sector_of)
    p16["year"] = p16["date"].dt.year

    # ------------------------------------------------- (a) FedInvest published bid/offer
    fed = p16.dropna(subset=["spread_price_bp", "mod_dur"]).copy()
    fed = fed[fed["spread_price_bp"] >= CO.MIN_SPREAD_PRICE_BP]
    fed["leg_yield_bp"] = fed["spread_price_bp"] / fed["mod_dur"]

    # ------------------------------------------------------------- (c) SR1170, per row
    sr = p16.dropna(subset=["mod_dur"]).copy()
    rank = sr["rank"].fillna(6).clip(upper=6).astype(int)
    sr["sr1170_price_bp"] = [CO.SR1170_FULL_SAMPLE[30][r] for r in rank]
    sr["sr1170_yield_bp"] = sr["sr1170_price_bp"] / sr["mod_dur"]
    print("off-the-run rank distribution in this universe: "
          + str(rank.value_counts().sort_index().to_dict()))

    # --------------------------------------------------------------- (b) Roll (1984)
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    isins = uni["isin"].astype(str).tolist()
    print(f"\nRoll: estimating over {len(isins)} bonds x months ...", flush=True)
    roll_all = IP.roll_by_bond_month(isins, drop_zero_changes=False)
    roll_nz = IP.roll_by_bond_month(isins, drop_zero_changes=True)
    roll_all["variant"] = "all changes"
    roll_nz["variant"] = "zero changes dropped"
    roll = pd.concat([roll_all, roll_nz], ignore_index=True)
    roll = roll.merge(uni[["isin", "cusip", "maturity_date"]], on="isin", how="left")
    roll["maturity_date"] = pd.to_datetime(roll["maturity_date"])
    roll["ttm"] = (roll["maturity_date"] - roll["month"]).dt.days / 365.25
    roll["sector"] = roll["ttm"].map(sector_of)
    roll["year"] = roll["month"].dt.year
    roll.to_csv(DATA / "ipanel_roll_bond_month.csv", index=False)

    # a duration to convert with: the median mod_dur for that bond-month
    md = (p16.assign(month=p16["date"].values.astype("datetime64[M]"))
              .groupby(["cusip", "month"])["mod_dur"].median().rename("mod_dur"))
    roll["month"] = pd.to_datetime(roll["month"])
    roll = roll.merge(md, left_on=["cusip", "month"], right_index=True, how="left")
    roll["roll_yield_bp"] = roll["roll_price_bp"] / roll["mod_dur"]

    nf = noise_floor()
    print("\nROLL NOISE FLOOR -- what a SPREADLESS random walk returns, by sample size:")
    print(nf.round(4).to_string(index=False))
    nf.to_csv(DATA / "ipanel_roll_noise_floor.csv", index=False)
    med_pairs = float(roll["n_pairs"].median())
    floor_at = float(np.interp(med_pairs, nf["n_pairs"], nf["roll_median_price_bp"]))
    print(f"median pairs per bond-month: {med_pairs:,.0f}  ->  noise floor "
          f"{floor_at:.4f} price bp")

    rows = []
    for v, g in roll.groupby("variant"):
        rows.append({
            "variant": v, "bond_months": int(len(g)),
            "frac_autocov_positive_undefined": float(g["roll_price_bp"].isna().mean()),
            "median_n_pairs": float(g["n_pairs"].median()),
            "roll_price_bp_median": float(g["roll_price_bp"].median()),
            "roll_yield_bp_median": float(g["roll_yield_bp"].median()),
        })
    rv = pd.DataFrame(rows)
    print("\nROLL, the two variants:")
    print(rv.round(4).to_string(index=False))
    rv.to_csv(DATA / "ipanel_roll_variants.csv", index=False)

    ROLL_VARIANT = "all changes"
    rsel = roll[roll["variant"].eq(ROLL_VARIANT)]

    # --------------------------------------------------------- the side-by-side table
    def agg(df, col_price, col_yield, keys):
        g = df.dropna(subset=[col_price, col_yield]).groupby(keys)
        return pd.DataFrame({
            "n": g.size(),
            "price_bp_med": g[col_price].median(),
            "yield_bp_med": g[col_yield].median(),
            "yield_bp_p90": g[col_yield].quantile(.90),
        })

    out = []
    for keys, label in ((["year"], "by year"), (["sector"], "by sector"),
                        (["year", "sector"], "by year x sector")):
        a = agg(fed, "spread_price_bp", "leg_yield_bp", keys).add_prefix("fedinvest_")
        b = agg(rsel, "roll_price_bp", "roll_yield_bp", keys).add_prefix("roll_")
        c = agg(sr, "sr1170_price_bp", "sr1170_yield_bp", keys).add_prefix("sr1170_")
        t = a.join(b, how="outer").join(c, how="outer").reset_index()
        t.insert(0, "grouping", label)
        out.append(t)
    anchors = pd.concat(out, ignore_index=True)
    for src in ("fedinvest", "roll", "sr1170"):
        anchors[f"{src}_fly_rt_bp"] = FLY_MULT * anchors[f"{src}_yield_bp_med"]
    anchors.to_csv(DATA / "ipanel_cost_anchors.csv", index=False)

    show = [c for c in anchors.columns
            if c in ("grouping", "year", "sector") or c.endswith(("_price_bp_med", "_fly_rt_bp"))]
    print("\nTHREE COST ANCHORS, BUTTERFLY ROUND TRIP IN YIELD BP:")
    print(anchors[anchors["grouping"].ne("by year x sector")][show]
          .round(3).to_string(index=False))

    # ------------------------------------------------------------------- the headline
    hl = {
        "fedinvest_leg_price_bp_median": float(fed["spread_price_bp"].median()),
        "fedinvest_leg_yield_bp_median": float(fed["leg_yield_bp"].median()),
        "fedinvest_fly_rt_bp": FLY_MULT * float(fed["leg_yield_bp"].median()),
        "roll_leg_price_bp_median": float(rsel["roll_price_bp"].median()),
        "roll_leg_yield_bp_median": float(rsel["roll_yield_bp"].median()),
        "roll_fly_rt_bp": FLY_MULT * float(rsel["roll_yield_bp"].median()),
        "roll_noise_floor_price_bp": floor_at,
        "roll_undefined_frac": float(rsel["roll_price_bp"].isna().mean()),
        "sr1170_leg_price_bp_median": float(sr["sr1170_price_bp"].median()),
        "sr1170_leg_yield_bp_median": float(sr["sr1170_yield_bp"].median()),
        "sr1170_fly_rt_bp": FLY_MULT * float(sr["sr1170_yield_bp"].median()),
        "daily_study_fly_rt_bp": 0.535,
    }
    hl["roll_over_fedinvest_price"] = (hl["roll_leg_price_bp_median"]
                                       / hl["fedinvest_leg_price_bp_median"])
    print("\nHEADLINE:")
    for k, v in hl.items():
        print(f"  {k:38s} {v:10.4f}")
    pd.DataFrame([hl]).T.rename(columns={0: "value"}).to_csv(
        DATA / "ipanel_cost_headline.csv")
    print("\nwrote ipanel_cost_anchors.csv, ipanel_cost_headline.csv, "
          "ipanel_roll_bond_month.csv, ipanel_roll_variants.csv, "
          "ipanel_roll_noise_floor.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
