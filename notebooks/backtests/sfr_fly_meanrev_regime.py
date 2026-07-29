# %% [markdown]
# # SFR Fly Mean-Reversion — 8. Regime and state filters
#
# **Formulation: trade the same signal, but only when the state says to.**
#
# Every framework so far applies one rule to every bar. This one asks whether the
# losses are concentrated in identifiable states, and whether gating them out
# leaves anything. The gates:
#
# * **Hurst exponent** — H < 0.5 mean-reverting, 0.5 random walk, > 0.5 trending.
#   Note the documented trap: under the `std` estimator a *deterministic* drift
#   cancels in `x_{t+l} − x_t`, so a strongly drifting fly reads H ≈ 0, not 1.
#   (The estimator this replaces returned `2 × slope` and measured H = 1.035 on a
#   pure random walk.)
# * **Variance ratio** — Lo-MacKinlay, with the heteroskedasticity-robust
#   z-statistic, so a conditionally heteroskedastic random walk is not rejected
#   as mean-reverting. That matters here: fly vol changes by a factor of three
#   between ZIRP and the hiking cycle.
# * **ADF** and **half-life** gates — only trade a fly whose recent window is
#   actually stationary and reverts on a usable horizon.
# * **Realised vol** — the cost is fixed at 1.5bp, so the move has to be big
#   enough to pay it.
# * **FOMC proximity** — flies price the velocity of the policy path.
# * **Curve level and slope** — the macro state.
#
# A gate that helps must beat the ungated rule *after* accounting for the trades
# it removed. A filter that only improves the average by deleting trades has not
# added information.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    base_z_window=120,
    entry_z=2.0,
    exit_style="z0",
    max_hold=20,
    lag=1,
    state_window=252,
    hurst_max_lag=20,
    vr_k=5,
    fomc_window=5,
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
from RVUtils.MeanRev.signals import zscore_signal
from RVUtils.mean_reversion import (
    adf_pvalue, half_life, hurst_exponent, rolling_half_life, rolling_hurst,
    variance_ratio, variance_ratio_stat,
)
from sfr_fly_meanrev_common import (
    header_block, league_row, load_lab, regime_block, shadow_block,
    three_panel_equity,
)

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"],
                entry_z=CONFIG["entry_z"], exit_style=CONFIG["exit_style"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
levels, gate0, st = lab["levels"], lab["gate"], lab["struct"]
sig = zscore_signal(levels, window=CONFIG["base_z_window"])
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions")

# %% [markdown]
# ## 1. Full-sample state statistics per fly
#
# Before gating anything: are these series mean-reverting at all by the standard
# diagnostics?

# %%
rows = []
for c in levels.columns:
    s = levels[c].dropna()
    if len(s) < 300:
        continue
    vr = variance_ratio_stat(s, k=CONFIG["vr_k"])
    rows.append({"key": c, "n": len(s), "sd_bp": s.std(),
                 "hurst_std": hurst_exponent(s, max_lag=100, method="std"),
                 "hurst_rs": hurst_exponent(s, max_lag=100, method="rs", min_lag=10),
                 "vr5": vr["vr"], "vr_z": vr["z"], "vr_p": vr["pvalue"],
                 "adf_p": adf_pvalue(s), "hl": half_life(s)})
state = pd.DataFrame(rows)
print(state.round(3).to_string(index=False))
print("\nsummary:")
print(state[["hurst_std", "hurst_rs", "vr5", "vr_z", "adf_p", "hl"]]
      .describe().round(3).to_string())
print(f"\n  H < 0.5 (mean-reverting) on {int((state['hurst_std'] < 0.5).sum())}"
      f"/{len(state)} keys")
print(f"  VR < 1 on {int((state['vr5'] < 1).sum())}/{len(state)}; "
      f"VR significantly < 1 (z < -1.96) on {int((state['vr_z'] < -1.96).sum())}")
print(f"  ADF stationary at 10% on {int((state['adf_p'] < 0.10).sum())}/{len(state)}")

# %%
fig, axes = plt.subplots(1, 3, figsize=(15, 4))
axes[0].hist(state["hurst_std"].dropna(), bins=18, color="#1f4e79")
axes[0].axvline(0.5, color="#c62828", lw=1.4, ls="--", label="random walk")
axes[0].set_title("Hurst exponent (std estimator)", fontsize=10)
axes[0].legend(fontsize=8)
axes[1].hist(state["vr5"].dropna(), bins=18, color="#2e7d32")
axes[1].axvline(1.0, color="#c62828", lw=1.4, ls="--", label="random walk")
axes[1].set_title(f"variance ratio, k={CONFIG['vr_k']}", fontsize=10)
axes[1].legend(fontsize=8)
axes[2].scatter(state["hl"], state["sd_bp"], s=30, color="#6a1b9a")
axes[2].set_xlabel("half-life (days)")
axes[2].set_ylabel("sd (bp)")
axes[2].axhline(CONFIG["cost_bp"], color="#c62828", ls="--", lw=1.0,
                label=f"round trip {CONFIG['cost_bp']}bp")
axes[2].set_title("reversion speed vs size of the move", fontsize=10)
axes[2].legend(fontsize=8)
for a in axes:
    a.grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Build the state panels
#
# All trailing, all causal.

# %%
W = CONFIG["state_window"]
hurst_p = pd.DataFrame({c: rolling_hurst(levels[c], window=W,
                                         max_lag=CONFIG["hurst_max_lag"], step=5)
                        for c in levels.columns}).reindex(levels.index)
hl_p = pd.DataFrame({c: rolling_half_life(levels[c], window=W)
                     for c in levels.columns}).reindex(levels.index)
vol_p = levels.diff().rolling(21, min_periods=10).std() * np.sqrt(252)
adf_p = pd.DataFrame(index=levels.index, columns=levels.columns, dtype=float)
for c in levels.columns:
    s = levels[c]
    vals = pd.Series(np.nan, index=s.index)
    for i in range(W - 1, len(s), 10):
        vals.iloc[i] = adf_pvalue(s.iloc[i - W + 1:i + 1])
    adf_p[c] = vals.ffill()

# curve level and slope from the strip
sp = lab["slot_panel"]
lvl = sp[[c for c in sp.columns if c <= 4]].mean(axis=1)
slope = (sp[[c for c in sp.columns if 13 <= c <= 16]].mean(axis=1)
         - sp[[c for c in sp.columns if c <= 4]].mean(axis=1)) * 100
lvl = lvl.reindex(levels.index).ffill()
slope = slope.reindex(levels.index).ffill()
print(f"state panels built: hurst {hurst_p.notna().to_numpy().mean():.0%} filled, "
      f"half-life {hl_p.notna().to_numpy().mean():.0%}, "
      f"adf {adf_p.notna().to_numpy().mean():.0%}")

# %% [markdown]
# ## 3. FOMC proximity
#
# Meeting dates come from the same repo helper the curve builder uses.

# %%
try:
    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
        get_fomc_meetings_list,
    )
    raw = get_fomc_meetings_list(as_of=levels.index[0].date(), n_plus_years=8)
    fomc = sorted({pd.Timestamp(getattr(d, "date", lambda: d)()
                                if not isinstance(d, pd.Timestamp) else d).normalize()
                   for d in raw})
    fomc = [d for d in fomc if levels.index[0] <= d <= levels.index[-1]]
except Exception as exc:
    print(f"FOMC list unavailable: {type(exc).__name__}: {exc}")
    fomc = []
print(f"{len(fomc)} FOMC dates inside the window")
days_to = pd.Series(np.nan, index=levels.index)
if fomc:
    fa = np.array([d.value for d in fomc])
    for i, d in enumerate(levels.index):
        diff = (fa - d.value) / 86_400_000_000_000
        fut = diff[diff >= 0]
        days_to.iloc[i] = fut.min() if len(fut) else np.nan

# %% [markdown]
# ## 4. Gate sweep
#
# Each gate is applied on top of the identical base signal and config, so the
# only thing that changes is which bars are eligible to open a trade.

# %%
def run_gate(name, mask):
    g = gate0 & mask.reindex(index=levels.index, columns=levels.columns).fillna(False)
    r = run_backtest(BASE, levels=levels, signal=sig, gate=g)
    m = r.metrics
    return {"gate": name, "bars_open_pct": float(g.to_numpy().mean()),
            "n_trades": m["n_trades"], "hit_rate": m["hit_rate"],
            "avg_net_bp": m["avg_net_bp"], "total_net_bp": m["total_net_bp"],
            "total_gross_bp": m["total_gross_bp"], "sharpe": m["sharpe"],
            "max_dd_bp": m["max_dd_bp"]}, r


ALL = pd.DataFrame(True, index=levels.index, columns=levels.columns)
gates = {
    "none (base)": ALL,
    "Hurst < 0.45": hurst_p < 0.45,
    "Hurst < 0.40": hurst_p < 0.40,
    "Hurst > 0.55 (trending)": hurst_p > 0.55,
    "half-life 3-60d": (hl_p >= 3) & (hl_p <= 60),
    "half-life 3-20d": (hl_p >= 3) & (hl_p <= 20),
    "ADF p < 0.10": adf_p < 0.10,
    "ADF p < 0.05": adf_p < 0.05,
    "realised vol top half": vol_p.gt(vol_p.median(axis=1), axis=0),
    "realised vol bottom half": vol_p.lt(vol_p.median(axis=1), axis=0),
}
if fomc:
    near = pd.DataFrame(np.repeat((days_to <= CONFIG["fomc_window"]).to_numpy()[:, None],
                                  levels.shape[1], axis=1),
                        index=levels.index, columns=levels.columns)
    gates[f"within {CONFIG['fomc_window']}d before FOMC"] = near
    gates[f"more than {CONFIG['fomc_window']}d from FOMC"] = ~near
steep = pd.DataFrame(np.repeat((slope > slope.median()).to_numpy()[:, None],
                               levels.shape[1], axis=1),
                     index=levels.index, columns=levels.columns)
gates["curve steep (upper half)"] = steep
gates["curve flat/inverted (lower half)"] = ~steep
high = pd.DataFrame(np.repeat((lvl > lvl.median()).to_numpy()[:, None],
                              levels.shape[1], axis=1),
                    index=levels.index, columns=levels.columns)
gates["front rates above median"] = high
gates["front rates below median"] = ~high

rows, results = [], {}
for name, mask in gates.items():
    row, r = run_gate(name, mask)
    rows.append(row)
    results[name] = r
gate_tbl = pd.DataFrame(rows).sort_values("total_net_bp", ascending=False)
print(gate_tbl.round(3).to_string(index=False))

# %%
base_row = gate_tbl[gate_tbl["gate"] == "none (base)"].iloc[0]
gate_tbl["vs_base_net_bp"] = gate_tbl["total_net_bp"] - base_row["total_net_bp"]
gate_tbl["net_bp_per_trade_vs_base"] = (gate_tbl["avg_net_bp"]
                                        - base_row["avg_net_bp"])
print("\nchange versus the ungated rule (a gate that only deletes trades is not "
      "information):")
print(gate_tbl[["gate", "bars_open_pct", "n_trades", "avg_net_bp",
                "net_bp_per_trade_vs_base", "total_net_bp", "vs_base_net_bp"]]
      .round(3).to_string(index=False))

# %%
fig, ax = plt.subplots(figsize=(12, 5))
g = gate_tbl.sort_values("avg_net_bp")
colors = ["#c62828" if v == "none (base)" else "#1f4e79" for v in g["gate"]]
ax.barh(g["gate"], g["avg_net_bp"], color=colors)
ax.axvline(0, color="grey", lw=0.9)
ax.axvline(base_row["avg_net_bp"], color="#c62828", ls="--", lw=1.2,
           label="ungated rule")
ax.set_xlabel("average net bp per trade")
ax.set_title("state filters, average net bp per trade "
             f"(cost {CONFIG['cost_bp']}bp round trip)", fontsize=11)
ax.legend(fontsize=8)
ax.grid(alpha=0.25, axis="x")
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 5. Best gate — full treatment
#
# The best row above is by construction the best of ~15 tried, so it gets the
# same scrutiny as any other selected config: regime split, shadow
# decomposition, and a league row that charges the search.

# %%
raw_best = gate_tbl.iloc[0]
usable = gate_tbl[gate_tbl["n_trades"] >= 30]
best_name = (usable.iloc[0]["gate"] if not usable.empty else raw_best["gate"])
best_res = results[best_name]
print(f"unrestricted best gate: {raw_best['gate']!r} with only "
      f"{int(raw_best['n_trades'])} trades ({raw_best['total_net_bp']:+.2f}bp) -- "
      f"a small-sample artifact, so the headline gate is the best one with at "
      f"least 30 trades: {best_name!r}")
pseudo_grid = pd.DataFrame({"total_net_bp": gate_tbl["total_net_bp"].to_numpy(),
                            "sharpe": gate_tbl["sharpe"].to_numpy(),
                            "n_trades": gate_tbl["n_trades"].to_numpy()})
header_block(f"8. Best state filter: {best_name}", best_res, grid=pseudo_grid,
             note=f"best of {len(gate_tbl)} gates with >=30 trades, on the same "
                  f"base signal and config")
three_panel_equity(best_res, f"8. best state filter — {best_name}")
plt.show()
regime_block(best_res, lab["regimes"], framework="8. Regime/state filter")
shadow_block(sig, lab, BASE, framework="8. Regime/state filter")
league_row("8. Regime/state filter", "best-gate", best_res, grid=pseudo_grid,
           cls="state",
           note=f"best of {len(gate_tbl)} gates with >=30 trades: {best_name}",
           window=str(lab["window"]), structure=str(lab["structure"]))

med_i = (gate_tbl["total_net_bp"] - gate_tbl["total_net_bp"].median()).abs().idxmin()
med_name = gate_tbl.loc[med_i, "gate"]
league_row("8. Regime/state filter", "median-gate", results[med_name],
           grid=pseudo_grid, cls="state",
           note=f"median gate of the sweep: {med_name}",
           window=str(lab["window"]), structure=str(lab["structure"]))

# %% [markdown]
# ## 6. Does the base rule work in ANY single regime?
#
# The most direct version of the sample-composition question: fit and trade
# inside one regime at a time.

# %%
reg = lab["regimes"]
rows = []
for name in ["ZIRP", "HIKING", "PLATEAU", "CUTTING"]:
    m = (reg == name).reindex(levels.index).fillna(False)
    if int(m.sum()) < 100:
        continue
    sub_lv = levels[m.to_numpy()]
    sub_sig = zscore_signal(sub_lv, window=CONFIG["base_z_window"])
    r = run_backtest(BASE, levels=sub_lv, signal=sub_sig,
                     gate=gate0[m.to_numpy()])
    mm = r.metrics
    rows.append({"regime": name, "n_days": int(m.sum()), "n_trades": mm["n_trades"],
                 "hit_rate": mm["hit_rate"], "avg_net_bp": mm["avg_net_bp"],
                 "total_gross_bp": mm["total_gross_bp"],
                 "total_net_bp": mm["total_net_bp"], "sharpe": mm["sharpe"]})
print("z-score fade FITTED AND TRADED inside one regime at a time:")
print(pd.DataFrame(rows).round(3).to_string(index=False))
