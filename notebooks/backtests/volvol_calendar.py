# %% [markdown]
# # Vol against vol: the adjacent-expiry fly hedge
#
# The outcome-map study closed the vol-vs-linear question and left one
# recommendation: a butterfly's model sensitivity is a **density**, so hedge it
# with a density — an adjacent-expiry butterfly rather than a ZQ basket.
#
# Consecutive SR3 quarterlies **nest**: a meeting resolved by the near contract's
# option expiry is also resolved by the far one's and is effective inside the far
# reference window, so the near resolved-meeting set is a subset of the far one's.
# A fly on the far expiry therefore carries the near one's shared-meeting
# exposure plus the meetings between them.
#
# This notebook asks three questions and lets the cells answer them: does the
# adjacent-expiry fly hedge, can the lattice size it, and is the cross-expiry
# disagreement itself worth trading.

# %%
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")
import outcome_map_common as omc                            # noqa: E402
import outcome_map_calendar_common as cal                   # noqa: E402
from linvol_grid_common import pick_winner                  # noqa: E402
from RVUtils.SFRRVLab.stats import (                        # noqa: E402
    deflated_for_grid, grid_distribution, neighbourhood_stability, verdict)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

DATA = Path("../data/outcome_map")
OUT = Path("../data/volvol")

ctx = omc.Context()
panel = pd.read_parquet(DATA / "cells.parquet")
panel["as_of"] = pd.to_datetime(panel["as_of"])
b_bar = omc.trailing_tilt(panel)
base = omc.signal_frame(ctx, panel, "pair_odd_dev", b_bar=b_bar)
cf = cal.calendar_frame(ctx, panel, base)
print(f"outcome-map packages      : {len(base):,}")
print(f"...with an adjacent mirror: {len(cf):,}")
print(f"sample                    : {cf['as_of'].min().date()} -> "
      f"{cf['as_of'].max().date()}")

# %% [markdown]
# ## 1. The nesting relation, and what a calendar hedge can never remove
#
# The far expiry always resolves the near one's meetings and some extra ones.
# Those extra meetings are exposure no amount of the far fly can cancel — they
# are the price of using it as a hedge, and they are also exactly the object the
# cross-expiry signal would be trading.

# %%
print("=== the pairing population ===")
print(cf[["n_shared", "n_extra", "dte", "dte2", "con1", "con2",
          "h1_abs", "h2_abs", "extra_exposure", "resid_frac"]]
      .describe([.1, .5, .9]).round(3).to_string())
print(f"\nrows where the near set is NOT a subset (extra < 0 impossible; "
      f"shared < n_resolved would show it): "
      f"{int((cf['n_shared'] < 2).sum())} with fewer than 2 shared meetings "
      f"(excluded by construction)")
print(f"median shared meetings {cf['n_shared'].median():.0f}, "
      f"median extra {cf['n_extra'].median():.0f}")
print(f"extra-meeting exposure as a share of the package's own: "
      f"{(cf['extra_exposure'] / cf['h1_abs']).median():.2f}")

# %% [markdown]
# ## 2. Does it hedge? — and why the horizon matters
#
# The first measurement of this regressed the two packages' **daily** changes.
# That is the wrong horizon: marks move on a 0.5bp tick grid, so each leg carries
# quantisation noise that is independent across expiries — errors-in-variables,
# which biases the slope and R² toward zero. The tradeable horizon is the holding
# period.

# %%
HOLDS = (1, 2, 3, 5, 10, 15)
recs = []
for _, r in cf.iterrows():
    fut = ctx.dates[ctx.dates > r["as_of"]][:max(HOLDS) + 1]
    if len(fut) < max(HOLDS) + 1:
        continue
    m1 = np.array([ctx.mark_any(t, r["symbol"], r["legs"]) for t in fut])
    m2 = np.array([ctx.mark_any(t, r["other"], r["legs2"]) for t in fut])
    if not (np.isfinite(m1[0]) and np.isfinite(m2[0])):
        continue
    for H in HOLDS:
        if H < len(m1) and np.isfinite(m1[H]) and np.isfinite(m2[H]):
            recs.append({"H": H, "d1": m1[H] - m1[0], "d2": m2[H] - m2[0],
                         "lam_tree": r["lam_tree"]})
hz = pd.DataFrame(recs)


def ols0(y, x):
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x)[ok], np.asarray(y)[ok]
    if len(x) < 30 or np.dot(x, x) == 0:
        return np.nan, np.nan
    b = float(np.dot(x, y) / np.dot(x, x))
    return b, 1 - float(np.var(y - b * x) / np.var(y))


rows = []
for H, g in hz.groupby("H"):
    b, r2 = ols0(g["d1"], g["d2"])
    gt = g[g["lam_tree"].abs() <= 3]
    bt, _ = ols0(gt["d1"], gt["lam_tree"] * gt["d2"])
    grid = {lam: 1 - np.var(g["d1"] - lam * g["d2"]) / np.var(g["d1"])
            for lam in np.arange(0.0, 2.01, 0.05)}
    best = max(grid, key=grid.get)
    rows.append({"horizon": H, "n": len(g),
                 "corr": round(float(np.corrcoef(g["d1"], g["d2"])[0, 1]), 3),
                 "beta_emp": round(b, 3), "R2": round(r2, 3),
                 "beta_vs_tree_lambda": round(bt, 3),
                 "risk_min_lambda": round(best, 2),
                 "var_removed": round(float(grid[best]), 3),
                 "var_removed_at_1to1": round(float(grid[1.0]), 3)})
hztab = pd.DataFrame(rows)
print("=== hedge quality by holding horizon ===")
print(hztab.to_string(index=False))
last = hztab.iloc[-1]
print(f"\nAt {int(last['horizon'])} sessions the adjacent-expiry fly removes "
      f"{last['var_removed']:.0%} of the package's variance at lambda "
      f"{last['risk_min_lambda']:.2f}, and {last['var_removed_at_1to1']:.0%} "
      f"at a flat 1:1 with nothing estimated.")
print("For comparison, the ZQ basket in the outcome-map study removed ~9-11% "
      "at its own best size, and RAISED risk at the size the lattice asked for.")

# %% [markdown]
# ## 3. Can the lattice size it?
#
# `beta_vs_tree_lambda` above is the test. One means the tree's least-squares
# ratio over the shared meetings is right-sized.

# %%
print(f"beta against the tree ratio at the trade horizon: "
      f"{last['beta_vs_tree_lambda']:.3f}")
print(f"  -> the tree ratio is {1 / last['beta_vs_tree_lambda']:.1f}x too large")
print(f"  (the linear leg's equivalent was 5.7x)")
print(f"\ntree lambda: median {cf['lam_tree'].median():.2f}, "
      f"IQR [{cf['lam_tree'].quantile(.25):.2f}, "
      f"{cf['lam_tree'].quantile(.75):.2f}], "
      f"share |lam|<=3 {(cf['lam_tree'].abs() <= 3).mean():.1%}")
print(f"empirical lambda (causal, 40 sessions): median "
      f"{cf['lam_emp'].median():.2f}, available {cf['lam_emp'].notna().mean():.1%}")
print("\nThe market sizes this hedge at about 1:1. The model says otherwise, and")
print("the model is wrong — the same failure as the linear leg, smaller.")

# %% [markdown]
# ## 4. The grid
#
# 128 pre-declared configs in each of three worlds. `map_odd` trades the
# outcome-map signal and uses the adjacent expiry as a hedge, so its
# `lambda=none` row must reproduce the prior study exactly — that is the control.
# `calendar` trades the cross-expiry residual itself.

# %%
league = pd.read_parquet(OUT / "league.parquet")
real = league[league["world"] == "real"].reset_index(drop=True)
live = real[real["n_trades"] > 0]
print(f"configs: {len(real)} real ({len(live)} traded, "
      f"{int(real['skipped'].sum())} skipped by construction)")
print("\n=== the hedge, priced (map_odd, fade only, per trade) ===")
mo = live[(live["signal"] == "map_odd") & (live["direction"] == "fade")]
print(mo.groupby("lam").agg(
    configs=("n_trades", "size"), n=("n_trades", "median"),
    gross=("per_trade_gross", "median"), cost=("per_trade_cost", "median"),
    std=("per_trade_std", "median"), contracts=("n_contracts", "median"),
    net_1x=("net_1x_bp", "median"), best_net=("net_1x_bp", "max")
).round(3).to_string())
un = mo[mo["lam"] == "none"]["per_trade_std"].median()
print(f"\nper-trade dispersion, unhedged {un:.2f}bp; the hedge's job is to cut "
      f"that, and its bill is the price of doing so.")

# %% [markdown]
# ### The thing that decides it: does the hedge remove more noise than edge?
#
# A hedge earns its place if it removes risk faster than it removes the trade.
# Gross per trade divided by dispersion per trade is that ratio, and it is a
# **pre-cost** comparison — if the hedge does not improve it at zero cost, no
# execution assumption can save it.
#
# The reason to fear it here is structural: the two expiries share meetings, so
# the far contract's map is rich and cheap in the same places the near one's is.
# The mispricing being traded lives in the shared component — the very component
# the hedge removes.

# %%
ir = mo.groupby("lam").agg(
    gross=("per_trade_gross", "median"), std=("per_trade_std", "median"),
    cost=("per_trade_cost", "median"))
ir["gross_per_unit_risk"] = ir["gross"] / ir["std"]
ir["risk_vs_unhedged"] = ir["std"] / float(ir.loc["none", "std"])
ir["edge_vs_unhedged"] = ir["gross"] / float(ir.loc["none", "gross"])
print(ir.round(3).to_string())
base_ir = float(ir.loc["none", "gross_per_unit_risk"])
best_lam = ir["gross_per_unit_risk"].idxmax()
print(f"\nunhedged gross per unit of risk {base_ir:.3f}; best hedged "
      f"{ir['gross_per_unit_risk'].max():.3f} (lambda={best_lam})")
print("If the hedge cuts edge and risk in similar proportion, it cannot improve")
print("the trade even before its bill — and its bill is the second problem.")

# %% [markdown]
# ### The control
#
# `map_odd` with `lambda = none` is the prior study's `pair_odd_dev` row run
# through this harness. It cannot match trade-for-trade — this study only sees
# contract-days that HAVE an adjacent mirror with at least two shared meetings —
# but the per-trade economics on the paired subsample must line up, or something
# in the calendar plumbing has changed the underlying trade.

# %%
prior = pd.read_parquet(DATA / "league_real.parquet")
pp = prior[(prior["expression"] == "pair_odd_dev") & (prior["linear"] == "none")
           & (prior["direction"] == "fade") & (prior["exit"] == "hold")
           & (prior["thr_pp"] == 8.0)]
here = mo[(mo["lam"] == "none") & (mo["exit"] == "hold") & (mo["thr_pp"] == 8.0)]
cmp = pd.DataFrame({
    "study": ["outcome-map (all rows)", "this harness (paired subsample)"],
    "n_trades": [int(pp["n_trades"].sum()), int(here["n_trades"].sum())],
    "per_trade_gross": [
        round(float((pp["gross_bp"].sum() / max(pp["n_trades"].sum(), 1))), 3),
        round(float((here["gross_bp"].sum()
                     / max(here["n_trades"].sum(), 1))), 3)],
    "per_trade_cost": [
        round(float(pp["opt_cost_bp"].sum() / max(pp["n_trades"].sum(), 1)), 3),
        round(float(here["cost_bp"].sum()
                    / max(here["n_trades"].sum(), 1)), 3)],
})
print(cmp.to_string(index=False))
print(f"\npairing retains {len(cf) / max(len(base), 1):.1%} of the packages; "
      f"the control's per-trade economics should sit in the same place, and a "
      f"gap here would mean the calendar plumbing changed the trade itself.")

# %%
print("=== the cross-expiry SIGNAL (calendar) ===")
ca = live[(live["signal"] == "calendar") & (live["direction"] == "fade")]
if len(ca):
    print(ca.groupby("lam").agg(
        configs=("n_trades", "size"), n=("n_trades", "median"),
        gross=("per_trade_gross", "median"), cost=("per_trade_cost", "median"),
        net_1x=("net_1x_bp", "median"), best_net=("net_1x_bp", "max")
    ).round(3).to_string())
mo_gross = float(mo[mo["lam"] == "none"]["per_trade_gross"].median())
ca_gross = float(ca["per_trade_gross"].median()) if len(ca) else np.nan
print(f"\nKILL CRITERION 3: the calendar signal must beat the unhedged "
      f"outcome-map row's gross per trade.")
print(f"  unhedged map_odd {mo_gross:+.3f}bp vs calendar {ca_gross:+.3f}bp "
      f"-> {'FIRES' if not (ca_gross > mo_gross) else 'does not fire'}")

# %%
dist = grid_distribution(live, metric="net_1x_bp")
print("=== net at 1x across the traded configs ===")
for k, v in dist.items():
    print(f"  {k:14s} {v:,.2f}" if isinstance(v, float) else f"  {k:14s} {v}")
print("\n=== sign test (median gross by direction) ===")
print(live.pivot_table(index=["signal", "lam"], columns="direction",
                       values="gross_bp", aggfunc="median").round(2).to_string())

# %%
with open(OUT / "dailies_real.pkl", "rb") as fh:
    dailies = pickle.load(fh)
w = pick_winner(live)
i = int(w.name)
dsr = deflated_for_grid(dailies.get(i, pd.Series(dtype=float)), real,
                        sharpe_col="sharpe")
print("=== best n-floored config ===")
for k in ("signal", "lam", "dte", "thr_pp", "exit", "direction"):
    print(f"  {k:10s} {w[k]}")
for k in ("n_trades", "gross_bp", "cost_bp", "net_1x_bp", "net_2x_bp", "hit",
          "nw_t", "per_trade_gross", "per_trade_cost", "per_trade_std",
          "n_contracts"):
    print(f"  {k:16s} {w[k]:+.3f}" if np.isfinite(w[k]) else f"  {k:16s} n/a")
print(f"\nDSR at {dsr['n_trials']} trials: {dsr['dsr_prob']:.3f}")
med = float(live["net_1x_bp"].median())
print(f"median config {med:+.1f}bp -> HOUSE VERDICT: "
      + verdict(net_bp_at_taker=float(w["net_1x_bp"]),
                net_bp_at_maker=float(w["gross_bp"]),
                dsr_prob=float(dsr["dsr_prob"]), median_net_bp=med,
                n_trades=int(w["n_trades"])))

# %%
print("=== neighbourhood ===")
nb = neighbourhood_stability(
    live, w, ["signal", "lam", "dte", "thr_pp", "exit", "direction"],
    metric="net_1x_bp")
print(nb.to_string(index=False))
print(f"\n{int((nb['net_1x_bp'] > 0).sum())}/{len(nb)} positive at 1x")

# %%
print("=== placebo worlds ===")
rows = []
for world, g in league.groupby("world"):
    gl = g[g["n_trades"] > 0]
    if gl.empty:
        continue
    gw = pick_winner(gl)
    rows.append({"world": world, "traded": len(gl),
                 "best_gross": round(float(gl["gross_bp"].max()), 1),
                 "best_net_1x": round(float(gl["net_1x_bp"].max()), 1),
                 "winner_signal": gw["signal"], "winner_lam": gw["lam"],
                 "winner_n": int(gw["n_trades"]),
                 "winner_gross": round(float(gw["gross_bp"]), 1)})
print(pd.DataFrame(rows).set_index("world").to_string())

# %% [markdown]
# ## 5. The answer
#
# Read off the cells above: whether the adjacent-expiry fly hedges (section 2),
# whether the lattice can size it (section 3), what it costs and whether the
# package it protects can afford it (section 4), and whether the cross-expiry
# disagreement is a trade in its own right.

# %%
print("1. Does an adjacent-expiry fly hedge a cell package?")
print(f"     {last['var_removed']:.0%} of variance removed at lambda "
      f"{last['risk_min_lambda']:.2f} over {int(last['horizon'])} sessions; "
      f"{last['var_removed_at_1to1']:.0%} at a flat 1:1.")
print("2. Can the lattice size it?")
print(f"     No: beta {last['beta_vs_tree_lambda']:.2f} against the tree ratio "
      f"({1/last['beta_vs_tree_lambda']:.1f}x too large).")
print("3. Can the package afford it?")
h1 = float(mo[mo["lam"] == "none"]["per_trade_cost"].median())
h2 = float(mo[mo["lam"] == "one"]["per_trade_cost"].median())
print(f"     Unhedged bill {h1:.2f}bp/trade -> 1:1 hedged {h2:.2f}bp/trade, "
      f"against a gross of {mo_gross:+.3f}bp/trade.")
print(f"4. Is the cross-expiry disagreement a trade? "
      f"{'no' if not (ca_gross > mo_gross) else 'see above'}")
print(f"5. ALIVE anywhere? "
      f"{'yes' if (dist.get('pct_positive', 0) > 0 and dsr['dsr_prob'] > 0.5) else 'no'}"
      f"  ({dist.get('pct_positive', 0):.0%} of configs positive at 1x)")
