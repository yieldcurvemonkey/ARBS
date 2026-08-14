# %% [markdown]
# # Strategy 3 grid search — which forward flattener is long vol *and* paid to hold?
#
# The companion to `strat3_strikeless_vol_backtest.ipynb`, which runs one
# config through the production engine. This notebook runs the whole grid and
# ranks it.
#
# **The question, in the user's own words:**
#
# > "strat 3 is about finding structures that allow us to get **LONG VOL and
# > EARN THETA** via the forward curve structures."
#
# So this is not a Sharpe hunt. Every one of the fifteen pairs is long gamma —
# that is a theorem about `dM = M_long - M_short`, not an empirical finding, and
# section 4 checks it holds on every pair on every day. What separates them is
# **carry**: the roll a flattener pays for the privilege of being convex. The
# ranking table therefore carries `mean_carry_1y_bp`, `pct_days_carry_positive`
# and `mean_gamma_usd_bp2` next to the Sharpe, and **a Sharpe-optimal cell that
# is bleeding carry is flagged rather than crowned**.
#
# ## What is searched
#
# | axis | values | why |
# |---|---|---|
# | pair | the Citi 15-pair grid | `10y10y/{15y15y,20y5y,20y10y,20y15y,25y5y,25y10y}`, `15y5y/{20y5y,20y10y,20y15y,25y5y,25y10y}`, `15y10y/{25y5y,25y10y}`, `20y5y/{25y5y,25y10y}` |
# | `hedge_threshold_bp` | 10, 15, 20, 25, 30, 40 | Citi: "the Sharpe ratio ... doesn't change significantly if the threshold is chosen in the **15-30bp** range, but declines with a smaller or larger threshold" — a prediction this grid can falsify |
# | `resize_mode` | neutral, always_decrease | the PM's two exits: "delta hedge it to 0 risk (always decrease) or keep it constant" |
# | `beta` | 1.0, 1.025 | Citi's Oct-2019 reweight of the live 15y5y/20y10y trade |
# | `roll_months` | 12, 24 | Citi rolled "every year"; 24 tests whether the ageing helps or hurts |
# | entry rule | always-on, z-gated, BE/rv-gated, both, carry-gated | Doc A §8.1's own screen, made mechanical |
#
# ## The reference point
#
# Citi Figure 4, sample 12/31/2013-5/7/2019, $100K DV01, 25bp hedging, net of
# their costs: **10y5y/15y15y 0.05, 10y10y/15y15y 0.13, 10y10y/20y10y 0.16,
# 10y10y/20y15y 0.24, 10y10y/25y10y 0.35, 15y5y/20y10y 0.18, 15y5y/20y15y 0.25,
# 20y5y/25y10y 0.30.** Different sample (ours is 2019-2026), same size, same
# hedging rule, same cost schedule. Their number appears as a column on every
# row it exists for, so the comparison is never left to memory.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import itertools
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
from RVUtils.ConvexityRV.curve_ops import payoff_profile

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
CURVE = "USD-SOFR-1D"
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 200)

# %% [markdown]
# ## 1. The config — the grid axes

# %%
GRID = {
    # --- WHAT ------------------------------------------------------------
    "pairs": list(S3.PAIRS_15),

    # --- THE HEDGE -------------------------------------------------------
    "thresholds": [10.0, 15.0, 20.0, 25.0, 30.0, 40.0],   # bp move in the LONGER rate
    "resize_modes": ["neutral", "always_decrease"],
    "betas": [1.0, 1.025],
    "roll_months": [12, 24],

    # --- THE ENTRY GATE (lag-1, scaling an always-on aged ledger) --------
    "entry_rules": [
        {"entry_rule": "always"},
        {"entry_rule": "z", "z_window": "1y", "z_min": 1.0},
        {"entry_rule": "z", "z_window": "3y", "z_min": 1.0},
        {"entry_rule": "be_ratio", "be_ratio_max": 0.80},
        {"entry_rule": "be_ratio", "be_ratio_max": 0.50},
        {"entry_rule": "z_and_be", "z_window": "3y", "z_min": 0.5, "be_ratio_max": 0.80},
        {"entry_rule": "carry", "carry_min_bp": 0.0},      # long gamma AND paid: the thesis
    ],

    # --- SIZING AND COSTS ------------------------------------------------
    "package_dv01_usd": 100_000.0,
    "cost_multipliers": [0.0, 1.0, 2.0],   # gross | Citi Fig-9 | capacity stress

    # --- SAMPLE ----------------------------------------------------------
    "start": datetime.date(2019, 1, 1),
    "end": datetime.date(2026, 8, 14),
}
PRIMARY_COST = 1.0            # the multiplier every headline number is quoted at
SPAN_YEARS = (pd.Timestamp(GRID["end"]) - pd.Timestamp(GRID["start"])).days / 365.25
print(json.dumps({k: (str(v) if isinstance(v, datetime.date) else v)
                  for k, v in GRID.items() if k != "pairs"}, indent=1))
print(f"pairs {len(GRID['pairs'])}, span_years {SPAN_YEARS:.2f}")

# %% [markdown]
# ## 2. The planted-answer sign test, live
#
# Re-measured on every execution. `bpv < 0` on a CURVE package must be the
# flattener, and the flattener must be the convex leg; a regression in
# `resolve_pricable` would invert the entire grid without raising.

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=CURVE, structure_kwargs={"bpv": bpv}, tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)])])
    bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in dates]),
                             strategy=strat, mdp=IRSwapsMDP(source="CITIVELO_EXCEL"),
                             show_progress=False)
    bt.run()
    return float(pd.Series(bt.mtm_history).iloc[-1])


plus, minus = _run_sign_probe(+100_000.0), _run_sign_probe(-100_000.0)
print(f"+bpv {plus:+,.0f}   -bpv {minus:+,.0f}")
assert plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(plus + minus) < 1e-6 * abs(plus), "buy/sell must mirror -- seam regressed?"

_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
_p22 = _mdp.get_pricer({"curve_name": CURVE, "timestamp": datetime.date(2022, 9, 13),
                        "offline": True})
_q = IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.NPV, curve=CURVE,
                 structure_kwargs={"front_tenor": "10Yx10Y", "back_tenor": "20Yx10Y",
                                   "bpv": -100_000.0})
_pk, _w = _q.resolve_package(pricer_or_curve=_p22)
_pk = [_p22.resolve_pricable(x, rw) for x, rw in zip(_pk, _w)]
_prof = payoff_profile(_p22, _pk, [-250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250],
                       horizon_date=None) / 100_000.0
print(f"10Yx10Y/20Yx10Y flattener payoff, bp: {np.round(_prof, 1).tolist()}")
assert (np.diff(_prof, 2) > 0).all(), "bpv<0 CURVE is not long gamma -- sign inverted"
assert np.allclose(np.round(_prof, 1),
                   [104.9, 60.0, 29.9, 11.6, 2.3, 0.4, 0.0, 0.9, 2.9, 9.5, 18.7, 29.7, 41.7],
                   atol=0.05), "the committed payoff regression table has moved"
print("SIGN + CONVEXITY + REGRESSION TABLE PASS")

# %% [markdown]
# ## 3. The precomputed panels
#
# `scripts/strat3_build_panels.py` produced both. The screen is constant
# maturity; the ledgers hold aged packages. Ledgers are stored at **zero cost**
# with the traded RISK recorded separately, so every cost multiplier below is a
# re-charge of the same path rather than a re-run of it.

# %%
SCREEN = pd.read_parquet(DATA / "strat3_screen.parquet")
LEDGERS_RAW = pd.read_parquet(DATA / "strat3_ledgers.parquet")

LEDGERS = {}
for key, grp in LEDGERS_RAW.groupby(level=["pair", "roll_months", "threshold_bp",
                                           "beta", "resize_mode"]):
    pair, rm, th, beta, mode = key
    # plain python types: the parquet round trip gives numpy scalars, and the
    # lookup key ``run_grid`` builds comes off a dataclass holding python ones
    LEDGERS.setdefault(tuple(pair.split("/")), {})[(int(rm), float(th), float(beta), str(mode))] = (
        grp.droplevel(["pair", "roll_months", "threshold_bp", "beta", "resize_mode"]).sort_index())

SCREENS = {p: SCREEN.xs(p, level="pair").sort_index()
           for p in SCREEN.index.get_level_values("pair").unique()}

_v = LEDGERS_RAW.reset_index()[["roll_months", "threshold_bp", "beta", "resize_mode"]].drop_duplicates()
print(f"screen  {SCREEN.shape}  {SCREEN.index.get_level_values('date').min().date()} .. "
      f"{SCREEN.index.get_level_values('date').max().date()}")
print(f"ledgers {LEDGERS_RAW.shape}  {len(LEDGERS)} pairs x {len(_v)} hedging variants")
_any = next(iter(next(iter(LEDGERS.values())).values()))
print(f"ledger dates {_any.index.min().date()} .. {_any.index.max().date()} ({len(_any)} days)")
assert len(LEDGERS) == 15, f"expected 15 pairs, got {sorted(LEDGERS)}"
assert len(_v) == len(GRID["thresholds"]) * len(GRID["resize_modes"]) * len(GRID["betas"]) \
    * len(GRID["roll_months"]), "the cached variant set does not match the grid"

# %% [markdown]
# ## 4. Known-answer checks
#
# Three, before any ranking is read.
#
# **(a) Citi Figure 7**, close of 2019-05-08 — the external known answer, eight
# published levels and carries.
#
# **(b)/(c) DV01 neutrality and convexity, on every pair on every day** of the
# 3,397-day screen. Not a spot check: `package_dv01 ~ 0` and `gamma > 0` are
# structural claims and the panel can test them 50,955 times.
#
# **(d) The sign probe** — section 2.

# %%
_P = _mdp.get_pricer({"curve_name": CURVE, "timestamp": datetime.date(2019, 5, 8),
                      "offline": True})
FIG7 = S3.screen_frame(_P, list(S3.CITI_FIG7_SCREEN), asof=datetime.date(2019, 5, 8),
                       include_query_carry=True).set_index("pair")
_pub = pd.DataFrame([{"pair": f"{a}/{b}", "citi_level": v[0], "citi_carry": v[3]}
                     for (a, b), v in S3.CITI_FIG7_SCREEN.items()]).set_index("pair")
TIE = FIG7.join(_pub)
TIE["d_level"] = TIE.level_bp - TIE.citi_level
TIE["d_carry"] = TIE.carry_1y_bp - TIE.citi_carry
display(TIE[["level_bp", "citi_level", "d_level", "carry_1y_bp", "citi_carry", "d_carry",
             "carry_query_bp", "gamma_ratio", "be_daily_analytic", "be_daily_exact"]].round(3))

_scr_all = SCREEN
checks = [
    ("(a) Fig 7 levels within 1.5bp", TIE.d_level.abs().max() < 1.5, TIE.d_level.abs().max()),
    ("(a) Fig 7 carry within 1.0bp", TIE.d_carry.abs().max() < 1.0, TIE.d_carry.abs().max()),
    ("(b) package PV01 ~ 0 on 2019-05-08",
     FIG7.package_dv01_usd.abs().max() < 1e-6 * 100_000.0, FIG7.package_dv01_usd.abs().max()),
    ("(c) gamma > 0 on every pair, every day",
     bool((_scr_all.gamma_usd_bp2 > 0).all()), float(_scr_all.gamma_usd_bp2.min())),
    ("(c) repriced gamma == dM/1e4 within 10%, every day",
     bool(_scr_all.gamma_ratio.between(0.90, 1.10).all()),
     f"{_scr_all.gamma_ratio.min():.3f}..{_scr_all.gamma_ratio.max():.3f}"),
    ("BE(analytic) == BE(repriced) within 5% where carry < 0",
     bool((_scr_all.loc[_scr_all.carry_1y_bp < 0, "be_daily_exact"]
           / _scr_all.loc[_scr_all.carry_1y_bp < 0, "be_daily_analytic"]).between(0.95, 1.05).all()),
     float((_scr_all.loc[_scr_all.carry_1y_bp < 0, "be_daily_exact"]
            / _scr_all.loc[_scr_all.carry_1y_bp < 0, "be_daily_analytic"]).max())),
    ("BE is exactly 0 wherever carry >= 0",
     bool((_scr_all.loc[_scr_all.carry_1y_bp >= 0, "be_daily_analytic"] == 0).all()),
     float(_scr_all.loc[_scr_all.carry_1y_bp >= 0, "be_daily_analytic"].max())),
]
display(pd.DataFrame(checks, columns=["check", "ok", "value"]))
assert all(ok for _, ok, _ in checks), "known-answer checks FAILED"
print(f"KNOWN-ANSWER PASS ({len(_scr_all):,} pair-days checked for (b)/(c))")

# %% [markdown]
# ## 5. The ex-ante screen, by pair
#
# Before any P&L: which pairs are structurally paid to be long gamma? This is
# the table the brief's objective is really about, and it splits the universe
# into two families that no amount of hedge tuning will merge.

# %%
_w = SCREEN[(SCREEN.index.get_level_values("date") >= pd.Timestamp(GRID["start"]))
            & (SCREEN.index.get_level_values("date") <= pd.Timestamp(GRID["end"]))]
EXANTE = _w.groupby("pair").agg(
    mean_level_bp=("level_bp", "mean"),
    mean_carry_1y_bp=("carry_1y_bp", "mean"),
    pct_days_carry_pos=("carry_1y_bp", lambda s: 100 * (s >= 0).mean()),
    mean_gamma_usd_bp2=("gamma_usd_bp2", "mean"),
    mean_be_daily_bp=("be_daily_analytic", "mean"),
    mean_rlzd_vol_bp=("rlzd_vol_bp", "mean"),
    mean_be_over_rv=("be_over_rv", "mean"),
).round(3)
EXANTE["dM_years"] = [S3.delta_m_years(*p.split("/")) for p in EXANTE.index]
EXANTE["citi_fig4_sharpe"] = [S3.CITI_FIG4_SHARPE.get(tuple(p.split("/")), np.nan)
                              for p in EXANTE.index]
display(EXANTE.sort_values("mean_carry_1y_bp", ascending=False))

# %% [markdown]
# ## 6. The grid
#
# Every cell is scored off the cached zero-cost ledgers — no repricing happens
# here, which is what makes a grid this size affordable. Sharpe is Citi's own
# Figure-4 convention: `mean(daily $) / std(daily $) x sqrt(252)`, computed on
# every day in the sample including flat ones, so a gated book and an always-on
# one are on the same scale.

# %%
CELLS = S3.grid_cells(GRID["pairs"], GRID["thresholds"], GRID["resize_modes"],
                      GRID["betas"], GRID["roll_months"], GRID["entry_rules"])
print(f"{len(CELLS):,} cells x {len(GRID['cost_multipliers'])} cost multipliers")

t0 = time.time()
frames = []
for mult in GRID["cost_multipliers"]:
    g = S3.run_grid(LEDGERS, SCREENS, CELLS, package_dv01_usd=GRID["package_dv01_usd"],
                    cost_multiplier=mult, window=(GRID["start"], GRID["end"]))
    g["cost_multiplier"] = mult
    frames.append(g)
RESULTS = pd.concat(frames, ignore_index=True)
print(f"scored {len(RESULTS):,} rows in {time.time()-t0:.0f}s")
assert len(RESULTS) == len(CELLS) * len(GRID["cost_multipliers"]), "cells went missing"
RESULTS.to_csv(DATA / "strat3_grid_results.csv", index=False)
print(f"-> {DATA / 'strat3_grid_results.csv'}")

R1 = RESULTS[RESULTS.cost_multiplier == PRIMARY_COST].copy()
COLS = ["pair", "threshold_bp", "resize_mode", "beta", "roll_months", "entry_rule",
        "be_ratio_max", "sharpe", "sharpe_ex_mtm", "total_net_usd", "net_bp",
        "carry_bp", "harvest_bp", "mtm_bp", "net_ex_mtm_bp",
        "mean_carry_1y_bp", "pct_days_carry_positive",
        "mean_gamma_usd_bp2", "mean_be_over_rv", "occupancy", "n_hedges", "skew",
        "hit_rate", "max_dd_usd", "citi_fig4_sharpe"]

# %% [markdown]
# ### 6.1 Top 25 by annualised Sharpe — with the carry column attached
#
# `mean_carry_1y_bp` is the ex-ante roll of the structure and
# `pct_days_carry_positive` is how often it was actually paid. `carry_bp` is
# the realised roll bucket of the book itself. **Read those before the Sharpe.**

# %%
TOP = R1.sort_values("sharpe", ascending=False).head(25)[COLS]
TOP.insert(0, "flag", np.where(TOP.mean_carry_1y_bp >= 0, "PAID",
                               np.where(TOP.mean_carry_1y_bp > -1.0, "cheap", "BLEEDS")))
display(TOP.round(3).reset_index(drop=True))

_best = R1.loc[R1.sharpe.idxmax()]
print(f"\nSharpe-optimal cell: {_best.pair} @{_best.threshold_bp:g}bp "
      f"{_best.resize_mode} beta={_best.beta} roll={_best.roll_months}m "
      f"entry={_best.entry_rule}")
print(f"  Sharpe {_best.sharpe:.3f}, net ${_best.total_net_usd:,.0f}, "
      f"mean 1y carry {_best.mean_carry_1y_bp:+.2f}bp "
      f"({_best.pct_days_carry_positive*100:.0f}% of days >= 0)")
if _best.mean_carry_1y_bp < 0:
    print("  ** FLAG: this cell is SHORT theta. It is long gamma (every cell is), "
          "but it pays to be, which is not the structure the brief asks for.")

# %% [markdown]
# ### 6.2 The same table ranked the way the brief asks
#
# Sharpe **subject to** the structure being paid to hold: filtered to cells
# whose mean ex-ante 1y carry is non-negative. If this table is empty, no
# structure in the Citi grid earned theta over 2019-2026 and that is itself the
# answer.

# %%
PAID = R1[R1.mean_carry_1y_bp >= 0].sort_values("sharpe", ascending=False)
print(f"{len(PAID):,} of {len(R1):,} cells are long gamma AND non-negative carry "
      f"({100*len(PAID)/len(R1):.1f}%)")
display(PAID.head(20)[COLS].round(3).reset_index(drop=True))

NEAR = R1[R1.mean_carry_1y_bp >= -0.5].sort_values("sharpe", ascending=False)
print(f"\nrelaxed to carry >= -0.5bp/yr: {len(NEAR):,} cells")
display(NEAR.head(15)[COLS].round(3).reset_index(drop=True))

# %% [markdown]
# ### 6.3 By pair, always-on, at Citi's own 25bp — the like-for-like comparison
#
# One row per pair, at exactly Citi's specification (25bp, DV01-neutral, annual
# roll, always on, $100K DV01, their cost schedule). Their Figure-4 Sharpe sits
# in the last column. Different sample — theirs is 12/2013-5/2019, ours is
# 1/2019-8/2026 — so this is a robustness read, not a reproduction.

# %%
BASE = R1[(R1.threshold_bp == 25.0) & (R1.resize_mode == "neutral")
          & (R1.beta == 1.0) & (R1.roll_months == 12)
          & (R1.entry_rule == "always")].set_index("pair")
LIKE = BASE[["sharpe", "sharpe_ex_mtm", "total_net_usd", "net_bp", "carry_bp",
             "harvest_bp", "mtm_bp", "net_ex_mtm_bp",
             "mean_carry_1y_bp", "pct_days_carry_positive", "mean_gamma_usd_bp2",
             "mean_be_over_rv", "n_hedges", "skew", "hit_rate", "max_dd_usd",
             "citi_fig4_sharpe"]].sort_values("sharpe", ascending=False)
display(LIKE.round(3))

_both = LIKE.dropna(subset=["citi_fig4_sharpe"])
print(f"\n{len(_both)} pairs overlap Citi's Figure 4.")
print(f"  ours  mean {_both.sharpe.mean():+.3f}, range {_both.sharpe.min():+.3f}..{_both.sharpe.max():+.3f}")
print(f"  Citi  mean {_both.citi_fig4_sharpe.mean():+.3f}, "
      f"range {_both.citi_fig4_sharpe.min():+.3f}..{_both.citi_fig4_sharpe.max():+.3f}")
if len(_both) > 2:
    print(f"  cross-sectional rank corr (Spearman): "
          f"{_both[['sharpe','citi_fig4_sharpe']].corr(method='spearman').iloc[0,1]:+.3f}")

# %% [markdown]
# ### 6.4 The gamma line on its own — with the directional windfall removed
#
# **This is the most important table in the notebook, and it is the one that
# most changes the reading of section 6.3.**
#
# Over 2019-2026 the long-end forward curve inverted enormously: the mean
# 10y10y/20y10y level went from about −14bp in May 2019 to about −56bp in
# August 2026. A flattener held through that made a fortune **for a reason that
# has nothing to do with convexity** — it was long the move. That P&L lands in
# the `mtm` bucket, and on most pairs it is larger than every other bucket put
# together.
#
# So the columns to read are:
#
# * `harvest_bp` — the P&L of the resizes alone. This is the strategy.
# * `carry_bp` — the roll the position paid to exist. This is the theta bill.
# * `net_ex_mtm_bp` = `harvest + carry − costs` — **the delta-hedged vol trade
#   with the direction stripped out.** Positive means the gamma paid for its own
#   theta and its own transaction costs. That is exactly the claim the note
#   makes and the brief asks for.
# * `mtm_bp` — where the curve went. Not a skill.
#
# `sharpe_ex_mtm` is the annualised Sharpe of that same direction-free series.

# %%
GAMMA_VIEW = BASE[["harvest_bp", "carry_bp", "mtm_bp", "net_ex_mtm_bp", "net_bp",
                   "sharpe_ex_mtm", "sharpe", "n_hedges", "mean_gamma_usd_bp2",
                   "mean_carry_1y_bp"]].copy()
GAMMA_VIEW["harvest_over_carry"] = (GAMMA_VIEW.harvest_bp / GAMMA_VIEW.carry_bp.abs()).replace(
    [np.inf, -np.inf], np.nan)
GAMMA_VIEW["harvest_per_hedge_usd"] = (BASE.harvest_usd / BASE.n_hedges).round(0)
GAMMA_VIEW["mtm_share_of_net"] = (BASE.mtm_bp / BASE.net_bp).round(3)
display(GAMMA_VIEW.sort_values("net_ex_mtm_bp", ascending=False).round(3))

_pos = GAMMA_VIEW[GAMMA_VIEW.net_ex_mtm_bp > 0]
print(f"\n{len(_pos)}/{len(GAMMA_VIEW)} pairs are profitable with the curve move removed "
      f"(harvest + carry - costs > 0), at Citi's own 25bp specification.")
print(f"mean mtm share of net across the 15 pairs: "
      f"{GAMMA_VIEW.mtm_share_of_net.mean():.2f}")

# %% [markdown]
# ### 6.5 Ranked the way the brief asks, twice over
#
# `sharpe_ex_mtm` ranks the **vol trade**; `mean_carry_1y_bp >= 0` restricts to
# structures that are **paid to hold**. A cell that clears both is the thing
# the objective actually names: long gamma, earning theta, with the direction
# taken out.

# %%
BOTH = R1[(R1.mean_carry_1y_bp >= 0) & (R1.net_ex_mtm_bp > 0)].sort_values(
    "sharpe_ex_mtm", ascending=False)
print(f"{len(BOTH):,} of {len(R1):,} cells are long gamma, non-negative carry, AND "
      f"profitable ex-direction")
display(BOTH.head(20)[COLS].round(3).reset_index(drop=True))

VOLONLY = R1.sort_values("sharpe_ex_mtm", ascending=False)
print("\ntop 15 by direction-free Sharpe, carry unconstrained:")
display(VOLONLY.head(15)[COLS].round(3).reset_index(drop=True))

# %% [markdown]
# ## 7. Stability, not a winning cell
#
# A single best cell out of several thousand is a lottery ticket. What matters is whether
# the surface is flat where Citi says it is flat.
#
# > "we have found that the Sharpe ratio of the strategy doesn't change
# > significantly if the threshold is chosen in the **15-30bp range**, but
# > declines with a smaller or larger threshold."
#
# That is a falsifiable prediction about the shape of the threshold axis, made
# on a different sample. Section 7.1 tests it directly.

# %%
STAB = (R1[(R1.entry_rule == "always") & (R1.resize_mode == "neutral")
           & (R1.beta == 1.0) & (R1.roll_months == 12)]
        .pivot(index="pair", columns="threshold_bp", values="sharpe"))
STAB["range"] = STAB.max(axis=1) - STAB.min(axis=1)
STAB["best_th"] = STAB[GRID["thresholds"]].idxmax(axis=1)
display(STAB.round(3).sort_values(15.0, ascending=False))

_mid = [t for t in GRID["thresholds"] if 15 <= t <= 30]
_out = [t for t in GRID["thresholds"] if t < 15 or t > 30]
_pred = pd.DataFrame({
    "sharpe_15_30bp": STAB[_mid].mean(axis=1),
    "sharpe_10_and_40bp": STAB[_out].mean(axis=1),
    "spread_inside_band": STAB[_mid].max(axis=1) - STAB[_mid].min(axis=1),
})
_pred["citi_claim_holds"] = _pred.sharpe_15_30bp >= _pred.sharpe_10_and_40bp
display(_pred.round(3))
_held, _n = int(_pred.citi_claim_holds.sum()), len(_pred)
print(f"\nCiti's 15-30bp plateau claim holds on {_held}/{_n} pairs; "
      f"mean Sharpe inside the band {_pred.sharpe_15_30bp.mean():+.3f} "
      f"vs {_pred.sharpe_10_and_40bp.mean():+.3f} outside it. "
      f"Median spread WITHIN the band: {_pred.spread_inside_band.median():.3f}.")

# %%
import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

_hm = STAB[GRID["thresholds"]].sort_index()
fig = go.Figure(go.Heatmap(z=_hm.values, x=[f"{t:g}bp" for t in _hm.columns], y=_hm.index,
                           colorscale="RdYlGn", zmid=0,
                           text=np.round(_hm.values, 2), texttemplate="%{text}",
                           colorbar=dict(title="Sharpe")))
fig.update_layout(template="plotly_dark", height=620,
                  title="annualised Sharpe by pair x hedge threshold "
                        "(always-on, DV01-neutral, annual roll, net of Citi Fig-9 costs)")
fig.show()

# %% [markdown]
# ### 7.1 The other axes
#
# Each knob's marginal effect, averaged over everything else. A knob whose
# marginal effect is inside the noise is a knob that should be left alone.

# %%
for axis in ("resize_mode", "beta", "roll_months", "entry_rule", "cost_multiplier"):
    src = RESULTS if axis == "cost_multiplier" else R1
    t = src.groupby(axis).agg(n=("sharpe", "size"), mean_sharpe=("sharpe", "mean"),
                              median_sharpe=("sharpe", "median"),
                              mean_sharpe_ex_mtm=("sharpe_ex_mtm", "mean"),
                              mean_net_usd=("total_net_usd", "mean"),
                              mean_carry_bp=("carry_bp", "mean"),
                              mean_harvest_bp=("harvest_bp", "mean"),
                              mean_net_ex_mtm_bp=("net_ex_mtm_bp", "mean"),
                              mean_occupancy=("occupancy", "mean"))
    print(f"\n--- {axis} ---")
    display(t.round(3))

# %% [markdown]
# ### 7.2 Carry against Sharpe — the efficient frontier the brief asks for
#
# One point per pair at Citi's own specification. Up-and-to-the-right is
# "long vol and earns theta"; the bottom-left quadrant is long vol that pays
# handsomely for the privilege.

# %%
_pts = BASE.reset_index()
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=_pts.mean_carry_1y_bp, y=_pts.sharpe, mode="markers+text",
    text=_pts.pair, textposition="top center", textfont=dict(size=9),
    marker=dict(size=np.clip(_pts.mean_gamma_usd_bp2 / 12, 6, 30),
                color=_pts.pct_days_carry_positive, colorscale="Viridis",
                showscale=True, colorbar=dict(title="% days<br>carry >= 0")),
    hovertemplate="%{text}<br>carry %{x:.2f}bp/yr<br>Sharpe %{y:.3f}<extra></extra>"))
fig.add_vline(x=0, line=dict(color="#ff5c5c", dash="dash"))
fig.add_hline(y=0, line=dict(color="#7b8394", dash="dot"))
fig.update_layout(template="plotly_dark", height=620,
                  xaxis_title="mean ex-ante 1y carry (bp) -- right of the red line is PAID to hold",
                  yaxis_title="annualised Sharpe, net of Citi Fig-9 costs",
                  title="marker size = mean $ gamma per bp^2; every pair here is long gamma")
fig.show()

# %% [markdown]
# ## 8. Equity curves of the cells worth looking at

# %%
from BT.trade_dashboard import compare_curves


def _book(pair, rm, th, beta, mode, entry=None, mult=PRIMARY_COST):
    led = LEDGERS[tuple(pair.split("/"))][(rm, th, beta, mode)]
    led = led[(led.index >= pd.Timestamp(GRID["start"])) & (led.index <= pd.Timestamp(GRID["end"]))]
    cfg = S3.Strat3Config(short_leg=pair.split("/")[0], long_leg=pair.split("/")[1],
                          roll_months=rm, hedge_threshold_bp=th, beta=beta,
                          resize_mode=mode, **(entry or {"entry_rule": "always"}))
    state = None if cfg.entry_rule == "always" else S3.entry_state(SCREENS[pair], cfg, led.index)
    st = S3.book_stats(led, state, costs=S3.cost_schedule_for(*cfg.pair, multiplier=mult),
                       package_dv01_usd=GRID["package_dv01_usd"])
    eq = st["equity"]
    d = eq.diff().fillna(eq.iloc[0])
    return pd.DataFrame({"timestamp": eq.index, "pnl": d.to_numpy()}), st


_curves, _rows = {}, []
for pair in LIKE.index[:6]:
    b, st = _book(pair, 12, 25.0, 1.0, "neutral")
    _curves[pair] = b
    _rows.append({"pair": pair, **{k: st[k] for k in
                                   ("total_net_usd", "sharpe", "carry_bp", "harvest_bp",
                                    "mtm_bp", "n_hedges", "max_dd_usd")}})
fig = compare_curves(_curves, title="top six pairs at Citi's own 25bp specification, "
                                    "net of Fig-9 costs")
fig.show()
display(pd.DataFrame(_rows).set_index("pair").round(3))

# %%
_pair = LIKE.index[0]
_curves2 = {f"@{t:g}bp": _book(_pair, 12, t, 1.0, "neutral")[0] for t in GRID["thresholds"]}
_curves2["always_decrease @25bp"] = _book(_pair, 12, 25.0, 1.0, "always_decrease")[0]
_curves2["beta 1.025 @25bp"] = _book(_pair, 12, 25.0, 1.025, "neutral")[0]
fig = compare_curves(_curves2, title=f"{_pair}: the hedge threshold and the resize mode")
fig.show()

# %% [markdown]
# ## 9. What the search cost
#
# The best Sharpe out of several thousand tries is not the Sharpe to expect
# from it out of sample. The deflated Sharpe ratio (Bailey & López de Prado)
# discounts the maximum by the expected maximum of that many draws under a null
# of zero skill, using the winning cell's OWN daily return moments — not the
# cross-section's — for the non-normality correction.

# %%
from scipy import stats as _st

_s = R1.sharpe.dropna()
_n_trials = len(R1)
_win = R1.loc[R1.sharpe.idxmax()]
_win_book, _win_stats = _book(_win.pair, int(_win.roll_months), float(_win.threshold_bp),
                              float(_win.beta), _win.resize_mode,
                              entry={"entry_rule": _win.entry_rule,
                                     "z_window": _win.z_window, "z_min": float(_win.z_min),
                                     "be_ratio_max": float(_win.be_ratio_max)})
_r = _win_stats["net_daily"]
_T = len(_r)
_sr = float(_r.mean() / _r.std(ddof=1))          # per-day Sharpe, the DSR's unit
_g3, _g4 = float(_r.skew()), float(_r.kurt() + 3.0)
_sr_std_cs = float(_s.std(ddof=1) / np.sqrt(252.0))   # cross-section, per-day units
_e_max = _sr_std_cs * ((1 - np.euler_gamma) * _st.norm.ppf(1 - 1.0 / _n_trials)
                       + np.euler_gamma * _st.norm.ppf(1 - 1.0 / (_n_trials * np.e)))
_z = ((_sr - _e_max) * np.sqrt(_T - 1)
      / np.sqrt(1 - _g3 * _sr + (_g4 - 1) / 4.0 * _sr ** 2))
display(pd.Series({
    "cells searched (at 1x cost)": _n_trials,
    "winning cell": f"{_win.pair} @{_win.threshold_bp:g}bp {_win.resize_mode} "
                    f"beta={_win.beta} roll={_win.roll_months}m {_win.entry_rule}",
    "sample days": _T,
    "winner annualised Sharpe": _sr * np.sqrt(252.0),
    "winner daily skew": _g3,
    "winner daily kurtosis": _g4,
    "cross-sectional Sharpe sd (annualised)": float(_s.std(ddof=1)),
    "expected max Sharpe under the null (annualised)": _e_max * np.sqrt(252.0),
    "deflated Sharpe p(true SR > 0)": float(_st.norm.cdf(_z)),
    "median cell Sharpe": float(_s.median()),
    "% of cells with Sharpe > 0": float(100 * (_s > 0).mean()),
    "Citi Fig-4 mean Sharpe (their sample)": float(np.mean(list(S3.CITI_FIG4_SHARPE.values()))),
}).to_frame("value"))

# %% [markdown]
# ## 10. Reading this notebook
#
# **Every cell in this grid is long gamma.** Section 4 checks it 50,955 times.
# So "is it long vol" is not the discriminating question and no ranking here
# turns on it. The discriminating question is what the position pays to be
# long gamma, which is the carry column, and that is set by which forward
# points the pair straddles — not by any hedging knob.
#
# **The gated entry rules scale an aged ledger.** A cell with `entry_rule != "always"`
# multiplies the always-on ledger's daily flows by a lag-1 {0,1} state and
# charges an initiation on every flip. It does not strike a fresh package at
# each entry. That understates the cost of re-entering at market and overstates
# the age of the position at entry; it is the same approximation
# `scripts/sv_citivelo_h13.py` documents. Treat a gated cell's Sharpe as an
# upper bound on the gated idea, and treat the always-on rows as the numbers
# that carry no such caveat.
#
# **Citi's Figure-4 Sharpes are on a different sample.** 12/2013-5/2019 versus
# our 1/2019-8/2026. The comparison in section 6.3 is a robustness read across
# two regimes, not a reproduction; the sample here contains the 2020 collapse
# and the 2022-2023 selloff, both of which move a convexity book far more than
# anything in theirs.
#
# **Costs are first-order.** Section 7.1's `cost_multiplier` row is not a
# sensitivity, it is a result. Anything that survives only at multiplier 0 is
# an artifact of not paying to trade.
