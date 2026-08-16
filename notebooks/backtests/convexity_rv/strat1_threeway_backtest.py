# %% [markdown]
# # Strategy 1, three ways — the **curve**, the **swaption** and the **exchange**
#
# **The question, in one line.** The same long-gamma exposure is for sale in
# three places, and all three reduce to a normal volatility in **bp/day**:
#
# | source | the number | where it comes from |
# |---|---|---|
# | **CURVE** | the flattener's *breakeven vol* — what you must realise to cover carry | `strat1_curve_gamma.breakeven_vol` |
# | **SWAPTION** | ATMF normal vol, sector-matched node **1Yx2Y** | Citi Velocity cube (local store) |
# | **LISTED** | ATM normal vol at the horizon-matched expiry | SFR (3M SOFR) futures options |
#
# Cheapest wins. But a single winner is the *least* interesting output, and this
# notebook is built around the three questions that carry information:
#
# **(a) How often does the ranking change, and do the two curve-vs-vol signals
# ever disagree?** If curve-vs-swaption and curve-vs-listed always give the same
# verdict, the listed leg adds nothing over the swaption leg — and that is a
# finding, not a failure. §6–§7.
#
# **(b) The swaption-minus-listed basis as its own series.** A real traded spread
# (sell OTC gamma, buy listed gamma), and the only part of this study that does
# not involve the curve at all. §8.
#
# **(c) Does "cheap vs **BOTH**" beat "cheap vs the swaption alone"?** The direct,
# honest test of whether the third leg carries information. §9.
#
# ---
#
# ## Three things this notebook establishes before it uses anything
#
# 1. **The window is the intersection, and it is short** (§2). The curve runs from
#    2019-01, the swaption cube from 2015-10, the listed panel only
#    **2024-07-01 .. 2026-07-28**. The three-way comparison exists *only* where all
#    three are present. Measured: **517 dates**, not 540. No three-way statistic
#    below is computed off a longer window.
# 2. **Sector matching is mandatory** (§2). An SFR option prices a 3-month rate; a
#    30-year forward flattener is not the same risk. The universe is the five
#    SFR-sector forward flatteners `strat1_listed` built, and the swaption node is
#    **1Yx2Y**. JPM's own 1Yx30Y appears only in §13, explicitly labelled as a
#    *non*-sector-matched reference.
# 3. **Every gate mode is scored on bit-identical cohort P&L** (§4). Swap NPV is
#    linear in `bpv`, so all five gates are derived arithmetically from one stored
#    engine run per structure. That claim is **verified against a fresh engine
#    pass**, not assumed — and the tie-out is exact to 0.0 bp.
#
# ## Sample-size warning, stated once and honoured throughout
#
# Two years with a one-year holding period is about **two** non-overlapping
# observations per structure, and the five structures have a measured mean
# pairwise P&L correlation of **0.70**. **No Sharpe ratio is claimed anywhere.**
# The headline outputs are the ranking, agreement and basis statistics (§6–§8),
# which are statements about pricing and survive a short sample. The gate P&L in
# §9–§11 is an illustration, labelled as such, and §12 reports the
# expected-maximum-Sharpe-under-null for the number of gates compared.
#
# **Network.** Nothing here can reach a vendor. Every input is local parquet: the
# strategy-1-listed signal panel, its cohort tables, and the swaption-cube store.
# `STIRFutureOptionMDP` / `USTFutureOptionMDP` are never imported, and no
# `sabr_smile` call exists anywhere in this notebook's import graph.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import math
import pathlib
import sys
import warnings

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"

from BT.trade_dashboard import compare_curves, summary_stats, trade_dashboard
from RVUtils.ConvexityRV import strat1_listed as sl
from RVUtils.ConvexityRV import strat1_threeway as tw
from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series

warnings.filterwarnings("ignore", category=RuntimeWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)
print("repo      ", _REPO)
print("artifacts ", DATA)


def safe(label: str) -> str:
    return label.replace("/", "-").replace(" ", "_")


# %% [markdown]
# ## 1. CONFIG — every knob, documented at the point of use
#
# `Strat1ThreeWayConfig` is frozen and nothing in it is tuned on the P&L. The
# knobs that matter most for honesty are `require_all_three` (forces every gate
# onto the same 517-date intersection, so gate differences measure *information*
# rather than *coverage*) and `signal_lag_days` (must equal the lag the stored
# engine runs used, or the derived books are not comparable to them).

# %%
CFG = tw.Strat1ThreeWayConfig()
print(json.dumps({k: (str(v) if isinstance(v, (datetime.date, tuple)) else v)
                  for k, v in CFG.as_dict().items()}, indent=2, default=str))
print("\ngate modes           :", tw.GATE_MODES)
print("DISTINCT gate modes  :", tw.DISTINCT_GATE_MODES,
      "  <- 'cheapest' is dropped: it is identical to 'both' (proved in §5)")

# %%
PANEL = pd.read_parquet(DATA / "strat1_listed_signal_panel.parquet")
PANEL["date"] = pd.to_datetime(PANEL["date"])
THREE = tw.threeway_frame(PANEL, CFG)
BASIS = tw.basis_frame(PANEL, CFG)
COHORTS = {}
for _lbl, _f, _b in CFG.structures:
    _p = DATA / f"strat1_listed_cohorts_{safe(_lbl)}.parquet"
    if _p.exists():
        COHORTS[_lbl] = pd.read_parquet(_p)
print(f"panel     {PANEL.shape[0]} rows")
print(f"three-way {THREE.shape[0]} rows x {THREE.shape[1]} cols")
print(f"basis     {len(BASIS)} dates")
print(f"cohorts   {len(COHORTS)} structures loaded")
assert len(COHORTS) == len(CFG.structures), "missing stored cohort tables"

# %% [markdown]
# ## 2. Coverage — the intersection, **stated before any three-way number**
#
# This is deliberately the first table in the notebook. The three series have
# very different histories, and every statistic after this point is restricted to
# the rows where all three are present.

# %%
COV = tw.intersection_report(THREE)
print(json.dumps(COV, indent=2))
print()
print(f"  curve breakeven  : available on {COV['rows_curve_ok']}/{COV['n_rows']} rows")
print(f"  swaption ATMF    : available on {COV['rows_swaption_ok']}/{COV['n_rows']} rows")
print(f"  listed ATM       : available on {COV['rows_listed_ok']}/{COV['n_rows']} rows")
print(f"  ALL THREE        : {COV['rows_all_three']} rows on "
      f"{COV['dates_all_three']} dates  <-- THE THREE-WAY WINDOW")
print()
print("The curve panel runs from 2019-01-02 and the swaption cube from 2015-10-08.")
print("Neither binds. The LISTED panel is the whole constraint, at both ends.")
assert COV["dates_all_three"] <= COV["n_dates"]
assert COV["rows_all_three"] < COV["n_rows"], "expected some rows to lack a benchmark"

# %% [markdown]
# ### 2a. Sector matching — what is being compared to what
#
# The five structures below all sit inside the 1Y–6Y span that the SFR strip
# actually prices. Strategy 1's own long-end universe (30s/50s, 20Yx5Y/25Yx5Y,
# 10Yx10Y/20Yx10Y) has **no listed benchmark at all** — the instrument that would
# price it is a UST bond option, and there is no offline UST futures-option
# history in this repo. Those structures appear only in §13, and never with a
# listed number attached.

# %%
print("three-way universe (SFR-sector forward flatteners):")
for _l, _f, _b in CFG.structures:
    print(f"  {_l:14s}  pay {_f:7s} / receive {_b:7s}")
print(f"\nswaption node used as the OTC leg: {sl.Strat1ListedConfig().otc_expiry}"
      f"x{sl.Strat1ListedConfig().otc_tenor}  (sector-matched to the curve legs)")
print("long-end structures with NO listed benchmark:",
      [s[0] for s in sl.LONG_END_STRUCTURES])

# %% [markdown]
# ## 3. Sign probe — the conventions, asserted rather than trusted
#
# Inherited from strategy 1 and re-checked here on the actual frame, because a
# silent sign flip in a long-gamma study inverts every conclusion:
#
# ```
# CURVE bpv < 0 = FLATTENER = LONG convexity
# signal +1 = curve is CHEAP gamma -> FLATTENER
# signal -1 = curve is RICH  gamma -> STEEPENER
# basis > 0 = swaptions price MORE vol than the exchange
# ```

# %%
_u = THREE[THREE["usable"].to_numpy(bool)]

# cheap means the curve's breakeven sits BELOW the benchmark
_cheap = _u[_u["signal_swaption"] > 0]
_rich = _u[_u["signal_swaption"] < 0]
assert (_cheap["curve_bp_day"].to_numpy(float)
        < _cheap["swaption_bp_day"].to_numpy(float)).all(), "signal +1 must mean cheap"
assert (_rich["curve_bp_day"].to_numpy(float)
        > _rich["swaption_bp_day"].to_numpy(float)).all(), "signal -1 must mean rich"
print(f"OK  signal +1 <=> breakeven < benchmark   ({len(_cheap)} rows)")
print(f"OK  signal -1 <=> breakeven > benchmark   ({len(_rich)} rows)")

# basis orientation
_b0 = _u.iloc[0]
assert _b0["basis_bp_day"] == (_b0["swaption_bp_day"] - _b0["listed_bp_day"])
print(f"OK  basis = swaption - listed             "
      f"({_b0['swaption_bp_day']:.3f} - {_b0['listed_bp_day']:.3f} = {_b0['basis_bp_day']:+.3f})")

# the sentinels are ranked, not dropped
_n_inf = int(np.isposinf(_u["curve_bp_day"].to_numpy(float)).sum())
_n_zero = int((_u["curve_bp_day"].to_numpy(float) == 0.0).sum())
assert _n_inf > 0 and _n_zero > 0, "expected both breakeven sentinels in this sample"
assert (_u.loc[np.isposinf(_u["curve_bp_day"].to_numpy(float)), "rank_curve"] == 3.0).all()
assert (_u.loc[_u["curve_bp_day"].to_numpy(float) == 0.0, "rank_curve"] == 1.0).all()
print(f"OK  never_cheap (+inf) ranks 3rd of 3     ({_n_inf} rows)")
print(f"OK  always_cheap (0.0) ranks 1st of 3     ({_n_zero} rows)")

# stored-direction convention on the cohort tables
_c0 = COHORTS["2Yx2Y/3Yx2Y"]
assert set(np.unique(_c0["direction"])) <= {-1.0, 1.0}
print(f"OK  stored cohort directions are +/-1     "
      f"({int((_c0['direction'] > 0).sum())} flatteners, {int((_c0['direction'] < 0).sum())} steepeners)")

# %% [markdown]
# ## 4. Known-answer tie-outs — **the cell that makes the rest trustworthy**
#
# Four independent checks. Every gate-mode number in this notebook is derived
# arithmetically from stored engine runs, so if any of these failed, none of the
# P&L below would mean anything.
#
# **(i) The signals are recomputed, and must equal the stored ones.**
# `threeway_frame` recomputes the curve-vs-benchmark signals from the bp/day
# columns rather than copying strategy-1-listed's `signal_otc` / `signal_listed`,
# so it works on any frame carrying three vols. That is only safe if the two
# agree on the real panel — *including* on the `always_cheap` (0) and
# `never_cheap` (+inf) sentinel rows, which is exactly where a naive numeric
# comparison would diverge from `signal_from_breakeven`'s status switch.
#
# **(ii) `apply_gate` replays the stored run exactly.** Feeding the stored
# direction back through the gate arithmetic must return the stored `net_pnl_bp`.
#
# **(iii) The published strategy-1-listed numbers are reproduced.** The
# `listed_only` gate must return the per-structure net-bp-per-cohort figures the
# strategy-1-listed study reported, to the digit.
#
# **(iv) Linearity was verified against a fresh engine pass.** Loaded from the
# artifact `_strat1_threeway_build.py verify` wrote.

# %%
# ---- (i) recomputed signals == stored signals, on the intersection
_ms = int((_u["signal_swaption"].to_numpy(float) != _u["src_signal_otc"].to_numpy(float)).sum())
_ml = int((_u["signal_listed"].to_numpy(float) != _u["src_signal_listed"].to_numpy(float)).sum())
assert _ms == 0 and _ml == 0, f"signal tie-out failed: {_ms} / {_ml} mismatches"
print(f"(i)   recomputed signals == stored, on all {len(_u)} intersection rows "
      f"(swaption {_ms} mismatches, listed {_ml})")

# ---- (ii) apply_gate replays the stored direction exactly
_errs = {}
for _lbl in COHORTS:
    _stored_sig = (PANEL[PANEL["structure"] == _lbl]
                   .set_index("date").sort_index()["signal_listed"])
    _g = tw.apply_gate(COHORTS[_lbl], _stored_sig, cfg=CFG)
    assert (_g["gate_direction"].to_numpy(float) == _g["direction"].to_numpy(float)).all()
    _c = _g[_g["gate_closed"].to_numpy(bool)]
    _errs[_lbl] = float(np.abs(_c["gate_net_bp"].to_numpy(float)
                               - _c["net_pnl_bp"].to_numpy(float)).max())
assert max(_errs.values()) < 1e-9, _errs
print(f"(ii)  apply_gate replays the stored engine P&L; worst error "
      f"{max(_errs.values()):.2e} bp across {len(_errs)} structures")

# ---- (iii) the published strategy-1-listed per-structure numbers
BOOKS = tw.all_gate_books(THREE, COHORTS, CFG)
_published = {"1Yx2Y/2Yx2Y": -10.68, "1Yx2Y/3Yx2Y": -11.21, "1Yx3Y/2Yx3Y": -6.12,
              "2Yx2Y/3Yx2Y": 1.99, "2Yx3Y/3Yx3Y": 2.20}
_gs = tw.gate_summary(BOOKS, CFG, by_structure=True)
_lo = _gs[_gs["gate_mode"] == "listed_only"].set_index("structure")["net_bp_mean"]
for _k, _v in _published.items():
    assert abs(float(_lo[_k]) - _v) < 0.01, (_k, float(_lo[_k]), _v)
print("(iii) listed_only gate reproduces the published strat1-listed numbers:")
for _k, _v in _published.items():
    print(f"        {_k:14s} derived {float(_lo[_k]):+7.3f}  published {_v:+6.2f}")

# ---- (iv) the linearity verification artifact
_vp = DATA / "strat1_threeway_linearity.json"
if _vp.exists():
    LIN = json.loads(_vp.read_text())
    assert LIN["linearity_holds"] and LIN["no_gate_wanted_the_extra_dates"]
    print(f"(iv)  fresh engine pass on {LIN['structure']}: max |unit - direction*stored| = "
          f"{LIN['max_abs_err_bp']:.1e} bp over {LIN['n_matched_closed']} closed cohorts")
    print(f"        stored entries subset of unit entries: {LIN['stored_entries_subset_of_unit']}")
    print(f"        the {len(LIN['extra_unit_entries'])} extra unit cohorts "
          f"({', '.join(LIN['extra_unit_entries'])}) are dates where NO gate mode trades,")
    print("        so the derived books have no coverage hole.")
else:
    print("(iv)  linearity artifact absent -- run `_strat1_threeway_build.py verify`")

# %% [markdown]
# ## 5. `both` and `cheapest` are the **same gate** — proved, not asserted
#
# The study specification asked for four gate modes. Two of them are provably one
# mode, and saying so is more useful than shipping two identical curves:
#
# ```
# both = +1  <=>  curve < swaption - t  AND  curve < listed - t
#            <=>  curve < min(swaption, listed) - t   =  cheapest = +1
# both = -1  <=>  curve > max(swaption, listed) + t   =  cheapest = -1
# ```
#
# "the curve beats both benchmarks" and "the curve is the cheapest of the three"
# are the same proposition, so **no knob separates them** — not the no-trade band,
# not `trade_when_rich`. The two are computed by deliberately *different*
# expressions (an AND over the two signals, versus a min/max comparison), so the
# check below compares two code paths rather than restating one.

# %%
ID = tw.assert_both_equals_cheapest(THREE)
print(json.dumps(ID, indent=2, default=str))
assert ID["identical"], "both != cheapest -- one of the two code paths has a bug"
for _t in (0.0, 0.5, 2.0):
    for _twr in (True, False):
        _c = tw.Strat1ThreeWayConfig(entry_threshold_bp_per_day=_t, trade_when_rich=_twr)
        _r = tw.assert_both_equals_cheapest(tw.threeway_frame(PANEL, _c))
        assert _r["identical"], (_t, _twr)
        print(f"  threshold={_t:4.1f}  trade_when_rich={_twr!s:5s}  ->  identical on "
              f"{_r['n_rows']} rows")
print("\n=> the multiple-testing correction in §12 counts FOUR distinct gates, not five.")

# %% [markdown]
# ## 6. The three vol series, and who is cheapest
#
# All three in bp/day on one axis. The curve's breakeven is per-structure; the two
# market vols are common to every structure on a given date.

# %%
_lbl = "2Yx2Y/3Yx2Y"
_s = THREE.xs(_lbl, level="structure")
_s = _s[_s["usable"].to_numpy(bool)]
_fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                     row_heights=[0.68, 0.32],
                     subplot_titles=(f"normal vol, bp/day — curve ({_lbl}) vs swaption vs listed",
                                     "curve minus each benchmark, bp/day"))
_cv = _s["curve_bp_day"].replace([np.inf, -np.inf], np.nan)
_fig.add_trace(go.Scatter(x=_s.index, y=_cv, name=f"CURVE breakeven ({_lbl})",
                          line=dict(color="#ff9f43", width=2)), row=1, col=1)
_fig.add_trace(go.Scatter(x=_s.index, y=_s["swaption_bp_day"], name="SWAPTION 1Yx2Y ATMF",
                          line=dict(color="#4dabf7", width=2)), row=1, col=1)
_fig.add_trace(go.Scatter(x=_s.index, y=_s["listed_bp_day"], name="LISTED SFR ATM",
                          line=dict(color="#3ddc84", width=2)), row=1, col=1)
_fig.add_trace(go.Scatter(x=_s.index, y=-_s["cheapness_vs_swaption_bp_day"],
                          name="curve - swaption", line=dict(color="#4dabf7", width=1)),
               row=2, col=1)
_fig.add_trace(go.Scatter(x=_s.index, y=-_s["cheapness_vs_listed_bp_day"],
                          name="curve - listed", line=dict(color="#3ddc84", width=1)),
               row=2, col=1)
_fig.add_hline(y=0, line=dict(color="#888", width=1), row=2, col=1)
_fig.update_layout(height=640, template="plotly_white",
                   title="§6 the three sources of the same gamma, one unit")
_fig.update_yaxes(title_text="bp/day", row=1, col=1)
_fig.show()
print("Note: never_cheap days carry breakeven = +inf and are BLANK in the top panel")
print(f"      by design ({int(np.isposinf(_s['curve_bp_day'].to_numpy(float)).sum())} of "
      f"{len(_s)} days here). They are ranked 3rd of 3, not dropped.")

# %% [markdown]
# ### 6a. How often is each source the cheapest gamma?

# %%
RANKS = tw.rank_table(THREE)
print(RANKS[["structure", "n_days", "frac_cheapest_curve", "frac_cheapest_swaption",
             "frac_cheapest_listed", "frac_richest_curve", "median_curve_bp_day",
             "median_swaption_bp_day", "median_listed_bp_day"]].round(4).to_string(index=False))
print()
print("Reading it: the LISTED exchange is the cheapest of the three on ~49% of")
print("pooled rows, the curve on ~31%, the swaption on ~20%. But the curve is the")
print("RICHEST source on 67% of rows — it is bimodal, not middling: it is either")
print("free convexity (always_cheap, breakeven 0) or it cannot be paid for at all.")
print()
print(RANKS[["structure", "frac_curve_zero", "frac_curve_inf"]].round(4).to_string(index=False))
print("  frac_curve_zero = 'always_cheap' days (carry is positive, gamma is free)")
print("  frac_curve_inf  = 'never_cheap'  days (no vol covers the carry)")

# %% [markdown]
# ### 6b. Does the ranking actually move?
#
# A ranking that never changes carries no information; one that changes daily is
# noise. This is the fraction of consecutive observed days on which the cheapest
# source is different from the previous day's.

# %%
TRANS = tw.transition_table(THREE)
print(TRANS.round(4).to_string(index=False))
print()
print("11%–22% of days change the winner, and a regime lasts 4.5–8.8 business days.")
print("That is slow enough to be a real pricing state and fast enough to matter —")
print("the ordering is not a fixed property of the structures.")

# %% [markdown]
# ## 7. (a) Do the two signals ever **disagree**?
#
# This is the question that decides whether the listed leg is worth carrying.
# `signal_swaption` and `signal_listed` are the *same* curve breakeven measured
# against two different benchmarks, so they disagree only when the benchmarks
# straddle the breakeven.

# %%
AGREE = tw.agreement_table(THREE)
print(AGREE[["structure", "n_days", "n_disagree", "frac_disagree",
             "frac_both_cheap", "frac_both_rich",
             "frac_swaption_cheap_listed_rich", "frac_swaption_rich_listed_cheap",
             "frac_gate_differs_from_swaption"]].round(4).to_string(index=False))

# %%
_p = AGREE[AGREE["structure"] == "POOLED"].iloc[0]
print(f"POOLED: the two benchmarks disagree on {_p['n_disagree']:.0f} of "
      f"{_p['n_days']:.0f} rows = {_p['frac_disagree']:.2%}\n")
print("WHY it is so low — and this is arithmetic, not evidence that the two")
print("markets agree about volatility:")
print(f"  the observed |basis| has median  {float(np.nanmedian(np.abs(BASIS['basis_bp_day']))):.3f} bp/day")
print(f"  but flipping a verdict needs the basis to exceed |curve - swaption|,")
print(f"  whose 25th percentile is       {_p['basis_needed_to_flip_25pct_bp_day']:.3f} bp/day")
print(f"  i.e. the basis would have to be ~{_p['basis_needed_to_flip_25pct_bp_day'] / float(np.nanmedian(np.abs(BASIS['basis_bp_day']))):.0f}x larger to flip even a quarter of days.")
print()
print("The curve-vs-vol gap DWARFS the OTC/listed basis. The two benchmarks are")
print("~0.25 bp/day apart; the curve sits several bp/day from either. So the")
print("substitution is a genuine change of benchmark that RARELY changes the sign.")
assert 0.0 < _p["frac_disagree"] < 0.10, "expected a small but non-zero disagreement rate"

# %% [markdown]
# ## 8. (b) The swaption-minus-listed **basis** as its own series
#
# This is a real traded spread and the only section here that does not involve the
# curve. Positive = the OTC market prices more vol than the exchange.

# %%
_fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                     row_heights=[0.55, 0.45],
                     subplot_titles=("ATM normal vol, bp/day — OTC 1Yx2Y swaption vs listed SFR",
                                     "basis = swaption - listed, bp/day"))
_fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS["swaption_bp_day"], name="SWAPTION 1Yx2Y",
                          line=dict(color="#4dabf7", width=2)), row=1, col=1)
_fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS["listed_bp_day"], name="LISTED SFR",
                          line=dict(color="#3ddc84", width=2)), row=1, col=1)
_fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS["basis_bp_day"], name="basis",
                          line=dict(color="#9b8cff", width=2), fill="tozeroy"), row=2, col=1)
_fig.add_hline(y=0, line=dict(color="#888", width=1), row=2, col=1)
_fig.add_hline(y=float(BASIS["basis_bp_day"].median()), line=dict(color="#ff5c5c", width=1, dash="dot"),
               row=2, col=1)
_fig.update_layout(height=620, template="plotly_white",
                   title="§8 the OTC / listed vol basis — a traded spread in its own right")
_fig.update_yaxes(title_text="bp/day", row=1, col=1)
_fig.update_yaxes(title_text="bp/day", row=2, col=1)
_fig.show()

# %%
BSUM = tw.basis_summary(BASIS)
print(BSUM.round(4).to_string(index=False))
_full = BSUM[BSUM["period"] == "FULL"].iloc[0]
print()
print(f"Level correlation swaption vs listed: "
      f"{BASIS['swaption_bp_day'].corr(BASIS['listed_bp_day']):.4f}")
print(f"Median basis {_full['median_bp_day']:+.4f} bp/day = "
      f"{_full['median_pct_of_listed']:+.2%} of the listed level; positive on "
      f"{_full['frac_positive']:.1%} of days.")
print()
print("The basis is REAL and PERSISTENT but small, and it has a clear regime:")
print("  2024Q3 mean -0.08  ->  2025Q1 peak +0.55  ->  2026Q2 flips to -0.13")
print("It is not a constant spread and it is not noise around zero. That is what")
print("makes it a candidate signal — and §11 tests whether it actually conditions")
print("anything.")
assert abs(_full["median_bp_day"]) < 1.0, "basis should be sub-bp/day"

# %% [markdown]
# ## 9. (c) Does gating on **BOTH** beat gating on the swaption alone?
#
# The straightforward, honest test. Every gate mode is scored on **bit-identical
# cohorts with bit-identical P&L** — the cohort entries, exits and unit P&L come
# from one stored engine run per structure, so the *only* thing that differs
# between these curves is the gate. §4 verified that derivation.
#
# **Weekly cohorts, 1-year hold, signal lagged one day, 0.5 bp one-way each side.**

# %%
GATES = tw.gate_summary(BOOKS, CFG)
print(GATES[["gate_mode", "n_cohorts", "n_traded", "frac_traded", "frac_flattener",
             "n_closed", "net_bp_mean", "net_bp_median", "hit_rate",
             "sharpe_per_trade", "t_stat_nominal", "t_stat_overlap_adj"]]
      .round(4).to_string(index=False))
print()
print("READ THIS TABLE AS AN ILLUSTRATION, NOT A RESULT. The `n_closed` column")
print("counts overlapping weekly cohorts; `n_eff_independent` below is what the")
print("sample actually contains.")
print(GATES[["gate_mode", "n_closed", "n_eff_independent"]].round(3).to_string(index=False))

# %%
_books = {}
for _m in tw.DISTINCT_GATE_MODES:
    _b = BOOKS[(BOOKS["gate_mode"] == _m) & BOOKS["gate_closed"].to_numpy(bool)].copy()
    if _b.empty:
        continue
    _books[_m] = (_b[["exit", "gate_net_bp"]]
                  .rename(columns={"exit": "closed_at", "gate_net_bp": "realized_pnl"})
                  .sort_values("closed_at"))
compare_curves(_books, title="§9 cumulative net P&L by GATE MODE, bp of package DV01 "
                             "(pooled over 5 SFR structures) — ILLUSTRATION ONLY",
               time_col="closed_at", pnl_col="realized_pnl", unit="bp").show()
print("'cheapest' is omitted from this chart: it is the same series as 'both' (§5),")
print("and plotting an identical curve twice would misrepresent how many distinct")
print("strategies were tried.")

# %%
_sw = GATES.set_index("gate_mode")
_delta = float(_sw.loc["both", "net_bp_mean"]) - float(_sw.loc["swaption_only", "net_bp_mean"])
_ntr = int(_sw.loc["swaption_only", "n_traded"]) - int(_sw.loc["both", "n_traded"])
print("=== THE ANSWER TO (c) ===")
print(f"  swaption_only : {float(_sw.loc['swaption_only', 'net_bp_mean']):+.4f} bp / cohort   "
      f"({int(_sw.loc['swaption_only', 'n_traded'])} traded, hit {float(_sw.loc['swaption_only', 'hit_rate']):.1%})")
print(f"  both          : {float(_sw.loc['both', 'net_bp_mean']):+.4f} bp / cohort   "
      f"({int(_sw.loc['both', 'n_traded'])} traded, hit {float(_sw.loc['both', 'hit_rate']):.1%})")
print(f"  listed_only   : {float(_sw.loc['listed_only', 'net_bp_mean']):+.4f} bp / cohort   "
      f"({int(_sw.loc['listed_only', 'n_traded'])} traded, hit {float(_sw.loc['listed_only', 'hit_rate']):.1%})")
print()
print(f"  Adding the listed veto stood aside on {_ntr} of "
      f"{int(_sw.loc['swaption_only', 'n_cohorts'])} cohorts and changed the mean")
print(f"  outcome by {_delta:+.4f} bp per cohort — i.e. by nothing, in the wrong direction,")
print("  on a sample far too small to call either way.")

# %% [markdown]
# ## 10. `trade_dashboard` on the best gate mode
#
# "Best" here means highest Sharpe-per-trade among the four distinct gates. §12
# shows that number does not clear the bar a null model sets, so this dashboard is
# a *description of a book*, not evidence of an edge.

# %%
_best = GATES.iloc[int(np.nanargmax(GATES["sharpe_per_trade"].to_numpy(float)))]["gate_mode"]
print(f"best gate mode by Sharpe/trade: {_best}\n")
print(summary_stats(_books[_best] if _best in _books else next(iter(_books.values())),
                    time_col="closed_at", pnl_col="realized_pnl",
                    unit="bp", span_years=2.0).to_string(index=False))
print("\n*** The 'annualised Sharpe' above is NOT a strategy Sharpe and is not claimed")
print("    as one. Those closed 'trades' are weekly-opened 1-year cohorts pooled over")
print("    five structures whose mean pairwise P&L correlation is 0.70; they share")
print("    ~98% of their holding windows. The t-statistic — and specifically the")
print("    overlap-adjusted one in §9 — is the honest summary of the evidence.")
trade_dashboard(_books[_best] if _best in _books else next(iter(_books.values())),
                time_col="closed_at", pnl_col="realized_pnl", unit="bp",
                title=f"§10 three-way gate '{_best}' — illustration only").show()

# %% [markdown]
# ### 10a. Per-structure, so the pooled number is not hiding a split

# %%
_gsb = tw.gate_summary(BOOKS, CFG, by_structure=True)
print(_gsb[_gsb["gate_mode"].isin(["swaption_only", "listed_only", "both"])]
      [["gate_mode", "structure", "n_traded", "n_closed", "frac_flattener",
        "net_bp_mean", "hit_rate", "sharpe_per_trade", "t_stat_overlap_adj"]]
      .round(4).to_string(index=False))
print()
print("The split tracks how ONE-SIDED the gate was, not a vol edge. Measured on the")
print("`both` gate, flattener share against mean net bp per cohort:")
_x = _gsb[_gsb["gate_mode"] == "both"][["structure", "frac_flattener", "net_bp_mean"]]
print(_x.round(4).to_string(index=False))
print(f"\n  rank correlation(flattener share, net bp) = "
      f"{_x['frac_flattener'].corr(_x['net_bp_mean'], method='spearman'):+.3f} over 5 points")
print("  The three structures that lost were short convexity on ~72-78% of cohorts;")
print("  the two that made money were near balanced. The front SOFR curve repriced")
print("  the easing path ONCE over this window, so this is one event, not five.")

# %% [markdown]
# ## 11. Does the basis **condition** the outcome?
#
# Question (b)'s operational half. If the OTC/listed basis says anything about
# when curve gamma is worth owning, it should show up as a monotone pattern
# across basis buckets at entry.

# %%
COND = tw.conditional_basis_table(BOOKS, BASIS, CFG, mode="both")
print(COND.round(4).to_string(index=False))
print()
print("No monotone pattern. Bucket 0 (most NEGATIVE basis — the exchange dearer")
print("than OTC) is the worst and bucket 1 (basis ~0) the best, with buckets 2-4")
print("in between and no ordering. With ~40-55 highly overlapping cohorts per")
print("bucket drawn from ~2 independent years, this table cannot distinguish a")
print("real conditioning effect from noise, and it does not claim to.")

# %% [markdown]
# ## 12. Multiple testing — the bar four gate modes have to clear
#
# Four *distinct* gates were compared (§5 showed `cheapest` is not a fifth). Under
# a null where none of them has an edge, the best of four still produces a
# positive Sharpe by luck, and the expected size of that luck depends on how many
# independent observations the sample contains — which is about **two**, not 267.

# %%
_n_closed = int(np.nanmax(GATES["n_closed"].to_numpy(float)))
_n_eff = float(np.nanmax(GATES["n_eff_independent"].to_numpy(float)))
_best_sr = float(np.nanmax(GATES["sharpe_per_trade"].to_numpy(float)))
_bar_nom = tw.expected_max_sharpe_under_null(len(tw.DISTINCT_GATE_MODES), _n_closed)
_bar_eff = tw.expected_max_sharpe_under_null(len(tw.DISTINCT_GATE_MODES), max(2, round(_n_eff)))
print(f"distinct gate modes compared      : {len(tw.DISTINCT_GATE_MODES)}")
print(f"closed cohorts (nominal)          : {_n_closed}")
print(f"effective independent observations: {_n_eff:.2f}")
print()
print(f"best observed Sharpe / trade      : {_best_sr:+.4f}")
print(f"E[max Sharpe | null], nominal n   : {_bar_nom:+.4f}   <- flattering, wrong n")
print(f"E[max Sharpe | null], effective n : {_bar_eff:+.4f}   <- the honest bar")
print()
print(f"deflated Sharpe vs the honest bar : "
      f"{tw.deflated_sharpe_ratio(_best_sr, max(2, round(_n_eff)), sr_benchmark=_bar_eff):.4f}")
print()
if _best_sr < _bar_eff:
    print("=> The best of four gates does NOT clear what pure luck would produce on a")
    print("   sample this size. There is no evidence of a gate-selection edge here,")
    print("   and the correct report of the P&L section is 'inconclusive by construction'.")
assert _best_sr < _bar_eff, "if this ever fails, revisit whether the sample grew"

# %% [markdown]
# ## 13. The long end — where the listed benchmark is **missing**
#
# The contrast that makes the low disagreement rate interesting. Over the *same*
# 2024-07 .. 2026-07 window, strategy 1's long-end forward flatteners are cheap
# against 1Yx30Y swaptions on essentially **100%** of days — versus 19–44% for the
# SFR-sector structures here.
#
# The long end is exactly where a listed benchmark would be most valuable, and
# exactly where it does not exist: pricing it needs **UST bond options**, and there
# is no offline UST futures-option panel in this repo. `listed_vol.load_ust_panel`
# raises rather than returning an empty frame, and the adapter
# `ust_price_vol_to_yield_vol` is implemented and hand-tested so it works the
# moment data exists.
#
# **1Yx30Y appears below as a deliberately NON-sector-matched reference.** It is
# not a three-way comparison and is never mixed into the tables above.

# %%
_s1 = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
_s1["date"] = pd.to_datetime(_s1["date"])
_le = _s1[(_s1["date"] >= pd.Timestamp(CFG.start)) & (_s1["date"] <= pd.Timestamp(CFG.end))]
_rows = []
for _l, _g in _le.groupby("structure"):
    _g = _g[np.isfinite(_g["atmf_vol_bp_day"].to_numpy(float))]
    _rows.append({
        "structure": _l, "listed_benchmark": "UNAVAILABLE (needs UST bond options)",
        "n_days": len(_g),
        "frac_cheap_vs_1Yx30Y": float((_g["signal_breakeven"] > 0).mean()),
        "frac_always_cheap": float((_g["breakeven_status"] == "always_cheap").mean()),
        "median_atmf_bp_day": float(_g["atmf_vol_bp_day"].median()),
    })
LONG_END = pd.DataFrame(_rows)
print(LONG_END.round(4).to_string(index=False))
print()
print("versus the SFR-sector structures on the same window:")
print(RANKS[RANKS["structure"] != "POOLED"][["structure", "frac_cheapest_curve"]]
      .round(4).to_string(index=False))
print()
print(f"1Yx30Y ATMF median over this window: "
      f"{float(np.nanmedian(_le['atmf_vol_bp_day'])):.3f} bp/day  (NOT sector-matched)")
print(f"1Yx2Y  ATMF median (sector-matched): "
      f"{float(BASIS['swaption_bp_day'].median()):.3f} bp/day")
print(f"listed SFR ATM median             : {float(BASIS['listed_bp_day'].median()):.3f} bp/day")

# %% [markdown]
# ## 14. VERDICT

# %%
VERDICT = tw.threeway_verdict(THREE, BASIS, BOOKS, CFG)
(DATA / "strat1_threeway_verdict.json").write_text(
    json.dumps(VERDICT, indent=2, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in VERDICT.items()
                  if k in ("coverage", "identity_both_equals_cheapest",
                           "pooled_ranking", "pooled_agreement", "basis_full_sample",
                           "best_gate_mode", "best_gate_sharpe_per_trade",
                           "expected_max_sharpe_under_null_effective",
                           "best_gate_deflated_sharpe", "best_gate_beats_null",
                           "listed_information", "n_distinct_gate_modes")},
                 indent=2, default=str))
print("\nfull verdict (incl. per-structure transitions and the gate table) written to")
print(f"  {DATA / 'strat1_threeway_verdict.json'}")

# %%
# The single sentence the whole study exists to produce, in the machine-readable
# verdict as well as the prose -- a consumer reading only the JSON must get the
# same headline as a reader of section 14.
print(VERDICT["listed_information"]["verdict"])
assert VERDICT["listed_information"]["listed_materially_changes_verdict"] is False, (
    "if this ever flips, the headline finding has changed and section 14 must be rewritten")

# %% [markdown]
# ### The findings, in order of evidential weight
#
# **1. The three-way window is 517 days, and that is the whole study.** 2,585
# (date, structure) rows over 2024-07-01 .. 2026-07-28. The curve panel starts in
# 2019 and the swaption cube in 2015; the listed panel binds both ends. Nothing
# above is quoted off a longer window.
#
# **2. Listed is the cheapest gamma most often; the curve is the most
# *volatile* source.** Pooled: listed cheapest **48.7%**, curve **31.1%**,
# swaption **20.1%**. But the curve is the *richest* source **67.3%** of the time
# — it is bimodal rather than middling. On **17.3%** of rows its breakeven is
# exactly zero (`always_cheap`: carry is positive, the convexity is free) and on
# **6.7%** it is infinite (`never_cheap`: no volatility covers the carry). The
# ordering also moves: the winner changes on **11%–22%** of days, with regimes
# lasting 4.5–8.8 business days.
#
# **3. (a) The two signals almost never disagree — 1.59% of rows.** 41 of 2,585,
# ranging 0.58% (1Yx2Y/2Yx2Y) to 3.48% (2Yx3Y/3Yx3Y). **This is arithmetic, not
# agreement between the two markets.** The OTC/listed basis has a median absolute
# size of ~0.27 bp/day, while flipping even a quarter of days would need it to
# exceed **2.72 bp/day** — roughly ten times larger. The curve-vs-vol gap simply
# dwarfs the basis.
#
# **=> On this sample, in this sector, the listed benchmark adds essentially no
# information over the sector-matched swaption.** That is the finding. It is a
# genuine change of benchmark that changes the verdict on 1.6% of rows and the
# traded outcome by −0.04 bp per cohort.
#
# **4. (b) The basis is real, persistent, and regime-driven — but small.** Median
# **+0.251 bp/day** (**+4.0%** of the listed level), positive on **75.6%** of days,
# p05..p95 −0.24..+0.76, full range −0.52..+1.22, level correlation **0.9597**.
# Quarterly means run −0.08 (2024Q3) → **+0.55** (2025Q1) → −0.13 (2026Q2), so the
# OTC premium to listed vol was substantial in early 2025 and had inverted by mid-
# 2026. As a *conditioning* variable (§11) it shows no monotone relationship with
# outcomes, and the sample cannot support one either way.
#
# **5. (c) Conditioning on "cheap vs BOTH" does not improve the trade.** The
# listed veto stood aside on **6 of 525** cohorts and moved the mean outcome by
# **−0.044 bp per cohort**. swaption_only −4.760, both −4.804, listed_only −4.764
# bp per cohort. The three gates are indistinguishable, which is exactly what
# finding 3 predicts.
#
# **6. `both` and `cheapest` are the same gate**, at every configuration — proved
# in §5 on two independent code paths. Four gate modes were compared, not five,
# and the multiple-testing correction uses four.
#
# **7. No gate mode clears the null — and every one of them lost money.** Pooled
# over the five structures, all four distinct gates returned about **−4.8 bp per
# cohort** with a Sharpe/trade of **−0.27**, against an expected-maximum-under-
# null of **+0.744** at the effective sample size (4 trials, ~2 independent
# observations). The best gate is negative, so "best of four" is not even a
# multiple-testing story here: the front SOFR curve repriced the easing path once
# over this window, the gate was short convexity into it on ~68% of days, and
# every cohort is a different view of that one event. The P&L section is
# inconclusive by construction and is labelled that way throughout.
#
# **8. The interesting gap is the long end.** Over the same window strategy 1's
# long-end forward flatteners are cheap against 1Yx30Y swaptions on **100%** of
# days (median breakeven 0.000, i.e. `always_cheap`) versus 19–44% here — and the
# long end is precisely where the listed benchmark is missing. Testing whether
# *that* result survives a listed benchmark needs UST bond-option history, which
# does not exist offline. The adapter is built and hand-tested; only the data is
# absent.
#
# ### What would change the answer
#
# * **UST futures-option history**, which would let the long end — where the curve
#   looks 100% cheap and the result is therefore most fragile — be priced against
#   an exchange rather than against the OTC market alone.
# * **A longer listed panel.** Two years and roughly two independent gamma cycles
#   cannot separate any of these gates. Ten years would make §9–§12 answerable.
# * **A wider-moneyness listed benchmark.** Only the ATM point is used here; the
#   listed smile exists and an expected-payoff signal under the listed density is
#   already wired (`signal_ep_listed`), but it is a different question.

# %%
print("artifacts written:")
for _p in sorted(DATA.glob("strat1_threeway_*")):
    print(f"  {_p.name:52s} {_p.stat().st_size / 1024:8.1f} KB")
