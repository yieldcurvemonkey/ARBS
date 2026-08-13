"""The frames agree on unit_key, so the null must be in the reason VALUE.

`ddfe04` showed 2,364 unit_keys on both sides and zero orphans either way, so
`.map()` is not missing a key -- it is mapping to a NaN. Find which units and
which branch produced it.
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

print("dtypes of the fields the reason ladder reads:")
for c in ("universe_exclusion", "rule", "failure", "pkg_exclusion"):
    s = units[c]
    n_none = int(s.isna().sum())
    kinds = {type(v).__name__ for v in s.head(400)}
    print(f"  {c:24s} dtype={s.dtype}  isna={n_none:5d}  py-types={kinds}")

print("\nwhat to_dict('records') actually hands back:")
recs = units.to_dict("records")
for c in ("universe_exclusion", "rule", "failure"):
    vals = [r[c] for r in recs]
    nones = sum(1 for v in vals if v is None)
    nans = sum(1 for v in vals if isinstance(v, float))
    print(f"  {c:24s} None={nones:5d}  float(nan)={nans:5d}")

# Replicate the ladder in publish_day exactly.
from SDRUtils.dealer_direction import types as T  # noqa: E402

bad = []
for r in recs:
    ex = None
    branch = None
    if r.get("universe_exclusion"):
        ex, branch = r["universe_exclusion"], "universe"
    elif r.get("rule") is None:
        ex, branch = (r.get("failure") or T.EXCL_UNORIENTABLE), "no-rule"
    elif r.get("failure") is not None:
        ex, branch = r["failure"], "failure"
    reason = ex or "IN_LADDER"
    if not isinstance(reason, str):
        bad.append((r["unit_key"], branch, repr(ex), repr(r.get("rule")),
                    repr(r.get("failure")), repr(r.get("universe_exclusion"))))

print(f"\nnon-string reasons: {len(bad)}")
for b in bad[:20]:
    print("  key=%s branch=%s ex=%s rule=%s failure=%s uex=%s" % b)
