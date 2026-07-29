# %% [markdown]
# # SFR Fly Mean-Reversion — 1. Rolling z-score fade
#
# **Formulation: level z-score.** The oldest and most-used desk rule: standardise
# the fly against its own trailing distribution and fade the tails.
#
# The traded object is a butterfly of SR3 futures, `fly = 2*belly - front - back`
# in bp (the Query layer's `FLY RATE` convention). One package is 1 front + 2
# belly + 1 back = **4 contracts** and moves **$25 per bp of fly**; the league
# table sizes at 100 packages, so $2,500/bp and 400 contracts.
#
# Standing honesty rules, enforced by the engine rather than by the notebook:
# signal at close `t` fills at `t+1`; a deterministic exit (fixed horizon, max
# hold, stop, end of sample) is known at entry and is **not** lagged a second
# time; the round trip is charged once on the exit bar; gates apply at entry
# only. Both signs are always swept — mean reversion is a finding, not an
# assumption.
#
# Marks are **raw SR3 settlement prices**, never a fitted curve. That is a
# measured decision: `USD-SOFR-1D-Q16STIRT` on 2026-07-27 returned front rates
# 22–36bp away from the settles it is calibrated to and bit-identical rates
# across strip slots 8–14, and its fly correlates **−0.377** with the settle fly
# (`notebooks/rv/_probe_curve_vs_settle.py`). `Q12STIRT` reprices the same
# settles to 0.5bp. A backtest on the broken curve would have been trading its
# own interpolation error.

# %%
CONFIG = dict(
    # --- universe -----------------------------------------------------------
    structures=("3m", "6m"),        # 3m fly = slots (i,i+1,i+2); 6m = (i,i+2,i+4)
    primary_structure="3m",
    primary_window="liquid16",      # 2022+: every strip slot trades every session
    long_window="front8",           # 2019+: slots 1-8 only; buys ZIRP + hiking
    # --- costs (bp round trip on the package) -------------------------------
    cost_bp=1.5,                    # 3 legs x 2 sides x 0.25bp
    n_packages=100,                 # $2,500 per bp
    # --- grid ---------------------------------------------------------------
    windows=(40, 60, 120, 250),     # z-score lookback, business days
    mas=(1, 3, 5),                  # smoothing applied before standardising
    entry_zs=(1.0, 1.5, 2.0, 2.5),
    exits=("z0", "half", "t5", "t20"),
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

import dataclasses

from RVUtils.MeanRev import MRConfig, grid_search, run_backtest, run_continuous
from RVUtils.MeanRev.signals import bollinger_signal, zscore_signal
from sfr_fly_meanrev_common import (
    coverage_report, grid_block, header_block, league_row, load_lab,
    per_slot_table, regime_block, run_family, shadow_block, sign_test,
    three_panel_equity,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
GRID = {"window": CONFIG["windows"], "ma": CONFIG["mas"],
        "entry_z": CONFIG["entry_zs"], "exit_style": CONFIG["exits"],
        "direction": CONFIG["directions"]}
PARAMS = ["window", "ma", "entry_z", "exit_style", "direction"]
SIG = lambda L, window, ma: zscore_signal(L, window=window, ma=ma)   # noqa: E731

lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
print(f"{CONFIG['primary_structure']} / {CONFIG['primary_window']}: "
      f"{lab['levels'].shape[1]} absolute flies, {lab['levels'].shape[0]} sessions, "
      f"{lab['levels'].index.min().date()} -> {lab['levels'].index.max().date()}")
print(f"window rationale: {lab['window_why']}")
print(coverage_report(lab).round(2).to_string())

# %% [markdown]
# ## The economics before any backtest
#
# A butterfly's daily standard deviation falls from ~2.4bp at `SFR123` to ~0.4bp
# at `SFR-14-15-16`. Against a **1.5bp** round trip, the back of the strip has to
# move nearly four daily sigmas just to pay the spread. This table is the single
# most important thing in the notebook: it says in advance which slots can
# possibly support a mean-reversion program.

# %%
cov = coverage_report(lab)
cov["cost_in_daily_sd"] = CONFIG["cost_bp"] / cov["daily_sd_bp"]
cov["iqr_in_cost"] = cov["iqr_bp"] / CONFIG["cost_bp"]
print("round-trip cost expressed in daily sigmas, and IQR expressed in round trips:")
print(cov[["cm_slot", "pack", "daily_sd_bp", "iqr_bp", "cost_in_daily_sd",
           "iqr_in_cost"]].round(2).to_string())

# %% [markdown]
# ## Primary run — 3m flies, 2022+ (every slot liquid)

# %%
out = run_family("1. z-score fade (3m, liquid16)", lab=lab, signal_fn=SIG,
                 grid_spec=GRID, params=PARAMS, base=BASE, cls="level",
                 note="rolling z of the fly level; both signs swept")

# %% [markdown]
# ## Lag ablation — how much of the result is same-bar execution?
#
# Reported as an ablation only. Lag-0 assumes you can trade the close you used
# to form the signal; the prior lab measured that inflating gross P&L by 56–72%.

# %%
rows = []
for lag in (0, 1, 2):
    cfg = dataclasses.replace(out["config"], lag=lag)
    r = run_backtest(cfg, levels=lab["levels"], signal=out["signal"], gate=lab["gate"])
    rows.append({"lag": lag, **{k: r.metrics[k] for k in
                                ("n_trades", "hit_rate", "avg_net_bp",
                                 "total_net_bp", "sharpe")}})
lag_tbl = pd.DataFrame(rows)
print(lag_tbl.round(3).to_string(index=False))
if len(lag_tbl) > 1 and lag_tbl.loc[1, "total_net_bp"] != 0:
    infl = (lag_tbl.loc[0, "total_net_bp"] - lag_tbl.loc[1, "total_net_bp"])
    print(f"\n  lag-0 minus lag-1 = {infl:+.1f}bp of pure execution assumption")

# %% [markdown]
# ## Threshold versus continuous sizing
#
# A threshold rule is in or out; continuous sizing holds `-clip(z, ±2)` packages
# and rebalances daily, charging turnover rather than a round trip. If the edge
# is real but small, continuous sizing usually harvests more of it — at the cost
# of paying the spread far more often.

# %%
rows = []
for cap in (1.0, 2.0, 3.0):
    for cost in (0.0, CONFIG["cost_bp"]):
        cfg = dataclasses.replace(out["config"], round_trip_cost_bp=cost)
        r = run_continuous(cfg, levels=lab["levels"], signal=out["signal"],
                           gate=lab["gate"], cap=cap, n_legs=3)
        rows.append({"cap": cap, "round_trip_bp": cost,
                     "total_net_bp": r.metrics["total_net_bp"],
                     "sharpe": r.metrics["sharpe"],
                     "turnover": r.metrics.get("turnover", np.nan)})
print(pd.DataFrame(rows).round(3).to_string(index=False))

# %% [markdown]
# ## Bollinger variant — same algebra, different exit
#
# The band rule differs from the z rule only in where it closes: a touch of the
# centre line rather than a fixed horizon. An EMA centre adapts faster.

# %%
boll = run_family(
    "1b. Bollinger band-crossing (3m, liquid16)", lab=lab,
    signal_fn=lambda L, window, ma_type: bollinger_signal(L, window=window,
                                                          ma_type=ma_type),
    grid_spec={"window": (40, 60, 120), "ma_type": ("sma", "ema"),
               "entry_z": (1.5, 2.0, 2.5), "exit_z": (0.0, 0.5),
               "exit_style": ("band",), "direction": ("fade", "momentum")},
    params=["window", "ma_type", "entry_z", "exit_z", "direction"],
    base=BASE, cls="level", note="band crossing; exit at the centre line")

# %% [markdown]
# ## 6m flies, same window
#
# Wings two quarters from the belly. Levels and dispersion are roughly 2.5x the
# 3m fly, so the same 1.5bp round trip is a smaller fraction of the move.

# %%
lab6 = load_lab("6m", CONFIG["primary_window"])
out6 = run_family("1c. z-score fade (6m, liquid16)", lab=lab6, signal_fn=SIG,
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="level",
                  note="6m fly: slots (i, i+2, i+4), wings equidistant")

# %% [markdown]
# ## The long window — 2019+, front 8 slots only
#
# This is the sample-composition test. It buys ZIRP and the hiking cycle at the
# price of restricting the cross-section to slots 1–8, which is where the
# liquidity actually was before 2022.

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
print(f"{lab8['levels'].shape[1]} flies, {lab8['levels'].shape[0]} sessions, "
      f"{lab8['levels'].index.min().date()} -> {lab8['levels'].index.max().date()}")
out8 = run_family("1d. z-score fade (3m, front8, 2019+)", lab=lab8, signal_fn=SIG,
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="level",
                  note="long history, slots 1-8; the regime-composition test")

# %% [markdown]
# ## Per-slot breakdown of the primary config
#
# Pooling the strip hides the thing that matters: the front flies move enough to
# pay the spread and the back ones do not.

# %%
res = out["result"]
per = per_slot_table(res, lab)
if not per.empty:
    print(per.round(3).to_string(index=False))

# %%
if not res.trades.empty:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(per["cm"], per["total_net_bp"], color="#1f4e79")
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_title("1. z-score fade — net bp by constant-maturity slot "
                 f"(cost {CONFIG['cost_bp']}bp round trip)", fontsize=11)
    ax.set_ylabel("net bp")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    plt.show()

# %% [markdown]
# ## Verdict
#
# Read the league rows written above, not this cell: the grid median and the
# deflated Sharpe decide, and the linear-shadow block says whether the fly added
# anything over the belly outright and the two belly-versus-wing spreads.
