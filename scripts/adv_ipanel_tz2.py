r"""ADVERSARIAL CHECK 3 (proper): TIMEZONE from MOVEMENT, not print counts.

The print-count profile on this tape is flat around the clock (3.4-5.2% per hour, peak
at 19:00) because Citi writes an evaluated mark on a schedule, not on a trade. Counting
prints therefore measures Citi's publisher, not the market, and cannot locate a session.

The quantity that DOES locate the New York session is how much the mark MOVES. Three
tests, in increasing sharpness:

  1. mean |d yield| by stamp hour  -> where is the session?
  2. the same, split EDT vs EST    -> DST discriminates local NY from UTC/London with
                                       no assumption about the offset
  3. FOMC statement days, 14:00 ET -> a dated event with a known clock time
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")

# FOMC statement days (14:00 ET release) inside the MI01 tape's span.
FOMC = [
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28",
    "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27",
    "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26",
    "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31",
    "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30",
    "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
]


def main() -> int:
    pd.set_option("display.width", 240)
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from RVUtils.ETFRebalance import intraday as ID

    uni = ID.universe()
    # the 24 bonds with the most MI01 coverage, by parquet size proxy: just take the
    # first 24 in the reference band -- coverage is near-uniform across the universe.
    isins = list(uni[uni["in_reference_band"].fillna(False)]["isin"].astype(str))[:24]
    cache = CitiVeloTagCache()

    parts = []
    for i, isin in enumerate(isins):
        s = cache.read(f"RATES.BOND.{isin}.YIELD", "MI01", "CLOSE")
        if s is None or s.empty:
            continue
        s = s.dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s[(s > 0.2) & (s < 12.0)]
        idx = pd.DatetimeIndex(s.index)
        d = pd.DataFrame({"ts": idx, "y": s.to_numpy(float)})
        d["day"] = d["ts"].dt.normalize()
        gap = d["ts"].diff().dt.total_seconds()
        same = d["day"].eq(d["day"].shift())
        # only changes over a <=5 minute contiguous gap, so a hole is not a "move"
        d["dy"] = (d["y"].diff() * 100.0).where(same & gap.le(300))
        d["hour"] = d["ts"].dt.hour
        parts.append(d[["ts", "day", "hour", "dy"]].dropna())
        if (i + 1) % 8 == 0:
            print(f"  {i+1}/{len(isins)} tags", flush=True)
    a = pd.concat(parts, ignore_index=True)
    print(f"\n{len(a):,} contiguous minute changes over {len(isins)} bonds")

    # ------------------------------------------------- 1. where is the session?
    prof = a.groupby("hour")["dy"].agg(n="size", mabs=lambda x: float(np.mean(np.abs(x))))
    prof["rel"] = prof["mabs"] / prof["mabs"].mean()
    print("\n=== MEAN |d yield| (bp per contiguous minute) BY STAMP HOUR")
    print(prof.round(4).to_string())
    prof.to_csv(DATA / "adv_tz_hour_profile.csv")
    print(f"peak movement hour: {int(prof['mabs'].idxmax())}   "
          f"quietest: {int(prof['mabs'].idxmin())}")

    # ------------------------------------------------- 2. DST
    loc = pd.DatetimeIndex(a["day"]).tz_localize("America/New_York",
                                                 nonexistent="shift_forward", ambiguous="NaT")
    off = pd.Series(loc.map(lambda x: x.utcoffset().total_seconds() / 3600.0
                            if pd.notna(x) else np.nan).to_numpy(), index=a.index)
    a["is_edt"] = off.eq(-4.0)
    p2 = (a.groupby(["is_edt", "hour"])["dy"].apply(lambda x: float(np.mean(np.abs(x))))
          .rename("mabs").reset_index().pivot(index="hour", columns="is_edt", values="mabs"))
    p2.columns = ["EST", "EDT"]
    p2["EST_rel"] = p2["EST"] / p2["EST"].mean()
    p2["EDT_rel"] = p2["EDT"] / p2["EDT"].mean()
    print("\n=== DST TEST: movement profile, EST vs EDT")
    print(p2.round(4).to_string())
    p2.to_csv(DATA / "adv_tz_dst_movement.csv")
    # centre of mass over the active window 06-20 to avoid the flat overnight
    win = p2.loc[6:20]
    com_est = float((win.index * win["EST"]).sum() / win["EST"].sum())
    com_edt = float((win.index * win["EDT"]).sum() / win["EDT"].sum())
    print(f"\npeak hour EST {int(p2['EST'].idxmax())}  EDT {int(p2['EDT'].idxmax())}")
    print(f"centre of mass 06-20h: EST {com_est:.3f}  EDT {com_edt:.3f}  "
          f"shift {com_edt - com_est:+.3f} h")
    print("EXPECT shift ~0 => stamps track the New York clock. shift ~-1 => UTC/London.")

    # ------------------------------------------------- 3. FOMC 14:00 ET
    fset = set(pd.to_datetime(FOMC).normalize())
    a["fomc"] = a["day"].isin(fset)
    f = (a.groupby(["fomc", "hour"])["dy"].apply(lambda x: float(np.mean(np.abs(x))))
         .rename("mabs").reset_index().pivot(index="hour", columns="fomc", values="mabs"))
    f.columns = ["other", "fomc"]
    f["ratio"] = f["fomc"] / f["other"]
    print("\n=== FOMC DAYS vs OTHER DAYS, movement ratio by stamp hour")
    print(f.round(3).to_string())
    f.to_csv(DATA / "adv_tz_fomc.csv")
    print(f"\nFOMC excess peaks at stamp hour {int(f['ratio'].idxmax())} "
          f"(ratio {f['ratio'].max():.2f}x).")
    print("Statement is 14:00 New York. ET predicts 14; UTC predicts 18 (EDT)/19 (EST); "
          "London predicts 19/19.")

    # ------------------------------------------------- 4. minute-of-day around the seam
    b = a[a["hour"].between(14, 17)].copy()
    b["mod"] = b["ts"].dt.hour * 60 + b["ts"].dt.minute
    m = b.groupby("mod")["dy"].apply(lambda x: float(np.mean(np.abs(x)))).rename("mabs")
    top = m.sort_values(ascending=False).head(12)
    print("\n=== 12 busiest MINUTES between 14:00 and 17:59 (movement)")
    print(pd.DataFrame({"minute": [f"{i//60:02d}:{i%60:02d}" for i in top.index],
                        "mean_abs_bp": top.to_numpy()}).round(4).to_string(index=False))
    m.to_csv(DATA / "adv_tz_minute_profile.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
