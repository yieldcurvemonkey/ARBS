"""Probe: is the calendar mechanism real in the LEVEL, even if it is useless as a signal?

Three things the placebo run does not answer.

1. **The direct test.** Theory says ``fly_k = sum_m delta_m * Phi_{k,m}``, so under
   a locally uniform path the cross-section of flies on a date should be
   proportional to the cross-section of ``phi_sum``, with a slope equal to the
   bp-per-meeting pace. Regressing one on the other per date and comparing the
   fitted slope with an independently measured pace is a falsifiable test of the
   mechanism that has nothing to do with whether it makes money.
2. **The 6m fly.** It carries 2.5-3x the dispersion for the same 3-leg cost, so
   its oracle bound is the one that matters.
3. **The tilt.** The prior lab's level-neutral fitted wing split was 0.463/0.537
   and it could not explain it. The calendar implies a *time-varying* split of
   the same magnitude. Do they line up?
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "notebooks" / "backtests"))

import numpy as np
import pandas as pd

pd.set_option("display.width", 240, "display.max_columns", 60)

import sfr_kink_fade_common as K
from RVUtils.MeanRev.signals import scale_only_zscore, zscore_signal

lab = K.load_kink_lab("3m", "liquid16", lam=100.0)
levels, st, cal = lab["levels"], lab["struct"], lab["calendar"]
phi = lab["phi"]

# --------------------------------------------------------------------------
# 1. per-date cross-sectional regression  fly ~ a + b * phi
# --------------------------------------------------------------------------
m = st[["as_of", "key", "value", "cm_slot"]].merge(
    cal[["as_of", "key", "phi_sum", "mtg_front", "mtg_back"]],
    on=["as_of", "key"], how="inner")
m["pace"] = ((m["leg_back"] if "leg_back" in m else 0) * 0)   # placeholder
legs = st[["as_of", "key", "leg0_value", "leg2_value"]]
m = m.merge(legs, on=["as_of", "key"], how="left")
m["pace"] = ((m["leg2_value"] - m["leg0_value"]) * 100.0
             / (m["mtg_back"] - m["mtg_front"]))

rows = []
for d, g in m.groupby("as_of"):
    g = g.dropna(subset=["value", "phi_sum", "pace"])
    if len(g) < 8 or g["phi_sum"].std() < 1e-9:
        continue
    X = np.column_stack([np.ones(len(g)), g["phi_sum"].to_numpy()])
    beta, *_ = np.linalg.lstsq(X, g["value"].to_numpy(), rcond=None)
    fit = X @ beta
    ss = float(((g["value"] - g["value"].mean()) ** 2).sum())
    rows.append({"date": d, "slope_bp_per_meeting": float(beta[1]),
                 "intercept": float(beta[0]),
                 "r2": float(1 - ((g["value"] - fit) ** 2).sum() / ss) if ss > 0 else np.nan,
                 "measured_pace": float(g["pace"].median())})
reg = pd.DataFrame(rows).set_index("date")
print("=== per-date cross-sectional regression: fly ~ a + b*phi ===", flush=True)
print(reg[["slope_bp_per_meeting", "measured_pace", "r2"]].describe()
      .round(3).to_string(), flush=True)
print(f"\n  corr(fitted slope, independently measured pace) = "
      f"{reg['slope_bp_per_meeting'].corr(reg['measured_pace']):+.3f}", flush=True)
print(f"  median |slope| = {reg['slope_bp_per_meeting'].abs().median():.2f} bp/meeting"
      f"   median |measured pace| = {reg['measured_pace'].abs().median():.2f}",
      flush=True)
print(f"  share of dates where the two agree in SIGN = "
      f"{float((np.sign(reg['slope_bp_per_meeting']) == np.sign(reg['measured_pace'])).mean()):.3f}",
      flush=True)
print(f"  median cross-sectional r2 of phi alone = {reg['r2'].median():.3f}", flush=True)

reg["regime"] = lab["regimes"].reindex(reg.index).to_numpy()
print("\n  by regime:", flush=True)
print(reg.groupby("regime")[["slope_bp_per_meeting", "measured_pace", "r2"]]
      .median().round(3).to_string(), flush=True)

# --------------------------------------------------------------------------
# 2. the 6m fly: where the dispersion is
# --------------------------------------------------------------------------
print("\n=== 6m fly ===", flush=True)
lab6 = K.load_kink_lab("6m", "liquid16", lam=100.0)
lv6 = lab6["levels"]
from RVUtils.MeanRev.signals import structure_signal_from_slots  # noqa: E402

mres6 = structure_signal_from_slots(lab6["resid_slots"], lab6["struct"],
                                    scale=1.0).reindex(index=lv6.index,
                                                       columns=lv6.columns)
print(f"  3m fly pooled sd {levels.stack().std():.2f}bp   "
      f"6m fly pooled sd {lv6.stack().std():.2f}bp   "
      f"ratio {lv6.stack().std() / levels.stack().std():.2f}x", flush=True)
sig6 = {"K0 raw z": zscore_signal(lv6, window=120),
        "K1 meeting resid": scale_only_zscore(mres6, window=120)}
t6 = K.selectivity_table(lv6, sig6, entry_z=2.0, gate=lab6["gate"],
                         horizons=(5, 10, 21), round_trip_bp=2.0)
print(t6.round(3).to_string(index=False), flush=True)

# --------------------------------------------------------------------------
# 3. calendar tilt vs the prior lab's fitted level-neutral wing split
# --------------------------------------------------------------------------
print("\n=== calendar tilt vs a fitted level-neutral wing split ===", flush=True)
tl = lab["tilted"]["front_share"]
print(f"  calendar front share: mean {tl.stack().mean():.4f}  "
      f"sd {tl.stack().std():.4f}  "
      f"range [{tl.stack().min():.4f}, {tl.stack().max():.4f}]", flush=True)

rows = []
for key in levels.columns:
    g = st[st["key"] == key]
    if len(g) < 250:
        continue
    f = g["leg0_value"].to_numpy(dtype=float) * 100.0
    b = g["leg1_value"].to_numpy(dtype=float) * 100.0
    k = g["leg2_value"].to_numpy(dtype=float) * 100.0
    # level-neutral fit: belly = w*front + (1-w)*back  ->  regress (b-k) on (f-k)
    y, x = b - k, f - k
    ok = np.isfinite(y) & np.isfinite(x)
    if ok.sum() < 100 or np.var(x[ok]) < 1e-12:
        continue
    w = float(np.dot(x[ok] - x[ok].mean(), y[ok] - y[ok].mean())
              / np.sum((x[ok] - x[ok].mean()) ** 2))
    cal_w = float(tl[key].mean()) if key in tl.columns else np.nan
    rows.append({"key": key, "fitted_front_share": w, "calendar_front_share": cal_w,
                 "cm": g["cm_label_short"].iloc[0]})
fit_tab = pd.DataFrame(rows)
print(f"  {len(fit_tab)} keys.  fitted front share: mean "
      f"{fit_tab['fitted_front_share'].mean():.4f}  "
      f"sd {fit_tab['fitted_front_share'].std():.4f}", flush=True)
print(f"  calendar front share (per-key mean): mean "
      f"{fit_tab['calendar_front_share'].mean():.4f}  "
      f"sd {fit_tab['calendar_front_share'].std():.4f}", flush=True)
print(f"  corr across keys = "
      f"{fit_tab['fitted_front_share'].corr(fit_tab['calendar_front_share']):+.3f}",
      flush=True)
print(fit_tab.round(4).head(12).to_string(index=False), flush=True)
print("DONE", flush=True)
