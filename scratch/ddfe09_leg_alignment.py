"""Is `RepricedUnit.legs[i]` the same leg as `unit.legs.iloc[i]`?

`price_one_day` pairs them positionally:

    for i, leg in enumerate(out.legs):
        "other_payment_amount": _f(unit.legs["other_payment_amount"].iloc[i])

If that pairing is off by anything, a package's per-leg fee is matched to the
wrong leg's NPV, and `package_price.classify` then solves the sign vector
against a scrambled input -- producing a confident, wrong orientation with no
symptom at all. The persisted `plegs` frame carries `trade_id` per leg, so the
question is answerable from what is already on disk plus a rebuild of the
units.

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ddfe09_leg_alignment.py 2026-04-01
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
from SDRUtils.dealer_direction import universe as U  # noqa: E402

CACHE = pathlib.Path(r"D:\ddfe_cache")
DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-04-01"

plegs = pd.read_parquet(CACHE / "plegs" / f"{DAY}.parquet")
print(f"{DAY}: {len(plegs):,} priced leg rows, "
      f"{plegs['unit_key'].nunique():,} units")

conn = psycopg2.connect(resolve_pg_url())
legs = U.load_legs(conn, DAY, DAY)
conn.close()
units = {u.unit_key: u for u in U.build_universe(legs)[0]}
print(f"rebuilt {len(units):,} kept units")

checked = mismatch = multileg = 0
bad = []
for key, grp in plegs.groupby("unit_key", sort=False):
    unit = units.get(str(key))
    if unit is None:
        continue
    grp = grp.sort_values("leg_index")
    persisted = [str(t) for t in grp["trade_id"]]
    expected = [str(t) for t in unit.legs["trade_id"]]
    checked += 1
    if len(expected) > 1:
        multileg += 1
    if persisted != expected[:len(persisted)]:
        mismatch += 1
        if len(bad) < 5:
            bad.append((key, persisted, expected))

print(f"\nunits checked           {checked:,}")
print(f"  of which multi-leg    {multileg:,}")
print(f"positional mismatches   {mismatch:,}")
if bad:
    for key, p, e in bad:
        print(f"  {key}\n    priced-order  {p}\n    unit.legs     {e}")
    raise SystemExit(1)

# The check is only meaningful if it COULD have failed: a suite of one-leg
# units would pass a shuffled implementation too.
if multileg == 0:
    print("\nNO MULTI-LEG UNIT IN THE SAMPLE -- this run proves nothing.")
    raise SystemExit(2)
print(f"\nOK: every priced leg list matches unit.legs positionally, over "
      f"{multileg:,} multi-leg units where a shuffle would have shown.")
