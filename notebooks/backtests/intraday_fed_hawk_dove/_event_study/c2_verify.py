"""
Known-answer + mutation tests for the chart-2 bootstrap machinery, and the
cross-reference reconstruction of the existing book's entry -45 / exit +180 convention.
"""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np
import pandas as pd

BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
sys.path.append(BASE)
import c2_strip as C

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 100)

FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    if not ok:
        FAIL.append(name)


print("=" * 120)
print("TEST 1 -- point estimates from the matrix machinery vs an independent pandas groupby")
print("=" * 120)
books = C.load("main")
days_r, Sr, Nr = C.build_cells(books["real"])
pt = C.stats_from_weights(np.ones((1, len(days_r))), Sr, Nr)
for off in (30, 240):
    d = books["real"][books["real"].offset_min == off]
    ref_pool = d.groupby("contract_rank")["signed_d_bp"].mean().reindex(C.RANKS).to_numpy()
    ref_h = d[d.stance_sign > 0].groupby("contract_rank")["signed_d_bp"].mean().reindex(C.RANKS).to_numpy()
    ref_d = d[d.stance_sign < 0].groupby("contract_rank")["signed_d_bp"].mean().reindex(C.RANKS).to_numpy()
    check(f"pooled mean matches groupby (+{off})",
          np.allclose(pt[("pool", off)][0], ref_pool), f"max diff {np.abs(pt[('pool',off)][0]-ref_pool).max():.2e}")
    check(f"hawk mean matches groupby (+{off})", np.allclose(pt[("h", off)][0], ref_h))
    check(f"dove mean matches groupby (+{off})", np.allclose(pt[("d", off)][0], ref_d))
    check(f"counts match (+{off})",
          int(pt[("nh", off)][0].sum() + pt[("nd", off)][0].sum()) == len(d),
          f"{int(pt[('nh',off)][0].sum()+pt[('nd',off)][0].sum())} vs {len(d)}")

print()
print("=" * 120)
print("TEST 2 -- KNOWN ANSWER: constant data. Every signed_d_bp := 7.0 => mean 7.0, bootstrap CI degenerate")
print("=" * 120)
b2 = {k: v.copy() for k, v in books.items()}
b2["real"]["signed_d_bp"] = 7.0
d2, S2, N2 = C.build_cells(b2["real"])
rng = np.random.default_rng(1)
W = rng.multinomial(len(d2), np.full(len(d2), 1.0 / len(d2)), size=500).astype(float)
bs = C.stats_from_weights(W, S2, N2)
m = bs[("pool", 240)]
check("constant data -> every bootstrap mean is exactly 7.0",
      np.allclose(np.nanmin(m), 7.0) and np.allclose(np.nanmax(m), 7.0),
      f"min {np.nanmin(m):.6f} max {np.nanmax(m):.6f}")

print()
print("=" * 120)
print("TEST 3 -- KNOWN ANSWER: perfectly day-clustered data. signed_d_bp := +10 on odd days, -10 on even.")
print("  The estimator is a size-WEIGHTED ratio sum(s_d)/sum(n_d), so the correct closed-form reference")
print("  is the linearised cluster-robust SE, NOT the equal-weight SE of the day means (resampling days")
print("  perturbs the weights too) and NOT the iid SE over events. See c2_verify3.py for the full")
print("  three-way check including the discriminating equal-day-size case.")
print("=" * 120)
b3 = {k: v.copy() for k, v in books.items()}
r3 = b3["real"]
dayidx = {v: i for i, v in enumerate(sorted(r3["date"].unique()))}
r3["signed_d_bp"] = r3["date"].map(dayidx).map(lambda i: 10.0 if i % 2 else -10.0)
d3, S3, N3 = C.build_cells(r3)
rng = np.random.default_rng(2)
W = rng.multinomial(len(d3), np.full(len(d3), 1.0 / len(d3)), size=20000).astype(float)
bs = C.stats_from_weights(W, S3, N3)
boot_sd = np.nanstd(bs[("pool", 240)][:, 2])
sub = r3[(r3.offset_min == 240) & (r3.contract_rank == 3)]
n_ev = len(sub)
iid_se = sub["signed_d_bp"].std(ddof=1) / np.sqrt(n_ev)
dm = sub.groupby("date")["signed_d_bp"].mean()
eqw_se = dm.std(ddof=1) / np.sqrt(len(dm))
s_ = S3[("h", 240)][:, 2] + S3[("d", 240)][:, 2]
n_ = N3[("h", 240)][:, 2] + N3[("d", 240)][:, 2]
k_ = n_ > 0
D_ = int(k_.sum())
y_ = s_[k_].sum() / n_[k_].sum()
clust_se = np.sqrt(D_ / (D_ - 1) * ((s_[k_] - y_ * n_[k_]) ** 2).sum()) / n_[k_].sum()
print(f"    n_events={n_ev}  n_days={len(dm)}  bootstrap SE={boot_sd:.4f}  "
      f"cluster-robust SE={clust_se:.4f}  equal-weight day SE={eqw_se:.4f}  iid SE={iid_se:.4f}")
check("day-clustered bootstrap SE matches the cluster-robust SE and far exceeds the iid SE",
      abs(boot_sd - clust_se) / clust_se < 0.03 and boot_sd > 1.5 * iid_se,
      f"ratio to cluster SE {boot_sd/clust_se:.4f}, ratio to iid SE {boot_sd/iid_se:.2f}")

print()
print("=" * 120)
print("TEST 4 -- MUTATION: break the clustering (resample EVENTS not days). The SE must collapse")
print("  toward the iid SE on the same test-3 data. If it does not, the code was never clustering.")
print("=" * 120)
sub_all = r3[r3.offset_min == 240]
vals = sub_all[sub_all.contract_rank == 3]["signed_d_bp"].to_numpy()
rng = np.random.default_rng(3)
naive = np.array([rng.choice(vals, size=len(vals), replace=True).mean() for _ in range(2000)])
check("event-level (WRONG) bootstrap SE collapses to the iid SE",
      abs(naive.std() - iid_se) / max(iid_se, 1e-12) < 0.15 or (naive.std() < 0.2 * boot_sd),
      f"naive SE {naive.std():.4f} vs iid {iid_se:.4f} vs correct day SE {boot_sd:.4f}")

print()
print("=" * 120)
print("TEST 5 -- MUTATION: multinomial-weight bootstrap == explicit index-resampling bootstrap")
print("=" * 120)
d4, S4, N4 = C.build_cells(books["real"])
rng = np.random.default_rng(4)
idx = rng.integers(0, len(d4), size=(4000, len(d4)))
S = S4[("h", 240)] + S4[("d", 240)]
N = N4[("h", 240)] + N4[("d", 240)]
explicit = S[idx].sum(1) / N[idx].sum(1)
rng = np.random.default_rng(5)
W = rng.multinomial(len(d4), np.full(len(d4), 1.0 / len(d4)), size=4000).astype(float)
wt = (W @ S) / (W @ N)
for r in range(5):
    check(f"rank {r+1}: two bootstrap implementations agree on SE to <5%",
          abs(explicit[:, r].std() - wt[:, r].std()) / wt[:, r].std() < 0.05,
          f"explicit {explicit[:,r].std():.4f} vs weights {wt[:,r].std():.4f}")

print()
print("=" * 120)
print("TEST 6 -- KNOWN ANSWER: DiD/delta algebra. Force hawk excess = +1, dove excess = +3 by construction")
print("  => DiD must be 2.0 and delta must be -1.0 at every rank.")
print("=" * 120)
b6r = books["real"].copy()
b6p = books["plac"].copy()
b6r["signed_d_bp"] = np.where(b6r.stance_sign > 0, 1.0, 3.0)
b6p["signed_d_bp"] = 0.0
dr, Sr6, Nr6 = C.build_cells(b6r)
dp, Sp6, Np6 = C.build_cells(b6p)
R = C.stats_from_weights(np.ones((1, len(dr))), Sr6, Nr6)
P = C.stats_from_weights(np.ones((1, len(dp))), Sp6, Np6)
hx = R[("h", 240)] - P[("h", 240)]
dx = R[("d", 240)] - P[("d", 240)]
check("DiD == 2.0 at every rank", np.allclose(0.5 * (hx + dx), 2.0), str(np.round(0.5 * (hx + dx), 6)))
check("delta == -1.0 at every rank", np.allclose(0.5 * (hx - dx), -1.0), str(np.round(0.5 * (hx - dx), 6)))

print()
print("=" * 120)
print("CROSS-REFERENCE -- rebuild the existing book's convention as closely as this panel allows:")
print("  entry -45 min, exit +180 min (the base cell of the report's ENTRY/EXIT table, 806 trades),")
print("  FED only, signed events only, 2023+ (the panel has no signed 2022 events).")
print("=" * 120)
ev = pd.read_parquet(BASE + r"\event_paths.parquet")
pl = pd.read_parquet(BASE + r"\placebo_paths.parquet")


def convention(df, entry, exit_):
    k = df[df.offset_min.isin([entry, exit_])].pivot_table(
        index=["event_id", "contract_rank", "stance_sign", "date"],
        columns="offset_min", values="d_rate_bp_from_baseline")
    k = k.dropna()
    k["d"] = (k[exit_] - k[entry])
    k = k.reset_index()
    k["signed"] = k["d"] * k["stance_sign"]
    return k[k.stance_sign != 0]


for entry, exit_ in ((-45, 180), (-60, 240), (-45, 240), (-60, 180)):
    r = convention(ev, entry, exit_)
    p = convention(pl, entry, exit_)
    rows = []
    for rk in C.RANKS:
        a = r[r.contract_rank == rk]
        b = p[p.contract_rank == rk]
        hx = a[a.stance_sign > 0]["signed"].mean() - b[b.stance_sign > 0]["signed"].mean()
        dx = a[a.stance_sign < 0]["signed"].mean() - b[b.stance_sign < 0]["signed"].mean()
        rows.append(dict(rank=rk, n=len(a), avg_bp=a["signed"].mean(), sd=a["signed"].std(),
                         ratio=a["signed"].mean() / a["signed"].std(),
                         plac_avg=b["signed"].mean(), excess=a["signed"].mean() - b["signed"].mean(),
                         DiD=0.5 * (hx + dx)))
    t = pd.DataFrame(rows).set_index("rank")
    print(f"\n  entry {entry:+d} -> exit {exit_:+d}   (FED only, signed, 2023+)")
    print(t.round(4).to_string())

print("\n  The report's own table for comparison (POOLED FED+ECB+BOE, incl. 2022, entry -45 exit +180):")
print("    1Q avg 0.0755 sharpe 0.50 | 2Q 0.1117 0.50 | 3Q 0.1771 0.68 | 4Q 0.1963 0.68 | 5Q 0.2275 0.74")

print()
print("=" * 120)
print("FAILURES:", FAIL if FAIL else "NONE -- all checks passed")
print("=" * 120)
