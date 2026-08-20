r"""Nail the hourly stamp to the minute, and explain why hour 15 is the odd one.

The coarse test said the hourly value at stamp H equals the minute tape as of
H+1h - a START-STAMPED bar carrying its own close. It tied out to a median
difference of 0.000 bp at stamps 10, 13 and 16, and to 0.187 bp at stamp 15.

A single hour behaving differently is either a real feature of that hour or a
defect in the test, and the two have opposite consequences for the study, so this
walks the candidate bound in minutes instead of hours.
"""

from __future__ import annotations

import pathlib

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

CANDIDATES = [
    ("H+45m", 45), ("H+50m", 50), ("H+55m", 55), ("H+58m", 58), ("H+59m", 59),
    ("H+60m", 60), ("H+61m", 61), ("H+65m", 65), ("H+75m", 75), ("H+90m", 90),
    ("H+120m", 120),
]


def main() -> int:
    cache = CitiVeloTagCache()
    stems = sorted((cache.base_dir / "MI01" / "CLOSE").glob("RATES.BOND.*.YIELD.parquet"))
    rows = []
    for p in stems[:120]:
        tag = p.stem
        mi = cache.read(tag, "MI01", "CLOSE")
        hr = cache.read(tag, "HOURLY", "CLOSE")
        if mi is None or hr is None or mi.empty or hr.empty:
            continue
        mi, hr = mi.dropna(), hr.dropna()
        mdays = pd.Series(mi.index).dt.date.to_numpy()
        hdays = pd.Series(hr.index).dt.date.to_numpy()
        for day in sorted(set(mdays) & set(hdays)):
            m = mi[mdays == day]
            h = hr[hdays == day]
            for hour in (10, 13, 14, 15, 16):
                ts = pd.Timestamp(day) + pd.Timedelta(hours=hour)
                if ts not in h.index:
                    continue
                target = float(h.loc[ts])
                for label, mins in CANDIDATES:
                    prior = m.index[m.index <= ts + pd.Timedelta(minutes=mins)]
                    if len(prior) == 0:
                        continue
                    v = float(m.loc[prior.max()])
                    rows.append({"hour": hour, "candidate": label,
                                 "exact": bool(abs(v - target) < 1e-9),
                                 "abs_diff_bp": abs(v - target) * 100.0})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    g = (df.groupby(["hour", "candidate"])
           .agg(n=("exact", "size"), exact=("exact", "mean"),
                med_bp=("abs_diff_bp", "median"))
           .reset_index())
    order = {c: i for i, (c, _) in enumerate(CANDIDATES)}
    g["ord"] = g["candidate"].map(order)
    piv_e = g.pivot(index="ord", columns="hour", values="exact")
    piv_e.index = [c for c, _ in CANDIDATES]
    piv_m = g.pivot(index="ord", columns="hour", values="med_bp")
    piv_m.index = [c for c, _ in CANDIDATES]
    print("EXACT-MATCH FRACTION between the hourly value at stamp H and the minute "
          "tape as of H+offset:")
    print(piv_e.round(3).to_string())
    print("\nMEDIAN |difference| in bp:")
    print(piv_m.round(4).to_string())
    best = piv_e.idxmax()
    print("\nBEST offset per stamp hour:", dict(best))
    piv_e.to_csv(DATA / "intraday_stamp_convention_minutes_exact.csv")
    piv_m.to_csv(DATA / "intraday_stamp_convention_minutes_absdiff.csv")
    print("wrote intraday_stamp_convention_minutes_*.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
