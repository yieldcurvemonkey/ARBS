"""
Addendum: is the claim's remediation ("4-6 more quarters") arithmetically possible?

The Powell arm is CLOSED -- Powell is gone, so its SE is frozen. Only the post arm grows.
That puts a hard FLOOR on SE(log rho) = SE_powell, hence a hard CEILING on achievable
power at any fixed effect size. Compute it.
"""
import os, json
import numpy as np, pandas as pd
from math import erf, sqrt

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

p = pd.read_parquet(os.path.join(OUT, "panel_daily.parquet"))
if "date" not in p.columns: p = p.reset_index()
p["date"] = pd.to_datetime(p["date"])
for c in ["is_fomc_day","is_cpi_day","is_nfp_day","is_speech_day"]:
    p[c] = p[c].astype(bool)
C = p[(~p.is_fomc_day)&(~p.is_cpi_day)&(~p.is_nfp_day)&p.abs_d_rate_bp.notna()]

def se_log_mean(x): return float(x.std(ddof=1)/x.mean()/np.sqrt(len(x)))
def parts(df):
    s = df.loc[df.is_speech_day,"abs_d_rate_bp"].to_numpy(float)
    n = df.loc[~df.is_speech_day,"abs_d_rate_bp"].to_numpy(float)
    return s,n
sP,nP = parts(C[C.chair_regime=="Powell"])
sW,nW = parts(C[C.chair_regime=="Warsh"])
seP = float(np.sqrt(se_log_mean(sP)**2 + se_log_mean(nP)**2))
seW = float(np.sqrt(se_log_mean(sW)**2 + se_log_mean(nW)**2))
rr = (sW.mean()/nW.mean())/(sP.mean()/nP.mean())
L = abs(np.log(rr))
za, zb = 1.959964, 0.8416212
def Phi(z): return 0.5*(1+erf(z/sqrt(2)))

say(f"observed rho = {rr:.4f}   |log rho| = {L:.5f}")
say(f"SE_powell (FROZEN, Powell arm is closed) = {seP:.5f}")
say(f"SE_warsh  (shrinks as sqrt(n))           = {seW:.5f}   n_clean=56")
say("")
lam_max = L/seP
pow_max = Phi(lam_max-za)+Phi(-lam_max-za)
say(f"CEILING: with an INFINITELY long post-transition arm, SE(log rho) -> {seP:.5f}")
say(f"         |z|_max = {lam_max:.3f}   MAX ACHIEVABLE POWER = {pow_max:.3f}")
say(f"         80% power at rho={rr:.3f} is UNREACHABLE: {pow_max < 0.80}")
say(f"         (equivalently: MDE can never fall below exp({za+zb:.3f}*{seP:.4f}) = "
    f"{np.exp((za+zb)*seP):.3f}, vs observed {rr:.3f})")
say("")
# days needed just for the CI to exclude 1 (|z|>1.96, i.e. ~50% power)
need_se = L/za
say(f"for the bootstrap CI merely to EXCLUDE 1.0 need SE(log rho) <= {need_se:.5f}")
if need_se <= seP:
    say("   IMPOSSIBLE -- already below the frozen Powell floor.")
    nd = None
else:
    need_seW = np.sqrt(need_se**2 - seP**2)
    nd = 56*(seW/need_seW)**2
    say(f"   -> SE_warsh must fall to {need_seW:.5f}; scales 1/sqrt(n)")
    say(f"   -> post-transition CLEAN days needed ~ {nd:.0f}  (~{nd/63:.1f} quarters, ~{nd/252:.1f} years)")
    say(f"   claim's remediation says '4-6 more quarters' (~{5*63} clean days). "
        f"Understates by ~{nd/(5*63):.1f}x.")
say("")
# what the claim's own recipe would actually buy: MDE after k more quarters
say("MDE after k more quarters of post-transition data (Powell arm frozen):")
for q in [0,2,4,6,8,12,20,30,40]:
    n_new = 56 + q*63
    seW_k = seW*np.sqrt(56/n_new)
    se_k = np.sqrt(seP**2+seW_k**2)
    say(f"   +{q:2d}q  n_post={n_new:5.0f}  SE={se_k:.4f}  MDE={np.exp((za+zb)*se_k):.3f}  "
        f"power@rho={rr:.3f}: {Phi(L/se_k-za)+Phi(-L/se_k-za):.3f}")

res = dict(observed_rho=float(rr), se_powell_frozen=seP, se_warsh=seW,
           max_achievable_power_at_observed_rho=float(pow_max),
           mde_floor_even_with_infinite_post_data=float(np.exp((za+zb)*seP)),
           post_clean_days_for_ci_to_exclude_one=(None if nd is None else float(nd)),
           post_quarters_for_ci_to_exclude_one=(None if nd is None else float(nd/63)),
           claim_says_quarters="4-6")
with open(os.path.join(OUT,"skeptic_power_ceiling_results.json"),"w") as f:
    json.dump(res,f,indent=2)
with open(os.path.join(OUT,"skeptic_power_ceiling_report.txt"),"w",encoding="utf-8") as f:
    f.write("\n".join(lines))
say("\nwrote skeptic_power_ceiling_*.")
