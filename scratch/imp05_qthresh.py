"""Complete the sensitivity grid with the two cell-quantile thresholds.

The LEDGER quotes a notional-share band whose low end (16.3%) does not appear
among the u = C/k thresholds, so it must come from u = a cell quantile. Six
thresholds, one table, so the quoted band is the measured one.
"""
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import numpy as np, pandas as pd
from SDRUtils.dealer_direction import imputation as imp

freq = pd.read_csv(r"C:\Users\chris\clee\ARBS-dd\scratch\partB_freq_cache.csv").dropna(subset=["cell"]).copy()
m = freq["cell"].str.split("|", expand=True)
freq["vintage"], freq["lo"], freq["cap"] = m[0], m[1].astype(float), m[3].astype(float)
for c in ("notional", "n", "sum_t", "sum_dv01"):
    freq[c] = freq[c].astype(float)

def run(kind, param):
    rows = []
    for (vintage, lo), g in freq.groupby(["vintage", "lo"], sort=True):
        C = float(g["cap"].iloc[0])
        capped = g[g["is_capped"].astype(bool)]
        n_cap = float(capped.loc[capped["notional"] == C, "n"].sum())
        sub = g[~g["is_capped"].astype(bool)]
        if kind == "div":
            u = C / param
        else:                                     # cell quantile, clamped as the probe did
            v = g.sort_values("notional")
            cw = v["n"].cumsum() / v["n"].sum()
            u = float(v.loc[cw >= param, "notional"].iloc[0])
            u = min(max(u, C / 50), C / 1.8)
        fit = imp.fit_cell(sub["notional"].to_numpy(), sub["n"].to_numpy(), u, C, n_cap)
        cap_mean_t = float(capped["sum_t"].sum() / capped["n"].sum())
        exc = 0.0 if fit is None else n_cap * max(fit.mean_above_lognormal - C, 0.0)
        rows.append({"lo": lo, "alpha": np.nan if fit is None else fit.pareto_alpha_censored,
                     "mult": np.nan if fit is None else fit.multiplier,
                     "tot_n": float((g["notional"] * g["n"]).sum()),
                     "tot_d": float(g["sum_dv01"].sum()),
                     "exc_n": exc, "exc_d": exc * cap_mean_t * 1e-4})
    return pd.DataFrame(rows)

def coarse(lo):
    return "<=2y" if lo < 2 else ("2-10y" if lo < 10 else ("10-30y" if lo < 30 else ">30y"))

out, per_bucket = [], {}
for kind, param, lab in [("div", 2.0, "C/2"), ("div", 4.0, "C/4"), ("div", 10.0, "C/10"),
                         ("div", 20.0, "C/20"), ("q", 0.90, "cell q0.90"), ("q", 0.95, "cell q0.95")]:
    d = run(kind, param)
    tn, en, td, ed = d.tot_n.sum(), d.exc_n.sum(), d.tot_d.sum(), d.exc_d.sum()
    d["bucket"] = d["lo"].map(coarse)
    ag = d.groupby("bucket").agg(td=("tot_d", "sum"), ed=("exc_d", "sum"),
                                 tn=("tot_n", "sum"), en=("exc_n", "sum"))
    per_bucket[lab] = pd.DataFrame({"dv01": ag.ed / (ag.td + ag.ed),
                                    "notional": ag.en / (ag.tn + ag.en)})
    out.append({"threshold": lab, "median_alpha": d.alpha.median(),
                "alpha<1": int((d.alpha < 1).sum()), "median_mult": d["mult"].median(),
                "notional_share": en / (tn + en), "dv01_share": ed / (td + ed)})
H = pd.DataFrame(out)
print(H.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print(f"\nDV01 share band     {H.dv01_share.min():.4f} - {H.dv01_share.max():.4f}")
print(f"notional share band {H.notional_share.min():.4f} - {H.notional_share.max():.4f}")
print(f"median alpha band   {H.median_alpha.min():.3f} - {H.median_alpha.max():.3f}")

print("\n== per-bucket DV01 share across all six thresholds ==")
D = pd.DataFrame({k: v["dv01"] for k, v in per_bucket.items()})
D["band"] = [f"{r.min():.4f}-{r.max():.4f}" for _, r in D.iterrows()]
print(D.to_string(float_format=lambda v: f"{v:.4f}"))
print("\n== per-bucket NOTIONAL share across all six thresholds ==")
N = pd.DataFrame({k: v["notional"] for k, v in per_bucket.items()})
N["band"] = [f"{r.min():.4f}-{r.max():.4f}" for _, r in N.iterrows()]
print(N.to_string(float_format=lambda v: f"{v:.4f}"))
