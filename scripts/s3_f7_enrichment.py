"""Which reconstructed signatures are REAL packages and which are same-second coincidence?

L-0081 bounded collisions in aggregate at 58.2% and that aggregate hides the thing
that matters: the shuffle preserves the group-SIZE distribution exactly (it permutes
which legs sit in each second, not how many), so the only thing it destroys is the
tenor COMPOSITION of a group. A signature whose as-built count barely exceeds -- or
falls below -- its shuffled null is not a traded structure at all; it is two common
tenors colliding in a busy second.

ENRICHMENT = as_built / mean(shuffled). Reported per signature over N draws, with
the null's own sd so the margin is readable rather than asserted.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_f7_enrichment.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib

import numpy as np
import pandas as pd

from s3_f7_collision_check import CANON, group, legs_for_day  # same conventions, one source

_REPO = pathlib.Path(__file__).resolve().parents[1]
SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")  # READ-ONLY
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
N_DRAWS = 20
SEED = 20260809


def main() -> None:
    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    picks = [files[i] for i in range(0, len(files), max(1, len(files) // 60))][:60]
    rng = np.random.default_rng(SEED)

    real_parts, null_parts = [], [[] for _ in range(N_DRAWS)]
    for fp in picks:
        d = legs_for_day(fp)
        if d.empty:
            continue
        real_parts.append(group(d, require_flag=False))
        for k in range(N_DRAWS):
            sh = d.copy()
            sh["_ts"] = rng.permutation(sh["_ts"].to_numpy())
            null_parts[k].append(group(sh, require_flag=False))

    def agg(parts):
        return pd.concat(parts).groupby(level=0).sum() if parts else pd.Series(dtype=int)

    real = agg(real_parts)
    nulls = pd.DataFrame({k: agg(p) for k, p in enumerate(null_parts)}).fillna(0)
    canon = [s for s in real.index if all(int(t) in CANON for t in s.split("-"))]

    tab = pd.DataFrame({
        "n_legs": [len(s.split("-")) for s in canon],
        "as_built": real.reindex(canon).fillna(0).astype(int),
        "null_mean": nulls.reindex(canon).fillna(0).mean(axis=1).round(1),
        "null_sd": nulls.reindex(canon).fillna(0).std(axis=1, ddof=1).round(1),
    }, index=canon)
    tab["enrichment"] = (tab["as_built"] / tab["null_mean"].clip(lower=0.5)).round(2)
    tab["z_vs_null"] = ((tab["as_built"] - tab["null_mean"]) /
                        tab["null_sd"].clip(lower=1.0)).round(1)
    tab = tab.sort_values("as_built", ascending=False)

    print(f"=== {len(picks)} sampled days, {N_DRAWS} shuffle draws ===")
    print(tab.to_string())

    real_sigs = tab[(tab["enrichment"] > 1.0) & (tab["z_vs_null"] >= 3.0)]
    print(f"\nsignatures with as_built > chance (enrichment > 1 AND z >= 3): "
          f"{len(real_sigs)} of {len(tab)}")
    print(f"  2-leg: {int((real_sigs['n_legs'] == 2).sum())} of "
          f"{int((tab['n_legs'] == 2).sum())}   "
          f"3-leg: {int((real_sigs['n_legs'] == 3).sum())} of "
          f"{int((tab['n_legs'] == 3).sum())}")
    print(f"  passing list: {real_sigs.index.tolist()}")

    tab.reset_index().rename(columns={"index": "signature"}).to_parquet(
        OUT / "f7_enrichment.parquet", index=False)
    (OUT / "f7_enrichment.json").write_text(json.dumps({
        "sampled_days": len(picks), "draws": N_DRAWS,
        "passing": real_sigs.index.tolist(),
        "n_2leg_pass": int((real_sigs["n_legs"] == 2).sum()),
        "n_3leg_pass": int((real_sigs["n_legs"] == 3).sum()),
        "table": tab.reset_index().rename(columns={"index": "signature"}).to_dict("records"),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
