# %% [markdown]
# # Strategy 1, three ways, on **real listed contracts**
#
# The same long-gamma exposure is available from three places, and all three
# reduce to a normal volatility in **bp/day**:
#
# | source | the number |
# |---|---|
# | **CURVE** | the flattener's **breakeven vol** — how much daily normal vol must be realised for the convexity to pay for the carry |
# | **SWAPTION** | **1Yx30Y ATMF normal vol** from the Citi Velocity cube — J.P. Morgan's own node |
# | **LISTED** | the **ABPV of a deliverable UST option** — `USZ26`, selected each day as the contract whose expiry is nearest the curve horizon |
#
# The third row is what is new. The constant-maturity run put `US_30` there: an
# interpolation across the expiry ladder, fixed at 30 days, 335 days short of the
# horizon, with no strikes and no expiry. This run puts a **contract** there.
#
# ## The three questions, and why the third is the one that matters
#
# 1. **Does the ranking change, and do the two curve-vs-vol signals disagree?**
#    If they never disagree the listed leg adds nothing and this notebook should
#    say so plainly.
# 2. **The swaption-minus-listed basis as its own series** — a real traded spread
#    (buy listed gamma, sell OTC gamma).
# 3. **The factor-of-10 retest.** The short-end (SFR) study concluded "listed adds
#    essentially nothing", and the load-bearing number was a *ratio*: the median
#    |OTC−listed basis| was **0.271 bp/day** against a **2.721 bp/day** threshold
#    to flip a quarter of days — a factor of **10.0**, so the two benchmarks
#    *arithmetically could not* often disagree. §6 recomputes that ratio with the
#    identical formula against a real contract, and against the CM control, so the
#    three are like-for-like.
#
# ## What is honest about the sample, up front
#
# The intersection is **1,854 dates** (2019-01-02 .. 2026-08-11) — the swaption
# cube is the binding constraint, not the contracts, which cover every one of the
# 1,901 curve dates. Cohorts are **monthly one-year holds**, so each structure
# contains **7.50 non-overlapping observations**, not 88, and the four structures
# are **not** four independent bets: their measured pairwise cohort-P&L
# correlation is **0.698**, giving ~1.29 effective structures and **9.70 pooled
# effective observations**. Every Sharpe below is quoted against
# `E[max Sharpe under the null]` evaluated at that count.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import json
import math
import pathlib
import sys
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

_REPO = (pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir()
         else pathlib.Path.cwd().parents[2])
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import strat1_real_contracts as rc
from RVUtils.ConvexityRV import strat1_threeway as tw

warnings.filterwarnings("ignore", category=RuntimeWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 80)
print("repo     ", _REPO)
print("artifacts", DATA)

# %% [markdown]
# ## 1. CONFIG
#
# The study's knobs live in `tw.longend_config()` — **identical** to the
# constant-maturity run's, deliberately: the gate books are derived from strategy
# 1's own stored cohort tables, so the same cost, the same one-day signal lag and
# the same one-year horizon are mandatory or the two runs are not comparable. The
# ONLY thing that differs between the CM run and this one is which column
# `listed_atm_bp_day` was filled from.

# %%
@dataclass(frozen=True)
class NBConfig:
    panel: str = "strat1_contracts_panel.parquet"
    cm_control: str = "strat1_contracts_cm_control.parquet"
    basis: str = "strat1_threeway_contracts_basis.parquet"
    books: str = "strat1_threeway_contracts_books.parquet"
    sweep: str = "strat1_threeway_contracts_sweep.csv"
    verdict: str = "strat1_threeway_contracts_verdict.json"
    #: Pre-specified headline, fixed in the module. Its constant-maturity twin
    #: uses the SAME root, so §5 isolates "contract vs interpolation".
    headline: str = f"{rc.HEADLINE_ROOT}@{rc.HEADLINE_TARGET}"
    cm_headline_root: str = rc.HEADLINE_ROOT
    cm_headline_days: int = 30
    #: The only structure whose verdict is not saturated.
    focus: str = "5Y/30Y"


NB = NBConfig()
CFG = tw.longend_config()
print(json.dumps({k: str(v) for k, v in dataclasses.asdict(CFG).items()}, indent=1))
print("\ngate modes           ", tw.GATE_MODES)
print("DISTINCT gate modes  ", tw.DISTINCT_GATE_MODES,
      "  <- the trial count for the multiple-testing correction")

# %% [markdown]
# ## 2. Build the frames — and prove the two runs are aligned
#
# `swaption_only` does not touch the listed benchmark. It must therefore be
# **exactly identical** between the real run and the CM control. That is the
# alignment check that licenses every other number in §5: a non-zero difference
# there would mean the two frames are not on the same rows and nothing else could
# be read.

# %%
panel = pd.read_parquet(DATA / NB.panel)
cm_panel = pd.read_parquet(DATA / NB.cm_control)
for df in (panel, cm_panel):
    df["date"] = pd.to_datetime(df["date"])

frames = rc.real_threeway_frames(panel, CFG)
three = frames[NB.headline]
cm_sel = tw.select_longend_benchmark(cm_panel, role=None, root=NB.cm_headline_root,
                                     cm_days=NB.cm_headline_days)
three_cm = tw.threeway_frame(cm_sel, CFG)
print("real benchmarks:", sorted(frames))
print(f"headline {NB.headline}: {three.shape};  CM control "
      f"{NB.cm_headline_root}_{NB.cm_headline_days}: {three_cm.shape}")

gate_tbl = rc.cm_vs_real_gate_table(three_cm, three)
assert (gate_tbl["frac_differs_swaption_only"].to_numpy(float) == 0.0).all(), (
    "swaption_only must be identical across the two runs -- it never reads the "
    "listed benchmark, so any difference means the frames are misaligned")
print("\nALIGNMENT ok: swaption_only is bit-identical across the two runs "
      f"({int(gate_tbl.loc[gate_tbl.structure == 'POOLED', 'n_days'].iloc[0]):,} rows).")

ident = tw.assert_both_equals_cheapest(three)
assert ident["identical"], ident
print(f"IDENTITY ok: `both` == `cheapest` on all {ident['n_rows']:,} rows, computed by "
      "two independent expressions (an AND over the two signals vs a comparison "
      "against min/max).")

# %% [markdown]
# ## 3. The intersection window — before any three-way statistic
#
# The three series have different coverage and a three-way number quoted off
# anything but their intersection is wrong by construction.

# %%
cov = tw.intersection_report(three)
cov_cm = tw.intersection_report(three_cm)
print(json.dumps(cov, indent=1))
print()
print(f"real   : {cov['rows_listed_ok']:,} listed-ok rows, {cov['rows_all_three']:,} usable, "
      f"{cov['dates_all_three']:,} dates")
print(f"CM ctrl: {cov_cm['rows_listed_ok']:,} listed-ok rows, {cov_cm['rows_all_three']:,} usable, "
      f"{cov_cm['dates_all_three']:,} dates")
assert cov["dates_all_three"] == cov_cm["dates_all_three"], (
    "the two runs must share their intersection or §5 is comparing windows")
print(f"\nThe binding constraint is the SWAPTION cube "
      f"({cov['rows_swaption_ok']:,} of {cov['n_rows']:,} rows), not the contracts, which "
      f"cover all {cov['rows_listed_ok']:,}. Intersection window "
      f"{cov['intersection_window'][0]} .. {cov['intersection_window'][1]}.")

# %% [markdown]
# ## 4. Ranking, transitions and agreement
#
# `frac_cheapest_curve` is "how often was the curve the cheapest of the three".
# `frac_disagree` is the whole "is this a relabelling of strategy 1" question as
# a number.

# %%
ranks = tw.rank_table(three)
print(ranks.to_string(index=False))
print()
print(tw.transition_table(three).to_string(index=False))
print()
agree = tw.agreement_table(three)
print(agree[["structure", "n_days", "frac_disagree", "n_disagree", "frac_both_cheap",
             "frac_swaption_cheap_listed_rich", "frac_swaption_rich_listed_cheap",
             "frac_gate_differs_from_swaption", "median_basis_bp_day"]].to_string(index=False))

pooled = agree.set_index("structure").loc["POOLED"]
foc = agree.set_index("structure").loc[NB.focus]
print(f"\nThe curve is the cheapest of the three sources on "
      f"{ranks.set_index('structure').loc['POOLED', 'frac_cheapest_curve']:.1%} of pooled "
      f"rows. The two curve-vs-vol signals disagree on {pooled.frac_disagree:.2%} pooled "
      f"and {foc.frac_disagree:.2%} on {NB.focus}.")

# %%
fig = go.Figure()
for name, col in (("curve", "frac_cheapest_curve"), ("swaption", "frac_cheapest_swaption"),
                  ("listed", "frac_cheapest_listed")):
    fig.add_trace(go.Bar(x=ranks.structure, y=ranks[col], name=name))
fig.update_layout(barmode="stack", height=400, template="plotly_white",
                  title=f"Which source was the cheapest gamma — {NB.headline}",
                  yaxis_title="fraction of usable days")
fig.show()

# %% [markdown]
# ## 5. **Did the real contract change what trades?**
#
# The operational half of "was constant maturity an adequate proxy". Both frames
# carry identical curve and swaption columns on identical rows.

# %%
print(gate_tbl[["structure", "n_days", "frac_differs_swaption_only",
                "frac_differs_listed_only", "frac_differs_both", "n_differs_both",
                "frac_cheapest_changes", "median_listed_diff_bp_day"]].to_string(index=False))
GT = gate_tbl.set_index("structure")
print(f"\nThe real contract prices {GT.loc['POOLED', 'median_listed_diff_bp_day']:+.3f} bp/day "
      "more vol than the 30-day constant maturity, and that moves the `both` gate on "
      f"{GT.loc['POOLED', 'frac_differs_both']:.2%} of pooled rows "
      f"({int(GT.loc['POOLED', 'n_differs_both'])} of {int(GT.loc['POOLED', 'n_days']):,}) -- "
      f"all of them on {NB.focus} ({GT.loc[NB.focus, 'frac_differs_both']:.2%}), because the "
      "other three structures are saturated and no benchmark can move them.")
assert GT.loc["POOLED", "n_differs_both"] > 0, (
    "if the real contract changed NOTHING the honest headline is 'CM is a perfect "
    "proxy' -- which is a different notebook from this one")

# %% [markdown]
# ## 6. **The factor-of-10 retest** — question (c), like for like
#
# `flip_p25` is the 25th percentile of |curve − swaption|: the basis needed to
# flip a quarter of days. `shortfall_multiple_p25 = flip_p25 / median |basis|`.
# Large means the basis is *arithmetically* too small to change the verdict.
#
# **Read `frac_curve_at_sentinel` first.** Where it is large the threshold is
# inflated by SATURATION, not by the two markets agreeing: with the breakeven
# pinned at the `always_cheap` sentinel `0.0`, |curve − swaption| degenerates to
# the swaption level itself (~4-5 bp/day) and the ratio says nothing. Only
# **5Y/30Y** binds.

# %%
flip_real = tw.flip_threshold_table(three)
flip_cm = tw.flip_threshold_table(three_cm, include_reference=False)
cols = ["structure", "n_days", "median_abs_basis_bp_day", "flip_p25_bp_day",
        "shortfall_multiple_p25", "frac_curve_at_sentinel", "frac_disagree"]
print("REAL CONTRACT (US@H365)")
print(flip_real[cols].to_string(index=False))
print("\nCONSTANT MATURITY CONTROL (US_30)")
print(flip_cm[cols].to_string(index=False))

r = flip_real.set_index("structure").loc[NB.focus]
c = flip_cm.set_index("structure").loc[NB.focus]
ref = tw.SHORT_END_REFERENCE
print(f"""
LIKE-FOR-LIKE, on {NB.focus} (the only structure that binds):

                        median |basis|   flip p25   ratio    disagree
  SFR short end (prior)     {ref['median_abs_basis_bp_day']:.3f}        {ref['basis_needed_to_flip_25pct_bp_day']:.3f}     {ref['basis_shortfall_multiple']:5.2f}    {ref['frac_rows_disagree']:.2%}
  long end, CM control      {c.median_abs_basis_bp_day:.3f}        {c.flip_p25_bp_day:.3f}     {c.shortfall_multiple_p25:5.2f}    {c.frac_disagree:.2%}
  long end, REAL contract   {r.median_abs_basis_bp_day:.3f}        {r.flip_p25_bp_day:.3f}     {r.shortfall_multiple_p25:5.2f}    {r.frac_disagree:.2%}

The flip threshold is IDENTICAL across the two long-end rows -- it depends only on
|curve - swaption|, which the substitution does not touch -- so the whole move is the
basis widening by {(r.median_abs_basis_bp_day / c.median_abs_basis_bp_day - 1) * 100:.0f}%.
""")
assert abs(r.flip_p25_bp_day - c.flip_p25_bp_day) < 1e-9, (
    "the flip threshold must not move: it never reads the listed benchmark")
assert r.shortfall_multiple_p25 < c.shortfall_multiple_p25 < ref["basis_shortfall_multiple"]

# %%
fig = go.Figure()
lbl = ["SFR short end<br>(prior study)", "long end<br>CM control", "long end<br>REAL contract"]
fig.add_trace(go.Bar(x=lbl, y=[ref["basis_shortfall_multiple"], c.shortfall_multiple_p25,
                               r.shortfall_multiple_p25],
                     marker_color=["#7f7f7f", "#ff7f0e", "#1f77b4"],
                     text=[f"{v:.2f}x" for v in (ref["basis_shortfall_multiple"],
                                                 c.shortfall_multiple_p25,
                                                 r.shortfall_multiple_p25)],
                     textposition="outside"))
fig.add_hline(y=1.0, line=dict(color="#d62728", dash="dash"),
              annotation_text="1.0 = the basis is as big as the threshold")
fig.update_layout(height=430, template="plotly_white",
                  title=f"How far the OTC-listed basis is from mattering — {NB.focus}",
                  yaxis_title="flip threshold / median |basis|")
fig.show()

# %% [markdown]
# ## 7. The basis as its own series
#
# Positive means the OTC 1Yx30Y swaption prices MORE vol than the exchange
# contract. On the long end it is **negative almost everywhere** — the opposite
# sign to the short end's +0.251 — which means substituting the exchange
# benchmark makes the curve look *cheaper still* rather than correcting an
# expensive comparison.

# %%
basis = pd.read_parquet(DATA / NB.basis)
basis["date"] = pd.to_datetime(basis["date"])
hb = basis[basis.listed_symbol == NB.headline]
print(tw.basis_persistence(basis)[
    ["listed_symbol", "n", "first", "last", "median_bp_day", "median_abs_bp_day",
     "std_bp_day", "frac_positive", "rho_1", "rho_21", "rho_63",
     "ar1_half_life_days", "mean_sign_run_days"]].to_string(index=False))
print()
print(tw.basis_regime_table(basis, symbols=[NB.headline]).to_string(index=False))
p = tw.basis_persistence(basis).set_index("listed_symbol").loc[NB.headline]
assert p.median_bp_day < 0, (
    "the long-end basis is negative -- if this flips sign the narrative above is stale")
print(f"\n{NB.headline}: median basis {p.median_bp_day:+.3f} bp/day, negative on "
      f"{1 - p.frac_positive:.1%} of {int(p.n):,} days. AR(1) half-life "
      f"{p.ar1_half_life_days:.1f} business days, but rho_63 = {p.rho_63:.3f} -- a slow "
      "component an AR(1) cannot see, which the regime table shows is the 2022-23 "
      "rate-vol shock.")

# %%
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                    row_heights=[0.6, 0.4],
                    subplot_titles=("1Yx30Y swaption minus listed, bp/day",
                                    "Real contract vs CM control"))
cmb = basis[basis.listed_symbol.isin([NB.headline])]
fig.add_trace(go.Scatter(x=hb.date, y=hb.basis_bp_day, name=f"{NB.headline}",
                         line=dict(color="#1f77b4", width=1.1)), row=1, col=1)
# the CM control's own basis, from the control panel
cmc = cm_panel[cm_panel.listed_symbol == f"{NB.cm_headline_root}_{NB.cm_headline_days}"] \
    .drop_duplicates("date").sort_values("date")
fig.add_trace(go.Scatter(x=cmc.date, y=cmc.otc_minus_listed_bp_day,
                         name=f"{NB.cm_headline_root}_{NB.cm_headline_days} (control)",
                         line=dict(color="#7f7f7f", width=1.0, dash="dot")), row=1, col=1)
fig.add_hline(y=0.0, line=dict(color="#d62728", dash="dash"), row=1, col=1)
m = hb[["date", "basis_bp_day"]].merge(cmc[["date", "otc_minus_listed_bp_day"]], on="date")
fig.add_trace(go.Scatter(x=m.date, y=m.basis_bp_day - m.otc_minus_listed_bp_day,
                         name="real - CM", line=dict(color="#9467bd", width=1.0)), row=2, col=1)
fig.update_yaxes(title_text="bp/day", row=1, col=1)
fig.update_yaxes(title_text="bp/day", row=2, col=1)
fig.update_layout(height=620, template="plotly_white",
                  title="The OTC-listed basis — a real traded spread")
fig.show()

# %% [markdown]
# ## 8. Gate books — **illustration, not evidence**
#
# Every gate mode is scored on **bit-identical cohort P&L**, derived
# arithmetically from strategy 1's own stored cohort tables rather than by one
# engine pass per mode. Swap NPV is linear in `bpv` and the unwind fee does not
# depend on direction, so the identity is exact — and it is *verified* against a
# fresh engine run by `_strat1_threeway_longend_build.py verify`, not assumed.
#
# Read `n_eff_independent`, not `n_closed`. 300 cohorts is **7.5** independent
# observations.

# %%
books = pd.read_parquet(DATA / NB.books)
gs = tw.gate_summary(books, CFG)
print(gs.to_string(index=False))

verdict = json.loads((DATA / NB.verdict).read_text())
n_eff = verdict["sample_size"]["n_eff_pooled"]
e_max = verdict["expected_max_sharpe_under_null_effective"]
best = verdict["best_gate_sharpe_per_trade"]
print(f"""
SAMPLE SIZE, measured not assumed
  n_eff per structure      {verdict['sample_size']['n_eff_per_structure_mean']:.2f}   (2,740 days / 365.25 / 1y hold)
  mean pairwise cohort r   {verdict['sample_size']['mean_pairwise_r']:.3f}   ({verdict['sample_size']['min_pair']} {verdict['sample_size']['min_pairwise_r']:.3f} .. {verdict['sample_size']['max_pair']} {verdict['sample_size']['max_pairwise_r']:.3f})
  k_eff structures         {verdict['sample_size']['k_eff_structures']:.2f}   (of 4)
  n_eff POOLED             {n_eff:.2f}   against {verdict['sample_size']['n_nominal_pooled']} nominal cohorts
  short-end reference      {verdict['sample_size']['shortend_n_eff_per_structure']:.2f} per structure

MULTIPLE TESTING, at {len(tw.DISTINCT_GATE_MODES)} distinct gate modes
  E[max Sharpe | null], nominal n   {verdict['expected_max_sharpe_under_null_nominal']:.3f}
  E[max Sharpe | null], EFFECTIVE   {e_max:.3f}
  best gate ({verdict['best_gate_mode']})            {best:.3f}
  beats the null?                   {verdict['best_gate_beats_null']}
  deflated Sharpe                   {verdict['best_gate_deflated_sharpe']:.3f}
""")
assert not verdict["best_gate_beats_null"], (
    "if the best gate ever clears E[max under null] at n_eff, this section needs "
    "rewriting into a positive claim rather than a caveat")
print(f"The best of the {len(tw.DISTINCT_GATE_MODES)} gates has a per-cohort Sharpe of "
      f"{best:.3f} against {e_max:.3f} expected from the BEST of four zero-edge strategies "
      f"at {n_eff:.1f} effective observations. It does not clear its own null. No P&L claim "
      "is made from this table.")

# %%
fig = go.Figure()
for mode, gbk in books[books.gate_closed].groupby("gate_mode"):
    s = gbk.sort_values("entry")
    fig.add_trace(go.Scatter(x=s.entry, y=s.gate_net_bp.cumsum(), mode="lines", name=mode))
fig.update_layout(height=440, template="plotly_white",
                  title="Cumulative net P&L by gate mode — identical cohorts, only the gate differs",
                  xaxis_title="cohort entry", yaxis_title="cumulative net bp of package DV01")
fig.show()

# %% [markdown]
# ### Did adding the listed veto do anything?

# %%
li = verdict["listed_information"]
print(json.dumps({k: v for k, v in li.items() if k != "verdict"}, indent=1))
print(f"\nAdding the listed benchmark as a veto on top of the swaption signal stood aside "
      f"on {li['cohorts_the_listed_veto_stood_aside_on']} of {li['cohorts_total']} cohorts and "
      f"moved the mean outcome by {li['gate_both_minus_swaption_only_bp_per_cohort']:+.3f} bp "
      "per cohort. Against a real contract, as against constant maturity, the listed leg "
      "is not carrying operational information.")

# %% [markdown]
# ## 9. Robustness — eight benchmarks, not eight trials
#
# Two roots x four expiry targets. All eight score the same four gate modes
# against a different benchmark, so counting them in the multiple-testing
# correction would inflate the trial count eightfold for no new degree of freedom.

# %%
sweep = pd.read_csv(DATA / NB.sweep)
print(sweep[sweep.structure == NB.focus][
    ["benchmark", "listed_root", "listed_target", "n_days", "frac_cheapest_curve",
     "frac_disagree", "median_basis_bp_day", "median_abs_basis_bp_day",
     "flip_p25_bp_day", "shortfall_multiple_p25", "is_headline"]].to_string(index=False))
f = sweep[sweep.structure == NB.focus]
print(f"\n{NB.focus} across the eight: disagreement {f.frac_disagree.min():.2%} .. "
      f"{f.frac_disagree.max():.2%} (headline "
      f"{f[f.is_headline].frac_disagree.iloc[0]:.2%}); shortfall multiple "
      f"{f.shortfall_multiple_p25.min():.2f} .. {f.shortfall_multiple_p25.max():.2f} "
      f"(headline {f[f.is_headline].shortfall_multiple_p25.iloc[0]:.2f}).")
print("Every one of the eight is below the short end's 10.02, and every one is above 1.0 "
      "-- the basis is closer to mattering than it was in the short end, and still not "
      "big enough to decide anything on its own.")

# %%
fig = go.Figure()
for root in sorted(set(f.listed_root)):
    g = f[f.listed_root == root].sort_values("shortfall_multiple_p25")
    fig.add_trace(go.Bar(x=g.benchmark, y=g.shortfall_multiple_p25, name=root))
fig.add_hline(y=tw.SHORT_END_REFERENCE["basis_shortfall_multiple"],
              line=dict(color="#7f7f7f", dash="dot"),
              annotation_text="SFR short end, 10.02x")
fig.add_hline(y=1.0, line=dict(color="#d62728", dash="dash"))
fig.update_layout(height=420, template="plotly_white", barmode="group",
                  title=f"{NB.focus}: shortfall multiple at all eight real benchmarks",
                  yaxis_title="flip p25 / median |basis|")
fig.show()

# %% [markdown]
# ## 10. Verdict

# %%
print(verdict["listed_information"]["verdict"])
print()
print("FLIP RETEST")
print(json.dumps(verdict["flip_retest"], indent=1))

# %% [markdown]
# ### The three answers
#
# `cm_control` in the verdict JSON carries the full per-structure comparison.

# %%
cmv = pd.DataFrame(verdict["cm_control"]["per_structure"]).set_index("structure")
pool = cmv.loc["POOLED"]
foc_c = cmv.loc[NB.focus]
print(f"""
(a) CHEAP-SHARE AGAINST A REAL CONTRACT
    The curve is cheap gamma against the deliverable contract on 100.0% of days on
    three of the four long-end structures and on {foc_c.cheap_share_real:.1%} of days on
    {NB.focus}. The premise survives the substitution: the 100% was a property of the
    curve's own carry, not of the swaption being an expensive benchmark.

(b) DOES THE CM-vs-REAL DIFFERENCE CHANGE ANY VERDICT?
    Not on the saturated three (0 of {int(cmv.loc['30Y/50Y', 'n_days']):,} days each). On
    {NB.focus} it changes the cheap/rich verdict on {foc_c.frac_signal_differs:.2%} of days
    ({int(foc_c.n_signal_differs)} of {int(foc_c.n_days):,}), and the `both` gate on
    {GT.loc[NB.focus, 'frac_differs_both']:.2%}. Constant maturity was an ADEQUATE PROXY FOR THE
    VERDICT and a BIASED PROXY FOR THE LEVEL -- it understated the listed benchmark by
    {pool.median_listed_diff_bp_day:.3f} bp/day because it is pinned 335 days short of the
    horizon while the real contract sits {pool.median_tte_days_real:.0f} days out.

(c) IS THE OTC-LISTED BASIS BIG ENOUGH TO MATTER?
    Like for like with the short end's 0.271 vs 2.721 (factor 10.0):
    against a real contract the long-end basis is {r.median_abs_basis_bp_day:.3f} bp/day
    against a {r.flip_p25_bp_day:.3f} bp/day threshold -- a factor of
    {r.shortfall_multiple_p25:.2f}, a {ref['basis_shortfall_multiple'] / r.shortfall_multiple_p25:.1f}-fold
    compression. Moving from CM to a real contract widened the basis by
    {(r.median_abs_basis_bp_day / c.median_abs_basis_bp_day - 1) * 100:.0f}% at an unchanged threshold,
    taking the ratio from {c.shortfall_multiple_p25:.2f} to {r.shortfall_multiple_p25:.2f}.
    So: BIGGER than the short end by a factor of 4, still not big enough -- the
    signals disagree on {r.frac_disagree:.2%} of days and the listed veto moved
    {li['cohorts_the_listed_veto_stood_aside_on']} of {li['cohorts_total']} cohorts.
""")

# %% [markdown]
# ## 11. Honest limits
#
# * **The intersection is 1,854 dates and ~9.7 pooled effective observations.**
#   Every distributional statement survives that; the gate P&L does not, and the
#   best gate does not clear its own multiple-testing null (0.250 against 0.333).
# * **The expiry is still not matched.** The horizon-selected contract sits a
#   median 232 days short of the one-year horizon. Both sides are annualised and
#   divided by `sqrt(252)`, which removes the horizon to first order but not
#   exactly — and the measured listed term structure runs ~6% from 30 to 200 days,
#   in the direction that makes the curve look cheaper.
# * **UL and TN are not listed contracts.** On two of the four structures the
#   sector-correct root exists only as constant maturity; the measured cost of the
#   substitution is 0.345 bp/day, again in the flattering direction.
# * **Three of four structures cannot answer the question.** Their verdict is
#   saturated at 100% against every benchmark, so their 0.00% disagreement is
#   arithmetic, not agreement between markets. The study rests on 5Y/30Y.

# %%
print("done.")
