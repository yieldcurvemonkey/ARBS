"""Does COMPRESSION actually appear on the Part 43 public tape?

L-0072 imported from pfin/SwapPulse's economic_classification.py that ('*','COMP')
carries on_p43 = False -- compression excluded from Part 43 by 43.2 -- and used
that to STRIKE compression as an explanation for CM-2's mid-peak. The local tape
shows 3,460 COMP event rows on a single file, which contradicts it. Resolve
precisely: are there NEWT+COMP USD rows, and do they carry fixed rates?

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_comp_check.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib

import pandas as pd
import pyarrow.parquet as pq

SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")  # READ-ONLY
COLS = ["Action type", "Event type", "Notional currency-Leg 1",
        "Fixed rate-Leg 1", "Notional amount-Leg 1", "UPI FISN", "Product name",
        "Cleared", "Package indicator"]


def main() -> None:
    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    # ten files spread across the history
    picks = [files[i] for i in range(0, len(files), max(1, len(files) // 10))][:10]
    rows = []
    for fp in picks:
        names = set(pq.read_schema(fp).names)
        want = [c for c in COLS if c in names]
        df = pq.read_table(fp, columns=want).to_pandas()
        usd = df[df["Notional currency-Leg 1"].astype(str) == "USD"]
        key = "UPI FISN" if "UPI FISN" in usd.columns else "Product name"
        ois = usd[usd[key].astype(str).str.contains("OIS", na=False)]
        ct = (ois.assign(a=ois["Action type"].astype(str), e=ois["Event type"].astype(str))
                 .groupby(["a", "e"]).size())
        newt_comp = int(ct.get(("NEWT", "COMP"), 0))
        newt_trad = int(ct.get(("NEWT", "TRAD"), 0))
        any_comp = int(ois["Event type"].astype(str).eq("COMP").sum())
        # do NEWT+COMP rows carry a usable fixed rate?
        nc = ois[(ois["Action type"].astype(str) == "NEWT")
                 & (ois["Event type"].astype(str) == "COMP")]
        with_rate = int(pd.to_numeric(nc.get("Fixed rate-Leg 1"), errors="coerce").notna().sum()) \
            if len(nc) else 0
        rows.append(dict(file=fp.stem, usd_ois=len(ois), newt_trad=newt_trad,
                         newt_comp=newt_comp, any_comp=any_comp,
                         newt_comp_with_rate=with_rate))
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    print()
    print(f"TOTAL over {len(picks)} sampled days: USD-OIS rows {out.usd_ois.sum():,}  "
          f"NEWT+TRAD {out.newt_trad.sum():,}  NEWT+COMP {out.newt_comp.sum():,}  "
          f"any COMP {out.any_comp.sum():,}  NEWT+COMP carrying a fixed rate "
          f"{out.newt_comp_with_rate.sum():,}")
    verdict = ("COMPRESSION IS PRESENT on the Part 43 tape -- L-0072's on_p43=False import "
               "does not describe this data") if out.newt_comp.sum() > 0 else \
              ("no NEWT+COMP USD-OIS rows found -- L-0072's import is consistent with this data")
    print("VERDICT:", verdict)


if __name__ == "__main__":
    main()
