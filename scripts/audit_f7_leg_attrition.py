"""AUDIT probe: does s3_f7_package_extract's leg filtering RESHAPE execution-timestamp
groups before the 2..3-leg window is applied?

packages_for_day() drops legs that fail the tenor-bucket or spot test FIRST, then keeps
groups of size 2..3. Two consequences that a flow signal would feel:

  (A) TRUNCATION - a genuine >3-leg group (or a 2/3-leg group with one unbucketable leg)
      is silently DEMOTED into the window and printed with a signature it never traded;
  (B) LOSS       - a genuine 2/3-leg group loses a leg and falls below 2, or stays above 3,
      and disappears from the flow entirely.

Both would add noise to / remove mass from the shock variable, i.e. bias toward NO effect.
This probe measures how big each is on a stratified sample of dissemination files.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/audit_f7_leg_attrition.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_package_extract as e  # noqa: E402

UNI = json.loads((e.OUT / "f7_universe.json").read_text())["universe"]


def main() -> None:
    files = sorted(pathlib.Path(p) for p in
                   glob.glob(str(e.SDR_DIR / "*" / "*" / "*.parquet")))
    files = files[::8]                       # stratified, every 8th day across the whole cache
    print(f"{len(files)} of {len(sorted(glob.glob(str(e.SDR_DIR / '*' / '*' / '*.parquet'))))} "
          f"files sampled: {files[0].stem} .. {files[-1].stem}")

    tot = dict(groups=0, raw2=0, raw3=0, raw_gt3=0,
               kept=0, kept_intact=0, kept_demoted=0,
               lost_below2=0, lost_still_gt3=0, lost_dupe_tenor=0)
    demoted_sig = {}
    kept_sig = {}
    t0 = time.time()
    for i, fp in enumerate(files):
        raw = e.load_day(fp)
        if raw.empty:
            continue
        keep = raw["_ts"].notna() & raw["_tenor"].notna() & raw["_spot"]
        for ts, g in raw.dropna(subset=["_ts"]).groupby("_ts", sort=False):
            n_raw = len(g)
            tot["groups"] += 1
            if n_raw == 2:
                tot["raw2"] += 1
            elif n_raw == 3:
                tot["raw3"] += 1
            elif n_raw > 3:
                tot["raw_gt3"] += 1
            gk = g[keep.reindex(g.index).fillna(False)]
            n_k = len(gk)
            if n_k < 2:
                if 2 <= n_raw <= e.MAX_LEGS:
                    tot["lost_below2"] += 1
                continue
            if n_k > e.MAX_LEGS:
                tot["lost_still_gt3"] += 1
                continue
            tens = np.sort(gk["_tenor"].to_numpy())
            if len(np.unique(tens)) != n_k:
                tot["lost_dupe_tenor"] += 1
                continue
            sig = "-".join(str(int(t)) for t in tens)
            tot["kept"] += 1
            kept_sig[sig] = kept_sig.get(sig, 0) + 1
            if n_k == n_raw:
                tot["kept_intact"] += 1
            else:
                tot["kept_demoted"] += 1
                demoted_sig[sig] = demoted_sig.get(sig, 0) + 1
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(files)} ({time.time()-t0:.0f}s)", flush=True)

    print("\n=== execution-timestamp group census (sampled files) ===")
    print(json.dumps(tot, indent=2))
    k = max(1, tot["kept"])
    print(f"\nPACKAGES PUBLISHED: {tot['kept']:,}")
    print(f"  intact  (every raw leg survived the filters): {tot['kept_intact']:,} "
          f"({tot['kept_intact']/k:.2%})")
    print(f"  DEMOTED (at least one raw leg was filtered away, so the printed signature "
          f"is NOT the traded structure): {tot['kept_demoted']:,} ({tot['kept_demoted']/k:.2%})")
    print(f"\nGROUPS LOST: below 2 legs after filtering {tot['lost_below2']:,}; "
          f"still >3 legs {tot['lost_still_gt3']:,}; duplicate tenor {tot['lost_dupe_tenor']:,}")

    print("\n=== demotion rate inside the 10-signature universe ===")
    rows = []
    for s in UNI:
        kk, dd = kept_sig.get(s, 0), demoted_sig.get(s, 0)
        rows.append({"signature": s, "packages": kk, "demoted": dd,
                     "demoted_frac": round(dd / kk, 3) if kk else np.nan})
    df = pd.DataFrame(rows).sort_values("demoted_frac", ascending=False)
    print(df.to_string(index=False))
    print(f"\nuniverse-wide demoted fraction: "
          f"{df['demoted'].sum() / max(1, df['packages'].sum()):.2%}")


if __name__ == "__main__":
    main()
