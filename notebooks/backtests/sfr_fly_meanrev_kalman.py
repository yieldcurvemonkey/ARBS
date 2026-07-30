# %% [markdown]
# # SFR Fly Mean-Reversion — 5. Kalman filter
#
# **Formulation: a fair value formed before the print, and drifting hedge ratios.**
#
# Two distinct uses of the same machinery:
#
# 1. **Local level.** State `m_t = m_{t-1} + w_t`, observation `y_t = m_t + v_t`.
#    The one-step-ahead prior uses information only through `t-1`, so the
#    standardised innovation `z = (y_t - prior_t)/sqrt(pred_var_t)` is a genuine
#    surprise. A trailing z-score, by contrast, compares today's print to a mean
#    that already contains it. `q/r` is the only knob: larger means a
#    faster-adapting fair value and a shorter memory.
#
# 2. **Dynamic hedge ratios.** Regress the belly on its two wings with
#    coefficients that follow a random walk. This is the honest alternative to
#    asserting `1/-2/1`, and unlike the rolling regression in the cointegration
#    notebook it has no window discontinuity.
#
# Both signals are causal by construction, which is the reason to prefer them:
# `test_kalman_local_level_prior_is_causal` in `tests/test_rv_meanrev_core.py`
# pins that perturbing `y[t]` cannot move `prior[t]`.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    qs=(1e-5, 1e-4, 1e-3, 1e-2),   # state noise / observation noise ratio
    r_obs=1.0,
    deltas=(1e-6, 1e-4),           # hedge-ratio drift
    entry_zs=(1.5, 2.0, 2.5, 3.0),
    exits=("z0", "half", "t5", "t10"),
    directions=("fade", "momentum"),
    max_hold=20,
    lag=1,
)
CONFIG

# %%
import sys
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig
from RVUtils.MeanRev.signals import kalman_level_signal
from RVUtils.mean_reversion import (
    adf_pvalue, half_life, kalman_hedge_ratio, kalman_local_level,
)
from sfr_fly_meanrev_common import load_lab, per_slot_table, run_family

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
levels, st = lab["levels"], lab["struct"]
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions")

# %% [markdown]
# ## 1. What the filter's fair value looks like
#
# The gap between the print and the prior is the tradeable quantity. If the
# filter tracks the level closely the innovation is tiny and there is nothing to
# fade; if it lags badly the innovation is mostly trend.

# %%
pick = [c for c in levels.columns if levels[c].notna().sum() > 700][:2]
fig, axes = plt.subplots(len(pick), 2, figsize=(14, 3.4 * len(pick)),
                         squeeze=False)
for i, c in enumerate(pick):
    s = levels[c].dropna()
    kf = kalman_local_level(s, q=1e-3, r=1.0)
    axes[i][0].plot(s.index, s.to_numpy(), lw=1.0, color="#1f4e79", label="fly (bp)")
    axes[i][0].plot(kf.index, kf["prior"].to_numpy(), lw=1.0, color="#c62828",
                    label="Kalman prior (t-1 information)")
    axes[i][0].set_title(f"{c} — level vs filtered fair value", fontsize=10)
    axes[i][0].legend(fontsize=7)
    axes[i][0].grid(alpha=0.25)
    axes[i][1].plot(kf.index, kf["z"].to_numpy(), lw=0.9, color="#2e7d32")
    axes[i][1].axhline(0, color="grey", lw=0.7)
    for lev in (-2, 2):
        axes[i][1].axhline(lev, color="grey", lw=0.6, ls="--")
    axes[i][1].set_title(f"{c} — standardised innovation", fontsize=10)
    axes[i][1].grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Innovation properties across the panel
#
# A well-specified filter leaves innovations that are close to white noise. If
# they are strongly negatively autocorrelated the level over-reacts bar to bar
# (fadeable); if positively, it trends.

# %%
rows = []
for q in CONFIG["qs"]:
    sig = kalman_level_signal(levels, q=q, r=CONFIG["r_obs"])
    ac = []
    for c in sig.columns:
        s = sig[c].dropna()
        if len(s) > 200:
            ac.append(float(s.autocorr(1)))
    rows.append({"q": q, "n_keys": len(ac), "mean_ac1": np.mean(ac),
                 "median_ac1": np.median(ac),
                 "mean_abs_z": float(sig.abs().stack().mean()),
                 "pct_beyond_2": float((sig.abs() > 2).to_numpy().mean())})
print("innovation diagnostics by filter speed:")
print(pd.DataFrame(rows).round(4).to_string(index=False))
print("\n  negative lag-1 autocorrelation of the innovation = bar-to-bar "
      "over-reaction, which is what a fade rule monetises.")

# %% [markdown]
# ## 3. Backtest — local-level innovation

# %%
GRID = {"q": CONFIG["qs"], "entry_z": CONFIG["entry_zs"],
        "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS = ["q", "entry_z", "exit_style", "direction"]
out = run_family("5. Kalman local-level (3m, liquid16)", lab=lab,
                 signal_fn=lambda L, q: kalman_level_signal(L, q=q,
                                                            r=CONFIG["r_obs"]),
                 grid_spec=GRID, params=PARAMS, base=BASE, cls="kalman",
                 note="standardised one-step-ahead innovation")

# %% [markdown]
# ## 4. Dynamic hedge ratios
#
# The belly regressed on both wings with drifting coefficients. Two things to
# read: where the coefficients actually sit relative to the butterfly's implied
# `(0.5, 0.5)`, and whether the resulting residual is more tradeable than the
# asserted fly.

# %%
hr_rows, hr_sig = [], {}
for key, g in st.groupby("key"):
    g = g.sort_values("as_of")
    if len(g) < 300:
        continue
    idx = pd.DatetimeIndex(g["as_of"])
    y = pd.Series(g["leg1_value"].to_numpy(float), index=idx)
    Xw = pd.DataFrame({"front": g["leg0_value"].to_numpy(float),
                       "back": g["leg2_value"].to_numpy(float)}, index=idx)
    kh = kalman_hedge_ratio(y, Xw, delta=1e-4, r=1e-3)
    hr_sig[key] = kh["z"]
    hr_rows.append({"key": key,
                    "beta_front_end": kh["beta_front"].iloc[-1],
                    "beta_back_end": kh["beta_back"].iloc[-1],
                    "beta_front_sd": kh["beta_front"].std(),
                    "beta_back_sd": kh["beta_back"].std(),
                    "resid_sd_bp": kh["resid"].std() * 100,
                    "resid_hl": half_life(kh["resid"] * 100)})
hr = pd.DataFrame(hr_rows)
print(hr.round(3).to_string(index=False))
print("\nthe butterfly asserts beta_front = beta_back = 0.5:")
print(hr[["beta_front_end", "beta_back_end", "beta_front_sd", "beta_back_sd",
          "resid_sd_bp", "resid_hl"]].describe().round(3).to_string())

# %%
def hedge_sig(L, delta):
    out = {}
    for key, g in st.groupby("key"):
        g = g.sort_values("as_of")
        if len(g) < 200:
            continue
        idx = pd.DatetimeIndex(g["as_of"])
        y = pd.Series(g["leg1_value"].to_numpy(float), index=idx)
        Xw = pd.DataFrame({"front": g["leg0_value"].to_numpy(float),
                           "back": g["leg2_value"].to_numpy(float)}, index=idx)
        out[key] = kalman_hedge_ratio(y, Xw, delta=delta, r=1e-3)["z"]
    return pd.DataFrame(out).reindex(index=L.index, columns=L.columns)


out_hr = run_family(
    "5b. Kalman dynamic hedge ratio (3m, liquid16)", lab=lab, signal_fn=hedge_sig,
    grid_spec={"delta": CONFIG["deltas"], "entry_z": CONFIG["entry_zs"],
               "exit_style": ("z0", "t5", "t10"),
               "direction": CONFIG["directions"]},
    params=["delta", "entry_z", "exit_style", "direction"],
    base=BASE, cls="kalman",
    note="belly on wings with drifting betas; fly still the traded package")

# %% [markdown]
# ## 5. Per-slot and long window

# %%
per = per_slot_table(out["result"], lab)
if not per.empty:
    print(per.round(3).to_string(index=False))

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
out8 = run_family("5c. Kalman local-level (3m, front8, 2019+)", lab=lab8,
                  signal_fn=lambda L, q: kalman_level_signal(L, q=q,
                                                             r=CONFIG["r_obs"]),
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="kalman",
                  note="long history")
