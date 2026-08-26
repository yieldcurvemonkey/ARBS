"""
Re-test 3 against the CORRECT reference. The estimator is a size-weighted ratio
    ybar = sum_d s_d / sum_d n_d
not an equal-weighted mean of day means, so its day-clustered SE is the linearised
cluster-robust SE
    Var = D/(D-1) * sum_d (s_d - ybar*n_d)^2 / (sum_d n_d)^2
Resampling days perturbs the WEIGHTS as well as the values, which is why the correct
bootstrap SE sits above the equal-weight day SE. Confirmed here on three inputs whose
answer is known in closed form, plus the discriminating case where the two references
must coincide (all days the same size).
"""
import sys
import numpy as np
import pandas as pd

BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(BASE)
import c2_strip as C

FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    if not ok:
        FAIL.append(name)


def cluster_se(s, n):
    """linearised cluster-robust SE of sum(s)/sum(n) over clusters"""
    D = len(s)
    y = s.sum() / n.sum()
    return np.sqrt(D / (D - 1) * ((s - y * n) ** 2).sum()) / n.sum()


books = C.load("main")
rr = books["real"].copy()
dayidx = {v: i for i, v in enumerate(sorted(rr["date"].unique()))}
rr["_di"] = rr["date"].map(dayidx)

print("=" * 116)
print("TEST 3a -- perfectly day-clustered data (+10 on odd days, -10 on even), UNEQUAL day sizes")
print("=" * 116)
rr["signed_d_bp"] = np.where(rr["_di"] % 2 == 1, 10.0, -10.0)
d3, S3, N3 = C.build_cells(rr)
rng = np.random.default_rng(2)
W = rng.multinomial(len(d3), np.full(len(d3), 1.0 / len(d3)), size=40000).astype(float)
bs = C.stats_from_weights(W, S3, N3)
boot = np.nanstd(bs[("pool", 240)][:, 2])

s = S3[("h", 240)][:, 2] + S3[("d", 240)][:, 2]
n = N3[("h", 240)][:, 2] + N3[("d", 240)][:, 2]
keep = n > 0
ref = cluster_se(s[keep], n[keep])
sub = rr[(rr.offset_min == 240) & (rr.contract_rank == 3)]
iid = sub["signed_d_bp"].std(ddof=1) / np.sqrt(len(sub))
dm = sub.groupby("date")["signed_d_bp"].mean()
eqw = dm.std(ddof=1) / np.sqrt(len(dm))
print(f"    n_events={len(sub)} n_days={int(keep.sum())} "
      f"day sizes: min={int(n[keep].min())} max={int(n[keep].max())} mean={n[keep].mean():.2f}")
print(f"    bootstrap SE      = {boot:.4f}")
print(f"    cluster-robust SE = {ref:.4f}   <- correct closed-form reference for a size-WEIGHTED ratio")
print(f"    equal-weight day  = {eqw:.4f}   (wrong reference: ignores that resampling perturbs the weights)")
print(f"    iid over events   = {iid:.4f}   (wrong reference: ignores clustering entirely)")
check("bootstrap SE matches the cluster-robust SE to <3%",
      abs(boot - ref) / ref < 0.03, f"ratio {boot/ref:.4f}")
check("bootstrap SE is far above the iid SE (i.e. it really is clustering)",
      boot > 1.5 * iid, f"ratio {boot/iid:.2f}")

print()
print("=" * 116)
print("TEST 3b -- DISCRIMINATING CASE: keep only days holding exactly ONE event at rank 3.")
print("  With equal day sizes the weighted ratio IS the equal-weight day mean, so the two")
print("  references must now coincide, and the bootstrap must match both.")
print("=" * 116)
one = sub.groupby("date").filter(lambda g: len(g) == 1)
rr2 = rr[rr["date"].isin(set(one["date"]))].copy()
d4, S4, N4 = C.build_cells(rr2)
rng = np.random.default_rng(7)
W = rng.multinomial(len(d4), np.full(len(d4), 1.0 / len(d4)), size=40000).astype(float)
bs = C.stats_from_weights(W, S4, N4)
boot2 = np.nanstd(bs[("pool", 240)][:, 2])
s = S4[("h", 240)][:, 2] + S4[("d", 240)][:, 2]
n = N4[("h", 240)][:, 2] + N4[("d", 240)][:, 2]
keep = n > 0
ref2 = cluster_se(s[keep], n[keep])
sub2 = rr2[(rr2.offset_min == 240) & (rr2.contract_rank == 3)]
dm2 = sub2.groupby("date")["signed_d_bp"].mean()
eqw2 = dm2.std(ddof=1) / np.sqrt(len(dm2))
print(f"    n_days={int(keep.sum())} all sizes==1: {bool((n[keep]==1).all())}")
print(f"    bootstrap {boot2:.4f}  cluster-robust {ref2:.4f}  equal-weight day {eqw2:.4f}")
check("with equal day sizes all three references coincide",
      abs(boot2 - ref2) / ref2 < 0.03 and abs(eqw2 - ref2) / ref2 < 0.03,
      f"boot/ref {boot2/ref2:.4f}, eqw/ref {eqw2/ref2:.4f}")

print()
print("=" * 116)
print("TEST 3c -- the REAL data: bootstrap SE vs the cluster-robust SE, every rank, both offsets")
print("=" * 116)
books = C.load("main")
d5, S5, N5 = C.build_cells(books["real"])
rng = np.random.default_rng(11)
W = rng.multinomial(len(d5), np.full(len(d5), 1.0 / len(d5)), size=40000).astype(float)
bs = C.stats_from_weights(W, S5, N5)
rows = []
for off in (30, 240):
    for r in range(5):
        s = S5[("h", off)][:, r] + S5[("d", off)][:, r]
        n = N5[("h", off)][:, r] + N5[("d", off)][:, r]
        k = n > 0
        b = np.nanstd(bs[("pool", off)][:, r])
        cr = cluster_se(s[k], n[k])
        d = books["real"]
        sub = d[(d.offset_min == off) & (d.contract_rank == r + 1)]
        iid = sub["signed_d_bp"].std(ddof=1) / np.sqrt(len(sub))
        rows.append(dict(offset=off, rank=r + 1, boot_SE=b, cluster_SE=cr, ratio=b / cr,
                         iid_SE=iid, cluster_over_iid=cr / iid))
t = pd.DataFrame(rows)
print(t.round(4).to_string(index=False))
check("bootstrap SE within 5% of the cluster-robust SE at every rank/offset",
      (t["ratio"].sub(1).abs() < 0.05).all(), f"max dev {t['ratio'].sub(1).abs().max():.4f}")
print(f"\n  NOTE: clustering inflates the SE by only {t['cluster_over_iid'].mean():.3f}x on the real data "
      f"(most days hold 1-3 speeches), so the day bootstrap is a mild but real correction.")

print()
print("=" * 116)
print("FAILURES:", FAIL if FAIL else "NONE -- all checks passed")
print("=" * 116)
