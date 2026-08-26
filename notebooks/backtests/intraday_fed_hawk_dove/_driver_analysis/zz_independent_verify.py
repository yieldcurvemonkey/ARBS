"""Independent re-computation of the load-bearing numbers, written from scratch
against the panel rather than by reading the analysis scripts.

Checks:
  1. rung (c) arm sizes and mean|d| ratio          (claimed 775/897, 1.012)
  2. concentration and its trim trajectory          (claimed 0.725 -> ~1.02 @ top5)
  3. dose-response on the clean sample              (claimed 3.39/3.72/3.74/3.78/3.40)
  4. curve-specificity placebo                      (claimed 1.089/1.095/1.073)
  5. Warsh-arm size and composition                 (claimed 56 days / 22 speech / 0 Warsh)
"""
import json

import numpy as np
import pandas as pd

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"

p = pd.read_parquet(f"{OUT}/panel_daily.parquet")
p.index = pd.to_datetime(p.index)
res = {}


def ratio(df, col="abs_d_rate_bp"):
    s = df.loc[df.is_speech_day.astype(bool), col]
    n = df.loc[~df.is_speech_day.astype(bool), col]
    return len(s), len(n), s.mean() / n.mean(), s.var(ddof=1) / n.var(ddof=1), s.median() / n.median()


# ---- 1. rung (c): ex-FOMC, ex-CPI, ex-NFP ----
c = p[~p.is_fomc_day.astype(bool) & ~p.is_cpi_day.astype(bool) & ~p.is_nfp_day.astype(bool)].dropna(subset=["abs_d_rate_bp"])
ns, nn, mr, vr, mdr = ratio(c)
res["rung_c"] = {"n_speech": ns, "n_nonspeech": nn, "mean_abs_ratio": round(mr, 4),
                 "var_ratio": round(vr, 4), "median_abs_ratio": round(mdr, 4)}

# ---- 2. concentration + trim trajectory ----
sq = c.abs_d_rate_bp ** 2
share_days = c.is_speech_day.astype(bool).mean()
share_sq = sq[c.is_speech_day.astype(bool)].sum() / sq.sum()
traj = {}
order = c.abs_d_rate_bp.sort_values(ascending=False).index
for k in (0, 1, 5, 10, 16):
    cc = c.drop(order[:k]) if k else c
    ssq = cc.abs_d_rate_bp ** 2
    sd = cc.is_speech_day.astype(bool).mean()
    ss = ssq[cc.is_speech_day.astype(bool)].sum() / ssq.sum()
    traj[f"ex_top{k}"] = round(ss / sd, 4)
res["concentration"] = {"share_days": round(share_days, 4), "share_sumsq": round(share_sq, 4),
                        "concentration": round(share_sq / share_days, 4), "trim_trajectory": traj,
                        "largest_day": str(order[0].date()),
                        "largest_day_bp": round(float(c.loc[order[0], "d_rate_bp"]), 2),
                        "largest_day_pct_of_sumsq": round(float(sq.loc[order[0]] / sq.sum() * 100), 1),
                        "largest_day_is_blackout": bool(c.loc[order[0], "is_blackout"]),
                        "top20_n_blackout": int(c.loc[order[:20], "is_blackout"].astype(bool).sum())}

# ---- 3. dose-response, clean sample (ex IMM roll) ----
clean = c[~c.is_imm_roll.astype(bool)]
buck = clean.n_speakers.clip(upper=4)
dose = clean.groupby(buck).abs_d_rate_bp.agg(["mean", "size"])
res["dose_clean"] = {"means": [round(x, 3) for x in dose["mean"].tolist()],
                     "n": dose["size"].tolist(),
                     "monotone_0_to_3": bool(np.all(np.diff(dose["mean"].values[:4]) > 0)),
                     "spread_bp": round(float(dose["mean"].max() - dose["mean"].min()), 3)}

# ---- 4. curve placebo: same days, different tenors ----
try:
    diag = pd.read_parquet(f"{OUT}/rates_diagnostic.parquet")
    diag.index = pd.to_datetime(diag.index)
    cand = [x for x in diag.columns if any(t in str(x).lower() for t in ("2y", "5y", "imm"))]
    pl = {}
    for col in cand:
        d = diag[col].diff() * 100
        j = pd.DataFrame({"a": d.abs(), "sp": p.is_speech_day.reindex(d.index)}).dropna()
        j = j.loc[j.index.isin(c.index)]
        if len(j) > 200:
            s = j.loc[j.sp.astype(bool), "a"]
            n = j.loc[~j.sp.astype(bool), "a"]
            pl[str(col)] = {"n": len(j), "mean_ratio": round(s.mean() / n.mean(), 4),
                            "median_ratio": round(s.median() / n.median(), 4)}
    res["curve_placebo"] = pl
except Exception as e:
    res["curve_placebo"] = f"ERROR {e}"

# ---- 5. Warsh arm ----
w = c[c.chair_regime.astype(str).str.contains("arsh", na=False)]
res["warsh_arm"] = {"n_days_clean": len(w), "n_speech_days": int(w.is_speech_day.astype(bool).sum()),
                    "regimes_present": sorted(p.chair_regime.astype(str).unique().tolist())}
cal = pd.read_parquet(f"{OUT}/fed_calendar_raw.parquet")
res["warsh_arm"]["warsh_events_in_calendar"] = int((cal.Speaker.astype(str).str.lower() == "warsh").sum())
res["warsh_arm"]["last_powell_event"] = str(pd.to_datetime(cal[cal.Speaker == "Powell"].Date).max().date())
res["warsh_arm"]["n_events_after_2026_05_22"] = int((pd.to_datetime(cal.Date) > "2026-05-22").sum())

print(json.dumps(res, indent=1, default=str))
with open(f"{OUT}/zz_independent_verify.json", "w") as f:
    json.dump(res, f, indent=1, default=str)
