"""Emit the frozen CAP_BANDS literal from the measured fit CSV.

Transcribing 18 x 8 numbers by hand is how a calibration acquires a typo that
no test can see. The test recomputes the multiplier from (mu, sigma, cap), but
that only helps if mu and sigma themselves came across intact -- so the literal
is generated, not typed.
"""
import pandas as pd

SRC = r"C:\Users\chris\clee\ARBS-dd\scratch\partB_final_imputation_Cdiv4.csv"
LABELS = ["<=46d", "46d-3m", "3m-6m", "6m-1y", "1y-2y", "2y-5y", "5y-10y",
          "10y-30y", ">30y"]

d = pd.read_csv(SRC).sort_values(["vintage", "lo"]).reset_index(drop=True)
print(f"# rows {len(d)}   n_cap total {int(d['n_cap'].sum()):,}")
for v, g in d.groupby("vintage"):
    assert len(g) == 9, (v, len(g))
for i, r in d.iterrows():
    lab = LABELS[i % 9]
    print(f'    CapBand("{r.vintage}", {r.lo!r}, {r.hi!r}, {r.cap:.0f}.0, "{lab}",')
    print(f'            ln_mu={r.ln_mu_cens!r}, ln_sigma={r.ln_sigma_cens!r},')
    print(f'            multiplier={r.ln_mult!r}, tail_index={r.par_alpha_cens!r},')
    print(f'            capped_count_error={r.ncap_err_ln!r},')
    print(f'            ks_lognormal={r.ks_lognorm!r}, n_capped={int(r.n_cap)}),')
print()
print("# coarse-bucket shares at u=C/4")
def coarse(lo):
    return "<=2y" if lo < 2.0 else ("2-10y" if lo < 10.0 else ("10-30y" if lo < 30.0 else ">30y"))
d["coarse"] = d["lo"].map(coarse)
agg = d.groupby("coarse").agg(n_cap=("n_cap", "sum"), tn=("tot_notional", "sum"),
                              en=("exc_notional_ln", "sum"), td=("tot_dv01", "sum"),
                              ed=("exc_dv01_ln", "sum"))
agg["share_n"] = agg["en"] / (agg["tn"] + agg["en"])
agg["share_d"] = agg["ed"] / (agg["td"] + agg["ed"])
print(agg.to_string())
tn, en, td, ed = d["tot_notional"].sum(), d["exc_notional_ln"].sum(), d["tot_dv01"].sum(), d["exc_dv01_ln"].sum()
print(f"OVERALL notional share {en/(tn+en):.6f}   dv01 share {ed/(td+ed):.6f}")
print(f"multiplier range {d['ln_mult'].min():.4f} - {d['ln_mult'].max():.4f}")
print(f"alpha median {d['par_alpha_cens'].median():.4f}  n<1 {(d['par_alpha_cens']<1).sum()}")
print(f"ks_lognorm range {d['ks_lognorm'].min():.4f} - {d['ks_lognorm'].max():.4f}")
print(f"ks_pareto  range {d['ks_pareto'].min():.4f} - {d['ks_pareto'].max():.4f}")
print(f"max |ncap err| {d['ncap_err_ln'].abs().max():.4f}")
