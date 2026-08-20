r"""Does a WIDER butterfly see more of the seam? Bound the structure, not one choice of it.

The 0.092 bp perfect-foresight ceiling was measured on adjacent-maturity triplets,
and an adjacent fly is the tightest possible: neighbouring bonds' richness
residuals are correlated, so most of the move cancels. A wider fly - belly against
wings two or three issues away - keeps more of the idiosyncratic move, at the cost
of more residual curve exposure.

If the ceiling rose enough with width to reach the cost, the adjacent-triplet
result would be an artefact of one arbitrary choice of structure rather than a
property of the seam. So it is swept.

Cost does not fall with width and there is no reason to think it rises much
either - all three legs are the same kind of 20-31y Treasury - so the measured
0.535 bp round trip is held fixed and the comparison is honest in the direction
that matters.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402
from RVUtils.ETFRebalance.curve import fit_residuals  # noqa: E402

FLY_ROUND_TRIP_BP = 0.535


def residual_panel(frame, stamp, meta):
    idx = pd.Series(frame.index)
    sub = frame[(idx.dt.hour == stamp).to_numpy()]
    sub = sub[~pd.Series(sub.index).dt.normalize().duplicated(keep="last").to_numpy()]
    long = sub.stack().rename("ytm").reset_index()
    long.columns = ["stamp", "tag", "ytm"]
    long["isin"] = long["tag"].str.split(".").str[2]
    long = long.merge(meta, on="isin", how="left")
    long["date"] = pd.to_datetime(long["stamp"]).dt.normalize()
    long["ttm"] = (long["maturity_date"] - long["stamp"]).dt.days / 365.25
    long = long[(long["ttm"] > 0) & long["ytm"].notna() & long["cpn"].notna()]
    long = long[long.groupby("date")["cusip"].transform("size") >= 20]
    r = fit_residuals(long, deg=3, x_axis="ttm", include_coupon=True, robust=True,
                      y_col="ytm")
    return r.pivot_table(index="date", columns="cusip", values="resid_bp")


def main() -> int:
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
    meta = uni.rename(columns={"coupon": "cpn"})[["isin", "cusip", "maturity_date", "cpn"]]
    mat = dict(zip(uni["cusip"].astype(str), uni["maturity_date"]))

    q = CitiVeloQuotes(offline=True)
    frame = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "HOURLY")
    frame = frame[frame.index >= "2021-01-01"]
    a = residual_panel(frame, 14, meta)      # the 15:00 New York mark
    b = residual_panel(frame, 15, meta)      # the 16:00 New York mark
    cols = a.columns.intersection(b.columns)
    idx = a.index.intersection(b.index)
    dr = (b.loc[idx, cols] - a.loc[idx, cols])
    dr = dr[dr.notna().sum(axis=1) >= 20]
    print(f"{len(dr)} dates x {len(cols)} bonds")

    rows = []
    for step in (1, 2, 3, 4, 6):
        per_date = []
        for _, row in dr.iterrows():
            v = row.dropna()
            if len(v) < 2 * step + 3:
                continue
            order = sorted(v.index, key=lambda c: mat.get(c, pd.Timestamp.max))
            vals = v[order].to_numpy()
            f = 2.0 * vals[step:-step] - vals[:-2 * step] - vals[2 * step:]
            if f.size:
                per_date.append((np.mean(np.abs(f)), np.std(f), f.size))
        if not per_date:
            continue
        arr = np.array(per_date)
        ceiling = float(np.median(arr[:, 0]))
        rows.append({
            "wing_step_issues": step,
            "approx_wing_gap_months": step * 3,
            "dates": len(arr),
            "flies_per_date": int(np.median(arr[:, 2])),
            "perfect_foresight_gross_bp": ceiling,
            "fly_sd_bp": float(np.median(arr[:, 1])),
            "cost_bp": FLY_ROUND_TRIP_BP,
            "gross_over_cost": ceiling / FLY_ROUND_TRIP_BP,
        })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print("\n15:00 -> 16:00 New York, PERFECT-FORESIGHT CEILING vs BUTTERFLY WIDTH")
    print(out.round(4).to_string(index=False))
    print(f"\nWidest structure tested reaches {out['gross_over_cost'].max():.3f}x the "
          f"measured {FLY_ROUND_TRIP_BP:.3f} bp round trip, with perfect foresight.")
    out.to_csv(DATA / "intraday_fly_width_sweep.csv", index=False)
    print("wrote intraday_fly_width_sweep.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
