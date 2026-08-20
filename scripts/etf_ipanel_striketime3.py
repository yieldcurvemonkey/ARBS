r"""Third, simplest reading of FedInvest's strike time -- and an honesty check on R2.

The two-day segment chain put the strike inside 11:00-12:00 New York with an R2 of only
0.52, and an R2 that low on two sources whose cross-sections correlate at 0.99 has to be
explained rather than shrugged at. This runs the most direct statistic available:

    corr( fed(t) - fed(t-1) ,  citi(T,t) - citi(T,t-1) )   for each mark time T

If FedInvest is a snapshot at T*, this correlation is maximised at T = T*, and its LEVEL
says how much of FedInvest's daily change is a snapshot of this market at all. A high
peak (0.9+) with the regression's R2 at 0.52 would mean the regression is losing power to
collinearity between segments; a low peak means FedInvest genuinely carries variance the
Citi path does not, which is a caveat on the whole tie-out and must be reported as one.

The same is done on a DE-MEANED basis -- each bond's change minus the day's cross-
sectional mean -- because the level is one common factor shared by every bond and the
cross-section is what this study actually trades.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import intraday as ID  # noqa: E402
from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402

DATA = IP.DATA


def daily_change_corr(marks: pd.DataFrame, fed: pd.DataFrame, label: str) -> pd.DataFrame:
    w = marks.merge(fed, on=["date", "cusip"], how="inner").dropna(
        subset=["ytm", "ytm_fed"])
    w = w.sort_values(["mark_time", "cusip", "date"])
    g = w.groupby(["mark_time", "cusip"])
    prev_date = g["date"].shift(1)
    has_prev = prev_date.notna()
    gap = np.full(len(w), -1, dtype=int)
    gap[has_prev.to_numpy()] = np.busday_count(
        prev_date[has_prev].values.astype("datetime64[D]"),
        w.loc[has_prev.to_numpy(), "date"].values.astype("datetime64[D]"))
    w["d_citi"] = (w["ytm"] - g["ytm"].shift(1)) * 100.0
    w["d_fed"] = (w["ytm_fed"] - g["ytm_fed"].shift(1)) * 100.0
    w = w[(gap == 1) & w["d_citi"].notna() & w["d_fed"].notna()]

    rows = []
    for mt, s in w.groupby("mark_time"):
        lvl = s.groupby("date")[["d_citi", "d_fed"]].mean()
        s = s.copy()
        s["x"] = s["d_citi"] - s.groupby("date")["d_citi"].transform("mean")
        s["y"] = s["d_fed"] - s.groupby("date")["d_fed"].transform("mean")
        beta = float(np.polyfit(lvl["d_citi"], lvl["d_fed"], 1)[0])
        rows.append({
            "layer": label, "mark_time": mt, "dates": int(len(lvl)),
            "bond_days": int(len(s)),
            "corr_level": float(lvl["d_citi"].corr(lvl["d_fed"])),
            "beta_level": beta,
            "corr_xsec_demeaned": float(s["x"].corr(s["y"])),
            "rmse_level_bp": float(np.sqrt(((lvl["d_fed"] - lvl["d_citi"]) ** 2).mean())),
        })
    return pd.DataFrame(rows).sort_values("mark_time")


def main() -> int:
    pd.set_option("display.width", 220)
    p = IP.load_panel("MI01")
    d = BP.load()
    d = d[d["cusip"].isin(set(p["cusip"])) & d["ytm"].notna() & d["price_source"].eq("mid")]
    fed = d[["date", "cusip", "ytm"]].rename(columns={"ytm": "ytm_fed"})

    m = p[p["is_fresh"] & p["ytm"].notna()][["date", "cusip", "mark_time", "ytm"]]
    t1 = daily_change_corr(m, fed, "MI01 (2021-2026)")

    uni = ID.universe()
    frame = ID.drop_impossible(ID.hourly_frame("YIELD"), "YIELD")
    hrs = []
    for hour in range(9, 18):
        sub = ID.ny_marks(frame, hour)
        long = sub.stack().rename("ytm").reset_index()
        long.columns = ["date", "isin", "ytm"]
        long = long.merge(uni[["isin", "cusip"]], on="isin", how="left")
        long["mark_time"] = f"{hour:02d}:00"
        hrs.append(long[["date", "cusip", "mark_time", "ytm"]])
    hm = pd.concat(hrs, ignore_index=True).dropna()
    t2 = daily_change_corr(hm, fed, "HOURLY (2019-2026)")

    tab = pd.concat([t1, t2], ignore_index=True)
    print("CORRELATION OF FedInvest's DAILY CHANGE WITH CITI's T-to-T DAILY CHANGE:")
    print(tab.round(4).to_string(index=False))
    tab.to_csv(DATA / "ipanel_striketime_dailycorr.csv", index=False)

    for lab, g in tab.groupby("layer", sort=False):
        b = g.sort_values("corr_level", ascending=False)
        print(f"\n{lab}: peak corr_level at {b.iloc[0]['mark_time']} "
              f"({b.iloc[0]['corr_level']:.4f}); runner-up {b.iloc[1]['mark_time']} "
              f"({b.iloc[1]['corr_level']:.4f})")
        bx = g.sort_values("corr_xsec_demeaned", ascending=False)
        print(f"   cross-sectionally de-meaned peak at {bx.iloc[0]['mark_time']} "
              f"({bx.iloc[0]['corr_xsec_demeaned']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
