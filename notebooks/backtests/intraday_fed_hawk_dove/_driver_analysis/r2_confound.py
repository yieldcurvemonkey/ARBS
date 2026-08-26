"""
CONFOUNDING / IDENTIFICATION REVIEW of Analysis A (variance ratio).

Attacks:
  T1  elapsed-time / day-of-week confound  (NOT tested by the author)
  T2  IMM-roll contamination of the DOSE-RESPONSE (author ran dose on V0, rolls IN)
  T3  placebo / specificity across the curve (NOT tested by the author)
  T4  reverse-causality re-check + fully-adjusted headline

All nulls are the AUTHOR'S circular rotation of (is_speech_day, n_speakers) jointly,
exhaustive over offsets [21, 1891], everything else held fixed.  An iid null is
documented in the panel notes to inflate p by 17x, so it is never used here.
"""
import sys, json
sys.path.append(r"C:\Users\chris\clee\ARBS")
import numpy as np
import pandas as pd

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
OUT = {}
DOWN = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

p = pd.read_parquet(D + r"\panel_daily.parquet")
rates = pd.read_parquet(D + r"\rates_daily.parquet")
p = p.join(rates, how="left", rsuffix="_r")

# ---------------------------------------------------------------- arrays
idx = p.index
n = len(p)
d_imm = p["d_rate_bp"].values.astype(float)
dow = p["dow"].values.astype(int)
speech0 = p["is_speech_day"].values.astype(bool)
nspk0 = p["n_speakers"].values.astype(int)
is_fomc = p["is_fomc_day"].values.astype(bool)
is_cpi = p["is_cpi_day"].values.astype(bool)
is_nfp = p["is_nfp_day"].values.astype(bool)
is_roll = p["is_imm_roll"].values.astype(bool)
is_black = p["is_blackout"].values.astype(bool)

# elapsed calendar days since previous spine row  (Monday = 3, post-holiday > 1)
gap = np.empty(n); gap[:] = np.nan
gap[1:] = (idx[1:] - idx[:-1]).days.values.astype(float)

DEFECT = pd.to_datetime(["2019-07-01", "2019-07-02", "2019-07-03",
                         "2019-07-05", "2019-07-08", "2020-03-06"])
is_defect = idx.isin(DEFECT)

have_d = ~np.isnan(d_imm)
RUNG_C = have_d & ~is_fomc & ~is_cpi & ~is_nfp

OFFSETS = np.arange(21, 1892)


def rot(a, off):
    return np.roll(a, off)


def two_sided_p(obs, null):
    null = np.asarray(null, float)
    null = null[np.isfinite(null)]
    if len(null) == 0 or not np.isfinite(obs):
        return np.nan
    med = np.median(null)
    return float((np.abs(null - med) >= abs(obs - med) - 1e-12).mean())


# =====================================================================
# T0  reproduce, then decompose the headline by DOW
# =====================================================================
print("=" * 78)
print("T0  WHERE DOES THE BELOW-1 CONCENTRATION LIVE?  (rung c, V0)")
print("=" * 78)
m = RUNG_C
sq = d_imm ** 2
sh_days = speech0[m].mean()
sh_sq = sq[m][speech0[m]].sum() / sq[m].sum()
print(f"raw: share_days {sh_days:.4f}  share_sumsq {sh_sq:.4f}  "
      f"concentration {sh_sq/sh_days:.4f}")

rows = []
for k in range(5):
    mk = m & (dow == k)
    sp, ns = mk & speech0, mk & ~speech0
    rows.append(dict(dow=DOWN[k], n=int(mk.sum()),
                     n_sp=int(sp.sum()), n_ns=int(ns.sum()),
                     p_speech=float(speech0[mk].mean()),
                     msq_sp=float(sq[sp].mean()), msq_ns=float(sq[ns].mean()),
                     msq_all=float(sq[mk].mean()),
                     share_of_total_sumsq=float(sq[mk].sum() / sq[m].sum())))
dowtab = pd.DataFrame(rows)
dowtab["msq_ratio"] = dowtab["msq_sp"] / dowtab["msq_ns"]
print(dowtab.round(4).to_string(index=False))
OUT["T0_dow_table"] = dowtab.round(6).to_dict("records")

print()
print("MONDAY is 24.9% of the non-speech arm but 16.5% of the speech arm,")
print("and carries the highest mean-square of any weekday.")
print(f"Monday share of ALL rung-c sum(d^2) = {dowtab.loc[0,'share_of_total_sumsq']:.4f}")

# elapsed-time check
print()
print("ELAPSED CALENDAR DAYS per arm (the mechanical confound):")
for lab, mm in [("speech", m & speech0), ("non-speech", m & ~speech0)]:
    print(f"  {lab:11s} mean gap {np.nanmean(gap[mm]):.4f} d   "
          f"P(gap>1) {np.nanmean(gap[mm] > 1):.4f}")
g_sp, g_ns = np.nanmean(gap[m & speech0]), np.nanmean(gap[m & ~speech0])
print(f"  non-speech days span {g_ns/g_sp:.4f}x the calendar time of speech days")
print(f"  => under sqrt-time scaling the VARIANCE ratio is mechanically "
      f"deflated by ~{g_sp/g_ns:.4f}")
OUT["T0_gap"] = dict(mean_gap_speech=float(g_sp), mean_gap_nonspeech=float(g_ns),
                     ratio=float(g_ns / g_sp),
                     p_gap_gt1_speech=float(np.nanmean(gap[m & speech0] > 1)),
                     p_gap_gt1_nonspeech=float(np.nanmean(gap[m & ~speech0] > 1)))
OUT["T0_raw"] = dict(share_days=float(sh_days), share_sumsq=float(sh_sq),
                     concentration=float(sh_sq / sh_days))


# =====================================================================
# T1  DOW-ADJUSTED statistics  (post-stratification on weekday)
# =====================================================================
print()
print("=" * 78)
print("T1  DAY-OF-WEEK FIXED EFFECT  (author never tested this)")
print("=" * 78)

W = np.array([(m & (dow == k)).sum() for k in range(5)], float)
W = W / W.sum()


def dow_adj(vals, sp, mask, minn=5):
    """weighted-by-DOW ratio of arm means, weights fixed to rung-c DOW mix"""
    num = den = 0.0
    for k in range(5):
        a = mask & sp & (dow == k)
        b = mask & ~sp & (dow == k)
        if a.sum() < minn or b.sum() < minn:
            return np.nan
        num += W[k] * vals[a].mean()
        den += W[k] * vals[b].mean()
    return num / den


def raw_ratio(vals, sp, mask):
    a, b = mask & sp, mask & ~sp
    if a.sum() < 5 or b.sum() < 5:
        return np.nan
    return vals[a].mean() / vals[b].mean()


absd = np.abs(d_imm)

variants = {
    "V0_as_spec": RUNG_C,
    "V1_ex_defect": RUNG_C & ~is_defect,
    "V2_ex_defect_ex_roll": RUNG_C & ~is_defect & ~is_roll,
    "V4_clean_2020plus": RUNG_C & ~is_defect & ~is_roll & (p["year"].values >= 2020),
    "V0_ex_MONDAY": RUNG_C & (dow != 0),
    "V2_ex_MONDAY": RUNG_C & ~is_defect & ~is_roll & (dow != 0),
    "V0_gap1_only": RUNG_C & (gap == 1),
}

res_rows = []
for vname, vmask in variants.items():
    for sname, vals in [("msq", sq), ("mean_abs", absd)]:
        obs_raw = raw_ratio(vals, speech0, vmask)
        obs_adj = dow_adj(vals, speech0, vmask)
        nr = np.array([raw_ratio(vals, rot(speech0, o), vmask) for o in OFFSETS])
        na = np.array([dow_adj(vals, rot(speech0, o), vmask) for o in OFFSETS])
        res_rows.append(dict(variant=vname, stat=sname, n=int(vmask.sum()),
                             raw=obs_raw, raw_nullmed=np.nanmedian(nr),
                             raw_p=two_sided_p(obs_raw, nr),
                             dowadj=obs_adj, adj_nullmed=np.nanmedian(na),
                             adj_p=two_sided_p(obs_adj, na)))
r1 = pd.DataFrame(res_rows)
print(r1.round(4).to_string(index=False))
OUT["T1_dow_adjusted"] = r1.round(6).to_dict("records")

# OLS |d| ~ speech + DOW dummies, HAC(10)
print()
print("OLS of |d| on speech dummy, with and without DOW fixed effects (HAC lag 10):")
import statsmodels.api as sm
mm = RUNG_C
y = absd[mm]
sp = speech0[mm].astype(float)
Ddum = np.column_stack([(dow[mm] == k).astype(float) for k in range(1, 5)])
for lab, X in [("no FE  ", np.column_stack([np.ones(mm.sum()), sp])),
               ("with FE", np.column_stack([np.ones(mm.sum()), sp, Ddum]))]:
    fit = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
    print(f"  {lab}  beta_speech = {fit.params[1]:+.4f} bp  "
          f"t = {fit.tvalues[1]:+.3f}  p = {fit.pvalues[1]:.4f}")
    OUT[f"T1_ols_{lab.strip()}"] = dict(beta=float(fit.params[1]),
                                        t=float(fit.tvalues[1]),
                                        p=float(fit.pvalues[1]))

# add elapsed-gap control
Xg = np.column_stack([np.ones(mm.sum()), sp, Ddum, np.sqrt(gap[mm])])
fit = sm.OLS(y, Xg).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
print(f"  +sqrt(gap) beta_speech = {fit.params[1]:+.4f} bp  "
      f"t = {fit.tvalues[1]:+.3f}  p = {fit.pvalues[1]:.4f}")
OUT["T1_ols_with_gap"] = dict(beta=float(fit.params[1]), t=float(fit.tvalues[1]),
                              p=float(fit.pvalues[1]))


# =====================================================================
# T2  IMM ROLL CONTAMINATION OF THE DOSE-RESPONSE
# =====================================================================
print()
print("=" * 78)
print("T2  IS THE 3-SPEAKER DOSE BUMP AN IMM-ROLL ARTEFACT?")
print("=" * 78)


def buckets(mask, nspk_arr):
    b = np.digitize(nspk_arr, [1, 2, 3, 4])  # 0,1,2,3,4+
    out = []
    for k in range(5):
        mk = mask & (b == k)
        out.append(dict(bucket=["0", "1", "2", "3", "4+"][k], n=int(mk.sum()),
                        mean_abs=float(absd[mk].mean()) if mk.sum() else np.nan,
                        med_abs=float(np.median(absd[mk])) if mk.sum() else np.nan,
                        n_roll=int((mk & is_roll).sum())))
    return pd.DataFrame(out)


print("rung (c) V0  (rolls IN -- this is what the author reported):")
b0 = buckets(RUNG_C, nspk0)
print(b0.round(4).to_string(index=False))
print()
print("rung (c) ex-roll ex-defect (V2):")
b2 = buckets(RUNG_C & ~is_roll & ~is_defect, nspk0)
print(b2.round(4).to_string(index=False))
OUT["T2_dose_V0"] = b0.round(6).to_dict("records")
OUT["T2_dose_V2_exroll"] = b2.round(6).to_dict("records")

print()
print("The 3-speaker bucket in V0 contains these IMM-roll days:")
mk3 = RUNG_C & (nspk0 == 3) & is_roll
sub = pd.DataFrame(dict(date=idx[mk3], d_bp=d_imm[mk3]))
print(sub.round(3).to_string(index=False))
OUT["T2_roll_days_in_3spk"] = [dict(date=str(a.date()), d_bp=float(b))
                               for a, b in zip(idx[mk3], d_imm[mk3])]

# monotonicity / trend, rotation null, on the CLEAN sample
from scipy.stats import spearmanr


def rho_stat(mask, sp_arr, ns_arr):
    return spearmanr(ns_arr[mask], absd[mask]).statistic


for lab, mask in [("V0 (rolls in)", RUNG_C),
                  ("V2 (ex-roll ex-defect)", RUNG_C & ~is_roll & ~is_defect)]:
    obs = rho_stat(mask, speech0, nspk0)
    nl = np.array([rho_stat(mask, rot(speech0, o), rot(nspk0, o)) for o in OFFSETS])
    print(f"\nSpearman rho(n_speakers, |d|) {lab}: {obs:+.4f}  "
          f"rotation p = {two_sided_p(obs, nl):.4f}")
    OUT[f"T2_rho_{lab.split()[0]}"] = dict(rho=float(obs),
                                           rotation_p=float(two_sided_p(obs, nl)))


# =====================================================================
# T3  PLACEBO / SPECIFICITY ACROSS THE CURVE
# =====================================================================
print()
print("=" * 78)
print("T3  PLACEBO: does the SAME pattern appear where Fedspeak should matter less?")
print("=" * 78)

series = {
    "imm3x4 (target)": "USD-SOFR-1D IMM_3xIMM_4 OUTRIGHT RATE",
    "2y": "USD-SOFR-1D 2y OUTRIGHT RATE",
    "5y": "USD-SOFR-1D 5y OUTRIGHT RATE",
    "ON 1d (policy)": "USD-SOFR-1D 1d OUTRIGHT RATE",
}
prows = []
for lab, col in series.items():
    dd = p[col].diff().values * 100.0
    ss = dd ** 2
    aa = np.abs(dd)
    mk = RUNG_C & ~np.isnan(dd) & ~is_defect & ~is_roll   # clean sample for all
    shd = speech0[mk].mean()
    shs = ss[mk][speech0[mk]].sum() / ss[mk].sum()
    obs_m = raw_ratio(aa, speech0, mk)
    obs_ma = dow_adj(aa, speech0, mk)
    nl = np.array([raw_ratio(aa, rot(speech0, o), mk) for o in OFFSETS])
    nla = np.array([dow_adj(aa, rot(speech0, o), mk) for o in OFFSETS])
    prows.append(dict(series=lab, n=int(mk.sum()), concentration=shs / shd,
                      msq_ratio=raw_ratio(ss, speech0, mk),
                      mean_abs_ratio=obs_m, mean_abs_p=two_sided_p(obs_m, nl),
                      mean_abs_dowadj=obs_ma,
                      dowadj_p=two_sided_p(obs_ma, nla)))
pl = pd.DataFrame(prows)
print(pl.round(4).to_string(index=False))
OUT["T3_placebo"] = pl.round(6).to_dict("records")


# =====================================================================
# T4  reverse causality re-check on the CLEAN sample + n_distinct_speakers
# =====================================================================
print()
print("=" * 78)
print("T4  REVERSE CAUSALITY + n_distinct_speakers (author did not re-run dose on it)")
print("=" * 78)
ndist = p["n_distinct_speakers"].values.astype(int)
mask = RUNG_C & ~is_roll & ~is_defect
bd = buckets(mask, ndist)
print("dose on n_distinct_speakers, clean sample:")
print(bd.round(4).to_string(index=False))
OUT["T4_dose_ndistinct"] = bd.round(6).to_dict("records")

obs = spearmanr(ndist[mask], absd[mask]).statistic
nl = np.array([spearmanr(rot(ndist, o)[mask], absd[mask]).statistic for o in OFFSETS])
print(f"Spearman rho(n_distinct, |d|) = {obs:+.4f}  rotation p = {two_sided_p(obs, nl):.4f}")
OUT["T4_rho_ndistinct"] = dict(rho=float(obs), rotation_p=float(two_sided_p(obs, nl)))

# does lagged |d| predict n_speakers, on the clean sample, HAC
lag1 = np.roll(absd, 1)
mk = mask & ~np.isnan(lag1)
X = np.column_stack([np.ones(mk.sum()), lag1[mk]])
fit = sm.OLS(nspk0[mk].astype(float), X).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
print(f"n_speakers ~ |d|_(t-1):  beta {fit.params[1]:+.5f}  t {fit.tvalues[1]:+.3f}  "
      f"p {fit.pvalues[1]:.4f}   R2 {fit.rsquared:.5f}")
OUT["T4_reverse"] = dict(beta=float(fit.params[1]), t=float(fit.tvalues[1]),
                         p=float(fit.pvalues[1]), r2=float(fit.rsquared))

with open(D + r"\r2_confound_results.json", "w") as f:
    json.dump(OUT, f, indent=1, default=str)
print("\nwrote r2_confound_results.json")
