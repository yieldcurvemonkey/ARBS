"""Audit SR3 settle coverage per (date, rank) before anything is backtested."""
import datetime
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fed_detachment_prices as P

START = datetime.date(2018, 5, 7)
END = datetime.date(2026, 8, 21)
MAX_RANK = 4

print("seed:", P.seed_local_cache(), flush=True)
print("local cache:", P.study_cache_dir(), flush=True)

fridays = pd.date_range(START, END, freq="W-FRI")
rmap = P.build_rank_map([d.date() for d in fridays], MAX_RANK)

needed_from = {}
for col in rmap.columns:
    for d, sym in rmap[col].items():
        if sym not in needed_from or d < needed_from[sym]:
            needed_from[sym] = d

syms = sorted(needed_from)
print(f"\n{len(syms)} contracts touched by ranks 1..{MAX_RANK} over {START}..{END}")

audit = P.gate_contract_history(syms, needed_from)
pd.set_option("display.width", 200)
print(audit.to_string(index=False))

bad = audit[~audit["ok"]]
print(f"\nSHORT: {len(bad)} of {len(audit)}")
if len(bad):
    print(sorted(bad["symbol"]))

# also: does any (date, rank) have no settle at all?
panel = P.settle_panel(syms)
px, _ = P.rank_price_frame(panel, fridays, MAX_RANK)
print("\nmissing weekly settles by rank (full 2018-2026 window):")
print(px.isna().sum().to_string())
jpm = px[px.index >= "2023-05-05"]
print("\nmissing weekly settles by rank (JPM window 2023-05->):")
print(jpm.isna().sum().to_string())
