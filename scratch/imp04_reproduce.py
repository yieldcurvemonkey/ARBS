"""Does the SHIPPED module reproduce the probe's tape numbers?

Validate the tool on a case whose answer is known before trusting it: the
frozen CAP_BANDS came from partB_final_imputation_Cdiv4.csv, so refitting the
same cached frequency table with SDRUtils.dealer_direction.imputation must
return the same multipliers -- and the same headline shares.

Also emits the threshold-sensitivity band, per-bucket and overall, which is
what the written note quotes.
"""
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import numpy as np, pandas as pd
from SDRUtils.dealer_direction import imputation as imp

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
pd.set_option("display.float_format", lambda v: f"{v:,.5g}")

CACHE = r"C:\Users\chris\clee\ARBS-dd\scratch\partB_freq_cache.csv"
freq = pd.read_csv(CACHE).dropna(subset=["cell"]).copy()
m = freq["cell"].str.split("|", expand=True)
freq["vintage"], freq["lo"], freq["hi"], freq["cap"] = (
    m[0], m[1].astype(float), m[2].astype(float), m[3].astype(float))
for c in ("notional", "n", "sum_t", "sum_dv01"):
    freq[c] = freq[c].astype(float)
print(f"frequency table: {len(freq):,} rows, {freq['n'].sum():,.0f} legs")

# ---------------------------------------------------------------- 1. refit
fits = imp.fit_frequency_table(freq)
print(f"\n== 1. refit vs frozen CAP_BANDS ==\n{'cell':<18}{'frozen mult':>12}"
      f"{'refit mult':>12}{'rel diff':>11}{'alpha':>8}{'ncap err':>10}")
worst = 0.0
for band in imp.CAP_BANDS:
    f = fits[(band.vintage, band.lo)]
    rel = abs(f.multiplier / band.multiplier - 1.0)
    worst = max(worst, rel)
    print(f"{band.vintage+' '+band.label:<18}{band.multiplier:>12.4f}"
          f"{f.multiplier:>12.4f}{rel:>11.2e}{f.pareto_alpha_censored:>8.3f}"
          f"{f.capped_count_error:>10.4f}")
print(f"worst relative multiplier difference: {worst:.3e}")
assert worst < 1e-6, "the shipped module does NOT reproduce the measured calibration"

# ------------------------------------------------- 2. shares, per threshold
def shares(divisor):
    rows = []
    for (vintage, lo), g in freq.groupby(["vintage", "lo"], sort=True):
        C = float(g["cap"].iloc[0])
        capped = g[g["is_capped"].astype(bool)]
        n_cap = float(capped.loc[capped["notional"] == C, "n"].sum())
        sub = g[~g["is_capped"].astype(bool)]
        fit = imp.fit_cell(sub["notional"].to_numpy(), sub["n"].to_numpy(),
                           C / divisor, C, n_cap)
        cap_mean_t = float(capped["sum_t"].sum() / capped["n"].sum())
        if fit is None:      # tail window too thin to fit: contributes nothing,
            print(f"   [no fit] {vintage} lo={lo} at u=C/{divisor:g}")  # and is named
            rows.append({"vintage": vintage, "lo": lo, "cap": C, "n_cap": n_cap,
                         "mult": float("nan"), "alpha": float("nan"),
                         "ks_ln": float("nan"), "ks_par": float("nan"),
                         "ncap_err": float("nan"),
                         "tot_notional": float((g["notional"] * g["n"]).sum()),
                         "tot_dv01": float(g["sum_dv01"].sum()),
                         "exc_notional": 0.0, "exc_dv01": 0.0})
            continue
        exc_n = n_cap * max(fit.mean_above_lognormal - C, 0.0)
        rows.append({"vintage": vintage, "lo": lo, "cap": C, "n_cap": n_cap,
                     "mult": fit.multiplier, "alpha": fit.pareto_alpha_censored,
                     "ks_ln": fit.ks_lognormal, "ks_par": fit.ks_pareto,
                     "ncap_err": fit.capped_count_error,
                     "tot_notional": float((g["notional"] * g["n"]).sum()),
                     "tot_dv01": float(g["sum_dv01"].sum()),
                     "exc_notional": exc_n,
                     "exc_dv01": exc_n * cap_mean_t * 1e-4})
    return pd.DataFrame(rows)

def coarse(lo):
    return "1. <=2y" if lo < 2 else ("2. 2-10y" if lo < 10 else
                                     ("3. 10-30y" if lo < 30 else "4. >30y"))

print("\n== 2. threshold sensitivity (lognormal censored) ==")
head = []
per = {}
for div in (2.0, 4.0, 10.0, 20.0):
    d = shares(div)
    per[div] = d
    tn, en = d["tot_notional"].sum(), d["exc_notional"].sum()
    td, ed = d["tot_dv01"].sum(), d["exc_dv01"].sum()
    head.append({"u": f"C/{div:g}", "median_alpha": d["alpha"].median(),
                 "cells_alpha_lt1": int((d["alpha"] < 1).sum()),
                 "median_mult": d["mult"].median(),
                 "max_abs_ncap_err": d["ncap_err"].abs().max(),
                 "notional_share": en / (tn + en), "dv01_share": ed / (td + ed)})
H = pd.DataFrame(head)
print(H.to_string(index=False))

print("\n== 3. per coarse bucket at the shipped u = C/4 ==")
d = per[4.0]
d["bucket"] = d["lo"].map(coarse)
agg = d.groupby("bucket").agg(n_cap=("n_cap", "sum"), tot_n=("tot_notional", "sum"),
                              exc_n=("exc_notional", "sum"),
                              tot_d=("tot_dv01", "sum"), exc_d=("exc_dv01", "sum"))
agg["notional_share"] = agg["exc_n"] / (agg["tot_n"] + agg["exc_n"])
agg["dv01_share"] = agg["exc_d"] / (agg["tot_d"] + agg["exc_d"])
print(agg[["n_cap", "notional_share", "dv01_share"]].to_string())
tn, en = d["tot_notional"].sum(), d["exc_notional"].sum()
td, ed = d["tot_dv01"].sum(), d["exc_dv01"].sum()
print(f"OVERALL notional {en/(tn+en):.4%}   dv01 {ed/(td+ed):.4%}")

print("\n== 4. per-bucket sensitivity across thresholds (dv01 share) ==")
rows = {}
for div, dd in per.items():
    dd = dd.copy(); dd["bucket"] = dd["lo"].map(coarse)
    a = dd.groupby("bucket").agg(td=("tot_dv01", "sum"), ed=("exc_dv01", "sum"))
    rows[f"C/{div:g}"] = a["ed"] / (a["td"] + a["ed"])
print(pd.DataFrame(rows).to_string(float_format=lambda v: f"{v:.4f}"))
print("\nKS: lognormal", f"{d['ks_ln'].min():.4f}-{d['ks_ln'].max():.4f}",
      " pareto", f"{d['ks_par'].min():.4f}-{d['ks_par'].max():.4f}",
      " lognormal wins", int((d['ks_ln'] < d['ks_par']).sum()), "of", len(d))
