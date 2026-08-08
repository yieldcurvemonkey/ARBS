"""F7 step 1: reconstruct USD spot curve PACKAGES from the local Part 43 cache.

Registered in H-F7. The two conventions that matter are fixed there and repeated
here so the code and the registration cannot drift apart:

  * aggregation is by FILE DATE (= dissemination date), never by execution
    timestamp -- L-0077 measured 8-30% of any file to be prints executed
    earlier, and a day-t flow variable built on execution timestamps would
    contain prints a live trader could not have seen by the day-t close.
  * the universe is action == NEWT and event == TRAD (the ECONOMIC_FLOW cell),
    verified against the file rather than trusted from an imported flag
    (L-0078).

A package is a set of NEWT+TRAD USD OIS legs sharing one execution timestamp
inside one dissemination file, with 2 or 3 legs, every leg spot-starting and
every leg bucketing to a standard tenor. Its SIGNATURE is the sorted tuple of
those tenors -- exact signatures, never families (the sibling FAILURE_LOG
records that family counts overstate exact-structure liquidity ~10x).

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 \
     scripts/s3_f7_package_extract.py [--days N]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import glob
import pathlib
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_REPO = pathlib.Path(__file__).resolve().parents[1]
SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")  # READ-ONLY
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

STD_TENORS = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50], dtype=float)
TENOR_TOL_D = 15.0           # a leg buckets if it is within 15 calendar days of a standard tenor
MAX_SPOT_LAG_D = 5           # effective date within a week of execution -> "spot starting"
MAX_LEGS = 3

_COLS = ["Action type", "Event type", "Execution Timestamp", "Effective Date",
         "Expiration Date", "Fixed rate-Leg 1", "Notional currency-Leg 1",
         "Notional amount-Leg 1", "Package indicator",
         "Block trade election indicator", "Cleared", "Platform identifier",
         "UPI FISN", "Product name"]


def log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _notional(s: pd.Series) -> pd.DataFrame:
    """Parse the notional string, flagging the CFTC cap marker ('1,100,000,000+')."""
    raw = s.astype(str).str.strip()
    capped = raw.str.endswith("+")
    val = pd.to_numeric(raw.str.replace(",", "", regex=False).str.rstrip("+"),
                        errors="coerce")
    return pd.DataFrame({"notional": val, "capped": capped})


def load_day(fp: pathlib.Path) -> pd.DataFrame:
    names = set(pq.read_schema(fp).names)
    want = [c for c in _COLS if c in names]
    df = pq.read_table(fp, columns=want).to_pandas()

    key = "UPI FISN" if "UPI FISN" in df.columns else "Product name"
    m = (df["Action type"].astype(str).eq("NEWT")
         & df["Event type"].astype(str).eq("TRAD")
         & df["Notional currency-Leg 1"].astype(str).eq("USD")
         & df[key].astype(str).str.contains("OIS", na=False))
    df = df.loc[m].copy()
    if df.empty:
        return df

    ts = pd.to_datetime(df["Execution Timestamp"], errors="coerce", utc=True)
    eff = pd.to_datetime(df["Effective Date"], errors="coerce")
    exp = pd.to_datetime(df["Expiration Date"], errors="coerce")

    years = (exp - eff).dt.days / 365.25
    # nearest standard tenor, accepted only inside the tolerance
    with np.errstate(invalid="ignore"):
        arr = years.to_numpy(dtype=float)
        idx = np.abs(arr[:, None] - STD_TENORS[None, :]).argmin(axis=1)
        near = STD_TENORS[idx]
        ok = np.abs((arr - near) * 365.25) <= TENOR_TOL_D
    df["_tenor"] = np.where(ok, near, np.nan)
    df["_years"] = years

    exec_d = ts.dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    df["_spot"] = (eff - exec_d).dt.days.between(-1, MAX_SPOT_LAG_D)
    df["_ts"] = ts
    df["_rate"] = pd.to_numeric(df["Fixed rate-Leg 1"], errors="coerce")
    nn = _notional(df["Notional amount-Leg 1"])
    df["_notional"] = nn["notional"].to_numpy()
    df["_capped"] = nn["capped"].to_numpy()
    df["_file_date"] = pd.Timestamp(fp.stem)
    df["_block"] = df.get("Block trade election indicator",
                          pd.Series(False, index=df.index)).astype(str).str.lower().eq("true")
    return df


def packages_for_day(df: pd.DataFrame) -> pd.DataFrame:
    """Group legs by execution timestamp; keep 2-3 leg spot standard-tenor sets."""
    if df.empty:
        return pd.DataFrame()
    d = df.dropna(subset=["_ts", "_tenor"])
    d = d[d["_spot"]]
    if d.empty:
        return pd.DataFrame()

    out = []
    for ts, g in d.groupby("_ts", sort=False):
        n = len(g)
        if n < 2 or n > MAX_LEGS:
            continue
        tens = np.sort(g["_tenor"].to_numpy())
        if len(np.unique(tens)) != n:          # two legs on the same tenor is not a curve trade
            continue
        out.append({
            "file_date": g["_file_date"].iloc[0],
            "exec_ts": ts,
            "n_legs": n,
            "signature": "-".join(str(int(t)) for t in tens),
            "notional_sum": float(np.nansum(g["_notional"].to_numpy())),
            "notional_min": float(np.nanmin(g["_notional"].to_numpy())),
            "capped_any": bool(g["_capped"].any()),
            "block_any": bool(g["_block"].any()),
            "rates": ",".join(f"{r:.6g}" for r in g.sort_values("_tenor")["_rate"]),
        })
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    files = sorted(pathlib.Path(p) for p in
                   glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    if args.days:
        files = files[-args.days:]
    log(f"{len(files)} dissemination files: {files[0].stem} .. {files[-1].stem}")

    parts, diag = [], []
    t0 = time.time()
    for i, fp in enumerate(files):
        try:
            raw = load_day(fp)
        except Exception as exc:                      # noqa: BLE001 - recorded, never swallowed
            log(f"  !! {fp.stem}: {type(exc).__name__}: {exc}")
            diag.append({"file_date": fp.stem, "error": f"{type(exc).__name__}: {exc}"})
            continue
        pk = packages_for_day(raw)
        parts.append(pk)
        diag.append({
            "file_date": fp.stem,
            "usd_ois_newt_trad": int(len(raw)),
            "bucketed": int(raw["_tenor"].notna().sum()) if len(raw) else 0,
            "spot": int(raw["_spot"].sum()) if len(raw) else 0,
            "packages": int(len(pk)),
            "error": "",
        })
        if (i + 1) % 100 == 0:
            log(f"  {i + 1}/{len(files)}  ({time.time() - t0:.0f}s)")

    pkg = pd.concat([p for p in parts if len(p)], ignore_index=True)
    dg = pd.DataFrame(diag)
    OUT.mkdir(parents=True, exist_ok=True)
    pkg.to_parquet(OUT / "f7_packages.parquet", index=False)
    dg.to_parquet(OUT / "f7_extract_diag.parquet", index=False)

    log(f"DONE in {time.time() - t0:.0f}s -> {len(pkg):,} packages over "
        f"{pkg['file_date'].nunique()} file-days")
    errs = dg[dg["error"].astype(bool)] if "error" in dg else dg.iloc[:0]
    log(f"files with errors: {len(errs)}")
    log(f"USD OIS NEWT+TRAD legs seen: {dg['usd_ois_newt_trad'].sum():,}; "
        f"bucketed to a standard tenor: {dg['bucketed'].sum():,} "
        f"({dg['bucketed'].sum() / max(1, dg['usd_ois_newt_trad'].sum()):.1%}); "
        f"spot-starting: {dg['spot'].sum():,}")

    print("\n=== top 25 exact signatures by package count ===")
    top = pkg.groupby(["n_legs", "signature"]).size().sort_values(ascending=False)
    print(top.head(25).to_string())


if __name__ == "__main__":
    sys.exit(main())
