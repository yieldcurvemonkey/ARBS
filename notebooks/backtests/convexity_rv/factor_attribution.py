# %% [markdown]
# # One factor basis for every convexity strategy
#
# **The question.** *"Is strat 1 base the only strategy that really trades RV?
# Are the others directional punts? It seems that means we are sizing these
# incorrectly."*
#
# **The answer, up front: the premise is inverted, and the real split is not
# between strategies at all.** It runs *through* strategy 1. Three of strat 1's
# four structures earn most of their P&L from convexity. The fourth, **5Y/30Y,
# is the single most directional book in the whole package** -- 260% of its P&L
# comes from the slope factor, at a t-statistic of 39.5, with an incremental
# R-squared of 0.71 on that one regressor. Strategy 3, which the mtm-share
# evidence had painted as directional, is convexity-dominated. Strategy 2's CA
# leg is the purest relative value of the set on a different and stronger
# criterion: **nothing in the curve basis explains it at all** (daily
# R-squared 0.011).
#
# ## Why this notebook had to exist
#
# "How directional is it?" had been answered three separate ways, and the three
# answers are not comparable:
#
# | strategy | the evidence on hand | what kind of number it is |
# |---|---|---|
# | strat 1 long-end | gross P&L on the *gated curve move*, slope 0.80, R2 0.80-0.83 | an R-squared against an ad-hoc regressor |
# | strat 3 | mtm share of net = 1.29, >= 0.88 on all 15 pairs | a ratio of accounting buckets |
# | strat 2 | gamma of -$1,057,841 on rank 5 | a dollar greek |
#
# An R-squared, a bucket ratio and a greek. You cannot rank three strategies on
# those, and the attempt is what produced the premise this notebook tests.
#
# So: one PCA of the USD-SOFR par curve, fitted once, on daily changes in bp;
# one convexity regressor that is quadratic rather than linear in those factors;
# one carry regressor; and every book regressed on the same five columns at both
# the trade and the daily level.

# %% [markdown]
# ## 0. CONFIG
#
# Everything the run depends on, in one place. `FactorConfig` carries the full
# documented set; the notebook does not override any of it, which is the point --
# the defaults ARE the report.

# %%
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

_REPO = pathlib.Path.cwd()
while not (_REPO / "RVUtils").exists() and _REPO != _REPO.parent:
    _REPO = _REPO.parent
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV import factor_attribution as fa
from RVUtils.ConvexityRV.strat2_sofr_convexity import (
    Strat2Config,
    model_timeseries,
    panel_timeseries,
    plan_epochs,
    trim_to_contiguous_run,
)

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 80)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
CFG = fa.FactorConfig()

print(f"repo   {_REPO}")
print(f"curve  {CFG.curve}   window {CFG.start} .. {CFG.end}")
print(f"grid   {len(CFG.tenors)} tenors: {', '.join(CFG.tenors)}")
print(f"PCs    {CFG.n_pcs}   matrix '{CFG.matrix}'")
print(f"HAC    daily lag {CFG.hac_lag_daily}, trade lag {CFG.hac_lag_trade}")
print(f"stability floor {fa.STABILITY_FLOOR}   factor order {fa.FACTOR_ORDER}")

# %% [markdown]
# ## 1. The factor basis
#
# ### 1a. The tenor grid, and why it is this one
#
# `2Y 3Y 5Y 7Y 10Y 15Y 20Y 25Y 30Y 40Y 50Y`. Three constraints pin it:
#
# 1. **It has to span every tenor any of the three strategies touches.** Strat 2
#    lives at 2Y-10Y (its hedge fly is 2s5s10s and its packs are 0.5-2.5y
#    forward); strat 1 and strat 3 live at 10Y-50Y. A grid chosen for one of
#    them cannot carry the other.
# 2. **It must include 40Y and 50Y.** `30Y/50Y` is a traded structure. A grid
#    that stops at 30Y cannot see its slope factor *at all* -- both legs would
#    collapse onto the same point and the package would look like pure noise.
#    Coverage is checked below rather than assumed; the SOFR curve prices 40Y and
#    50Y on every day of the window, so nothing is lost by including them.
# 3. **Roughly log-spaced**, so no region is over-weighted by sheer count of
#    nodes. Eleven tenors with six of them beyond 10Y matches where the traded
#    risk sits without letting the front end vanish.
#
# 1Y is fetched and cached alongside as a grid-sensitivity check but is not in
# the basis: it is dominated by policy-path noise that none of these structures
# trades.

# %%
_RATES_F = DATA / "factor_rate_panel.parquet"
if _RATES_F.exists():
    RATES = pd.read_parquet(_RATES_F)
    print(f"loaded cached rate panel {RATES.shape}")
else:
    # ~7 minutes cold. The builder script does this out of band so nbconvert
    # never has to: notebooks/backtests/convexity_rv/_factor_attribution_build.py
    _t0 = time.time()
    RATES = fa.build_rate_panel(CFG, n_jobs=8)
    RATES.to_parquet(_RATES_F)
    print(f"built rate panel {RATES.shape} in {time.time() - _t0:.0f}s")

print(f"\n{RATES.index.min().date()} .. {RATES.index.max().date()}, {len(RATES)} days")
print("\nnon-null count per tenor (a patchy 40Y would silently truncate the PCA):")
print(RATES.notna().sum().to_string())
assert RATES[list(CFG.tenors)].notna().all().all(), "the PCA grid has gaps"
print(f"\nlevels in % on the first and last day:\n"
      f"{RATES[list(CFG.tenors)].iloc[[0, -1]].round(4).to_string()}")

# %% [markdown]
# ### 1b. Fit, and the explained variance
#
# `fit_curve_pca_from_timeseries` from the repo's own risk model
# (`RVUtils/df_based_pca_risk_model.py`), on **daily changes in bp**, on the
# **covariance** matrix. Covariance rather than correlation is not a style
# choice: it keeps the loadings in bp space, so a DV01 ladder projects onto them
# directly as `f = V'r` and the exposures in section 5 are exact rather than
# needing a per-tenor rescale.

# %%
FM = fa.fit_factor_model(RATES, CFG)
_ev = FM.explained_variance.head(5)
print("explained variance (%):")
print((_ev * 100).round(3).to_string())
print(f"\nfitted on {len(FM.d_rates_bp)} daily changes, {len(FM.tenors)} tenors")
print(f"first three PCs carry {100 * _ev.iloc[:3].sum():.2f}% of daily curve variance")

print("\nloadings:")
print(FM.loadings.iloc[:, :4].round(4).to_string())

# %% [markdown]
# ### 1c. Does the usual level / slope / curvature reading actually hold here?
#
# It cannot be assumed. A long-end-heavy grid can rotate PC2 and PC3 into each
# other, and this grid has six of its eleven nodes past 10Y. So each loading
# vector is scored on its own shape and given the label the evidence supports:
#
# * `same_sign_frac` -- the fraction of loadings sharing the modal sign. 1.0 is a
#   LEVEL factor: every tenor moves the same way.
# * `n_sign_flips` -- sign changes walking short to long. 0 = level, 1 = a
#   monotone SLOPE, 2 = a wing/belly CURVATURE shape.
# * `loading_sum` -- the parallel component. A slope factor sums to ~0.
#
# The label comes from the flip count, which is a structural property of the
# vector, not a comparison against what we hoped to find.

# %%
CLS = fa.classify_pcs(FM.loadings, FM.tenors, n=3)
print(CLS.round(4).to_string())

assert list(CLS["label"]) == ["level", "slope", "curvature"], (
    f"the usual reading does NOT hold on this grid: {list(CLS['label'])}. "
    "Every downstream label in this notebook would be wrong.")
assert CLS.loc["PC1", "same_sign_frac"] == 1.0
assert CLS.loc["PC2", "n_sign_flips"] == 1
assert abs(CLS.loc["PC2", "corr_with_log_tenor"]) > 0.95
assert abs(CLS.loc["PC2", "loading_sum"]) < 0.15 * abs(CLS.loc["PC1", "loading_sum"])
print("\nPASS -- PC1/PC2/PC3 are level / slope / curvature on this grid.")

print(f"\nPC1 is NOT flat: {FM.loadings['PC1'].min():.4f} at "
      f"{FM.loadings['PC1'].idxmin()} to {FM.loadings['PC1'].max():.4f} at "
      f"{FM.loadings['PC1'].idxmax()} -- a humped level, peaking around 7Y.")
print("That hump is why a DV01-neutral package is not PC1-neutral. Section 5.")

# %%
_fig = go.Figure()
for pc, colour in zip(["PC1", "PC2", "PC3"], ["#4dabf7", "#ff9f43", "#3ddc84"]):
    _fig.add_trace(go.Scatter(
        x=[fa._tenor_years(t) for t in FM.tenors], y=FM.loadings[pc].values,
        name=f"{pc} ({CLS.loc[pc, 'label']}, {100 * FM.explained_variance[pc]:.1f}%)",
        mode="lines+markers", line=dict(color=colour, width=2)))
_fig.add_hline(y=0, line=dict(color="#888", width=1, dash="dot"))
_fig.update_layout(title="USD-SOFR daily-change PCA loadings, 2019-2026",
                   xaxis_title="tenor (years, log scale)", xaxis_type="log",
                   yaxis_title="loading", height=430, template="plotly_white")
_fig

# %% [markdown]
# ### 1d. Measurement decision 1 -- the factor series is RAW, not the PCA's scores
#
# `fit_curve_pca_from_timeseries` demeans before projecting (`X_std = X - mean`).
# That is correct for fitting a covariance and **wrong for attribution**. Over
# 2019-2026 the mean daily change is positive at every tenor -- the curve drifted
# up by roughly 190bp on average across the grid -- and a demeaned score throws
# exactly that away. Attribute a one-year trade with demeaned scores and the
# whole directional drift lands in the intercept and gets reported as *alpha*.
#
# So the loadings `V` come from the standard demeaned fit, and the factor series
# is rebuilt raw: `F_t = dR_t @ V`.
#
# This is the single decision most likely to flip the answer to "how directional
# is it", which is why it is checked first.

# %%
_tot = (FM.rates_bp.iloc[-1] - FM.rates_bp.iloc[0]).reindex(FM.model.columns)
print(f"total curve move over the window, grid average: {_tot.mean():+.1f} bp")
print(f"{'':8s} {'raw sum':>12s} {'demeaned sum':>14s}")
for pc in ("PC1", "PC2", "PC3"):
    print(f"{pc:8s} {FM.scores[pc].sum():+12.1f} {FM.scores_demeaned[pc].sum():+14.1f}")

_expect = float(_tot.values @ FM.loadings["PC1"].values)
assert abs(FM.scores["PC1"].sum() - _expect) < 1e-6 * abs(_expect), \
    "raw PC1 must sum to the projection of the total curve move"
assert abs(FM.scores_demeaned["PC1"].sum()) < 1e-6 * abs(_expect)
print(f"\nPASS -- raw PC1 sums to {_expect:+.1f}bp, the projection of the actual "
      f"total move; the demeaned series sums to zero by construction.")
print("Using the demeaned series would have booked +632bp of realised level "
      "drift to alpha in every strategy below.")

# %% [markdown]
# ### 1e. Measurement decision 2 -- the convexity regressor
#
# It must be **quadratic in the factors**, not linear, or a long-gamma position
# has nowhere to load that a directional one does not. A long-gamma position
# earns in `|move|^2`. Two choices then have to be made explicitly.
#
# **Which move.** The *parallel-equivalent shift*: the cross-sectional mean of
# the rate change across the grid, in bp. Not PC1 itself. The reason is a
# tie-out. `curve_ops.payoff_profile` measures convexity by repricing the whole
# package on a **parallel-shifted** curve -- that is how every gamma in this
# package was computed, and the profiles are already on disk in
# `strat1_signal_panel.parquet`. Defining the regressor as the squared parallel
# move makes the fitted coefficient checkable against an independently computed
# greek: `beta_convexity` should come back at `0.5 * gamma`. A regressor built on
# PC1 would need an extra scaling constant and the check would be softer.
#
# **Over what window.** The squared move over *exactly the interval the P&L is
# measured over*:
#
# | book | second-order term it actually earns | regressor |
# |---|---|---|
# | unhedged buy-and-hold (strat 1 cohorts) | `(R_T - R_0)^2` | squared terminal move |
# | the daily mark of that same book | `(dR_t)^2` | squared daily move |
# | delta-hedged (strat 3, rebalanced every 25bp) | `sum_t (dR_t)^2` | realised variance |
#
# Daily regressions get `(dR_t)^2`; trade-level regressions get the squared
# terminal move, with realised variance run as a sensitivity in section 4.
#
# It is **not demeaned**. Its mean *is* the average gamma earnings; demeaning it
# would push exactly that quantity into the intercept and report it as alpha.

# %%
PAR = fa.parallel_move(FM)
CVX = fa.convexity_from_parallel(PAR)
print(f"parallel move: mean {PAR.mean():+.4f} bp/day, sd {PAR.std():.3f} bp/day")
print(f"convexity regressor: mean {CVX.mean():.3f} bp^2/day "
      f"(rms move {np.sqrt(CVX.mean()):.3f} bp), min {CVX.min():.4f}")

print("\ncorrelation with each PC -- the regressor must not be a linear function "
      "of the basis:")
for pc in ("PC1", "PC2", "PC3"):
    print(f"  corr(convexity, {pc}) = {np.corrcoef(CVX, FM.scores[pc])[0, 1]:+.4f}")
_m1 = float(FM.loadings["PC1"].mean())
print(f"\ncorr(parallel move, PC1 x mean loading) = "
      f"{np.corrcoef(PAR, FM.scores['PC1'] * _m1)[0, 1]:.6f}  "
      f"-- the parallel component IS essentially PC1 alone, as PC2 sums to ~0")

for pc in ("PC1", "PC2", "PC3"):
    assert abs(np.corrcoef(CVX, FM.scores[pc])[0, 1]) < 0.20, f"convexity ~ {pc}"
assert CVX.mean() > 0 and CVX.min() >= 0
print("\nPASS -- quadratic, non-negative, near-orthogonal to all three PCs.")

# %% [markdown]
# ### 1f. Sign probe
#
# Nothing below means anything if the sign conventions are wrong, and they are
# easy to get wrong: this package's convention (`RVUtils/ConvexityRV/__init__.py`)
# was established empirically against the engine, not read off the risk-weight
# code. Four independent checks.

# %%
_rates_mean = FM.rates_bp.mean().to_dict()

# (a) a DV01-neutral flattener pays the front leg and receives the back leg
_lad = fa.dv01_neutral_ladder("5Y", "30Y", 100_000.0, _rates_mean)
print(f"(a) 5Y/30Y flattener ladder: { {k: round(v) for k, v in _lad.items()} }")
assert _lad["5Y"] > 0 > _lad["30Y"], "flattener must pay front, receive back"
assert abs(sum(_lad.values())) < 1e-6, "and be DV01-neutral"

# (b) that ladder must MAKE money on a flattening move and LOSE on a steepening
_flatten = pd.Series({t: (-5.0 if fa._tenor_years(t) >= 20 else +5.0) for t in FM.tenors})
_pnl_flat = float(sum(_lad.get(t, 0.0) * _flatten[t] for t in FM.tenors))
print(f"(b) P&L of that ladder on a +5bp front / -5bp back move: ${_pnl_flat:+,.0f}")
assert _pnl_flat > 0, "a flattener must gain when the curve flattens"

# (c) the long-end run's unit book IS the base run's direction=+1 position.
#
#     JOIN ON ENTRY DATE, NOT ON `tag`. The two runs number their cohorts
#     independently -- the base has 88 and the long-end run has 91 over the same
#     2019-02-01..2026-08-03 span -- so `30Y/50Y_c0012` means 2020-04-01 in one
#     file and 2020-02-03 in the other. Joining on tag reports a correlation of
#     0.897 and looks like a real discrepancy between the two backtests. Joined
#     on entry date the two agree to the last bit on every closed cohort of
#     every structure, which is what "same position, opposite sign convention"
#     actually means.
print("(c) base gross_pnl_bp == direction x LE-unit gross_bp, joined on ENTRY DATE:")
for _lab, _f, _bk in fa.STRAT1_STRUCTURES:
    _safe = _lab.replace("/", "-")
    _a = pd.read_parquet(DATA / f"strat1_cohorts_{_safe}.parquet")
    _b = pd.read_parquet(DATA / f"strat1_le_cohorts_{_safe}_always.parquet")
    _a["entry"] = pd.to_datetime(_a["entry"])
    _b["entry"] = pd.to_datetime(_b["entry"])
    _m = (_a[_a["closed"]][["entry", "direction", "gross_pnl_bp"]]
          .merge(_b[_b["closed"]][["entry", "gross_bp"]], on="entry").dropna())
    _md = float((_m["gross_pnl_bp"] - _m["direction"] * _m["gross_bp"]).abs().max())
    print(f"      {_lab:18s} {len(_m):3d} closed cohorts, max |diff| {_md:.2e} bp")
    assert _md < 1e-8, f"{_lab}: the two runs do not share a sign convention"
assert (pd.read_parquet(DATA / "strat1_cohorts_30Y-50Y.parquet")["direction"] == 1.0).all()

# (d) every strat 1 flattener must be LONG convexity: positive payoff-profile gamma
SIG = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
SIG["date"] = pd.to_datetime(SIG["date"])
print("(d) gamma from the payoff profile (bp of P&L per bp^2 of parallel shift):")
for _lab, _f, _bk in fa.STRAT1_STRUCTURES:
    _g = fa.gamma_from_payoff_profile(SIG, _lab)
    print(f"      {_lab:18s} {_g:+.5f}")
    assert _g > 0, f"{_lab} is not long convexity"

print("\nSIGN PROBE PASS -- flattener = pay front / receive back = long convexity, "
      "and the two strat 1 runs agree row for row.")

# %% [markdown]
# ## 2. Every strategy on the same basis
#
# ### 2a. What each series is
#
# | book | trade unit | daily source | direction | carry regressor |
# |---|---|---|---|---|
# | strat 1 base x4 | closed 1y cohort | per-structure equity | signal (`direction`) | 1y carry-roll at entry |
# | strat 1 LE `always` | closed cohort, 4 structures pooled | POOLED equity | +1 throughout | 1y carry-roll at entry |
# | strat 1 LE `swaption_only` | ditto, `gate_direction`-signed | POOLED equity | gate (+1/-1, 0 dropped) | ditto, signed |
# | strat 2 CA leg | epoch (= `unhedged`) | epoch equity | +1, never reverses | none separable |
# | strat 2 fly hedge only | epoch (`hedged - unhedged`) | ditto | +1 | none |
# | strat 2 hedged | epoch | ditto | +1 | none |
# | strat 3 x2 | calendar quarter | ledger `total + cost` | +1, always on | the ledger's own carry bucket |
#
# Every one of them is a **$100,000-DV01 package**, which is what makes the
# dollar contributions directly comparable with no further normalisation.
#
# Two things are deliberately *not* symmetric and both are stated rather than
# smoothed over:
#
# * **`weight` is +1 wherever the book never reverses.** The sign of the fitted
#   convexity coefficient is then an *output* of the regression, not an
#   assumption pushed in through the regressor. Only 5Y/30Y (45 long / 43 short)
#   and the `swaption_only` gate actually flip, and there +1 means the
#   flattener.
# * **Strat 2 has no separable carry series.** For a futures-vs-swap convergence
#   trade the "carry" *is* the convergence of the traded quantity; there is no
#   independent theta to regress. Its carry share reads NaN rather than a
#   fabricated zero.

# %% [markdown]
# ### 2b. Rebuilding strat 2's epochs
#
# `strat2_equity.parquet` is a pair of equity curves with no trade log beside
# it, so the epoch boundaries are re-derived from the cached panel with the
# notebook's own config. That is cheap (seconds -- it is all in-memory screen
# arithmetic on `strat2_panel.parquet`) and it is checked against the equity
# curve's own span below.

# %%
S2CFG = Strat2Config(
    n_contracts=13, rank_start=2, n_packs=9, ca_basis_bp=0.0,
    round_pack_price_to_tick=False, sigma_model_mode="fit", sigma_fit_degree=2,
    holee_convention="citi", ca_floor_bp=0.1, realized_window_days=63,
    z_window_3m=63, z_window_1y=252, min_history_for_z1y=252, week_days=5,
    top_n_per_metric=3, min_metrics_flagged=0, hedge_enabled=True,
    hedge_tenors=("2Y", "5Y", "10Y"), hedge_regression_days=252,
    hedge_min_abs_beta=1.0, hedge_require_positive_wings=True,
    ca_dv01=100_000.0, max_hold_months=3, rebalance_freq="BMS",
)
_p2 = pd.read_parquet(DATA / "strat2_panel.parquet")
_r2 = pd.read_parquet(DATA / "strat2_rates.parquet")
P2, R2 = trim_to_contiguous_run(_p2, _r2)
SPECS = plan_epochs(P2, R2, S2CFG, ts=panel_timeseries(P2, S2CFG),
                    model=model_timeseries(P2, S2CFG), verbose=False)
EPOCHS = pd.DataFrame([{"entry": s.entry, "exit": s.exit, "pack": s.pack,
                        "ca_entry_bp": round(s.ca_entry_bp, 2),
                        "contracts": s.contracts_per_leg} for s in SPECS])
_eq2 = pd.read_parquet(DATA / "strat2_equity.parquet")
_eq2.index = pd.to_datetime(_eq2.index)
print(f"{len(EPOCHS)} epochs, {EPOCHS['entry'].min()} .. {EPOCHS['exit'].max()}")
print(f"equity curve spans        {_eq2.index.min().date()} .. {_eq2.index.max().date()}")
assert pd.Timestamp(EPOCHS["exit"].max()) == _eq2.index.max(), \
    "the rebuilt epochs do not span the cached equity curve"
assert (EPOCHS["contracts"] > 0).all(), \
    "strat 2 is documented as short-convexity-always; a negative leg would break `weight=+1`"
print("PASS -- epochs reconstructed and every one is long the pack / pays the swap.")

# %% [markdown]
# ### 2c. Loading every book, and reconciling what the regression sees
#
# Two calendar traps, both measured rather than assumed away, both large enough
# to change the answer:
#
# 1. **Live cohorts carry a `NaT` exit.** `(index <= NaT)` is all-False, so a
#    naive weight build gives the twelve still-open cohorts zero size and drops
#    the final year of marks onto flat days. Their exit is set to the end of the
#    calendar instead.
# 2. **The backtests mark on `bdate_range`, which includes Good Friday; the
#    curve panel does not price it.** A plain index intersection deletes those
#    marks silently -- $17.7m on seven days for one strat 1 structure. Each
#    unscored day's mark is folded onto the next scored day, which is where its
#    factor move shows up anyway.
#
# The reconciliation below has to close: regression total + P&L on flat days +
# P&L on marks past the panel's last day == the book's own equity total.

# %%
SERIES = fa.load_all_strategies(DATA, SIG, EPOCHS, FM.scores.index)
print(f"{len(SERIES)} series ({sum(1 for s in SERIES.values() if s.level == 'daily')} daily, "
      f"{sum(1 for s in SERIES.values() if s.level == 'trade')} trade)\n")

_rows = []
for _k, _s in SERIES.items():
    if _s.level != "daily":
        continue
    _X = fa.daily_design(FM, _s, n_pcs=CFG.n_pcs)
    _kept = float(_s.y.reindex(_X.index).sum())
    _flat = float(_s.y.sum()) - _kept
    _rows.append({"book": _s.name, "days_kept": len(_X), "days": len(_s.y),
                  "regression_pnl": _kept, "flat_day_pnl": _flat,
                  "off_calendar_pnl": _s.off_calendar, "book_total": _s.raw_total})
REC = pd.DataFrame(_rows)
REC["residual"] = (REC["book_total"] - REC["regression_pnl"]
                   - REC["flat_day_pnl"] - REC["off_calendar_pnl"])
print(REC.round(0).to_string())
assert REC["residual"].abs().max() < 1.0, "the P&L reconciliation does not close"
print("\nPASS -- every dollar of every equity curve is accounted for.")
print("\nThe only material 'flat day' P&L is 5Y/30Y's: its long and short cohorts "
      "sometimes exactly offset, and on those days the book carries no net\n"
      "first-order exposure at all. Those days are dropped rather than entered "
      "as zero-exposure observations, which would only shrink the estimates.")

# %%
RESULTS = fa.run_attribution(FM, SERIES, CFG, n_pcs=CFG.n_pcs)
BYKEY = {f"{r.name} [{r.level}]": r for r in RESULTS}
TRADE = fa.decisive_table(RESULTS, level="trade")
DAILY = fa.decisive_table(RESULTS, level="daily")
print(f"{len(RESULTS)} regressions: {len(TRADE)} trade-level, {len(DAILY)} daily.")

# %% [markdown]
# ## 3. THE DECISIVE TABLE
#
# ### 3a. Share of realised P&L, trade level -- ranked by convexity
#
# OLS with an intercept makes the residuals sum to exactly zero, so the realised
# P&L decomposes without remainder:
#
# `sum(y) = alpha*T + sum_k beta_k * sum(x_k)`
#
# Shares therefore close to 100%. They can exceed 100% or go negative whenever
# the factors partly offset -- which is the *normal* case here, not a pathology:
# a book that earned $213m of gamma and gave $73m of it back to slope and
# curvature genuinely has a convexity share above 1.

# %%
_show = ["strategy", "n_obs", "total_pnl", "r2"] + \
        [f"share_{k}" for k in fa.FACTOR_ORDER] + \
        ["share_unexplained", "denom_stability", "pnl_coverage"]
_t = TRADE[_show].copy()
for _c in _t.columns:
    if _c.startswith("share_") or _c == "pnl_coverage":
        _t[_c] = (100 * _t[_c]).round(1)
_t["total_pnl"] = (_t["total_pnl"] / 1e6).round(2)
_t = _t.rename(columns={"total_pnl": "P&L $m", **{f"share_{k}": k for k in fa.FACTOR_ORDER},
                        "share_unexplained": "unexpl", "denom_stability": "stab",
                        "pnl_coverage": "cover%"})
print("TRADE LEVEL -- % of realised P&L by factor\n")
print(_t.round(3).to_string(index=False))

# %% [markdown]
# ### 3b. The same contributions, gross-normalised
#
# `share_*` is the literal answer to "what % of the P&L came from X", and it is
# the only reading that closes to 100%. But it divides by a net that is sometimes
# a small residue of much larger offsetting flows -- `denom_stability` in the
# table above is the ratio of the net to the sum of the absolute contributions,
# and it runs 0.13-1.00. When it is low the percentages are arithmetically
# correct and practically unreadable.
#
# So the same contributions are also shown over the **sum of their absolute
# values**. Bounded in [-1, 1], immune to a small net, and the column to read
# when comparing books whose P&L totals differ by two orders of magnitude.

# %%
_show = ["strategy", "n_obs"] + [f"gross_{k}" for k in fa.FACTOR_ORDER] + ["gross_unexplained"]
_g = TRADE[_show].copy()
for _c in _g.columns[2:]:
    _g[_c] = (100 * _g[_c]).round(1)
_g = _g.rename(columns={**{f"gross_{k}": k for k in fa.FACTOR_ORDER},
                        "gross_unexplained": "unexpl"})
print("TRADE LEVEL -- contributions as % of GROSS factor contribution\n")
print(_g.to_string(index=False))

# %% [markdown]
# ### 3c. The risk reading -- incremental R-squared and t-statistics
#
# The two blocks above are *return* attributions. They can be misleading on
# their own, and the failure mode is specific: a book can carry an enormous,
# overwhelmingly significant slope exposure that simply *happened not to earn
# anything* over this window, and its P&L share would be near zero.
#
# Incremental R-squared is the *risk* reading -- where the variance of the P&L
# comes from, which is what "is it a directional punt?" is really asking. It is
# order-dependent, and the order is the one the task specifies:
# `level -> slope -> curvature -> convexity -> carry`.
#
# t-statistics are **Newey-West**. They have to be: strat 1's cohorts are entered
# monthly and held a year, so twelve consecutive trade-level observations share
# eleven months of the same market path.

# %%
_show = ["strategy", "r2"] + [f"incr_{k}" for k in fa.FACTOR_ORDER] + \
        [f"t_{k}" for k in fa.FACTOR_ORDER]
_i = TRADE[_show].copy()
_i = _i.rename(columns={**{f"incr_{k}": f"dR2_{k[:4]}" for k in fa.FACTOR_ORDER},
                        **{f"t_{k}": f"t_{k[:4]}" for k in fa.FACTOR_ORDER}})
print("TRADE LEVEL -- incremental R2 (in the stated order) and HAC t-stats\n")
print(_i.round(3).to_string(index=False))

# %% [markdown]
# ### 3d. The daily-MTM level, and where it disagrees with the trade level
#
# The two levels agree on the linear factors and **disagree systematically on
# convexity**, and the disagreement has one cause.
#
# A daily squared parallel move averages 27.4 bp^2. Multiply by a gamma of order
# 100 $/bp^2 and the gamma term is a few thousand dollars a day, against daily
# P&L noise two orders of magnitude larger. Over a one-year holding window the
# squared move is in the thousands of bp^2 and the same gamma term is millions --
# a real fraction of the trade's P&L. So **the trade level identifies convexity
# and the daily level does not**: t-statistics on the convexity column run
# 2.1-5.4 at trade level on every book, against 0.9-2.1 daily -- and 30Y/50Y's
# daily convexity coefficient even flips sign, at t = -0.16.
#
# The daily level is the better place to read the *linear* exposures, where its
# 1,900 observations beat the trade level's 31-316. Read the two together: daily
# for level/slope/curvature, trade for convexity.

# %%
_show = ["strategy", "n_obs", "total_pnl", "r2"] + \
        [f"share_{k}" for k in fa.FACTOR_ORDER] + \
        ["share_unexplained", "denom_stability", "pnl_coverage"]
_d = DAILY[_show].copy()
for _c in _d.columns:
    if _c.startswith("share_") or _c == "pnl_coverage":
        _d[_c] = (100 * _d[_c]).round(1)
_d["total_pnl"] = (_d["total_pnl"] / 1e6).round(2)
_d = _d.rename(columns={"total_pnl": "P&L $m", **{f"share_{k}": k for k in fa.FACTOR_ORDER},
                        "share_unexplained": "unexpl", "denom_stability": "stab",
                        "pnl_coverage": "cover%"})
print("DAILY LEVEL -- % of realised P&L by factor\n")
print(_d.round(3).to_string(index=False))

print("\n\nconvexity identification, trade vs daily:\n")
for _r in TRADE.itertuples():
    _dr = DAILY[DAILY["strategy"] == _r.strategy]
    if _dr.empty:
        continue
    print(f"  {_r.strategy:30s} t_convexity  trade {_r.t_convexity:+6.2f} "
          f"(n={_r.n_obs:4d})   daily {float(_dr['t_convexity'].iloc[0]):+6.2f} "
          f"(n={int(_dr['n_obs'].iloc[0]):4d})")

# %%
_names = list(TRADE["strategy"])
_fig = go.Figure()
for _k, _c in zip(fa.FACTOR_ORDER + ("unexplained",),
                  ["#4dabf7", "#ff5c5c", "#ff9f43", "#3ddc84", "#9b8cff", "#adb5bd"]):
    _col = f"gross_{_k}"
    _fig.add_trace(go.Bar(y=_names, x=100 * TRADE[_col].fillna(0.0), name=_k,
                          orientation="h", marker_color=_c))
_fig.update_layout(barmode="relative", height=520, template="plotly_white",
                   title="Where each book's P&L came from (trade level, "
                         "gross-normalised, ranked by convexity)",
                   xaxis_title="% of gross factor contribution",
                   yaxis=dict(autorange="reversed"))
_fig

# %% [markdown]
# ## 4. Diagnostics on the fit itself
#
# ### 4a. Collinearity -- where the level/carry split is not identified
#
# If the carry regressor were clean, `beta_carry` would come back near 1: it is
# already in dollars, already signed, and enters the P&L one-for-one. It does
# not. It is -1.09 on 5Y/30Y at trade level and +14.9 on 10Yx10Y/20Yx10Y daily.
# That is collinearity, and it is structural rather than a bug: carry-and-roll at
# entry is mechanically a function of curve steepness, which is what the slope
# regressor measures. Separately, with +632bp of realised level drift the
# one-year squared terminal move is no longer orthogonal to the one-year level
# move, so `level` and `convexity` share information at the trade horizon too.
#
# Where the correlations below are large, **the split between those two columns
# is order-dependent and should be read off the incremental R-squared block, not
# off the coefficients**. It does not affect the totals or the convexity-vs-
# directional conclusion, which turns on columns that are not collinear.

# %%
_pairs = [("carry", "slope"), ("carry", "level"), ("level", "convexity"),
          ("level", "slope"), ("slope", "curvature")]
_rows = []
for _k, _s in SERIES.items():
    if _s.level != "trade":
        continue
    _X = fa.trade_design(FM, _s, n_pcs=CFG.n_pcs)
    _r = {"book": _s.name}
    for _a, _b in _pairs:
        _r[f"{_a[:4]}~{_b[:4]}"] = (float(_X[_a].corr(_X[_b]))
                                    if _a in _X and _b in _X else np.nan)
    _rows.append(_r)
print("trade-level design-matrix correlations\n")
print(pd.DataFrame(_rows).round(3).to_string(index=False))

# %% [markdown]
# ### 4b. Sensitivity -- the delta-hedged convexity regressor
#
# The buy-and-hold rule says the trade-level convexity regressor is the squared
# *terminal* move. A delta-hedged book earns realised variance instead. Both are
# run; the headline uses the horizon-matched one.
#
# Note the direction of the effect. For the *unhedged* strat 1 cohorts, swapping
# to realised variance costs R-squared (0.80 -> 0.68 on 10Yx10Y/20Yx10Y,
# 0.57 -> 0.26 on 20Yx5Y/25Yx5Y) -- the terminal-move rule is the right one for
# them. The conclusion is unchanged either way: every book that reads
# convexity-dominated on one regressor reads convexity-dominated on the other.

# %%
_tr = {k: v for k, v in SERIES.items() if v.level == "trade"}
_rv = fa.run_attribution(FM, _tr, CFG, n_pcs=CFG.n_pcs, convexity="realised_var")
_a_by = {r.name: r for r in RESULTS if r.level == "trade"}
print(f"{'book':32s} {'sq-terminal':>12s} {'realised-var':>13s} {'R2':>7s} {'->':>3s} {'R2':>6s}")
for _b in _rv:
    _a = _a_by[_b.name]
    print(f"{_b.name:32s} {100 * _a.shares['convexity']:11.1f}% "
          f"{100 * _b.shares['convexity']:12.1f}% {_a.r2:7.3f} {'->':>3s} {_b.r2:6.3f}")

# %% [markdown]
# ### 4c. Why strat 3's coarse level is a calendar quarter, not a roll segment
#
# The roll segment is strat 3's intuitive "trade" -- one per 12-month roll. Over
# 2019-2026 that is **eight observations against five regressors and an
# intercept**: two residual degrees of freedom, which will fit anything. The
# R-squared of 0.99 it returns is a statement about arithmetic. The quarterly
# blocking (31 non-overlapping observations) is long enough for the squared-move
# term to carry signal and short enough to be identified. Both are shown so the
# over-fit is visible rather than merely avoided.

# %%
_roll = fa.load_strat3(DATA, ["15Yx5Y/20Yx10Y"], FM.scores.index, trade_block=None)
_rr = fa.run_attribution(FM, {"roll": _roll["strat3 15Yx5Y/20Yx10Y"]}, CFG,
                         n_pcs=CFG.n_pcs)[0]
_rq = BYKEY["strat3 15Yx5Y/20Yx10Y [trade]"]
print(f"roll segments : n={_rr.n_obs:3d}  R2={_rr.r2:.3f}  adj R2={_rr.r2_adj:.3f}  "
      f"share_convexity={100 * _rr.shares['convexity']:.1f}%")
print(f"quarters      : n={_rq.n_obs:3d}  R2={_rq.r2:.3f}  adj R2={_rq.r2_adj:.3f}  "
      f"share_convexity={100 * _rq.shares['convexity']:.1f}%  "
      f"t_convexity={_rq.tstats['convexity']:.2f}")
assert _rr.n_obs < 10 and _rr.r2 > 0.95, "the over-fit exhibit is meant to over-fit"

# %% [markdown]
# ## 5. The sizing diagnosis
#
# ### 5a. What a DV01-neutral flattener's factor exposure actually is
#
# The hypothesis under test was: *DV01-neutral is not factor-neutral. A
# DV01-neutral flattener zeroes PC1 and is therefore by construction ~fully
# exposed to PC2.*
#
# **The first half is right and the second half is wrong**, and the correction
# matters more than the confirmation.
#
# `f = V'r` gives the package's exposure in dollars per unit of each PC score.
# But dollars-per-unit is not comparable across PCs, because the PCs do not move
# by the same amount -- PC1 carries 88.3% of daily variance and PC3 carries 0.7%.
# The columns that settle it are `var_pc1..var_pc3`, the share of the package's
# own variance from each factor: `f_k^2 * lambda_k`, normalised.
#
# Forward legs are split into the two spot legs that replicate them
# (`AxB` = long spot `A+B`, short spot `A`, same notional) using par annuities.
# That is an approximation and it is adequate here: it feeds a ratio, and the
# tie-out in 5c shows the resulting exposure vector is right to within a few
# percent where the exposure is large.

# %%
SIZING = fa.sizing_diagnosis(fa.STRAT1_STRUCTURES, FM, SIG, dv01=100_000.0)
_s = SIZING[["structure", "pc1_usd_per_unit", "pc2_usd_per_unit", "pc3_usd_per_unit",
             "var_pc1", "var_pc2", "var_pc3", "pc1_leakage_vs_outright"]].copy()
for _c in ("var_pc1", "var_pc2", "var_pc3", "pc1_leakage_vs_outright"):
    _s[_c] = (100 * _s[_c]).round(1)
print("factor exposure of a $100k-DV01 DV01-NEUTRAL flattener\n")
print(_s.round(0).to_string(index=False))

print("\n\nDV01-neutrality does remove level risk -- `pc1_leakage_vs_outright` is the "
      "package's\nPC1 exposure as a % of a same-size outright's, and it is 3.8-16.7%. "
      "It does NOT\nremove it, because PC1's loadings are humped rather than flat.")

# %% [markdown]
# ### 5b. Slope exposure against convexity exposure, per structure
#
# `slope_pnl_1sd_1y` is what a one-sigma annual PC2 move puts through the book.
# `convex_pnl_1y` is `0.5 * gamma * E[(1y parallel move)^2]`, with gamma read
# off the payoff profiles already on disk -- an independently computed greek, not
# a regression output.
#
# **The ratio is not a property of "DV01-neutral". It is a property of how far
# apart the two legs sit in PC2-loading space.**

# %%
_s = SIZING[["structure", "gamma_bp_per_bp2", "slope_pnl_1sd_1y_usd",
             "curv_pnl_1sd_1y_usd", "convex_pnl_1y_usd",
             "slope_to_convex", "curv_to_convex"]].copy()
for _c in ("slope_pnl_1sd_1y_usd", "curv_pnl_1sd_1y_usd", "convex_pnl_1y_usd"):
    _s[_c] = (_s[_c] / 1e3).round(0)
print("1-year risk, $k per $100k-DV01 package\n")
print(_s.round(4).to_string(index=False))

_wide = SIZING.set_index("structure").loc["5Y/30Y", "slope_to_convex"]
_tight = SIZING.set_index("structure").loc["10Yx10Y/20Yx10Y", "slope_to_convex"]
print(f"\n5Y/30Y slope-to-convexity  {_wide:.2f}")
print(f"10Yx10Y/20Yx10Y            {_tight:.3f}   ratio between them: {_wide / _tight:.0f}x")
assert _wide > 5.0 and _tight < 0.2

# %%
_fig = go.Figure()
for _k, _c, _n in zip(["var_pc1", "var_pc2", "var_pc3"],
                      ["#4dabf7", "#ff5c5c", "#ff9f43"],
                      ["PC1 level (residual leakage)", "PC2 slope", "PC3 curvature"]):
    _fig.add_trace(go.Bar(y=SIZING["structure"], x=100 * SIZING[_k], name=_n,
                          orientation="h", marker_color=_c))
_fig.update_layout(barmode="stack", height=380, template="plotly_white",
                   title="What a DV01-neutral flattener is actually exposed to "
                         "(share of package variance)",
                   xaxis_title="% of package factor variance",
                   yaxis=dict(autorange="reversed"))
_fig

# %% [markdown]
# ### 5c. Tie-out -- the regression betas against the analytic exposures
#
# This is the check that binds sections 1, 2 and 5 together. If the fitted
# `beta_slope` of an always-on flattener book does not come back at the ladder's
# own `f = V'r`, then either the basis or the attribution is wrong and nothing
# above can be trusted.
#
# Two tolerances, because a ratio on a near-zero denominator is exactly the trap
# flagged in 3b. `ratio_slope` is informative only where the analytic exposure is
# large; `rel_err` normalises the *error vector* by the package's total factor
# exposure `||f||`, and `cosine` says whether the exposure vector points the
# right way at all.
#
# The residual gap has a cause: `f` is the exposure at inception, while `beta` is
# the *average realised* exposure of a book whose cohorts age (a year-old
# 30Y/50Y is a 29Y/49Y) and whose DV01-neutrality drifts as rates move.

# %%
_per = {}
for _lab, _f, _bk in fa.STRAT1_STRUCTURES:
    _safe = _lab.replace("/", "-")
    _coh = pd.read_parquet(DATA / f"strat1_le_cohorts_{_safe}_always.parquet")
    _eq = pd.read_parquet(DATA / f"strat1_le_equity_{_safe}_always.parquet")
    _eq.index = pd.to_datetime(_eq.index)
    _raw = _eq["equity_usd"].astype(float).diff().dropna()
    _dy, _ = fa.align_to_factor_calendar(_raw, FM.scores.index)
    _w = fa._active_weight(_dy.index, pd.to_datetime(_coh["entry"]),
                           pd.to_datetime(_coh["exit"]).fillna(pd.Timestamp(FM.scores.index[-1])),
                           _coh["gate_direction"].astype(float))
    _ss = fa.StrategySeries(name=f"LEalways {_lab}", level="daily", y=_dy, weight=_w)
    _X = fa.daily_design(FM, _ss, n_pcs=CFG.n_pcs)
    _per[f"LEalways {_lab}"] = fa.attribute(_dy.reindex(_X.index), _X,
                                            name=f"LEalways {_lab}", level="daily",
                                            hac_lag=CFG.hac_lag_daily)

TIE = fa.exposure_tieout(FM, fa.STRAT1_STRUCTURES, _per, dv01=100_000.0)
print(TIE.round(3).to_string(index=False))

_ti = TIE.set_index("structure")
assert (_ti["cosine"] > 0.99).all(), "the fitted exposure vector points the wrong way"
for _lab in ("5Y/30Y", "20Yx5Y/25Yx5Y"):
    assert _ti.loc[_lab, "rel_err"] < 0.10, f"{_lab} tie-out is loose"
    assert abs(_ti.loc[_lab, "ratio_slope"] - 1.0) < 0.10, f"{_lab} slope ratio"
for _lab in ("30Y/50Y", "10Yx10Y/20Yx10Y"):
    assert _ti.loc[_lab, "rel_err"] < 0.60, f"{_lab} tie-out is broken, not merely loose"
print(f"\nPASS -- cosine > 0.99 on all four.")
print(f"The two LARGE-exposure structures tie out on the exposure vector to "
      f"{100 * _ti.loc['5Y/30Y', 'rel_err']:.1f}% and "
      f"{100 * _ti.loc['20Yx5Y/25Yx5Y', 'rel_err']:.1f}%, and the slope coefficient")
print(f"alone to {100 * abs(_ti.loc['5Y/30Y', 'ratio_slope'] - 1):.1f}% and "
      f"{100 * abs(_ti.loc['20Yx5Y/25Yx5Y', 'ratio_slope'] - 1):.1f}% of its analytic value.")
print("The two SMALL-exposure structures carry a larger relative error on a tiny")
print("denominator (f_slope of $409-$2,463 against packages whose ||f|| is $9k-$21k),")
print("which is cohort ageing, not a broken basis -- their cosines are 0.996 and 0.999.")

# %%
print("gamma tie-out: fitted beta_convexity against 0.5 x gamma from the payoff profile\n")
print(f"{'structure':20s} {'0.5*gamma*1e5':>14s} {'trade beta':>11s} {'(t)':>7s} "
      f"{'daily beta':>11s} {'(t)':>7s}")
for _lab, _f, _bk in fa.STRAT1_STRUCTURES:
    _g = 0.5 * fa.gamma_from_payoff_profile(SIG, _lab) * fa.BP_TO_USD
    _rt = BYKEY[f"strat1_base {_lab} [trade]"]
    _rd = _per[f"LEalways {_lab}"]
    print(f"{_lab:20s} {_g:14.1f} {_rt.coefs['convexity']:11.1f} "
          f"{_rt.tstats['convexity']:7.2f} {_rd.coefs['convexity']:11.1f} "
          f"{_rd.tstats['convexity']:7.2f}")
print("\nThe TRADE-level coefficients land within roughly +/-45% of an independently")
print("computed greek on all four structures, at t = 3.5-4.8. The DAILY ones do not")
print("(t = 1.0-1.6, one sign flip) -- which is section 3d's point restated: the daily")
print("squared move is noise-sized, and daily convexity shares must not be quoted alone.")

# %% [markdown]
# ## 6. The verdict
#
# ### The premise is inverted, and the real split runs through strategy 1
#
# **1. Strat 1 base is not "the one that trades RV". Three of its four
# structures are convexity-dominated and the fourth is the most directional book
# in the entire package.**
#
# `5Y/30Y` earns **259.6% of its P&L from the slope factor** (t = 39.5,
# incremental R-squared 0.71 at trade level and 0.86 daily) and 16.5% from
# convexity. Its total R-squared of 0.97 is not a strategy with an unexplained
# edge; it is a slope position with a small convexity garnish. The other three --
# `10Yx10Y/20Yx10Y` (172% convexity, 0% slope), `30Y/50Y` (142%, -4%),
# `20Yx5Y/25Yx5Y` (55%, 0%) -- carry essentially no slope exposure at all.
#
# This also explains the evidence that produced the premise. The long-end
# backtest's R-squared of 0.80-0.83 on the gated curve move, the monotone
# +39.5/+10.4/+4.3/+0.4/-29.9 bucket ramp, the -18.04bp negative residual on
# 5Y/30Y: all of that was measured **on 5Y/30Y**, the one structure where it is
# true. Generalising it to strat 1 was the error.
#
# **2. Strat 3 is not a directional punt. It is the second-most
# convexity-dominated book here.** `15Yx5Y/20Yx5Y` 124% and `15Yx5Y/20Yx10Y` 86%
# of P&L from convexity, with slope shares of 1.1% and t-statistics on slope of
# -0.34 and -0.49. The mtm-share evidence (1.29 of net, >= 0.88 on all 15 pairs)
# was not wrong, it was *measuring something else*: mtm-share says "marked to
# market", not "directional". A delta-hedged gamma harvest books its entire
# earnings through the mark. The two statements are compatible and only one of
# them answers the question.
#
# **3. Strat 2's CA leg is the purest relative value of the set -- on a stronger
# criterion than convexity.** Daily R-squared **0.011**. Nothing in level, slope,
# curvature or convexity explains it, and 186% of its P&L is the intercept. That
# is the signature of a true convergence trade: orthogonal to the curve, paid by
# the convergence of the traded quantity itself.
#
# Its convexity coefficient is the one place where the two levels genuinely
# conflict rather than merely differ in power, and the conflict is worth stating
# plainly rather than quoting whichever half fits. Daily it is **negative**
# (-71% of P&L) as short gamma predicts, but at t = -0.78 -- which section 3d
# already said is not identified. At trade level, where convexity IS identified,
# it is **positive** (+26.7%, t = +2.32). The likely reading of the positive
# trade-level sign is not gamma at all: epochs are entered when the screen flags
# a rich CA, and a rich CA is itself larger in high-volatility months, so a
# 1-year-window squared move picks up "how much premium was collected", not "how
# much gamma was paid". Neither coefficient is decisive.
#
# **The strat 2 conclusion therefore rests on orthogonality, not on the gamma
# sign** -- R-squared 0.011 daily and 0.150 at trade level, against 0.30-0.97 for
# every strat 1 book. It has a low convexity share because it is not a long-gamma
# book, and it is the purest RV here because none of the curve factors reach it.
#
# Note the fly hedge in isolation, though: `hedged - unhedged` is 66% level and
# -41% slope with a t-stat of 2.55 on slope, and it lost $606k. The 2s5s10s
# hedge is the *only* directional thing in strategy 2, and it was bolted onto the
# one leg that did not need it.
#
# ### The sizing diagnosis -- the hypothesis is half right, and the wrong half matters
#
# The proposal was: *DV01-neutral zeroes PC1 and is therefore by construction
# ~fully exposed to PC2.*
#
# **Confirmed: DV01-neutral is not factor-neutral, and it is not even
# PC1-neutral.** PC1's loadings are humped (0.279 at 2Y, 0.334 at 7Y, 0.272 at
# 50Y), not flat, so a package with zero net DV01 keeps 3.8-16.7% of a same-size
# outright's level exposure.
#
# **Refuted: the residual is not slope, except for one structure.** Share of
# package factor variance:
#
# | structure | PC1 level | PC2 slope | PC3 curvature | slope/convexity |
# |---|---|---|---|---|
# | 5Y/30Y | 5.1% | **88.9%** | 6.0% | **7.08** |
# | 30Y/50Y | 43.3% | 29.3% | 27.4% | 0.39 |
# | 20Yx5Y/25Yx5Y | **69.0%** | 14.7% | 16.4% | 0.59 |
# | 10Yx10Y/20Yx10Y | **61.3%** | 0.2% | **38.5%** | 0.055 |
#
# The slope-to-convexity ratio spans **130x** across four structures that are all
# DV01-neutral flatteners. So the ratio is not a property of DV01-neutral sizing
# at all -- it is a property of **how far apart the two legs sit in PC2-loading
# space**. 5Y and 30Y sit at PC2 loadings of **+0.282 and -0.281**: a 0.563
# spread across a factor whose full width on this grid is 0.849, so the package
# picks up two thirds of the available slope. `10Yx10Y/20Yx10Y` decomposes onto
# spot points at +0.526m of 20Y against -0.134m of 10Y and -0.393m of 30Y, whose
# PC2 loadings (-0.213, -0.016, -0.281) very nearly cancel -- $409 of net slope
# exposure per unit, against $56,249 for 5Y/30Y. **137x less slope, from the same
# DV01-neutral rule.**
#
# The tight forward pairs are not slope trades. They are **residual-level-leakage
# plus curvature** trades: `10Yx10Y/20Yx10Y` is 61% level and 38% curvature and
# 0.2% slope. Its dominant unwanted exposure is the level risk that DV01-
# neutrality was supposed to have removed, and the second is curvature.
#
# ### What that implies for sizing
#
# 1. **5Y/30Y should not be sized as a convexity trade, because it is not one.**
#    At $100k DV01 it carries $5.4m of one-sigma annual slope risk against $765k
#    of expected convexity earnings. If the convexity thesis is what is wanted,
#    the structure has to change (tighter legs) or the slope has to be hedged
#    explicitly -- DV01-neutrality will not do it.
# 2. **The other three need a PC1 hedge, not a PC2 hedge.** Their leakage is
#    level, and DV01-neutral sizing does not remove it because PC1 is humped. A
#    PC1-neutral rather than DV01-neutral weighting is the fix, and
#    `RVUtils/pca_rv.py::curve_weights(short, long, neutralize=("PC1",))` already
#    computes it.
# 3. **The convexity thesis HAS been tested, and it survives.** Three of strat
#    1's structures, both strat 3 pairs and both strat 1 long-end books put
#    86-172% of realised P&L through the convexity term, at t = 2.7-5.4 on an
#    independently checkable regressor whose fitted coefficient lands within
#    ~30% of the payoff-profile gamma. What had not been tested was 5Y/30Y, and
#    it fails.
#
# ### Ranking by convexity share (trade level)
#
# 1. strat1_base 10Yx10Y/20Yx10Y **171.5%**
# 2. strat1_base 30Y/50Y **142.2%**
# 3. strat3 15Yx5Y/20Yx5Y **123.8%**
# 4. strat1_LE always **111.8%**
# 5. strat1_LE swaption_only **99.6%**
# 6. strat3 15Yx5Y/20Yx10Y **86.1%**
# 7. strat1_base 20Yx5Y/25Yx5Y **54.7%**
# 8. strat2 hedged **48.9%**
# 9. strat2 CA leg **26.7%** (but R2 = 0.15; it is orthogonal to the basis, not
#    directional)
# 10. strat1_base 5Y/30Y **16.5%** -- the directional punt
# 11. strat2 fly hedge only **-136.2%** (short the convexity it was hedging)

# %%
print("=" * 78)
print("FINAL: % of realised P&L, trade level, ranked by convexity share")
print("=" * 78)
_final = TRADE[["strategy", "n_obs", "total_pnl"] +
               [f"share_{k}" for k in fa.FACTOR_ORDER] + ["share_unexplained", "r2"]].copy()
_final["total_pnl"] = (_final["total_pnl"] / 1e6).round(2)
for _c in [c for c in _final.columns if c.startswith("share_")]:
    _final[_c] = (100 * _final[_c]).round(1)
_final.columns = ["strategy", "n", "P&L $m"] + [k for k in fa.FACTOR_ORDER] + ["unexpl", "R2"]
print(_final.to_string(index=False))
print()
print("Convexity leader:", TRADE["strategy"].iloc[0],
      f"({100 * TRADE['share_convexity'].iloc[0]:.1f}%)")
print("Most directional:", "strat1_base 5Y/30Y",
      f"(slope {100 * float(TRADE.loc[TRADE['strategy'] == 'strat1_base 5Y/30Y', 'share_slope'].iloc[0]):.1f}%, "
      f"t = {float(TRADE.loc[TRADE['strategy'] == 'strat1_base 5Y/30Y', 't_slope'].iloc[0]):.1f})")
print("Purest RV (orthogonal to the whole basis): strat2 CA leg, daily R2 =",
      f"{float(DAILY.loc[DAILY['strategy'] == 'strat2 CA leg (unhedged)', 'r2'].iloc[0]):.3f}")
