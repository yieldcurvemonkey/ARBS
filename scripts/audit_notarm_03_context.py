"""AUDIT (refute-probe) 3: (a) verify the claim's quoted 5-10 h=21 notional cell,
(b) quantify what the offending row actually is -- a SWAPTION admitted by the 'OIS'
substring filter -- and how prevalent that is across the tape."""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_gate as g  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
OUT = g.OUT
SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")

# ---- (a) the claim's quoted cell -------------------------------------------
par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))

sig = "5-10"
x = g.structure_series(par, sig).reindex(common).dropna()
sub = pkg[pkg["signature"] == sig]
flow = sub.groupby("file_date")["notional_sum"].sum().reindex(x.index, fill_value=0).astype(float)
z = g.zscore(x, g.Z_WIN)
shock = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
persistent = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) & (z.shift(1).abs() >= g.Z_ENTRY)
for h in (21,):
    a = g.episodes(x, z, persistent & shock, h)
    b = g.episodes(x, z, persistent & ~shock, h)
    incr = round(float(a["gross_bp"].median()) - float(b["gross_bp"].median()), 3)
    print(f"(a) 5-10 NOTIONAL arm h={h}: n_shock={len(a)}  n_noshock={len(b)}  "
          f"incr_vs_noshock={incr:+.3f}bp   [claim said -0.103bp with 12 episodes]")

# ---- (b) what IS that row? --------------------------------------------------
fp = SDR_DIR / "2024" / "08" / "2024-08-05.parquet"
df = pq.read_table(fp, columns=["Action type", "Event type", "Execution Timestamp",
                                "Notional currency-Leg 1", "Notional amount-Leg 1",
                                "UPI FISN"]).to_pandas()
m = (df["Action type"].astype(str).eq("NEWT") & df["Event type"].astype(str).eq("TRAD")
     & df["Notional currency-Leg 1"].astype(str).eq("USD")
     & df["UPI FISN"].astype(str).str.contains("OIS", na=False))
sel = df.loc[m]
print(f"\n(b) 2024-08-05: legs admitted by the F7 filter = {len(sel):,}")
vc = sel["UPI FISN"].value_counts()
print(vc.to_string())
opt = sel["UPI FISN"].astype(str).str.contains("Opt", na=False)
print(f"    of which OPTION (FISN contains 'Opt'): {int(opt.sum())} = {opt.mean():.4%}")

# negatives among admitted legs, that one day
raw = sel["Notional amount-Leg 1"].astype(str).str.strip()
negleg = raw.str.startswith("-")
print(f"    admitted legs with a NEGATIVE notional string: {int(negleg.sum())}")
print(f"    of those, FISN contains 'Opt': "
      f"{int((negleg & opt).sum())} / {int(negleg.sum())}")

# ---- (c) prevalence across a sample of days --------------------------------
files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
files = [f for f in files if "2023-12" <= f.stem <= "2026-07-21"]
step = max(1, len(files) // 40)
samp = files[::step]
tot_legs = tot_opt = tot_neg = tot_neg_opt = 0
for fp in samp:
    names = set(pq.read_schema(fp).names)
    if "UPI FISN" not in names:
        continue
    d = pq.read_table(fp, columns=["Action type", "Event type", "Notional currency-Leg 1",
                                   "Notional amount-Leg 1", "UPI FISN"]).to_pandas()
    mm = (d["Action type"].astype(str).eq("NEWT") & d["Event type"].astype(str).eq("TRAD")
          & d["Notional currency-Leg 1"].astype(str).eq("USD")
          & d["UPI FISN"].astype(str).str.contains("OIS", na=False))
    s = d.loc[mm]
    o = s["UPI FISN"].astype(str).str.contains("Opt", na=False)
    n = s["Notional amount-Leg 1"].astype(str).str.strip().str.startswith("-")
    tot_legs += len(s); tot_opt += int(o.sum()); tot_neg += int(n.sum())
    tot_neg_opt += int((n & o).sum())
print(f"\n(c) across {len(samp)} sampled dissemination days:")
print(f"    admitted USD-OIS NEWT+TRAD legs : {tot_legs:,}")
print(f"    of which FISN contains 'Opt'    : {tot_opt:,} = {tot_opt/max(1,tot_legs):.4%}")
print(f"    with a negative notional string : {tot_neg:,} = {tot_neg/max(1,tot_legs):.4%}")
print(f"    negative AND option             : {tot_neg_opt:,}")
