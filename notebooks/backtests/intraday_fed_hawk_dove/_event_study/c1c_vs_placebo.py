"""Two numbers the null headline will be challenged on.

(1) Pooled real-vs-placebo: signed_d_bp ~ 1 + is_real, day-clustered.  This is the
    single cleanest "against the null" statistic - it uses the placebo as a control
    group rather than as a backdrop.
(2) The same signed mean/t at +30 and +240 for ALL FIVE contract ranks, because the
    first objection to a rank-3 null is "maybe it lives in a different contract".
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

from c_common import HERE, OFFSETS, cluster_mean_se, cluster_ols, wide

ev_all = pd.read_parquet(HERE / "event_paths.parquet")
pl_all = pd.read_parquet(HERE / "placebo_paths.parquet")

res = {"real_vs_placebo": {}, "by_rank": {}}

print("=" * 88)
print("REAL vs PLACEBO  -  signed_d_bp ~ 1 + is_real, SE clustered by day, rank 3")
print("  (real book = non-overlapping signed; placebo = all signed pseudo-events)")
for book, evsub in (("nonoverlap", ev_all[(ev_all["contract_rank"] == 3) & (~ev_all["is_overlapping"])]),
                    ("all", ev_all[ev_all["contract_rank"] == 3])):
    pr, mr = wide(evsub)
    pp, mp = wide(pl_all[pl_all["contract_rank"] == 3])
    res["real_vs_placebo"][book] = {}
    print(f"  --- real book: {book} (n={len(mr)}) vs placebo (n={len(mp)})")
    for o in (0, 5, 15, 30, 60, 120, 240, 300):
        yr = pr[o].to_numpy() * mr["stance_sign"].to_numpy()
        yp = pp[o].to_numpy() * mp["stance_sign"].to_numpy()
        y = np.concatenate([yr, yp])
        real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
        day = np.concatenate([mr["date"].astype(str).to_numpy(), mp["date"].astype(str).to_numpy()])
        ok = np.isfinite(y)
        X = np.column_stack([np.ones(ok.sum()), real[ok]])
        r = cluster_ols(y[ok], X, day[ok], names=["const", "is_real"])
        res["real_vs_placebo"][book][str(o)] = dict(
            excess_bp=r["is_real"]["coef"], se=r["is_real"]["se"], t=r["is_real"]["t"],
            n=r["n"], n_days=r["n_clusters"])
        print(f"     +{o:>4}m  real - placebo = {r['is_real']['coef']:+.4f} bp "
              f"(SE {r['is_real']['se']:.4f}, t={r['is_real']['t']:+.2f}, "
              f"n={r['n']}, {r['n_clusters']} days)")

print()
print("=" * 88)
print("BY CONTRACT RANK  -  signed mean (bp) and day-clustered t, non-overlapping signed book")
rows = []
for rk in sorted(ev_all["contract_rank"].unique()):
    p, m = wide(ev_all[(ev_all["contract_rank"] == rk) & (~ev_all["is_overlapping"])])
    rec = {"rank": int(rk), "n_events": int(len(m))}
    for o in (5, 30, 240):
        v = p[o].to_numpy() * m["stance_sign"].to_numpy()
        s = cluster_mean_se(v, m["date"].to_numpy())
        rec[f"mean_{o}"] = s["mean"]
        rec[f"t_{o}"] = s["t"]
        rec[f"n_{o}"] = s["n"]
    rows.append(rec)
tab = pd.DataFrame(rows).set_index("rank")
print(tab.to_string(float_format=lambda x: f"{x:8.4f}"))
res["by_rank"] = tab.to_dict(orient="index")

# a bare-hands cross-check of one cell, computed a different way, so the wide()
# pivot path cannot be silently wrong
chk = ev_all[(ev_all["contract_rank"] == 3) & (~ev_all["is_overlapping"]) &
             (ev_all["offset_min"] == 240) & (ev_all["stance_sign"] != 0)]
print(f"\ncross-check rank 3 @ +240 straight from the long panel: "
      f"mean signed {chk['signed_d_bp'].mean():+.6f} bp on n={chk['signed_d_bp'].notna().sum()} "
      f"| pivot path said {tab.loc[3, 'mean_240']:+.6f} on n={int(tab.loc[3, 'n_240'])}")

# minimum detectable effect at the headline cell
se240 = tab.loc[3, "mean_240"] / tab.loc[3, "t_240"]
res["mde"] = dict(offset=240, rank=3, book="nonoverlap",
                  mean_bp=float(tab.loc[3, "mean_240"]), se_bp=float(se240),
                  ci95_lo=float(tab.loc[3, "mean_240"] - 1.96 * se240),
                  ci95_hi=float(tab.loc[3, "mean_240"] + 1.96 * se240),
                  mde80_bp=float(2.802 * se240), n=int(tab.loc[3, "n_240"]))
print(f"\nMDE at rank 3 / +240 / non-overlapping: mean {res['mde']['mean_bp']:+.3f} bp, "
      f"SE {se240:.3f}, 95% CI [{res['mde']['ci95_lo']:+.3f}, {res['mde']['ci95_hi']:+.3f}] bp; "
      f"smallest effect this n could detect at 80% power = {res['mde']['mde80_bp']:.2f} bp")

(HERE / "c1c_vs_placebo.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
print("\nwrote c1c_vs_placebo.json")
