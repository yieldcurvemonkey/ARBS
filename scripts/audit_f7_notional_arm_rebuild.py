"""AUDIT (verify claimed defect 'notional-arm'): rebuild the F7 package tape under
BOTH the as-built rule and the CORRECTED rule, on every dissemination file.

as-built  : filter legs (tenor bucket + spot) FIRST, then keep groups of size 2..3.
corrected : require the RAW execution-timestamp group to be 2..3 legs AND every raw
            leg to survive the filters (i.e. no demotion, no truncation).
superset  : ALSO admit >3-leg raw groups whose surviving bucketed spot legs number 2..3
            (this is a strictly MORE inclusive flow, to test the other direction).

Step 0 of the protocol: the as-built arm must reproduce the committed
f7_packages.parquet exactly, otherwise a delta means my probe drifted, not the fix.

Writes only to the scratchpad. Modifies nothing committed.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_package_extract as e  # noqa: E402

SCRATCH = pathlib.Path(
    r"C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS"
    r"\d0f44428-35f8-4f61-96a2-3a3318a94197\scratchpad")


def rows_for_day(raw: pd.DataFrame):
    """Return (as_built, corrected, superset) package row lists for one file."""
    ab, co, su = [], [], []
    if raw.empty:
        return ab, co, su
    passes = raw["_tenor"].notna() & raw["_spot"].fillna(False)
    d = raw.dropna(subset=["_ts"])
    for ts, g in d.groupby("_ts", sort=False):
        n_raw = len(g)
        gk = g[passes.reindex(g.index).fillna(False)]
        n_k = len(gk)
        if n_k < 2 or n_k > e.MAX_LEGS:
            continue
        tens = np.sort(gk["_tenor"].to_numpy())
        if len(np.unique(tens)) != n_k:
            continue
        rec = {
            "file_date": g["_file_date"].iloc[0],
            "exec_ts": ts,
            "n_legs": n_k,
            "signature": "-".join(str(int(t)) for t in tens),
            "notional_sum": float(np.nansum(gk["_notional"].to_numpy())),
            "notional_min": float(np.nanmin(gk["_notional"].to_numpy())),
            "capped_any": bool(gk["_capped"].any()),
            "block_any": bool(gk["_block"].any()),
        }
        ab.append(rec)                       # as-built publishes every such group
        if n_raw == n_k:                     # nothing was filtered away -> intact
            co.append(rec)
        if n_raw > e.MAX_LEGS:               # a genuine >3 group demoted into the window
            su.append(rec)
    return ab, co, su


def main() -> None:
    files = sorted(pathlib.Path(p) for p in
                   glob.glob(str(e.SDR_DIR / "*" / "*" / "*.parquet")))
    print(f"{len(files)} files: {files[0].stem} .. {files[-1].stem}", flush=True)
    AB, CO, SU = [], [], []
    t0 = time.time()
    for i, fp in enumerate(files):
        raw = e.load_day(fp)
        a, c, s = rows_for_day(raw)
        AB += a
        CO += c
        SU += s
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(files)} ({time.time()-t0:.0f}s)", flush=True)
    ab = pd.DataFrame(AB)
    co = pd.DataFrame(CO)
    su = pd.DataFrame(SU)
    print(f"as-built {len(ab):,}   corrected {len(co):,}   "
          f"(demoted {len(ab)-len(co):,} = {(len(ab)-len(co))/max(1,len(ab)):.2%})   "
          f"of which from raw>3 groups: {len(su):,}")

    # ---- STEP 0: does the as-built arm reproduce the committed tape? ----
    ref = pd.read_parquet(e.OUT / "f7_packages.parquet")
    ref["file_date"] = pd.to_datetime(ref["file_date"])
    ab["file_date"] = pd.to_datetime(ab["file_date"])
    a_cnt = ab.groupby(["file_date", "signature"]).size().rename("mine")
    r_cnt = ref.groupby(["file_date", "signature"]).size().rename("ref")
    j = pd.concat([a_cnt, r_cnt], axis=1).fillna(0)
    bad = j[j["mine"] != j["ref"]]
    print(f"\nSTEP 0 reproduction: {len(ref):,} committed rows vs {len(ab):,} mine; "
          f"file_date x signature cells disagreeing: {len(bad)}")
    if len(bad):
        print(bad.head(20).to_string())

    ab.to_parquet(SCRATCH / "f7_pkg_asbuilt.parquet", index=False)
    co.to_parquet(SCRATCH / "f7_pkg_corrected.parquet", index=False)
    print("written to scratchpad")


if __name__ == "__main__":
    main()
