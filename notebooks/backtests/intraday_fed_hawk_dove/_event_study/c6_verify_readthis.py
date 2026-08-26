"""Verify every number READ_THIS.md quotes that c5_fixes.py did not itself compute.

A write-up that quotes a reviewer's stdout is quoting something nobody can re-run.
Each figure below is recomputed here from the panel (or read from the figure's own
JSON at its real key) and printed next to the value claimed in READ_THIS.md.
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
sys.path.append(str(HERE))
from c_common import cluster_mean_se  # noqa: E402

FAIL = []


def chk(label, got, want, tol=0.02):
    ok = (got is None and want is None) or (want is not None and abs(got - want) <= tol)
    print(f"  {'OK  ' if ok else 'FAIL'}  {label:<58s} got {got!s:<12s} claimed {want}")
    if not ok:
        FAIL.append(label)


print("=" * 92)
print("1. days_to_fomc TERCILE, rank 3, +240, all signed  (READ_THIS limitation 7)")
print("=" * 92)
ev = pd.read_parquet(HERE / "event_paths.parquet")
e3 = ev[(ev["contract_rank"] == 3) & (ev["offset_min"] == 240) & (ev["stance_sign"] != 0)].copy()
e3 = e3[e3["d_rate_bp_from_baseline"].notna()]
e3["signed"] = e3["d_rate_bp_from_baseline"] * e3["stance_sign"]
d = e3["days_to_fomc"].abs()
q1, q2 = d.quantile([1 / 3, 2 / 3])
terciles = {"near": d <= q1, "mid": (d > q1) & (d <= q2), "far": d > q2}
got = {}
for nm, m in terciles.items():
    r = cluster_mean_se(e3.loc[m, "signed"].to_numpy(), e3.loc[m, "date"].to_numpy())
    got[nm] = r
    print(f"    {nm:<5s} |days_to_fomc| range {d[m].min():.0f}-{d[m].max():.0f}: "
          f"mean {r['mean']:+.4f} bp  t {r['t']:+.3f}  n {r['n']}")
chk("far tercile mean bp", round(got["far"]["mean"], 2), 0.61, 0.02)
chk("far tercile t", round(got["far"]["t"], 2), 2.13, 0.03)
chk("near tercile mean bp", round(got["near"]["mean"], 2), -0.01, 0.10)

# is the gradient release-driven?  READ_THIS claims it is not, so measure the
# contamination share in each tercile rather than asserting it.
ids = set(e3["event_id"])
sys.path.append(str(HERE))
import k1_release_window as K1  # noqa: E402
cal_all, rel = K1.load_calendar()
rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
meta = e3.drop_duplicates("event_id")[["event_id", "speech_ts"]]
flag, _ = K1.flag_windows(meta, rel_hm, -60, 240)
fmap = dict(zip(meta["event_id"], flag))
e3["contam"] = e3["event_id"].map(fmap)
print("    contamination share by tercile (READ_THIS: 'flat across terciles'):")
shares = {}
for nm, m in terciles.items():
    shares[nm] = float(e3.loc[m, "contam"].mean())
    print(f"      {nm:<5s} {shares[nm]:.1%}")
chk("tercile contamination spread (pp)",
    round(100 * (max(shares.values()) - min(shares.values())), 1), 4.0, 4.0)

print()
print("=" * 92)
print("2. ARGMAX-MINUTE two-proportion z  (READ_THIS verdict row (a))")
print("=" * 92)
z3 = json.load(open(HERE / "z3_stampcheck.json"))
p1, n1 = z3["real_all"]["share_0"], z3["real_all"]["n"]
p2, n2 = z3["placebo"]["share_0"], z3["placebo"]["n"]
pp = (p1 * n1 + p2 * n2) / (n1 + n2)
se = np.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
z = (p1 - p2) / se
print(f"    real {p1:.4%} (n={n1})   placebo {p2:.4%} (n={n2})   pooled {pp:.4%}   z = {z:+.3f}")
chk("real share at minute 0 (%)", round(100 * p1, 2), 3.50, 0.02)
chk("placebo share at minute 0 (%)", round(100 * p2, 2), 2.71, 0.02)
chk("two-proportion z", round(z, 2), 1.14, 0.03)

print()
print("=" * 92)
print("3. FIG-4 numbers, read at their real JSON keys  (READ_THIS fig4 + verdict)")
print("=" * 92)
f4 = json.load(open(HERE / "fig4_window_decay.json"))
micro = f4["microstructure"]
print("    microstructure:", json.dumps(micro)[:300])
tc = f4["t_curve_primary"]
print("    t_curve_primary:", json.dumps(tc)[:400])
pm = f4["t_curve_pre_event_mirror"]
print("    pre_event_mirror:", json.dumps(pm)[:400])
dc = f4["daily_correlation"]
print("    daily_correlation primary:", json.dumps(dc.get("primary_all_events_0to240", dc))[:300])
orb = f4["overlap_robust"]
wk = [r for r in orb if r["window_min"] == 7200]
print("    overlap_robust @ 1 week:", json.dumps(wk))
chk("zero-move share, first 5 min", round(micro["frac_zero_move_first_5min"], 3), 0.444, 0.001)
chk("5-min MDE bp", round(tc[0]["mde_bp"], 3), 0.074, 0.001)
chk("5-min t", round(tc[0]["t"], 2), 0.71, 0.01)
pm30 = [r for r in pm if r["window_min"] == 30][0]
chk("30-min PRE-speech mean bp", round(pm30["mean"], 3), 0.116, 0.002)
chk("30-min PRE-speech t", round(pm30["t"], 2), 1.36, 0.03)
if wk:
    chk("1-week cluster t", round(wk[0]["t_cluster"], 2), 2.90, 0.03)
    chk("1-week block-bootstrap t", round(wk[0]["t_block"], 2), 1.85, 0.05)
    chk("1-week Newey-West t", round(wk[0]["t_nw"], 2), 1.68, 0.05)
chk("daily |corr| vs event window", round(dc["primary_all_events_0to240"]["abs_pearson"], 4),
    0.2949, 0.0002)

print()
print("=" * 92)
print("4. c5_fixes.json cross-read: the numbers READ_THIS quotes from it")
print("=" * 92)
F = json.load(open(HERE / "c5_fixes.json"))
for bk, lab in (("fig1_nonoverlap", "headline"), ("fig1b_all", "all events")):
    b = F[bk]
    rc = b["release_split_240"]
    print(f"  {lab}:")
    print(f"    gap raw            {b['gap_240']['coef']:+.4f} (t {b['gap_240']['t']:+.3f}, n {b['gap_240']['n']})")
    print(f"    gap DiD matched    {b['placebo_parent_matched']['gap_did_240']['coef']:+.4f} "
          f"(t {b['placebo_parent_matched']['gap_did_240']['t']:+.3f})")
    print(f"    gap DiD clean      {rc['gap_did_clean_parent_matched']['coef']:+.4f} "
          f"(t {rc['gap_did_clean_parent_matched']['t']:+.3f}, n {rc['gap_did_clean_parent_matched']['n']})")
    print(f"    composite clean    {rc['clean']['mean']:+.4f} (t {rc['clean']['t']:+.3f}, n {rc['clean']['n']})")
    print(f"    day FE             {b['day_fe_240']['coef']} (t {b['day_fe_240']['t']}, "
          f"{b['day_fe_240']['n_id_days']} id days)")
    print(f"    trim top1% days    {b['trim_top1pct_days_240']['mean']:+.4f} "
          f"(t {b['trim_top1pct_days_240']['t']:+.3f})")
    print(f"    joint clean+trim   {F['joint_clean_and_trim'][bk]['clean_then_trim']['mean']:+.4f} "
          f"(t {F['joint_clean_and_trim'][bk]['clean_then_trim']['t']:+.3f})")
    print(f"    top3 share of sum  {b['tail_concentration']['top3_share_of_total_pct']:.0f}%")
    print(f"    pre-event gap      {b['pre_event_gap_at_argmax_bp']:+.3f} bp at "
          f"{b['pre_event_gap_argmax_offset']:+d} min")

s = F["fig2_strip_release_clean"]
print("\n  strip, release-clean excess over placebo at +240:")
for r in ("1", "2", "3", "4", "5"):
    print(f"    {r}Q  full {s[r]['full']['mean']:+.3f} (t {s[r]['full']['t']:+.2f}, n {s[r]['full']['n']}) | "
          f"clean {s[r]['clean']['mean']:+.3f} (t {s[r]['clean']['t']:+.2f}, n {s[r]['clean']['n']}) | "
          f"contam {s[r]['contaminated']['mean']:+.3f} (t {s[r]['contaminated']['t']:+.2f}) | "
          f"clean excess {s[r]['excess_clean']['coef']:+.3f} (t {s[r]['excess_clean']['t']:+.2f})")
print(f"\n  overlap double-count: {F['overlap_double_count']}")
print(f"  placebo blackout: real {F['placebo_blackout_mismatch']['real_share_within_10d_fomc_pct']:.1f}% "
      f"vs placebo {F['placebo_blackout_mismatch']['placebo_share_within_10d_fomc_pct']:.1f}%")
print(f"  SVB week: {F['svb_week_hole']}")
print(f"  release coverage: real {F['coverage_real']}")

print()
print("=" * 92)
print("RESULT:", "ALL CHECKS PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
print("=" * 92)
sys.exit(0 if not FAIL else 1)
