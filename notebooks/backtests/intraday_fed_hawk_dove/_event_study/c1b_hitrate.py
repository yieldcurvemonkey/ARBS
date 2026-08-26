"""Distribution-robust read of the same paths.

The mean is the tradeable quantity, but with a handful of macro-contaminated
five-hour windows in the book (Barkin 2025-04-09 alone is +29.5bp) the mean's
standard error is set by the tails.  The hit rate and the median say whether
there is a systematic DIRECTION underneath, independent of those tails.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd

from c_common import HERE, OFFSETS, cluster_mean_se, load_rank3, wide

SHOW = [-60, -30, -5, 0, 5, 15, 30, 60, 120, 240, 300]


def block(piv, meta, tag):
    s = meta["stance_sign"].to_numpy()
    day = meta["date"].to_numpy()
    rows = []
    for o in SHOW:
        v = piv[o].to_numpy() * s
        ok = np.isfinite(v)
        vv, dd = v[ok], day[ok]
        moved = vv != 0
        hit = (vv[moved] > 0).astype(float)
        h = cluster_mean_se(hit, dd[moved])
        # a coin-flip null: t on (hit - 0.5), day-clustered
        t50 = (h["mean"] - 0.5) / h["se"] if h["se"] and h["se"] > 0 else np.nan
        m = cluster_mean_se(vv, dd)
        rows.append(dict(offset=o, n=int(ok.sum()), n_moved=int(moved.sum()),
                         hit_rate=h["mean"], hit_se=h["se"], t_vs_50=t50,
                         median_bp=float(np.median(vv)),
                         mean_bp=m["mean"], mean_t=m["t"],
                         trim10_bp=float(pd.Series(vv).clip(
                             *np.percentile(vv, [5, 95])).mean())))
    df = pd.DataFrame(rows).set_index("offset")
    print("=" * 92)
    print(tag)
    print(df.to_string(float_format=lambda x: f"{x:9.4f}"))
    return df


def main():
    ev, pl = load_rank3()
    out = {}
    for key, d in (("nonoverlap", ev[~ev["is_overlapping"]]), ("all", ev), ("placebo", pl)):
        piv, meta = wide(d)
        out[key] = block(piv, meta, key).to_dict(orient="index")
    (HERE / "c1b_hitrate.json").write_text(
        json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("\nwrote c1b_hitrate.json")


if __name__ == "__main__":
    main()
