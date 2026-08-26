"""Independent re-derivation of every headline number in frequency_seasonality_results.json.
Different code path on purpose: scipy for the fit, a calendar-side FOMC join for the intra-cycle
profile (weekends included), and a shuffle mutation to prove the trough detector is not vacuous."""
import os, json
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import pandas as pd, numpy as np
from scipy import stats

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
res = json.load(open(os.path.join(D, "frequency_seasonality_results.json"), encoding="utf-8"))
cal = pd.read_parquet(os.path.join(D, "fed_calendar_raw.parquet"))
cal["Date"] = pd.to_datetime(cal["Date"])
pan = pd.read_parquet(os.path.join(D, "panel_daily.parquet")); pan.index = pd.to_datetime(pan.index)
jpm = pd.read_csv(r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv")
jpm["date"] = pd.to_datetime(jpm["date"])
CUT = pd.Timestamp("2026-08-24")
c = cal[cal.Date <= CUT]
fails = []


def chk(name, got, want, tol=1e-6):
    ok = abs(float(got) - float(want)) <= tol
    print(f"  [{'OK ' if ok else 'FAIL'}] {name:46} got {got}  want {want}")
    if not ok:
        fails.append(name)


print("=== 1. events per year (independent count via value_counts) ===")
vc = c.Date.dt.year.value_counts().sort_index()
for row in res["events_per_year"]:
    chk(f"events {row['year']}", vc.loc[row["year"]], row["events"])

print("\n=== 2. partial-year annualisation, recomputed ===")
ph = res["partial_year_handling"]
sh = []
for y in range(2015, 2026):
    cy = c[c.Date.dt.year == y]
    sh.append((cy.Date <= pd.Timestamp(y, 8, 24)).sum() / len(cy))
chk("mean share by 24 Aug", round(float(np.mean(sh)), 4), ph["mean_share_of_year_by_24_aug_complete_years"], 5e-5)
chk("annualised seasonal", round(195 / float(np.mean(sh)), 1), ph["annualised_seasonal"], 0.15)
chk("annualised prorata", round(195 / (236 / 365), 1), ph["annualised_prorata"], 0.15)

print("\n=== 3. trend fit via scipy.linregress (vs numpy.polyfit) ===")
ys = list(range(2015, 2026)); vs = [int(vc.loc[y]) for y in ys]
lr = stats.linregress(ys, vs)
chk("slope", round(lr.slope, 3), res["trend"]["slope_events_per_year"], 1e-3)
chk("r2", round(lr.rvalue ** 2, 4), res["trend"]["r2"], 1e-4)
chk("t_stat", round(lr.slope / lr.stderr, 3), res["trend"]["t_stat"], 2e-3)
print(f"       p-value of the trend slope: {lr.pvalue:.5f}")
resid25 = vs[-1] - (lr.intercept + lr.slope * 2025)
chk("2025 residual", round(float(resid25), 1), res["trend"]["latest_complete_year"]["residual"], 0.15)

print("\n=== 4. seasonality index ===")
mm = (c[c.Date.dt.year <= 2025].groupby([c.Date.dt.year, c.Date.dt.month]).size()
      .unstack().reindex(columns=range(1, 13)).fillna(0))
idx = mm.mean(0) / (mm.values.sum() / (11 * 12))
chk("Oct index", round(float(idx[10]), 3), res["seasonality"]["strongest_month"]["index"], 1e-3)
chk("Dec index", round(float(idx[12]), 3), res["seasonality"]["weakest_month"]["index"], 1e-3)
assert int(idx.idxmax()) == 10 and int(idx.idxmin()) == 12, "strongest/weakest month disagree"
print("  [OK ] argmax/argmin months agree (Oct / Dec)")

print("\n=== 5. JPM coverage, recomputed with a merge instead of a set lookup ===")
p = c.drop_duplicates(subset=["Date", "Speaker"])[["Date", "Speaker"]].copy()
m = p.merge(jpm[["date", "speaker"]].drop_duplicates(), left_on=["Date", "Speaker"],
            right_on=["date", "speaker"], how="left", indicator=True)
chk("total engagements", len(p), res["jpm_coverage"]["total_engagements"])
chk("total scored", int((m._merge == "both").sum()), res["jpm_coverage"]["total_scored"])

print("\n=== 6. YTD like-for-like windows ===")
for y in [2024, 2025, 2026]:
    n = int(((c.Date >= pd.Timestamp(y, 1, 1)) & (c.Date <= pd.Timestamp(y, 8, 24))).sum())
    chk(f"YTD {y}", n, res["trend"]["like_for_like_ytd_to_24_aug"][str(y)])

print("\n=== 7. intra-cycle trough, re-derived FROM THE CALENDAR SIDE ===")
# completely different route: recover FOMC decision dates from the panel, then compute
# days_to_fomc for the RAW calendar (weekends included) rather than trusting panel.n_speakers.
fomc = pd.DatetimeIndex(sorted(pan.index[pan.is_fomc_day]))
print(f"       recovered {len(fomc)} FOMC decision dates; "
      f"{sum(d.dayofweek == 2 for d in fomc)} are Wednesdays")
span = c[(c.Date >= pan.index.min()) & (c.Date <= pan.index.max())]
nxt = fomc.searchsorted(span.Date.values, side="left")
ok = nxt < len(fomc)
dtf = pd.Series((fomc[nxt[ok]] - pd.DatetimeIndex(span.Date.values[ok])).days, name="dtf")
ev = dtf.value_counts().sort_index()
# denominator: calendar days at each offset over the same span
all_days = pd.date_range(pan.index.min(), pan.index.max(), freq="D")
n2 = all_days.searchsorted(all_days)  # placeholder to keep shapes obvious
nx2 = fomc.searchsorted(all_days.values, side="left")
ok2 = nx2 < len(fomc)
den = pd.Series((fomc[nx2[ok2]] - all_days[ok2]).days).value_counts().sort_index()
rate = (ev / den).dropna()
near = float(rate.loc[0:9].mean())
farr = float(rate.loc[18:44].mean())
print(f"       calendar-side rate: days 0-9 = {near:.3f} ev/CALENDAR day, "
      f"days 18-44 = {farr:.3f}  ->  trough is {100*near/farr:.1f}% of far-field")
if near / farr > 0.30:
    fails.append("calendar-side trough not reproduced")
    print("  [FAIL] calendar-side trough absent")
else:
    print("  [OK ] calendar-side route reproduces a deep trough (panel route said "
          f"{res['intra_cycle_profile']['empirical_trough_pct_of_far_field']}%)")

print("\n=== 8. VACUITY CHECK: does the trough detector fire on shuffled data? ===")
rng = np.random.default_rng(7)
depths = []
for _ in range(200):
    sh_ev = rng.permutation(pan.n_speakers.values)
    g = pd.DataFrame({"d": pan.days_to_fomc.values, "e": sh_ev}).groupby("d").agg(
        n=("e", "size"), ev=("e", "mean"))
    g = g[g.n >= 8]
    depths.append(float(g.loc[0:9, "ev"].mean()) / float(g.loc[18:44, "ev"].mean()))
depths = np.array(depths)
real = res["intra_cycle_profile"]["empirical_trough_pct_of_far_field"] / 100.0
print(f"       shuffled trough depth: mean {depths.mean():.3f} of far-field "
      f"(min {depths.min():.3f}, 1st pct {np.percentile(depths,1):.3f}); real {real:.3f}")
if depths.min() <= real:
    fails.append("shuffle reproduces the trough - detector is vacuous")
    print("  [FAIL] shuffling reproduces the trough")
else:
    print(f"  [OK ] 0/200 shuffles reach the observed depth -> the trough is a real "
          f"property of the FOMC clock, not an artefact of the binning")

print("\n=== 9. reconciliation: panel vs calendar event totals ===")
print(f"       calendar events inside panel span : {len(span)}")
print(f"       panel n_speakers sum              : {int(pan.n_speakers.sum())}")
print(f"       difference                        : {len(span) - int(pan.n_speakers.sum())} "
      f"(off-spine weekend/holiday Fedspeak, expected)")
wk_in_span = int((span.Date.dt.dayofweek >= 5).sum())
print(f"       of which weekend-dated            : {wk_in_span}")

print("\n" + ("ALL CHECKS PASS" if not fails else f"FAILURES: {fails}"))
