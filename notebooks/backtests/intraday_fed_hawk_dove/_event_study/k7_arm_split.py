"""Arm split of the release-contamination result, and the pre-leg by book.

Two loose ends before the verdict:
  (1) Is the contaminated-window effect a hawk story, a dove story, or both?
      If only the hawk arm moves, 'release contamination' and 'the hiking-cycle
      trend' are the same object seen twice.
  (2) The findings' 'pre-event drift is flat' clause is established on the
      224-event non-overlapping book.  Print the signed PRE leg [-60 -> 0] for
      BOTH books so the claim can be checked where the quoted numbers live.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(str(HERE))

from c_common import cluster_mean_se  # noqa: E402
from k1_release_window import load_calendar, flag_windows  # noqa: E402

pd.set_option("display.width", 250)


def main():
    cal_all, rel = load_calendar()
    CAL_END = cal_all["release_ts_ny"].max()
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    res = {}

    for rank in (1, 3):
        e = ev[ev["contract_rank"] == rank]
        meta = e.drop_duplicates("event_id").set_index("event_id").copy()
        yv = {o: e[e["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"]
              .reindex(meta.index) for o in (0, 30, 240)}
        base = ((meta["stance_sign"] != 0) & (meta["speech_ts"] <= CAL_END)).to_numpy()
        mb = meta[base]
        sgn = mb["stance_sign"].to_numpy().astype(float)
        clus = mb["date"].to_numpy()
        v = yv[240][base].to_numpy()
        f, _ = flag_windows(mb, rel_hm, -60, 240)

        print("\n" + "=" * 96)
        print(f"RANK {rank}  --  +240, ARM SPLIT of the release-contamination result")
        print("=" * 96)
        print("  arm      subset        n   mean d_rate (RAW, not signed)      signed contribution")
        for arm, s in (("HAWK", 1.0), ("DOVE", -1.0)):
            for nm, m in (("clean ", (sgn == s) & ~f), ("contam", (sgn == s) & f)):
                r_raw = cluster_mean_se(v[m], clus[m])
                r_sig = cluster_mean_se(v[m] * s, clus[m])
                print(f"  {arm:<8s} {nm}  {r_raw['n']:>4d}   "
                      f"{r_raw['mean']:+7.4f} bp (t {r_raw['t']:+5.2f})        "
                      f"{r_sig['mean']:+7.4f} bp (t {r_sig['t']:+5.2f})")
                res[f"r{rank}_{arm}_{nm.strip()}"] = dict(raw=r_raw, signed=r_sig)

        print("\n" + "-" * 96)
        print(f"RANK {rank}  --  signed PRE leg [-60 -> 0], which CANNOT be a speech response")
        print("-" * 96)
        v0 = yv[0][base].to_numpy()
        for bnm, bm in (("ALL SIGNED (where the +0.20/+0.24 bp composites are quoted)",
                         np.ones(len(mb), bool)),
                        ("NON-OVERLAPPING SIGNED (where 'the pre-drift is flat' is established)",
                         (~mb["is_overlapping"]).to_numpy())):
            r = cluster_mean_se(v0[bm] * sgn[bm], clus[bm])
            r30 = cluster_mean_se(yv[30][base].to_numpy()[bm] * sgn[bm], clus[bm])
            r240 = cluster_mean_se(v[bm] * sgn[bm], clus[bm])
            print(f"  {bnm}")
            print(f"    PRE  [-60->0]  {r['mean']:+7.4f} bp (t {r['t']:+5.2f}, n {r['n']})")
            print(f"    +30  [-60->+30] {r30['mean']:+7.4f} bp (t {r30['t']:+5.2f}, n {r30['n']})"
                  f"   pre is {100 * r['mean'] / r30['mean'] if r30['mean'] else float('nan'):.0f}% of it")
            print(f"    +240 [-60->+240] {r240['mean']:+7.4f} bp (t {r240['t']:+5.2f}, n {r240['n']})"
                  f"  pre is {100 * r['mean'] / r240['mean'] if r240['mean'] else float('nan'):.0f}% of it")
            res[f"r{rank}_pre_{bnm[:20]}"] = dict(pre=r, o30=r30, o240=r240)

    with open(HERE / "k7_arm_split.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
