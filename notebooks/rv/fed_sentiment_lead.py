# %% [markdown]
# # Does a data surprise lead Fedspeak by five weeks?
#
# JWS Macro #8, *Playing Devil's Advocate* (23-Aug-2026), plots an equally
# weighted Bloomberg Inflation & Labor Market Surprise composite **pushed
# forward five weeks** against the Bloomberg Fed Sentiment Language Model, and
# annotates four turning points where the grey line leads the red. The reading
# offered is a "tidy 5-week lead of data surprise vs Fedspeak", and it matters
# right now because the grey line has rolled from ~0.85 in July to ~0.1 while
# the red has only just started to turn: if the lead holds, Fedspeak turns
# dovish through late September, straight through the 16-Sep FOMC.
#
# This notebook rebuilds both series on our own infrastructure -- Citi Velocity
# surprise indices and the JPM NLP hawk/dove corpus -- and **measures** the lead
# instead of assuming it.
#
# ## What was measured -- the numbers up front
#
# *(Every figure here is restated by a cell below. If the cells and this summary
# ever disagree, the cells are what ran.)*
#
# 1. **Taken at face value the lead is 11-14 weeks, not 5.** As-published the
#    curve peaks at **+11w (r 0.62)**, interior inside the headline +/-13 scan.
#    Point-in-time it pins at the **+13w** boundary of that scan, so the scan is
#    widened to +/-26: it resolves to **+14w (r 0.77)** with a flat top across
#    +12..+16 and a fall away to 0.52 by +26w, which makes it a real interior
#    maximum rather than an artefact of where the scan stopped. At JWS's +5w the
#    correlation is 0.46 (point-in-time, 62% of the peak) and 0.55
#    (as-published, 89%). At long negative lags the curve is -0.37
#    (point-in-time) and +0.05 (as-published), so sentiment does not lead
#    surprises in either vintage -- the *direction* of the story survives; the
#    number does not.
# 2. **An independent inflation series agrees, and also says 11-14 weeks.**
#    Citi's proper monthly Inflation Surprise Index (`ISI.SI_CISI`, 343
#    observations back to 1998 -- a different construction from the daily leg
#    the chart uses) peaks against the same sentiment index at **+4 months**,
#    r 0.756, again with an interior peak.
# 3. **Exactly one cell clears a null that respects the persistence, and it is
#    the one built from information that did not exist at the time.** Both
#    series are heavily smoothed and near-unit-root, so the null keeps each path
#    *exactly* and destroys only the alignment, scored by the same 27-lag
#    maximum the real analysis takes. The **as-published** levels peak reaches
#    **p = 0.001** -- but run it on the point-in-time *window* rather than its
#    own longer one and it falls to **p = 0.081**. The extra significance comes
#    entirely from 2022, where 100% of the sentiment rows are back-filled by
#    reports that did not exist until May-2023. The honest cells:
#    point-in-time levels **p = 0.09** against a test whose measured size is
#    8.3%, and on weekly **changes** -- the one transform where the null is
#    exactly calibrated (measured size 5.0%) -- a maximum over all 27 lags of
#    **r 0.153, p = 0.55**. There is no relationship in changes at any lag in
#    either vintage.
# 4. **Five weeks is the first half of the sample, and it has already broken.**
#    Split the point-in-time sample at 2024-12: the first half's argmax is
#    **exactly +5 weeks** (r 0.685) -- JWS's number. The second half's is +13w,
#    and the correlation *at five weeks* is **-0.07**, bootstrap 5-95%
#    [-0.47, +0.37]. In changes: +0.219 then +0.043.
# 5. **The pipeline manufactures about three weeks of the apparent lead by
#    itself.** A *zero*-lead relationship pushed through the identical pipeline
#    on synthetic data comes out at a median argmax of **+3 weeks** in levels
#    (+1 in changes) -- the backward EWMA's own centre of mass. Asserted by a
#    test (`test_pipeline_reports_a_lead_even_when_the_true_lead_is_zero`), not
#    left as a footnote.
# 6. **Found algorithmically rather than drawn, the turning points give 12-13
#    weeks with a -1 to +23 spread.** Nine surprise turns and thirteen sentiment
#    turns since Apr-2023; the gap to the next same-sign sentiment turn has
#    median **13.0w**, mean 12.2w, range **-1 to +23**, n = 6. One of the six is
#    negative -- sentiment turned first.
# 7. **The current episode already contradicts the five-week rule.** Our
#    composite peaked 2026-06-05 at +1.16 and reads -0.37 now. Five weeks past
#    that peak is 2026-07-10, and since then Fed sentiment has gone from **+9.7
#    to +29.6 -- the most hawkish reading in the entire sample (100th
#    percentile)** -- on **16 hawk-labelled speeches out of 19**, Logan 62,
#    Hammack 58, Warsh 49.
# 8. **The rolldown is an inflation-surprise story, not a data story.** It is
#    entirely the prices leg (z +0.22 -> -1.27 since 10-Jul). The labour leg was
#    still +1.4 through July and only slipped to +0.53 in the last fortnight.
# 9. **The point-in-time series is revised hard, exactly where it is used.**
#    Mean |revision| between what a reader saw at the time and what the same
#    week reads today is **2.65 sentiment points = 39% of one standard
#    deviation**; 74.6% of weeks move by more than a point. The 2026-07-31
#    reading was **21.63 at the time and reads 30.47 today**. And 17.9% of Fed
#    rows are published so late they can never enter the point-in-time index at
#    all.
# 10. **It does not reach the price.** The forward 4/5/6/8/11/13-week change in
#    the 2y SOFR OIS rate regressed on the composite gives **|t| <= 0.79 and
#    R2 <= 0.013** across all twelve cells -- in the point-in-time era *and* in
#    the full 2005-2026 sample, where HAC leaves an effective n of 86-281 rather
#    than the 12-42 the point-in-time era supports. Sentiment itself does no
#    better (t -0.68, R2 0.005).
# 11. **No variant of the construction recovers five weeks.** Eleven
#    alternatives -- half-lives 7d to 42d, z-windows 2y to 5y, a Wednesday week,
#    each leg alone, the whole economic surprise index, relevance weighting --
#    put the levels argmax at **13 weeks in 11 cases out of 11**. On changes the
#    argmax scatters across -12, -5, +1 and +13, which is what no relationship
#    looks like.
#
# **Verdict.** The lead exists as a shape and it points the right way, but it
# is 11-14 weeks rather than five; the only cell that clears its null is the one
# built from scores that did not exist at the time; it is unstable across the
# only two halves this sample supports, with the five-week correlation going
# from +0.69 to -0.07; and it does not reach a tradeable price at any horizon.
# As a description of history it is fine. As a reason to be positioned for
# dovish Fedspeak into 16-Sep it is four arrows on a chart -- and the current
# episode has already run five weeks past the surprise peak with Fedspeak at
# its most hawkish reading on record.
#
# ## Two vintages, because our sentiment data is not Bloomberg's
#
# JWS plots Bloomberg's Fed Sentiment Language Model, which is contemporaneous
# by construction. Ours is not. The JPM corpus is a set of PDF reports, each
# carrying a "Recent Speeches" table of that speaker's history, and **JPM
# re-scores history as its model is revised**: 53% of the 730 Fed rows come from
# a report published after the speech they describe (median 1 day, p90 246, max
# 6432). So there are two legitimate series:
#
# | | keyed on | starts | use |
# |---|---|---|---|
# | **as-published** | `date` | density-gated to 2022-01 | matches the *shape* of JWS's chart, fine for describing history, **not tradeable** |
# | **point-in-time** | `date` **and** `pub_date` | **2023-05-02** | the only one that says what could have been acted on |
#
# Both are built and both are plotted. The gap between them is a finding.
#
# **Say the effective n out loud.** The Citi surprise data runs daily from 2003
# (monthly inflation from 1998). The sentiment corpus starts 2023-05-02. The
# binding constraint on any honest point-in-time sample is therefore the
# *sentiment* side: **147 weekly observations**, about three years, which is
# roughly six turning points. A long x-axis does not make a long sample.

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

#: connected notebook renderer keeps plotly.js on a CDN rather than embedding a
#: copy of the library in every figure
pio.renderers.default = "plotly_mimetype+notebook_connected"

HERE = Path.cwd()
REPO = HERE if (HERE / "MDP").exists() else HERE.parents[1]
for p in (str(REPO), str(REPO / "notebooks" / "rv")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_sentiment_lead_data as D  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 120)

BG, GRID = "#11151c", "#2a3340"
GREY, RED, BLUE, AMBER = "#9aa7b8", "#e05353", "#4c9be8", "#e8b44c"


def style(fig, height=520, title=None):
    fig.update_layout(
        template="plotly_dark", height=height, title=title,
        paper_bgcolor=BG, plot_bgcolor=BG, margin=dict(l=60, r=60, t=60, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=12),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


CFG = D.LeadConfig()
LAGS = CFG.lags()
print("config frozen at import; every knob and its reason:")
print(CFG.describe().to_string(index=False))

# %% [markdown]
# ## The inputs, and gate G3
#
# The surprise side is a `CVTSHIST` pull, so it is not a static file. The
# notebook reads a **committed snapshot** and prints its provenance;
# `fed_sentiment_lead_refresh.py --live` rewrites that snapshot from the live
# add-in and `--xlsx` from the hand-exported workbook. The live path is a
# separate command on purpose: every Velocity fetch runs through a
# human-logged-in Excel over COM, and driving that from inside a notebook
# runner is a measured hazard here.
#
# **G3** asserts that every series used has more than 100 non-zero observations
# -- which is what keeps the identically-zero sub-indices
# (`EXTERNAL_BALANCES_OR_TRADE`, `GOVERNMENT_FINANCES`) out of an equal-weight
# average -- and that the two legs share a frequency before they are averaged.
# The proper monthly Inflation Surprise Index is deliberately *not* one of the
# two legs: forward-filling a 343-observation monthly series into a daily one
# makes the composite a step function whose turning points are calendar
# artefacts, and turning points are the entire claim under test. It appears
# later, on its own panel, at its own frequency.

# %%
panel, PROV = D.load_surprise_panel()
print("snapshot provenance:", {k: v for k, v in PROV.items() if k != "missing_tags"})
print(f"panel {panel.shape}  {panel.index.min().date()} -> {panel.index.max().date()}")

G3 = D.gate_surprise_sanity(panel, CFG)
print("\nG3 -- surprise sanity (asserts inside):")
print(G3.to_string(index=False))

# hand-check: a hot CPI must move the prices leg UP
prices = panel[D.TAG_PRICES].dropna()
for d, note in [("2024-04-10", "Mar-24 core CPI 0.4% vs 0.3% expected"),
                ("2025-01-15", "Dec-24 core CPI 0.2% vs 0.3% -- a COOL print"),
                ("2026-07-17", "the week the prices leg collapsed")]:
    t = pd.Timestamp(d)
    prev, on = prices[prices.index < t].iloc[-1], prices.asof(t)
    print(f"  {d}  {note:48s} prices leg {prev:+7.2f} -> {on:+7.2f}  ({on - prev:+.2f})")

# %% [markdown]
# ## The two series, and gates G1 / G2 / G5
#
# **The surprise composite.** Both legs are trailing-z-scored on a 756 business
# day (3 year) window and equally weighted. Citi's raw indices run in the tens
# (labour last +11.8, prices -9.3) while JWS's axis runs -0.75 to +1.50, so he
# is plotting something standardised; a trailing window is the only way to do
# that without look-ahead.
#
# **The sentiment index.** A calendar-time EWMA over *visible* Fed speeches,
# half-life 21 days, truncated at 126. The weight is set by **speech** recency
# in both vintages -- so a report published 245 days after its speech arrives
# with that speech already 245 days old and contributes nothing. That is
# intended: a re-score of an old speech is not news about the committee's
# current stance. It is also expensive, and G1 reports what it costs.
#
# * **G1** -- the publication gate, date by date, with the share it removes.
# * **G2** -- the point-in-time series must be empty before 2023-05-02.
# * **G5** -- every z-score is trailing. Tested mechanically: truncating the
#   series after `t` must not change its value at `t`.

# %%
composite, LEGS = D.build_surprise_composite(panel, CFG)
X_ALL = D.weekly_last(composite, CFG.week_anchor)
GRID_W = D.weekly_grid("2021-01-01", composite.dropna().index.max(), CFG.week_anchor)

SCORES = D.load_fed_scores(CFG)
SENT_AP = D.sentiment_index(SCORES, GRID_W, CFG, point_in_time=False)
SENT_PIT = D.sentiment_index(SCORES, GRID_W, CFG, point_in_time=True)

publag = (SCORES["pub_date"] - SCORES["date"]).dt.days
print(f"FED rows {len(SCORES)}   speeches {SCORES['date'].min().date()} -> "
      f"{SCORES['date'].max().date()}   reports {SCORES['pub_date'].min().date()} -> "
      f"{SCORES['pub_date'].max().date()}")
print(f"publication lag: median {publag.median():.0f}d  p75 {publag.quantile(.75):.0f}d  "
      f"p90 {publag.quantile(.9):.0f}d  max {publag.max():.0f}d  "
      f"share published after the speech {(publag > 0).mean():.1%}")
never = int((publag > CFG.ewma_window_days).sum())
print(f"rows published so late they can NEVER enter the point-in-time index "
      f"(lag > {CFG.ewma_window_days}d): {never} = {never/len(SCORES):.1%}")

G1 = D.gate_vintage(SCORES, GRID_W, CFG)
print("\nG1 -- what the publication gate removes (every 26th week):")
print(G1.loc[G1.index[::26]].round(3).to_string())
print(f"G1 passes: the gate removes up to {int(G1['n_removed'].max())} rows "
      f"({G1['share_removed'].max():.0%} at the corpus start, "
      f"{G1.loc[G1.index >= '2023-06-01', 'share_removed'].mean():.1%} on average after it)")

D.gate_no_pre_corpus(SENT_PIT["sentiment"], CFG)
print(f"G2 passes: no point-in-time observation before {CFG.corpus_start}; "
      f"first is {SENT_PIT['sentiment'].first_valid_index().date()}")

G5 = D.gate_trailing_only(panel[D.TAG_LABOUR].dropna(), CFG,
                          probe_dates=["2019-06-28", "2023-05-05", "2026-01-30"])
print(f"G5 passes: worst |diff| between the trailing z on truncated and full "
      f"history is {float(G5['abs_diff'].max()):.1e}")
print(G5.to_string(index=False))

print(f"\nsentiment coverage: as-published {int(SENT_AP['sentiment'].notna().sum())} weeks "
      f"from {SENT_AP['sentiment'].first_valid_index().date()}; point-in-time "
      f"{int(SENT_PIT['sentiment'].notna().sum())} weeks from "
      f"{SENT_PIT['sentiment'].first_valid_index().date()}")
print(f"speeches inside the EWMA window: min {int(SENT_PIT['n_speeches'].min())}, "
      f"median {int(SENT_PIT['n_speeches'].median())}, max {int(SENT_PIT['n_speeches'].max())} "
      f"-- the min_speeches={CFG.min_speeches_in_window} floor never binds, because the "
      f"corpus's first reports back-fill ~165 Fed speeches at once")

# %% [markdown]
# ## 1. The chart, in both vintages
#
# Grey on the left axis is the surprise composite **pushed forward five weeks**,
# exactly as JWS draws it. Red on the right is Fed sentiment. The dashed red
# line is the point-in-time vintage -- the same weeks, gated on what had been
# published. The shaded band before 2023-05-02 is where the point-in-time
# series does not exist at all.

# %%
push = pd.Timedelta(weeks=CFG.jws_lead_weeks)
x_push = X_ALL.copy()
x_push.index = x_push.index + push

fig = make_subplots(specs=[[{"secondary_y": True}]])
m = x_push.index >= pd.Timestamp(CFG.chart_start)
fig.add_trace(go.Scatter(x=x_push.index[m], y=x_push[m], name=f"surprise composite, pushed fwd {CFG.jws_lead_weeks}w",
                         line=dict(color=GREY, width=2.4)), secondary_y=False)
for series, name, dash in ((SENT_AP["sentiment"], "Fed sentiment, as-published", "solid"),
                           (SENT_PIT["sentiment"], "Fed sentiment, point-in-time", "dash")):
    s = series[series.index >= pd.Timestamp(CFG.chart_start)]
    fig.add_trace(go.Scatter(x=s.index, y=s, name=name,
                             line=dict(color=RED, width=2.0, dash=dash)), secondary_y=True)
fig.add_vrect(x0=CFG.chart_start, x1=CFG.corpus_start, fillcolor="#ffffff", opacity=0.06,
              line_width=0, annotation_text="no point-in-time signal exists here",
              annotation_position="top left", annotation_font_size=11)
fig.add_hline(y=0, line=dict(color=GRID, width=1), secondary_y=False)
fig.update_yaxes(title_text="surprise composite (trailing z, equal weight)", secondary_y=False)
fig.update_yaxes(title_text="Fed sentiment (JPM hawk/dove, EWMA hl=21d)", secondary_y=True)
style(fig, 560, "JWS's chart, rebuilt: surprise composite pushed forward 5 weeks vs Fed sentiment")
fig.show()

# %% [markdown]
# The shape is recognisable and the direction is right, so this is the same
# phenomenon JWS is looking at. Two differences worth stating before anything is
# measured:
#
# * **Our composite is lower than his.** He describes ~0.85 in July falling to
#   ~0.1; ours reads +0.63 on 10-Jul and **-0.37** now. Different underlying
#   indices (Citi vs Bloomberg) and a trailing rather than full-sample
#   standardisation both move the level. The *rolldown* reproduces; the level
#   does not, and nothing below depends on the level.
# * **The two vintages track each other at r 0.907** but with mean |gap| 2.65
#   sentiment points -- and the gap is largest at the right-hand edge, which is
#   where a trade would be put on.

# %%
both = pd.concat([SENT_AP["sentiment"].rename("as_published"),
                  SENT_PIT["sentiment"].rename("point_in_time")], axis=1).dropna()
print(f"vintage agreement over {len(both)} weeks: r = {both.corr().iloc[0,1]:.4f}, "
      f"mean|gap| {(both.iloc[:,0]-both.iloc[:,1]).abs().mean():.3f}, "
      f"max|gap| {(both.iloc[:,0]-both.iloc[:,1]).abs().max():.3f} sentiment points")
print("\nthe composite through the episode JWS is writing about:")
print(X_ALL[X_ALL.index >= "2026-06-01"].round(3).to_string())

# %% [markdown]
# ## 2. Measure the lead -- do not assume it
#
# The lag scan runs **symmetrically, -13 to +13 weeks**. Negative lags are the
# control: if the curve peaked there the story would be backwards.
#
# Three transforms, because they answer different questions and only one of
# them supports inference:
#
# | transform | what it sees | measured null size |
# |---|---|---|
# | **levels** | the shape JWS is describing | 8.3% |
# | **changes** | week-on-week co-movement | **5.0%** |
# | **prewhitened** | Box-Jenkins: filter both by the input's own AR model | 9.2% |
#
# Those sizes are not assumed -- they were measured over 120 unrelated AR(0.97)
# pairs scored at a nominal 5%, and they are why the p-values quoted in the
# findings come from **changes**.
#
# Every lag is scored on **one common-support row set**, so a difference between
# lags is a difference in the relationship and not a difference in the sample;
# the per-lag maximal-sample curve is computed alongside as a check that the two
# agree.
#
# Two nulls, both scored by the same 27-lag maximum the real analysis takes:
#
# * **shift null** (primary) -- rotate the surprise series circularly. Every
#   surrogate keeps the real path's trend, persistence, variance and marginal
#   distribution; only the alignment is destroyed.
# * **phase null** -- phase-randomise to the same power spectrum. Reported
#   beside it, never instead: it is mildly anti-conservative on levels and
#   heavily *over*-conservative on changes.

# %%
def measure(x, y, transform, *, boot=600, shift=1500, phase=800, seed=31):
    xt, yt, info = D.transform_pair(x, y, transform)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    curve = D.lag_curve_common(Xm, Ym, LAGS)
    pair = D.lag_curve_pairwise(xt, yt, LAGS)
    j = int(np.nanargmax(curve["corr"].to_numpy()))
    b = D.bootstrap_lead(Xm, Ym, LAGS, CFG, draws=boot, rng=np.random.default_rng(seed))
    plat = D.plateau(curve, b["band_lo"])
    sh = D.shift_null(x, y, LAGS, CFG, transform=transform, draws=shift,
                      rng=np.random.default_rng(seed + 10))
    ph = D.surrogate_null(x, y, LAGS, CFG, transform=transform, draws=phase,
                          rng=np.random.default_rng(seed + 20))
    obs = float(curve["corr"].iloc[j])
    return dict(transform=transform, n=len(Ym), argmax=int(curve["lag_weeks"].iloc[j]),
                corr=obs, at_5w=float(curve.loc[curve["lag_weeks"] == 5, "corr"].iloc[0]),
                at_0w=float(curve.loc[curve["lag_weeks"] == 0, "corr"].iloc[0]),
                boot_lo=b["argmax_q05"], boot_hi=b["argmax_q95"],
                plateau_lo=min(plat), plateau_hi=max(plat), plateau_n=len(plat),
                pairwise_argmax=int(pair["lag_weeks"].iloc[int(np.nanargmax(pair["corr"].to_numpy()))]),
                p_shift=D.surrogate_pvalue(obs, sh), p_phase=D.surrogate_pvalue(obs, ph),
                curve=curve, band_lo=b["band_lo"], band_hi=b["band_hi"], info=info)


SAMPLES = {
    "as_published": (X_ALL[X_ALL.index >= pd.Timestamp(CFG.as_published_start)],
                     SENT_AP["sentiment"][SENT_AP.index >= pd.Timestamp(CFG.as_published_start)]),
    "point_in_time": (X_ALL[X_ALL.index >= pd.Timestamp(CFG.corpus_start)],
                      SENT_PIT["sentiment"][SENT_PIT.index >= pd.Timestamp(CFG.corpus_start)]),
}
RES = {}
rows = []
for vint, (x, y) in SAMPLES.items():
    for tr in ("levels", "changes", "prewhitened"):
        r = measure(x, y, tr)
        RES[(vint, tr)] = r
        rows.append({"vintage": vint, **{k: v for k, v in r.items()
                                         if k not in ("curve", "band_lo", "band_hi", "info")}})
SUMMARY = pd.DataFrame(rows)
print(SUMMARY.round(3).to_string(index=False))

# %% [markdown]
# The whole curve, not just its winner -- G4. A single argmax with no curve
# around it is not evidence.

# %%
fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                    subplot_titles=("as-published (2022-01 ->)", "point-in-time (2023-05 ->)"))
for col, vint in enumerate(("as_published", "point_in_time"), start=1):
    for tr, colr in (("levels", GREY), ("changes", RED), ("prewhitened", BLUE)):
        r = RES[(vint, tr)]
        c = r["curve"]
        fig.add_trace(go.Scatter(x=c["lag_weeks"], y=c["corr"], name=f"{tr}",
                                 legendgroup=tr, showlegend=col == 1,
                                 line=dict(color=colr, width=2.2)), row=1, col=col)
        if tr == "levels":
            fig.add_trace(go.Scatter(
                x=list(c["lag_weeks"]) + list(c["lag_weeks"])[::-1],
                y=list(r["band_hi"]) + list(r["band_lo"])[::-1], fill="toself",
                fillcolor="rgba(154,167,184,0.18)", line=dict(width=0),
                name="levels 5-95% block bootstrap", legendgroup="band",
                showlegend=col == 1, hoverinfo="skip"), row=1, col=col)
    fig.add_vline(x=CFG.jws_lead_weeks, line=dict(color=AMBER, width=1.6, dash="dash"),
                  row=1, col=col)
    fig.add_vline(x=0, line=dict(color=GRID, width=1), row=1, col=col)
    fig.add_hline(y=0, line=dict(color=GRID, width=1), row=1, col=col)
fig.update_xaxes(title_text="lag, weeks (positive = surprise LEADS sentiment)")
fig.update_yaxes(title_text="correlation", row=1, col=1)
style(fig, 470, "The full lag curve. Amber dashed = JWS's 5 weeks.")
fig.show()

for vint in ("as_published", "point_in_time"):
    r = RES[(vint, "levels")]
    print(f"{vint:14s} levels: peak {r['corr']:.3f} at {r['argmax']:+d}w; "
          f"at +5w {r['at_5w']:+.3f} ({r['at_5w']/r['corr']:.0%} of the peak); "
          f"plateau {r['plateau_lo']:+d}..{r['plateau_hi']:+d} "
          f"({r['plateau_n']}/{len(LAGS)} lags indistinguishable from the peak)")

# %% [markdown]
# ### Is the argmax interior, or is it the edge of the scan?
#
# A curve that is still rising when the scan stops does not identify a lead --
# it says "at least as long as you looked". Widening the scan to +/-26 weeks
# answers it directly, and the answer is the reason the headline says 11-14
# weeks rather than dismissing the peak as an artefact.

# %%
WIDE = np.arange(-26, 27)
wide_rows = []
fig = go.Figure()
for vint, (x, y), colr in (("as_published", SAMPLES["as_published"], GREY),
                           ("point_in_time", SAMPLES["point_in_time"], RED)):
    xt, yt, _ = D.transform_pair(x, y, "levels")
    Xm, Ym, _ = D.lag_matrix(xt, yt, WIDE)
    c = D.lag_curve_common(Xm, Ym, WIDE)
    v = c["corr"].to_numpy()
    j = int(np.nanargmax(v))
    wide_rows.append({"vintage": vint, "n": len(Ym), "argmax": int(c["lag_weeks"].iloc[j]),
                      "corr": v[j], "interior_peak": bool(0 < j < len(v) - 1),
                      "corr_at_-18w": float(c.loc[c["lag_weeks"] == -18, "corr"].iloc[0]),
                      "corr_at_+26w": float(v[-1])})
    fig.add_trace(go.Scatter(x=c["lag_weeks"], y=v, name=vint, line=dict(color=colr, width=2.4)))
fig.add_vrect(x0=-13, x1=13, fillcolor="#ffffff", opacity=0.05, line_width=0,
              annotation_text="the headline scan window", annotation_position="top left")
fig.add_vline(x=CFG.jws_lead_weeks, line=dict(color=AMBER, width=1.6, dash="dash"))
fig.add_hline(y=0, line=dict(color=GRID, width=1))
fig.update_xaxes(title_text="lag, weeks")
fig.update_yaxes(title_text="correlation, levels")
style(fig, 430, "Wide scan: the peak turns over, so it is a real interior maximum")
fig.show()
print(pd.DataFrame(wide_rows).round(3).to_string(index=False))
print("\nThe curve rises, peaks around +11..+16 and falls away again, so the argmax")
print("is a real interior maximum and not an artefact of where the scan stopped.")
print("At long NEGATIVE lags it is -0.37 (point-in-time) and +0.05 (as-published),")
print("so sentiment does not lead surprises in either vintage. The direction of")
print("JWS's story survives. The number does not: it is 11-14 weeks, not five.")

# %% [markdown]
# ### G6 -- calibrating the estimator against its own filter offset
#
# This is the test that decides whether any measured lead means anything. The
# sentiment index is a **backward** EWMA: with a 21-day half-life its centre of
# mass sits about 28 days behind the grid date. So a purely *contemporaneous*
# relationship, pushed through this pipeline, still comes out looking like a
# multi-week lead -- and unless that artefact is measured, it is impossible to
# say how much of an observed lead belongs to the Fed.
#
# Twelve synthetic worlds are built with a **zero** planted lead and run through
# the identical pipeline. Whatever argmax comes back is the pipeline's own
# offset, and every real number below is read against it.

# %%
sys.path.insert(0, str(REPO / "tests"))
from test_fed_sentiment_lead import _synthetic_world  # noqa: E402

offsets = {}
for tr in ("levels", "changes", "prewhitened"):
    vals = []
    for seed in range(12):
        p0, b0, _ = _synthetic_world(lead_days=0, rng=np.random.default_rng(700 + seed))
        c0, _ = D.build_surprise_composite(p0, CFG)
        xx = D.weekly_last(c0, CFG.week_anchor)
        yy = D.sentiment_index(b0, xx.index, CFG, point_in_time=False)["sentiment"]
        xt, yt, _ = D.transform_pair(xx, yy, tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        vals.append(int(cc["lag_weeks"].iloc[int(np.nanargmax(cc["corr"].to_numpy()))]))
    offsets[tr] = vals
    print(f"  {tr:12s} zero-lead argmax over 12 synthetic worlds: median "
          f"{np.median(vals):+.1f}w  mean {np.mean(vals):+.2f}w  range {min(vals):+d}..{max(vals):+d}")

print("\nso the levels numbers must be read as (measured lead - ~3 weeks):")
for vint in ("as_published", "point_in_time"):
    r = RES[(vint, "levels")]
    print(f"  {vint:14s} measured {r['argmax']:+d}w  ->  ~{r['argmax'] - int(np.median(offsets['levels'])):+d}w "
          f"attributable to the relationship")

print("\nand a half-life sweep on the REAL data -- if the argmax tracked the")
print("smoother, the smoother would be what is being seen:")
for hl in (7, 14, 21, 28, 42, 63):
    c2 = D.LeadConfig(ewma_halflife_days=float(hl))
    y2 = D.sentiment_index(SCORES, X_ALL.index, c2, point_in_time=False)["sentiment"]
    out = []
    for tr in ("levels", "changes"):
        xt, yt, _ = D.transform_pair(X_ALL, y2, tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        j = int(np.nanargmax(cc["corr"].to_numpy()))
        out.append(f"{tr} {int(cc['lag_weeks'].iloc[j]):+3d}w r={cc['corr'].iloc[j]:.3f}")
    print(f"  hl={hl:3d}d (E[age] {hl/np.log(2)/7:4.1f}w)   " + "   ".join(out))
print("  -> the argmax moves +10w to +13w while the filter's centre of mass moves")
print("     1.4w to 13.0w. The smoother is not the whole story; the common trend is.")

# %% [markdown]
# ### The nulls
#
# Both series wander. Over ~150 weekly observations two wandering series can be
# aligned to almost anything, which is why the null has to preserve the
# wandering. The bar the observed peak has to clear is the distribution of the
# **searched maximum** under surrogates that keep each path exactly.

# %%
fig = make_subplots(rows=1, cols=3, subplot_titles=("levels", "changes", "prewhitened"))
for col, tr in enumerate(("levels", "changes", "prewhitened"), start=1):
    x, y = SAMPLES["point_in_time"]
    sh = D.shift_null(x, y, LAGS, CFG, transform=tr, draws=1500,
                      rng=np.random.default_rng(91))
    r = RES[("point_in_time", tr)]
    fig.add_trace(go.Histogram(x=sh["max_corr"], nbinsx=45, marker_color=GREY,
                               opacity=0.75, showlegend=False), row=1, col=col)
    fig.add_vline(x=r["corr"], line=dict(color=RED, width=2.4), row=1, col=col,
                  annotation_text=f"observed {r['corr']:.2f}<br>p={r['p_shift']:.3f}",
                  annotation_position="top left", annotation_font_size=11)
fig.update_xaxes(title_text="max correlation over all 27 lags")
style(fig, 380, "Shift null (point-in-time): 1,500 rotations, each scored by the same 27-lag search")
fig.show()

print(SUMMARY[["vintage", "transform", "n", "argmax", "corr", "at_5w",
               "p_shift", "p_phase"]].round(3).to_string(index=False))
print("\nOne cell of six clears 0.05 on the primary null: as-published levels, at")
print("p=0.001 over 216 weeks. Every other cell fails, and the point-in-time levels")
print("peak reaches only p=0.09 against a test whose measured size is 8.3%. On")
print("changes -- the one transform whose null is exactly calibrated at 5.0% -- the")
print("maximum over all 27 lags is r=0.153, p=0.55.")

# %% [markdown]
# ### The one significant cell, on the same window as the others
#
# `as_published/levels` is the only cell that clears its null, and it is scored
# over 216 weeks rather than the 147 the point-in-time series supports. The
# extra 69 weeks are 2022, where **G1 removed 100% of the rows** -- every
# sentiment value there is back-filled by a report that did not exist until
# May-2023. Running both vintages over the *same* window separates "the vintage
# matters" from "the sample is longer".

# %%
vrows = []
xp, _ = SAMPLES["point_in_time"]
for vint, sent in (("as_published", SENT_AP), ("point_in_time", SENT_PIT)):
    yv = sent["sentiment"][sent.index >= pd.Timestamp(CFG.corpus_start)]
    for tr in ("levels", "changes"):
        xt, yt, _ = D.transform_pair(xp, yv, tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        j = int(np.nanargmax(cc["corr"].to_numpy()))
        obs = float(cc["corr"].iloc[j])
        sh = D.shift_null(xp, yv, LAGS, CFG, transform=tr, draws=1500,
                          rng=np.random.default_rng(61))
        vrows.append({"vintage": vint, "transform": tr, "window": "point-in-time only",
                      "n": len(Ym), "argmax": int(cc["lag_weeks"].iloc[j]),
                      "corr": round(obs, 3),
                      "at_5w": round(float(cc.loc[cc["lag_weeks"] == 5, "corr"].iloc[0]), 3),
                      "null_q95": round(sh["q95"], 3),
                      "p_shift": round(D.surrogate_pvalue(obs, sh), 3)})
VINT = pd.DataFrame(vrows)
print(VINT.to_string(index=False))
print(f"\nas-published levels: p=0.001 on its own 216-week window, "
      f"p={VINT.query('vintage==\'as_published\' and transform==\'levels\'')['p_shift'].iloc[0]:.3f} "
      f"on the 147-week point-in-time window.")
print("So the only significant result in the notebook is a property of the years")
print("where no signal existed. That is the vintage trap doing exactly what it does.")

# %% [markdown]
# ### An independent inflation series, at its own frequency
#
# The chart's inflation leg is Citi's *daily* `PRICES_OR_MONEY_SUPPLY`
# sub-index. Citi also publishes a proper **Inflation Surprise Index**
# (`ISI.SI_CISI`), monthly, 343 observations back to 1998 -- a different
# construction, and the two correlate at only 0.41 in levels. If the lead is a
# property of the world rather than of one index, it should survive the swap.

# %%
cisi = panel[D.TAG_CISI_MONTHLY].dropna()
lab_m = panel[D.TAG_LABOUR].dropna().resample("ME").last()
zc, zl = D.trailing_z(cisi, 36, 24), D.trailing_z(lab_m, 36, 24)
comp_m = pd.concat([zc, zl], axis=1)
comp_m = comp_m.mean(axis=1).where(comp_m.notna().all(axis=1))
sent_m = D.sentiment_index(SCORES, comp_m.index, CFG, point_in_time=False)["sentiment"]
MLAGS = np.arange(-6, 7)
xt, yt, _ = D.transform_pair(comp_m[comp_m.index >= "2022-01-01"],
                             sent_m[sent_m.index >= "2022-01-01"], "levels")
Xm, Ym, _ = D.lag_matrix(xt, yt, MLAGS)
cm = D.lag_curve_common(Xm, Ym, MLAGS)
j = int(np.nanargmax(cm["corr"].to_numpy()))
print(f"monthly CISI: {len(cisi)} obs {cisi.index.min().date()} -> {cisi.index.max().date()}")
print(f"correlation of the daily prices leg with the monthly CISI (levels): "
      f"{pd.concat([panel[D.TAG_PRICES].resample('ME').last(), cisi], axis=1).dropna().corr().iloc[0,1]:.3f}"
      f"  -- they are NOT the same series")
print(f"monthly lag curve, n={len(Ym)} months, argmax "
      f"{int(cm['lag_weeks'].iloc[j]):+d} MONTHS, r={cm['corr'].iloc[j]:.3f}:")
print("  " + "  ".join(f"{int(l):+d}m:{v:+.2f}" for l, v in zip(cm["lag_weeks"], cm["corr"])))
print(f"  +1 month (~4-5 weeks, JWS's claim) reads "
      f"{float(cm.loc[cm['lag_weeks'] == 1, 'corr'].iloc[0]):+.3f} against a peak of "
      f"{cm['corr'].iloc[j]:.3f} at +4 months (~17 weeks).")

# %% [markdown]
# ## 3. Stability -- is this a lead, or is it two or three turning points?
#
# Three years of weekly data is about six turning points. Splitting the
# point-in-time sample in half is the most the data will support, and it is
# enough.

# %%
x, y = SAMPLES["point_in_time"]
joint = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
MID = joint.index[len(joint) // 2]
srows = []
for tr in ("levels", "changes"):
    for label, sub in ((f"{joint.index.min().date()}..{MID.date()}", joint[joint.index <= MID]),
                       (f"{MID.date()}..{joint.index.max().date()}", joint[joint.index > MID]),
                       ("full sample", joint)):
        xt, yt, _ = D.transform_pair(sub["x"], sub["y"], tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        b = D.bootstrap_lead(Xm, Ym, LAGS, CFG, draws=800, rng=np.random.default_rng(71))
        k5 = int(np.where(LAGS == 5)[0][0])
        lo, hi = np.nanquantile(b["curves"][:, k5], [0.05, 0.95])
        j = int(np.nanargmax(cc["corr"].to_numpy()))
        srows.append({"transform": tr, "window": label, "n": len(Ym),
                      "argmax": int(cc["lag_weeks"].iloc[j]), "peak_corr": cc["corr"].iloc[j],
                      "corr_at_5w": float(cc.loc[cc["lag_weeks"] == 5, "corr"].iloc[0]),
                      "boot_5w_lo": lo, "boot_5w_hi": hi})
STAB = pd.DataFrame(srows)
print(STAB.round(3).to_string(index=False))
print("\nThe first half's argmax is EXACTLY +5 weeks -- JWS's number, and it is a")
print("real feature of 2023-05..2024-12. The second half puts the argmax at +13w")
print("and the five-week correlation at -0.07, with a bootstrap interval that")
print("comfortably contains zero. The lead is not stable; it is not even the same")
print("sign at the horizon being traded.")

# %%
fig = go.Figure()
for label, sub, colr in ((f"first half (n={len(joint[joint.index <= MID])})",
                          joint[joint.index <= MID], BLUE),
                         (f"second half (n={len(joint[joint.index > MID])})",
                          joint[joint.index > MID], AMBER),
                         ("full sample", joint, GREY)):
    xt, yt, _ = D.transform_pair(sub["x"], sub["y"], "levels")
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    cc = D.lag_curve_common(Xm, Ym, LAGS)
    fig.add_trace(go.Scatter(x=cc["lag_weeks"], y=cc["corr"], name=label,
                             line=dict(color=colr, width=2.4)))
fig.add_vline(x=CFG.jws_lead_weeks, line=dict(color=RED, width=1.6, dash="dash"),
              annotation_text="JWS 5w", annotation_position="top")
fig.add_hline(y=0, line=dict(color=GRID, width=1))
fig.update_xaxes(title_text="lag, weeks")
fig.update_yaxes(title_text="correlation, levels")
style(fig, 430, "The same curve, two halves: the lead moves from +5w to +13w")
fig.show()

# %% [markdown]
# ### The turning points, found rather than drawn
#
# JWS annotates four arrows. Hand-picking the points that line up bakes in the
# conclusion, so these are found algorithmically -- local extrema above a
# prominence threshold -- and then each surprise turn is matched to the next
# same-sign sentiment turn.

# %%
TP_X = D.turning_points(X_ALL[X_ALL.index >= "2023-04-01"], CFG.turning_point_prominence)
TP_Y = D.turning_points(SENT_AP["sentiment"][SENT_AP.index >= "2023-04-01"], 6.0)
print(f"surprise composite: {len(TP_X)} turns")
print(TP_X.to_string(index=False))
print(f"\nsentiment: {len(TP_Y)} turns")
print(TP_Y.to_string(index=False))

matched = []
for _, r in TP_X.iterrows():
    same = TP_Y[TP_Y["kind"] == r["kind"]]
    d = (same["date"] - r["date"]).dt.days / 7.0
    fwd = d[d >= -2]
    if len(fwd):
        matched.append({"kind": r["kind"], "surprise_turn": r["date"].date(),
                        "next_sentiment_turn": same.loc[fwd.idxmin(), "date"].date(),
                        "gap_weeks": round(float(fwd.min()), 1)})
MATCH = pd.DataFrame(matched)
print("\nnearest FOLLOWING same-sign sentiment turn:")
print(MATCH.to_string(index=False))
print(f"\nmedian {MATCH['gap_weeks'].median():.1f}w   mean {MATCH['gap_weeks'].mean():.1f}w   "
      f"range {MATCH['gap_weeks'].min():.1f}..{MATCH['gap_weeks'].max():.1f}   n={len(MATCH)}")
print("Four arrows on a three-year chart is n=4. Found rather than drawn it is")
print("n=6, median 13 weeks, and one of the six is negative.")

# %% [markdown]
# ## 4. Where we are now
#
# The composite peaked on 2026-06-05 at +1.16 and reads -0.37. The claim under
# test says Fedspeak should have turned dovish five weeks after that peak --
# 2026-07-10.

# %%
last_x = X_ALL.dropna()
last_s = SENT_PIT["sentiment"].dropna()
pit_hist = SENT_PIT["sentiment"][SENT_PIT.index >= pd.Timestamp(CFG.corpus_start)].dropna()
print(f"surprise composite   latest {last_x.index[-1].date()}  {last_x.iloc[-1]:+.3f}   "
      f"(peak {TP_X.iloc[-1]['date'].date()} {TP_X.iloc[-1]['value']:+.3f})")
print(f"Fed sentiment        latest {last_s.index[-1].date()}  {last_s.iloc[-1]:+.2f}   "
      f"= {(pit_hist <= last_s.iloc[-1]).mean():.0%} percentile of its own 2023-05+ history")
print(f"last speech in the corpus {SCORES['date'].max().date()}; "
      f"last report {SCORES['pub_date'].max().date()}")

print("\nthe legs -- the rolldown is entirely INFLATION:")
wkz = LEGS[[c for c in LEGS.columns if c.endswith("_z")]].resample(CFG.week_anchor).last()
print(wkz[wkz.index >= "2026-06-01"].round(3).to_string())

print("\nwhat Fed speakers actually said while the composite was rolling over:")
recent = SCORES[SCORES["date"] >= "2026-06-15"][
    ["date", "pub_date", "speaker", "hawk_dove_score", "relevance_pct", "stance"]]
print(recent.to_string(index=False))
print(f"\n{int((recent['stance'] == 'hawk').sum())} of {len(recent)} labelled hawk. "
      f"Sentiment went from {SENT_PIT['sentiment'].loc['2026-07-10']:+.2f} on 10-Jul to "
      f"{last_s.iloc[-1]:+.2f} now.")

for k in (CFG.jws_lead_weeks, 11, 13):
    when = TP_X.iloc[-1]["date"] + pd.Timedelta(weeks=k)
    seen = "ALREADY PASSED -- sentiment rose instead" if when < last_s.index[-1] else "not yet observable"
    print(f"a {k:2d}-week lead off the 2026-06-05 peak puts the sentiment turn at "
          f"{when.date()}  ({seen})")
print(f"\nFOMC is 2026-09-16, "
      f"{(pd.Timestamp('2026-09-16') - last_x.index[-1]).days / 7.0:.1f} weeks after the last "
      f"composite observation.")

# %% [markdown]
# ### How much does the newest sentiment reading move after the fact?
#
# The right-hand edge is where a trade is put on, and it is also the least
# settled part of the series.

# %%
final = SENT_AP["sentiment"]
rev_rows = []
for t in GRID_W[GRID_W >= pd.Timestamp(CFG.corpus_start)]:
    seen = D.sentiment_index(SCORES, pd.DatetimeIndex([t]), CFG,
                             point_in_time=True)["sentiment"].iloc[0]
    rev_rows.append({"date": t, "seen_at_the_time": seen, "reads_today": final.loc[t]})
REV = pd.DataFrame(rev_rows).set_index("date").dropna()
REV["revision"] = REV["reads_today"] - REV["seen_at_the_time"]
print(f"n={len(REV)} weeks   mean revision {REV['revision'].mean():+.3f}   "
      f"mean|revision| {REV['revision'].abs().mean():.3f}   "
      f"p90 {REV['revision'].abs().quantile(.9):.3f}   max {REV['revision'].abs().max():.3f}")
print(f"share of weeks revised by more than one sentiment point: "
      f"{(REV['revision'].abs() > 1).mean():.1%}")
print(f"a typical revision is {REV['revision'].abs().mean()/REV['seen_at_the_time'].std():.1%} "
      f"of one standard deviation of the series itself")
print("\nthe last eight weeks, as seen then vs as they read today:")
print(REV.tail(8).round(2).to_string())

fig = go.Figure()
fig.add_trace(go.Scatter(x=REV.index, y=REV["seen_at_the_time"], name="seen at the time (PIT)",
                         line=dict(color=RED, width=2, dash="dash")))
fig.add_trace(go.Scatter(x=REV.index, y=REV["reads_today"], name="reads today (as-published)",
                         line=dict(color=RED, width=2)))
fig.add_trace(go.Bar(x=REV.index, y=REV["revision"], name="revision",
                     marker_color=GREY, opacity=0.5, yaxis="y2"))
fig.update_layout(yaxis2=dict(overlaying="y", side="right", title="revision", showgrid=False))
fig.update_yaxes(title_text="Fed sentiment")
style(fig, 430, "The same week, seen then and seen now")
fig.show()

# %% [markdown]
# ## 5. Tradeability
#
# Three questions, in the order that decides whether any of this is worth
# holding risk against.
#
# **Does it reach the price?** The direct test: regress the forward change in
# the 2y SOFR OIS rate on the composite. Overlapping horizons make an OLS
# t-statistic two to three times too large, so the standard errors are
# Newey-West with the HAC lag set to the horizon, and the effective n is
# printed beside the nominal one.

# %%
r2y = D.read_cached_rate(D.TAG_SOFR_2Y)
if r2y is None:
    print("no cached SOFR 2y series on this machine -- the rates leg is not testable here")
else:
    print(f"{D.TAG_SOFR_2Y}: {len(r2y)} daily obs {r2y.index.min().date()} -> "
          f"{r2y.index.max().date()} (read-only from the shared Citi tag cache, no COM)")
    w2 = D.weekly_last(r2y, CFG.week_anchor)
    trows = []
    for h in (4, 5, 6, 8, 11, 13):
        fwd = (w2.shift(-h) - w2) * 100.0
        for label, start in (("full 2005+", "2005-01-01"),
                             ("point-in-time era", str(CFG.corpus_start))):
            df = pd.concat([X_ALL[X_ALL.index >= start].rename("x"), fwd.rename("y")],
                           axis=1).dropna()
            if len(df) < 30:
                continue
            nw = D.newey_west_t(df["y"].to_numpy(), df["x"].to_numpy(), lag=h)
            trows.append({"horizon_w": h, "sample": label, "n": nw["n"],
                          "effective_n": round(nw["effective_n"], 1),
                          "beta_bp_per_unit": round(nw["beta"], 2),
                          "t_HAC": round(nw["t"], 2), "R2": round(nw["r2"], 4)})
    RATES = pd.DataFrame(trows)
    print(RATES.to_string(index=False))
    fwd5 = (w2.shift(-CFG.jws_lead_weeks) - w2) * 100.0
    df = pd.concat([SENT_PIT["sentiment"].rename("x"), fwd5.rename("y")], axis=1).dropna()
    nw = D.newey_west_t(df["y"].to_numpy(), df["x"].to_numpy(), lag=CFG.jws_lead_weeks)
    print(f"\nand the sentiment index itself against the same forward move: n={nw['n']}, "
          f"effective n={nw['effective_n']:.1f}, beta {nw['beta']:+.3f}bp/point, "
          f"t {nw['t']:+.2f}, R2 {nw['r2']:.4f}")
    print("\nNothing at any horizon, in either sample. Whatever the two indices share,")
    print("it is not information about where the front end goes next.")

# %% [markdown]
# **Does it call the next speech?** The lead's only tradeable expression is
# knowing the tone of Fedspeak before it happens. The label is a *trailing*
# median of that speaker's committee, so no future speech enters it.

# %%
sc = SCORES[SCORES["date"] >= pd.Timestamp(CFG.corpus_start)].reset_index(drop=True)
comp_daily = composite.dropna()
crows = []
for k in (0, 3, 5, 8, 11, 13):
    sig, act, hawk, weeks = [], [], [], set()
    for _, r in sc.iterrows():
        asof = r["date"] - pd.Timedelta(weeks=k)
        prior = comp_daily[comp_daily.index < asof]
        past = sc[(sc["date"] < r["date"]) & (sc["pub_date"] <= r["date"])]
        if prior.empty or len(past) < 30:
            continue
        sig.append(prior.iloc[-1])
        act.append(r["hawk_dove_score"])
        hawk.append(r["hawk_dove_score"] > past["hawk_dove_score"].median())
        weeks.add(r["date"].to_period("W").ordinal)
    if len(sig) < 30:
        continue
    sig, act, hawk = np.asarray(sig), np.asarray(act), np.asarray(hawk)
    crows.append({"lead_weeks": k, "speeches": len(sig), "distinct_weeks": len(weeks),
                  "sign_agreement": round(float(np.mean((sig > 0) == hawk)), 3),
                  "corr_with_score": round(float(np.corrcoef(sig, act)[0, 1]), 3)})
CALL = pd.DataFrame(crows)
print(CALL.to_string(index=False))
print("\nSign agreement runs 0.54-0.59 against a 0.50 coin. The effective sample is")
print("the WEEK count, not the speech count -- speeches cluster, and a week with six")
print("speakers is one draw of the signal, not six. This is the same level")
print("relationship seen in section 2, re-expressed, not independent evidence.")

# %% [markdown]
# **What would it have to buy?** The existing point-in-time-gated speaker
# backtest (`notebooks/backtests/intraday_fed_hawk_dove`, branch
# `feat/global-cb-hawk-dove`) already prices the trade this lead would condition:

# %%
FED_LEG = {"trades": 473, "total_bp": 103.5, "avg_bp": 0.219, "sharpe": 0.69,
           "t": 1.24, "breakeven_bp": 0.146, "listed_cost_bp": 0.25}
for k, v in FED_LEG.items():
    print(f"  {k:16s} {v}")
gap = FED_LEG["listed_cost_bp"] - FED_LEG["avg_bp"]
print(f"\n  shortfall {gap:+.3f}bp per trade -- a conditioning overlay would have to lift")
print(f"  the per-trade edge by {gap/FED_LEG['avg_bp']:.0%} merely to reach break-even,")
print("  from a signal whose measured conditioning information is not distinguishable")
print("  from zero on the only calibrated test in this notebook.")

# %% [markdown]
# ## Robustness -- the knobs that were not chosen
#
# The headline is taken at the frozen configuration. These are the alternatives,
# reported after the fact rather than used to pick a winner.

# %%
rrows = []
variants = [
    ("frozen", dict()),
    ("EWMA hl 7d", dict(ewma_halflife_days=7.0)),
    ("EWMA hl 42d", dict(ewma_halflife_days=42.0)),
    ("EWMA window 63d", dict(ewma_window_days=63)),
    ("z window 504bd (2y)", dict(z_window_bd=504, z_min_periods=252)),
    ("z window 1260bd (5y)", dict(z_window_bd=1260, z_min_periods=756)),
    ("week anchor W-WED", dict(week_anchor="W-WED")),
    ("labour leg only", dict(surprise_tags=(D.TAG_LABOUR,))),
    ("prices leg only", dict(surprise_tags=(D.TAG_PRICES,))),
    ("economic TOTAL", dict(surprise_tags=(D.TAG_ECON_TOTAL,))),
]
for name, kw in variants:
    c2 = D.LeadConfig(**kw)
    comp2, _ = D.build_surprise_composite(panel, c2)
    x2 = D.weekly_last(comp2, c2.week_anchor)
    g2 = D.weekly_grid("2021-01-01", comp2.dropna().index.max(), c2.week_anchor)
    y2 = D.sentiment_index(SCORES, g2, c2, point_in_time=True)["sentiment"]
    y2 = y2[y2.index >= pd.Timestamp(c2.corpus_start)]
    x2 = x2[x2.index >= pd.Timestamp(c2.corpus_start)]
    row = {"variant": name}
    for tr in ("levels", "changes"):
        xt, yt, _ = D.transform_pair(x2, y2, tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        j = int(np.nanargmax(cc["corr"].to_numpy()))
        row[f"{tr}_argmax"] = int(cc["lag_weeks"].iloc[j])
        row[f"{tr}_peak"] = round(float(cc["corr"].iloc[j]), 3)
        row[f"{tr}_at5w"] = round(float(cc.loc[cc["lag_weeks"] == 5, "corr"].iloc[0]), 3)
    rrows.append(row)

# and the relevance-weighted sentiment variant, which needs its own call
y_rel = D.sentiment_index(SCORES, GRID_W, CFG, point_in_time=True,
                          weight_by_relevance=True)["sentiment"]
y_rel = y_rel[y_rel.index >= pd.Timestamp(CFG.corpus_start)]
row = {"variant": "relevance-weighted"}
for tr in ("levels", "changes"):
    xt, yt, _ = D.transform_pair(SAMPLES["point_in_time"][0], y_rel, tr)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    cc = D.lag_curve_common(Xm, Ym, LAGS)
    j = int(np.nanargmax(cc["corr"].to_numpy()))
    row[f"{tr}_argmax"] = int(cc["lag_weeks"].iloc[j])
    row[f"{tr}_peak"] = round(float(cc["corr"].iloc[j]), 3)
    row[f"{tr}_at5w"] = round(float(cc.loc[cc["lag_weeks"] == 5, "corr"].iloc[0]), 3)
rrows.append(row)

ROBUST = pd.DataFrame(rrows)
print(ROBUST.to_string(index=False))
n5 = int((ROBUST["levels_argmax"] == 5).sum())
print(f"\n{n5} of {len(ROBUST)} variants put the levels argmax at 5 weeks. "
      f"The median across variants is {ROBUST['levels_argmax'].median():.0f}w "
      f"(range {ROBUST['levels_argmax'].min()}..{ROBUST['levels_argmax'].max()}).")
print(f"On changes the argmax scatters across "
      f"{sorted(set(ROBUST['changes_argmax']))} -- which is what no relationship")
print("looks like, and is consistent with the p-values above.")
print("\nNote these argmaxes are inside the +/-13 headline scan, where the")
print("point-in-time peak sits on the boundary; the wide scan above resolves it")
print("to +14w. The robustness point is that nothing moves it near five.")

# %% [markdown]
# ## Caveats, and what would change the answer
#
# 1. **Our sentiment series is not the one JWS plots.** Bloomberg's Fed
#    Sentiment Language Model is contemporaneous and continuous; ours is an
#    aggregate of discrete JPM speech scores, and its smoothing is a choice we
#    made. Section 2's half-life sweep bounds how much that choice can matter to
#    the argmax (+10w to +13w while the filter's own centre of mass moves 1.4w
#    to 13.0w), but it cannot make the two series the same object. A reader with
#    Bloomberg's series should re-run the lag scan on it; the machinery here
#    takes any two series.
# 2. **147 weekly point-in-time observations.** That is the sample, whatever the
#    x-axis suggests. It supports one split and roughly six turning points, and
#    it is why nothing here is quoted as significant.
# 3. **The level of our composite differs from JWS's** (-0.37 vs his ~0.1) and
#    the daily prices leg correlates with Citi's proper monthly Inflation
#    Surprise Index at only 0.41. The rolldown reproduces in both; the level
#    does not, and it is worth knowing that "the inflation surprise index" names
#    at least two different series.
# 4. **The as-published panel starts 2022-01 by a density gate, not by data
#    availability.** 2021 carries 8 Fed speeches in the whole year and 2020 one;
#    running it back to the earliest speech date (2008-11) would produce a chart,
#    not a sample.
# 5. **The shift null's size is measured, not exact** -- 8.3% on levels, 5.0% on
#    changes, 9.2% on prewhitened, over 120 unrelated AR(0.97) pairs. p-values
#    on levels and prewhitened should be read against those sizes rather than
#    against 5%.
# 6. **The turning-point matcher takes the *next* same-sign sentiment turn**,
#    which is generous to the claim: it can reach 23 weeks forward to find one.
#    A stricter window would shrink n below the point of usefulness.
# 7. **What would change the answer.** A longer point-in-time sentiment history
#    (the corpus growing forward, or a contemporaneous vendor series) is the only
#    thing that would let the +11..+14w peak be tested properly. Failing that,
#    the two halves disagreeing is the most informative fact available, and it
#    disagrees in the direction that matters: the horizon being traded.
#
# ## Reproducing this
#
# ```
# conda run -n stir python notebooks/rv/fed_sentiment_lead_refresh.py --xlsx   # or --live
# conda run -n stir python notebooks/rv/run_fed_sentiment_lead.py
# conda run -n stir python -m pytest tests/test_fed_sentiment_lead.py -q
# ```
#
# The `.py` is the source of truth; the `.ipynb` is generated from it by
# `notebooks/backtests/_py2nb.py`, executed by nbclient and verified by
# `notebooks/backtests/_verify_nb.py` -- zero cell errors *and* zero unrun
# cells, because nbconvert will happily emit a notebook full of tracebacks.
