"""Adversarial pass 4: stamp convention, lookahead, timezone, downsampling.

OFFLINE ONLY.  No com_client, no connect(), no Excel.

Q1  Is the HOURLY bar stamped H equal to the last MINUTE print at or before H:59?
    Or does it equal a print at (H+1):00 or later -- the only lookahead channel left?
Q2  Are the stamps really America/New_York?  Test on FOMC statement days (14:00 NY)
    and on the 08:30 NY data release, using the MINUTE tape's own activity, not a
    docstring.
Q3  Downsampling: MINIMUM gap per tag on MI01 (must be 1 minute); distinct stamps per
    (bond, date) on HOURLY (a midnight-only date is a daily-downsampled window).
"""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from RVUtils.ETFRebalance import intraday as itd
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
import etf_tsgrid_lib as L

DATA = L.DATA
uni = itd.universe()
isins = list(uni["isin"].astype(str))
i2c = dict(zip(isins, uni["cusip"].astype(str)))

q = CitiVeloQuotes(offline=True)
MIN = q.frame([f"RATES.BOND.{i}.YIELD" for i in isins], "MI01")
MIN.columns = [i2c.get(str(c).split(".")[2], str(c)) for c in MIN.columns]
HR = q.frame([f"RATES.BOND.{i}.YIELD" for i in isins], "HOURLY")
HR.columns = [i2c.get(str(c).split(".")[2], str(c)) for c in HR.columns]
mi = pd.DatetimeIndex(MIN.index); hi = pd.DatetimeIndex(HR.index)
print("MI01  %s  %s..%s  %d dates" % (MIN.shape, mi.min(), mi.max(), mi.normalize().nunique()))
print("HOURLY %s  %s..%s  %d dates" % (HR.shape, hi.min(), hi.max(), hi.normalize().nunique()))

# ------------------------------------------------------------------ Q3 downsampling
print("\n=== Q3 DOWNSAMPLING ===")
res = []
for c in MIN.columns[:400]:
    s = MIN[c].dropna()
    if len(s) < 50:
        continue
    t = pd.DatetimeIndex(s.index)
    d = t.normalize()
    gaps = []
    for _, gidx in pd.Series(np.arange(len(t)), index=d).groupby(level=0):
        if len(gidx) > 1:
            gaps.append(np.diff(t[gidx.to_numpy()]).astype("timedelta64[m]").astype(int))
    if not gaps:
        continue
    gg = np.concatenate(gaps)
    res.append(dict(cusip=c, n=len(s), min_gap=int(gg.min()), med_gap=float(np.median(gg)),
                    p25=float(np.percentile(gg, 25))))
res = pd.DataFrame(res)
print("MI01 per-tag gaps: min_gap distribution", res.min_gap.value_counts().to_dict())
print("  tags with min_gap > 1 minute: %d of %d" % ((res.min_gap > 1).sum(), len(res)))
print("  median of per-tag median gap: %.1f min" % res.med_gap.median())
res.to_csv(DATA / "adv_ts_mi01_gaps.csv", index=False)

# hourly: distinct stamps per date
hsub = HR[hi >= "2019-11-18"]
hidx = pd.DatetimeIndex(hsub.index)
per_date = pd.Series(hidx.hour).groupby(hidx.normalize().to_numpy()).nunique()
print("\nHOURLY distinct stamps per date: med %d p05 %d min %d" %
      (per_date.median(), per_date.quantile(.05), per_date.min()))
mid_only = per_date[per_date <= 2]
print("  dates with <=2 distinct stamps (daily-downsampled leak): %d of %d" % (len(mid_only), len(per_date)))
if len(mid_only):
    print("   ", list(mid_only.index[:10]))
gaps_h = np.diff(np.unique(hidx.astype("int64")))
print("  hourly stamp set present:", sorted(pd.Series(hidx.hour).unique()))

# ------------------------------------------------------------------ Q1 stamp convention
print("\n=== Q1 STAMP CONVENTION / LOOKAHEAD ===")
common_days = sorted(set(mi.normalize().unique()) & set(hi.normalize().unique()))
print("overlapping days:", len(common_days))
rows = []
for day in common_days:
    mday = MIN[mi.normalize() == day]
    hday = HR[hi.normalize() == day]
    if mday.empty or hday.empty:
        continue
    mt = pd.DatetimeIndex(mday.index)
    for st in range(9, 18):
        hrow = hday[pd.DatetimeIndex(hday.index).hour == st]
        if hrow.empty:
            continue
        hrow = hrow.iloc[-1]
        for c in MIN.columns:
            hv = hrow.get(c, np.nan)
            if not np.isfinite(hv):
                continue
            s = mday[c]
            # candidate A: last print at or before st:59  (START-stamped, own close)
            a = s[(mt.hour == st)].dropna()
            va = float(a.iloc[-1]) if len(a) else np.nan
            ta = a.index[-1] if len(a) else pd.NaT
            # candidate B: last print at or before st:00 (END-stamped hour ending at st)
            b = s[(mt.hour == st - 1)].dropna()
            vb = float(b.iloc[-1]) if len(b) else np.nan
            # candidate C: a print at exactly (st+1):00 -- LOOKAHEAD channel
            cser = s[(mt.hour == st + 1) & (mt.minute == 0)].dropna()
            vc = float(cser.iloc[-1]) if len(cser) else np.nan
            # candidate D: last print anywhere in [st:00, (st+1):00]  incl the boundary
            dser = s[((mt.hour == st) | ((mt.hour == st + 1) & (mt.minute == 0)))].dropna()
            vd = float(dser.iloc[-1]) if len(dser) else np.nan
            td = dser.index[-1] if len(dser) else pd.NaT
            rows.append(dict(day=day, stamp=st, cusip=c, hv=hv, A=va, B=vb, C=vc, D=vd,
                             tA=ta, tD=td))
cmp = pd.DataFrame(rows)
print("comparisons:", len(cmp))
for k in ["A", "B", "C", "D"]:
    ok = cmp[k].notna()
    eq = (np.abs(cmp.loc[ok, "hv"] - cmp.loc[ok, k]) < 1e-9)
    print("  hourly == candidate %s : %.4f  (n=%d)  medabs=%.6f" %
          (k, eq.mean(), ok.sum(), float(np.nanmedian(np.abs(cmp.loc[ok, "hv"] - cmp.loc[ok, k])))))
# does D ever differ from A -- i.e. does a boundary print at (st+1):00 ever get used?
dd = cmp[(cmp.A.notna()) & (cmp.D.notna())]
diff = dd[np.abs(dd.A - dd.D) > 1e-12]
print("  rows where a boundary (st+1):00 print would change the answer: %d of %d" % (len(diff), len(dd)))
if len(diff):
    hit_d = (np.abs(diff.hv - diff.D) < 1e-9).mean()
    hit_a = (np.abs(diff.hv - diff.A) < 1e-9).mean()
    print("     on those rows hourly matches D (LOOKAHEAD) %.4f, matches A (clean) %.4f" % (hit_d, hit_a))
# staleness of the hourly close: how old is the print it carries?
age = (pd.DatetimeIndex(cmp.tA.dropna()) - pd.DatetimeIndex(cmp.tA.dropna()).floor("h"))
agem = 59 - (age.total_seconds() / 60)
print("\nAGE of the print the hourly close carries, minutes before the hour end:")
print("  med %.1f  p75 %.1f  p90 %.1f  p99 %.1f  frac>5min %.4f" %
      (np.median(agem), np.percentile(agem, 75), np.percentile(agem, 90),
       np.percentile(agem, 99), float((agem > 5).mean())))
cmp.drop(columns=["tA", "tD"]).to_csv(DATA / "adv_ts_stamp_check.csv", index=False)

# ------------------------------------------------------------------ Q2 timezone
print("\n=== Q2 TIMEZONE ===")
FOMC = pd.to_datetime([
    "2021-09-22", "2021-11-03", "2021-12-15", "2022-01-26", "2022-03-16", "2022-05-04",
    "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14", "2023-02-01",
    "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01",
    "2023-12-13", "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31",
    "2024-09-18", "2024-11-07", "2024-12-18", "2025-01-29", "2025-03-19", "2025-05-07",
    "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
])
mnorm = mi.normalize()
mmin = (mi.hour * 60 + mi.minute).to_numpy()
prints = MIN.notna().sum(axis=1).to_numpy()
absmove = MIN.diff().abs().mean(axis=1).to_numpy() * 100.0    # bp
df = pd.DataFrame(dict(day=mnorm, minute=mmin, prints=prints, mv=absmove))
df["is_fomc"] = df.day.isin(set(FOMC))
print("FOMC days present in MI01 tape:", int(df.loc[df.is_fomc, "day"].nunique()))
if df.is_fomc.any():
    a = df[df.is_fomc].groupby(df.minute // 5 * 5)["mv"].mean()
    b = df[~df.is_fomc].groupby(df.minute // 5 * 5)["mv"].mean()
    ratio = (a / b).dropna().sort_values(ascending=False)
    print("top 8 five-minute buckets by FOMC/non-FOMC |move| ratio (minute-of-day, NY if 840=14:00):")
    for k, v in ratio.head(8).items():
        print("    %02d:%02d  ratio %.2f" % (k // 60, k % 60, v))
    out = pd.DataFrame(dict(minute_of_day=ratio.index, ratio=ratio.values))
    out.to_csv(DATA / "adv_ts_tz_fomc_ratio.csv", index=False)
# unconditional activity profile 08:00-10:00 to find the 08:30 release
pr = df.groupby("minute")["prints"].mean()
print("\nunconditional print profile, peak minute-of-day:", int(pr.idxmax()),
      "-> %02d:%02d" % (pr.idxmax() // 60, pr.idxmax() % 60))
print(pr.loc[[m for m in range(500, 560) if m in pr.index]].round(1).to_string())
