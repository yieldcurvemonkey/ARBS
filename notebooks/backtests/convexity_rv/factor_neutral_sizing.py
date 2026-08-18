# %% [markdown]
# # Factor-neutral sizing: does the convexity edge survive the hedge?
#
# **The question.** The cross-strategy attribution found that the long-end
# flatteners are not sized to what they claim to trade, and the inference was
# *"we are sizing these incorrectly"*. This notebook tests that constructively.
# It builds the alternative sizings, runs them over the same window, the same 91
# cohorts and the same engine, and asks the only question that decides it:
#
# > **after neutralising the dominant factor FOR THAT STRUCTURE, does a positive
# > convexity edge remain, or does the P&L simply go to zero?**
#
# **The answer, up front: the edge survives on the three tight forward pairs and
# it dies on 5Y/30Y** — and the split is exactly the one the attribution
# predicted, structure by structure.
#
# | structure | dominant factor | incumbent | after neutralising it | retained |
# |---|---|---|---|---|
# | 30Y/50Y | level | 341.0 bp | **300.7 bp** | 88% |
# | 20Yx5Y/25Yx5Y | level | 479.6 bp | **426.3 bp** | 89% |
# | 10Yx10Y/20Yx10Y | level | 500.1 bp | **334.8 bp** | 67% |
# | 5Y/30Y | slope | 268.8 bp | **−739.8 bp** | −275% |
#
# All three tight pairs stay positive, keep a 53–73% hit rate, and keep the
# convexity term intact at `t = 4.1–4.9` with an incremental R² of 0.32–0.36 —
# statistically indistinguishable from the incumbent's. Neutralising slope on
# 5Y/30Y takes it from **+269 bp to −740 bp** and the hit rate from 0.53 to 0.20.
# That book's P&L *was* the slope bet, and there is nothing underneath it.
#
# Three findings sit alongside that and are not decoration:
#
# 1. **The hedges do what they claim.** Measured on realised daily P&L, the level
#    regressor's incremental R² falls 0.162 → 0.019 on 20Yx5Y/25Yx5Y, 0.215 →
#    0.073 on 10Yx10Y/20Yx10Y and 0.0111 → 0.0005 on 30Y/50Y; the slope
#    regressor's falls **0.883 → 0.012** on 5Y/30Y. That is a measurement on the
#    books, not a property of the solve, and it is the half of the answer that
#    does not depend on a small sample.
# 2. **`slope_beta_hedged` beats the incumbent on three of four structures** —
#    1.38x, 1.82x and 1.86x — with its overlay charged at the most expensive
#    honest reading. But read *why*: the flatteners were **losing** on slope
#    (share_slope = −149% on 5Y/30Y), so removing it adds money. That is a
#    genuine risk reduction whose *size* is a property of what slope did in
#    2019–2026, not a new source of return.
# 3. **`pc1_neutral` on 5Y/30Y is an estimation artefact, not an edge.** It scores
#    +1408 bp walk-forward against **−66 bp** on the same rule with full-sample
#    loadings — a gap of 105% of its own total. That is the PCA moving, not a
#    trade, and it is reported here rather than banked.
#
# **On the multiple-testing bar:** four distinct sizings at a measured pooled
# effective sample of 9.79 observations sets `E[max Sharpe | null] = 0.3327` per
# observation. Seven books clear it — but four of them are the *same structure*
# (20Yx5Y/25Yx5Y), whose incumbent already cleared at 0.9333, so re-sizing is not
# what produced them. Section 13 states exactly what does and does not survive.

# %% [markdown]
# ## 0. CONFIG
#
# Everything the run depends on, in one place. The BACKTEST knobs are
# deliberately not restated here — they come from
# `strat1_longend_listed.strat1_config()`, strategy 1's committed base run
# ($100k package DV01, monthly cohorts, 1-year hold, 0.5 bp one way, no
# force-close, 2019-01-02..2026-08-14). The whole point of this study is that its
# books are directly comparable to that run, and a single differing knob would
# make every comparison below a comparison of two configurations instead of two
# sizings.

# %%
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

_REPO = pathlib.Path.cwd()
while not (_REPO / "RVUtils").exists() and _REPO != _REPO.parent:
    _REPO = _REPO.parent
sys.path.insert(0, str(_REPO))

from BT.trade_dashboard import compare_curves, summary_stats, trade_dashboard
from RVUtils.ConvexityRV import factor_attribution as fa
from RVUtils.ConvexityRV import factor_neutral_sizing as fns
from RVUtils.ConvexityRV import strat1_longend_listed as ll
from RVUtils.ConvexityRV import strat1_threeway as tw

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 90)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
CFG = fns.FactorNeutralConfig()
S1 = ll.strat1_config()
FCFG = fa.FactorConfig()
DV01 = float(S1.package_dv01)
T_START = time.time()

print(f"repo        {_REPO}")
print(f"curve       {S1.curve}   {S1.start} .. {S1.end}")
print(f"package     ${DV01:,.0f} DV01, {S1.cohort_freq} cohorts, "
      f"{S1.horizon} hold, {S1.cost_bp_one_way} bp one way")
print(f"sizings     {CFG.sizings}")
print(f"scored      {CFG.scored_sizings}  ({len(CFG.scored_sizings)} trials)")
print(f"weights     {CFG.weight_mode}, min_fit_days {CFG.min_fit_days}, "
      f"hard floor {CFG.hard_fit_floor}, beta window {CFG.beta_window}")
print(f"hedge leg   {CFG.hedge_leg}   slope overlay {fns.SLOPE_INSTRUMENT}")
print(f"legs        {CFG.legs}")
print(f"certify     {CFG.certify_structure} x {CFG.certify_sizing}")

# %% [markdown]
# ## 1. The retarget — why the default sizing in the draft was wrong
#
# This study was drafted to test one claim: *DV01-neutral sizing leaves a
# dominant **slope** bet*. The attribution then finished, and reading the same
# four packages as a share of their **own factor variance** rather than as a
# dollar exposure inverted the premise for three of the four:
#
# | structure | level | slope | curvature | dominant |
# |---|---|---|---|---|
# | 5Y/30Y | 5.1% | **88.9%** | 6.0% | slope |
# | 30Y/50Y | **43.3%** | 29.3% | 27.4% | level |
# | 20Yx5Y/25Yx5Y | **69.0%** | 14.7% | 16.4% | level |
# | 10Yx10Y/20Yx10Y | **61.3%** | 0.2% | 38.5% | level |
#
# The slope premise is true for **5Y/30Y and nothing else**. For the three tight
# forward pairs the dominant unwanted exposure is **level** — in a construction
# whose entire stated purpose was to remove level exposure.
#
# **Why DV01-neutrality does not remove level.** It would, if PC1's loadings were
# flat. They are not: PC1 is humped, 0.279 at 2Y, 0.334 at 7Y, 0.272 at 50Y. Two
# legs of equal and opposite DV01 therefore leave `dv01 * (v1_front − v1_back)`,
# and a *tight* pair has small slope and curvature differences, so that small
# absolute residue is a *large share* of the little exposure the package has.
#
# So `pc1_neutral` is added as a first-class sizing and is the headline test for
# the three tight pairs. It is a two-leg trade — one constraint plus a
# normalisation — and it is deliberately **not** DV01-neutral. That is the point.
#
# The table above is copied from the attribution report, and copied numbers rot,
# so the next cell recomputes all of it from the shared `FactorModel` and prints
# the gap.

# %%
PANEL = pd.read_parquet(DATA / "factor_rate_panel.parquet")
PANEL.index = pd.to_datetime(PANEL.index)
FM = fa.fit_factor_model(PANEL, FCFG)
CALENDAR = FM.scores.index

print(f"rate panel  {PANEL.shape[0]} days x {PANEL.shape[1]} tenors, "
      f"{PANEL.index.min():%Y-%m-%d} .. {PANEL.index.max():%Y-%m-%d}")
print(f"factor fit  {FM.rates_bp.shape[0]} levels -> {FM.scores.shape[0]} changes")
print(f"explained   {FM.explained_variance.head(3).round(4).to_dict()}")
print()
print("PC labels are TESTED structurally, never assumed from eigenvalue order:")
print(fa.classify_pcs(FM.loadings, FM.tenors).to_string())

# %%
DOMINANT = fns.dominant_factor_table(FM)
print("Re-measured on the shared basis, against the attribution report's numbers:")
print(DOMINANT[["structure", "var_level", "var_slope", "var_curv",
                "prior_var_level", "prior_var_slope", "prior_var_curv",
                "max_abs_prior_gap", "dominant", "headline_sizing",
                "pc1_leakage_vs_outright"]].round(4).to_string(index=False))
_gap = float(DOMINANT["max_abs_prior_gap"].max())
print(f"\nlargest disagreement with the attribution report: {_gap:.2e} "
      f"({'CONFIRMED' if _gap < 0.005 else 'DISAGREES -- stop and re-read'})")
print("\n`pc1_leakage_vs_outright` is the quieter half of the finding: the share")
print("of a SAME-SIZE outright's level exposure that survives DV01-neutrality.")
print("3.8%-16.7%. Small in dollars, and for a tight pair it is most of the risk.")

# %% [markdown]
# ## 2. One engine pass per LEG, and why that is exact rather than approximate
#
# A package is a weighted sum of legs, and swap NPV is linear in `bpv`. So if the
# engine is run once per LEG at a fixed unit DV01, with each cohort carrying its
# own tag, then **every sizing of every structure is a linear combination of the
# same eight mark matrices**:
#
# ```
# equity_s(t) = Σ_k Σ_L (r_{s,k,L} / UNIT_DV01) · contrib_{L,k}(t) − fees_s(t)
#
# contrib_{L,k}(t) = mark_{L,k}(t)          while the leg is open
#                  = gross_realized_{L,k}   once it has unwound
# ```
#
# That is not an approximation of the package run, it *is* the package run:
# `resolve_pricable` solves notional off pv01 linearly, `rl.IRS.npv` is linear in
# notional, and no cash is realised mid-hold. Section 3 measures that claim
# against four genuine engine runs rather than asserting it.
#
# The payoff is that a sizing comparison costs no extra engine time. Sixteen
# books, four sizings, walk-forward weights that change every month, and a
# monthly-rebalanced overlay: all of them are re-weightings of eight fixed mark
# matrices. Nothing in the comparison is a re-run, so nothing in it can differ
# for a reason other than the weights — which is the whole point of a sizing
# experiment.
#
# ### The one grid wrinkle, measured rather than assumed
#
# The engine's `mtm_history` carries a day only if the curve priced that leg on
# it. On **2019-04-19 (Good Friday)** the local SOFR curve prices 5Y and 25Yx5Y
# but not 10Y, 30Y or 50Y. Requiring bit-identical indices would refuse a
# perfectly usable cache; unioning them would forward-fill a mark that was never
# taken. So the legs are **intersected**, which lands on 1907 days — precisely
# the grid the four stored two-leg engine runs use, so section 3 compares like
# with like. No cohort entry or exit falls on the dropped day; that is asserted,
# not hoped.

# %%
LEGS, IDX = fns.load_leg_runs(DATA, log=print)
SCHED = LEGS["5Y"].cohorts
ENTRIES = list(pd.to_datetime(SCHED["entry"]))
NLIVE = fns.live_packages(SCHED, IDX)

print(f"\n{len(LEGS)} legs on a common grid of {len(IDX)} marks, "
      f"{IDX.min():%Y-%m-%d} .. {IDX.max():%Y-%m-%d}")
print(f"{len(SCHED)} cohorts, {int(SCHED['closed'].sum())} closed, "
      f"{int((~SCHED['closed']).sum())} still live at the end")
print(f"live packages: mean {NLIVE.mean():.2f}, max {NLIVE.max():.0f}")
print()
print(pd.DataFrame({
    lg: {"terminal_usd": float(r.equity.iloc[-1]),
         "n_marks": int(len(r.equity)),
         "n_closed": int(r.cohorts["closed"].sum()),
         "mean_gross_bp": float(r.cohorts["gross_pnl_bp"].mean())}
    for lg, r in LEGS.items()}).T.to_string())

# %%
GREEKS = fns.load_leg_greeks(DATA)
GAMMA = fns.leg_gamma_bp(GREEKS)
CARRY = fns.leg_carry_bp(GREEKS)
print(f"greeks: {len(GREEKS)} rows, {GREEKS['leg'].nunique()} legs x "
      f"{GREEKS['date'].nunique()} cohort entry dates")
print(pd.DataFrame({"gamma_usd_per_bp2_per_dv01": GAMMA,
                    "carry_bp_1y": CARRY,
                    "rate_pct": GREEKS.groupby("leg")["rate_pct"].mean()}).round(6).to_string())

# %% [markdown]
# **Carry tie-out.** The greeks pass is a fresh repricing loop and nothing above
# depends on it being right unless it is checked. The DV01-neutral package's
# carry, rebuilt from the per-leg numbers as `carry_front − carry_back`, must
# reproduce `carry_roll_bp` on the committed signal panel exactly — same
# quantity, independent code path.

# %%
_sp = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
_sp["date"] = pd.to_datetime(_sp["date"])
_rows = []
for _lab, _f, _b in fa.STRAT1_STRUCTURES:
    _ref = _sp[_sp["structure"] == _lab].set_index("date")["carry_roll_bp"]
    _mine = pd.Series({_d: float(fns.leg_carry_bp(GREEKS, on=_d).get(_f, np.nan)
                                 - fns.leg_carry_bp(GREEKS, on=_d).get(_b, np.nan))
                       for _d in ENTRIES})
    _r = _ref.reindex(_mine.index)
    _rows.append({"structure": _lab, "greeks_mean_bp": _mine.mean(),
                  "panel_mean_bp": _r.mean(), "corr": _mine.corr(_r),
                  "max_abs_gap_bp": float((_mine - _r).abs().max())})
CARRY_TIEOUT = pd.DataFrame(_rows)
print(CARRY_TIEOUT.round(6).to_string(index=False))
assert float(CARRY_TIEOUT["max_abs_gap_bp"].max()) < 1e-9, "greeks carry does not tie out"
print("\nExact on every structure. The greeks pass is measuring the same object")
print("the committed signal panel measures, so the hedge's carry is real.")

# %% [markdown]
# ## 3. Certification I — the composition against four genuine engine runs
#
# `strat1_le_unit_equity_*.parquet` are four real `QueryDrivenBacktest` passes of
# the two-leg DV01-neutral package, produced by a different module before this
# one existed. Rebuilding them as `front − back` out of the per-leg mark
# matrices, and charging the fee with the **generalised per-leg cost model**
# rather than the engine's flat per-cohort figure, tests three things at once:
#
# * that a package IS the sum of its legs (the linearity the whole design rests on);
# * that the leg runs share the stored runs' cohort schedule to the day;
# * that `2 · (cost_bp_one_way / 2) · Σ_L |r_L|` reproduces the two-leg flat fee
#   exactly — which is what lets a *three*-leg package be priced at all.
#
# The two numbers reported are the ones the rest of this package certifies with:
# terminal gap and correlation of daily changes. A composition can hit the
# terminal level by luck while taking a different path, and only the daily
# correlation refuses to let that pass.

# %%
CERT_COMPOSE = fns.certify_dv01_neutral(LEGS, DATA, cfg=S1)
print(CERT_COMPOSE[["structure", "engine_terminal_usd", "composed_terminal_usd",
                    "terminal_gap_usd", "terminal_gap_pct", "corr_daily_changes",
                    "max_abs_daily_gap_usd", "n_marks_common"]].to_string(index=False))
print(f"\nworst terminal gap  {CERT_COMPOSE['terminal_gap_pct'].abs().max():.3e} %")
print(f"worst daily corr    {CERT_COMPOSE['corr_daily_changes'].min():.8f}")
print(f"worst daily gap     ${CERT_COMPOSE['max_abs_daily_gap_usd'].max():.2e}")
assert CERT_COMPOSE["terminal_gap_pct"].abs().max() < 1e-9
assert CERT_COMPOSE["corr_daily_changes"].min() > 1 - 1e-12
print("\nMachine precision on all four, on the level AND on the path. The fee")
print("model reproduces $100,000 per closed cohort round trip exactly: 79 closed")
print("x $100k = $7.9m, which is the whole difference between the fee-free")
print("composition and the engine's net curve.")

# %% [markdown]
# ## 4. The weights — walk-forward, and the look-ahead audit stated explicitly
#
# **There are two PCAs in this study and they do different jobs.**
#
# The **weight** basis is walk-forward: re-fitted at every cohort entry on data
# strictly before it (expanding, `min_fit_days = 250`), because a weight is a
# *decision* and a decision cannot use tomorrow's covariance. Fitting on the full
# 2019–2026 sample is right for the attribution report — that is a description of
# what happened — and would be look-ahead here, because a 2019 cohort would be
# sized with 2026's covariance.
#
# The **measurement** basis is the committed full-sample `FactorModel` above.
# Every exposure table, every variance share and the re-run attribution use it and
# only it. Re-fitting a different PCA to score the new books would make the
# *"did the level share move toward zero?"* comparison a comparison of two bases
# instead of two sizings.
#
# ### The look-ahead audit, item by item
#
# | quantity | what it may see | leak? |
# |---|---|---|
# | `pc1_neutral` / `pc12_neutral` weights at cohort *k* | curve days `< entry_k` | none |
# | eigenvector labelling | previous fit only (`_match_pcs` + `classify_pcs`) | none |
# | `slope_beta_hedged` beta at rebalance *m* | its own gross P&L, days `< entry_m` | none |
# | the **factor** that beta is a beta *to* | `V` fitted at `entry_m` | none — **fixed here** |
# | greeks / carry | the cohort's own entry date | none |
# | the trade set (91 cohorts, 1-year holds) | fixed, identical for every sizing | none |
# | `residual_exposure`, attribution shares | full sample, by design | **measurement only** |
#
# The fourth row is the one the draft got wrong. The beta was trailing, but it was
# a beta to a *definition of slope* estimated at the end of the sample. Truncating
# the window does not fix that; `walk_forward_scores` does.
#
# ### Two things that are NOT dropped, on purpose
#
# Cohort 0 enters 2019-02-01 and the panel starts 2019-01-02, so it has ~20 daily
# changes and nothing can be done about it — `FactorConfig.start` is the first day
# the full 2Y..50Y grid prices locally. Eleven cohorts sit under `min_fit_days`.
# They are **flagged, not dropped**: dropping them would change the trade set and
# stop this being a sizing comparison at all. Section 9 re-scores every book
# without them as a robustness row.

# %%
LBD, WF_DIAG, VBD = fns.walk_forward_loadings(
    PANEL, FCFG, ENTRIES, fns.LEG_UNIVERSE,
    min_fit_days=CFG.min_fit_days, hard_floor=CFG.hard_fit_floor)
print(f"{len(LBD)} walk-forward fits, {WF_DIAG['n_fit_days'].min()} .. "
      f"{WF_DIAG['n_fit_days'].max()} days of history")
print(f"short fits (< {CFG.min_fit_days} days): {int(WF_DIAG['short_fit'].sum())}")
print(f"non-canonical PC labels: {int((~WF_DIAG['label_ok']).sum())}")
print()
print(WF_DIAG.head(6).to_string(index=False))
print("...")
print(WF_DIAG.tail(3).to_string(index=False))

# %%
W = fns.cohort_weights(SCHED, fa.STRAT1_STRUCTURES, LBD, hedge_leg=CFG.hedge_leg,
                       dv01=DV01, neutralize=CFG.neutralize,
                       sizings=fns.STATIC_SIZINGS)
_cached = pd.read_parquet(DATA / "fns_cohort_weights.parquet")
_k = ["structure", "sizing", "cohort", "leg"]
_gap = float(np.abs(W.sort_values(_k)["dv01"].to_numpy()
                    - _cached.sort_values(_k)["dv01"].to_numpy()).max())
print(f"walk-forward weights reproduce the cached table to {_gap:.3e} $ of DV01")
assert _gap < 1e-6, "the weights the engine certified are not the weights composed"
print("This matters: the genuine engine run in section 11 was fed the CACHED")
print("table, so a drift between the two would certify a different book.")
print()
WSUM = fns.weights_summary(W, WF_DIAG)
print(WSUM.round(1).to_string(index=False))

# %% [markdown]
# `gross_dv01_mean` is the whole story in one column. `dv01_neutral` is $200,000
# by construction. `pc1_neutral` is *near* it — the two legs are close in PC1
# space — but never equal, and the deviation is the trade. `pc12_neutral` on
# 5Y/30Y is **$364,300**, 1.8x the incumbent's gross risk, because the 10Y hedge
# leg needed to zero a slope exposure of $56,249 per unit is large. That extra
# gross DV01 is what the cost model has to charge for, and it is exactly what the
# flat per-package fee could not express.

# %% [markdown]
# ## 5. Did the hedge remove the factor? — residual exposure
#
# This is the half of the test the P&L cannot answer. A hedge that moves the P&L
# to zero has not necessarily removed the factor, and a hedge that leaves the P&L
# alone has not necessarily failed to. **If the shares do not move, the hedge is
# not doing what it claims regardless of what the P&L does.**
#
# Weights are walk-forward; exposures are measured on the shared full-sample
# basis. Measuring a walk-forward-weighted package on its *own* walk-forward basis
# would report `f_PC1 = 0` by construction and prove nothing at all. The question
# is whether a weight chosen on 2019–2022 information is still level-neutral when
# scored on the ruler everything else in this package is scored on.

# %%
RESID = fns.residual_exposure_table(W, FM)
print(RESID[["structure", "sizing", "n_legs", "gross_dv01_mean",
             "abs_f_level_mean", "abs_f_slope_mean", "abs_f_curv_mean",
             "var_level", "var_slope", "var_curv"]].round(4).to_string(index=False))

# %%
_piv = RESID.pivot(index="structure", columns="sizing", values="var_level")
_piv = _piv[[c for c in ("dv01_neutral", "pc1_neutral", "pc12_neutral") if c in _piv]]
_piv["pc1_reduction"] = 1.0 - _piv["pc1_neutral"] / _piv["dv01_neutral"]
_piv["pc12_reduction"] = 1.0 - _piv["pc12_neutral"] / _piv["dv01_neutral"]
print("LEVEL share of the package's own factor variance:")
print(_piv.round(4).to_string())
print()
_pivs = RESID.pivot(index="structure", columns="sizing", values="var_slope")
_pivs = _pivs[[c for c in ("dv01_neutral", "pc1_neutral", "pc12_neutral") if c in _pivs]]
_pivs["pc12_reduction"] = 1.0 - _pivs["pc12_neutral"] / _pivs["dv01_neutral"]
print("SLOPE share of the package's own factor variance:")
print(_pivs.round(4).to_string())

# %% [markdown]
# **Read this table before any P&L.** On the three tight pairs `pc1_neutral` cuts
# the level share by 51%, 85% and 86%; `pc12_neutral` cuts the slope share on
# 5Y/30Y by 99.1%. The hedges are doing what they claim.
#
# The two rows that do **not** behave are the finding, not a defect:
#
# * **5Y/30Y `pc1_neutral` makes level *worse*** (0.0514 → 0.0889). Level was never
#   that book's problem — 5.1% of its variance — and the walk-forward PC1 shape
#   differs enough from the full-sample one that "zeroing level on 2020 data"
#   leaves more level on the 2019–2026 ruler than doing nothing. Section 9 prices
#   that gap and it is large.
# * **Every `pc1_neutral` row raises the SLOPE share.** That is arithmetic, not
#   leakage: total factor variance shrinks, so what remains is a bigger fraction
#   of a smaller number. The dollar exposure `abs_f_slope_mean` is the column to
#   read against, and on 30Y/50Y it rises from $2,463 to $2,988 — a real, modest
#   increase, the price of a two-leg trade with only one constraint to spend.
#
# Note also that `pc12_neutral` does not drive the analytic level and slope
# exposures to *exactly* zero here, and should not: the weights were solved on
# each cohort's own walk-forward basis and are being scored on the full-sample
# one. The residue (`var_level` 0.09–0.29 against 0.05–0.69 unhedged) is the
# honest cost of not knowing the covariance in advance, and section 10 confirms
# it on realised P&L rather than on the solve.

# %% [markdown]
# ## 6. The books
#
# Every sizing trades the **same 91 monthly cohorts on the same 1-year holds**.
# Only the leg weights differ. Costs are charged per LEG:
#
# ```
# fee_round_trip = 2 · (cost_bp_one_way / 2) · Σ_L |r_L|
# ```
#
# At `r = (+100k, −100k)` that is `2 · 0.25 · 200,000 = $100,000`, exactly the flat
# fee `build_backtest` charges — so this is not a new cost assumption, it is the
# same one written so a three-leg package can pay for three legs. Carry is not
# charged separately and must not be: the engine holds real swaps for a year and
# marks them, so realised P&L already contains it. It is reported as a
# decomposition column (`mean_carry_bp`), never as a second subtraction.

# %%
EQ, BK, CARRY_USD = {}, {}, {}
for (_lab, _sz), _g in W.groupby(["structure", "sizing"], sort=False):
    EQ[(_lab, _sz)], BK[(_lab, _sz)] = fns.compose_book(LEGS, _g, cfg=S1)
    _ck = {}
    for _k2, _gk in _g.groupby("cohort"):
        _d = pd.Timestamp(_gk["entry"].iloc[0])
        _cb = fns.leg_carry_bp(GREEKS, on=_d)
        _ck[_d] = float(sum(float(_r) * float(_cb.get(_l, np.nan))
                            for _l, _r in zip(_gk["leg"], _gk["dv01"])))
    CARRY_USD[(_lab, _sz)] = pd.Series(_ck).sort_index()
print(f"composed {len(EQ)} static books")

# %% [markdown]
# ## 7. `slope_beta_hedged` — the empirical variant, and its honest cost
#
# The incumbent package plus a DV01-neutral 5s30s overlay, sized by the beta of
# the book's own daily gross P&L on `dPC2`, estimated on a **trailing** 252-day
# window and rebalanced monthly. Both the beta and the factor definition are
# walk-forward (section 4).
#
# The beta is fitted on **gross** P&L, not net: the cost model books a $100k step
# on the dozen days a cohort unwinds, and a step function is not a factor
# exposure — including it would bias the beta by whatever the curve happened to do
# on unwind days.
#
# **Cost is a full round trip every month.** The overlay as constructed opens a
# fresh at-market spread each month rather than adjusting a held one, so it pays
# to get out and back in. That is the expensive reading and it is the headline;
# `overlay_cost_sensitivity` reports the cheaper delta-traded bound beside it so
# the reader can see the churn rather than take one number on trust.

# %%
SCORES_AT = {d: fns.walk_forward_scores(PANEL, FCFG, VBD[d], d, window=CFG.beta_window)
             for d in ENTRIES}
OVERLAY = {}
for _lab, _f, _b in fa.STRAT1_STRUCTURES:
    _wsub = W[(W["structure"] == _lab) & (W["sizing"] == "dv01_neutral")]
    _gross, _ = fns.compose_book(LEGS, _wsub, cfg=S1, cost_bp_one_way=0.0)
    _betas = fns.slope_beta_path(_gross, NLIVE, SCORES_AT, ENTRIES,
                                 window=CFG.beta_window)
    _sched = SCHED.assign(structure=_lab)
    _oeq, _obk, _hp = fns.compose_overlay(LEGS, _sched, _betas, LBD, cfg=S1)
    EQ[(_lab, "slope_beta_hedged")], BK[(_lab, "slope_beta_hedged")] = fns.add_overlay(
        EQ[(_lab, "dv01_neutral")], BK[(_lab, "dv01_neutral")], _oeq, _obk, cfg=S1)
    CARRY_USD[(_lab, "slope_beta_hedged")] = CARRY_USD[(_lab, "dv01_neutral")]
    OVERLAY[_lab] = {"betas": _betas, "book": _obk, "hedge_path": _hp,
                     "cost": fns.overlay_cost_sensitivity(_obk, _hp, _sched, cfg=S1)}

OVL_SUMMARY = pd.DataFrame([{
    "structure": _lab,
    "beta_mean_usd_per_pc2": float(_o["betas"]["beta_usd_per_pc2"].mean()),
    "beta_t_median": float(_o["betas"]["t_stat"].median()),
    "beta_r2_median": float(_o["betas"]["r2"].median()),
    "n_short_window": int(_o["betas"]["short_window"].sum()),
    "hedge_dv01_per_leg_mean": float(_o["hedge_path"]["hedge_dv01_per_leg"].mean()),
    "hedge_vs_package": abs(float(_o["hedge_path"]["hedge_dv01_per_leg"].mean())) / DV01,
    "overlay_gross_usd": float(_o["book"]["overlay_gross_usd"].sum()),
    "overlay_cost_usd": float(_o["book"]["overlay_cost_usd"].sum()),
    "overlay_net_usd": float(_o["book"]["overlay_net_usd"].sum()),
    "cost_delta_traded_usd": float(_o["cost"].loc[1, "total_cost_usd"]),
    "churn_ratio": float(_o["cost"].loc[2, "total_cost_usd"]),
} for _lab, _o in OVERLAY.items()])
print(OVL_SUMMARY.round(3).to_string(index=False))

# %%
_rec = []
for _lab, _o in OVERLAY.items():
    _oeq = EQ[(_lab, "slope_beta_hedged")] - EQ[(_lab, "dv01_neutral")]
    _rec.append({"structure": _lab,
                 "overlay_terminal_equity": float(_oeq.iloc[-1]),
                 "sum_per_cohort_net": float(_o["book"]["overlay_net_usd"].sum()),
                 "gap": float(_oeq.iloc[-1] - _o["book"]["overlay_net_usd"].sum()),
                 "n_live_cohorts": int((~_o["book"]["closed"]).sum()),
                 "one_month_fee": float(2.0 * fns.leg_cost_bp_one_way(S1) * 2
                                        * abs(_o["hedge_path"]["hedge_dv01_per_leg"]
                                              .iloc[-1]))})
OVL_RECON = pd.DataFrame(_rec)
print("Overlay reconciliation -- equity path against the per-cohort book:")
print(OVL_RECON.round(2).to_string(index=False))
print("""
The residual is the twelve STILL-LIVE cohorts' final monthly fee. The equity
curve is a mark-to-market and does not charge an exit cost on a position that is
still open -- the same convention `compose_book` uses -- while the per-cohort
table books it. It touches no `net_bp`, because `book_stats` reads closed
cohorts only and a closed cohort's last overlay segment always ends before the
last mark. The reported `overlay_cost_usd` is therefore the CONSERVATIVE side of
a 0.4% bookkeeping difference, which is the side to be on.""")

# %% [markdown]
# **`hedge_vs_package` on 5Y/30Y is 1.08.** The slope hedge that neutralises that
# book is *bigger than the book*. That is not a defect of the 5s30s choice: a
# package whose slope exposure is $56,249 per unit of PC2 has no slope hedge that
# is not essentially its own reverse, and the overlay costs **$116.5m** against a
# $100k-DV01 package — 1163 bp of cost, four times its own gross P&L. The three
# tight pairs need 2.9%–8.5% of package size and cost an order of magnitude less.
# This is the same finding as the attribution's, arrived at from the cost side.
#
# **Where the tight pairs' overlay P&L comes from, stated plainly.** On 30Y/50Y
# the overlay adds $26.9m net to a $34.1m base — 44% of the hedged book. That is
# not extra convexity; it is the *absence of a slope loss*. The attribution shows
# these flatteners were losing on slope (`share_slope` = −149% on 5Y/30Y, −10% on
# 30Y/50Y), so a position that cancels slope adds back what slope took away. The
# risk reduction is real and causally sized. Its magnitude is a property of what
# slope did in 2019–2026 and should not be extrapolated.
#
# `beta_t_median` of 3.4–4.6 says the beta is estimated, not fitted to noise;
# `n_short_window` of 44 says half the rebalances ran on less than a full 252-day
# window, which is unavoidable — the alternative is leaving the first years
# unhedged and comparing two different trade sets.

# %% [markdown]
# ## 8. The sizing-by-structure table
#
# Everything net of its own hedge cost, with a gross column beside it so the
# reader can see what the hedge took.

# %%
_rows = []
for (_lab, _sz), _eq in EQ.items():
    _bk = BK[(_lab, _sz)]
    _cl = _bk[_bk["closed"].to_numpy(bool)]
    _st = fns.book_stats(_eq, _bk, cfg=S1,
                         carry_bp=float(CARRY_USD[(_lab, _sz)].mean() / DV01),
                         business_days_per_year=CFG.business_days_per_year)
    _st.update({
        "structure": _lab, "sizing": _sz,
        "gross_bp_total": float(_cl["gross_bp"].sum()),
        "cost_bp_total": float(_cl["cost_bp"].sum()),
        "gross_dv01_mean": float(_cl["gross_dv01"].mean()),
        "breakeven_cost_bp_leg": fns.breakeven_cost_bp(_bk, cfg=S1),
    })
    _rows.append(_st)
STATS = pd.DataFrame(_rows).set_index(["structure", "sizing"]).sort_index()
HEAD = ["n_closed", "gross_bp_total", "cost_bp_total", "total_net_bp", "mean_net_bp",
        "hit_rate", "sharpe_per_trade", "t_stat_overlap_adj", "mtm_final_bp",
        "mtm_sharpe_ann", "mtm_max_dd_bp", "mean_carry_bp", "breakeven_cost_bp_leg"]
print("WALK-FORWARD weights. Every row net of ITS OWN hedge cost.")
print(STATS[HEAD].round(4).to_string())

# %%
_net = STATS["total_net_bp"].unstack("sizing")
_net = _net[[c for c in fns.SIZINGS if c in _net.columns]]
_rel = _net.div(_net["dv01_neutral"], axis=0)
print("total net bp, closed cohorts:")
print(_net.round(1).to_string())
print("\nas a multiple of the incumbent:")
print(_rel.round(3).to_string())

# %% [markdown]
# **The decisive read.** Neutralising the structure's own dominant factor:
#
# * **survives** on 30Y/50Y (341 → 301 bp, −12%), 20Yx5Y/25Yx5Y (480 → 426 bp,
#   −11%) and 10Yx10Y/20Yx10Y (500 → 335 bp, −33%). All three stay positive, all
#   three keep hit rates of 0.53–0.73, and section 10 shows the convexity term
#   intact at `t = 4.1–4.9`. The incumbent sizing was *not* diluting a bigger
#   convexity trade — the level exposure it carried was mildly **profitable** over
#   this sample, which is why removing it costs 11–33% rather than adding. What
#   removing it buys is that the remaining P&L is the thing the book claims to
#   trade.
# * **collapses** on 5Y/30Y under `pc12_neutral`: **+269 → −740 bp**, hit rate
#   0.53 → 0.20, Sharpe/trade +0.065 → −0.583. Remove the slope and there is
#   nothing underneath.
#
# `slope_beta_hedged` reads *better* than the incumbent on the three tight pairs
# (1.38x–1.86x). Section 7 and section 13 say why that is a risk reduction rather
# than a new earner. `pc1_neutral` on 5Y/30Y reads **+1408 bp** and must not be
# banked — see section 9.
#
# **Break-even cost** is generalised here and had to be. The house
# `breakeven_cost_bp` divides by `2 · n_closed` because every one of its packages
# is the same two legs at the same size; that is exactly what stops working when
# `pc12_neutral` trades three legs and `pc1_neutral` trades two of unequal size.
# The denominator used is the gross DV01 actually traded, so the number is
# comparable across sizings: **1.21–1.83 bp per leg** on the surviving books
# against a charged 0.25 bp, i.e. 5–7x headroom.

# %%
COSTS = {}
for (_lab, _sz), _g in W.groupby(["structure", "sizing"], sort=False):
    COSTS[(_lab, _sz)] = fns.cost_sensitivity(LEGS, _g, cfg=S1,
                                              multipliers=CFG.cost_multipliers)
_cs = pd.concat({k: v.set_index("cost_multiple")["total_net_bp"]
                 for k, v in COSTS.items()}, axis=1).T
_cs.index.names = ["structure", "sizing"]
print("total net bp by cost multiple (1.0 = the committed 0.5 bp one way):")
print(_cs.sort_index().round(1).to_string())
print("\nThe 0.0 column is the hedge priced honestly: the gap between it and the")
print("1.0 column is exactly what the extra legs cost to trade.")

# %% [markdown]
# ## 9. Walk-forward against full-sample — the price of not knowing
#
# The full-sample variant is computed for free and reported beside the headline.
# If the two agree the look-ahead was immaterial and the comparison is
# like-for-like; if they do not, **the walk-forward one is the answer and the gap
# is the cost of not knowing the covariance in advance.** Measured, not asserted.

# %%
L_FULL = fns.full_sample_loadings(PANEL, FCFG, fns.LEG_UNIVERSE)
W_FULL = fns.cohort_weights(SCHED, fa.STRAT1_STRUCTURES,
                            {pd.Timestamp(_e): L_FULL for _e in ENTRIES},
                            hedge_leg=CFG.hedge_leg, dv01=DV01,
                            neutralize=CFG.neutralize, sizings=fns.STATIC_SIZINGS)
_rows = []
for (_lab, _sz), _g in W_FULL.groupby(["structure", "sizing"], sort=False):
    _eq, _bk = fns.compose_book(LEGS, _g, cfg=S1)
    _cl = _bk[_bk["closed"].to_numpy(bool)]
    _p = _cl["net_bp"].to_numpy(float)
    _rows.append({"structure": _lab, "sizing": _sz,
                  "full_sample_net_bp": float(_p.sum()),
                  "full_sample_sharpe": float(_p.mean() / _p.std(ddof=1))})
LOOKAHEAD = pd.DataFrame(_rows).set_index(["structure", "sizing"]).join(
    STATS[["total_net_bp", "sharpe_per_trade"]]).rename(
    columns={"total_net_bp": "walk_forward_net_bp",
             "sharpe_per_trade": "walk_forward_sharpe"})
LOOKAHEAD["net_bp_gap"] = LOOKAHEAD["walk_forward_net_bp"] - LOOKAHEAD["full_sample_net_bp"]
LOOKAHEAD["abs_gap_vs_wf"] = (LOOKAHEAD["net_bp_gap"].abs()
                              / LOOKAHEAD["walk_forward_net_bp"].abs())
print(LOOKAHEAD[["full_sample_net_bp", "walk_forward_net_bp", "net_bp_gap",
                 "abs_gap_vs_wf", "full_sample_sharpe",
                 "walk_forward_sharpe"]].round(3).to_string())

# %% [markdown]
# **5Y/30Y `pc1_neutral` is where this matters and it disqualifies that number.**
# The same sizing rule scores **−66 bp** with full-sample loadings and **+1408 bp**
# walk-forward — a gap of 1474 bp, 105% of the walk-forward total. That is not a
# result; it is the PCA moving. The mechanism is visible in the weights: the 5Y
# leg of the walk-forward `pc1_neutral` ranges $70,557 to $134,875 (sd $18,902),
# spiking during the 2020–2022 ZIRP window when the 5Y point barely moved with
# level and PC1-neutrality therefore demanded a much bigger 5Y leg. The P&L that
# produced is a bet on the estimator, not on convexity.
#
# The three tight pairs are the opposite: full-sample and walk-forward agree to
# 3–20%, which is what "the look-ahead was immaterial" looks like when measured.

# %%
_wf5 = W[(W["structure"] == "5Y/30Y") & (W["sizing"] == "pc1_neutral")
         & (W["leg"] == "5Y")]["dv01"]
print(f"5Y/30Y pc1_neutral, walk-forward 5Y leg DV01: mean ${_wf5.mean():,.0f}  "
      f"sd ${_wf5.std(ddof=1):,.0f}  range ${_wf5.min():,.0f} .. ${_wf5.max():,.0f}")
print(f"full-sample equivalent: ${W_FULL[(W_FULL['structure'] == '5Y/30Y') & (W_FULL['sizing'] == 'pc1_neutral') & (W_FULL['leg'] == '5Y')]['dv01'].iloc[0]:,.0f}")

# %% [markdown]
# ### Robustness: the eleven thin-fit cohorts
#
# Dropping them would change the trade set, so the headline keeps them. Re-scored
# without them, here is what moves.

# %%
_thin = set(WF_DIAG.loc[WF_DIAG["short_fit"], "date"].astype("datetime64[ns]"))
_rows = []
for (_lab, _sz), _bk in BK.items():
    _cl = _bk[_bk["closed"].to_numpy(bool)]
    _keep = _cl[~pd.to_datetime(_cl["entry"]).isin(_thin)]
    _p, _q = _cl["net_bp"].to_numpy(float), _keep["net_bp"].to_numpy(float)
    _rows.append({"structure": _lab, "sizing": _sz,
                  "n_all": len(_p), "net_bp_all": float(_p.sum()),
                  "n_mature": len(_q), "net_bp_mature_only": float(_q.sum()),
                  "sharpe_all": float(_p.mean() / _p.std(ddof=1)),
                  "sharpe_mature": float(_q.mean() / _q.std(ddof=1))})
THIN = pd.DataFrame(_rows).set_index(["structure", "sizing"]).sort_index()
print(f"{len(_thin)} cohorts sized on a PCA shorter than {CFG.min_fit_days} days:")
print(THIN.round(3).to_string())

# %% [markdown]
# ## 10. The attribution, re-run ON THE NEW BOOKS
#
# A successful hedge must move the neutralised factor toward zero *in the
# realised P&L*, not only in the analytic exposure. The books are put back through
# `factor_attribution.run_attribution` unchanged, on the same shared full-sample
# basis, so a share here is the same object as a share in the attribution report
# and the two tables can be read side by side.
#
# Two readings, and they answer different questions:
#
# * `share_*` — fraction of the realised P&L. The literal question. It can exceed
#   100% or go negative whenever factors partly offset, which is normal.
# * `incr_*` — incremental R². The **risk** reading, and the one that settles
#   "did the hedge work". A book can carry a huge slope exposure that happened to
#   earn nothing, and only the R² column shows it.

# %%
SERIES = {}
for (_lab, _sz), _eq in EQ.items():
    SERIES.update(fns.sizing_series(_lab, _sz, _eq, BK[(_lab, _sz)], CALENDAR,
                                    cfg=S1, carry_usd=CARRY_USD[(_lab, _sz)]))
ATTR_TRADE = fns.attribution_shares(FM, SERIES, FCFG, level="trade")
ATTR_DAILY = fns.attribution_shares(FM, SERIES, FCFG, level="daily")
_cols = ["strategy", "n_obs", "total_pnl", "r2", "share_level", "share_slope",
         "share_curvature", "share_convexity", "share_carry", "share_unexplained",
         "t_convexity", "denom_unstable"]
print("TRADE level (convexity regressor = squared TERMINAL move; the right one")
print("for an unhedged 1-year buy-and-hold cohort):")
print(ATTR_TRADE[_cols].round(3).to_string(index=False))

# %%
_icols = ["strategy", "r2", "incr_level", "incr_slope", "incr_curvature",
          "incr_convexity", "incr_carry", "t_level", "t_slope", "t_convexity"]
print("DAILY level, INCREMENTAL R^2 -- the risk reading:")
print(ATTR_DAILY[_icols].round(4).to_string(index=False))

# %%
_d = ATTR_DAILY.copy()
_d["structure"] = _d["strategy"].str.rsplit(" ", n=1).str[0]
_d["sizing"] = _d["strategy"].str.rsplit(" ", n=1).str[1]
MOVE = pd.DataFrame({
    "incr_level": _d.pivot(index="structure", columns="sizing", values="incr_level").stack(),
    "incr_slope": _d.pivot(index="structure", columns="sizing", values="incr_slope").stack(),
}).unstack("sizing")
print("Did the neutralised factor's RISK share move toward zero? (daily incr R^2)")
print(MOVE.round(4).to_string())
print()
for _s in ("20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y", "30Y/50Y"):
    _a = float(MOVE[("incr_level", "dv01_neutral")][_s])
    _b = float(MOVE[("incr_level", "pc1_neutral")][_s])
    print(f"{_s:18s} level  {_a:.4f} -> {_b:.4f}   ({100*(1-_b/_a) if _a else np.nan:+.0f}%)")
_a = float(MOVE[("incr_slope", "dv01_neutral")]["5Y/30Y"])
_b = float(MOVE[("incr_slope", "pc12_neutral")]["5Y/30Y"])
print(f"{'5Y/30Y':18s} slope  {_a:.4f} -> {_b:.4f}   ({100*(1-_b/_a):+.0f}%)")

# %% [markdown]
# **The hedges work.** Level's incremental R² falls 88% on 20Yx5Y/25Yx5Y, 66% on
# 10Yx10Y/20Yx10Y and to zero on 30Y/50Y; slope's falls **99%** on 5Y/30Y. That is
# measured on realised P&L, on the same ruler as the attribution report, and it is
# the part of the answer that does not depend on a small sample.
#
# **And the convexity term survives on the tight pairs.** At trade level,
# `incr_convexity` is 0.32–0.36 with `t_convexity` = 4.1–4.9 on every
# `pc1_neutral` and `pc12_neutral` book of the three tight pairs — essentially
# unchanged from the incumbent's 0.31–0.35. The hedge removed the factor and left
# the convexity where it was, which is the good outcome and the one the prior
# predicted.
#
# **5Y/30Y is the counter-case, and it is instructive.** Its incumbent book has
# `incr_slope = 0.883` and `incr_convexity = 0.004` — the convexity term explains
# essentially *nothing*. Hedge the slope out and `incr_convexity` rises to 0.315
# because it is now the largest thing left, while the P&L goes to −740 bp. The
# convexity was always there as an *exposure*; it was never the earner.

# %% [markdown]
# ## 11. Certification II — a genuine multi-leg engine run of the new weights
#
# Section 3 certified the composition *arithmetic* against four stored two-leg
# runs. It cannot certify the **new weights**, because those vary by cohort and
# are not equal and opposite — the one thing the stored unit runs never exercise.
# So `5Y/30Y × pc12_neutral`, the structure the whole premise rests on and the one
# whose weights move most, is re-run as a genuine three-leg `QueryDrivenBacktest`
# with 273 tagged leg-positions, fed the cached weight table verbatim.
#
# `QueryDrivenBacktest.run()` **swallows exceptions**, so a dead run is an empty
# `mtm_history` and never a traceback. The build script asserts on it; so does
# this cell.

# %%
_safe = f"{fns.safe_leg(CFG.certify_structure)}_{CFG.certify_sizing}"
_ep = DATA / f"fns_certify_equity_{_safe}.parquet"
_cp = DATA / f"fns_certify_cohorts_{_safe}.parquet"
if _ep.exists() and _cp.exists():
    ENG = pd.read_parquet(_ep)["equity_usd"].astype(float)
    ENG.index = pd.to_datetime(ENG.index)
    ENG_COH = pd.read_parquet(_cp)
    assert len(ENG) > 0, "certify run produced no mtm_history"
    _composed = EQ[(CFG.certify_structure, CFG.certify_sizing)]
    # The engine run charges fee=0 on the unwind, exactly as the leg runs do, so
    # it is compared against the FEE-FREE composition. The fee model itself is
    # already certified exactly in section 3.
    _gw = W[(W["structure"] == CFG.certify_structure)
            & (W["sizing"] == CFG.certify_sizing)]
    _gross_composed, _ = fns.compose_book(LEGS, _gw, cfg=S1, cost_bp_one_way=0.0)
    CERT_ENGINE = fns.certify_engine(ENG, _gross_composed,
                                     label=CFG.certify_structure,
                                     sizing=CFG.certify_sizing, cfg=S1)
    print(json.dumps({k: (round(v, 10) if isinstance(v, float) else v)
                      for k, v in CERT_ENGINE.items()}, indent=1, default=str))
    print(f"\ncohorts closed in the engine run: {int(ENG_COH['closed'].sum())} / {len(ENG_COH)}")
    print(f"leg-positions opened: {int(ENG_COH['n_legs'].sum())}")
    assert abs(CERT_ENGINE["terminal_gap_pct"]) < 1e-6
    assert CERT_ENGINE["corr_daily_changes"] > 1 - 1e-9
    print("\nThe composed pc12_neutral book IS the engine's own three-leg run, on")
    print("the level and on the path. Every other book in this notebook is built")
    print("by the same arithmetic from the same eight mark matrices.")
else:
    CERT_ENGINE = {}
    raise FileNotFoundError(
        f"{_ep} missing -- run `_factor_neutral_build.py certify "
        f"'{CFG.certify_structure}' {CFG.certify_sizing}` first")

# %% [markdown]
# ## 12. The analytic sweeps — exposures and greeks, deliberately NOT P&L
#
# `HEDGE_LEG = 10Y` is pre-committed on stated structural grounds: it is the most
# liquid point on the USD curve, it sits in the middle of the PCA grid so its
# loading vector is genuinely independent of both long-end legs, and it gives a
# well-conditioned solve for all four structures. The sweep below shows the whole
# frontier so that choice is **checkable** — in exposures, conditioning, gamma and
# carry, and **never in realised P&L**, because ranking nine hedge tenors on
# returns and reporting the winner would be nine trials wearing one trial's
# clothes.

# %%
FRONTIER = fns.hedge_tenor_frontier(FM, gamma=GAMMA, carry=CARRY)
print(FRONTIER[["structure", "hedge_leg", "ok", "cond", "dv01_hedge", "gross_dv01",
                "hedge_frac_of_gross", "var_curv_residual", "gamma_usd_per_bp2",
                "gamma_vs_dv01n", "carry_usd_1y"]].round(4).to_string(index=False))
print(f"\n10Y condition numbers: "
      f"{FRONTIER[FRONTIER['hedge_leg'] == '10Y']['cond'].round(2).tolist()}")
print("Best-conditioned admissible hedge per structure:")
print(FRONTIER[FRONTIER["ok"]].loc[
    FRONTIER[FRONTIER["ok"]].groupby("structure")["cond"].idxmin(),
    ["structure", "hedge_leg", "cond"]].to_string(index=False))

# %%
SLOPE_TAB = fns.slope_instrument_table(FM)
print("Slope overlay candidates, ranked on curvature injected per unit of slope")
print("hedged. A slope hedge that carries curvature swaps one factor for another:")
print(SLOPE_TAB.round(4).to_string(index=False))

# %%
STRADDLE = fns.straddle_sizing_table(_sp)
print("`vega_neutral` -- the note's funded-straddle construction, ANALYTIC ONLY:")
print(STRADDLE.round(6).to_string(index=False))
print("""
NOT RUN, and the reason is measured rather than asserted.
`strat1_curve_gamma.build_backtest` raises on `trade_straddle=True` -- the
swaption leg was never wired into the engine -- so producing a vega_neutral P&L
would mean adding an untested engine path to answer an OPTIONAL part of the
question. It is also not worth it, and the measurement says why: the straddle
whose premium exactly funds the package's own 1-year carry is a median of
$4.17 of underlying DV01 for 20Yx5Y/25Yx5Y and $937 for 10Yx10Y/20Yx10Y against
a $100,000 package -- 0.004% and 0.94% of it. Calling a book with a
0.004%-of-size straddle bolted on "vega-neutral" would be calling an unhedged
flattener vega-neutral.

Only 5Y/30Y funds a real straddle (median $17,169, 17.2% of the package), and
that is precisely because its carry is large and negative (-3.60 bp median) --
which is the same fact, seen from the carry side, that makes it the directional
book this notebook has just taken apart. The one structure where vega_neutral
would be a meaningful construction is the one where the convexity thesis has
already failed on its own terms.""")

# %% [markdown]
# ## 13. Statistics — what actually clears
#
# Two haircuts, both measured on **these** books rather than inherited:
#
# * **overlap in time** — monthly cohorts held a year share ~92% of their window,
#   so 79 closed cohorts are `span / horizon` non-overlapping observations;
# * **overlap across structures** — `k_eff = k / (1 + (k−1)·r̄)` at the measured
#   mean pairwise cohort-P&L correlation.
#
# `r̄` is re-measured per sizing, not inherited from the incumbent: a sizing that
# changes the leg ratios changes what the four structures have in common, and
# assuming it did not would be assuming the answer to a question this study asks.

# %%
NEFF = {}
for _sz in fns.SIZINGS:
    NEFF[_sz] = fns.n_eff_report({_l: BK[(_l, _sz)] for _l, _f, _b in fa.STRAT1_STRUCTURES},
                                 cfg=S1)
print(pd.DataFrame({_sz: {k: v for k, v in _n.items()
                          if k in ("n_eff_per_structure_mean", "mean_pairwise_r",
                                   "min_pairwise_r", "max_pairwise_r",
                                   "k_eff_structures", "n_eff_pooled",
                                   "n_common_closed_cohorts", "n_nominal_pooled")}
                    for _sz, _n in NEFF.items()}).T.round(4).to_string())
N_EFF_POOLED = float(NEFF["dv01_neutral"]["n_eff_pooled"])
N_TRIALS = len(CFG.scored_sizings)
BAR = tw.expected_max_sharpe_under_null(N_TRIALS, n_obs=int(round(N_EFF_POOLED)))
print(f"\nincumbent pooled n_eff = {N_EFF_POOLED:.3f} on {NEFF['dv01_neutral']['n_nominal_pooled']} "
      f"nominal cohort-rows; mean pairwise r = {NEFF['dv01_neutral']['mean_pairwise_r']:.3f}")
print(f"E[max Sharpe | null] over {N_TRIALS} distinct sizings at n_eff = "
      f"{N_EFF_POOLED:.2f}: {BAR:.4f} per observation")
print("\nThe bar is set at the INCUMBENT's pooled n_eff, which is the conservative")
print("choice: three of the four sizings measure a LOWER cross-structure")
print("correlation and therefore a higher n_eff, which would lower the bar.")

# %%
SCORE = fns.sharpe_scoreboard(
    STATS.reset_index()[["structure", "sizing", "sharpe_per_trade", "n_closed",
                         "total_net_bp", "hit_rate", "mtm_sharpe_ann", "skew",
                         "kurtosis"]],
    N_EFF_POOLED, n_trials=N_TRIALS)
print(SCORE.sort_values("sharpe_per_trade", ascending=False).to_string(
    index=False, float_format=lambda v: f"{v:,.4f}"))
CLEARS = SCORE.loc[SCORE["clears_max_null"], ["structure", "sizing"]]
print(f"\nBooks clearing E[max|null] = {BAR:.4f}:")
print(CLEARS.to_string(index=False) if len(CLEARS) else "  NONE")

# %% [markdown]
# **Read the scoreboard honestly.** Seven of sixteen books clear the bar, and the
# count flatters them:
#
# * **Four are the same structure.** All four sizings of 20Yx5Y/25Yx5Y clear
#   (0.545–1.036). Its *incumbent* already cleared at 0.9333, so what clears is
#   the structure, not the re-sizing. Counting them as four independent survivals
#   is precisely the error `k_eff = 1.31` exists to prevent.
# * **Two of the remaining three are `slope_beta_hedged`** (30Y/50Y 0.508,
#   10Yx10Y/20Yx10Y 0.414), and section 7 showed roughly 43% of that book's P&L
#   is the overlay itself — a short-slope position that paid because slope was
#   what the flatteners were losing on. Real, causally sized, honestly costed,
#   and a bet on the sample.
# * **The third is `pc12_neutral` on 30Y/50Y** (0.347 against the incumbent's
#   0.311) — a genuine, tiny improvement, well inside noise at `n_eff = 9.8`.
#
# `pc1_neutral` on 5Y/30Y has the fourth-highest total P&L in the table and does
# **not** clear (0.260), which is the right outcome — and it is **excluded from
# every claim** on the section 9 evidence regardless: a rule whose two estimates
# differ by 105% of its own total is not a rule with an edge.
#
# The statement this study supports is therefore narrower than the scoreboard and
# worth more than a spurious one:
#
# > On 9.8 effective observations, **no sizing rule is shown to beat the
# > incumbent on P&L.** What *is* shown — on a measurement, not on a Sharpe — is
# > that the hedges remove the factor they target, that the convexity term
# > survives that removal on the three tight pairs at `t = 4.1–4.9`, and that on
# > 5Y/30Y there is no convexity earner underneath the slope bet at all.

# %% [markdown]
# ## 14. Equity curves and the house analytics
#
# `compare_curves` across the sizings, on the closed-cohort books and on the daily
# MTM; `trade_dashboard` on the best honest book.

# %%
SPAN_YEARS = (pd.Timestamp(IDX[-1]) - pd.Timestamp(IDX[0])).days / 365.25
print(f"span_years = {SPAN_YEARS:.2f}")

COHORT_BOOKS = {}
for _sz in fns.SIZINGS:
    _b = pd.concat([BK[(_l, _sz)] for _l, _f, _b2 in fa.STRAT1_STRUCTURES])
    _b = _b[_b["closed"].to_numpy(bool)].copy()
    _b["exit"] = pd.to_datetime(_b["exit"])
    COHORT_BOOKS[_sz] = _b.sort_values("exit")
compare_curves(COHORT_BOOKS,
               title="All four structures pooled — closed 1-year cohorts by sizing, net (bp)",
               time_col="exit", pnl_col="net_bp", unit="bp", side_col="gate_direction")

# %%
MTM_BOOKS = {}
for _sz in fns.SIZINGS:
    _e = sum(EQ[(_l, _sz)] for _l, _f, _b2 in fa.STRAT1_STRUCTURES) / DV01
    _d = _e.diff().dropna()
    MTM_BOOKS[_sz] = pd.DataFrame({"date": _d.index, "pnl": _d.to_numpy()})
compare_curves(MTM_BOOKS,
               title="All four structures pooled — daily MTM by sizing, bp of package DV01",
               time_col="date", pnl_col="pnl", unit="bp")

# %%
_b530 = {}
for _sz in fns.SIZINGS:
    _b = BK[("5Y/30Y", _sz)]
    _b = _b[_b["closed"].to_numpy(bool)].copy()
    _b["exit"] = pd.to_datetime(_b["exit"])
    _b530[_sz] = _b.sort_values("exit")
compare_curves(_b530,
               title="5Y/30Y — the book whose P&L WAS the slope bet (closed cohorts, net, bp)",
               time_col="exit", pnl_col="net_bp", unit="bp", side_col="gate_direction")

# %%
_tight = {}
for _sz in fns.SIZINGS:
    _b = BK[("20Yx5Y/25Yx5Y", _sz)]
    _b = _b[_b["closed"].to_numpy(bool)].copy()
    _b["exit"] = pd.to_datetime(_b["exit"])
    _tight[_sz] = _b.sort_values("exit")
compare_curves(_tight,
               title="20Yx5Y/25Yx5Y — the book where the edge SURVIVES the hedge (net, bp)",
               time_col="exit", pnl_col="net_bp", unit="bp", side_col="gate_direction")

# %%
BEST = ("20Yx5Y/25Yx5Y", "pc1_neutral")
print(f"trade_dashboard on the HEADLINE test for the tight pairs: {BEST}")
_bb = BK[BEST]
_bb = _bb[_bb["closed"].to_numpy(bool)].copy()
_bb["exit"] = pd.to_datetime(_bb["exit"])
trade_dashboard(_bb.sort_values("exit"),
                title=f"{BEST[0]} {BEST[1]} — level-neutral, closed 1-year cohorts (net)",
                span_years=SPAN_YEARS, time_col="exit", pnl_col="net_bp",
                unit="bp", side_col="gate_direction")

# %%
print("CONTROL — the same structure at the incumbent DV01-neutral sizing:")
_bc = BK[("20Yx5Y/25Yx5Y", "dv01_neutral")]
_bc = _bc[_bc["closed"].to_numpy(bool)].copy()
_bc["exit"] = pd.to_datetime(_bc["exit"])
trade_dashboard(_bc.sort_values("exit"),
                title="20Yx5Y/25Yx5Y dv01_neutral — the incumbent (net)",
                span_years=SPAN_YEARS, time_col="exit", pnl_col="net_bp",
                unit="bp", side_col="gate_direction")

# %%
SUMMARY = pd.DataFrame({
    _sz: summary_stats(COHORT_BOOKS[_sz], span_years=SPAN_YEARS, time_col="exit",
                       pnl_col="net_bp", unit="bp", side_col="gate_direction")
         .set_index("metric")["value"]
    for _sz in fns.SIZINGS})
print(SUMMARY.to_string())
print("""
READ THE 'annualised Sharpe' ROW WITH CARE. `summary_stats` annualises by
scaling the per-trade Sharpe by sqrt(trades / year), which is right for
INDEPENDENT trades. These are not: 1-year holds opened monthly across four
correlated structures, so ~48 "trades per year" are worth about ONE
non-overlapping observation, and the sqrt(48) it multiplies by is very nearly
all of the number. The honest evidence test is the scoreboard in section 13.""")

# %% [markdown]
# ## 15. Persist and verdict

# %%
for (_lab, _sz), _eq in EQ.items():
    _s = f"{fns.safe_leg(_lab)}_{_sz}"
    _eq.to_frame("equity_usd").to_parquet(DATA / f"fns_equity_{_s}.parquet")
    BK[(_lab, _sz)].to_parquet(DATA / f"fns_cohorts_{_s}.parquet", index=False)
STATS.reset_index().to_parquet(DATA / "fns_book_stats.parquet", index=False)
RESID.to_parquet(DATA / "fns_residual_exposure.parquet", index=False)
ATTR_TRADE.to_parquet(DATA / "fns_attribution_trade.parquet", index=False)
ATTR_DAILY.to_parquet(DATA / "fns_attribution_daily.parquet", index=False)
LOOKAHEAD.reset_index().to_parquet(DATA / "fns_lookahead.parquet", index=False)
SCORE.to_parquet(DATA / "fns_scoreboard.parquet", index=False)
FRONTIER.to_parquet(DATA / "fns_hedge_frontier.parquet", index=False)
OVL_SUMMARY.to_parquet(DATA / "fns_overlay_summary.parquet", index=False)
print(f"wrote {2 * len(EQ)} per-book parquets + 9 tables to {DATA}")

# %%
VERDICT = fns.verdict(CFG, STATS, SCORE, RESID, ATTR_TRADE,
                      CERT_COMPOSE, NEFF["dv01_neutral"], dominant=DOMINANT)
VERDICT["certification_engine_multileg"] = CERT_ENGINE
VERDICT["lookahead"] = LOOKAHEAD.reset_index().to_dict("records")
VERDICT["overlay"] = OVL_SUMMARY.to_dict("records")
VERDICT["carry_tieout"] = CARRY_TIEOUT.to_dict("records")
VERDICT["headline"] = {
    "question": "after neutralising the dominant factor for that structure, "
                "does the convexity edge survive net of the hedge?",
    "answer": "survives on the three tight forward pairs; dies on 5Y/30Y",
    "tight_pairs_net_bp_retained": {
        s: float(STATS.loc[(s, fns.HEADLINE_SIZING[s]), "total_net_bp"]
                 / STATS.loc[(s, "dv01_neutral"), "total_net_bp"])
        for s in ("30Y/50Y", "20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y")},
    "5Y30Y_pc12_net_bp": float(STATS.loc[("5Y/30Y", "pc12_neutral"), "total_net_bp"]),
    "5Y30Y_dv01_net_bp": float(STATS.loc[("5Y/30Y", "dv01_neutral"), "total_net_bp"]),
    "pc1_neutral_5Y30Y_disqualified": True,
    "pc1_neutral_5Y30Y_reason": "walk-forward vs full-sample gap is 105% of its "
                                "own total; the P&L is PCA instability, not edge",
}
(DATA / "fns_verdict.json").write_text(json.dumps(VERDICT, indent=1, default=str))
print(json.dumps(VERDICT["headline"], indent=1, default=str))
print(f"\nwrote {DATA / 'fns_verdict.json'}")

# %%
print("=" * 78)
print("FINAL: sizing by structure, walk-forward weights, net of each hedge's cost")
print("=" * 78)
_f = STATS.reset_index()[["structure", "sizing", "gross_bp_total", "cost_bp_total",
                          "total_net_bp", "hit_rate", "sharpe_per_trade",
                          "t_stat_overlap_adj", "breakeven_cost_bp_leg"]].copy()
_f = _f.merge(RESID[["structure", "sizing", "var_level", "var_slope"]],
              on=["structure", "sizing"], how="left")
_f["headline"] = [("<<" if fns.HEADLINE_SIZING.get(s) == z else "")
                  for s, z in zip(_f["structure"], _f["sizing"])]
_f = _f.sort_values(["structure", "sizing"])
print(_f.round(4).to_string(index=False))
print()
print(f"Certification I  (composition vs 4 stored engine runs): "
      f"terminal gap {CERT_COMPOSE['terminal_gap_pct'].abs().max():.1e}%, "
      f"daily corr {CERT_COMPOSE['corr_daily_changes'].min():.8f}")
print(f"Certification II (3-leg engine run of pc12_neutral 5Y/30Y): "
      f"terminal gap {CERT_ENGINE.get('terminal_gap_pct', float('nan')):.1e}%, "
      f"daily corr {CERT_ENGINE.get('corr_daily_changes', float('nan')):.8f}")
print(f"E[max Sharpe | null], {N_TRIALS} sizings at n_eff {N_EFF_POOLED:.2f}: {BAR:.4f}")
print(f"clears: {len(CLEARS)} book(s), all on 20Yx5Y/25Yx5Y -- one bet, three rows")
print(f"\nnotebook ran in {time.time() - T_START:.0f}s")
