r"""Stamp convention and timezone, broken apart so they cannot confound each other.

1. HOURLY era census: rows at NY-session stamps 9..16 per tag per YEAR. A daily-
   stamped early era would show as zeros there and hide behind 40k hourly gaps.
2. Stamp discriminator, CONDITIONED. The report's test compared hourly@H against
   "MI01 asof H+45m .. H+120m" unconditionally. When nothing prints between H:55
   and H+1:05 the start-stamped and end-stamped hypotheses give the SAME answer
   and every candidate matches. So keep only cells where MI01 has prints in both
   [H-1,H) and [H,H+1) AND the two last prints DIFFER. Then exactly one hypothesis
   can survive.
3. Timezone anchored on the MINUTE tape, not on the hourly stamps: on FOMC
   decision days the 14:00 statement must ignite |dy| on MI01 clock minutes. That
   is independent of any hourly stamping convention.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

cache = CitiVeloTagCache()
uni = pd.read_csv(DATA / "intraday_universe.csv")
isins = list(uni["isin"].astype(str))

# ---------------------------------------------------------------- 1. era census
rows = []
for isin in isins:
    s = cache.read(f"RATES.BOND.{isin}.YIELD", "HOURLY", "CLOSE")
    if s is None or s.empty:
        continue
    idx = pd.DatetimeIndex(s.dropna().index)
    df = pd.DataFrame({"y": idx.year, "h": idx.hour})
    sess = df[(df["h"] >= 9) & (df["h"] <= 16)]
    ct = sess.groupby("y").size()
    ndays = sess.assign(d=pd.DatetimeIndex(s.dropna().index[(idx.hour >= 9) & (idx.hour <= 16)]).normalize()
                        ).groupby("y")["d"].nunique()
    for yr in ct.index:
        rows.append({"isin": isin, "year": int(yr), "session_rows": int(ct[yr]),
                     "session_days": int(ndays[yr]),
                     "rows_per_day": ct[yr] / max(1, ndays[yr])})
era = pd.DataFrame(rows)
agg = era.groupby("year").agg(tags=("isin", "nunique"),
                              rows_per_day_min=("rows_per_day", "min"),
                              rows_per_day_med=("rows_per_day", "median"),
                              rows_per_day_max=("rows_per_day", "max"))
print("=== 1. HOURLY session-stamp era census (stamps 9..16, 8 possible/day) ===")
print(agg.round(3).to_string())
era.to_csv(DATA / "adv_seam_hourly_era_census.csv", index=False)

# ------------------------------------------------- 2. conditioned discriminator
mi_files = sorted((cache.base_dir / "MI01" / "CLOSE").glob("RATES.BOND.*.YIELD.parquet"))
mi_tags = [p.stem for p in mi_files]
uni_tags = {f"RATES.BOND.{i}.YIELD" for i in isins}
mi_tags = [t for t in mi_tags if t in uni_tags]
print(f"\n=== 2. stamp discriminator: {len(mi_tags)} universe tags with MI01 ===")

recs = []
for tag in mi_tags:
    mi = cache.read(tag, "MI01", "CLOSE")
    hr = cache.read(tag, "HOURLY", "CLOSE")
    if mi is None or hr is None or mi.empty or hr.empty:
        continue
    mi = mi.dropna()
    hr = hr.dropna()
    mid = pd.DatetimeIndex(mi.index)
    hrd = pd.DatetimeIndex(hr.index)
    common = sorted(set(mid.normalize().unique()) & set(hrd.normalize().unique()))
    for day in common:
        m = mi[mid.normalize() == day]
        h = hr[hrd.normalize() == day]
        mix = pd.DatetimeIndex(m.index)
        for H in (10, 11, 12, 13, 14, 15, 16):
            ts = pd.Timestamp(day) + pd.Timedelta(hours=H)
            if ts not in h.index:
                continue
            prev_win = m[(mix >= ts - pd.Timedelta(hours=1)) & (mix < ts)]
            this_win = m[(mix >= ts) & (mix < ts + pd.Timedelta(hours=1))]
            if prev_win.empty or this_win.empty:
                continue
            end_hyp = float(prev_win.iloc[-1])    # bar labelled H = hour ENDING H
            start_hyp = float(this_win.iloc[-1])  # bar labelled H = hour STARTING H
            if abs(end_hyp - start_hyp) < 1e-12:
                continue                          # non-discriminating cell
            tgt = float(h.loc[ts])
            recs.append({"tag": tag, "day": day, "H": H,
                         "match_start": abs(tgt - start_hyp) < 1e-9,
                         "match_end": abs(tgt - end_hyp) < 1e-9,
                         "d_start_bp": abs(tgt - start_hyp) * 100,
                         "d_end_bp": abs(tgt - end_hyp) * 100})
D = pd.DataFrame(recs)
print(f"discriminating cells: {len(D):,}")
if len(D):
    g = D.groupby("H").agg(n=("match_start", "size"),
                           start_stamped=("match_start", "mean"),
                           end_stamped=("match_end", "mean"),
                           med_d_start_bp=("d_start_bp", "median"),
                           med_d_end_bp=("d_end_bp", "median"))
    print(g.round(4).to_string())
    print(f"\nOVERALL  start-stamped {D['match_start'].mean():.4f}   "
          f"end-stamped {D['match_end'].mean():.4f}   neither "
          f"{(~D['match_start'] & ~D['match_end']).mean():.4f}")
    g.to_csv(DATA / "adv_seam_stamp_discriminator.csv")

# -------------------------------------------------------- 3. tz from MI01 alone
from SDRUtils.analytics.fomc import load_fomc_schedule  # noqa: E402

fomc = pd.DatetimeIndex(sorted(set(pd.to_datetime(
    load_fomc_schedule("USD-SOFR-1D")["effective_date"]))))
print(f"\n=== 3. timezone from the MINUTE tape ===")
print("fomc dates in registry:", len(fomc), fomc.min().date(), "..", fomc.max().date())

prof = {}
for tag in mi_tags:
    mi = cache.read(tag, "MI01", "CLOSE")
    if mi is None or mi.empty:
        continue
    mi = mi.dropna()
    idx = pd.DatetimeIndex(mi.index)
    days = idx.normalize()
    dy = pd.Series(mi.to_numpy(float), index=idx).diff().abs() * 100.0
    dy[days != pd.Series(days, index=idx).shift()] = np.nan
    tmp = pd.DataFrame({"day": days, "minute": idx.hour * 60 + idx.minute, "dy": dy.to_numpy()})
    tmp["is_fomc"] = tmp["day"].isin(set(fomc))
    prof[tag] = tmp
P = pd.concat(prof.values(), ignore_index=True)
P = P[(P["minute"] >= 7 * 60) & (P["minute"] <= 17 * 60)]
P["bin5"] = (P["minute"] // 5) * 5
fo = P[P["is_fomc"]].groupby("bin5")["dy"].mean()
no = P[~P["is_fomc"]].groupby("bin5")["dy"].mean()
ratio = (fo / no).dropna().sort_values(ascending=False)
print(f"FOMC-day minute observations: {int(P['is_fomc'].sum()):,}  "
      f"distinct fomc days in MI01: {P.loc[P['is_fomc'],'day'].nunique()}")
print("\ntop 12 five-minute bins by FOMC/non-FOMC mean |dy| ratio (bin start, NY-clock-if-NY):")
for b, r in ratio.head(12).items():
    print(f"  {int(b)//60:02d}:{int(b)%60:02d}  ratio {r:.2f}   fomc {fo[b]:.4f}bp  ord {no[b]:.4f}bp")
out = pd.DataFrame({"bin5": ratio.index, "ratio": ratio.to_numpy()})
out["hhmm"] = [f"{int(b)//60:02d}:{int(b)%60:02d}" for b in out["bin5"]]
out.to_csv(DATA / "adv_seam_fomc_minute_profile.csv", index=False)

print("\nunconditional mean |dy| by 5-min bin, top 10 (should peak at 08:30 if NY):")
uncond = P.groupby("bin5")["dy"].mean().sort_values(ascending=False)
for b, v in uncond.head(10).items():
    print(f"  {int(b)//60:02d}:{int(b)%60:02d}  {v:.4f} bp")
