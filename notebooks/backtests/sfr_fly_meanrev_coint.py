# %% [markdown]
# # SFR Fly Mean-Reversion — 3. Cointegration
#
# **Formulation: is `1/-2/1` actually the cointegrating vector?**
#
# A butterfly asserts weights `(-1, +2, -1)` on the three legs' rates. That is a
# convention, not an estimate. This notebook estimates the vector instead — by
# Engle-Granger (regress the belly on its two wings), by Johansen, and by
# Box-Tiao (the linear combination with the *slowest* variance ratio, i.e. the
# most mean-reverting portfolio) — and trades both the asserted and the fitted
# spread.
#
# If the fitted vector is far from `(0.5, 0.5)` on the wings, the traded fly is
# not the stationary combination and its "mean reversion" is partly a trend in
# whatever the fly is loading on that the fitted vector hedges out. If the fitted
# vector trades no better than the asserted one, the convention is fine and the
# extra estimation is noise.
#
# Box-Tiao and Johansen come from `arbitragelab`, which is installed editable in
# this environment (mapped to `RVUtils/arbitragelab`), so they are the reference
# implementations rather than re-derivations.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    coint_windows=(252, 500),      # rolling estimation window for the vector
    z_windows=(60, 120),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "half", "t10"),
    directions=("fade", "momentum"),
    max_hold=30,
    lag=1,
    refit_every=21,                # Johansen / Box-Tiao refit cadence
)
CONFIG

# %%
import sys
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import dataclasses

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig, run_backtest
from RVUtils.MeanRev.signals import coint_spread_signal, zscore_signal
from RVUtils.cointegration import engle_granger, johansen
from RVUtils.mean_reversion import adf_pvalue, half_life, rolling_zscore
from sfr_fly_meanrev_common import (
    header_block, league_row, load_lab, per_slot_table, regime_block, run_family,
    shadow_block, three_panel_equity,
)

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
st, levels = lab["struct"], lab["levels"]
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions")

# %% [markdown]
# ## 1. Full-sample Engle-Granger and Johansen per fly
#
# `beta_front + beta_back` near 1.0 with each near 0.5 is the butterfly. The
# Johansen vector is normalised so the belly weight is 1, then rescaled the same
# way, so the two are directly comparable to `(0.5, 0.5)`.

# %%
rows = []
for key, g in st.groupby("key"):
    g = g.sort_values("as_of")
    if len(g) < 300:
        continue
    idx = pd.DatetimeIndex(g["as_of"])
    f = pd.Series(g["leg0_value"].to_numpy(float), index=idx)
    b = pd.Series(g["leg1_value"].to_numpy(float), index=idx)
    k = pd.Series(g["leg2_value"].to_numpy(float), index=idx)
    X = pd.DataFrame({"f": f, "k": k})
    eg_f = engle_granger(b, f)
    eg_k = engle_granger(b, k)
    # two-regressor EG: belly on both wings
    import statsmodels.api as sm
    A = sm.add_constant(X.values)
    fit = sm.OLS(b.values, A).fit()
    resid = pd.Series(b.values - A @ fit.params, index=idx)
    asserted = pd.Series((2 * b - f - k).to_numpy(), index=idx)
    try:
        joh = johansen(pd.DataFrame({"b": b, "f": f, "k": k}))
        jv = joh["coint_vector"]
        jv = jv / jv[0] if abs(jv[0]) > 1e-9 else jv
        j_f, j_k, j_rank = -jv[1], -jv[2], joh["rank"]
    except Exception:
        j_f = j_k = np.nan
        j_rank = -1
    rows.append({
        "key": key, "n": len(g),
        "eg_b_front": fit.params[1], "eg_b_back": fit.params[2],
        "eg_sum": fit.params[1] + fit.params[2],
        "joh_front": j_f, "joh_back": j_k, "joh_rank": j_rank,
        "adf_fitted": adf_pvalue(resid), "adf_asserted": adf_pvalue(asserted),
        "hl_fitted": half_life(resid * 100), "hl_asserted": half_life(asserted * 100),
    })
vec = pd.DataFrame(rows)
print(vec.round(3).to_string(index=False))
print("\nsummary (the butterfly convention is beta_front = beta_back = 0.5):")
print(vec[["eg_b_front", "eg_b_back", "eg_sum", "joh_front", "joh_back",
           "adf_fitted", "adf_asserted", "hl_fitted", "hl_asserted"]]
      .describe().round(3).to_string())
print(f"\nfitted spread stationary at 10%: "
      f"{int((vec['adf_fitted'] < 0.10).sum())}/{len(vec)} keys")
print(f"asserted fly stationary at 10%:   "
      f"{int((vec['adf_asserted'] < 0.10).sum())}/{len(vec)} keys")

# %%
fig, axes = plt.subplots(1, 2, figsize=(13, 4))
axes[0].scatter(vec["eg_b_front"], vec["eg_b_back"], s=28, color="#1f4e79",
                label="Engle-Granger")
axes[0].scatter(vec["joh_front"], vec["joh_back"], s=28, color="#c62828",
                marker="^", alpha=0.75, label="Johansen")
axes[0].scatter([0.5], [0.5], s=180, marker="*", color="black",
                label="asserted 1/-2/1", zorder=5)
axes[0].set_xlabel("weight on the front wing")
axes[0].set_ylabel("weight on the back wing")
axes[0].set_title("fitted cointegrating vectors vs the butterfly convention",
                  fontsize=10)
axes[0].legend(fontsize=8)
axes[0].grid(alpha=0.25)
axes[1].scatter(vec["hl_asserted"], vec["hl_fitted"], s=28, color="#2e7d32")
lim = np.nanpercentile(np.concatenate([vec["hl_asserted"].to_numpy(),
                                       vec["hl_fitted"].to_numpy()]), 95)
axes[1].plot([0, lim], [0, lim], color="grey", lw=0.9, ls="--")
axes[1].set_xlim(0, lim)
axes[1].set_ylim(0, lim)
axes[1].set_xlabel("half-life of the asserted fly (days)")
axes[1].set_ylabel("half-life of the fitted spread (days)")
axes[1].set_title("does fitting the vector speed up reversion?", fontsize=10)
axes[1].grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Box-Tiao — the most mean-reverting combination
#
# Box-Tiao finds the linear combination of the three legs with the smallest
# predictable-to-total variance ratio, i.e. the *fastest* reverting portfolio
# available from these legs. It is the strongest possible statement of "if any
# combination of these three contracts mean-reverts, it is this one" — so if
# Box-Tiao's own portfolio does not survive costs, no weighting of the legs will.

# %%
try:
    from arbitragelab.hedge_ratios import get_box_tiao_hedge_ratio
    HAVE_BT = True
except Exception as exc:
    print(f"arbitragelab Box-Tiao unavailable: {type(exc).__name__}: {exc}")
    HAVE_BT = False

bt_rows = []
if HAVE_BT:
    for key, g in st.groupby("key"):
        g = g.sort_values("as_of")
        if len(g) < 300:
            continue
        idx = pd.DatetimeIndex(g["as_of"])
        df = pd.DataFrame({"b": g["leg1_value"].to_numpy(float),
                           "f": g["leg0_value"].to_numpy(float),
                           "k": g["leg2_value"].to_numpy(float)}, index=idx)
        try:
            hedge, _, _, resid = get_box_tiao_hedge_ratio(df, dependent_variable="b")
        except Exception:
            continue
        w = {kk: float(v) for kk, v in hedge.items()}
        s = pd.Series(resid, index=idx) * 100
        bt_rows.append({"key": key, "w_b": w.get("b", np.nan),
                        "w_front": -w.get("f", np.nan), "w_back": -w.get("k", np.nan),
                        "hl": half_life(s), "adf": adf_pvalue(s), "sd_bp": s.std()})
if bt_rows:
    bt = pd.DataFrame(bt_rows)
    print(bt.round(3).to_string(index=False))
    print("\nBox-Tiao weights vs the butterfly's (0.5, 0.5) on the wings:")
    print(bt[["w_front", "w_back", "hl", "adf", "sd_bp"]].describe().round(3).to_string())
    print(f"\nBox-Tiao spread half-life median {bt['hl'].median():.1f}d vs "
          f"asserted fly {vec['hl_asserted'].median():.1f}d")
else:
    bt = pd.DataFrame()
    print("no Box-Tiao rows")

# %% [markdown]
# ## 3. Backtest — the ASSERTED fly, z-scored (the benchmark)

# %%
GRID_A = {"window": CONFIG["z_windows"], "entry_z": CONFIG["entry_zs"],
          "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS_A = ["window", "entry_z", "exit_style", "direction"]
out_a = run_family("3. Asserted fly, z-scored (benchmark)", lab=lab,
                   signal_fn=lambda L, window: zscore_signal(L, window=window),
                   grid_spec=GRID_A, params=PARAMS_A, base=BASE, cls="coint",
                   note="the 1/-2/1 convention, standardised")

# %% [markdown]
# ## 4. Backtest — the FITTED (rolling Engle-Granger) spread
#
# Important: the P&L is still marked on the **traded** fly, because a fitted
# vector with non-integer weights is not what gets executed. The fitted spread
# supplies the *signal*; the butterfly remains the instrument. Trading the fitted
# weights themselves would need per-leg contract counts and a different cost
# model, and is out of scope here.

# %%
def coint_sig(L, coint_window, z_window):
    return coint_spread_signal(st, window=coint_window, z_window=z_window)["signal"] \
        .reindex(index=L.index, columns=L.columns)


GRID_B = {"coint_window": CONFIG["coint_windows"], "z_window": CONFIG["z_windows"],
          "entry_z": CONFIG["entry_zs"], "exit_style": CONFIG["exits"],
          "direction": CONFIG["directions"]}
PARAMS_B = ["coint_window", "z_window", "entry_z", "exit_style", "direction"]
out_b = run_family("3b. Fitted EG spread signal, fly traded", lab=lab,
                   signal_fn=coint_sig, grid_spec=GRID_B, params=PARAMS_B,
                   base=BASE, cls="coint",
                   note="rolling belly-on-wings residual as the signal")

# %% [markdown]
# ## 5. Head to head
#
# The comparison that matters: does estimating the vector beat asserting it?

# %%
cmp = pd.DataFrame([
    {"variant": "asserted 1/-2/1 z-score",
     "median_net_bp": out_a["grid"]["total_net_bp"].median(),
     "best_net_bp": out_a["grid"]["total_net_bp"].max(),
     "pct_positive": (out_a["grid"]["total_net_bp"] > 0).mean(),
     "best_sharpe": out_a["grid"]["sharpe"].max()},
    {"variant": "fitted EG residual z-score",
     "median_net_bp": out_b["grid"]["total_net_bp"].median(),
     "best_net_bp": out_b["grid"]["total_net_bp"].max(),
     "pct_positive": (out_b["grid"]["total_net_bp"] > 0).mean(),
     "best_sharpe": out_b["grid"]["sharpe"].max()},
])
print(cmp.round(3).to_string(index=False))

# %% [markdown]
# ## 6. Long window

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
out8 = run_family("3c. Asserted fly z-score (3m, front8, 2019+)", lab=lab8,
                  signal_fn=lambda L, window: zscore_signal(L, window=window),
                  grid_spec=GRID_A, params=PARAMS_A, base=BASE, cls="coint",
                  note="long history")
