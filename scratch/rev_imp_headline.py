"""Does the boundary pin move the shipped headline out of its own band?"""
import numpy as np
import pandas as pd
from SDRUtils.dealer_direction import imputation as imp

freq = pd.read_csv("scratch/partB_freq_cache.csv")
p = freq["cell"].str.split("|", expand=True)
freq["vintage"], freq["lo"] = p[0], p[1].astype(float)
freq["hi"], freq["cap"] = p[2].astype(float), p[3].astype(float)
freq = freq[["vintage", "lo", "hi", "cap", "notional", "is_capped", "n",
             "sum_dv01", "sum_t"]]

tot_dv01 = float(freq["sum_dv01"].sum())
capped_dv01 = (freq[freq["is_capped"]]
               .groupby(["vintage", "lo"])["sum_dv01"].sum())
print(f"total DV01 proxy {tot_dv01:.4g}, capped-at-cap share "
      f"{capped_dv01.sum()/tot_dv01:.4f}  (docstring says 0.142)")

for slack in (30.0, 45.0, 60.0):
    imp.LN_MU_SLACK = slack
    fits = imp.fit_frequency_table(
        freq[["vintage", "lo", "hi", "cap", "notional", "is_capped", "n"]])
    excess = sum((f.multiplier - 1.0) * float(capped_dv01.get(k, 0.0))
                 for k, f in fits.items())
    share = excess / (tot_dv01 + excess)
    keff = 1.0 + excess / capped_dv01.sum()
    print(f"LN_MU_SLACK={slack:5.0f}  imputed DV01 share {share:.4f}  "
          f"effective k {keff:.3f}")
imp.LN_MU_SLACK = 30.0
print(f"\nshipped constant IMPUTED_DV01_SHARE = {imp.IMPUTED_DV01_SHARE}")
print(f"quoted sensitivity band          = {imp.SENSITIVITY_DV01_SHARE}")
