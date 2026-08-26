"""CHART 3 analysis: speaker-level ex-ante stance vs RAW rate move at +240.

Pre-registered in c3_PRECOMMIT.txt: headline rank = 3, headline sample = all signed
events with a valid y at rank 3, min 8 VALID-Y events per speaker.

y is d_rate_bp_from_baseline (RAW directional move), NOT signed_d_bp.
"""
import sys, json, pickle
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd
from scipy import stats as sps
import c3_stats as CS

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 300)

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
OFFSET = 240
RANK = 3          # PRE-COMMITTED, see c3_PRECOMMIT.txt
MIN_N = 8
YCOL = "d_rate_bp_from_baseline"   # RAW move. NOT signed_d_bp.
XCOL = "stance_score_exante"       # point-in-time ex-ante score

OUT = []
def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def event_slab(df, rank=RANK, offset=OFFSET, require_signed=True, clean_only=False):
    """One row per event: x, y on exactly the SAME rows."""
    s = df[(df.offset_min == offset) & (df.contract_rank == rank)].copy()
    if require_signed:
        s = s[s[XCOL].notna()]
    s = s[s[YCOL].notna()]
    if clean_only:
        s = s[~s.is_overlapping]
    return s


def speaker_table(s, min_n=MIN_N):
    """Aggregate to one row per speaker. n counts VALID-Y events."""
    g = s.groupby("speaker").agg(
        n=(YCOL, "count"),
        mean_stance=(XCOL, "mean"),
        mean_move=(YCOL, "mean"),
        sd_move=(YCOL, "std"),
        n_voter=("is_voter", "sum"),
        role=("role", "first"),
    )
    g["se_move"] = g["sd_move"] / np.sqrt(g["n"])
    g["voter_share"] = g["n_voter"] / g["n"]
    kept = g[g.n >= min_n].copy().sort_values("mean_stance")
    dropped = g[g.n < min_n].copy().sort_values("n", ascending=False)
    return kept, dropped


def fit_table(tab):
    f = CS.simple_fit(tab["mean_stance"].values, tab["mean_move"].values)
    return f


# =====================================================================
ev = pd.read_parquet(D + r"\event_paths.parquet")
pl = pd.read_parquet(D + r"\placebo_paths.parquet")

say("=" * 78)
say("CHART 3  --  speaker ex-ante stance  vs  RAW rate move at +240 min")
say(f"headline rank {RANK} (pre-registered), offset +{OFFSET}min, y = {YCOL} (RAW)")
say("=" * 78)

s = event_slab(ev)
say(f"\nHEADLINE SAMPLE: {len(s)} events (signed AND valid y at rank {RANK}), "
    f"{s.speaker.nunique()} speakers")
say(f"  date span {s.speech_ts.min().date()} -> {s.speech_ts.max().date()}")
say(f"  year counts: {dict(s.speech_ts.dt.year.value_counts().sort_index())}")

tab, dropped = speaker_table(s)
say(f"\nSPEAKERS KEPT (n>=%d valid-y events): %d" % (MIN_N, len(tab)))
say(tab[["n", "mean_stance", "mean_move", "se_move", "voter_share", "role"]].to_string())
say(f"\nSPEAKERS EXCLUDED (n<{MIN_N}): {len(dropped)}")
if len(dropped):
    say(dropped[["n", "mean_stance", "mean_move", "role"]].to_string())
say(f"  events lost to the n>={MIN_N} filter: {int(dropped['n'].sum())} of {len(s)}")

# ---- x-range structure
neg = tab[tab.mean_stance < 0]
say(f"\nX-RANGE STRUCTURE: {len(neg)} of {len(tab)} kept speakers have a NEGATIVE mean stance")
say("  " + ", ".join(f"{i} {r.mean_stance:+.1f}" for i, r in neg.iterrows()))
say(f"  x range {tab.mean_stance.min():+.2f} .. {tab.mean_stance.max():+.2f}")
say(f"  y range {tab.mean_move.min():+.3f} .. {tab.mean_move.max():+.3f} bp")
say(f"  median SE of a speaker mean: {tab.se_move.median():.3f} bp")

# =====================================================================
say("\n" + "=" * 78)
say("MAIN REGRESSION  (unweighted OLS, one dot per speaker)")
say("=" * 78)
F = fit_table(tab)
say(f"  slope    = {F['slope']:+.5f} bp per stance-score point")
say(f"  se       = {F['se_slope']:.5f}")
say(f"  t        = {F['t_slope']:+.3f}")
say(f"  p        = {F['p_slope']:.4f}")
say(f"  R2       = {F['r2']:.4f}")
say(f"  n        = {F['n']} speakers, dof {F['dof']}")
say(f"  intercept= {F['intercept']:+.4f} bp")

# WLS check
w = 1.0 / tab["se_move"].values ** 2
Xw = np.column_stack([np.ones(len(tab)), tab["mean_stance"].values])
W = CS.wls(Xw, tab["mean_move"].values, w)
say(f"\n  WLS (1/SE^2) check: slope {W['beta'][1]:+.5f}  t {W['t'][1]:+.3f}  R2 {W['r2']:.4f}")

# =====================================================================
say("\n" + "=" * 78)
say("INFLUENCE  --  who is the lever?")
say("=" * 78)
inf = pd.DataFrame({
    "leverage": F["leverage"], "cook": F["cook"], "resid": F["resid"],
    "mean_stance": tab["mean_stance"].values, "mean_move": tab["mean_move"].values,
    "n": tab["n"].values,
}, index=tab.index).sort_values("cook", ascending=False)
say(inf.to_string())

lever = inf.index[0]
say(f"\nBIGGEST LEVER by Cook's D: {lever}  (D={inf.cook.iloc[0]:.3f}, h={inf.leverage.iloc[0]:.3f})")

# full LOO sweep
loo = []
for sp in tab.index:
    t2 = tab.drop(index=sp)
    f2 = fit_table(t2)
    loo.append(dict(dropped=sp, slope=f2["slope"], t=f2["t_slope"], r2=f2["r2"], p=f2["p_slope"]))
loo = pd.DataFrame(loo).set_index("dropped").sort_values("slope")
say("\nFULL LEAVE-ONE-OUT SWEEP (drop each speaker once):")
say(loo.to_string())
say(f"\n  slope range across LOO: {loo.slope.min():+.5f} .. {loo.slope.max():+.5f}")
say(f"  t     range across LOO: {loo.t.min():+.3f} .. {loo.t.max():+.3f}")
say(f"  LOO fits with p<0.05: {int((loo.p < 0.05).sum())} of {len(loo)}")

F_loo = fit_table(tab.drop(index=lever))
say(f"\nHEADLINE LOO -- drop {lever}:")
say(f"  slope {F_loo['slope']:+.5f}  se {F_loo['se_slope']:.5f}  t {F_loo['t_slope']:+.3f}  "
    f"p {F_loo['p_slope']:.4f}  R2 {F_loo['r2']:.4f}  n {F_loo['n']}")

# =====================================================================
say("\n" + "=" * 78)
say("SIGN AGREEMENT  --  is a speaker's mean move signed like their stance?")
say("=" * 78)
agree = np.sign(tab["mean_move"].values) == np.sign(tab["mean_stance"].values)
k = int(agree.sum()); nn = len(agree)
bt = sps.binomtest(k, nn, 0.5)
say(f"  {k} of {nn} speakers correctly signed = {k/nn:.1%}")
say(f"  binomial p vs 50% (two-sided) = {bt.pvalue:.4f}")
say(f"  95% CI on the rate: {bt.proportion_ci().low:.3f} .. {bt.proportion_ci().high:.3f}")
tab["correct_sign"] = agree
say("\n  by speaker:")
for i, r in tab.iterrows():
    say(f"    {i:11s} stance {r.mean_stance:+7.2f}  move {r.mean_move:+7.3f}bp  "
        f"{'OK ' if r.correct_sign else 'NO '}  n={int(r.n)}")
say(f"\n  COMPOSITION WARNING: {int((tab.mean_stance>0).sum())} of {nn} kept speakers are "
    f"hawk-mean, so the 50% benchmark is close to a test of 'did rates drift up'.")

# =====================================================================
say("\n" + "=" * 78)
say("PLACEBO  --  identical pipeline on calendar-matched quiet days")
say("=" * 78)
sp_ = event_slab(pl)
say(f"  placebo events: {len(sp_)}, speakers {sp_.speaker.nunique()}")
ptab, pdrop = speaker_table(sp_)
PF = fit_table(ptab)
say(f"  placebo slope = {PF['slope']:+.5f}  se {PF['se_slope']:.5f}  t {PF['t_slope']:+.3f}  "
    f"p {PF['p_slope']:.4f}  R2 {PF['r2']:.4f}  n {PF['n']}")
pagree = np.sign(ptab["mean_move"].values) == np.sign(ptab["mean_stance"].values)
pk = int(pagree.sum()); pn = len(pagree)
pbt = sps.binomtest(pk, pn, 0.5)
say(f"  placebo sign agreement: {pk}/{pn} = {pk/pn:.1%}  (binomial p {pbt.pvalue:.4f})")
say(f"  REAL {k/nn:.1%} vs PLACEBO {pk/pn:.1%}  -> difference {100*(k/nn - pk/pn):+.1f}pp")
say("\n  placebo speaker table:")
say(ptab[["n", "mean_stance", "mean_move", "se_move"]].to_string())

# real-vs-placebo slope difference, 2-sample z on the two slopes
dz = (F["slope"] - PF["slope"]) / np.sqrt(F["se_slope"] ** 2 + PF["se_slope"] ** 2)
say(f"\n  slope difference real-placebo = {F['slope']-PF['slope']:+.5f}, z = {dz:+.3f}")

# =====================================================================
say("\n" + "=" * 78)
say("VOTERS vs NON-VOTERS")
say("=" * 78)
sv = s[s.is_voter]
sn = s[~s.is_voter]
say(f"  voter events {len(sv)}, non-voter events {len(sn)}")

vtab, vdrop = speaker_table(sv)
ntab, ndrop = speaker_table(sn)
VF = fit_table(vtab); NF = fit_table(ntab)
say(f"\n  VOTER     speaker-level: slope {VF['slope']:+.5f}  t {VF['t_slope']:+.3f}  "
    f"p {VF['p_slope']:.4f}  R2 {VF['r2']:.4f}  n {VF['n']} speakers")
say(f"  NON-VOTER speaker-level: slope {NF['slope']:+.5f}  t {NF['t_slope']:+.3f}  "
    f"p {NF['p_slope']:.4f}  R2 {NF['r2']:.4f}  n {NF['n']} speakers")
say(f"\n  voter x-range   {vtab.mean_stance.min():+.2f} .. {vtab.mean_stance.max():+.2f}  "
    f"(neg-stance speakers: {int((vtab.mean_stance<0).sum())})")
say(f"  nonvoter x-range {ntab.mean_stance.min():+.2f} .. {ntab.mean_stance.max():+.2f}  "
    f"(neg-stance speakers: {int((ntab.mean_stance<0).sum())})")
say("\n  voter table:")
say(vtab[["n", "mean_stance", "mean_move", "se_move", "role"]].to_string())
say("\n  non-voter table:")
say(ntab[["n", "mean_stance", "mean_move", "se_move", "role"]].to_string())

# event-level powered check, clustered by speaker
x = s[XCOL].values.astype(float)
v = s["is_voter"].values.astype(float)
y = s[YCOL].values.astype(float)
Xi = np.column_stack([np.ones(len(s)), x, v, x * v])
CL = CS.ols_cluster(Xi, y, s["speaker"].values)
names = ["const", "stance", "is_voter", "stance x is_voter"]
say(f"\n  EVENT-LEVEL  raw ~ stance * is_voter, SE clustered by speaker "
    f"(n={CL['n']}, {CL['n_clusters']} clusters):")
for j, nm in enumerate(names):
    say(f"    {nm:20s} b={CL['beta'][j]:+.5f}  se={CL['se'][j]:.5f}  t={CL['t'][j]:+.3f}  "
        f"p={CL['p'][j]:.4f}")
say(f"    -> non-voter slope = {CL['beta'][1]:+.5f}; voter slope = {CL['beta'][1]+CL['beta'][3]:+.5f}")

# within-rotator: speaker FE + stance x is_voter, rotators only
rot = s.groupby("speaker")["is_voter"].nunique()
rotators = rot[rot == 2].index.tolist()
sr = s[s.speaker.isin(rotators)]
say(f"\n  WITHIN-ROTATOR (speakers who both voted and did not): {len(rotators)} speakers, "
    f"{len(sr)} events")
say(f"    {sorted(rotators)}")
if len(sr) > 50:
    dm = pd.get_dummies(sr["speaker"], drop_first=True).values.astype(float)
    xr = sr[XCOL].values.astype(float); vr = sr["is_voter"].values.astype(float)
    Xr = np.column_stack([np.ones(len(sr)), xr, vr, xr * vr, dm])
    CR = CS.ols_cluster(Xr, sr[YCOL].values.astype(float), sr["speaker"].values)
    say(f"    with speaker fixed effects, clustered by speaker ({CR['n_clusters']} clusters):")
    for j, nm in enumerate(names):
        say(f"      {nm:20s} b={CR['beta'][j]:+.5f}  se={CR['se'][j]:.5f}  t={CR['t'][j]:+.3f}  "
            f"p={CR['p'][j]:.4f}")
    say(f"      -> within-rotator non-voter slope {CR['beta'][1]:+.5f}, "
        f"voter slope {CR['beta'][1]+CR['beta'][3]:+.5f}")
else:
    CR = None

# =====================================================================
say("\n" + "=" * 78)
say("ROBUSTNESS")
say("=" * 78)
say("\n  ALL 5 CONTRACT RANKS at +240 (headline rank 3 pre-registered):")
rank_rows = []
for r in [1, 2, 3, 4, 5]:
    sr_ = event_slab(ev, rank=r)
    t_, d_ = speaker_table(sr_)
    f_ = fit_table(t_)
    ag = np.sign(t_["mean_move"].values) == np.sign(t_["mean_stance"].values)
    pl_ = event_slab(pl, rank=r)
    pt_, _ = speaker_table(pl_)
    pf_ = fit_table(pt_)
    rank_rows.append(dict(rank=r, n_ev=len(sr_), n_spk=f_["n"], slope=f_["slope"],
                          t=f_["t_slope"], p=f_["p_slope"], r2=f_["r2"],
                          sign_agree=ag.mean(), placebo_slope=pf_["slope"],
                          placebo_t=pf_["t_slope"]))
rank_df = pd.DataFrame(rank_rows).set_index("rank")
say(rank_df.to_string())

say("\n  NON-OVERLAPPING events only (rank 3):")
sc = event_slab(ev, clean_only=True)
ctab, cdrop = speaker_table(sc)
CF = fit_table(ctab)
cag = np.sign(ctab["mean_move"].values) == np.sign(ctab["mean_stance"].values)
say(f"    events {len(sc)}, speakers kept {CF['n']} (excluded {len(cdrop)})")
say(f"    slope {CF['slope']:+.5f}  t {CF['t_slope']:+.3f}  p {CF['p_slope']:.4f}  "
    f"R2 {CF['r2']:.4f}  sign-agree {cag.mean():.1%}")
say(ctab[["n", "mean_stance", "mean_move", "se_move"]].to_string())

say("\n  BUCKET |b|>=1 events only (rank 3):")
sb = s[s.bucket.abs() >= 1]
btab, bdrop = speaker_table(sb)
BF = fit_table(btab)
say(f"    events {len(sb)}, speakers kept {BF['n']}")
say(f"    slope {BF['slope']:+.5f}  t {BF['t_slope']:+.3f}  p {BF['p_slope']:.4f}  R2 {BF['r2']:.4f}")

say("\n  OTHER OFFSETS (rank 3, same pipeline):")
off_rows = []
for o in [15, 30, 60, 120, 180, 240, 300]:
    so = event_slab(ev, offset=o)
    to_, _ = speaker_table(so)
    fo = fit_table(to_)
    off_rows.append(dict(offset=o, n_ev=len(so), n_spk=fo["n"], slope=fo["slope"],
                         t=fo["t_slope"], p=fo["p_slope"], r2=fo["r2"]))
say(pd.DataFrame(off_rows).set_index("offset").to_string())

say("\n  CONTRAST: the same fit run on signed_d_bp instead of the raw move.")
say("  NOTE -- this is reported NEUTRALLY. I first predicted it would 'slope up hard',")
say("  and that prediction was WRONG. The circularity that makes signed_d_bp unusable")
say("  as this chart's y lives in its LEVEL (it is pre-flipped so a correct-direction")
say("  move is positive by construction), NOT in its slope against the mean score.")
say("  That y is the RAW move here is established by c3_verify.py V1/V2, not by this line.")
s_circ = ev[(ev.offset_min == OFFSET) & (ev.contract_rank == RANK) &
            ev[XCOL].notna() & ev["signed_d_bp"].notna()].copy()
gc_ = s_circ.groupby("speaker").agg(n=("signed_d_bp", "count"),
                                    mean_stance=(XCOL, "mean"),
                                    mean_move=("signed_d_bp", "mean"))
gc_ = gc_[gc_.n >= MIN_N]
FC = CS.simple_fit(gc_["mean_stance"].values, gc_["mean_move"].values)
say(f"    signed_d_bp slope {FC['slope']:+.5f}  t {FC['t_slope']:+.3f}  R2 {FC['r2']:.4f}  (n {FC['n']})")
say(f"    mean signed_d_bp across those speakers = {gc_['mean_move'].mean():+.4f} bp "
    f"<- THIS level, not the slope, is the pre-flipped quantity")

# =====================================================================
res = dict(
    tab=tab, dropped=dropped, F=F, W=W, inf=inf, lever=lever, loo=loo, F_loo=F_loo,
    sign_k=k, sign_n=nn, sign_p=bt.pvalue,
    ptab=ptab, PF=PF, pk=pk, pn=pn, pbt_p=pbt.pvalue,
    vtab=vtab, ntab=ntab, VF=VF, NF=NF, CL=CL, CR=CR, rotators=rotators,
    rank_df=rank_df, CF=CF, ctab=ctab, BF=BF, off=pd.DataFrame(off_rows), FC=FC,
    n_events=len(s), n_speakers_all=s.speaker.nunique(),
    span=(str(s.speech_ts.min().date()), str(s.speech_ts.max().date())),
    RANK=RANK, OFFSET=OFFSET, MIN_N=MIN_N,
)
with open(D + r"\c3_results.pkl", "wb") as f:
    pickle.dump(res, f)
with open(D + r"\c3_analysis.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("\n[written] c3_results.pkl + c3_analysis.txt")
