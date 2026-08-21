# %% [markdown]
# # W4 — Ultra-long curve pairs on risk-adjusted carry, 2021–2026
#
# > *"the ratio of the daily breakeven — the daily move in rates that yields a
# > convexity gain offsetting a negative daily carry — to realized daily
# > volatility. Three most attractive curves by each metric are marked in red."*
# >
# > — Citi, *Alert: Taking profits on delta-hedged 15y5y/20y10y flatteners*,
# > close 04-Dec-2019
#
# The brief names **risk-adjusted carry** as this book's dominant driver, and the
# note above prints exactly that screen: fifteen USD curve pairs by eight
# columns. This notebook takes that screen, turns it into a rule, and measures
# what the rule earns.
#
# **The verdict is that it does not work, and the reason is not costs.** Read
# section 9 before section 6: the gross Sharpe is below what a zero-edge
# strategy would be expected to produce from the search that found it.

# %%
import datetime as dt
import json
import math
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import rac_backtest as B
from RVUtils.ConvexityRV import rac_signal as R
from RVUtils.ConvexityRV.strat1_threeway import expected_max_sharpe_under_null

DATA = REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 200, "display.max_columns", 40)
print(f"repo {REPO}")

# %% [markdown]
# ## 1. The config
#
# Every knob, and the reason for its value. `RacConfig` carries the same
# defaults; they are restated here so the notebook is self-describing.
#
# The two that matter most are `enter_pct` and `steepener_pct`. Citi publishes
# **absolute** thresholds — exit around 0.8, steepener above 1.0 — and section 3
# shows why they cannot be used on this curve.

# %%
CONFIG = R.RacConfig(
    lookback_days=756,     # 3y, matching Citi's own "3y ZS" column
    enter_pct=0.80,        # flattener when risk-adjusted carry is unusually good
    exit_pct=0.35,         # ...and closed when it reverts this far
    steepener_pct=0.20,    # the other side
    top_n=3,               # Citi marks "three most attractive" in red
    min_carry_bp=None,     # OFF: the carry SIGN is not reliable near zero (§3)
    start=dt.date(2021, 1, 1),
    end=dt.date(2026, 8, 20),
)
MIN_HOLD, MAX_HOLD = 21, 252
print(json.dumps(CONFIG.to_dict(), indent=1, default=str))

# %% [markdown]
# ## 2. Does the machine give the right answer to a question we already know?
#
# Citi's 04-Dec-2019 screen prints all eight columns for all fifteen pairs —
# **120 published cells** the code was never fitted to. The package's screen is
# graded against them in `tests/test_convexity_rv_rac_screen.py`; the headline
# numbers are restated here.
#
# The verdict is a **split**: rank transfers, level does not.

# %%
TIEOUT = {
    "spearman_level": 0.9857,
    "spearman_carry": 0.9445,
    "spearman_be_daily": 0.9920,
    "spearman_be_over_rv": 0.9884,
    "offset_level_bp": -0.807,
    "offset_carry_bp": +1.101,
    "offset_ratio": -0.190,
    "citi_exit_threshold": 0.8,
    "citi_steepener_threshold": 1.0,
    "our_max_ratio": 0.747,
}
print("Citi 2019-12-04, 15 pairs, graded out of sample:")
for k, v in TIEOUT.items():
    print(f"  {k:26} {v:+.4f}" if isinstance(v, float) else f"  {k:26} {v}")

assert TIEOUT["spearman_be_over_rv"] > 0.95, "the decision statistic's RANK must transfer"
assert TIEOUT["our_max_ratio"] < TIEOUT["citi_steepener_threshold"], (
    "no pair on our curve reaches Citi's 1.0 steepener threshold, which is why "
    "the rule is keyed on rank and percentile rather than on her absolute levels"
)
print("\nOK: rank transfers (spearman 0.988); level does not (offset -0.190),")
print("and Citi's 1.0 steepener threshold would fire ZERO times on our curve.")

# %% [markdown]
# ## 3. Why the traded statistic is not the published one
#
# Two measurements forced it.
#
# **The published ratio is saturated.** Citi truncates the daily breakeven to
# zero whenever carry is non-negative, so the ratio is exactly 0 on a large
# fraction of the sample — worst on the tight forward pairs the factor
# attribution identified as the convexity-dominated ones. A time-series
# percentile of a flat-zero series is undefined exactly where the rule wants to
# fire, because `carry >= 0` *is* the entry condition.
#
# **The continuous statistic underneath it is not saturated**, is signed, passes
# smoothly through zero, and is literally risk-adjusted carry:
#
# $$\mathrm{rac} = \frac{\text{carry}_{1y}\ (\mathrm{bp})}
#                        {\sigma_{\text{realised}}\ (\mathrm{bp/day}) \times \sqrt{252}}$$

# %%
panel = pd.read_parquet(DATA / "rac_screen_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
print(f"screen panel {panel.shape}, {panel['pair'].nunique()} pairs, "
      f"{panel['date'].min().date()} .. {panel['date'].max().date()}")

sat = R.saturation_table(R.add_rac(panel))
print("\nsaturation of the PUBLISHED ratio, by year:")
print(sat.round(3).to_string())

assert sat["be_truncated_to_0"].max() > 0.4, "the truncation should be material"
assert (sat["rac_exactly_0"].fillna(0) == 0).all(), (
    "the continuous statistic must never be exactly zero"
)
print("\nOK: the published ratio is truncated on up to "
      f"{sat['be_truncated_to_0'].max():.1%} of a year; rac never is.")

# %% [markdown]
# ### 3.1 The universe is not uniform, and the module says so
#
# A carry-keyed rule can only ever say one thing about a pair whose carry is
# essentially always negative.

# %%
cpf = R.carry_positive_fraction(panel)
print("fraction of days with POSITIVE carry, by pair:")
print(cpf.round(3).to_string())
print(f"\none-sided family (named in the module): {list(R.ONE_SIDED_FAMILY)}")
assert cpf[list(R.ONE_SIDED_FAMILY)].max() < 0.10, (
    "the 10Yx10Y family is supposed to be structurally one-sided on this sample"
)

# %% [markdown]
# ## 4. The sign probe
#
# Re-derived from the engine on every run rather than trusted from a comment.
# A flattener pays the shorter leg and receives the longer one, so the front
# leg's PV01 must be positive, the back leg's negative, and the two must sum to
# zero.

# %%
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
probe = B.sign_probe(mdp, dt.date(2022, 9, 13))
print(probe)
assert probe["is_flattener"], "bpv<0 is not a flattener on this engine"
assert abs(probe["sum"]) < 1.0, f"package is not DV01-neutral: {probe['sum']}"
assert probe["front_pv01"] > 0 > probe["back_pv01"]
print("\nOK: bpv<0 = pay front / receive back = FLATTENER, DV01-neutral to "
      f"{probe['sum']:.1e}")

# %% [markdown]
# ## 5. What this config actually trades

# %%
sig = R.build_signal_panel(panel, CONFIG)
_d = sig.index.get_level_values("date")
sig = sig[(_d >= pd.Timestamp(CONFIG.start)) & (_d <= pd.Timestamp(CONFIG.end))]
state = R.entry_state(sig, CONFIG)

eps = B.episodes_from_state(state, exit_pct=CONFIG.exit_pct,
                            rac_pct=sig["rac_pct"],
                            max_hold_days=MAX_HOLD, min_hold_days=MIN_HOLD)
holds = pd.Series([e.days for e in eps])
print(f"{len(eps)} episodes   median hold {holds.median():.0f} bdays   "
      f"mean {holds.mean():.0f}   max {holds.max()}")

funnel = pd.DataFrame({
    "cells (date x pair)": [len(sig)],
    "flattener days": [int((state == 1).sum())],
    "steepener days": [int((state == -1).sum())],
    "flat days": [int((state == 0).sum())],
    "episodes": [len(eps)],
    "flattener episodes": [sum(1 for e in eps if e.side == 1)],
    "steepener episodes": [sum(1 for e in eps if e.side == -1)],
}).T.rename(columns={0: "n"})
print("\n" + funnel.to_string())

by_year = (pd.DataFrame({"date": [e.entry for e in eps],
                         "side": [e.side for e in eps]})
           .assign(year=lambda d: d["date"].dt.year)
           .groupby("year")["side"]
           .agg(flat=lambda s: (s == 1).sum(), steep=lambda s: (s == -1).sum()))
print("\nepisodes entered, by year and side:")
print(by_year.to_string())
print("\nNOTE: 2024 and 2025 enter ZERO flatteners. Risk-adjusted carry declined")
print("monotonically, so on a 3y trailing window every pair sits near the bottom")
print("of its own history. The book is steepener-only for half the sample.")

# %% [markdown]
# ## 6. How this config performed
#
# Priced by `QueryDrivenBacktest`, daily mark-to-market. `run()` swallows
# exceptions and prints them, so a failing backtest is indistinguishable from a
# flat equity curve; `assert_ran` asserts on the artifacts instead.

# %%
ARMS = {}
for tag in ("base", "zero_cost"):
    f = DATA / f"rac_w4_equity_{tag}.parquet"
    if f.exists():
        e = pd.read_parquet(f)["equity"]
        e.index = pd.to_datetime(e.index)
        ARMS[tag] = e
print(f"loaded arms: {list(ARMS)}")
assert ARMS, "no equity curves found; run _rac_w4_run.py first"


def perf(eq: pd.Series, label: str) -> dict:
    r = eq.diff().dropna()
    span = (eq.index[-1] - eq.index[0]).days / 365.25
    return {
        "arm": label,
        "terminal": float(eq.iloc[-1]),
        "ann_sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
        "ann_pnl": float(eq.iloc[-1] / span),
        "max_dd": float((eq - eq.cummax()).min()),
        "span_years": span,
    }


PERF = pd.DataFrame([perf(e, k) for k, e in ARMS.items()])
print(PERF.to_string(index=False))

_base = PERF[PERF["arm"] == "base"].iloc[0]
assert _base["max_dd"] < 0, "a book with no drawdown has not been marked"
print(f"\nMax drawdown is {abs(_base['max_dd']) / abs(_base['terminal']):.1f}x the "
      "terminal P&L. That is visible before any statistic is computed.")

# %%
_y = ARMS["base"].resample("YE").last().diff()
_y.iloc[0] = ARMS["base"].resample("YE").last().iloc[0]
print("P&L by year (base arm):")
print(_y.map(lambda v: f"{v:>14,.0f}").to_string())

# %% [markdown]
# ## 7. Costs
#
# Charged per **leg**: 2 legs x 2 sides x `half_spread_bp` on the package DV01.
# At 0.25bp that is **$100,000 per closed episode**.
#
# The only external datapoint available says that is *conservative*: Citi's own
# 15y5y/20y10y round trip ran **+$187K gross to +$155K net on $50K DV01**, i.e.
# about **$64K per $100k DV01 including every resize**.

# %%
gross = float(ARMS["zero_cost"].iloc[-1])
net = float(ARMS["base"].iloc[-1])
costs = gross - net
n_ep = len(eps)
be_half = 0.25 * gross / costs if costs else np.nan

print(f"gross            {gross:>15,.0f}")
print(f"net              {net:>15,.0f}")
print(f"costs            {costs:>15,.0f}   ({costs / gross:.1%} of gross)")
print(f"per episode      {costs / n_ep:>15,.0f}")
print(f"break-even half-spread   {be_half:.3f} bp   (charged 0.250)")
print(f"  = {4 * be_half:.2f} bp round trip on the package DV01")
print(f"  Citi measured ~0.64bp; charged here 1.00bp")

assert costs > 0, "the cost arm did not charge anything"
print("\nCosts make it worse. They are NOT what makes it dead — see section 9.")

# %% [markdown]
# ## 8. Is it convexity, or is it duration?
#
# The `mtm_share` statistic cannot answer this — an earlier block in this package
# established that by getting it wrong. Only the factor attribution answers it.
#
# Daily P&L on the shared level / slope / curvature / convexity basis, HAC
# t-stats. PC1 is 87.76% of variance with all-positive humped loadings, i.e.
# level.

# %%
ATTR = {
    "level":     {"share_pct": -132.8, "t": -4.85, "incr_r2": 0.1226},
    "convexity": {"share_pct": -156.8, "t": -0.67, "incr_r2": 0.0012},
    "curvature": {"share_pct": 2.0,    "t": 0.14,  "incr_r2": 0.0001},
    "slope":     {"share_pct": 0.1,    "t": 0.37,  "incr_r2": 0.0004},
}
A = pd.DataFrame(ATTR).T
print(A.to_string())
print("\ntotal R2 0.1244, of which level supplies 0.1226")

assert abs(ATTR["level"]["t"]) > 3.0, "level should be the significant factor"
assert abs(ATTR["convexity"]["t"]) < 2.0
print("\nThe only factor distinguishable from nothing is the one a DV01-neutral")
print("package is supposed not to have, and the book LOSES to it.")
print("\nCAVEAT that cuts the other way: DESIGN.md records that DAILY convexity is")
print("unidentified (t 2.1-5.4 at trade level vs 0.9-2.1 daily), so the convexity")
print("row is the expected reading at this frequency, NOT evidence of absence.")

# %% [markdown]
# ## 9. What the search cost — and why this is dead
#
# **Read this before section 6.** Positions are held a mean of ~102 business
# days, so 117 episodes over 5.63 years are not 117 independent observations.

# %%
mean_hold = float(holds.mean())
span = float(PERF[PERF["arm"] == "base"]["span_years"].iloc[0])
n_eff = span * 252.0 / mean_hold
print(f"mean hold {mean_hold:.0f} bdays -> n_eff ~ {n_eff:.1f} independent holds")

rows = []
for N in (1, 6, 12, 24, 48):
    rows.append({"trials": N,
                 "E[max SR | null]": expected_max_sharpe_under_null(N, n_obs=int(n_eff))})
NULL = pd.DataFrame(rows)
print("\n" + NULL.round(3).to_string(index=False))

gross_sr = float(PERF[PERF["arm"] == "zero_cost"]["ann_sharpe"].iloc[0])
net_sr = float(PERF[PERF["arm"] == "base"]["ann_sharpe"].iloc[0])
null_12 = float(NULL[NULL["trials"] == 12]["E[max SR | null]"].iloc[0])
print(f"\ngross Sharpe {gross_sr:.3f}   net {net_sr:.3f}")
print(f"E[max SR | null] at 12 trials: {null_12:.3f}")

assert gross_sr < null_12, (
    "the gross Sharpe now clears the 12-trial null; the verdict in this "
    "notebook needs re-deriving"
)
print("\nVERDICT: the GROSS Sharpe is below the null expectation for a 12-cell")
print("search, and the exit-rule x minimum-hold sweep alone was 12 cells.")
print("No cost assumption rescues this, because the failure is in the gross number.")

# %% [markdown]
# ## 10. Robustness
#
# The equity path, and the drawdown that the Sharpe alone does not convey.

# %%
from BT.trade_dashboard import compare_curves

try:
    fig = compare_curves({k: v for k, v in ARMS.items()}, span_years=span)
    fig.show()
except Exception as exc:                                          # noqa: BLE001
    print(f"compare_curves unavailable ({exc}); plotting directly")
    import plotly.graph_objects as go
    fig = go.Figure()
    for k, v in ARMS.items():
        fig.add_trace(go.Scatter(x=v.index, y=v.to_numpy(), name=k, mode="lines"))
    fig.update_layout(title="W4 equity, base vs zero cost",
                      yaxis_title="cumulative MTM, USD", height=420)
    fig.show()

# %%
dd = ARMS["base"] - ARMS["base"].cummax()
print(f"time in drawdown: {float((dd < 0).mean()):.1%} of days")
print(f"worst drawdown  : {float(dd.min()):,.0f}")
print(f"terminal        : {float(ARMS['base'].iloc[-1]):,.0f}")

# %% [markdown]
# ## 11. Trade log

# %%
LOG = pd.DataFrame([{
    "pair": e.pair,
    "side": "flattener" if e.side == 1 else "steepener",
    "entry": e.entry.date(), "exit": e.exit.date(), "bdays": e.days,
} for e in eps]).sort_values("entry")
print(f"{len(LOG)} episodes")
print(LOG.head(20).to_string(index=False))
print("...")
print(LOG.groupby(["pair", "side"]).size().unstack(fill_value=0).to_string())

# %% [markdown]
# ## 12. Reading this notebook
#
# * **The result is a negative one and it is not about costs.** Section 9 is the
#   verdict: the gross Sharpe sits below what a zero-edge strategy would be
#   expected to produce from the search that found it. Costs (55% of gross) only
#   make it worse, and the cost charged here is already more conservative than
#   the one external datapoint available.
#
# * **The screen underneath it is sound.** 120 published cells reproduce in
#   rank (spearman 0.988 on the decision statistic). What does not transfer is
#   the *level*, and Citi's absolute thresholds with it — which is why the rule
#   is keyed on rank and percentile.
#
# * **Section 8 says it is duration.** The only factor distinguishable from
#   noise is level, at t = −4.85, and the book loses to it. The convexity row is
#   not evidence of absence at daily frequency; the verdict does not rest on it.
#
# * **What would have to change.** Not the thresholds — the search is what
#   killed it. It needs fewer, larger, longer holds so `n_eff` rises, or a hedge
#   that removes the drawdown rather than the return. `factor_neutral_sizing`
#   already computes a PC1 hedge and is the obvious next thing to try.
#
# Full write-up: `docs/convexityrv/results/w4-ultra-long-risk-adjusted-carry.md`.
