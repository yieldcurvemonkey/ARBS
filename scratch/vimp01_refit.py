"""VERIFY (review-only, no edits): is the shipped CAP_BANDS table generated or typed?

Dual-anchored. With the CURRENT module code:
  * at LN_MU_SLACK = 30 it must reproduce the OLD (HEAD) table -- which also
    prices the ``require_converged=True`` change, claimed to cost <= 4.7e-10;
  * at LN_MU_SLACK = 150 it must reproduce the NEW table on EVERY field, not
    just the multiplier: ln_mu, ln_sigma, capped_count_error, ks_lognormal,
    ks_pareto, ln_degenerate.
Then 60 / 300 for the docstring's "unchanged in every printed digit" claim.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

# --- the HEAD version, loaded standalone so its CAP_BANDS can be compared ---
head_src = subprocess.run(
    ["git", "-C", ROOT, "show", "HEAD:SDRUtils/dealer_direction/imputation.py"],
    capture_output=True, text=True, check=True).stdout
head_path = os.path.join(HERE, "_vimp_head.py")
open(head_path, "w", encoding="utf-8").write(head_src)
spec = importlib.util.spec_from_file_location("_vimp_head", head_path)
head = importlib.util.module_from_spec(spec)
sys.modules["_vimp_head"] = head          # dataclasses looks the module up
spec.loader.exec_module(head)
print(f"HEAD module loaded: LN_MU_SLACK={head.LN_MU_SLACK} "
      f"bands={len(head.CAP_BANDS)}; CURRENT: LN_MU_SLACK={imp.LN_MU_SLACK} "
      f"bands={len(imp.CAP_BANDS)}")


def load() -> pd.DataFrame:
    f = pd.read_csv(os.path.join(HERE, "partB_freq_cache.csv"))
    f = f.dropna(subset=["cell"]).copy()
    m = f["cell"].str.split("|", expand=True)
    f["vintage"] = m[0]
    for c, src in (("lo", m[1]), ("hi", m[2]), ("cap", m[3])):
        f[c] = src.astype(float)
    for c in ("notional", "n", "sum_t", "sum_dv01"):
        f[c] = f[c].astype(float)
    return f


FREQ = load()
FIT_COLS = ["vintage", "lo", "cap", "notional", "is_capped", "n"]


def refit(slack: float):
    imp.LN_MU_SLACK = slack
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)   # a skip must be loud
        return imp.fit_frequency_table(FREQ[FIT_COLS])


def compare(fits, bands, label, fields):
    shipped = {(b.vintage, b.lo): b for b in bands}
    print(f"\n=== {label}: refit {len(fits)} cells vs shipped {len(shipped)}")
    assert set(fits) == set(shipped), (set(fits) ^ set(shipped))
    worst = {}
    for key in sorted(shipped):
        b, f = shipped[key], fits[key]
        got = {"multiplier": f.multiplier, "ln_mu": f.ln_mu_censored,
               "ln_sigma": f.ln_sigma_censored,
               "capped_count_error": f.capped_count_error,
               "ks_lognormal": f.ks_lognormal, "ks_pareto": f.ks_pareto,
               "ln_degenerate": f.ln_degenerate}
        for fld in fields:
            want, have = getattr(b, fld), got[fld]
            if fld == "ln_degenerate":
                if want != have:
                    print(f"  MISMATCH {key} {fld}: shipped {want} refit {have}")
                    worst[fld] = 1.0
                continue
            d = abs(have - want)
            rel = d / max(abs(want), 1e-12)
            if rel > worst.get(fld, (0.0,))[0] if isinstance(
                    worst.get(fld), tuple) else True:
                pass
            prev = worst.get(fld, (0.0, ""))
            if rel > prev[0]:
                worst[fld] = (rel, f"{key} shipped {want!r} refit {have!r}")
    for fld in fields:
        w = worst.get(fld, (0.0, "-"))
        if isinstance(w, tuple):
            print(f"  max rel diff {fld:20s} {w[0]:.3e}   ({w[1]})")
    return worst


ALL = ["multiplier", "ln_mu", "ln_sigma", "capped_count_error",
       "ks_lognormal", "ks_pareto", "ln_degenerate"]

f30 = refit(30.0)
compare(f30, head.CAP_BANDS, "CURRENT CODE at slack 30 vs HEAD table", ALL[:-1])
print("  (ln_degenerate not comparable: HEAD's CapBand has no such field)")

f150 = refit(150.0)
compare(f150, imp.CAP_BANDS, "CURRENT CODE at slack 150 vs SHIPPED table", ALL)

for s in (60.0, 300.0):
    fs = refit(s)
    compare(fs, imp.CAP_BANDS, f"CURRENT CODE at slack {s:g} vs SHIPPED table", ALL)

imp.LN_MU_SLACK = 150.0

# ---- headline constants, recomputed from the same cache -------------------
tot_dv01 = float(FREQ["sum_dv01"].sum())
capped_dv01 = FREQ[FREQ["is_capped"]].groupby(["vintage", "lo"])["sum_dv01"].sum()
tot_not = float(FREQ["notional"].mul(FREQ["n"]).sum())
capped_not = (FREQ[FREQ["is_capped"]].assign(v=lambda d: d["notional"] * d["n"])
              .groupby(["vintage", "lo"])["v"].sum())
c = float(capped_dv01.sum()) / tot_dv01
excess = sum((f.multiplier - 1.0) * float(capped_dv01.get(k, 0.0))
             for k, f in f150.items())
share = excess / (tot_dv01 + excess)
keff = 1.0 + excess / float(capped_dv01.sum())
exc_n = sum((f.multiplier - 1.0) * float(capped_not.get(k, 0.0))
            for k, f in f150.items())
share_n = exc_n / (tot_not + exc_n)
print("\n=== headline recomputed at slack 150 (freq-cache population) ===")
print(f"  capped-at-cap DV01 share c = {c:.4f}   shipped CAPPED_AT_CAP_DV01_SHARE "
      f"= {imp.CAPPED_AT_CAP_DV01_SHARE}")
print(f"  effective k                = {keff:.4f}  shipped EFFECTIVE_MULTIPLIER "
      f"= {imp.EFFECTIVE_MULTIPLIER}")
print(f"  imputed DV01 share         = {share:.4f}  shipped IMPUTED_DV01_SHARE "
      f"= {imp.IMPUTED_DV01_SHARE}")
print(f"  imputed notional share     = {share_n:.4f}  shipped "
      f"IMPUTED_NOTIONAL_SHARE = {imp.IMPUTED_NOTIONAL_SHARE}")

BUCKET = {("V1", 0.0): "<=2y", ("V1", 0.12): "<=2y", ("V1", 0.3): "<=2y",
          ("V1", 0.54): "<=2y", ("V1", 1.04): "<=2y", ("V1", 2.25): "2-10y",
          ("V1", 5.25): "2-10y", ("V1", 10.75): "10-30y", ("V1", 31.0): ">30y",
          ("V2", 0.0): "<=2y", ("V2", 0.12): "<=2y", ("V2", 0.3): "<=2y",
          ("V2", 0.54): "<=2y", ("V2", 1.04): "<=2y", ("V2", 2.25): "2-10y",
          ("V2", 5.25): "2-10y", ("V2", 11.0): "10-30y", ("V2", 31.0): ">30y"}
FREQ["bucket"] = [BUCKET[(v, lo)] for v, lo in zip(FREQ["vintage"], FREQ["lo"])]
print("  per-bucket DV01 share (refit vs shipped IMPUTED_SHARE_BY_BUCKET):")
for bk in ("<=2y", "2-10y", "10-30y", ">30y"):
    sub = FREQ[FREQ["bucket"] == bk]
    tot_b = float(sub["sum_dv01"].sum())
    capb = sub[sub["is_capped"]].groupby(["vintage", "lo"])["sum_dv01"].sum()
    exb = sum((f150[k].multiplier - 1.0) * float(v) for k, v in capb.items())
    tot_bn = float(sub["notional"].mul(sub["n"]).sum())
    capbn = (sub[sub["is_capped"]].assign(v=lambda d: d["notional"] * d["n"])
             .groupby(["vintage", "lo"])["v"].sum())
    exbn = sum((f150[k].multiplier - 1.0) * float(v) for k, v in capbn.items())
    print(f"    {bk:7s} dv01 {exb/(tot_b+exb):.4f} notional "
          f"{exbn/(tot_bn+exbn):.4f}   shipped {imp.IMPUTED_SHARE_BY_BUCKET[bk]}")
