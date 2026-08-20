r"""ADVERSARIAL CHECK 3+4: the tape itself. TIMEZONE and DOWNSAMPLING.

OFFLINE ONLY -- CitiVeloTagCache reads parquet off disk. Nothing here touches Excel.

TIMEZONE, the decisive test
---------------------------
The report asserts America/New_York from market-behaviour arguments (a peak at stamp 14
on FOMC days). Those arguments assume what they conclude if the offset is wrong by a
whole number of hours. The test that needs NO assumption is DAYLIGHT SAVING:

  * if the stamps are New York LOCAL, a New York event sits at the SAME stamp hour all
    year, because the clock moves with the event.
  * if the stamps are UTC (or London), the same New York event moves by exactly ONE
    hour between EDT months and EST months.

So: split the tape into EDT months and EST months and compare the intraday activity
profile. A shift identifies the zone; no shift identifies local New York. This is the
same logic the repo used for the CVTSHIST request bound, applied to the DATA.

DOWNSAMPLING
------------
Per the brief, check the MINIMUM gap per tag, not the median: MI01 bond data is
genuinely sparse (median gap 2 min) so a 2-min median is liquidity, but a MINIMUM of
600 s over a whole block is the 10-minute cliff and means the window came back
downsampled.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")


def main() -> int:
    pd.set_option("display.width", 240)
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from RVUtils.ETFRebalance import intraday as ID

    uni = ID.universe()
    isins = list(uni["isin"].astype(str))
    cache = CitiVeloTagCache()

    # ------------------------------------------------------------------ DOWNSAMPLING
    print("=== DOWNSAMPLING: minimum gap per (tag, day-block), MI01 YIELD")
    rows, prof_all = [], []
    for i, isin in enumerate(isins):
        s = cache.read(f"RATES.BOND.{isin}.YIELD", "MI01", "CLOSE")
        if s is None or s.empty:
            rows.append({"isin": isin, "prints": 0, "days": 0, "min_gap_s": np.nan,
                         "med_gap_s": np.nan, "days_min_gap_ge_600s": 0})
            continue
        s = s.dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        idx = pd.DatetimeIndex(s.index)
        df = pd.DataFrame({"ts": idx})
        df["day"] = df["ts"].dt.normalize()
        g = df["ts"].diff().dt.total_seconds()
        same = df["day"].eq(df["day"].shift())
        g = g.where(same)
        per_day = g.groupby(df["day"]).agg(["min", "median", "count"]).dropna()
        n_bad = int((per_day["min"] >= 600).sum())
        rows.append({"isin": isin, "prints": len(s), "days": int(df["day"].nunique()),
                     "min_gap_s": float(g.min()), "med_gap_s": float(g.median()),
                     "days_min_gap_ge_600s": n_bad,
                     "days_min_gap_ge_3600s": int((per_day["min"] >= 3600).sum()),
                     "days_with_ge20_prints": int((per_day["count"] >= 20).sum())})
        # intraday activity profile for the tz test
        prof_all.append(pd.DataFrame({"ts": idx}))
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(isins)} tags", flush=True)

    dz = pd.DataFrame(rows)
    dz.to_csv(DATA / "adv_tape_mingap.csv", index=False)
    served = dz[dz["prints"] > 0]
    print(f"\ntags served {len(served)}/{len(dz)}   total prints {int(served['prints'].sum()):,}")
    print(f"MIN gap over the whole tape, distribution across tags:")
    print(served["min_gap_s"].value_counts().sort_index().head(10).to_string())
    print(f"tags whose GLOBAL min gap >= 600s (10-min cliff): "
          f"{int((served['min_gap_s'] >= 600).sum())}")
    print(f"tag-days whose min gap >= 600s: {int(served['days_min_gap_ge_600s'].sum()):,} "
          f"of {int(served['days'].sum()):,} tag-days")
    print(f"tag-days whose min gap >= 3600s: {int(served['days_min_gap_ge_3600s'].sum()):,}")
    print(f"median of per-tag MEDIAN gap: {served['med_gap_s'].median():.0f} s")

    # ------------------------------------------------------------------- TIMEZONE/DST
    print("\n=== TIMEZONE: DST test on the print-activity profile")
    ts = pd.concat(prof_all, ignore_index=True)["ts"]
    ts = pd.DatetimeIndex(ts)
    dfp = pd.DataFrame({"hour": ts.hour, "date": ts.normalize()})
    # US DST: 2nd Sun Mar .. 1st Sun Nov. Use a tz object to label without assuming.
    loc = pd.DatetimeIndex(dfp["date"]).tz_localize("America/New_York", nonexistent="shift_forward",
                                                    ambiguous="NaT")
    dfp["is_edt"] = (loc.map(lambda x: x.utcoffset().total_seconds() / 3600.0
                             if pd.notna(x) else np.nan) == -4.0)
    prof = (dfp.groupby(["is_edt", "hour"]).size().rename("prints").reset_index()
            .pivot(index="hour", columns="is_edt", values="prints").fillna(0))
    prof.columns = ["EST", "EDT"]
    prof["EST_share"] = prof["EST"] / prof["EST"].sum()
    prof["EDT_share"] = prof["EDT"] / prof["EDT"].sum()
    print(prof.round(4).to_string())
    prof.to_csv(DATA / "adv_tape_dst_profile.csv")
    # where is the peak, and does it move?
    pk_est, pk_edt = int(prof["EST_share"].idxmax()), int(prof["EDT_share"].idxmax())
    # centre of mass of the session as a sharper statistic than the mode
    com_est = float((prof.index * prof["EST_share"]).sum())
    com_edt = float((prof.index * prof["EDT_share"]).sum())
    print(f"\npeak stamp hour: EST {pk_est}  EDT {pk_edt}   (shift {pk_edt - pk_est} h)")
    print(f"session centre of mass: EST {com_est:.3f}  EDT {com_edt:.3f}  "
          f"(shift {com_edt - com_est:+.3f} h)")
    print("EXPECT: shift 0 if stamps are America/New_York; shift -1 (EDT earlier in "
          "stamp space) if stamps are UTC/London.")

    # first/last print hour of the session, which is a hard edge
    edge = dfp.groupby(["is_edt", "date"])["hour"].agg(["min", "max"]).reset_index()
    e = edge.groupby("is_edt")[["min", "max"]].median()
    print("\nmedian first/last stamp hour of a session:")
    print(e.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
