"""AUDIT (refute-probe) 4: package-level prevalence of OPTION legs admitted by the
'OIS' substring filter (s3_f7_package_extract.py:75). Legs are only 0.52% options,
but options print multi-leg at one timestamp, so they may be over-represented in
PACKAGES -- which is what the flow variable counts."""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_package_extract as ex  # noqa: E402

pd.set_option("display.width", 250)
SDR_DIR = ex.SDR_DIR

files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
files = [f for f in files if "2023-12-01" <= f.stem <= "2026-07-21"]
step = max(1, len(files) // 60)
samp = files[::step]
print(f"{len(files)} files in window; sampling {len(samp)}")

UNI = ["10-30", "2-10", "2-30", "5-10", "5-30",
       "10-15-30", "10-20-30", "2-5-10", "5-10-30", "5-7-10"]

rows = []
for fp in samp:
    raw = ex.load_day(fp)
    if not len(raw):
        continue
    key = "UPI FISN" if "UPI FISN" in raw.columns else "Product name"
    raw = raw.copy()
    raw["_opt"] = raw[key].astype(str).str.contains("Opt|Call|P Epn|P Brm|Nstd", na=False)
    d = raw.dropna(subset=["_ts", "_tenor"])
    d = d[d["_spot"]]
    n_pkg = n_pkg_opt = n_pkg_uni = n_pkg_uni_opt = 0
    for ts, gg in d.groupby("_ts", sort=False):
        n = len(gg)
        if n < 2 or n > ex.MAX_LEGS:
            continue
        tens = np.sort(gg["_tenor"].to_numpy())
        if len(np.unique(tens)) != n:
            continue
        sig = "-".join(str(int(t)) for t in tens)
        isopt = bool(gg["_opt"].any())
        n_pkg += 1
        n_pkg_opt += isopt
        if sig in UNI:
            n_pkg_uni += 1
            n_pkg_uni_opt += isopt
    rows.append({"file_date": fp.stem, "pkgs": n_pkg, "pkgs_opt": n_pkg_opt,
                 "pkgs_uni": n_pkg_uni, "pkgs_uni_opt": n_pkg_uni_opt})

t = pd.DataFrame(rows)
print(t.to_string(index=False))
print(f"\nTOTAL over {len(t)} sampled days:")
print(f"  packages                      : {t['pkgs'].sum():,}")
print(f"  packages containing an OPTION : {t['pkgs_opt'].sum():,} "
      f"= {t['pkgs_opt'].sum()/max(1,t['pkgs'].sum()):.3%}")
print(f"  packages in the F7 UNIVERSE   : {t['pkgs_uni'].sum():,}")
print(f"  universe pkgs with an OPTION  : {t['pkgs_uni_opt'].sum():,} "
      f"= {t['pkgs_uni_opt'].sum()/max(1,t['pkgs_uni'].sum()):.3%}")
