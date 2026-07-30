"""Probe: is it the FOMC CALENDAR, or just a flexible basis?

The smooth-policy-path fit explains a large share of an SR3 butterfly's
variance. That is only interesting if the *real* meeting dates do it better than
a decoy with the same number of knots. Three decoys:

* **shifted**  -- the real calendar moved bodily by N days: same count, same
  irregularity, wrong phase against the IMM grid.
* **even**     -- eight pseudo-meetings a year at exactly equal spacing: same
  count, no irregularity at all.
* **curve**    -- the existing smooth-in-slot-index fits (NS / NSS / spline /
  cubic), which assume the strip should be smooth in calendar time.

Everything is compared at a **matched residual scale**, because a basis with
more effective freedom trivially explains more.
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "notebooks" / "backtests"))

import numpy as np
import pandas as pd

pd.set_option("display.width", 240, "display.max_columns", 60)

import sfr_kink_fade_common as K
from RVUtils.MeanRev.meetings import fomc_decisions, meeting_residual_panel
from RVUtils.MeanRev.signals import (
    curvefit_residual_signal, structure_signal_from_slots,
)

lab = K.load_kink_lab("3m", "liquid16", lam=10.0)
levels, st, c = lab["levels"], lab["struct"], lab["contracts"]
slot_panel = lab["slot_panel"]

REAL = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2032, 12, 31))
print(f"{len(REAL)} real meetings", flush=True)


def shifted(days):
    return [d + datetime.timedelta(days=int(days)) for d in REAL]


def even(anchor=datetime.date(2018, 1, 31), n=140, step=365.25 / 8.0):
    return [anchor + datetime.timedelta(days=int(round(step * i))) for i in range(n)]


def resid_fly(meetings, lam):
    r = meeting_residual_panel(c, meetings=meetings, lam=lam, max_slot=16)
    return structure_signal_from_slots(r, st, scale=1.0).reindex(
        index=levels.index, columns=levels.columns)


def score(name, sig, extra=""):
    r2 = 1.0 - sig.stack().var() / levels.stack().var()
    corr = float(pd.Series({k: levels[k].corr(sig[k])
                            for k in levels.columns}).median())
    return {"basis": name, "detail": extra, "resid_sd_bp": float(sig.stack().std()),
            "r2_explained": float(r2), "median_corr_with_raw": corr}


# --------------------------------------------------------------------------
# 1. explained variance at a MATCHED residual scale (~3.2bp)
# --------------------------------------------------------------------------
TARGET_SD = 3.2


def tune_lam(meetings, lo=0.05, hi=1e6, iters=26):
    """Bisect lam so the residual fly's sd lands on TARGET_SD."""
    for _ in range(iters):
        mid = float(np.sqrt(lo * hi))
        sd = float(resid_fly(meetings, mid).stack().std())
        if sd < TARGET_SD:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


rows = []
cases = [("real", REAL, ""), ("shifted +21d", shifted(21), ""),
         ("shifted +45d", shifted(45), ""), ("shifted -30d", shifted(-30), ""),
         ("even 8/yr", even(), "")]
lams = {}
for name, mt, extra in cases:
    lam = tune_lam(mt)
    lams[name] = lam
    rows.append({**score(name, resid_fly(mt, lam), extra), "lam": lam,
                 "n_meetings": len(mt)})

for form in ("ns", "nss", "spline", "poly3"):
    r = curvefit_residual_signal(slot_panel, st, form=form, scale=100.0)
    sig = r.reindex(index=levels.index, columns=levels.columns)
    rows.append({**score(f"curve:{form}", sig), "lam": np.nan, "n_meetings": 0})

out = pd.DataFrame(rows)
print("\n=== explained variance, residual scale matched to ~3.2bp where tunable ===",
      flush=True)
print(out.round(3).to_string(index=False), flush=True)

# --------------------------------------------------------------------------
# 2. does the residual PREDICT the forward move better than the decoys?
# --------------------------------------------------------------------------
print("\n=== forward-predictive power of each residual (pooled Spearman IC) ===",
      flush=True)
from scipy.stats import spearmanr  # noqa: E402

fwd = {h: levels.shift(-h) - levels for h in (5, 10, 21)}
rows = []
panels = {name: resid_fly(mt, lams[name]) for name, mt, _ in cases}
for form in ("nss", "spline"):
    panels[f"curve:{form}"] = curvefit_residual_signal(
        slot_panel, st, form=form, scale=100.0).reindex(
        index=levels.index, columns=levels.columns)
panels["raw fly"] = levels
for name, p in panels.items():
    row = {"basis": name}
    for h, f in fwd.items():
        a = p.to_numpy(dtype=float).ravel()
        b = f.to_numpy(dtype=float).ravel()
        ok = np.isfinite(a) & np.isfinite(b)
        row[f"ic_h{h}"] = float(spearmanr(a[ok], b[ok]).correlation)
        row[f"n_h{h}"] = int(ok.sum())
    rows.append(row)
print(pd.DataFrame(rows).round(4).to_string(index=False), flush=True)
print("  (negative IC = the residual mean-reverts: rich now -> falls)", flush=True)

# --------------------------------------------------------------------------
# 3. per-date cross-sectional IC, which is what a fade actually trades
# --------------------------------------------------------------------------
print("\n=== per-date cross-sectional IC (mean over dates, t across dates) ===",
      flush=True)
rows = []
for name, p in panels.items():
    row = {"basis": name}
    for h, f in fwd.items():
        ics = []
        for d in p.index:
            a = p.loc[d].to_numpy(dtype=float)
            b = f.loc[d].to_numpy(dtype=float)
            ok = np.isfinite(a) & np.isfinite(b)
            if ok.sum() < 6 or np.unique(a[ok]).size < 4:
                continue
            ic = spearmanr(a[ok], b[ok]).correlation
            if np.isfinite(ic):
                ics.append(ic)
        ics = np.asarray(ics)
        row[f"ic_h{h}"] = float(ics.mean()) if ics.size else np.nan
        row[f"t_h{h}"] = (float(ics.mean() / ics.std(ddof=1) * np.sqrt(ics.size))
                          if ics.size > 3 else np.nan)
    rows.append(row)
print(pd.DataFrame(rows).round(3).to_string(index=False), flush=True)
print("  t is NOT overlap-corrected -- treat as an ordering, not a p-value",
      flush=True)
print("DONE", flush=True)
