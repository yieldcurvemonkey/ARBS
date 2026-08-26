"""Independent re-computation of the chart-3 headline numbers, plus power (MDE).
Deliberately re-derives y from price/baseline_price rather than trusting the
d_rate_bp_from_baseline column, so a bad column would show up."""
import sys, pickle
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd
from scipy import stats as sps
import c3_stats as CS

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(D + r"\event_paths.parquet")
res = pickle.load(open(D + r"\c3_results.pkl", "rb"))
tab = res["tab"]
FAILS = []

def chk(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("   " + detail if detail else ""))
    if not ok:
        FAILS.append(name)

s = ev[(ev.offset_min == 240) & (ev.contract_rank == 3) &
       ev.stance_score_exante.notna() & ev.d_rate_bp_from_baseline.notna()].copy()

print("=== V1: re-derive y from PRICE, not from the d_rate column ===")
# rate_bp = (100-price)*100 ; d = rate(T) - rate(baseline) = (baseline_price - price)*100
y_indep = (s["baseline_price"] - s["price"]) * 100.0
d = (y_indep - s["d_rate_bp_from_baseline"]).abs()
chk("y recomputed from price matches the stored column", d.max() < 1e-6,
    f"max abs diff {d.max():.3e} over {len(s)} rows")

print()
print("=== V2: confirm y is the RAW move, NOT signed_d_bp ===")
# NOTE: 19 events carry an ex-ante score of EXACTLY 0.0 -> stance_sign 0 -> signed_d_bp NaN.
# The identity can only be checked where signed_d_bp exists.
sgn = s["stance_sign"].values
ok_rows = s["signed_d_bp"].notna().values
chk("signed_d_bp is NaN exactly where the score is 0.0",
    bool(((s["stance_score_exante"] == 0).values == ~ok_rows).all()),
    f"{int((~ok_rows).sum())} zero-score rows")
ident = np.allclose(s["signed_d_bp"].values[ok_rows],
                    (s["d_rate_bp_from_baseline"].values * sgn)[ok_rows])
chk("signed == raw * stance_sign on all non-NaN rows", ident,
    f"checked {int(ok_rows.sum())} rows")
n_dove = int((sgn < 0).sum())
differ = int((~np.isclose(s["d_rate_bp_from_baseline"].values[ok_rows],
                          s["signed_d_bp"].values[ok_rows])).sum())
chk("raw and signed columns genuinely DIFFER (so y is unsigned)", differ > 0,
    f"{differ} rows differ, of {n_dove} dove rows (rest are doves whose raw move was 0)")

print()
print("=== V2b: robustness -- drop the 19 exactly-zero-score events ===")
s_nz = s[s.stance_score_exante != 0]
g = s_nz.groupby("speaker").agg(n=("d_rate_bp_from_baseline", "count"),
                                mean_stance=("stance_score_exante", "mean"),
                                mean_move=("d_rate_bp_from_baseline", "mean"))
g = g[g.n >= 8]
fz = CS.simple_fit(g["mean_stance"].values, g["mean_move"].values)
print(f"  excluding score==0: n_ev {len(s_nz)}, speakers {fz['n']}, "
      f"slope {fz['slope']:+.5f}, t {fz['t_slope']:+.3f}, R2 {fz['r2']:.4f}")
print(f"  headline (incl.):   n_ev {len(s)}, speakers {res['F']['n']}, "
      f"slope {res['F']['slope']:+.5f}, t {res['F']['t_slope']:+.3f}, R2 {res['F']['r2']:.4f}")
print("  zero-score events by speaker:",
      dict(s[s.stance_score_exante == 0].speaker.value_counts()))

print()
print("=== V3: per-speaker means recomputed with a plain python loop ===")
worst = 0.0
for sp in tab.index:
    rows = s[s.speaker == sp]
    mv = float(np.mean(list(rows["d_rate_bp_from_baseline"].values)))
    st = float(np.mean(list(rows["stance_score_exante"].values)))
    n = len(rows)
    worst = max(worst, abs(mv - tab.loc[sp, "mean_move"]), abs(st - tab.loc[sp, "mean_stance"]))
    if n != tab.loc[sp, "n"]:
        chk(f"n mismatch for {sp}", False, f"{n} vs {tab.loc[sp,'n']}")
chk("all speaker means/n reproduce by loop", worst < 1e-9, f"max abs diff {worst:.3e}")

print()
print("=== V4: headline slope via scipy.linregress (independent of c3_stats) ===")
lr = sps.linregress(tab["mean_stance"].values, tab["mean_move"].values)
chk("slope matches scipy", abs(lr.slope - res["F"]["slope"]) < 1e-12,
    f"{lr.slope:+.6f} vs {res['F']['slope']:+.6f}")
chk("t matches scipy", abs(lr.slope / lr.stderr - res["F"]["t_slope"]) < 1e-8,
    f"t {lr.slope/lr.stderr:+.4f}")
chk("R2 matches scipy", abs(lr.rvalue**2 - res["F"]["r2"]) < 1e-12, f"R2 {lr.rvalue**2:.6f}")

print()
print("=== V5: correlation is the same story ===")
r_p = sps.pearsonr(tab["mean_stance"], tab["mean_move"])
r_s = sps.spearmanr(tab["mean_stance"], tab["mean_move"])
print(f"  Pearson  r = {r_p[0]:+.4f}  p = {r_p[1]:.4f}")
print(f"  Spearman r = {r_s[0]:+.4f}  p = {r_s[1]:.4f}")

print()
print("=== V6: POWER -- what slope COULD this design have found? ===")
se = res["F"]["se_slope"]
tcrit = sps.t.ppf(0.975, res["F"]["dof"])
# 80% power, two-sided 5%
mde = (tcrit + sps.t.ppf(0.80, res["F"]["dof"])) * se
xr = tab["mean_stance"].max() - tab["mean_stance"].min()
print(f"  se(slope)            = {se:.5f} bp per stance point")
print(f"  MDE slope @80% power = {mde:.5f} bp per stance point")
print(f"  x-range              = {xr:.1f} stance points (Barr {tab['mean_stance'].min():+.1f} "
      f"-> Mester {tab['mean_stance'].max():+.1f})")
print(f"  => detectable end-to-end hawk-minus-dove spread = {mde*xr:.3f} bp at +240min")
print(f"  observed end-to-end fitted spread               = {res['F']['slope']*xr:+.3f} bp")
print(f"  95% CI on the end-to-end spread = "
      f"{(res['F']['slope']-tcrit*se)*xr:+.3f} .. {(res['F']['slope']+tcrit*se)*xr:+.3f} bp")

print()
print("=== V7: pooled signed effect (context: is there ANY average reaction?) ===")
for rk in [1, 2, 3, 4, 5]:
    q = ev[(ev.offset_min == 240) & (ev.contract_rank == rk) & ev.signed_d_bp.notna()]
    m = q.signed_d_bp.mean(); sd = q.signed_d_bp.std(); n = len(q)
    t = m / (sd / np.sqrt(n))
    print(f"  rank {rk}: mean signed_d_bp = {m:+.4f} bp  t = {t:+.3f}  n = {n}")
q = ev[(ev.offset_min == 240) & (ev.contract_rank == 3) & ev.signed_d_bp.notna()]
for lbl, sub in [("hawk", q[q.stance_sign > 0]), ("dove", q[q.stance_sign < 0])]:
    m = sub.d_rate_bp_from_baseline.mean(); sd = sub.d_rate_bp_from_baseline.std(); n = len(sub)
    print(f"  rank3 {lbl}: mean RAW move = {m:+.4f} bp  t = {m/(sd/np.sqrt(n)):+.3f}  n = {n}")

print()
print("=== V8: Barr's leverage share ===")
lev = res["inf"]["leverage"]
print(f"  Barr leverage {lev.get('Barr', np.nan):.4f} of total {lev.sum():.2f} "
      f"(= {100*lev.get('Barr', np.nan)/lev.sum():.1f}% of all leverage, vs {100/len(lev):.1f}% if even)")
print(f"  Barr Cook's D {res['inf'].loc['Barr','cook']:.4f} -- he ANCHORS the x-axis "
      f"but sits ON the line, so he does not tilt it")
xs = tab["mean_stance"]
print(f"  x-variance share from Barr: "
      f"{((xs['Barr']-xs.mean())**2)/((xs-xs.mean())**2).sum():.1%}")

print()
print("=" * 60)
print("VERIFY FAILURES:", FAILS if FAILS else "NONE -- all checks passed")
