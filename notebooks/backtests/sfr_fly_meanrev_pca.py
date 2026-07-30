# %% [markdown]
# # SFR Fly Mean-Reversion — 4. PCA residual
#
# **Formulation: the fly's deviation from a fitted factor curve.**
#
# Fit a rolling PCA to the 16-slot strip, reconstruct each date's cross-section
# from its `k` leading factors, and take the residual. The fly's signal is the
# same weighted sum of its legs' residuals as its level is of its legs' rates —
# so the units stay bp and the object stays the traded package.
#
# The economic claim is different from a z-score. A z-score asks "is this fly
# high relative to its own history?"; a PCA residual asks "is this fly high
# relative to what the *rest of the curve* is doing today?". The second is
# cross-sectionally hedged, so it should be far less exposed to the regime drift
# that dominates the level (the OU notebook measured a median `mu` spread across
# regimes of several bp against a 1.5bp round trip).
#
# One eigendecomposition per **date**, not per fly — a per-structure rolling PCA
# would repeat the identical decomposition once for each of the 26 structures.
# Loadings are sign-aligned to the previous window so an eigenvector flip does
# not print as a spurious residual jump.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    pca_windows=(126, 261, 500),
    ks=(2, 3, 4),
    on=("levels", "changes"),
    z_window=120,
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "half", "t10"),
    directions=("fade", "momentum"),
    max_hold=30,
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
from RVUtils.MeanRev.signals import pca_residual_signal, zscore_signal
from RVUtils.mean_reversion import adf_pvalue, half_life, rolling_zscore
from sfr_fly_meanrev_common import (
    load_lab, per_slot_table, run_family,
)

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
levels, slot_panel, st = lab["levels"], lab["slot_panel"], lab["struct"]
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions; "
      f"strip panel {slot_panel.shape}")

# %% [markdown]
# ## 1. How much of the strip do 1-4 factors explain?
#
# If three factors explain essentially everything, the residual is measurement
# noise and there is nothing to trade. If they leave a persistent structured
# remainder, that remainder is where a fly lives.

# %%
X = slot_panel.dropna(axis=1, how="all").dropna()
for tag, M in (("levels", X.to_numpy()), ("changes", X.diff().dropna().to_numpy())):
    C = np.cov(M - M.mean(axis=0), rowvar=False)
    ev = np.sort(np.linalg.eigvalsh(C))[::-1]
    ev = ev / ev.sum()
    print(f"  {tag:8s}: explained variance by factor "
          f"{np.round(ev[:6] * 100, 2)}  cumulative "
          f"{np.round(np.cumsum(ev[:6]) * 100, 3)}")

# %% [markdown]
# ## 2. The residual series
#
# Built once at the middle grid setting so its properties can be inspected
# before anything is traded.

# %%
resid = pca_residual_signal(slot_panel, st, window=261, k=3, on="levels")
resid = resid.reindex(index=levels.index, columns=levels.columns)
print(f"residual panel {resid.shape}, non-NaN {resid.notna().to_numpy().mean():.1%}")
rows = []
for c in resid.columns:
    s = resid[c].dropna()
    if len(s) < 250:
        continue
    rows.append({"key": c, "sd_bp": s.std(), "hl": half_life(s),
                 "adf_p": adf_pvalue(s),
                 "corr_with_level": float(levels[c].corr(resid[c]))})
rs = pd.DataFrame(rows)
print(rs.describe().round(3).to_string())
print(f"\nstationary at 10%: {int((rs['adf_p'] < 0.10).sum())}/{len(rs)} keys")
print(f"median |corr| between the PCA residual and the raw fly level: "
      f"{rs['corr_with_level'].abs().median():.3f}")
print("  (a residual that is ~the level again has hedged nothing)")

# %%
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
pick = [c for c in resid.columns if resid[c].notna().sum() > 500][:4]
for c in pick:
    axes[0].plot(resid.index, resid[c].to_numpy(), lw=1.0, label=c)
axes[0].axhline(0, color="grey", lw=0.8)
axes[0].set_title("PCA residual of the fly (bp), k=3, window 261", fontsize=10)
axes[0].legend(fontsize=7)
axes[0].grid(alpha=0.25)
axes[1].scatter(rs["sd_bp"], rs["hl"], s=30, color="#1f4e79")
axes[1].set_xlabel("residual sd (bp)")
axes[1].set_ylabel("residual half-life (days)")
axes[1].axvline(CONFIG["cost_bp"], color="#c62828", ls="--", lw=1.0,
                label=f"round trip {CONFIG['cost_bp']}bp")
axes[1].set_title("is the residual bigger than the spread?", fontsize=10)
axes[1].legend(fontsize=8)
axes[1].grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 3. Backtest — z-scored PCA residual

# %%
def pca_sig(L, pca_window, k, on):
    r = pca_residual_signal(slot_panel, st, window=pca_window, k=k, on=on)
    r = r.reindex(index=L.index, columns=L.columns)
    return r.apply(lambda s: rolling_zscore(s, CONFIG["z_window"],
                                            min_periods=40, ddof=0))


GRID = {"pca_window": CONFIG["pca_windows"], "k": CONFIG["ks"], "on": CONFIG["on"],
        "entry_z": CONFIG["entry_zs"], "exit_style": CONFIG["exits"],
        "direction": CONFIG["directions"]}
PARAMS = ["pca_window", "k", "on", "entry_z", "exit_style", "direction"]
out = run_family("4. PCA residual (3m, liquid16)", lab=lab, signal_fn=pca_sig,
                 grid_spec=GRID, params=PARAMS, base=BASE, cls="pca",
                 note="rolling strip PCA; fly residual z-scored")

# %% [markdown]
# ## 4. Raw residual as the signal (no second standardisation)
#
# The residual is already in bp and already centred, so z-scoring it a second
# time is a modelling choice worth testing rather than assuming.

# %%
def pca_raw(L, pca_window, k):
    r = pca_residual_signal(slot_panel, st, window=pca_window, k=k, on="levels")
    return r.reindex(index=L.index, columns=L.columns)


out_raw = run_family(
    "4b. PCA residual, raw bp (no z)", lab=lab, signal_fn=pca_raw,
    grid_spec={"pca_window": (261, 500), "k": (3, 4),
               "entry_z": (1.0, 2.0, 4.0),        # here entry_z is in BP
               "exit_style": ("z0", "t10"), "direction": ("fade", "momentum")},
    params=["pca_window", "k", "entry_z", "exit_style", "direction"],
    base=BASE, cls="pca",
    note="entry threshold in bp of residual, not sigmas")

# %% [markdown]
# ## 5. Per-slot and long window

# %%
per = per_slot_table(out["result"], lab)
if not per.empty:
    print(per.round(3).to_string(index=False))

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
st8, sp8 = lab8["struct"], lab8["slot_panel"]


def pca_sig8(L, pca_window, k, on):
    r = pca_residual_signal(sp8, st8, window=pca_window, k=k, on=on)
    r = r.reindex(index=L.index, columns=L.columns)
    return r.apply(lambda s: rolling_zscore(s, CONFIG["z_window"],
                                            min_periods=40, ddof=0))


out8 = run_family("4c. PCA residual (3m, front8, 2019+)", lab=lab8,
                  signal_fn=pca_sig8,
                  grid_spec={"pca_window": (261, 500), "k": (3,), "on": ("levels",),
                             "entry_z": CONFIG["entry_zs"],
                             "exit_style": CONFIG["exits"],
                             "direction": CONFIG["directions"]},
                  params=["pca_window", "k", "on", "entry_z", "exit_style",
                          "direction"],
                  base=BASE, cls="pca", note="long history")
