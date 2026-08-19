# %% [markdown]
# # Olds vs currents: the off-the-run switch, across the curve
#
# **The trade.** Buy a seasoned Treasury, sell the on-the-run of the same original-issue
# tenor, duration-matched. The on-the-run is rich because it is liquid; when the next
# auction displaces it, that richness is released and the spread converges. The study runs
# every pair among CT / O / OO / OOO (current, old, double-old, triple-old) on the 2y, 3y,
# 5y, 7y, 10y, 20y and 30y, 2010 to 2026, marked daily, with the equity curve in basis
# points of a DV01-matched position.
#
# **Order of operations, and why it is not the obvious one.** Coverage, then the *raw
# object* (yield pickup by rank with no trading rule on it), then ONE hand-reconciled
# trade, then the baseline, and only then the grid. The raw object comes first because if
# the premium is not there, a grid run first would only report which noise it liked. The
# reconciled trade comes next because five hundred wrong numbers look exactly like five
# hundred right ones.
#
# **Three things this config deliberately cannot do.**
# 1. It cannot hold a position by ALIAS. `O10/CT10` is a different pair of bonds either
#    side of an auction; measured on the 2024-02-16 refunding the alias series moved
#    −1.395bp day-over-day while the pair actually held moved −0.358bp. Differencing the
#    alias books 1.04bp nobody earned, on a trade whose whole premium is 0.1–1.8bp.
#    Positions are pinned to CUSIPs at entry.
# 2. It cannot use the engine's native carry. `Query/FixedRateBonds/carry_roll.py` applies
#    ONE rate — the last overnight SOFR fixing — to every bond, so both legs of a switch
#    finance identically, the financing nets to zero and the trade looks free. It is not.
# 3. It cannot silently reduce its trial count. Placebos and controls are counted in the
#    deflation alongside the configurations that were being hoped for.
#
# > ⚠ **The caveat that matters most.** The raw spread between two ranks is not a pure
# > liquidity premium: the older bond also matures ~1–3 months earlier, so the spread
# > carries a slice of curve slope. That component is roughly static while a position is
# > on (both bonds age together), but it sets the LEVEL, and in some regimes it dominates
# > the sign. §2 shows this directly — in 2015–16 the 10y rank-3 yielded *less* than the
# > on-the-run, which no liquidity story explains.

# %%
import os, sys, pathlib, warnings, json

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")

# Derived, never hardcoded: the FOMC builder pins `ARBS-gcb` and silently imports another
# worktree's code when copied. `_make_v3_notebooks.py` derives it for exactly this reason.
REPO = str(pathlib.Path.cwd().parents[2]) if pathlib.Path.cwd().name == "ust_switch" else os.getcwd()
sys.path.insert(0, REPO)

import numpy as np
import pandas as pd

from RVUtils.USTSwitch import analytics as A
from RVUtils.USTSwitch import figures as F
from RVUtils.USTSwitch import grid as G
from RVUtils.USTSwitch.costs import CostModel, cost_table_summary
from RVUtils.USTSwitch.data import coverage_report, load_prepared, select_financing
from RVUtils.USTSwitch.engine import SwitchConfig, run_switch

plt = F.style()
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

panel, amap = load_prepared()
print(f"panel {panel.shape}  {panel['date'].min().date()} .. {panel['date'].max().date()}")

# %% [markdown]
# ## 1. The config
#
# One frozen dataclass. Every field is a knob the later sections sweep one at a time.

# %%
CONFIG = SwitchConfig(
    tenor=10,
    rank_young=0,       # CT  -- the on-the-run, the leg you short in the classic switch
    rank_old=1,         # O   -- the seasoned leg you buy
    direction=1,        # +1 = long old / short current
    entry_offset=1,     # business days after the auction roll
    exit_rule="next_roll",
    exit_offset=1,
    financing_mode="modelled",
    cost_multiplier=1.0,
)
print(CONFIG.name)

# %% [markdown]
# ### 1.1 Recipes

# %%
RECIPES = {
    "classic 10y O-vs-CT": dict(tenor=10, rank_young=0, rank_old=1, direction=1),
    "deep 30y OOO-vs-CT": dict(tenor=30, rank_young=0, rank_old=3, direction=1),
    "20y O-vs-CT (richest specialness)": dict(tenor=20, rank_young=0, rank_old=1, direction=1),
    "fade (short the old)": dict(tenor=10, rank_young=0, rank_old=1, direction=-1),
    "measured financing only": dict(financing_mode="actual"),
    "no financing (control)": dict(financing_mode="none"),
}

# %% [markdown]
# ## 2. What the study can see, and what the trade is made of
#
# Coverage first. `financing_actual` is the fraction of rows with **measured** per-issue
# repo (the JPM package, 2016-08-10 to 2025-08-26); outside that window specialness is
# modelled by (tenor, rank, age) and every headline is reported in all three financing
# modes so the model's contribution is visible rather than assumed.

# %%
cov = coverage_report(panel)
display(cov)
print(f"rows with measured financing: {panel['has_actual_financing'].mean():.1%}")

# %% [markdown]
# ### 2.1 The raw object — yield pickup by rank, before any trading rule
#
# This is the whole trade in one table. If the pickup is not monotone in rank, the
# liquidity premium is not the dominant term and no configuration will rescue it.

# %%
ts = {t: A.spread_term_structure(panel, t) for t in G.TENORS}
ts = {t: d for t, d in ts.items() if d is not None and not d.empty}
display(pd.concat(ts, names=["tenor"]).round(3))
F.plot_spread_term_structure(ts)
plt.show()

# %% [markdown]
# ### 2.2 The cost line, from NY Fed Staff Report 1170 Table 3
#
# Effective bid-ask by off-the-run rank, converted from price bp to yield bp by modified
# duration. Printed **before** any P&L, because every prior lab in this repo died on the
# cost line and the cost was the last thing shown.

# %%
ct = cost_table_summary()
display(ct.pivot_table(index="tenor", columns="pair", values="rt_cost_bp").round(3))

# %% [markdown]
# ### 2.3 Financing — measured specialness by tenor and rank
#
# Reproduced from the JPM package and tied out against their published `3m Repo Special`
# at corr 0.9997 (mean abs error 0.037bp). The 20y is by far the most special.

# %%
F.plot_specialness(panel)
plt.show()
display(panel[panel["has_actual_financing"]]
        .groupby(["tenor", "rank"])["special_actual_bp"].mean().unstack().round(3))

# %% [markdown]
# ## 3. Does the machine give the right answer to a question we already know?
#
# The known-answer gate. One trade is recomputed from the raw panel by arithmetic that
# does not touch engine code, and the reconciliation is then broken on purpose — once by
# flipping the direction, once by removing the specialness — to prove it is sensitive to
# both. A reconciliation that passes either way is checking nothing.

# %%
# ! python reconcile_one_trade.py
import subprocess
print(subprocess.run([sys.executable, str(pathlib.Path(REPO) / "notebooks/backtests/ust_switch/reconcile_one_trade.py")],
                     capture_output=True, text=True).stdout)

# %% [markdown]
# ## 4. How this config performed

# %%
p_fin = select_financing(panel, CONFIG.financing_mode)
res = run_switch(p_fin, amap, CONFIG, cost_model=CostModel(multiplier=CONFIG.cost_multiplier))
print("funnel:", res.funnel)
display(A.pnl_decomposition(res).round(4))
summ = A.summarize_switch(res)
display(pd.Series(summ).to_frame("value"))

F.plot_equity({CONFIG.name: res.equity_bp})
plt.show()
F.plot_pnl_decomposition(A.pnl_decomposition(res))
plt.show()

# %% [markdown]
# ## 5. The grid
#
# Seven tenors × six rank pairs × direction × entry offset × exit rule × optional z-filter.

# %%
cfgs = G.expand(financing_mode=CONFIG.financing_mode)
print(f"{len(cfgs)} configurations")
league, daily, results = G.run_grid(p_fin, amap, cfgs)
scored = A.league_table(league.to_dict("records"), min_trades=8)
print(f"{len(scored)} with >= 8 trades")
display(scored.head(15)[["name", "tenor", "pair", "direction", "entry_offset",
                         "n_trades", "net_bp_per_trade", "cost_bp_per_trade",
                         "sharpe", "t_stat_nw"]].round(4))

# %%
F.plot_league_heatmap(scored, value="sharpe")
plt.show()
F.plot_league_heatmap(scored, value="net_bp_per_trade",
                      title="Best net bp per trade by tenor and rank pair")
plt.show()

# %% [markdown]
# ## 6. Placebo — the same rules, entered off the auction clock
#
# The premium is created at an auction. Shift entry away from the roll and a real auction
# mechanism must degrade. If the shifted book performs as well, whatever is being measured
# is not the on-the-run premium and the auction story is decoration.

# %%
top = scored.head(12)["name"].tolist()
pl_cfgs = G.placebo_grid([c for c in cfgs if c.name in top], shifts=(7, 14, -7))
pl_league, pl_daily, _ = G.run_grid(p_fin, amap, pl_cfgs, progress=False)
print(f"top-12 mean Sharpe  : {scored[scored['name'].isin(top)]['sharpe'].mean():+.3f}")
print(f"placebo mean Sharpe : {pl_league['sharpe'].mean():+.3f}")
display(pl_league[["name", "n_trades", "net_bp_per_trade", "sharpe"]].round(4).head(12))

# %% [markdown]
# ## 7. What the search cost — deflated Sharpe
#
# Trials counted = grid + placebo. `apply_dsr_gate` would default to `len(results)`, which
# is the wrong count when the frame in hand is one slice of a larger search.

# %%
n_trials = len(cfgs) + len(pl_cfgs)
defl = A.deflate_league(scored, {**daily, **pl_daily}, n_trials=n_trials)
defl["verdict"] = defl.apply(A.verdict_row, axis=1)
print(f"trials {n_trials}   sr_var {defl['sr_variance'].iloc[0]:.4f}   "
      f"E[max Sharpe | null] {defl['sr_star'].iloc[0]:.3f}")
display(defl.head(20)[["name", "tenor", "pair", "n_trades", "net_bp_per_trade",
                       "sharpe", "dsr_prob", "breakeven_cost_mult", "verdict"]].round(4))
print(defl["verdict"].value_counts().to_string())

# %% [markdown]
# ## 8. Cost curve and break-even

# %%
best_cfg = next(c for c in cfgs if c.name == defl.iloc[0]["name"])
cc = G.cost_curve(panel, amap, best_cfg)
display(cc.round(4))
F.plot_cost_curve(cc)
plt.show()

# %% [markdown]
# ## 9. Seasonality
#
# Two clocks, and they are not interchangeable. The **auction-cycle** clock is the
# mechanism: the premium is created at one auction and released at the next, so a real
# effect must concentrate somewhere on this axis. The **calendar** clock is the
# conventional one. For 2y/3y/5y/7y (monthly auctions) the two nearly coincide; for
# 10y/20y/30y (quarterly) they separate cleanly, which is what makes the comparison
# informative.

# %%
best_res = results[defl.iloc[0]["name"]]
cyc = A.auction_cycle_profile(best_res)
F.plot_auction_cycle(cyc)
plt.show()
F.plot_cycle_cumulative(cyc)
plt.show()

# %%
seas = A.calendar_seasonality(best_res)
F.plot_calendar_seasonality(seas)
plt.show()

# %% [markdown]
# ### 9.1 Pooled across every long-old config
#
# One configuration's calendar is noise. Pooling every long-old cell, weighted by
# observation count, is the honest version of the same picture.

# %%
pool = []
for nm, r in results.items():
    if r.config.direction > 0 and not r.trades.empty:
        c = A.auction_cycle_profile(r)
        if not c.empty:
            c["tenor"] = r.config.tenor
            pool.append(c)
allc = pd.concat(pool, ignore_index=True)
g = (allc.groupby("cycle_day")
     .apply(lambda d: pd.Series({"n": d["n"].sum(),
                                 "mean_pnl_bp": np.average(d["mean_pnl_bp"], weights=d["n"]),
                                 "mean_price_bp": np.average(d["mean_price_bp"], weights=d["n"])}),
            include_groups=False)
     .reset_index())
F.plot_auction_cycle(g.assign(cum_mean_pnl_bp=g["mean_pnl_bp"].cumsum()),
                     title="Auction-cycle seasonality, pooled over all long-old configs")
plt.show()

# %% [markdown]
# ## 10. Robustness
#
# Financing modes side by side, and a per-year split. A strategy alive in one regime and
# dead in three is not alive.

# %%
rows = {}
for mode in ("none", "modelled", "actual"):
    c = SwitchConfig(**{**best_cfg.__dict__, "financing_mode": mode})
    r = run_switch(select_financing(panel, mode), amap, c, cost_model=CostModel())
    rows[mode] = A.summarize_switch(r)
    if not r.daily.empty:
        rows[mode]["_eq"] = r.equity_bp
eq = {m: v.pop("_eq") for m, v in rows.items() if "_eq" in v}
display(pd.DataFrame(rows).T[["n_trades", "net_bp_per_trade", "special_bp_per_trade",
                              "sharpe", "t_stat_nw", "hit_rate"]].round(4))
F.plot_equity(eq, title="Same rules, three financing assumptions")
plt.show()

# %%
from RVUtils.BasisVsVol.analytics import regime_split
best_daily = results[defl.iloc[0]["name"]].daily.rename(columns={"pnl_bp": "pnl"})
display(regime_split(best_daily, col="pnl", by="year").round(4))

# %% [markdown]
# ## 11. Trade log

# %%
OUT = pathlib.Path(REPO) / "notebooks/backtests/ust_switch/_out"
OUT.mkdir(parents=True, exist_ok=True)
tl = results[defl.iloc[0]["name"]].trades.copy()
tl["cum_bp"] = tl["net_bp"].cumsum()
tl.to_csv(OUT / "best_trade_log.csv", index=False)
defl.to_csv(OUT / "league_deflated.csv", index=False)
display(tl.round(4).tail(20))

# %% [markdown]
# ## 12. Reading this notebook
#
# **Kill conditions, in the order they should be checked.**
#
# 1. §2.1 — if the yield pickup is not monotone in rank for a tenor, that tenor's cells are
#    measuring curve slope, not liquidity, whatever their Sharpe says.
# 2. §3 — if the reconciliation does not both PASS as configured and FAIL under the two
#    mutations, nothing below it means anything.
# 3. §6 — if the placebo Sharpe is not materially below the real one, the auction
#    mechanism is not what is being harvested.
# 4. §7 — a row with `dsr_prob < 0.95` is SELECTION-ARTIFACT, not a strategy.
# 5. §8 — `breakeven_cost_mult` below ~1.5 means the result lives inside the error bar of
#    the cost assumption, and SR1170's spreads are measured off *executed* trades, so they
#    are if anything optimistic for the deep-old legs.
#
# **What would change the answer.** Per-issue financing beyond the JPM window (2016-08 to
# 2025-08) is modelled; a real repo history for 2010–2016 would firm up 40% of the sample.
# A Citi Velocity cross-check is written and ready in `tie_out_citi_repo.py` but was
# blocked on the Excel add-in transport.
