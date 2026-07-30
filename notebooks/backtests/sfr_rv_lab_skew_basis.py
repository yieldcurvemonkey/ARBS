# %% [markdown]
# # SR3 RV Lab — Framework 1: the skew basis (risk-reversal spread across expiries)
#
# **RV class: A/B — within-contract shape, coupled across two expiries.**
#
# The traded object is a 4-leg package: long the back contract's risk reversal
# (long hike wing = put on price, short cut wing = call on price) against short
# the front contract's risk reversal, with all four strikes fixed on the
# execution date at the listed strikes nearest `forward ± offset`.
#
# `signal = RR_back - RR_front` in bp of listed settle premium. This is the same
# object the P&L is marked on — signal and mark are one executable structure, so
# there is no model-vs-market wedge to fool us.
#
# Why this is not pinned by parity: put-call parity fixes `C - P` at a common
# strike to `F - K`. It says nothing about the *difference between two different
# strikes' premiums* (that is the skew), and nothing about how that difference
# compares across two expiries. The level of the RR spread is genuinely free.
#
# Honesty rules in force: listed marks only, lag-1 fills, entry gates on BL
# surface quality, costs charged per completed trade, and both signs tested.

# %%
CONFIG = dict(
    wing_offset=0.375,        # percent from the forward to each wing
    strike_tol=0.13,          # max distance from the target strike (percent)
    min_oi=100,               # per-leg open-interest floor for strike selection
    pair_gaps=(1, 2),         # 1 = adjacent quarterlies, 2 = 6-month pairs
    contracts_per_leg=100,    # package size for the dollar column
    cost_bp=2.5,              # headline round-trip cost on the package
    zscore_windows=(60, 120),
    mas=(1, 5, 10),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "half", "t10"),
    directions=("fade", "momentum"),
    entry_every=(1, 5),       # 1 = daily, 5 = weekly rebalance
)
CONFIG

# %%
import dataclasses
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sfr_rv_lab_common import (
    LabConfig, config_from_row, coverage_report, cost_block, exit_comparison,
    gate_sensitivity, grid_block, header_block, league_row, load_lab,
    marks_x_lag_panel, median_row, stability_block, three_panel_equity,
)
from RVUtils.SFRRVLab import (
    Leg, Structure, add_event_distance, grid_search, pair_rr_basis,
    risk_reversal_panel, run_backtest,
)

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)

lab = load_lab()
print(coverage_report(lab).to_string())

# %% [markdown]
# ## Signal panel
#
# One row per (adjacent pair, date): the premium-native RR spread plus the four
# strikes that produced it, and the AND of both legs' BL quality gates.

# %%
rr = risk_reversal_panel(lab["quotes"], lab["contracts"],
                         offset=CONFIG["wing_offset"], tol=CONFIG["strike_tol"],
                         min_oi=CONFIG["min_oi"])
basis = pair_rr_basis(rr, quality=lab["gate"], gaps=CONFIG["pair_gaps"])
basis = add_event_distance(basis)
print(f"pairs ({basis['key'].nunique()}): {sorted(basis['key'].unique())}")
print(f"rows: {len(basis)}   leg gate: {basis['gate'].mean():.1%}   "
      f"BL gate: {basis['gate_bl'].mean():.1%}")
print(basis.groupby("key")["signal"].describe().round(2).to_string())

# %% [markdown]
# ### Model-mark comparison series (for the honesty panel only)
#
# The BL mean-minus-median skew basis, `mm_back - mm_front`. Prior work measured
# its P&L as *anti*-correlated with the executable one; it is carried here purely
# so the marks x lag panel can show that again on this sample.

# %%
c = lab["contracts"]
mm = c.set_index(["as_of", "symbol"])["mm_bp"]
model_rows = []
for key, sub in basis.groupby("key"):
    f, b = key.split("-")
    mf = mm.reindex(pd.MultiIndex.from_arrays([sub["as_of"], [f] * len(sub)]))
    mb = mm.reindex(pd.MultiIndex.from_arrays([sub["as_of"], [b] * len(sub)]))
    m = sub.copy()
    m["signal"] = (mb.to_numpy() - mf.to_numpy())
    model_rows.append(m)
model_basis = pd.concat(model_rows, ignore_index=True).dropna(subset=["signal"])
print(f"model-mark signal rows: {len(model_basis)}")

# %% [markdown]
# ## The tradeable package
#
# Strikes are read off the signal frame at the **execution** date, so the entry
# never uses a strike chosen with information from the signal bar.

# %%
BASIS_IDX = basis.set_index(["key", "as_of"]).sort_index()


def builder(key, exec_date, direction):
    try:
        r = BASIS_IDX.loc[(key, exec_date)]
    except KeyError:
        return None
    if isinstance(r, pd.DataFrame):
        r = r.iloc[0]
    front, back = key.split("-")
    return Structure((
        Leg("option", back, 1.0, "P", float(r["hk_K_b"])),
        Leg("option", back, -1.0, "C", float(r["ct_K_b"])),
        Leg("option", front, -1.0, "P", float(r["hk_K_f"])),
        Leg("option", front, 1.0, "C", float(r["ct_K_f"])),
    ), label=f"RRspread {key}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"],
                 quality_gate=True)

# %% [markdown]
# ## Grid — both directions, full sweep
#
# The distribution comes first; the top rows are selection-inflated by
# construction and are shown only after it.

# %%
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style",
          "entry_every"]
grid = grid_search(
    {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
     "zscore_window": list(CONFIG["zscore_windows"]),
     "entry_min_zscore": list(CONFIG["entry_zs"]),
     "exit_style": list(CONFIG["exits"]),
     "entry_every": list(CONFIG["entry_every"])},
    signals=basis, book=lab["book"], builder=builder, base=BASE,
    show_progress=True)
print(f"\n{len(grid)} configs, {int(grid['n_trades'].sum())} trades in total")

# %%
best = grid_block(grid, PARAMS)
_ = stability_block(grid, best, PARAMS)

# %% [markdown]
# ### Which sign wins?
#
# The house rule: never assume mean-reversion. If momentum's distribution is
# better than fade's, that is the finding.

# %%
sign_test = (grid.groupby("direction")
             .agg(n_configs=("total_net_bp", "size"),
                  median_net_bp=("total_net_bp", "median"),
                  pct_positive=("total_net_bp", lambda s: (s > 0).mean()),
                  best_net_bp=("total_net_bp", "max"),
                  median_trades=("n_trades", "median"))
             .round(3))
print(sign_test.to_string())

# %% [markdown]
# ## Best honest config

# %%
best_cfg = config_from_row(BASE, best, PARAMS)
res = run_backtest(best_cfg, signals=basis, book=lab["book"], builder=builder)
_ = header_block("Skew basis — best config", res, grid=grid)
fig = three_panel_equity(res, "Skew basis (best config)")
plt.show()

# %%
if not res.trades.empty:
    print(res.trades.sort_values("entry").to_string(index=False))

# %% [markdown]
# ## Honesty panels

# %%
print("EXIT COMPARISON")
print(exit_comparison(best_cfg, signals=basis, book=lab["book"],
                      builder=builder).to_string(index=False))

# %%
print("MARKS x LAG (same structure, same listed P&L marks — only the signal "
      "source and the fill lag change)")
mxl = marks_x_lag_panel(best_cfg, signals=basis, book=lab["book"],
                        builder=builder, model_signals=model_basis)
print(mxl.to_string(index=False))
if "lag_inflation" in mxl.attrs:
    print(f"\nsame-bar (lag 0) gross inflation: {mxl.attrs['lag_inflation']:.1%}")

# %%
_ = cost_block(res)

# %% [markdown]
# ### What each entry gate costs
#
# `gate` is leg-level (both wings listed and OI-screened). `gate_bl` is the
# stricter Breeden-Litzenberger surface rule from the spec. On this panel the BL
# rule mostly rejects days when the listed chain is too narrow for the density to
# integrate to one (`pre_norm_mass` sits *below* 1, i.e. truncation) rather than
# days when the two traded wings are stale — so it is reported, not assumed.

# %%
print(gate_sensitivity(best_cfg, signals=basis, book=lab["book"],
                       builder=builder).to_string(index=False))

# %% [markdown]
# ## Variant: FOMC event-window entries only
#
# Enter only in the five business days before a meeting; everything else is
# unchanged. This tests whether the basis carries event information rather than
# a permanent premium.

# %%
ev = basis.copy()
ev["eligible"] = ev["days_to_fomc"].between(-7, -1)
print(f"eligible bars: {ev['eligible'].mean():.1%}")
grid_ev = grid_search(
    {"direction": list(CONFIG["directions"]), "ma": [1, 5],
     "entry_min_zscore": [1.0, 1.5, 2.0], "exit_style": ["t5", "t10", "z0"]},
    signals=ev, book=lab["book"], builder=builder, base=BASE)
best_ev = grid_block(grid_ev, ["direction", "ma", "entry_min_zscore", "exit_style"])

# %%
res_ev = run_backtest(
    config_from_row(BASE, best_ev, ["direction", "ma", "entry_min_zscore",
                                    "exit_style"]),
    signals=ev, book=lab["book"], builder=builder)
_ = header_block("Skew basis — FOMC window", res_ev, grid=grid_ev)
if not res_ev.daily_bp.empty:
    fig = three_panel_equity(res_ev, "Skew basis (FOMC window)")
    plt.show()

# %% [markdown]
# ## Delta-hedged variant
#
# The 4-leg risk-reversal spread is not delta-neutral: the two contracts' wings
# do not cancel. Killing each contract's delta daily on its own future isolates
# the skew content from the residual direction, exactly as in the digital
# calendar. If the edge disappears here, it was direction.

# %%
BASE_HEDGED = dataclasses.replace(BASE, delta_hedge="daily", future_leg_bp=0.25)
grid_h = grid_search(
    {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
     "zscore_window": list(CONFIG["zscore_windows"]),
     "entry_min_zscore": list(CONFIG["entry_zs"]),
     "exit_style": list(CONFIG["exits"])},
    signals=basis, book=lab["book"], builder=builder, base=BASE_HEDGED,
    show_progress=True)
PARAMS_H = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]
best_h = grid_block(grid_h, PARAMS_H)
res_h = run_backtest(config_from_row(BASE_HEDGED, best_h, PARAMS_H),
                     signals=basis, book=lab["book"], builder=builder)
_ = header_block("Skew basis — delta-hedged", res_h, grid=grid_h)
if not res_h.daily_bp.empty:
    fig = three_panel_equity(res_h, "Skew basis (delta-hedged)")
    plt.show()

# %%
print("\nUNHEDGED vs DELTA-HEDGED — is the edge skew or direction?")
print(pd.DataFrame([
    {"variant": "unhedged", "median_net_bp": grid["total_net_bp"].median(),
     "best_net_bp": grid["total_net_bp"].max(),
     "pct_positive": float((grid["total_net_bp"] > 0).mean())},
    {"variant": "delta-hedged", "median_net_bp": grid_h["total_net_bp"].median(),
     "best_net_bp": grid_h["total_net_bp"].max(),
     "pct_positive": float((grid_h["total_net_bp"] > 0).mean())},
]).round(2).to_string(index=False))

# %% [markdown]
# ## League rows
#
# Two rows per framework: the best honest config and the *median* config of the
# sweep. If only the first is positive, the framework is a selection artifact.

# %%
med = median_row(grid)
res_med = run_backtest(config_from_row(BASE, med, PARAMS), signals=basis,
                       book=lab["book"], builder=builder)
_ = header_block("Skew basis — median config", res_med, grid=grid)

# %%
league_row("1. Skew basis (RR spread)", "best-config", res, grid=grid, cls="A/B",
           note=f"{CONFIG['wing_offset']*100:.0f}bp wings, 4 option legs")
league_row("1. Skew basis (RR spread)", "median-config", res_med, grid=grid,
           cls="A/B", note="median of the sweep, not selected")
league_row("1. Skew basis (RR spread)", "fomc-window", res_ev, grid=grid_ev,
           cls="A/B", note="entries limited to 7 business days pre-FOMC")
league_row("1b. Skew basis (delta-hedged)", "best-config", res_h, grid=grid_h,
           cls="A/B", note="each contract's delta re-hedged daily — skew only")
