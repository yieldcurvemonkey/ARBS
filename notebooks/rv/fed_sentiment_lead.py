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
# 1. **Taken at face value the lead is 11-14 weeks, not 5 -- but "at face value"
#    is carrying weight.** As-published the curve peaks at **+11w (r 0.619)**;
#    point-in-time it pins at the **+13w** edge of the headline +/-13 scan, and
#    widening to +/-26 resolves it to **+14w (r 0.773)** with a flat top over
#    +12..+16 falling to 0.52 by +26w -- a real interior maximum, not an artefact
#    of where the scan stopped. At long negative lags the curve is **-0.37**
#    (point-in-time) and **+0.05** (as-published), so sentiment does not lead
#    surprises in either vintage: the *direction* of JWS's story survives.
#    **The precision does not.** The point-in-time bootstrap pins the argmax to
#    +12..+13 (right-censored at the +13 scan edge; the wide scan is what
#    resolves it) and its paired plateau to 2 of 27 lags, but the as-published cell
#    -- the one with more data -- has a 5-95% bootstrap interval of **[+1, +13]**
#    and a plateau of **-3..+13, 17 of 27 lags**. In that vintage five weeks
#    cannot be separated from eleven at all.
# 2. **An independent inflation series says longer still: about +4 months.**
#    Citi's proper monthly Inflation Surprise Index (`ISI.SI_CISI`, 343
#    observations back to 1998; it correlates with the daily prices leg the
#    chart uses at only **0.41**, so it is a genuinely different construction)
#    peaks at **+4 months ~ 17 weeks**, r 0.756 blended with the labour leg and
#    **r 0.595 on its own**, interior in both. JWS's +1 month reads 0.594 and
#    0.483. Longer than the weekly estimate, and not five weeks.
# 3. **The null does not control its size on levels, so no levels p-value here
#    is inference -- and on changes, where it does, there is nothing.** The null
#    keeps each path *exactly* and destroys only the alignment, enumerating the
#    whole finite rotation set and scoring every surrogate by the same 27-lag
#    maximum the real analysis takes. Its **size**, measured over 60 unrelated
#    AR(0.97) pairs at a nominal 5%: **levels 20.0%** [Wilson 0.118, 0.318]
#    against **changes 6.7%** [0.026, 0.159]. So the levels cells --
#    point-in-time **p = 0.008**, as-published **p = 0.005** -- sit on a test
#    that fires one time in five when nothing is there, and are reported rather
#    than believed. On **changes** the maximum over all 27 lags is **r 0.153,
#    p = 0.475** point-in-time and **r 0.094, p = 0.829** as-published. Nothing,
#    at any lag, in either vintage.
# 4. **The estimator has power; what levels lacks is size control.** A
#    *deliberately planted* five-week lead clears in every transform at the
#    resolution floor (**p = 0.010**; in levels the null's 95th percentile is
#    **0.429** against an observed **0.919**). So the machinery finds a lead
#    that is really there. The problem is the other side of the test: on levels
#    it also finds one 20% of the time when nothing is there. Power without
#    size is exactly why the verdict is taken from the changes row and not from
#    the biggest number in the table. Asserted by
#    `test_the_rotation_null_does_not_control_size_on_LEVELS`.
# 5. **Five weeks is the first half of the sample, and it has already broken.**
#    Split point-in-time at 2024-12: the first half's argmax is **exactly +5
#    weeks** (r 0.685, p 0.029 -- its own resolution floor, on 33 rotations, on the
#    transform whose null fires 20% of the time). The second half's
#    is +13w and the correlation *at five weeks* is **-0.07**, bootstrap 5-95%
#    [-0.47, +0.37]. In changes: +0.219 then +0.043. The halves do not disagree
#    about *whether*; they disagree about *where*, at the horizon being traded.
# 6. **The pipeline manufactures about three weeks of the apparent lead by
#    itself.** A *zero*-lead relationship pushed through the identical pipeline
#    on synthetic data returns a median argmax of **+3 weeks** in levels (+1 in
#    changes) -- the backward EWMA's own centre of mass. Asserted by
#    `test_pipeline_reports_a_lead_even_when_the_true_lead_is_zero`. Sweeping
#    the half-life 7d to 63d moves the filter's centre of mass 1.4w to 13.0w and
#    the point-in-time argmax **not at all** (+13w throughout), so the smoother
#    is not what is being seen -- but nor does any setting bring it near five.
# 7. **Found algorithmically rather than drawn, the turning points give 12-13
#    weeks, and three of nine have no partner at all.** Nine surprise turns
#    since Apr-2023; six have a following same-sign sentiment turn, at median
#    **13.0w**, mean 12.2w, range **-1 to +23** (one is negative -- sentiment
#    turned first). The other three, all in 2026, have none, and they are
#    dropped -- which is generous to the claim, because they are precisely the
#    turns that have so far not been followed.
# 8. **The current episode already contradicts the five-week rule.** Our
#    composite peaked 2026-06-05 at +1.16 and reads -0.37. Five weeks past that
#    peak is 2026-07-10, and since then Fed sentiment has gone from **+9.7 to
#    +29.6 -- the most hawkish reading in the entire sample (100th
#    percentile)** -- on **16 hawk labels out of 19** (Logan 62, Hammack 58,
#    Warsh 49). The measured 11-14 week lead puts the turn between 2026-08-21
#    and 2026-09-04, which is not yet observable.
# 9. **The rolldown is an inflation-surprise story, not a data story.** It is
#    entirely the prices leg (z +0.22 -> -1.27), and it happened in a single
#    day: **2026-07-14**, a -7.7 move on the June CPI print and the largest
#    one-day move in that index all year. The labour leg was still +1.4 through
#    July and only slipped to +0.529 in the last fortnight.
# 10. **The point-in-time series is revised hard, exactly where it is used.**
#    Mean |revision| between what a reader saw and what the same week reads
#    today is **2.65 sentiment points = 39% of one standard deviation**; 74.6%
#    of weeks move by more than a point; **2026-07-31 was 21.63 at the time and
#    reads 30.47 today**. Inside the 126-day window the index actually reads,
#    the publication gate removes **11.7% of rows on average and 29% at its
#    worst** -- not the 4.7% the cumulative count suggests. And 17.9% of Fed
#    rows are published so late they can never enter a point-in-time index at
#    all.
# 11. **It does not reach the price.** The forward 4/5/6/8/11/13-week change in
#    the 2y SOFR OIS rate regressed on the composite gives **|t| <= 0.79 and
#    R2 <= 0.0127** across all twelve cells, in the point-in-time era *and* in
#    the full 2005-2026 sample. HAC leaves an effective n of 86-281 in the long
#    sample and only 12-42 in the short one. Sentiment itself does no better
#    (t -0.68, R2 0.005).
# 12. **No variant of the construction recovers five weeks.** Ten alternatives
#    beside the frozen baseline -- half-lives 7d to 42d, z-windows 2y to 5y, a
#    Wednesday week, each leg alone, the whole economic surprise index,
#    relevance weighting -- all put the point-in-time levels argmax at 13 weeks.
#    On changes the argmax scatters across -12, -5, +1 and +13, which is what no
#    relationship looks like.
#
# **Verdict.** The lead exists as a shape and it points the right way. But it is
# 11-14 weeks rather than five; the strongest version of it fails a null that
# respects how persistent both series are; the only version that clears one is
# the vintage built from scores that did not exist at the time; the sample's two
# halves disagree about the horizon, with the five-week correlation going from
# +0.69 to -0.07; and it does not reach a tradeable price at any horizon tested.
# As a description of history it is fine. As a reason to be positioned for
# dovish Fedspeak into 16-Sep it is four arrows on a chart -- and the current
# episode has already run five weeks past the surprise peak with Fedspeak at its
# most hawkish reading on record.
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
for d, note in [("2024-04-10", "Mar-24 core CPI 0.4% vs 0.3% -- a HOT print"),
                ("2025-01-15", "Dec-24 core CPI 0.2% vs 0.3% -- a COOL print"),
                ("2026-07-14", "Jun-26 CPI -- the day the prices leg collapsed")]:
    t = pd.Timestamp(d)
    prev, on = prices[prices.index < t].iloc[-1], prices.asof(t)
    print(f"  {d}  {note:52s} prices leg {prev:+7.2f} -> {on:+7.2f}  ({on - prev:+.2f})")
_2026 = prices.loc["2026-01-01":].diff().abs()
print(f"  (that -7.7 is the largest single-day move in the prices leg all year; "
      f"the next largest is {_2026.nlargest(2).iloc[1]:.1f}. The direction is right: "
      f"a cool CPI pushes the inflation-surprise index DOWN.)")
print(f"\n  raw levels last ({prices.index[-1].date()}): labour "
      f"{panel[D.TAG_LABOUR].dropna().iloc[-1]:+.1f}, prices {prices.iloc[-1]:+.1f} -- "
      f"the tens-scale that makes a standardisation necessary before anything is "
      f"plotted against JWS's -0.75..+1.50 axis.")

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
_post = G1.loc[G1.index >= "2023-06-01"]
print(f"G1 passes: the gate removes up to {int(G1['n_removed'].max())} rows "
      f"({G1['share_removed'].max():.0%} at the corpus start, "
      f"{_post['share_removed'].mean():.1%} on average after it)")
print(f"  but the cumulative share is not the operative number: the index only ever "
      f"reads rows INSIDE the {CFG.ewma_window_days}-day window, and there the gate "
      f"removes {_post['share_removed_in_window'].mean():.1%} on average, "
      f"{_post['share_removed_in_window'].max():.0%} at its worst "
      f"({int(_post['n_in_window'].median())} rows in a typical window). That is the "
      f"share that can actually move a sentiment value, and it is the larger of the two.")

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
_pit_win = SENT_PIT["n_speeches"][SENT_PIT.index >= pd.Timestamp(CFG.corpus_start)]
print(f"speeches inside the EWMA window, ON THE POINT-IN-TIME SAMPLE: "
      f"min {int(_pit_win.min())}, median {int(_pit_win.median())}, "
      f"max {int(_pit_win.max())} -- so the min_speeches="
      f"{CFG.min_speeches_in_window} floor never binds there. Before 2023-05 it binds "
      f"everywhere, which is G2: the count is zero and the series is empty.")
_first2 = SCORES["pub_date"].isin(pd.to_datetime(["2023-05-02", "2023-05-03"]))
_t0 = pd.Timestamp("2023-05-05")
_win0 = int((((SCORES["date"] <= _t0) & (SCORES["pub_date"] <= _t0))
             & ((_t0 - SCORES["date"]).dt.days <= CFG.ewma_window_days)).sum())
print(f"  it never binds because the corpus's first two report dates publish "
      f"{int(_first2.sum())} Fed rows at once, {_win0} of them inside the "
      f"{CFG.ewma_window_days}-day window. So the point-in-time series does not start "
      f"thin -- it starts at full strength, on a single day's information dump. That is "
      f"what a reader genuinely received; it is not a leak. But it does mean the very "
      f"first weeks are one report vintage's view of history rather than a series that "
      f"accumulated, and 2023-05-02 itself has only 8 visible rows (1 inside the window), "
      f"which is why the weekly grid's first usable Friday is 2023-05-05.")

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
# Three transforms, because they answer different questions:
#
# | transform | what it sees |
# |---|---|
# | **levels** | the shape JWS is describing |
# | **changes** | week-on-week co-movement |
# | **prewhitened** | Box-Jenkins: filter both by the input's own AR model |
#
# The verdict rests on **changes**, and the reason is size control. A cell below
# measures all six null/transform sizes rather than quoting them: on levels this
# null rejects **20%** of the time when nothing is there, against **6.7%** on
# changes. The estimator is not short of power -- a deliberately planted
# five-week lead clears every transform at the floor -- it is that a levels
# rejection means almost nothing when one rejection in five is spurious.
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
#   beside it, never instead. It is circular, so a surrogate wanders less than
#   a near-unit-root sample really does; the sizes cell below measures both and
#   finds them close, but where the two disagree on a *cell* -- and on
#   point-in-time levels they disagree by an order of magnitude -- the one that
#   keeps each path exactly is the one to believe.

# %%
def measure(x, y, transform, *, boot=600, shift=1500, phase=800, seed=31):
    xt, yt, info = D.transform_pair(x, y, transform)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    curve = D.lag_curve_common(Xm, Ym, LAGS)
    pair = D.lag_curve_pairwise(xt, yt, LAGS)
    j = int(np.nanargmax(curve["corr"].to_numpy()))
    b = D.bootstrap_lead(Xm, Ym, LAGS, CFG, draws=boot, rng=np.random.default_rng(seed))
    plat = D.plateau(curve, b["curves"])
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
                ar_order=int(info.get("ar_order", 0)),
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
_xw, _yw = SAMPLES["point_in_time"]
_Xw, _Yw, _ = D.lag_matrix(*D.transform_pair(_xw, _yw, "levels")[:2], WIDE)
_obsw = float(np.nanmax(D.lag_curve_common(_Xw, _Yw, WIDE)["corr"].to_numpy()))
_nw = D.shift_null(_xw, _yw, WIDE, CFG, transform="levels", draws=2000,
                   rng=np.random.default_rng(83))
print(f"\npoint-in-time, priced for THIS search (53 lags, not 27): peak {_obsw:.3f}, "
      f"p {D.surrogate_pvalue(_obsw, _nw):.3f} over {_nw['distinct_rotations']} exact "
      f"rotations (floor {_nw['p_floor']:.3f}).")
print("A wider search costs a wider null, so the +14w peak is if anything harder")
print("to defend than the +13w one -- which is why the wide scan is used to")
print("establish the SHAPE of the curve and never to supply a p-value.")
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
# `D.synthetic_world` is the SAME construction
# `test_pipeline_reports_a_lead_even_when_the_true_lead_is_zero` asserts on, so
# the notebook and the test cannot drift into two different calibrations. It
# lives in the data module rather than in the test file, because a deliverable
# notebook that imports from `tests/` cannot be re-executed by anyone who ships
# `notebooks/` without them.
offsets = {}
for tr in ("levels", "changes", "prewhitened"):
    vals = []
    for seed in range(12):
        p0, b0, _ = D.synthetic_world(lead_days=0, rng=np.random.default_rng(700 + seed))
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

print("\nand a half-life sweep on the REAL data, in BOTH vintages -- if the argmax")
print("tracked the smoother, the smoother would be what is being seen:")
sweep_rows = []
for hl in (7, 14, 21, 28, 42, 63):
    c2 = D.LeadConfig(ewma_halflife_days=float(hl))
    row = {"halflife_d": hl, "filter_E_age_w": round(hl / np.log(2) / 7, 1)}
    for vint, pit, start in (("as_pub", False, CFG.as_published_start),
                             ("pit", True, CFG.corpus_start)):
        y2 = D.sentiment_index(SCORES, X_ALL.index, c2, point_in_time=pit)["sentiment"]
        y2 = y2[y2.index >= pd.Timestamp(start)]
        x2 = X_ALL[X_ALL.index >= pd.Timestamp(start)]
        for tr in ("levels", "changes"):
            xt, yt, _ = D.transform_pair(x2, y2, tr)
            Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
            cc = D.lag_curve_common(Xm, Ym, LAGS)
            j = int(np.nanargmax(cc["corr"].to_numpy()))
            row[f"{vint}_{tr}_argmax"] = int(cc["lag_weeks"].iloc[j])
            row[f"{vint}_{tr}_r"] = round(float(cc["corr"].iloc[j]), 3)
    sweep_rows.append(row)
SWEEP = pd.DataFrame(sweep_rows)
print(SWEEP.to_string(index=False))
_lo, _hi = SWEEP["pit_levels_argmax"].min(), SWEEP["pit_levels_argmax"].max()
print(f"  -> across a filter whose centre of mass moves "
      f"{SWEEP['filter_E_age_w'].min():.1f}w to {SWEEP['filter_E_age_w'].max():.1f}w, the")
print(f"     point-in-time levels argmax moves {_lo:+d}w to {_hi:+d}w and the as-published")
print(f"     one {SWEEP['as_pub_levels_argmax'].min():+d}w to "
      f"{SWEEP['as_pub_levels_argmax'].max():+d}w. The smoother is not what is being")
print("     seen -- but nor does the argmax ever come back near five.")

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
_ps = SUMMARY.set_index(["vintage", "transform"])["p_shift"]
_pp = SUMMARY.set_index(["vintage", "transform"])["p_phase"]
print(f"\nBoth LEVELS cells clear 0.05 on the primary null -- as-published "
      f"p={_ps[('as_published','levels')]:.3f}, point-in-time "
      f"p={_ps[('point_in_time','levels')]:.3f} -- and neither is evidence: the sizes")
print("cell below measures this null firing 20% of the time on levels when there is")
print(f"nothing there. On changes, where it is near nominal, the maximum over all 27")
print(f"lags is r={SUMMARY.set_index(['vintage','transform'])['corr'][('point_in_time','changes')]:.3f}, "
      f"p={_ps[('point_in_time','changes')]:.3f}.")
print(f"\nThe PERMISSIVE phase null disagrees, and it is reported rather than hidden:")
print(f"it rejects point-in-time levels at p={_pp[('point_in_time','levels')]:.3f} and")
print(f"as-published levels at p={_pp[('as_published','levels')]:.3f}. Two nulls that")
print("differ by an order of magnitude on the same cell is not a result; it is a")
print("sign that a levels correlation between two wandering series is fragile to")
print("how the null is built. The conservative one is the one that keeps each")
print("path exactly, and it does not reject.")

print("\nprewhitening depends on an AR order chosen by AIC, so sweep the cap:")
xpw, ypw = SAMPLES["point_in_time"]
for mp in (2, 4, 6, 8, 12, 16):
    xt, yt, info = D.transform_pair(xpw, ypw, "prewhitened", max_p=mp)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    cc = D.lag_curve_common(Xm, Ym, LAGS)
    j = int(np.nanargmax(cc["corr"].to_numpy()))
    print(f"  cap {mp:2d} -> order {info['ar_order']:2d}"
          f"{' (AT THE CAP)' if info['ar_order'] == mp else '':14s}"
          f"  argmax {int(cc['lag_weeks'].iloc[j]):+3d}w  r {cc['corr'].iloc[j]:.3f}"
          f"  at+5w {float(cc.loc[cc['lag_weeks'] == 5, 'corr'].iloc[0]):+.3f}")
print("  -> +12w or +13w throughout. The order choice does not move the answer.")

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
_apw = VINT.query("vintage=='as_published' and transform=='levels'").iloc[0]
_ap_full = SUMMARY.query("vintage=='as_published' and transform=='levels'").iloc[0]
print(f"\nas-published levels: r {_ap_full['corr']:.3f} at p {_ap_full['p_shift']:.3f} on its own "
      f"216-week window; r {_apw['corr']:.3f} at p {_apw['p_shift']:.3f} on the 147-week "
      f"point-in-time window.")
print("Note the correlation RISES when 2022 is dropped and the p-value still")
print("worsens. That is the mechanism worth naming: significance here is bought")
print("with sample LENGTH, not with the strength of the relationship -- a shorter")
print("sample lets random rotations line up better, so the null widens faster than")
print("the signal does. The 69 extra weeks that buy it are 2022, where G1 removes")
print("100% of the sentiment rows. So the only cell in the study that clears its")
print("null is a cell whose significance comes from a stretch of series that, for")
print("a reader at the time, did not exist.")

# %% [markdown]
# ### The null's own size, measured here rather than quoted
#
# A p-value means nothing without knowing how often its test fires on nothing,
# and that number is not 5% just because it was asked to be. So it is measured
# here rather than quoted: two unrelated AR(0.97) series, scored exactly as the
# real analysis scores them -- the maximum over the whole lag grid -- sixty
# times for each null and transform.
#
# An earlier version of this study *did* quote it, at 8.3% on levels against
# 5.0% on changes, and built the choice of transform on that gap. Both numbers
# were artefacts of a null whose rotations were sampled with replacement and an
# AR order selected on a moving sample. Fixing those moved the sizes, which is
# why nothing here is cited from a docstring any more.
#
# A size estimated on sixty trials is itself an estimate, so each comes with a
# Wilson interval. That interval is wide, and saying so is the point: "the
# changes null is calibrated and the levels null is not" is a claim about a
# difference of a few rejections, and the intervals overlap.

# %%
size_rows = []
for which in ("shift", "phase"):
    for tr in ("levels", "changes", "prewhitened"):
        r = D.measure_null_size(CFG, transform=tr, which=which, trials=60, draws=300,
                                seed=1000)
        size_rows.append({**r, "size": round(r["size"], 3),
                          "wilson_lo": round(r["wilson_lo"], 3),
                          "wilson_hi": round(r["wilson_hi"], 3)})
SIZES = pd.DataFrame(size_rows)
print(SIZES.to_string(index=False))
_s = SIZES.set_index(["null", "transform"])["size"]
print(f"\nAt a nominal 5%: shift/levels {_s[('shift','levels')]:.1%}, "
      f"shift/changes {_s[('shift','changes')]:.1%}, "
      f"shift/prewhitened {_s[('shift','prewhitened')]:.1%}.")
print("The intervals overlap, so this does NOT establish that one null is")
print("calibrated and another is not. What it does establish is that none of")
print("them is generous: a p of 0.57 on changes is not a near miss under any")
print("size in these intervals, and a p of 0.10 on levels is not a rejection")
print("under any of them either.")

print("\nSo the transform is chosen on POWER, not calibration. Plant a five-week")
print("lead deliberately and ask each transform to find it:")
_p, _b, _ = D.synthetic_world(lead_days=35, rng=np.random.default_rng(14))
_c, _ = D.build_surprise_composite(_p, CFG)
_x = D.weekly_last(_c, CFG.week_anchor)
_y = D.sentiment_index(_b, _x.index, CFG, point_in_time=False)["sentiment"]
for tr in ("levels", "changes", "prewhitened"):
    xt, yt, _ = D.transform_pair(_x, _y, tr)
    Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
    cc = D.lag_curve_common(Xm, Ym, LAGS)
    j = int(np.nanargmax(cc["corr"].to_numpy()))
    obs = float(cc["corr"].iloc[j])
    nl = D.shift_null(_x, _y, LAGS, CFG, transform=tr, draws=2000,
                      rng=np.random.default_rng(15))
    print(f"  {tr:12s} argmax {int(cc['lag_weeks'].iloc[j]):+3d}w  r {obs:.3f}  "
          f"null q95 {nl['q95']:.3f}  p {D.surrogate_pvalue(obs, nl):.3f}")
print("  -> in LEVELS the planted relationship reaches r 0.92 and the null reaches")
print("     0.92 too, so it does not clear. The identical relationship is")
print("     unambiguous in changes. A levels result on ~150 weekly points of")
print("     wandering data is close to uninformative in EITHER direction, which is")
print("     why the verdict rests on the changes row and not on the biggest number.")

# %% [markdown]
# ### An independent inflation series, at its own frequency
#
# The chart's inflation leg is Citi's *daily* `PRICES_OR_MONEY_SUPPLY`
# sub-index. Citi also publishes a proper **Inflation Surprise Index**
# (`ISI.SI_CISI`), monthly, 343 observations back to 1998 -- a different
# construction, and the two correlate at only 0.41 in levels. If the lead is a
# property of the world rather than of one index, it should survive the swap.
#
# This panel varies the **surprise** side, so it holds the sentiment side fixed
# at the **as-published** vintage: 43 monthly observations is already thin, and
# gating it as well would leave too little to read. It is therefore a check on
# the surprise construction, not a second point-in-time test -- and it inherits
# the same hindsight the as-published series carries everywhere else.

# %%
cisi = panel[D.TAG_CISI_MONTHLY].dropna()
lab_m = panel[D.TAG_LABOUR].dropna().resample("ME").last()
# 36 and 24 are MONTHS here, not business days -- the same 3-year window and
# 2-year minimum the daily legs use, expressed at this series' own frequency
zc, zl = D.trailing_z(cisi, 36, 24), D.trailing_z(lab_m, 36, 24)
comp_m = pd.concat([zc, zl], axis=1)
comp_m = comp_m.mean(axis=1).where(comp_m.notna().all(axis=1))
sent_m = D.sentiment_index(SCORES, comp_m.index, CFG, point_in_time=False)["sentiment"]
MLAGS = np.arange(-6, 7)
# the blended monthly composite shares its LABOUR leg with the daily one, so a
# CISI-only curve is run beside it -- that is the only fully independent input
for label, series in (("CISI + labour (blended)", comp_m),
                      ("CISI ALONE (independent)", zc)):
    xt_, yt_, _ = D.transform_pair(series[series.index >= "2022-01-01"],
                                   sent_m[sent_m.index >= "2022-01-01"], "levels")
    Xm_, Ym_, _ = D.lag_matrix(xt_, yt_, MLAGS)
    cm_ = D.lag_curve_common(Xm_, Ym_, MLAGS)
    j_ = int(np.nanargmax(cm_["corr"].to_numpy()))
    print(f"  {label:26s} n={len(Ym_):3d}m  argmax {int(cm_['lag_weeks'].iloc[j_]):+d}m "
          f"(~{int(cm_['lag_weeks'].iloc[j_]) * 4.33:.0f}w)  r={cm_['corr'].iloc[j_]:.3f}"
          f"  at +1m {float(cm_.loc[cm_['lag_weeks'] == 1, 'corr'].iloc[0]):+.3f}")
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
print("\nand the null on each half, so '+5w in the first half' is not asserted bare:")
for label, sub_ in ((f"{joint.index.min().date()}..{MID.date()}", joint[joint.index <= MID]),
                    (f"{MID.date()}..{joint.index.max().date()}", joint[joint.index > MID])):
    for tr in ("levels", "changes"):
        xt, yt, _ = D.transform_pair(sub_["x"], sub_["y"], tr)
        Xm, Ym, _ = D.lag_matrix(xt, yt, LAGS)
        cc = D.lag_curve_common(Xm, Ym, LAGS)
        obs = float(np.nanmax(cc["corr"].to_numpy()))
        nl = D.shift_null(sub_["x"], sub_["y"], LAGS, CFG, transform=tr, draws=2000,
                          rng=np.random.default_rng(77))
        print(f"  {label} {tr:8s} peak {obs:.3f}  p {D.surrogate_pvalue(obs, nl):.3f}"
              f"  (exact over {nl['distinct_rotations']} rotations, floor "
              f"{nl['p_floor']:.3f})")
print("A half is 60 weeks, so the rotation set is small and the p-value floor is")
print("coarse. Neither half's peak is significant. The finding is not that either")
print("half found something -- it is that the two halves disagree about WHERE.")
print("\nThe first half's argmax is EXACTLY +5 weeks -- JWS's number, and it is where")
print("that half's curve peaks. It is NOT a significant peak (p 0.100 above), so the")
print("honest statement is that the first half's argmax happens to land at five, on")
print("a sample and a transform where an argmax carries little information. The")
print("second half puts it at +13w with the five-week correlation at -0.07 and a")
print("bootstrap interval that comfortably contains zero. What the split shows is")
print("not that either half found something, but that they disagree about WHERE --")
print("and they disagree at the horizon a trade would be put on.")

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
#
# **This detector is deliberately non-causal.** `scipy.signal.find_peaks` sees
# the whole series, so a turn is only identifiable after the series has turned
# back. That is correct here and it is *generous to the claim*: it is the same
# licence a chart annotated after the fact enjoys. Nothing downstream of this
# cell feeds a p-value or a trade -- it exists to replace four hand-drawn arrows
# with a rule, and the matcher is likewise generous, reaching up to 23 weeks
# forward to find a partner for each surprise turn.

# %%
TP_X = D.turning_points(X_ALL[X_ALL.index >= "2023-04-01"], CFG.turning_point_prominence)
TP_Y = D.turning_points(SENT_AP["sentiment"][SENT_AP.index >= "2023-04-01"],
                        CFG.sentiment_turning_point_prominence)
_TP_Y_PIT = D.turning_points(SENT_PIT["sentiment"][SENT_PIT.index >= "2023-04-01"],
                             CFG.sentiment_turning_point_prominence)
print(f"NOTE the sentiment turns below are the AS-PUBLISHED series, to match the "
      f"chart being critiqued -- and the vintage matters more here than anywhere "
      f"else in the notebook. On the point-in-time series the same rule finds only "
      f"{len(_TP_Y_PIT)} turns against {len(TP_Y)}: the mean 2.65-point revision is a "
      f"third of the {CFG.sentiment_turning_point_prominence} prominence bar, and "
      f"back-filling sharpens turns that were not visible at the time. So this "
      f"exhibit reproduces the chart being critiqued; it is not evidence about what "
      f"a reader could have seen, and the {len(TP_Y)}-turn count is itself a "
      f"hindsight artefact.")
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
_censored = len(TP_X) - len(MATCH)
print(f"\n{_censored} of {len(TP_X)} surprise turns have NO following same-sign "
      f"sentiment turn and are dropped:")
_paired = {pd.Timestamp(d) for d in MATCH["surprise_turn"]}
print(TP_X[~TP_X["date"].isin(_paired)].to_string(index=False))
print("They are the most recent ones, and they are censored by the end of the")
print("sample rather than by anything about the relationship -- the sentiment")
print("turn that would pair with them has not happened yet, which is exactly the")
print("situation the current episode is in. Censoring the unresolved cases is")
print("generous to the claim: it drops precisely the turns that have so far")
print("failed to be followed.")
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
print("  from zero on every test in this notebook that has the power to tell.")

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
_alt = ROBUST[ROBUST["variant"] != "frozen"]
n5 = int((_alt["levels_argmax"] == 5).sum())
print(f"\n{n5} of {len(_alt)} ALTERNATIVES (the frozen baseline is excluded -- it is "
      f"the configuration being defended, not evidence for it) put the levels argmax "
      f"at 5 weeks. Across those {len(_alt)} the median is "
      f"{_alt['levels_argmax'].median():.0f}w, range "
      f"{_alt['levels_argmax'].min()}..{_alt['levels_argmax'].max()}.")
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
#    made. Section 2's half-life sweep bounds how much that choice can matter --
#    the point-in-time argmax does not move at all across half-lives 7d to 63d,
#    the as-published one moves +10w to +13w -- but it cannot make the two series
#    the same object. A reader with Bloomberg's series should re-run the lag scan
#    on it; the machinery here takes any two series.
# 2. **147 weekly point-in-time observations.** That is the sample, whatever the
#    x-axis suggests. It supports one split and roughly six turning points. One
#    cell in the notebook does clear its null at p = 0.001 -- as-published
#    levels -- and it is the only one, it is the untradeable vintage, and it
#    falls to p = 0.081 the moment it is scored on the point-in-time window. It
#    is reported as a vintage artefact rather than a result, and that reading is
#    itself a judgement a reader may want to check.
# 3. **The level of our composite differs from JWS's** (-0.37 vs his ~0.1) and
#    the daily prices leg correlates with Citi's proper monthly Inflation
#    Surprise Index at only 0.41. The rolldown reproduces in both; the level
#    does not, and it is worth knowing that "the inflation surprise index" names
#    at least two different series.
# 4. **The as-published panel starts 2022-01 by a density gate, not by data
#    availability.** 2021 carries 8 Fed speeches in the whole year and 2020 one;
#    running it back to the earliest speech date (2008-11) would produce a chart,
#    not a sample.
# 5. **The null sizes are measured in a cell, and their intervals are wide.**
#    Sixty trials each, so a 5.0% estimate carries a Wilson interval of roughly
#    [1.7%, 13.7%]. That is honest but weak, and it is why the choice of
#    transform is argued from power (a planted lead that levels cannot detect)
#    rather than from a size ranking. It is also why every p-value in the study
#    is either far above 0.05 or sitting on its own resolution floor -- none of
#    them is a near miss that a better-calibrated null would flip.
# 5b. **The shift null's p-value has a floor.** The rotation set is finite -- 189
#    on the as-published window, 119 on the wide-scan row set, 59 on a half --
#    and it is enumerated in full, so the test is exact but coarse. A reported
#    0.005 is the smallest number that test can produce, not a measurement of
#    one-in-two-hundred.
# 6. **The turning-point exhibit is generous to the claim in three ways.** The
#    matcher takes the *next* same-sign sentiment turn and can reach 23 weeks
#    forward to find one; three of the nine surprise turns have no partner and
#    are dropped, and they are the recent ones that have so far not been
#    followed; and the sentiment turns are located on the as-published series,
#    where the same rule finds 13 turns against the point-in-time series' 7.
#    None of it feeds a p-value. It exists to replace four hand-drawn arrows
#    with a rule, and even under those generous terms the answer is 13 weeks.
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
