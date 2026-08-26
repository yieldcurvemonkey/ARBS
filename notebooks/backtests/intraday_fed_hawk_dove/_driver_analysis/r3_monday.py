import sys, json
sys.path.append(r"C:\Users\chris\clee\ARBS")
import numpy as np, pandas as pd

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(D + r"\panel_daily.parquet")
rates = pd.read_parquet(D + r"\rates_daily.parquet")
p = p.join(rates, how="left", rsuffix="_r")
idx = p.index
d = p["d_rate_bp"].values.astype(float); sq = d ** 2; absd = np.abs(d)
dow = p["dow"].values.astype(int)
sp = p["is_speech_day"].values.astype(bool)
roll = p["is_imm_roll"].values.astype(bool)
DEF = pd.to_datetime(["2019-07-01","2019-07-02","2019-07-03","2019-07-05","2019-07-08","2020-03-06"])
isdef = idx.isin(DEF)
RC = ~np.isnan(d) & ~p["is_fomc_day"].values & ~p["is_cpi_day"].values & ~p["is_nfp_day"].values
OFF = np.arange(21, 1892)
OUT = {}

def tp(o, nl):
    nl = np.asarray(nl, float); nl = nl[np.isfinite(nl)]
    med = np.median(nl); return float((np.abs(nl - med) >= abs(o - med) - 1e-12).mean())

print("=" * 78)
print("HOW MANY DAYS ARE THE 'VARIANCE SITS ON NON-SPEECH DAYS' HEADLINE?")
print("=" * 78)
mon_ns = RC & (dow == 0) & ~sp
print(f"Monday non-speech cell: n={mon_ns.sum()}  msq={sq[mon_ns].mean():.2f}")
top = np.argsort(-sq * mon_ns)[:5]
run = sq[mon_ns].sum()
for i in top:
    print(f"   {idx[i].date()}  d={d[i]:+8.2f}bp   "
          f"{sq[i]/sq[mon_ns].sum()*100:5.1f}% of the Monday non-speech sum(d^2)")
k3 = np.zeros(len(p), bool); k3[top[:3]] = True
rem = mon_ns & ~k3
print(f"   remove those 3 -> n={rem.sum()}  msq={sq[rem].mean():.2f}  "
      f"(was {sq[mon_ns].mean():.2f})")
OUT["monday_nonspeech_msq"] = float(sq[mon_ns].mean())
OUT["monday_nonspeech_msq_ex3"] = float(sq[rem].mean())
OUT["top3_monday_nonspeech"] = [dict(date=str(idx[i].date()), d_bp=float(d[i])) for i in top[:3]]

print()
print("Concentration as those 3 Mondays are removed one at a time:")
order = list(top[:3])
cum = np.zeros(len(p), bool)
for j, i in enumerate([None] + order):
    if i is not None: cum[i] = True
    m = RC & ~cum
    shd = sp[m].mean(); shs = sq[m][sp[m]].sum() / sq[m].sum()
    lab = "none removed" if i is None else f"-{idx[i].date()}"
    print(f"   {lab:16s} n={m.sum():4d}  concentration={shs/shd:.4f}  "
          f"msq_ratio={sq[m&sp].mean()/sq[m&~sp].mean():.4f}")
    OUT[f"conc_after_{lab}"] = float(shs / shd)

print()
print("=" * 78)
print("MEDIAN |d| RATIO -- the author's 'one loose end' -- ACROSS THE CURVE")
print("=" * 78)
cols = {"imm3x4 (target)": "USD-SOFR-1D IMM_3xIMM_4 OUTRIGHT RATE",
        "2y": "USD-SOFR-1D 2y OUTRIGHT RATE",
        "5y": "USD-SOFR-1D 5y OUTRIGHT RATE"}
rows = []
for lab, c in cols.items():
    dd = p[c].diff().values * 100.0; aa = np.abs(dd)
    m = RC & ~np.isnan(dd) & ~isdef & ~roll
    def med_ratio(s):
        a, b = m & s, m & ~s
        return np.median(aa[a]) / np.median(aa[b])
    obs = med_ratio(sp)
    nl = np.array([med_ratio(np.roll(sp, o)) for o in OFF])
    rows.append(dict(series=lab, med_ratio=obs, null_med=np.nanmedian(nl),
                     rotation_p=tp(obs, nl)))
mr = pd.DataFrame(rows)
print(mr.round(4).to_string(index=False))
OUT["median_ratio_placebo"] = mr.round(6).to_dict("records")
print()
print("If the median tilt is the SAME size in the 5y as in the 3m forward,")
print("it is ambient mid-week news flow, not a front-end Fedspeak response.")

with open(D + r"\r3_monday_results.json", "w") as f:
    json.dump(OUT, f, indent=1, default=str)
print("\nwrote r3_monday_results.json")
