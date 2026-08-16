# %% [markdown]
# # Strategy 1, three ways, on the **LONG END** — curve vs swaption vs exchange
#
# **The question.** The same long-gamma exposure is for sale in three places, and
# all three reduce to a normal volatility in **bp/day**:
#
# | source | the number | where it comes from |
# |---|---|---|
# | **CURVE** | the flattener's *breakeven vol* — what you must realise to cover carry | `strat1_curve_gamma.breakeven_vol` |
# | **SWAPTION** | ATMF normal vol at **1Yx30Y** — the note's own node | Citi Velocity cube (local store) |
# | **LISTED** | UST futures-option **ABPV**, annualised bp/yr on the CTD's yield | QuikStrike constant-maturity harvest |
#
# ---
#
# ## Why this run exists, and why the earlier one could not answer it
#
# The earlier three-way study reached a clean conclusion — *"the listed benchmark
# adds essentially no information over the sector-matched swaption"* — but it
# reached it **in the wrong sector, on 517 days**. The SFR options it used price a
# 3-month rate; strategy 1's structures are 30-year flatteners. So the study had
# to substitute SFR-sector stand-in structures, and its window was capped by the
# SFR panel's two-year span.
#
# The constant-maturity UST vol harvest removed both limits at once:
#
# | | SFR / short end (prior) | **UST / long end (here)** |
# |---|---|---|
# | intersection | 517 dates, 2024-07 → 2026-07 | **1,854 dates, 2019-01 → 2026-08** |
# | structures | SFR-sector 2–3Y-tail forwards | **strategy 1's own long-end four** |
# | swaption node | 1Yx2Y (a sector-matched proxy) | **1Yx30Y** (the note's node) |
# | n_eff per structure | 2.05 | **7.50** |
#
# ## The specific thing being re-tested
#
# The short-end finding did not rest on the disagreement rate itself. It rested on
# a **ratio**: the median |OTC−listed basis| was **0.271 bp/day** while flipping a
# quarter of days would have needed **2.721** — a factor of **10**. At that ratio
# the two benchmarks *arithmetically cannot* often disagree, whatever the two
# markets believe.
#
# The long end is a different market. Swaption vol there is set by
# structured-product and mortgage-convexity hedging; listed bond-option vol by
# macro funds and dealer gamma. **If the basis is much larger there, listed
# carries information here even though it did not in the short end.** §7 re-measures
# that ratio with the identical expression.
#
# ## What this notebook establishes before it uses anything
#
# 1. **The intersection, and its length, first** (§2). 1,854 days for the
#    US-benchmarked structures, 1,614 for the UL-benchmarked ones, 1,614 in common.
#    No three-way statistic below is quoted off anything longer.
# 2. **The benchmark is pre-specified** (§3). `primary` @ 30-day constant maturity,
#    where `primary` is fixed per structure by `listed_vol.UST_SECTOR_MAP` from the
#    *measured* CTD maturity of each contract. The other eleven benchmarks are
#    robustness (§10), not extra trials.
# 3. **Every gate is scored on bit-identical cohort P&L** (§4). Verified against a
#    fresh 27-minute engine pass on the one structure where it can bite.
#
# ## Sample-size warning, stated once and honoured throughout
#
# Monthly cohorts held one year over 7.5 years is **7.50** non-overlapping
# observations per structure — 3.7x the short end's 2.05, and still not 88. The
# four structures have a **measured** mean pairwise cohort-P&L correlation of
# **0.698**, worth `k_eff = 1.29` independent structures, so the pooled effective
# count is **9.7**, not 352. §12 quotes every Sharpe against the
# expected-maximum-under-null at that count.
#
# **Network.** Nothing here can reach a vendor. Every input is local parquet.
# `USTFutureOptionMDP` / `STIRFutureOptionMDP` are never imported and no
# `sabr_smile` call exists anywhere in this notebook's import graph.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import itertools
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
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_listed as sl
from RVUtils.ConvexityRV import strat1_threeway as tw

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)
warnings.filterwarnings("ignore", category=FutureWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"


# %% [markdown]
# ## 1. CONFIG — every knob, and why it is where it is
#
# `tw.longend_config()` differs from the SFR default in exactly two fields
# (`structures`, and the window). Everything that touches the cohorts —
# `horizon_years`, `cost_bp_one_way`, `package_dv01`, `signal_lag_days` — is left
# at strategy 1's own value on purpose, because the gate books are derived from
# strategy 1's own stored cohort tables and would not be comparable to them
# otherwise.

# %%
CFG = tw.longend_config()

#: Pre-specified headline benchmark. Fixed in the module, not in this cell, so it
#: cannot become "the best of twelve" after the fact.
ROLE, CM = tw.HEADLINE_ROLE, tw.HEADLINE_CM_DAYS

print("Strat1ThreeWayConfig (long-end):")
for k, v in CFG.as_dict().items():
    print(f"  {k:32s} {v}")
print(f"\nheadline benchmark: role={ROLE!r} @ cm_days={CM}")
print(f"distinct gate modes (trial count): {tw.DISTINCT_GATE_MODES}")

# The universe, and which listed root benchmarks each structure -- read off the
# measured CTD map, never hand-typed here.
print("\nsector map (from measured CTD maturity):")
for label, _f, _b in CFG.structures:
    b = lv.ust_benchmarks_for(label)
    p = lv.UST_CTD_PROFILE[b["primary"]]
    print(f"  {label:18s} primary={b['primary']} (CTD {p['ctd_ttm_yrs']:.2f}y, "
          f"~{p['swap_point']})  alt={b['alt']}  control={b['control']}")

# %% [markdown]
# **The consequence worth stating up front**: the contract *named* "30-year bond"
# (US) has a cheapest-to-deliver with a median **15.9 years** left, so the primary
# benchmark for 30Y/50Y is the **Ultra Bond (UL, CTD 25.6 years)**, not US. The
# sector map is driven by that measurement and by nothing else.

# %%
LONGEND_PANEL = DATA / "strat1_listed_longend_panel.parquet"
S1_PANEL = DATA / "strat1_signal_panel.parquet"
TW_PANEL = DATA / "strat1_threeway_longend_panel.parquet"
TW_BASIS = DATA / "strat1_threeway_longend_basis.parquet"
TW_BOOKS = DATA / "strat1_threeway_longend_books.parquet"
TW_SWEEP = DATA / "strat1_threeway_longend_sweep.csv"
TW_VERIFY = DATA / "strat1_threeway_longend_linearity.json"

panel = pd.read_parquet(LONGEND_PANEL)
panel["date"] = pd.to_datetime(panel["date"])
print(f"long-end listed panel: {len(panel):,} rows "
      f"= {panel['date'].nunique():,} dates x {panel['structure'].nunique()} structures "
      f"x {panel['listed_symbol'].nunique()} benchmarks")

three = tw.threeway_frame(
    tw.select_longend_benchmark(panel, role=ROLE, cm_days=CM), CFG)
print(f"three-way frame @ {ROLE}@{CM}: {len(three):,} rows")

# %% [markdown]
# ### 1a. Sanity: the selector really picked the mapped root
#
# A silently mis-selected benchmark would invalidate everything downstream and
# would look completely normal in a plot, so it is asserted rather than eyeballed.

# %%
_sel = tw.select_longend_benchmark(panel, role=ROLE, cm_days=CM)
_got = _sel.drop_duplicates("structure").set_index("structure")["listed_root"].to_dict()
_want = {label: lv.UST_SECTOR_MAP[label]["primary"] for label, _f, _b in CFG.structures}
assert _got == _want, (_got, _want)
assert set(_sel["listed_cm_days"]) == {CM}
assert not _sel.duplicated(subset=["date", "structure"]).any()
print("selected primary roots:", _got)
print("matches UST_SECTOR_MAP:", _got == _want)
print("unique (date, structure) key:", not _sel.duplicated(subset=['date', 'structure']).any())


# %% [markdown]
# ## 2. THE INTERSECTION, AND ITS LENGTH — before any statistic
#
# The honesty requirement this study was given: *quote every three-way statistic
# only on the true intersection, and report its length first.* So it is reported
# first, and per structure — because the primary root is **not the same contract
# for every structure**, and the roots do not share a history.

# %%
_ir = tw.longend_intersection_report(three)
print("POOLED")
for k in ("n_rows", "n_dates", "rows_all_three", "dates_all_three",
          "intersection_window", "frac_rows_usable"):
    print(f"  {k:22s} {_ir['pooled'][k]}")

print("\nPER STRUCTURE (each statistic below uses this structure's own intersection)")
_per = pd.DataFrame(_ir["per_structure"])
print(_per.to_string(index=False))

print(f"\nCOMMON to all four structures: {_ir['n_common_dates']:,} dates "
      f"{_ir['common_window']}")
print(f"\n{_ir['note']}")

# %% [markdown]
# **Read this before anything else.**
#
# * The intersection is **1,854 days** for the two US-benchmarked structures
#   (5Y/30Y, 10Yx10Y/20Yx10Y) and **1,614** for the two UL-benchmarked ones. UL is
#   a thinner series than US; TN, used only as an alt, starts in 2023.
# * **1,614 days are common to all four.** Every per-structure number below uses
#   that structure's own intersection, which is the right choice (it uses all the
#   data each structure has) — the common count is the floor any *cross-structure*
#   claim would have to be re-measured on.
# * The binding constraint is the **swaption**, not the listed panel: 47 of 1,901
#   days carry no 1Yx30Y ATMF. That is the reverse of the short-end study, where
#   the listed panel was the constraint on both ends.
#
# Compare with the prior run: **517 dates → 1,854.** A 3.6x longer window, on the
# structures the note actually recommends.

# %%
# The three coverages as a picture -- where each source is present, by year.
_cov = three.reset_index()
_cov["year"] = _cov["date"].dt.year
_rows = []
for (y, s), g in _cov.groupby(["year", "structure"]):
    _rows.append({"year": y, "structure": s,
                  "curve": int((~np.isnan(g["curve_bp_day"].to_numpy(float))).sum()),
                  "swaption": int(np.isfinite(g["swaption_bp_day"].to_numpy(float)).sum()),
                  "listed": int(np.isfinite(g["listed_bp_day"].to_numpy(float)).sum()),
                  "all_three": int(g["usable"].sum())})
_cvt = pd.DataFrame(_rows)
fig = go.Figure()
for src, col in (("curve", "#4C78A8"), ("swaption", "#F58518"), ("listed", "#54A24B"),
                 ("all_three", "#111111")):
    g = _cvt.groupby("year")[src].sum()
    fig.add_trace(go.Bar(x=g.index, y=g.values, name=src,
                         marker_color=col, opacity=0.9 if src == "all_three" else 0.6))
fig.update_layout(title="§2 rows present per source per year (4 structures pooled) — "
                        "the swaption is the binding constraint, not the exchange",
                  barmode="group", height=380, template="plotly_white",
                  yaxis_title="rows")
fig.show()


# %% [markdown]
# ## 3. THE THREE SERIES, ALIGNED, IN bp/day
#
# All three are normal vols in bp/day on the same axis. The curve series carries
# two sentinels that are meaningful and are kept, never dropped:
# `always_cheap` stores **0.0** (the package carries positively, so it is cheap
# against *any* vol) and `never_cheap` stores **+inf**.

# %%
_p = three.reset_index()
fig = make_subplots(rows=2, cols=2, shared_xaxes=True,
                    subplot_titles=[s for s, _f, _b in CFG.structures])
for i, (label, _f, _b) in enumerate(CFG.structures):
    g = _p[(_p["structure"] == label) & _p["usable"]].set_index("date").sort_index()
    r, c = divmod(i, 2)
    cv = g["curve_bp_day"].replace([np.inf], np.nan)
    for name, s, col in (("curve (breakeven)", cv, "#4C78A8"),
                         ("swaption 1Yx30Y", g["swaption_bp_day"], "#F58518"),
                         ("listed", g["listed_bp_day"], "#54A24B")):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, line=dict(color=col, width=1),
                                 showlegend=(i == 0), legendgroup=name), row=r + 1, col=c + 1)
fig.update_layout(height=680, template="plotly_white",
                  title="§3 the three vols in bp/day, per structure "
                        "(curve +inf days blanked; they are RICH, not missing)")
fig.show()

# %%
# Medians on the intersection, per structure. The listed root differs by
# structure, so the benchmark columns are NOT the same series across rows.
_med = []
for label, _f, _b in CFG.structures:
    g = _p[(_p["structure"] == label) & _p["usable"]]
    root = _sel.loc[_sel["structure"] == label, "listed_root"].iloc[0]
    cv = g["curve_bp_day"].to_numpy(float)
    _med.append({
        "structure": label, "listed": f"{root}_{CM}", "n_days": len(g),
        "curve_bp_day": np.median(cv[np.isfinite(cv)]),
        "swaption_bp_day": np.median(g["swaption_bp_day"]),
        "listed_bp_day": np.median(g["listed_bp_day"]),
        "frac_curve_always_cheap": float((cv == 0.0).mean()),
        "frac_curve_never_cheap": float(np.isposinf(cv).mean()),
    })
print(pd.DataFrame(_med).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

# %% [markdown]
# The curve breakeven is **far below both market vols** on the three forward
# structures — median 0.00 / 0.41 / 1.07 bp/day against ~5.0–5.4 for the two
# markets. That is what "saturated" means below: those flatteners carry positively
# on 34–85% of days, so no benchmark can make them look rich.
#
# **5Y/30Y is the exception**: median breakeven 2.42 bp/day against swaption 5.02
# and listed 5.63, with 21.8% of days at `never_cheap`. Its verdict genuinely
# moves, and it is the only structure on which the choice of benchmark can change
# anything.


# %% [markdown]
# ## 4. TIE-OUTS — run before any result is read
#
# Four checks. Each is an assert, not a printout to be eyeballed.

# %% [markdown]
# ### 4a. The recomputed signal IS strategy 1's own signal
#
# `gate_swaption_only` is the curve breakeven read against the 1Yx30Y ATMF —
# exactly what `strat1_curve_gamma` already stored. If these differ, the long-end
# mode is measuring something other than strategy 1's signal and every gate
# comparison is against the wrong baseline.
#
# Restricted to `usable` rows because `require_all_three=True` deliberately zeroes
# the gate where the listed benchmark is absent. That is the gate working.

# %%
_s1 = pd.read_parquet(S1_PANEL)
_s1["date"] = pd.to_datetime(_s1["date"])
_j = (three.reset_index().set_index(["date", "structure"])
      .join(_s1.set_index(["date", "structure"])["signal"].rename("stored"), how="inner"))
_u = _j["usable"].to_numpy(bool)
_ndiff = int((_j.loc[_u, "gate_swaption_only"].to_numpy(float)
              != _j.loc[_u, "stored"].to_numpy(float)).sum())
print(f"gate_swaption_only vs stored strat1 signal: {_ndiff} differ of {int(_u.sum()):,} usable rows")
assert _ndiff == 0
assert int(_u.sum()) == 6936

# %% [markdown]
# ### 4b. Known answer: replaying the stored direction reproduces the stored P&L
#
# This pins the cost convention (charged twice, only when traded) and the
# linearity derivation at once. It is the single check that makes every gate-mode
# number below trustworthy.

# %%
def _safe(label): return label.replace("/", "-")


cohorts = {label: pd.read_parquet(DATA / f"strat1_cohorts_{_safe(label)}.parquet")
           for label, _f, _b in CFG.structures}

for label, c in cohorts.items():
    sig = pd.Series(c["direction"].to_numpy(float), index=pd.to_datetime(c["entry"]))
    b = tw.apply_gate(c, sig, cfg=CFG, lag_days=0)     # direction indexed by entry
    m = b["gate_closed"].to_numpy(bool)
    err = np.abs(b.loc[m, "gate_net_bp"].to_numpy(float) - c.loc[m, "net_pnl_bp"].to_numpy(float))
    print(f"  {label:18s} n_cohorts={len(c):3d} n_closed={int(m.sum()):3d} "
          f"max|err|={err.max():.2e} bp")
    assert err.max() < 1e-9, label

# %% [markdown]
# ### 4c. Linearity, verified against a fresh engine pass
#
# The gate books are derived arithmetically from **one** stored run per structure
# rather than one engine pass per gate. That rests on swap NPV being linear in
# `bpv`, so flipping the sign negates the package exactly.
#
# On the long end that claim is load-bearing in exactly **one** place: three of
# the four structures were traded with `direction == +1` on all 88 cohorts, so for
# them the "unit flattener" run *is* the stored run and the identity is trivially
# `+1 × x == x`. **5Y/30Y is the only structure with a mixed book** (45 flatteners,
# 43 steepeners), so it is the only one where the negation does real work — and it
# is the one re-run against the engine (1,624 s, 91 cohorts).

# %%
_lin = json.loads(TW_VERIFY.read_text(encoding="utf-8"))
print(json.dumps({k: v for k, v in _lin.items()
                  if k not in ("extra_entry_detail", "why_this_structure", "omission_note")},
                 indent=1))
assert _lin["linearity_holds"]
assert _lin["max_abs_err_bp"] == 0.0
assert _lin["n_stored_steepeners"] == 43
assert _lin["stored_entries_subset_of_unit"]
assert _lin["all_extras_explained_by_missing_swaption"]
print(f"\nmax abs error over {_lin['n_matched_closed']} matched closed cohorts, "
      f"including {_lin['n_stored_steepeners']} steepeners: "
      f"{_lin['max_abs_err_bp']} bp — exact")

# %% [markdown]
# ### 4d. The cohort-coverage gap, quantified rather than waved at
#
# The unit run opened **91** monthly cohorts; the stored run opened **88**. All
# three differences are explained, and the explanation has to be read off
# **strategy 1's own grid**, not the three-way grid — they are not the same grid.
# The curve store has rows on days the exchange is shut, so 2024-03-29 (Good
# Friday) exists in `strat1_signal_panel.parquet` but not in the listed panel.

# %%
for d, v in _lin["extra_entry_detail"].items():
    print(f"  {d}: stored lagged onto {v['stored_lagged_onto']} — swaption "
          f"{'MISSING' if v['swaption_atmf_there'] is None else 'present'}, "
          f"strat1 signal {v['stored_signal_there']}")
    print(f"      -> gate would have been "
          f"{v['gate_on_threeway_grid']['both'] if v['gate_on_threeway_grid'] else None}, "
          f"worth {v['gated_gross_bp_if_it_had_opened']} bp gross")
print(f"\n{_lin['omission_note']}")

# %% [markdown]
# So: **two** of the three (Feb/Mar 2020) lag onto days with no swaption quote at
# all, where every gate is 0 — nothing is lost. **One** (2024-04-01) lags onto
# Good Friday, where the swaption cube is empty so strategy 1's signal was 0, but
# where a gate reading the three-way grid's previous day (2024-03-28) would have
# gone short. On 5Y/30Y that cohort was worth **+29.70 bp gross**.
#
# **Why this does not damage the comparison.** Every gate mode is scored on the
# *same* 88 stored cohorts, so the cohort is omitted identically from all of them
# — which is precisely the "identical cohorts" requirement. Only the absolute
# level of each gate's P&L is affected, by the same amount in each. The same date
# is omitted from the other three structures' books too, with unmeasured magnitude
# and, again, identically across gates.


# %% [markdown]
# ## 5. RANKING — how often is each source the cheapest gamma?
#
# The direct answer to "cheapest wins", and the first place the saturation shows.

# %%
_ranks = tw.rank_table(three)
print(_ranks[["structure", "n_days", "frac_cheapest_curve", "frac_cheapest_swaption",
              "frac_cheapest_listed", "frac_richest_listed",
              "median_curve_bp_day", "median_swaption_bp_day", "median_listed_bp_day",
              "frac_curve_zero", "frac_curve_inf"]]
      .to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

# %%
_trans = tw.transition_table(three)
print(_trans.to_string(index=False, float_format=lambda x: f"{x:9.4f}"))

# %% [markdown]
# **The ranking, and how often the winner changes:**
#
# * On the three forward structures the curve is the cheapest of the three on
#   **100.0%** of days and the cheapest source **never changes** — 1 regime over
#   1,854 (or 1,614) days. A ranking that never moves carries no information.
# * On **5Y/30Y** the curve is cheapest on 50.8% of days, the swaption on 42.3%
#   and the listed on 7.0%; the winner changes on **4.86%** of days, i.e. **91
#   regimes** averaging 20.4 days each. That is the only row in this table with
#   any information in it.
# * The listed benchmark is the **richest** of the three on 61.5% of pooled days —
#   the exchange consistently prices more vol than the OTC swaption, which is §6.


# %% [markdown]
# ## 6. THE OTC−LISTED BASIS — level, percentiles, persistence, regime
#
# A real traded spread (sell OTC gamma, buy listed gamma) and the only part of
# this study that does not involve the curve at all. **Positive means the 1Yx30Y
# swaption prices more vol than the exchange contract.**
#
# It is computed per `listed_symbol`, never collapsed to one row per date: the
# primary root differs by structure, so a date-keyed collapse would silently label
# one root's basis "the basis". `basis_frame` now raises if given a long-end panel.

# %%
basis = tw.longend_basis_frame(panel, CFG)
_persist = tw.basis_persistence(basis)
print(_persist[["listed_symbol", "n", "first", "last", "median_bp_day", "mean_bp_day",
                "std_bp_day", "p05", "p95", "frac_positive", "median_abs_bp_day"]]
      .to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

# %% [markdown]
# **The basis is NEGATIVE at every one of the twelve benchmarks.** That is the
# headline of this section and it inverts the hypothesis the study was set to
# test: the brief supposed swaptions might be the *expensive* comparison that made
# the curve look cheap. They are the **cheap** one. Listed UST vol prices a median
# 0.195–0.859 bp/day **more** vol than the 1Yx30Y swaption, so substituting the
# exchange benchmark makes the flattener look **cheaper still**.
#
# Note the ordering — UL_30 (−0.195) < US_30 (−0.545) < TN_30 (−0.555) < TY_30
# (−0.802). The basis grows as the benchmark's CTD gets **shorter**, i.e. as the
# sector match gets worse. The deliberately-wrong TY control has the largest basis
# of all, which is exactly what a sector effect looks like.

# %%
assert (_persist["median_bp_day"] < 0).all()
assert len(_persist) == 12
print("all 12 benchmarks price MORE vol than the 1Yx30Y swaption:",
      bool((_persist["median_bp_day"] < 0).all()))

# %% [markdown]
# ### 6a. Persistence — a bid/offer, or a position?

# %%
print(_persist[["listed_symbol", "n", "rho_1", "rho_5", "rho_21", "rho_63", "rho_126",
                "ar1_half_life_days", "n_sign_runs", "mean_sign_run_days"]]
      .to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

# %% [markdown]
# Two readings that **disagree**, which is the information:
#
# * the **AR(1) half-life** is short — US_30 9.5 business days, UL_30 9.3, TY_30
#   24.9 — so a shock decays quickly;
# * the **long-lag autocorrelation is not zero** — US_30 ρ(63) = 0.318, TY_30
#   0.628 — so there is a slow component an AR(1) cannot see.
#
# Sign runs average 7–38 days, so the basis holds one sign for weeks at a time.
# This is a position, not a bid/offer. §6b shows what the slow component is.

# %% [markdown]
# ### 6b. Regime — the slow component, made visible

# %%
_reg = tw.basis_regime_table(basis, by="year", symbols=["US_30", "UL_30", "TY_30"])
print(_reg.pivot(index="period", columns="listed_symbol", values="median_bp_day")
      .to_string(float_format=lambda x: f"{x:8.3f}"))
print()
print(_reg[_reg["listed_symbol"] == "US_30"]
      [["period", "n", "median_bp_day", "std_bp_day", "p05", "p95", "frac_positive",
        "median_listed_bp_day", "median_otc_bp_day"]]
      .to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

# %%
fig = go.Figure()
for sym, col in (("UL_30", "#4C78A8"), ("US_30", "#F58518"), ("TY_30", "#54A24B")):
    g = basis[basis["listed_symbol"] == sym].sort_values("date")
    fig.add_trace(go.Scatter(x=g["date"], y=g["basis_bp_day"], name=sym,
                             line=dict(color=col, width=1)))
fig.add_hline(y=0.0, line=dict(color="#888", dash="dash"))
fig.add_hline(y=tw.SHORT_END_REFERENCE["median_abs_basis_bp_day"],
              line=dict(color="#C00", dash="dot"),
              annotation_text="short-end median |basis| = +0.271")
fig.update_layout(title="§6b OTC(1Yx30Y) − listed vol basis, bp/day. Negative everywhere; "
                        "collapses through the 2022–23 rate-vol shock",
                  height=420, template="plotly_white", yaxis_title="bp/day")
fig.show()

# %% [markdown]
# **The basis is not stationary, and a single median hides the whole story.**
# US_30 runs −0.055 / −0.150 / −0.257 through 2019–2021, then collapses to
# **−1.573 (2022)** and **−1.416 (2023)** through the rate-vol shock, then recovers
# −0.700 / −0.439 / −0.107. In 2022 and 2023 the basis was negative on **100.0%**
# of days.
#
# UL_30 does the same and its **sign flips** with the regime: +0.024 (2019),
# −1.131 (2022), +0.163 (2024), **+0.376 (2026)** — positive on 82.2% of days in
# 2026. So the "listed is always richer" statement is a full-sample statement, not
# a structural one: at the end of the sample the Ultra Bond is *cheaper* than the
# swaption.
#
# The driver is visible in the last two columns: through 2022 the **listed** vol
# went to 7.53 bp/day while the swaption only reached 5.95. Exchange bond-option
# vol repriced the shock much harder than the OTC 30-year tail did.


# %% [markdown]
# ## 7. **THE RETEST** — the factor-of-10, re-measured like for like
#
# The short-end conclusion rested on this ratio and nothing else. Recomputed here
# with the **identical expression**: median |swaption − listed| against
# `np.nanpercentile(|curve − swaption|, 25)`, with `never_cheap` days (gap `+inf`)
# **included**, exactly as the short-end computation had them.

# %%
_flip = tw.flip_threshold_table(three)
print(_flip[["structure", "n_days", "frac_verdict_saturated", "median_abs_basis_bp_day",
             "flip_p25_bp_day", "shortfall_multiple_p25", "frac_disagree",
             "shortfall_multiple_p25_finite", "frac_gap_infinite",
             "frac_curve_at_sentinel"]]
      .to_string(index=False, float_format=lambda x: f"{x:9.4f}"))

# %% [markdown]
# ### Read `frac_verdict_saturated` first — it says which rows mean anything
#
# It is the share of days on the **majority verdict**. At 1.0000 the flattener is
# cheap gamma on *every single day*, so no benchmark can change the answer and the
# large ratio is **saturation, not agreement between the markets**. With breakeven
# pinned at the `always_cheap` sentinel 0.0, `|curve − swaption|` degenerates to
# the swaption level itself (~4–5 bp/day).
#
# That is true of **three of the four structures**, whose disagreement rate is
# consequently exactly **0.0000**.
#
# > **A trap worth naming**, because it is the obvious wrong selector: this must be
# > read off `frac_verdict_saturated`, **not** off the share of days at a breakeven
# > sentinel. The two rank the universe differently — 10Yx10Y/20Yx10Y has *fewer*
# > sentinel days than 5Y/30Y (0.342 vs 0.578) and yet its verdict is unanimous.
# > Selecting on sentinels nominates a structure whose disagreement rate is zero as
# > the one where the benchmark matters. The module selects on saturation and the
# > test suite pins it.
#
# ### The one row that binds
#
# | | short end (SFR) | **long end (5Y/30Y)** | change |
# |---|---|---|---|
# | n | 2,585 rows / 517 dates | **1,854** | 3.6x |
# | median \|basis\| | 0.271 bp/day | **0.556** | **x2.05** |
# | basis to flip 25% of days | 2.721 bp/day | **1.917** | x0.70 |
# | **shortfall multiple** | **10.02** | **3.45** | **÷2.91** |
# | signals disagree | 1.59% | **3.34%** | **x2.11** |
#
# **The factor of 10 becomes a factor of 3.4.** It moved from both ends at once:
# the basis roughly doubled *and* the threshold fell by about a third. The
# disagreement rate roughly doubled in step, exactly as that arithmetic predicts.
#
# This is a **real difference in kind between the two sectors** — and it is still
# not enough for the listed benchmark to decide anything. 3.34% is below the 5%
# materiality bar the short-end study set, and three of the four structures sit at
# exactly zero.

# %%
_b = _flip.set_index("structure").loc["5Y/30Y"]
assert _b["frac_verdict_saturated"] < 0.6
assert _b["shortfall_multiple_p25"] < tw.SHORT_END_REFERENCE["basis_shortfall_multiple"]
assert _b["frac_disagree"] > tw.SHORT_END_REFERENCE["frac_rows_disagree"]
for _s in ("30Y/50Y", "20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y"):
    assert _flip.set_index("structure").loc[_s, "frac_verdict_saturated"] == 1.0
    assert _flip.set_index("structure").loc[_s, "frac_disagree"] == 0.0
print(f"binding structure 5Y/30Y: ratio {_b['shortfall_multiple_p25']:.2f} vs short end "
      f"{tw.SHORT_END_REFERENCE['basis_shortfall_multiple']:.2f} "
      f"({tw.SHORT_END_REFERENCE['basis_shortfall_multiple'] / _b['shortfall_multiple_p25']:.2f}x compression)")
print(f"disagreement {_b['frac_disagree']:.4f} vs short end "
      f"{tw.SHORT_END_REFERENCE['frac_rows_disagree']:.4f} "
      f"({_b['frac_disagree'] / tw.SHORT_END_REFERENCE['frac_rows_disagree']:.2f}x)")


# %% [markdown]
# ## 8. SIGNAL AGREEMENT — curve-vs-swaption against curve-vs-listed
#
# The same curve breakeven read against two different benchmarks. If they never
# disagree, the listed leg is a relabelling.

# %%
_agree = tw.agreement_table(three)
print(_agree.to_string(index=False, float_format=lambda x: f"{x:9.4f}"))

# %% [markdown]
# * Pooled disagreement **0.89%** (62 of 6,936 rows) — but that pools three
#   structures whose disagreement is structurally zero, so it understates.
# * On **5Y/30Y**: **3.34%**, 62 of 1,854 days. Every disagreement in the study
#   comes from this one structure.
# * The disagreements are **asymmetric**: 2.70% are "swaption says rich, listed
#   says cheap" against 0.65% the other way. That follows directly from the sign of
#   the basis — listed prices more vol, so the curve clears the listed bar more
#   often than the swaption bar.
# * `frac_gate_differs_from_swaption` = 0.0334: adding the listed veto to
#   strategy 1's signal changes the verdict on 3.34% of days on 5Y/30Y and on
#   **none** anywhere else.


# %% [markdown]
# ## 9. GATE COMPARISON — on identical cohorts
#
# Five gates, all the same curve breakeven read against a different rule. Scored
# on **bit-identical** cohort P&L: same entries, same exits, same unit P&L, so any
# difference between two gate curves is the gate and nothing else.

# %%
books = tw.all_gate_books(three, cohorts, CFG)
_gs = tw.gate_summary(books, CFG)
print(_gs.to_string(index=False, float_format=lambda x: f"{x:11.4f}"))

# %% [markdown]
# ### 9a. How many gates are there, really? — the trial count
#
# The multiple-testing correction counts trials, so this has to be measured rather
# than counted off the list of names. Two quite different things make gates
# coincide, and conflating them gets the trial count wrong in both directions.

# %%
_gd = tw.gate_distinctness_table(three, books)
print(_gd.to_string(index=False, float_format=lambda x: f"{x:9.4f}"))
_gdi = _gd.set_index(["mode_a", "mode_b"])
assert _gdi.loc[("both", "cheapest"), "n_differ_daily"] == 0
assert _gdi.loc[("listed_only", "either"), "n_differ_daily"] > 0
assert _gdi.loc[("listed_only", "either"), "n_differ_at_entries"] == 0
print(f"\ntrial count used for the correction: {len(tw.DISTINCT_GATE_MODES)} "
      f"{tw.DISTINCT_GATE_MODES}")

# %% [markdown]
# * **`both` == `cheapest` is an IDENTITY** — 0 differences in 7,098 daily rows and
#   0 across 352 cohorts, re-verified here on the long end rather than inherited
#   from the short-end study. "The curve beats both benchmarks" and "the curve is
#   the cheapest of the three" are the same proposition, and the two are computed
#   by deliberately different expressions so this is a measurement of two code
#   paths, not a tautology.
# * **`listed_only` == `either` is a COINCIDENCE of this cohort grid** — they
#   differ on **12 of 7,098** daily rows, so they are genuinely different gates,
#   but none of those 12 days is one of the 88 monthly entry dates, so their books
#   are identical. **3 distinct equity curves, 4 distinct gates.**
# * The correction uses the **ex-ante** count, **4**. Using the 3 realised books
#   would lower the null threshold on an accident of the calendar.

# %%
# Only the four DISTINCT gate modes are plotted. 'cheapest' is omitted because it
# is provably the same series as 'both' (above), and drawing an identical curve
# twice would misrepresent how many strategies were tried.
_books_by_mode = {}
for _m in tw.DISTINCT_GATE_MODES:
    _b = books[(books["gate_mode"] == _m) & books["gate_closed"].to_numpy(bool)].copy()
    if _b.empty:
        continue
    _books_by_mode[_m] = (_b[["exit", "gate_net_bp"]]
                          .rename(columns={"exit": "closed_at",
                                           "gate_net_bp": "realized_pnl"})
                          .sort_values("closed_at"))

compare_curves(_books_by_mode,
               title="§9 cumulative net P&L by GATE MODE, bp of package DV01 "
                     "(pooled over the 4 long-end structures) — ILLUSTRATION ONLY",
               time_col="closed_at", pnl_col="realized_pnl", unit="bp").show()
print("Three curves are visible, not four: 'listed_only' and 'either' differ on 12")
print("of 7,098 daily rows but on NONE of the 88 monthly cohort entry dates, so on")
print("this grid their books coincide exactly. They are still two gates (§9a), and")
print("the multiple-testing correction in §12 counts four.")

# %% [markdown]
# ### 9b. What the listed veto actually did

# %%
_g = _gs.set_index("gate_mode")
_d = float(_g.loc["both", "net_bp_mean"]) - float(_g.loc["swaption_only", "net_bp_mean"])
_aside = int(_g.loc["swaption_only", "n_traded"]) - int(_g.loc["both", "n_traded"])
print(f"cohorts:                        {int(_g.loc['swaption_only', 'n_cohorts'])}")
print(f"the listed veto stood aside on: {_aside}")
print(f"mean outcome moved by:          {_d:+.4f} bp per cohort")
print(f"swaption_only mean net:         {float(_g.loc['swaption_only', 'net_bp_mean']):+.4f} bp")
print(f"both          mean net:         {float(_g.loc['both', 'net_bp_mean']):+.4f} bp")

# %% [markdown]
# Adding the listed benchmark as a veto on strategy 1's own signal stood aside on
# **4 of 352** cohorts and moved the mean outcome by **−0.046 bp per cohort** — on
# a book whose mean is +7.10 bp and whose per-cohort standard deviation is 29.3.
# The effect is three orders of magnitude smaller than the noise.


# %% [markdown]
# ## 10. ROBUSTNESS — all twelve benchmarks
#
# Does the answer depend on which contract, or on which constant maturity? Every
# (structure, root, cm) on one page. **These are robustness, not extra trials:**
# all twelve score the same four gate modes.

# %%
_sweep = pd.read_csv(TW_SWEEP)
print(_sweep[_sweep["structure"] == "5Y/30Y"]
      [["benchmark", "listed_root", "n_days", "is_headline", "frac_cheapest_curve",
        "frac_cheapest_swaption", "frac_cheapest_listed", "frac_days_ranking_changes",
        "frac_disagree", "median_basis_bp_day", "flip_p25_bp_day",
        "shortfall_multiple_p25"]]
      .to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

# %%
_b5 = _sweep[_sweep["structure"] == "5Y/30Y"]
print(f"5Y/30Y disagreement across the 12 benchmarks: "
      f"{_b5['frac_disagree'].min():.4f} .. {_b5['frac_disagree'].max():.4f}")
print(f"5Y/30Y shortfall multiple across the 12:      "
      f"{_b5['shortfall_multiple_p25'].min():.3f} .. {_b5['shortfall_multiple_p25'].max():.3f}")
print("\nrows where disagreement crosses the 5% materiality bar:")
print(_b5[_b5["frac_disagree"] >= 0.05][["benchmark", "listed_root", "frac_disagree",
                                         "median_basis_bp_day"]]
      .to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

# %% [markdown]
# **The answer does not depend on the contract or the tenor in any way that
# changes the conclusion**, and the one place it comes closest is instructive.
#
# 5Y/30Y's disagreement runs **3.24%–5.34%** across the twelve. The pre-specified
# `primary`@30 reads **3.34%**. The only two benchmarks that cross the 5% bar are
# **TY at 60 and 90 days — the deliberately-wrong control**, whose CTD is a
# 6.8-year Treasury.
#
# That is not a benchmark that "works better". Disagreement scales with the size of
# the basis, and TY has the biggest basis (−0.859 / −0.826 bp/day against US's
# −0.626 / −0.706) precisely *because* it is the worst sector match. Reading the
# control as evidence that listed matters would be reading a sector mismatch as
# information. It **strengthens** the verdict rather than weakening it: the
# sector-matched benchmarks are the ones that disagree least.
#
# On the three saturated structures every benchmark gives disagreement **0.0000**
# and ranking changes **0.0000**. Nothing moves them.


# %% [markdown]
# ## 11. `trade_dashboard` on the best gate
#
# `swaption_only` — strategy 1's own signal, unmodified — has the highest
# per-cohort Sharpe of the five. §12 is where that stops being a recommendation.

# %%
_best = str(_gs.iloc[int(np.nanargmax(_gs["sharpe_per_trade"].to_numpy(float)))]["gate_mode"])
print(f"best gate mode by Sharpe per cohort: {_best}\n")
print(summary_stats(_books_by_mode[_best], time_col="closed_at",
                    pnl_col="realized_pnl", unit="bp", span_years=7.5)
      .to_string(index=False))
print("\n*** The 'annualised Sharpe' above is NOT a strategy Sharpe and is not")
print("    claimed as one. Those closed 'trades' are monthly-opened 1-year cohorts")
print("    pooled over four structures whose measured mean pairwise unit-P&L")
print("    correlation is 0.698; they share ~92% of their holding windows. The")
print("    overlap-adjusted t in §12 is the honest summary of the evidence.")

# %%
trade_dashboard(_books_by_mode[_best], time_col="closed_at", pnl_col="realized_pnl",
                unit="bp",
                title=f"§11 long-end gate '{_best}' — illustration only "
                      f"(n_closed = {int(_gs.set_index('gate_mode').loc[_best, 'n_closed'])}, "
                      f"but n_eff = 9.7)").show()


# %% [markdown]
# ## 12. SAMPLE SIZE AND THE MULTIPLE-TESTING CORRECTION
#
# Both haircuts, both measured.

# %%
_ne = tw.effective_independent_n_pooled(cohorts, CFG)
_corr, _summ = tw.cohort_pnl_correlation(cohorts, CFG)
print("measured pairwise correlation of UNIT cohort P&L "
      f"({_summ['n_common_closed_cohorts']} commonly-closed cohorts):")
print(_corr.to_string(float_format=lambda x: f"{x:6.3f}"))
print()
for k in ("n_eff_per_structure_mean", "n_structures", "mean_pairwise_r", "min_pair",
          "min_pairwise_r", "max_pair", "max_pairwise_r", "k_eff_structures",
          "n_eff_pooled", "n_nominal_pooled", "shortend_n_eff_per_structure"):
    print(f"  {k:30s} {_ne[k]}")
print(f"\n  {_ne['formula']}")

# %% [markdown]
# * **Overlap in time.** Monthly cohorts held one year share ~92% of their holding
#   window. Span 2019-02-01 → 2026-08-03 = 2,740 days = **7.50** non-overlapping
#   one-year observations per structure. (Short end: 2.05. This run has **3.7x**
#   more independent information per structure.)
# * **Overlap across structures.** Measured mean pairwise unit-cohort-P&L
#   correlation **r̄ = 0.698**, from 0.489 (20Yx5Y/25Yx5Y vs 5Y/30Y) to 0.862
#   (30Y/50Y vs 10Yx10Y/20Yx10Y). With `k_eff = k / (1 + (k−1)·r̄)`, four
#   structures are worth **1.29** independent ones.
# * **Pooled: `7.50 × 1.29 = 9.7`.** Not 352.
#
# The correlation is computed on the **unit** (pure-flattener) P&L, not the stored
# signed P&L — otherwise it would be a property of whichever directions each
# structure happened to trade, and would change when a gate changed.

# %%
_n_eff = int(round(_ne["n_eff_pooled"]))
_bar_eff = tw.expected_max_sharpe_under_null(len(tw.DISTINCT_GATE_MODES), _n_eff)
_bar_nom = tw.expected_max_sharpe_under_null(
    len(tw.DISTINCT_GATE_MODES), int(_gs["n_closed"].max()))
_best_sr = float(_gs["sharpe_per_trade"].max())
_dsr = tw.deflated_sharpe_ratio(_best_sr, _n_eff, sr_benchmark=_bar_eff)

print(f"trials (distinct gate modes, ex ante):     {len(tw.DISTINCT_GATE_MODES)}")
print(f"n_eff used:                                {_n_eff}   (nominal n_closed = {int(_gs['n_closed'].max())})")
print(f"E[max Sharpe | null] at NOMINAL n:         {_bar_nom:.4f}   <- the flattering version")
print(f"E[max Sharpe | null] at EFFECTIVE n:       {_bar_eff:.4f}   <- the honest one")
print(f"best gate ({_best}) Sharpe per cohort:  {_best_sr:.4f}")
print(f"beats the null?                            {_best_sr > _bar_eff}")
print(f"deflated Sharpe (P beats that benchmark):  {_dsr:.4f}")
assert not (_best_sr > _bar_eff)

# %%
print(_gs[["gate_mode", "n_closed", "n_eff_independent", "net_bp_mean", "hit_rate",
           "sharpe_per_trade", "t_stat_nominal", "t_stat_overlap_adj"]]
      .to_string(index=False, float_format=lambda x: f"{x:10.4f}"))

# %% [markdown]
# ### The bottom line on the P&L, stated at the right sample size
#
# The long-end books **are** profitable — `swaption_only` returns +7.10 bp per
# cohort with a 64.1% hit rate. But:
#
# * the **overlap-adjusted t is 0.66**, not the nominal 4.13. The nominal statistic
#   divides by √290 when the sample contains ~10 independent observations;
# * the best of four gates scores Sharpe **0.242** against an expected maximum
#   under the null of **0.333**. **It does not clear the bar.** Four zero-edge
#   strategies scored on 10 observations would be expected to produce a best
#   Sharpe of 0.333 by chance alone;
# * the deflated Sharpe — the probability the observed 0.242 beats that benchmark
#   — is **0.395**, i.e. worse than a coin flip.
#
# Note how much the choice of `n` matters: at the *nominal* 290 cohorts the null
# bar would be 0.062 and the best gate would clear it by 4x. That version would be
# wrong, and it is exactly the mistake `n_eff` exists to prevent.
#
# **No gate mode is recommended by this study.** The differences between them
# (7.104 / 7.057 / 6.789 bp per cohort) are far inside the noise, and the ranking
# among them is not evidence.


# %% [markdown]
# ## 13. VERDICT

# %%
_verdict = tw.longend_verdict(three, basis, sweep=_sweep, books=books,
                              cohorts=cohorts, cfg=CFG)
print(_verdict["listed_information"]["verdict"])

# %%
print(json.dumps({
    "coverage": {k: _verdict["coverage"][k] for k in
                 ("n_dates", "dates_all_three", "intersection_window", "rows_all_three")},
    "identity_both_equals_cheapest": _verdict["identity_both_equals_cheapest"],
    "flip_retest": _verdict["flip_retest"],
    "listed_information": {k: v for k, v in _verdict["listed_information"].items()
                           if k != "verdict"},
    "sample_size": {k: _verdict["sample_size"][k] for k in
                    ("n_eff_per_structure_mean", "mean_pairwise_r", "k_eff_structures",
                     "n_eff_pooled", "n_nominal_pooled")},
    "n_trials_used_for_correction": _verdict["n_trials_used_for_correction"],
    "expected_max_sharpe_under_null_effective": _verdict["expected_max_sharpe_under_null_effective"],
    "best_gate_mode": _verdict["best_gate_mode"],
    "best_gate_sharpe_per_trade": _verdict["best_gate_sharpe_per_trade"],
    "best_gate_beats_null": _verdict["best_gate_beats_null"],
    "best_gate_deflated_sharpe": _verdict["best_gate_deflated_sharpe"],
}, indent=1, default=str))

# %% [markdown]
# ---
#
# ## The answer, in five parts
#
# **1. The hypothesis is backwards, and now on 7.5 years of the right structures.**
# The brief asked whether swaptions were the *expensive* comparison that made
# long-end flatteners look cheap. They are the **cheap** one. The OTC−listed basis
# is **negative at all twelve benchmarks** (−0.195 to −0.859 bp/day), so
# substituting the exchange makes the curve look cheaper still. The three forward
# flatteners are cheap gamma against every listed benchmark on **100.0%** of
# 1,854 (or 1,614) days — identical to their 100% against 1Yx30Y swaptions.
#
# **2. The factor-of-10 becomes a factor of 3.4 — and that is a real sector
# difference.** On 5Y/30Y, the only unsaturated structure, the median |basis|
# roughly doubled (0.271 → 0.556 bp/day) while the flip threshold fell by about a
# third (2.721 → 1.917), so the shortfall multiple compresses **10.02 → 3.45**.
# The disagreement rate roughly doubles in step: **1.59% → 3.34%**. The long end
# genuinely is a different market, and the listed benchmark is measurably closer to
# mattering here than it was in the short end.
#
# **3. It still does not decide anything.** 3.34% is below the 5% materiality bar
# the short-end study set. Three of the four structures disagree on exactly
# **0.00%** of days, their ranking never changes once in 1,854 days, and the
# listed veto stood aside on **4 of 352** cohorts for **−0.046 bp per cohort**
# against a per-cohort σ of 29.3. The only benchmarks that push disagreement past
# 5% are the deliberately-wrong **TY control** at 60 and 90 days — a sector
# mismatch, not a signal.
#
# **4. The cheap-share is saturated, so it is weak evidence about a benchmark.**
# 30Y/50Y is `always_cheap` on 84.9% of days: it carries positively and is
# therefore cheap against *any* vol. The comparison never binds there, and the
# information lives in the basis, the gap and 5Y/30Y.
#
# **5. The P&L is an illustration and fails its own test.** 7.50 effective
# observations per structure, 9.7 pooled after a **measured** r̄ = 0.698 haircut.
# The best of four gates scores 0.242 against an expected-max-under-null of
# **0.333** and does not clear it; the overlap-adjusted t is **0.66**. No gate mode
# is recommended.
#
# ### What would change the answer
#
# The one measurement that could: a **strike-level** UST futures-option panel. This
# study compares ATM to ATM. The listed skew and the swaption skew are set by
# genuinely different flows, and the basis in the *wings* could be several times
# the 0.556 bp/day ATM basis measured here — which is the regime in which the
# shortfall multiple would fall below 1 and the listed benchmark would start
# deciding. No offline UST smile history exists (`listed_vol.load_ust_panel`
# measured 8 cached smiles on 2 dates), and building one is a per-strike crawl.
