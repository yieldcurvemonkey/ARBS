"""Why do 15 coverage legs on 2024-07-01 belong to a unit with no reason?

The guard in `publish_day` fired. Either the guard is wrong or the two frames
genuinely disagree; this says which, with the offending rows printed.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE = pathlib.Path(r"D:\ddfe_cache")
DAY = sys.argv[1] if len(sys.argv) > 1 else "2024-07-01"

units = pd.read_parquet(CACHE / "units" / f"{DAY}.parquet")
cov = pd.read_parquet(CACHE / "covlegs" / f"{DAY}.parquet")

uk_units = units["unit_key"].astype(str)
uk_cov = cov["unit_key"].astype(str)

print(f"{DAY}: units {len(units):,}  unique unit_key {uk_units.nunique():,}")
print(f"        coverage rows {len(cov):,}  unique unit_key {uk_cov.nunique():,}")

dupes = uk_units[uk_units.duplicated(keep=False)]
print(f"duplicate unit_key in units: {dupes.nunique()} keys, {len(dupes)} rows")
if len(dupes):
    print(units[uk_units.isin(dupes)][
        ["unit_key", "package_id", "kind", "n_legs", "universe_exclusion"]
    ].head(20).to_string(index=False))

orphans = sorted(set(uk_cov) - set(uk_units))
print(f"\ncoverage unit_keys NOT in units: {len(orphans)}")
for o in orphans[:10]:
    print(f"  {o!r}")
    print(cov[uk_cov == o].to_string(index=False))

# Is it a dtype/whitespace artefact or a genuinely absent unit?
if orphans:
    stripped = {u.strip() for u in uk_units}
    print("\nafter strip(), still missing:",
          len([o for o in orphans if o.strip() not in stripped]))
    print("as float-formatted:",
          len([o for o in orphans if o.replace(".0", "") in set(uk_units)]))

# And the reverse: units with no coverage legs at all.
missing_cov = sorted(set(uk_units) - set(uk_cov))
print(f"\nunits with NO coverage leg: {len(missing_cov)}")
if missing_cov:
    print(units[uk_units.isin(missing_cov[:10])][
        ["unit_key", "package_id", "kind", "n_legs", "rate_index",
         "universe_exclusion", "dv01_proxy"]
    ].head(10).to_string(index=False))
