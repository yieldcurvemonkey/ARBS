r"""How long does a butterfly have to be held before the pond can pay for the boat?

The one-hour seam is bounded: a PERFECT forecaster of every adjacent-maturity
butterfly's 15:00->16:00 richness change earns 0.092 bp gross against a measured
0.535 bp round trip. That kills the one-hour trade without needing a signal.

It does not by itself kill every intraday horizon, so this sweeps them. Cost is
per TRADE and does not care how long the trade is held, so the ratio improves
mechanically with horizon and the only question is where it crosses one - and
whether the crossing point is inside the intraday window the study is about, or
back out at the daily horizon the daily study already measured and rejected.

Perfect foresight is the ceiling, and it is a very generous one. A real signal
captures a fraction of it: an information coefficient of 0.10, which is a
respectable cross-sectional IC, turns a ceiling of X bp into roughly 0.08*X of
realised gross. The last column says what IC would be needed just to break even,
so a horizon can be dismissed on feasibility rather than on the ceiling alone.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402
from RVUtils.ETFRebalance.curve import fit_residuals  # noqa: E402

FLY_ROUND_TRIP_BP = 0.535

#: (label, stamp hour). Citi's HOURLY bars are START-stamped and carry their own
#: close, verified to equal the minute tape at H:59 on 100.0% of 3,804 bond-day
#: hours - so the New York mark at clock time C lives at stamp C-1.
CLOCKS = {"09:00": 8, "10:00": 9, "12:00": 11, "14:00": 13, "15:00": 14,
          "16:00": 15, "17:00": 16}


def residual_panel(frame: pd.DataFrame, stamp: int, meta: pd.DataFrame) -> pd.DataFrame:
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


def fly_stats(dr: pd.DataFrame, mat: dict) -> tuple[float, float, int]:
    rows = []
    for _, row in dr.iterrows():
        v = row.dropna()
        if len(v) < 5:
            continue
        order = sorted(v.index, key=lambda c: mat.get(c, pd.Timestamp.max))
        vals = v[order].to_numpy()
        f = 2.0 * vals[1:-1] - vals[:-2] - vals[2:]
        rows.append((np.mean(np.abs(f)), np.std(f)))
    if not rows:
        return float("nan"), float("nan"), 0
    arr = np.array(rows)
    return float(np.median(arr[:, 0])), float(np.median(arr[:, 1])), len(rows)


def main() -> int:
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
    meta = uni.rename(columns={"coupon": "cpn"})[["isin", "cusip", "maturity_date", "cpn"]]
    mat = dict(zip(uni["cusip"].astype(str), uni["maturity_date"]))

    q = CitiVeloQuotes(offline=True)
    frame = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "HOURLY")
    frame = frame[frame.index >= "2021-01-01"]
    panels = {c: residual_panel(frame, s, meta) for c, s in CLOCKS.items()}
    print(f"residual panels built at {len(panels)} clock times, "
          f"{panels['16:00'].shape[0]} dates x {panels['16:00'].shape[1]} bonds")

    rows = []
    horizons = [("15:00", "16:00", 0), ("14:00", "16:00", 0), ("12:00", "16:00", 0),
                ("10:00", "16:00", 0), ("09:00", "17:00", 0),
                ("16:00", "16:00", 1), ("16:00", "16:00", 5), ("16:00", "16:00", 21)]
    for c0, c1, lag_d in horizons:
        a, b = panels[c0], panels[c1]
        cols = a.columns.intersection(b.columns)
        if lag_d:
            bb = b.copy()
            bb.index = bb.index - pd.Timedelta(days=0)
            b_shift = b.shift(-lag_d)
            idx = a.index.intersection(b_shift.index)
            dr = b_shift.loc[idx, cols] - a.loc[idx, cols]
        else:
            idx = a.index.intersection(b.index)
            dr = b.loc[idx, cols] - a.loc[idx, cols]
        dr = dr[dr.notna().sum(axis=1) >= 20]
        mean_abs, sd, n = fly_stats(dr, mat)
        label = f"{c0}->{c1}" + (f" +{lag_d}bd" if lag_d else "")
        rows.append({
            "horizon": label, "dates": n,
            "fly_mean_abs_bp": mean_abs, "fly_sd_bp": sd,
            "perfect_foresight_gross_bp": mean_abs,
            "cost_bp": FLY_ROUND_TRIP_BP,
            "gross_over_cost": mean_abs / FLY_ROUND_TRIP_BP,
            "IC_needed_to_breakeven": FLY_ROUND_TRIP_BP / mean_abs * 0.8
            if mean_abs == mean_abs and mean_abs > 0 else np.nan,
        })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 240)
    print("\nPERFECT-FORESIGHT CEILING PER BUTTERFLY, BY HOLDING HORIZON")
    print("(gross is the mean |richness change| of an adjacent-maturity fly; "
          "cost is the measured 0.535 bp round trip)")
    print(out.round(4).to_string(index=False))
    print("\nIC_needed_to_breakeven is 0.8 * cost / ceiling: an IC above ~0.15 "
          "cross-sectionally is not achievable in this literature, so anything "
          "needing more than that is dead on feasibility, not just on the ceiling.")
    out.to_csv(DATA / "intraday_horizon_sweep.csv", index=False)
    print("\nwrote intraday_horizon_sweep.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
