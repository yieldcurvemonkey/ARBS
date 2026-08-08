"""Can the Part 43 tape support a NEW-RISK vs UNWIND composition state?

Pure coverage counting (design doc: data description consumes no trial). This
decides whether F8 is registerable at all, and in what form:

  * how many rows carry each (action, event) cell, per L-0072's matrix -- and
    VERIFIED AGAINST THE FILE rather than trusted from the imported flags,
    because L-0078 found one of those flags does not describe this tape;
  * whether unwind-shaped rows carry the tenor information a per-structure
    composition ratio needs (effective + expiration dates);
  * how persistent the resulting composition series is -- a state that is not
    persistent is F7 again, and L-0085 already killed that shape.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 \
     scripts/s3_f8_composition_probe.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_REPO = pathlib.Path(__file__).resolve().parents[1]
SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")  # READ-ONLY
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

COLS = ["Action type", "Event type", "Execution Timestamp", "Effective Date",
        "Expiration Date", "Notional currency-Leg 1", "Notional amount-Leg 1",
        "UPI FISN", "Product name"]


def main() -> None:
    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    picks = [files[i] for i in range(0, len(files), max(1, len(files) // 120))][:120]
    print(f"sampling {len(picks)} of {len(files)} files")

    cells, daily = {}, []
    for fp in picks:
        names = set(pq.read_schema(fp).names)
        want = [c for c in COLS if c in names]
        df = pq.read_table(fp, columns=want).to_pandas()
        key = "UPI FISN" if "UPI FISN" in df.columns else "Product name"
        d = df[df["Notional currency-Leg 1"].astype(str).eq("USD")
               & df[key].astype(str).str.contains("OIS", na=False)].copy()
        if d.empty:
            continue
        d["a"] = d["Action type"].astype(str)
        d["e"] = d["Event type"].astype(str)
        for (a, e), n in d.groupby(["a", "e"]).size().items():
            cells[(a, e)] = cells.get((a, e), 0) + int(n)

        eff = pd.to_datetime(d["Effective Date"], errors="coerce")
        exp = pd.to_datetime(d["Expiration Date"], errors="coerce")
        d["_has_tenor"] = eff.notna() & exp.notna()
        new = d[(d.a == "NEWT") & (d.e == "TRAD")]
        unw = d[(d.a == "TERM") | (d.e == "ETRM")]
        daily.append({
            "file_date": pd.Timestamp(fp.stem),
            "new_risk": len(new), "unwind": len(unw),
            "unwind_with_tenor": int(unw["_has_tenor"].sum()),
            "new_with_tenor": int(new["_has_tenor"].sum()),
        })

    ct = (pd.Series(cells).sort_values(ascending=False).rename("rows")
          .rename_axis(["action", "event"]).reset_index())
    ct["share"] = (ct["rows"] / ct["rows"].sum()).round(4)
    print("\n=== (action, event) cells, USD OIS ===")
    print(ct.head(14).to_string(index=False))

    dd = pd.DataFrame(daily).sort_values("file_date").reset_index(drop=True)
    dd["u_share"] = dd["unwind"] / (dd["new_risk"] + dd["unwind"]).replace(0, np.nan)
    print(f"\n=== daily new-risk vs unwind over {len(dd)} sampled days ===")
    print(f"  new_risk/day  median {dd.new_risk.median():.0f}  "
          f"(tenor-parsable {dd.new_with_tenor.sum() / max(1, dd.new_risk.sum()):.1%})")
    print(f"  unwind/day    median {dd.unwind.median():.0f}  "
          f"(tenor-parsable {dd.unwind_with_tenor.sum() / max(1, dd.unwind.sum()):.1%})")
    print(f"  unwind share  median {dd.u_share.median():.4f}  "
          f"IQR {dd.u_share.quantile(.25):.4f}-{dd.u_share.quantile(.75):.4f}  "
          f"sd {dd.u_share.std(ddof=1):.4f}")

    # PERSISTENCE -- the property that decides whether F8 is a regime or an event.
    s = dd.set_index("file_date")["u_share"].dropna()
    ac = [float(s.autocorr(k)) for k in (1, 5, 10, 21)]
    print(f"  autocorrelation of the unwind share: lag1 {ac[0]:+.3f}  lag5 {ac[1]:+.3f}  "
          f"lag10 {ac[2]:+.3f}  lag21 {ac[3]:+.3f}   (sampled every "
          f"{len(files) // len(picks)} files, so 'lag1' is ~{len(files) // len(picks)} "
          f"trading days)")

    res = {
        "sampled_files": len(picks), "total_files": len(files),
        "cells": {f"{a}|{e}": int(n) for (a, e), n in cells.items()},
        "new_risk_per_day_median": float(dd.new_risk.median()),
        "unwind_per_day_median": float(dd.unwind.median()),
        "unwind_tenor_parsable": float(dd.unwind_with_tenor.sum() / max(1, dd.unwind.sum())),
        "u_share_median": float(dd.u_share.median()),
        "u_share_sd": float(dd.u_share.std(ddof=1)),
        "u_share_autocorr": {"lag1": ac[0], "lag5": ac[1], "lag10": ac[2], "lag21": ac[3]},
    }
    (OUT / "f8_composition_probe.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    dd.to_parquet(OUT / "f8_composition_daily.parquet", index=False)
    print("\nwrote f8_composition_probe.json + f8_composition_daily.parquet")


if __name__ == "__main__":
    main()
