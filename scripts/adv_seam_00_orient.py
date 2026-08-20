r"""Independent orientation: what is actually in the Citi tag cache."""
from __future__ import annotations

import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

cache = CitiVeloTagCache()
print("cache base:", cache.base_dir)
for freq in sorted(p.name for p in cache.base_dir.iterdir() if p.is_dir()):
    d = cache.base_dir / freq
    for pp in sorted(x.name for x in d.iterdir() if x.is_dir()):
        files = list((d / pp).glob("RATES.BOND.*.parquet"))
        files = [f for f in files if not f.name.endswith(".meta.json")]
        print(f"  {freq}/{pp}: {len(files)} bond parquet files")

# MI01 bond YIELD coverage
mi = sorted((cache.base_dir / "MI01" / "CLOSE").glob("RATES.BOND.*.YIELD.parquet"))
print(f"\nMI01 bond YIELD tags: {len(mi)}")
rows = []
for p in mi[:400]:
    s = cache.read(p.stem, "MI01", "CLOSE")
    if s is None or s.empty:
        continue
    days = pd.Series(pd.DatetimeIndex(s.index).normalize().unique())
    rows.append({"tag": p.stem, "n": len(s), "ndays": len(days),
                 "first": s.index.min(), "last": s.index.max()})
df = pd.DataFrame(rows)
print(df[["n", "ndays"]].describe().to_string())
print("first min:", df["first"].min(), " last max:", df["last"].max())

# union of MI01 days
alldays = set()
for p in mi:
    s = cache.read(p.stem, "MI01", "CLOSE")
    if s is None or s.empty:
        continue
    alldays |= set(pd.DatetimeIndex(s.index).normalize().unique())
alldays = sorted(alldays)
print(f"\nMI01 union distinct days: {len(alldays)}  {alldays[0]} .. {alldays[-1]}")
pd.Series([pd.Timestamp(d) for d in alldays]).to_csv(
    ROOT / "notebooks/backtests/etf_rebalance/_data/adv_mi01_days.csv", index=False)
byyear = pd.Series([pd.Timestamp(d).year for d in alldays]).value_counts().sort_index()
print(byyear.to_string())
