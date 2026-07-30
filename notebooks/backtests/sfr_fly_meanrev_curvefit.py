# %% [markdown]
# # SFR Fly Mean-Reversion — 6. Fitted-curve residual
#
# **Formulation: rich/cheap against a smooth curve through the strip.**
#
# Each date, fit a smooth function of maturity to the 16-slot strip —
# Nelson-Siegel, Svensson, a least-squares cubic spline, or a cubic polynomial —
# and take each contract's deviation from it. The fly's signal is the same
# weighted sum of its legs' deviations as its level is of its legs' rates.
#
# The fit is **cross-sectional on that date only**, so it carries no time-series
# look-ahead by construction — no window, no burn-in, no rolling statistic.
#
# There is a tension worth stating up front. A butterfly is already a second
# difference along the strip, and a smooth curve has small second differences by
# design, so the residual of a smooth fit is *almost* the fly again. The
# diagnostic below measures exactly how much: if the residual correlates ~1.0
# with the raw fly, this framework is the z-score notebook with extra steps.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    forms=("ns", "nss", "spline", "poly3"),
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
import time
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
from RVUtils.MeanRev.signals import curvefit_residual_signal
from RVUtils.mean_reversion import adf_pvalue, half_life, rolling_zscore
from sfr_fly_meanrev_common import load_lab, per_slot_table, run_family

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
levels, slot_panel, st = lab["levels"], lab["slot_panel"], lab["struct"]
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions")

# %% [markdown]
# ## 1. What the fits look like on one date

# %%
from RVUtils.curve_fit_rv import _ns_yield, _nss_yield
from scipy.interpolate import LSQUnivariateSpline
from scipy.optimize import least_squares

d = slot_panel.dropna().index[-1]
y = slot_panel.loc[d].dropna()
x = np.array([float(c) / 4.0 for c in y.index])
fits = {}
res = least_squares(lambda p: _ns_yield(x, *p) - y.to_numpy(),
                    [y.iloc[-1], y.iloc[0] - y.iloc[-1], 0.0, 2.0], max_nfev=800)
fits["ns"] = _ns_yield(x, *res.x)
res = least_squares(lambda p: _nss_yield(x, *p) - y.to_numpy(),
                    [y.iloc[-1], y.iloc[0] - y.iloc[-1], 0.0, 0.0, 2.0, 5.0],
                    max_nfev=800)
fits["nss"] = _nss_yield(x, *res.x)
fits["spline"] = LSQUnivariateSpline(x, y.to_numpy(),
                                     t=np.quantile(x, [0.33, 0.66]), k=3)(x)
fits["poly3"] = np.polyval(np.polyfit(x, y.to_numpy(), 3), x)

fig, axes = plt.subplots(1, 2, figsize=(14, 4))
axes[0].plot(x, y.to_numpy(), "o-", color="black", lw=1.4, ms=5, label="SR3 strip")
for k, v in fits.items():
    axes[0].plot(x, v, lw=1.2, alpha=0.85, label=k)
axes[0].set_xlabel("years along the strip")
axes[0].set_ylabel("rate (%)")
axes[0].set_title(f"strip and fits, {pd.Timestamp(d).date()}", fontsize=10)
axes[0].legend(fontsize=8)
axes[0].grid(alpha=0.25)
for k, v in fits.items():
    axes[1].plot(x, (y.to_numpy() - v) * 100, "o-", lw=1.1, ms=3, label=k)
axes[1].axhline(0, color="grey", lw=0.8)
axes[1].set_xlabel("years along the strip")
axes[1].set_ylabel("residual (bp)")
axes[1].set_title("per-contract residual", fontsize=10)
axes[1].legend(fontsize=8)
axes[1].grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Is the residual anything other than the fly?
#
# The residual panels are memoised per `(form, panel)`: the diagnostic below, the
# grid, and the raw-bp variant all want the same four panels, and each one is
# ~1,150 non-linear curve fits. Without the cache the notebook recomputes them
# about ten times over.

# %%
_RESID_CACHE = {}


def resid_panel(sp, struct, form, tag):
    k = (tag, form)
    if k not in _RESID_CACHE:
        _RESID_CACHE[k] = curvefit_residual_signal(sp, struct, form=form)
    return _RESID_CACHE[k]


rows = []
for form in CONFIG["forms"]:
    t0 = time.time()
    r = resid_panel(slot_panel, st, form, "primary")
    r = r.reindex(index=levels.index, columns=levels.columns)
    dt = time.time() - t0
    cors, sds, hls, adfs = [], [], [], []
    for c in r.columns:
        s = r[c].dropna()
        if len(s) < 250:
            continue
        cors.append(float(levels[c].corr(r[c])))
        sds.append(float(s.std()))
        hls.append(half_life(s))
        adfs.append(adf_pvalue(s))
    rows.append({"form": form, "seconds": dt, "n_keys": len(cors),
                 "median_corr_with_fly": np.nanmedian(cors),
                 "median_sd_bp": np.nanmedian(sds),
                 "median_hl": np.nanmedian(hls),
                 "pct_stationary": float(np.mean(np.array(adfs) < 0.10))})
diag = pd.DataFrame(rows)
print(diag.round(3).to_string(index=False))
print("\n  median_corr_with_fly near 1.0 means the 'curve residual' IS the fly, "
      "and this framework collapses into the z-score notebook.")

# %% [markdown]
# ## 3. Backtest

# %%
def cf_sig(L, form):
    r = resid_panel(slot_panel, st, form, "primary")
    r = r.reindex(index=L.index, columns=L.columns)
    return r.apply(lambda s: rolling_zscore(s, CONFIG["z_window"],
                                            min_periods=40, ddof=0))


GRID = {"form": CONFIG["forms"], "entry_z": CONFIG["entry_zs"],
        "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS = ["form", "entry_z", "exit_style", "direction"]
out = run_family("6. Fitted-curve residual (3m, liquid16)", lab=lab,
                 signal_fn=cf_sig, grid_spec=GRID, params=PARAMS, base=BASE,
                 cls="curvefit", note="NS / NSS / spline / cubic, z-scored")

# %% [markdown]
# ## 4. Raw residual in bp, no second standardisation

# %%
def cf_raw(L, form):
    r = resid_panel(slot_panel, st, form, "primary")
    return r.reindex(index=L.index, columns=L.columns)


out_raw = run_family(
    "6b. Fitted-curve residual, raw bp", lab=lab, signal_fn=cf_raw,
    grid_spec={"form": ("nss", "spline"), "entry_z": (1.0, 2.0, 4.0),
               "exit_style": ("z0", "t10"), "direction": ("fade", "momentum")},
    params=["form", "entry_z", "exit_style", "direction"],
    base=BASE, cls="curvefit", note="entry threshold in bp of residual")

# %% [markdown]
# ## 5. Per-slot and long window

# %%
per = per_slot_table(out["result"], lab)
if not per.empty:
    print(per.round(3).to_string(index=False))

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
st8, sp8 = lab8["struct"], lab8["slot_panel"]


def cf_sig8(L, form):
    r = resid_panel(sp8, st8, form, "front8")
    r = r.reindex(index=L.index, columns=L.columns)
    return r.apply(lambda s: rolling_zscore(s, CONFIG["z_window"],
                                            min_periods=40, ddof=0))


out8 = run_family("6c. Fitted-curve residual (3m, front8, 2019+)", lab=lab8,
                  signal_fn=cf_sig8,
                  grid_spec={"form": ("nss", "spline"),
                             "entry_z": CONFIG["entry_zs"],
                             "exit_style": CONFIG["exits"],
                             "direction": CONFIG["directions"]},
                  params=PARAMS, base=BASE, cls="curvefit", note="long history")
