# %% [markdown]
# # The same question, a different judge, and eighteen more years
#
# `fed_sentiment_lead.ipynb` measured JWS Macro #8's claim — an equal-weight
# inflation + labour surprise composite, pushed forward five weeks, leading a
# Fed sentiment index — and answered: **not five weeks, 11–14, and it does not
# clear a null that respects how persistent both series are.** That study ran on
# the JPM NLP corpus, whose point-in-time window is **147 weekly observations**.
#
# This notebook re-runs it on **FedLock V3**: ~4,000 Fed speeches scored by a
# pairwise TrueSkill tournament with Llama 3.3 70B as judge, 1985 to today.
# Overlapped with Citi's daily surprise indices that is **1,133 weekly
# observations — 7.7× the first study's sample** — on a completely independent
# sentiment model.
#
# **The estimator, the frozen config and every gate are imported unchanged from
# the first study.** Nothing is re-tuned. So any difference in the answer is
# attributable to the data, which is the entire point.
#
# ## What was measured — the numbers up front
#
# *(Every figure here is restated by a cell below. If the cells and this summary
# ever disagree, the cells are what ran.)*
#
# 1. **The first study's number replicates on a different model — on the same
#    window.** FedLock over 2023-05→2026-08 gives levels **+11w, r 0.744,
#    p 0.082**, against the JPM corpus's **+13w, r 0.737, p 0.096**. Two
#    unrelated scoring models, same window, same estimator, same answer. The
#    +11–13 week result was **not** an artefact of JPM's scoring.
# 2. **And it does not survive the other eighteen years.** Same series, same
#    config, 2004-12→2026-08: the levels argmax is +9w with **r 0.0606**,
#    **p 0.4105**, and a paired plateau covering **all 27 lags**. Going from 147
#    weeks to 1,133 collapses the levels correlation from **0.744 to 0.0606**.
# 3. **The recent window is the most favourable three years in two decades.**
#    The 3-year rolling correlation at +11w has median 0.131 and runs from
#    **−0.459 to +0.783**; by year it is −0.19 in 2017 and **+0.73 in 2026**.
#    The first study measured this relationship at its historical maximum.
# 4. **What does survive twenty-one years is +2 weeks, and it is small.** In
#    weekly changes the argmax is **+2w, r 0.122, p 0.0027** — exact over 1,105
#    rotations — with a **one-lag plateau**, the tightest in either study.
#    Era-adjusted scores give the same **+2w** (r 0.1029, p 0.0027). At five
#    weeks the correlation is **−0.0053**. The test behind that p is calibrated
#    **at this sample's length**, not study 1's: 1 rejection in 40 at a nominal
#    5% = **2.5%**, so the null is conservative here rather than inflated. It
#    also survives Bonferroni across this notebook's six primary cells
#    (**0.0163**), and a Wednesday week anchor moves the spike only to **+1w**
#    (r 0.093, p 0.0018) — inside the "one to two weeks" this is described as.
# 5. **Net of the pipeline's own offset, that is about one week.** G6 re-run at
#    FedLock's 2.52 speeches/week returns a zero-lead argmax of **+1w** in
#    changes. So +2w measured − ~1w filter ≈ **one week of genuine lag** — a
#    speech-writing lag, not a forecastable lead. The Fed talks about last
#    week's data.
# 6. **The stable relationship is the one that has faded.** The +2w link is
#    positive in **85%** of 3-year rolling windows and ran ~+0.20 through
#    2010–2022 — but reads **−0.09 in 2025 and −0.05 in 2026**. The
#    historically robust effect is currently absent; the currently strong one is
#    historically absent. They are mirror images.
# 7. **No sub-period is significant.** Five ~4-year blocks: levels argmax +9,
#    +11, −13, +13, +13; changes +9, +2, −13, +2, +13; p from **0.052 to 0.852**.
#    The +2w result needs the pooled sample to be visible at all.
# 8. **Cross-model agreement is moderate, not high.** On the 372 speeches both
#    corpora scored: **r 0.656** (Spearman 0.620) at the speech level and
#    **0.677** at the index level — about **43% shared variance**. Two systems
#    that both claim to measure "how hawkish was this speech" agree on well under
#    half of it, so a lead measured on either is materially a property of the
#    model as well as of the Fed.
# 9. **Changing the judge moves the whole history at once.** V2 (Gemini 2.0
#    Flash) → V3 (Llama 3.3 70B): mean |move| **3.545 points = 51% of one
#    standard deviation**, p90 7.36, max 17.08, Spearman **0.828** — which ties
#    out to FedLock's own published ρ = 0.82. The first study's JPM revision was
#    39% of a standard deviation; this is worse, and unlike a vintage it cannot
#    be gated, because it is not a vintage — it is a different model.
# 10. **This dataset can never be point-in-time**, through three separate
#    channels: one global `builtOn` stamp with no row-level date; TrueSkill
#    fitting every rating jointly against speeches from the whole corpus,
#    including the future; and a judge whose training data contains decades of
#    commentary about what the Fed did next. Anonymisation strips names, not
#    hindsight.
# 11. **It does not reach the price, on twenty-one years.** Eighteen
#    signal × horizon cells against the forward 2y SOFR OIS change: **|t| ≤ 1.90,
#    R² ≤ 0.0076**. The largest is era-adjusted at 5 weeks — unadjusted
#    p 0.057, **Bonferroni over 18 cells 1.000**, and the same regressor at 13
#    weeks reads t 0.34.
# 12. **Both models agree about right now.** FedLock's index sits at the **93rd
#    percentile of twenty-two years** (the JPM index was at the 100th percentile
#    of its three), on prints including Hammack 71.02, Kashkari 65.32 and Logan
#    63.49 — while the surprise composite reads −0.373.
#
# **Verdict.** The five-week lead is not there. The eleven-to-thirteen week lead
# is real in 2023–2026 and in no other three-year window in two decades — the
# first study caught it at its maximum, which is why two independent models
# agreed on it. What twenty-one years actually contains is a **one-to-two week
# response lag with r ≈ 0.12**: Fedspeak reacting to data on the timetable you
# would expect from how speeches get written. That has faded to zero over the
# last two years, explains 1.5% of the variance when it is present, and never
# reaches a price.
#
# ## How this pairs with the first study
#
# Neither dataset can answer the question alone, and the reason is worth stating
# plainly because it is the structural fact about this whole research area:
#
# | | JPM NLP corpus | FedLock V3 |
# |---|---|---|
# | point-in-time possible | **yes**, via `pub_date` | **no**, by construction |
# | usable sample | 147 weeks | 1,133 weeks |
# | what it can establish | what was *actionable* | what was *true* |
#
# The first study is tradeable over three years; this one is un-gateable over
# twenty-one. A lead worth holding risk against would have to survive both, and
# this one does not survive either.

# %%
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"

HERE = Path.cwd()
REPO = HERE if (HERE / "MDP").exists() else HERE.parents[1]
for _p in (str(REPO), str(REPO / "notebooks" / "rv")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_sentiment_lead_data as D   # the first study's estimator, UNCHANGED
import fedlock_data as F              # the new input

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 120)

BG, GRID = "#11151c", "#2a3340"
GREY, RED, BLUE, AMBER, GREEN = "#9aa7b8", "#e05353", "#4c9be8", "#e8b44c", "#5cb87a"


def style(fig, height=520, title=None):
    fig.update_layout(
        template="plotly_dark", height=height, title=title,
        paper_bgcolor=BG, plot_bgcolor=BG, margin=dict(l=60, r=60, t=60, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), font=dict(size=12),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


CFG = D.LeadConfig()
LAGS = CFG.lags()
print("The frozen config is imported from the first study and NOT re-tuned.")
print("The one knob that legitimately differs is speech density, which is a")
print("property of the corpus rather than a choice: JPM 3.28/week, FedLock 2.52.")
print("It enters only the G6 calibration, which is re-run below at 2.52.\n")
print(CFG.describe().head(12).to_string(index=False))

# %% [markdown]
# ## 1. The data, and the gate that cannot be built
#
# **G7** is this study's replacement for the first one's G1/G2. There, the
# discipline was gating on `pub_date`. Here there is nothing to gate on, and the
# danger is precisely that the machinery still *has* a `point_in_time` switch:
# flip it and you get a series back, with no error, identical to the
# as-published one. So the absence is asserted rather than assumed, and
# `test_the_point_in_time_switch_is_INERT_on_fedlock` pins it.
#
# **G8** ties FedLock's era-adjusted column out to its published definition,
# `adjusted = raw − quarterly mean + 50`.

# %%
SP, PROV = F.load_speeches()
print("snapshot provenance:")
for k in ("dataset", "url", "fetched", "built_on", "data_through", "n_rows",
          "n_dated", "n_undated", "first", "last"):
    if k in PROV:
        print(f"  {k:14s} {PROV[k]}")

G7 = F.gate_single_vintage(SP, PROV)
print(f"\nG7 passes: {G7['verdict']}")
print(f"  built on {G7['built_on']}, data through {G7['data_through']}, "
      f"{G7['row_level_vintage_fields']} row-level vintage fields")

G8 = F.gate_era_adjustment(SP)
print(f"\nG8 passes: `ma` reconstructs as raw - quarterly mean + 50 at "
      f"corr {G8['corr']:.4f}, mean |resid| {G8['mean_abs_resid']:.3f}, "
      f"max {G8['max_abs_resid']:.3f} over {G8['n']} speeches.")
print("  The residual is not zero because FedLock's quarterly mean is taken over")
print("  ALL speeches including the undated ones this study must drop, which")
print("  cannot be placed in a quarter here.")

print(f"\nundated rows dropped: {PROV['n_undated']} of {PROV['n_rows']} "
      f"({PROV['n_undated']/PROV['n_rows']:.1%}) -- the source gave a bare year")
print(f"  by speaker: {PROV['undated_by_speaker']}")
print(f"  their mean score {PROV['undated_mean_score']:.2f} vs the dated corpus's "
      f"{PROV['dated_mean_score']:.2f}, so the hole is not obviously tilted")
print("  They still took part in the tournament, so the dated speeches' ratings")
print("  were partly fitted against them. That is harmless for timing, which is")
print("  all this study reads, but it is why they cannot simply be called absent.")

# %% [markdown]
# ### Known-answer checks, on the column the claims were made about
#
# FedLock publishes three checkable claims. Two are about the **speaker
# cross-section** and one about the **timeline**. The cross-section claims are
# about the *era-adjusted* Rankings tab, and checking them on raw means produces
# a false failure — raw is dominated by the era a speaker served in, so anyone
# who spoke recently floats to the top and the ZIRP-era hawks sink.

# %%
G_ERA, INFO_ERA = F.known_answer_speaker_ranking(SP, score_column="ma")
_, INFO_RAW = F.known_answer_speaker_ranking(SP, score_column="m")
print(f"{INFO_ERA['n_speakers']} speakers with >= 20 dated speeches\n")
print("published claim: Hoenig most hawkish; Plosser, Fisher, Lacker round out the top five")
for n in ("Hoenig", "Plosser", "Fisher", "Lacker"):
    print(f"  {n:9s} era-adjusted rank {INFO_ERA['hawk_ranks'][n]:2d}   "
          f"raw rank {INFO_RAW['hawk_ranks'][n]:2d}")
print("published claim: Brainard, Raskin, Evans in the bottom quartile")
for n in ("Brainard", "Evans"):
    r = INFO_ERA["dove_ranks"][n]
    print(f"  {n:9s} era-adjusted rank {r:2d}/{INFO_ERA['n_speakers']} "
          f"({'bottom quartile' if r > 0.75*INFO_ERA['n_speakers'] else 'middle'})")
print("  Raskin has fewer than 20 dated speeches and is not testable here.")
print(f"\nhawk/dove pair separation using FedLock's OWN roster:")
print(f"  era-adjusted {INFO_ERA['pair_separation']:.1%}   raw {INFO_RAW['pair_separation']:.1%}")
print(f"  The two inversions are Waller (on the hawk list, rank "
      f"{INFO_ERA['hawk_ranks']['Waller']}) and Bostic (dove list, rank "
      f"{INFO_ERA['dove_ranks']['Bostic']}) -- both 2020s figures, where the corpus")
print("  is dense and the quarterly demeaning does the most work.")

TREND = F.gaussian_trend(SP, score_column="m")
TR = TREND[TREND.index >= "1995-01-01"]
print(f"\npublished claim: the smoothed timeline peaks Q3-2022 and troughs Q2-2020")
print(f"  peak   {TR.idxmax().date()} ({TR.idxmax().to_period('Q')})  {TR.max():.2f}")
print(f"  trough {TR.idxmin().date()} ({TR.idxmin().to_period('Q')})  {TR.min():.2f}")
JH = SP[(SP["date"] >= "2022-08-24") & (SP["date"] <= "2022-08-28")]
print(f"\npublished example: Powell's Aug-2022 Jackson Hole scores 78")
print(f"  V3 gives m = {JH['m'].iloc[0]:.1f} (era-adjusted {JH['ma'].iloc[0]:.1f}). The 78 is a")
print("  V2-era figure; FedLock's own methodology page warns its numbers predate V3.")
print("\nSo the cross-section validates on the published construction and the")
print("timeline reproduces exactly. The timeline is the series this study reads.")

# %% [markdown]
# ### How far the history moves when the judge changes
#
# The first study measured how much the JPM index gets revised: mean 2.65
# sentiment points, 39% of one standard deviation. FedLock's analogue is not a
# revision at all — it is what happens when the **model** is replaced. V2 (the
# frozen Gemini 2.0 Flash run, preserved at `/fedlock/v2/`) against V3.

# %%
V2P = REPO / "notebooks" / "rv" / "fedlock_v2_snapshot.parquet"
if V2P.exists():
    V2 = F.read_snapshot(V2P)
    CV = F.compare_vintages(V2, SP)
    print(f"matched {CV['matched']} speeches ({CV['n_v3']} in V3, {CV['n_v2']} in V2 -- "
          f"V3 removed cross-source duplicates)")
    rows = []
    for c, label in (("m", "raw"), ("ma", "era-adjusted")):
        d = CV[c]
        rows.append({"column": label, "pearson": round(d["pearson"], 4),
                     "spearman": round(d["spearman"], 4),
                     "mean_abs_move": round(d["mean_abs_move"], 3),
                     "p90": round(d["p90_abs_move"], 3), "max": round(d["max_abs_move"], 2),
                     "as_share_of_one_sd": f"{d['move_in_sd']:.1%}"})
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nFedLock publishes rho = 0.82 between the runs; we measure Spearman "
          f"{CV['m']['spearman']:.3f} on raw. That ties out.")
    print("But a rank correlation is the flattering statistic. The level move is")
    print(f"{CV['m']['move_in_sd']:.0%} of one standard deviation for a typical speech, and")
    print("every historical score moves at once, because TrueSkill refits the whole")
    print("graph. There is no vintage to gate on -- only a model to choose.")
else:
    print("v2 snapshot absent; run fedlock_refresh.py to enable the comparison")

# %% [markdown]
# ## 2. Do the two sentiment models even agree?
#
# Before any lead is quoted: if two independent models disagree about which
# speeches were hawkish, a lead measured on either is a property of that model
# as much as of the Fed.

# %%
JPM = D.load_fed_scores(CFG)
CM = F.cross_model_agreement(SP, JPM)
print(f"speeches both corpora scored since {CFG.corpus_start}: {CM['matched']} "
      f"(FedLock has {CM['n_fedlock']} in the window, JPM {CM['n_jpm']})")
for c, label in (("m", "raw"), ("ma", "era-adjusted")):
    d = CM[f"speech_level_{c}"]
    print(f"  FedLock {label:12s} vs JPM hawk_dove_score: "
          f"pearson {d['pearson']:.3f}  spearman {d['spearman']:.3f}")
_r = CM["speech_level_m"]["pearson"]
print(f"\nr = {_r:.3f} is {_r**2:.0%} shared variance -- well under half. Not the")
print("near-identity a reader might assume from two systems that both claim to")
print("measure 'how hawkish was this speech'. Whatever either one measures, a")
print("majority of its variation is not shared with the other.")

# %% [markdown]
# ## 3. The series
#
# Same surprise composite as the first study, read from its committed snapshot.
# Same weekly EWMA sentiment index, same 21-day half-life. Two score columns:
# **raw** (like-for-like with the first study and with JWS's level chart) and
# **era-adjusted**, reported alongside.
#
# One interaction to flag where it belongs, before the numbers: the measured
# lead in the first study was ~13 weeks ≈ one quarter, and era adjustment is
# *quarterly block demeaning*. It removes variation at exactly the frequency the
# hypothesised lead lives at, and it uses within-quarter information. Its weekly
# **changes**, though, are almost untouched — which is why the two columns give
# the same answer once differenced.

# %%
PANEL, SPROV = D.load_surprise_panel()
COMPOSITE, LEGS = D.build_surprise_composite(PANEL, CFG)
X_ALL = D.weekly_last(COMPOSITE, CFG.week_anchor)
D.gate_surprise_sanity(PANEL, CFG)
D.gate_trailing_only(PANEL[D.TAG_LABOUR].dropna(), CFG,
                     probe_dates=["2010-06-25", "2019-06-28", "2026-01-30"])
print("G3 and G5 pass (surprise sanity, trailing-only) -- unchanged from study 1")

GRID_W = D.weekly_grid("2004-01-02", COMPOSITE.dropna().index.max(), CFG.week_anchor)
BOOKS = {"raw": F.to_score_book(SP, score_column="m"),
         "era_adjusted": F.to_score_book(SP, score_column="ma")}
SENT = {k: D.sentiment_index(v, GRID_W, CFG, point_in_time=False)
        for k, v in BOOKS.items()}
rows = []
for k, s in SENT.items():
    d = s["sentiment"].dropna()
    rows.append({"column": k, "weeks": len(d), "first": d.index.min().date(),
                 "last": d.index.max().date(), "mean": round(d.mean(), 2),
                 "sd": round(d.std(), 3), "weekly_change_sd": round(d.diff().std(), 3),
                 "lag1_autocorr": round(d.autocorr(1), 3),
                 "median_speeches_in_window": int(s["n_speeches"].median())})
print(pd.DataFrame(rows).to_string(index=False))
print("\nThe era-adjusted INDEX has an sd of 0.83 against raw's 5.42 -- but its")
print("weekly-change sd is 0.66 against 0.69, and its autocorrelation is 0.69")
print("against 0.99. Era adjustment removes the LEVEL and keeps essentially all")
print("the high-frequency variation. So it is nearly flat as an index and still")
print("carries the same week-to-week information: right for ranking speeches,")
print("misleading as a level series, and equivalent once differenced.")

# %%
fig = make_subplots(specs=[[{"secondary_y": True}]])
push = pd.Timedelta(weeks=CFG.jws_lead_weeks)
xp = X_ALL.copy(); xp.index = xp.index + push
m = xp.index >= pd.Timestamp("2004-12-01")
fig.add_trace(go.Scatter(x=xp.index[m], y=xp[m],
                         name=f"surprise composite, pushed fwd {CFG.jws_lead_weeks}w",
                         line=dict(color=GREY, width=1.6)), secondary_y=False)
fig.add_trace(go.Scatter(x=SENT["raw"].index, y=SENT["raw"]["sentiment"],
                         name="FedLock sentiment (raw, EWMA hl=21d)",
                         line=dict(color=RED, width=1.8)), secondary_y=True)
fig.add_vrect(x0=pd.Timestamp(CFG.corpus_start), x1=X_ALL.index.max(), fillcolor="#ffffff",
              opacity=0.07, line_width=0,
              annotation_text="the first study's entire sample",
              annotation_position="top left", annotation_font_size=11)
fig.update_yaxes(title_text="surprise composite (trailing z)", secondary_y=False)
fig.update_yaxes(title_text="FedLock sentiment", secondary_y=True)
style(fig, 520, "Twenty-two years. The shaded strip is all the first study could see.")
fig.show()

# %% [markdown]
# ## 4. The lead, measured — same estimator, same config
#
# Symmetric −13..+13 scan, common-support matrix, paired-bootstrap plateau, and
# the exact rotation null. The rotation set here is **1,105 distinct rotations**
# rather than the first study's 189, so the p-value floor falls from 0.005 to
# 0.0009 — this sample can actually resolve a small effect.

# %%
def measure(x, y, transform, *, boot=400, shift=1400, seed=31):
    xt, yt, info = D.transform_pair(x, y, transform)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    curve = D.lag_curve_common(Xm, Ym, LAGS)
    j = int(np.nanargmax(curve["corr"].to_numpy()))
    b = D.bootstrap_lead(Xm, Ym, LAGS, CFG, draws=boot, rng=np.random.default_rng(seed))
    plat = D.plateau(curve, b["curves"])
    nl = D.shift_null(x, y, LAGS, CFG, transform=transform, draws=shift,
                      rng=np.random.default_rng(seed + 10))
    obs = float(curve["corr"].iloc[j])
    return dict(transform=transform, n=len(Ym), argmax=int(curve["lag_weeks"].iloc[j]),
                corr=obs, at_5w=float(curve.loc[curve["lag_weeks"] == 5, "corr"].iloc[0]),
                boot_lo=b["argmax_q05"], boot_hi=b["argmax_q95"],
                plateau_lo=min(plat), plateau_hi=max(plat), plateau_n=len(plat),
                ar_order=int(info.get("ar_order", 0)),
                p_shift=D.surrogate_pvalue(obs, nl), rotations=nl["distinct_rotations"],
                p_floor=nl["p_floor"], curve=curve, band_lo=b["band_lo"],
                band_hi=b["band_hi"])


SAMPLES, RES, rows = {}, {}, []
for col, s in SENT.items():
    j = pd.concat([X_ALL.rename("x"), s["sentiment"].rename("y")], axis=1).dropna()
    SAMPLES[col] = j
    for tr in ("levels", "changes", "prewhitened"):
        r = measure(j["x"], j["y"], tr)
        RES[(col, tr)] = r
        rows.append({"score": col, **{k: v for k, v in r.items()
                                      if k not in ("curve", "band_lo", "band_hi")}})
SUMMARY = pd.DataFrame(rows)
print(f"sample: {SAMPLES['raw'].index.min().date()} -> "
      f"{SAMPLES['raw'].index.max().date()}, {len(SAMPLES['raw'])} weeks "
      f"(the first study had 147)\n")
print(SUMMARY.round(4).to_string(index=False))

# %%
fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                    subplot_titles=("raw scores", "era-adjusted scores"))
for col_i, col in enumerate(("raw", "era_adjusted"), start=1):
    for tr, colr in (("levels", GREY), ("changes", RED), ("prewhitened", BLUE)):
        c = RES[(col, tr)]["curve"]
        fig.add_trace(go.Scatter(x=c["lag_weeks"], y=c["corr"], name=tr, legendgroup=tr,
                                 showlegend=col_i == 1,
                                 line=dict(color=colr, width=2.2)), row=1, col=col_i)
    fig.add_vline(x=CFG.jws_lead_weeks, line=dict(color=AMBER, width=1.6, dash="dash"),
                  row=1, col=col_i)
    fig.add_vline(x=13, line=dict(color=GREEN, width=1.2, dash="dot"), row=1, col=col_i)
    fig.add_hline(y=0, line=dict(color=GRID, width=1), row=1, col=col_i)
fig.update_xaxes(title_text="lag, weeks (positive = surprise LEADS sentiment)")
fig.update_yaxes(title_text="correlation", row=1, col=1)
style(fig, 450, "1,133 weeks. Amber dashed = JWS's 5w; green dotted = study 1's 13w.")
fig.show()

lv = RES[("raw", "levels")]
ch = RES[("raw", "changes")]
print(f"levels : argmax {lv['argmax']:+d}w, r {lv['corr']:.3f}, p {lv['p_shift']:.4f}, "
      f"plateau {lv['plateau_lo']:+d}..{lv['plateau_hi']:+d} "
      f"({lv['plateau_n']}/{len(LAGS)} lags -- the bootstrap cannot separate ANY lag "
      f"from the peak)")
print(f"changes: argmax {ch['argmax']:+d}w, r {ch['corr']:.3f}, p {ch['p_shift']:.4f}, "
      f"plateau {ch['plateau_lo']:+d}..{ch['plateau_hi']:+d} "
      f"({ch['plateau_n']}/{len(LAGS)} lag) -- exact over {ch['rotations']} rotations, "
      f"floor {ch['p_floor']:.4f}")
print(f"\nAt JWS's five weeks the changes correlation is {ch['at_5w']:+.3f}.")
print(f"r = {ch['corr']:.3f} explains {ch['corr'] ** 2:.1%} of the variance, measured on")
print(f"a sample {len(SAMPLES['raw']) / 147:.1f}x the first study's 147 weeks.")
print("The significant result is at TWO weeks, with a one-lag plateau, and it is")
print("the only cell in either study whose peak the bootstrap can actually pin.")

# %% [markdown]
# ### The null's size at THIS sample's length
#
# The +2w result is the only significant headline in either study, so the test
# behind it has to be calibrated at the length it actually runs on. Study 1
# measured the shift null's size at n = 170 weeks; this sample is 1,133, with
# 1,105 rotations rather than 189, and the splice artefact that rotation
# introduces does not have to scale the same way. So it is re-measured here
# rather than inherited.

# %%
SIZE = D.measure_null_size(CFG, transform="changes", which="shift",
                           n_weeks=len(SAMPLES["raw"]), trials=40, draws=1200,
                           seed=2000)
print(f"shift null on changes at n = {len(SAMPLES['raw'])} weeks: "
      f"{SIZE['rejected']}/{SIZE['trials']} rejections at a nominal 5% = "
      f"{SIZE['size']:.1%}  [Wilson {SIZE['wilson_lo']:.1%}, {SIZE['wilson_hi']:.1%}]")
_p2 = RES[("raw", "changes")]["p_shift"]
print(f"\nthe +2w p-value is {_p2:.4f}. Against six primary cells (2 score columns x")
print(f"3 transforms) a Bonferroni correction gives {min(1.0, _p2 * 6):.4f}, so it")
print("survives paying for the search across this notebook's own grid.")
print("It does NOT survive being treated as the winner of a search over every")
print("lag AND transform AND sample split in both studies -- but it was not")
print("selected that way: it is the cell the estimator was pointed at, on the")
print("transform study 1 had already committed to before this data existed.")

# %% [markdown]
# ### Does the +2w spike depend on which day the week ends?
#
# A single-lag spike under Friday-ending weeks deserves one check against a
# different anchor. The study's wording is "one to two weeks", so +1 or +3 under
# a Wednesday anchor is a pass; a jump to +8 would not be.

# %%
_c2 = D.LeadConfig(week_anchor="W-WED")
_x2 = D.weekly_last(COMPOSITE, _c2.week_anchor)
_g2 = D.weekly_grid("2004-01-02", COMPOSITE.dropna().index.max(), _c2.week_anchor)
_y2 = D.sentiment_index(BOOKS["raw"], _g2, _c2, point_in_time=False)["sentiment"]
_j2 = pd.concat([_x2.rename("x"), _y2.rename("y")], axis=1).dropna()
_xt, _yt, _ = D.transform_pair(_j2["x"], _j2["y"], "changes")
_Xm, _Ym, _ = D.lag_matrix(_xt, _yt, LAGS)
_cc = D.lag_curve_common(_Xm, _Ym, LAGS)
_k = int(np.nanargmax(_cc["corr"].to_numpy()))
_nl = D.shift_null(_j2["x"], _j2["y"], LAGS, CFG, transform="changes", draws=1400,
                   rng=np.random.default_rng(63))
print(f"W-WED anchor, changes: n={len(_Ym)} argmax "
      f"{int(_cc['lag_weeks'].iloc[_k]):+d}w  r {_cc['corr'].iloc[_k]:.3f}  "
      f"p {D.surrogate_pvalue(float(_cc['corr'].iloc[_k]), _nl):.4f}")
print(f"W-FRI anchor, changes: argmax {ch['argmax']:+d}w  r {ch['corr']:.3f}  "
      f"p {ch['p_shift']:.4f}")

# %% [markdown]
# ### G6 — the pipeline's own offset, re-measured at this corpus's density
#
# The first study found that a backward EWMA manufactures ~3 weeks of apparent
# lead in levels on data with a planted lead of **zero**. That offset depends on
# how densely the response side is sampled, so it must be re-measured at
# FedLock's 2.52 speeches/week rather than inherited from JPM's 3.28.

# %%
offsets = {}
for tr in ("levels", "changes"):
    vals = []
    for seed in range(12):
        p0, b0, _ = D.synthetic_world(lead_days=0, rng=np.random.default_rng(900 + seed),
                                      speeches_per_week=2.52)
        c0, _ = D.build_surprise_composite(p0, CFG)
        xx = D.weekly_last(c0, CFG.week_anchor)
        yy = D.sentiment_index(b0, xx.index, CFG, point_in_time=False)["sentiment"]
        xt, yt, _ = D.transform_pair(xx, yy, tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        vals.append(int(cc["lag_weeks"].iloc[int(np.nanargmax(cc["corr"].to_numpy()))]))
    offsets[tr] = vals
    print(f"  {tr:8s} zero-lead argmax over 12 synthetic worlds at 2.52/wk: "
          f"median {np.median(vals):+.1f}w  range {min(vals):+d}..{max(vals):+d}")
off = int(np.median(offsets["changes"]))
print(f"\nSo the changes result reads: measured {ch['argmax']:+d}w minus a filter offset")
print(f"of {off:+d}w = about {ch['argmax'] - off} week of relationship. A speech is")
print("drafted days ahead and delivered on a calendar fixed weeks ahead; a one-week")
print("lag between data landing and Fedspeak reflecting it is what the mechanics of")
print("speech-writing predict. It is a response time, not a forecastable lead.")

# %% [markdown]
# ## 5. Why the first study saw thirteen weeks
#
# Two things have to be reconciled: on 2023-05→2026-08 the JPM corpus gave
# +13w at r 0.737, and on 2004-2026 FedLock gives r 0.0606 in levels. Either the
# models disagree, or the windows do.

# %%
BRIDGE = []
sub = SAMPLES["raw"][SAMPLES["raw"].index >= pd.Timestamp(CFG.corpus_start)]
# FedLock is as-published by construction, so the strictly like-for-like row
# from study 1 is its AS-PUBLISHED same-window panel, not only its PIT one.
for tr, s1 in (("levels", "PIT +13w r 0.737 p 0.096 | as-pub +12w r 0.652 p 0.089"),
               ("changes", "PIT +13w r 0.153 p 0.568 | as-pub  +0w r 0.104 p 0.986")):
    xt, yt, _ = D.transform_pair(sub["x"], sub["y"], tr)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    cc = D.lag_curve_common(Xm, Ym, LAGS)
    k = int(np.nanargmax(cc["corr"].to_numpy()))
    obs = float(cc["corr"].iloc[k])
    nl = D.shift_null(sub["x"], sub["y"], LAGS, CFG, transform=tr, draws=1200,
                      rng=np.random.default_rng(57))
    BRIDGE.append({"transform": tr, "n": len(Ym),
                   "fedlock_argmax": int(cc["lag_weeks"].iloc[k]),
                   "fedlock_r": round(obs, 3),
                   "fedlock_p": round(D.surrogate_pvalue(obs, nl), 3),
                   "study1_jpm": s1})
print("FedLock, restricted to the FIRST STUDY'S WINDOW (2023-05 -> 2026-08):")
print(pd.DataFrame(BRIDGE).to_string(index=False))

JSENT = D.sentiment_index(JPM, GRID_W, CFG, point_in_time=False)["sentiment"]
BOTH = pd.concat([SENT["raw"]["sentiment"].rename("fedlock"),
                  JSENT.rename("jpm")], axis=1).dropna()
BOTH = BOTH[BOTH.index >= pd.Timestamp(CFG.corpus_start)]
print(f"\nindex-level agreement over {len(BOTH)} weeks: "
      f"pearson {BOTH.corr().iloc[0,1]:.4f}, "
      f"spearman {BOTH.corr(method='spearman').iloc[0,1]:.4f} "
      f"(speech level was {CM['speech_level_m']['pearson']:.3f})")
print("\nSo the models AGREE. On that window, two unrelated scoring systems put the")
print("peak at +11-13w with p ~0.08-0.10; against study 1's as-published panel --")
print("the like-for-like vintage, since FedLock has no other -- FedLock is if")
print("anything the STRONGER of the two (r 0.744 vs 0.652). The first study's")
print("number was not an artefact of JPM's model. It is an artefact of the WINDOW.")

# %% [markdown]
# ### Which window? The most favourable one in two decades.

# %%
j = SAMPLES["raw"]
roll_rows = []
for k, tr, lab in ((11, "levels", "levels @ +11w"), (2, "changes", "changes @ +2w")):
    a = j["x"].shift(k) if tr == "levels" else j["x"].diff().shift(k)
    b = j["y"] if tr == "levels" else j["y"].diff()
    rc = a.rolling(156, min_periods=120).corr(b).dropna()
    roll_rows.append((lab, rc))
    print(f"{lab}: 3-year rolling correlation over {len(rc)} windows")
    print(f"  min {rc.min():+.3f}  p25 {rc.quantile(.25):+.3f}  median {rc.median():+.3f}  "
          f"p75 {rc.quantile(.75):+.3f}  max {rc.max():+.3f}  positive in "
          f"{float((rc > 0).mean()):.0%} of windows")
    yr = rc.groupby(rc.index.year).mean().round(2)
    print(f"  by year: {yr.to_dict()}")

fig = go.Figure()
for (lab, rc), colr in zip(roll_rows, (GREY, RED)):
    fig.add_trace(go.Scatter(x=rc.index, y=rc, name=lab, line=dict(color=colr, width=2)))
fig.add_hline(y=0, line=dict(color=GRID, width=1))
fig.add_vrect(x0=pd.Timestamp(CFG.corpus_start), x1=j.index.max(), fillcolor="#ffffff", opacity=0.07,
              line_width=0, annotation_text="the first study's sample",
              annotation_position="top left", annotation_font_size=11)
fig.update_yaxes(title_text="3-year rolling correlation")
style(fig, 430, "The strong relationship is recent; the stable one has faded")
fig.show()
print("The two lines are mirror images. The +11w levels link runs negative through")
print("2016-2019 and reaches its twenty-year maximum in 2025-2026 -- exactly the")
print("window the first study could see. The +2w changes link is positive in 85% of")
print("windows, sits near +0.20 for a decade, and is the one that has gone to zero now.")

# %% [markdown]
# ## 6. Stability: five sub-periods instead of two halves
#
# The first study could split its sample once, into two 60-week halves. Twenty-one
# years supports five blocks of ~4 years.

# %%
BLOCKS = [("2005-01-01", "2009-01-01"), ("2009-01-01", "2013-01-01"),
          ("2013-01-01", "2017-01-01"), ("2017-01-01", "2021-01-01"),
          ("2021-01-01", "2027-01-01")]
srows = []
for lo, hi in BLOCKS:
    s = j[(j.index >= lo) & (j.index < hi)]
    if len(s) < 60:
        continue
    row = {"block": f"{lo[:4]}-{hi[:4]}", "weeks": len(s)}
    for tr in ("levels", "changes"):
        xt, yt, _ = D.transform_pair(s["x"], s["y"], tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        k = int(np.nanargmax(cc["corr"].to_numpy()))
        obs = float(cc["corr"].iloc[k])
        nl = D.shift_null(s["x"], s["y"], LAGS, CFG, transform=tr, draws=1200,
                          rng=np.random.default_rng(55))
        row[f"{tr}_argmax"] = int(cc["lag_weeks"].iloc[k])
        row[f"{tr}_r"] = round(obs, 3)
        row[f"{tr}_p"] = round(D.surrogate_pvalue(obs, nl), 3)
        row[f"{tr}_at5w"] = round(float(cc.loc[cc["lag_weeks"] == 5, "corr"].iloc[0]), 3)
    srows.append(row)
STAB = pd.DataFrame(srows)
print(STAB.to_string(index=False))
print(f"\nNot one of the {len(STAB)} blocks is significant on either transform "
      f"(p from {min(STAB['levels_p'].min(), STAB['changes_p'].min()):.3f} to "
      f"{max(STAB['levels_p'].max(), STAB['changes_p'].max()):.3f}), and the levels")
print("argmax visits +9, +11, -13, +13, +13. The +2w changes result exists only in")
print("the pooled sample. That is what a small, persistent effect looks like -- and")
print("it is also what a pooled artefact looks like, which is why it is reported at")
print("r 0.12 and not called a signal.")

# %% [markdown]
# ## 7. Where we are now
#
# The first study found the current episode contradicting the five-week rule
# outright. FedLock is an independent check on that reading.

# %%
hist = SENT["raw"]["sentiment"].dropna()
print(f"FedLock sentiment latest ({hist.index[-1].date()}): {hist.iloc[-1]:.2f}")
print(f"  = {float((hist <= hist.iloc[-1]).mean()):.0%} percentile of 2004+, "
      f"{float((hist[hist.index >= pd.Timestamp(CFG.corpus_start)] <= hist.iloc[-1]).mean()):.0%} "
      f"of the first study's window")
print(f"surprise composite latest: {float(X_ALL.dropna().iloc[-1]):+.3f} "
      f"(peaked +1.164 on 2026-06-05)")
print("\nlast eight weekly readings:")
print(hist.tail(8).round(2).to_string())
print("\nFedLock speeches since 2026-06-15:")
print(SP[SP["date"] >= "2026-06-15"][["date", "speaker", "m", "ma", "speech_type"]]
      .to_string(index=False))
print("\nBoth models agree: Fedspeak is close to the top of its historical range")
print("while the surprise composite has rolled over. Five weeks past the composite")
print("peak was 2026-07-10, since when this index has gone from 54.97 to 59.66.")

# %% [markdown]
# ## 8. Does it reach the price?
#
# The first study could only test this over 168 weeks, leaving an effective n of
# 12-42 after HAC. Twenty-one years leaves 86-281.

# %%
R2Y = D.read_cached_rate(D.TAG_SOFR_2Y)
if R2Y is None:
    print("no cached SOFR 2y on this machine -- the rates leg is not testable here")
else:
    W2 = D.weekly_last(R2Y, CFG.week_anchor)
    trows = []
    for src, ser in (("surprise composite", X_ALL),
                     ("FedLock raw", SENT["raw"]["sentiment"]),
                     ("FedLock era-adj", SENT["era_adjusted"]["sentiment"])):
        for h in (4, 5, 6, 8, 11, 13):
            fwd = (W2.shift(-h) - W2) * 100.0
            df = pd.concat([ser.rename("x"), fwd.rename("y")], axis=1).dropna()
            df = df[df.index >= "2005-01-01"]
            nw = D.newey_west_t(df["y"].to_numpy(), df["x"].to_numpy(), lag=h)
            trows.append({"signal": src, "horizon_w": h, "n": nw["n"],
                          "effective_n": round(nw["effective_n"]),
                          "t_HAC": round(nw["t"], 2), "R2": round(nw["r2"], 4)})
    RATES = pd.DataFrame(trows)
    print(RATES.to_string(index=False))
    best = RATES.loc[RATES["t_HAC"].abs().idxmax()]
    from scipy import stats
    p_raw = float(2 * (1 - stats.norm.cdf(abs(best["t_HAC"]))))
    same13 = RATES.query("signal == @best.signal and horizon_w == 13")["t_HAC"].iloc[0]
    print(f"\nThe one cell that flickers: {best['signal']} at {best['horizon_w']}w, "
          f"t = {best['t_HAC']}, R2 {best['R2']}.")
    print(f"  unadjusted two-sided p = {p_raw:.3f}")
    print(f"  Bonferroni over the {len(RATES)} cells shown = "
          f"{min(1.0, p_raw * len(RATES)):.3f}")
    print(f"  and the same regressor at 13 weeks reads t = {same13}")
    print("  It is also the regressor with an sd of 0.83, so its beta is large by")
    print("  construction. Reported because it is the largest number in the table,")
    print("  not because it is a result.")

# %% [markdown]
# ## Caveats, and what would change the answer
#
# 1. **Nothing here is point-in-time and nothing here is tradeable.** Three
#    channels, none removable: one `builtOn` stamp with no row-level date;
#    TrueSkill fitting every rating jointly against a comparison graph that spans
#    the whole corpus including the future; and a judge model whose training data
#    contains decades of commentary about what the Fed did next. The third is the
#    one FedLock's methodology does not discuss — anonymisation removes names, not
#    hindsight, and only post-cutoff speeches are scored blind.
# 2. **The 327 undated rows are 8.2% of the corpus**, concentrated in Fisher,
#    Yellen and Williams from the regional-Fed scrapers. They are dropped because
#    placing a speech inside its year would fabricate the one property being
#    measured. They still participated in the tournament, so the dated speeches'
#    scores were partly fitted against them.
# 3. **The +2w result is small and pooled.** r 0.122 is 1.5% of variance, and no
#    individual four-year block reaches significance. A pooled p of 0.0027 with
#    no sub-period support is consistent with a small persistent effect *and*
#    with a structural artefact of two series that share a weekly sampling
#    scheme. The rolling-correlation panel is the evidence that leans toward the
#    former — 85% of windows positive — but it is not proof.
# 4. **The era-adjusted index is nearly flat as a level series** (sd 0.83) even
#    though it is the right column for ranking speakers. Anything read off its
#    *level* should be treated with suspicion; its changes are sound.
# 5. **Two of FedLock's own hawk/dove labels invert** on era-adjusted scores
#    (Waller ranks 40/47, Bostic 15/47). The four named ZIRP-era hawks and Evans
#    check out, and the timeline reproduces exactly, so the series this study
#    reads is validated — but the roster as a whole is not.
# 6. **A refresh is a new dataset, not an update.** New speeches enter the
#    tournament and re-rate old ones. The V2→V3 measurement bounds how far that
#    can go: half a standard deviation for a typical speech, all at once.
# 7. **What would change the answer.** A sentiment series that is both
#    contemporaneous and long — a vendor index with a real publication axis, or
#    FedLock re-run as a sequence of frozen as-of vintages — is the only thing
#    that would let the +11-13w peak be tested on more than one favourable
#    window. Short of that, the pair of studies is the best available: the
#    tradeable one is too short, the long one cannot be gated, and the +11-13w
#    result lives only where they cannot both look.
#
# ## Reproducing this
#
# ```
# conda run -n stir python notebooks/rv/fedlock_refresh.py        # fetch V3 + V2
# conda run -n stir python notebooks/rv/run_fedlock_sentiment_lead.py
# conda run -n stir python -m pytest tests/test_fedlock_sentiment_lead.py -q
# ```
#
# The `.py` is the source of truth; the `.ipynb` is generated by
# `notebooks/backtests/_py2nb.py`, executed by nbclient, verified by
# `_verify_nb.py` (zero errors, zero unrun) and audited by
# `_audit_fedlock_numbers.py`, which requires every figure in the findings block
# to appear verbatim in an executed cell.
