# %% [markdown]
# # When Fedspeak detaches from the data, is there a trade?
#
# Two studies already on `main` measured the relationship between an
# equally-weighted inflation + labour surprise composite and a Fed sentiment
# index, and answered the question JWS Macro #8 asked. The lead is **+11 to +13
# weeks on 2023-2026, not five**; that window is a **twenty-year maximum**; what
# survives twenty-one years is **+1 to +2 weeks, r ~ 0.12**; and the *level* of
# either series does not reach the price.
#
# This notebook asks the question those two did not. Not "does sentiment follow
# the data", but:
#
# > **when sentiment DETACHES from the data, does the front end pay you to bet
# > on the gap closing?**
#
# A residual is a genuinely different object from a level, so the prior is not
# decisive. Four constructions of "detached", four lead-alignments, four entry
# thresholds, four holding periods and eight instruments -- **2048 cells** --
# are searched, and the search is paid for by a null that is scored on exactly
# the statistic the search maximises.
#
# ## What was measured -- the numbers up front
#
# *(Every figure here is restated by a cell below, and the last cell of the
# notebook prints all of them together in exactly the form the prose quotes them.
# If the cells and this summary ever disagree, the cells are what ran.
# `_audit_fed_detachment_numbers.py` enforces that as part of the build.)*
#
# **The answer is no, and it is not close.**
#
# 1. **On the tradeable sample the best of 2048 cells is beaten by a random
#    misalignment of its own signal 98% of the time.** Best weekly Sharpe
#    **0.1903** (annualised **1.3721**) against a rotation null whose **median is
#    0.2445** and whose 95th percentile is **0.3036**: **p = 0.9773** on an
#    exhaustive 43-rotation test, i.e. the observed maximum sits at the **2nd**
#    percentile of its own null. The permissive phase-randomised null agrees:
#    **p = 0.9601**. Deflated Sharpe **0.0226** against an SR0 of **0.3113**.
# 2. **The pre-registered cell, written down before the grid ran, earns
#    +1.891bp per trade net over 23 trades with a t-statistic of 0.2884.** Gap at
#    k = 0, one sigma, four weeks, third deferred SR3, faded. Hit rate **47.83%**,
#    weekly Sharpe **0.0267**. Its entire **+43.5bp** is **one trade** -- the
#    largest of its seven episodes is a single 2024-07-05 entry worth
#    **+87.0bp**, and the other **22** trades together lose **43.5bp**.
# 3. **This is not a cost problem.** Set transaction costs to **ZERO** and the
#    grid's best cell reads **0.2054** against a null median of **0.2562**:
#    **p = 0.9773**, unchanged. A round trip costs 0.50bp against a per-trade
#    standard deviation of **24.4bp** at the four-week horizon -- **2.0%** of the
#    noise. Every previous verdict on this desk died at the cost line. This one
#    dies well before it.
# 4. **Twenty-one years does not rescue it.** FedLock V3 -- a different judge
#    model, dated speeches back to 1985 -- against the 2y SOFR OIS over **1081
#    weeks**: best **0.0858**, null median **0.0769**, **p = 0.3146** (spectral
#    **0.3242**), DSR **0.0130**. On SR3 from 2018, **432 weeks**: best **0.1719**,
#    null median **0.1398**, **p = 0.0845** (spectral **0.1172**), DSR **0.1248**.
#    The best of the three samples is the one whose sentiment side can never be
#    gated, which is the ordering you would expect if hindsight in the scoring
#    were contributing something.
# 5. **The winning cells look significant one at a time, which is the whole point
#    of the exercise.** A shared sign-flip test on the JPM winner alone gives
#    **p = 0.0309**; on the FedLock 21-year winner **p = 0.0043**; on the FedLock
#    SR3 winner **p = 0.0003**, off **106** trades at **+6.783bp** each with a
#    t-statistic of **3.7338**. Every one of those is the maximum of a 256 or
#    2048-cell search, and the search-corrected p-values are **0.9773**,
#    **0.3146** and **0.0845**. Report the first set and you have three tradeable
#    strategies; report the second and you have none. A Romano-Wolf stepdown over
#    the WHOLE JPM family against the same rotations rejects **0** cells; its
#    rank-1 adjusted p is **0.9773**, identical to the rotation p-value, which is
#    what says the two tests are wired to the same family.
# 6. **The harness was calibrated in both directions, on data whose answer is
#    known.** SIZE, over 40 pairs of unrelated AR(0.97) inputs pushed through the
#    identical pipeline and scored by the identical 2048-cell search: **2**
#    rejections in 40, a size of **0.05** at a nominal 5% [Wilson **0.0138**,
#    **0.1650**], median p **0.511**. The phase-randomised null agrees: **1** in
#    20, again **0.05** [Wilson **0.0089**, **0.2361**]. The prior study's levels
#    null fired 20% of the time on the same family of construction; this one does
#    not. POWER, against an edge planted by construction and buried in one
#    standard deviation of AR noise: **13** detections in 15, **86.7%** [Wilson
#    **0.6212**, **0.9626**], at a median p of **0.0227** -- the resolution floor.
#    Bury the same edge in THREE standard deviations of noise and power falls to
#    **13.3%**: so "no signal" here means no signal of a size this sample could
#    resolve, and the honest reading of the null is bounded by that, not by
#    infinity. The apparatus finds an edge that is there and does not manufacture
#    one that is not, which is what makes a p of 0.9773 a real absence rather
#    than a blunt instrument.
# 7. **A defect in the shared data layer, which reaches work already on `main`.**
#    `RATES.OIS.USD_SOFR.PAR.2Y` in the Citi tag cache is **47.2%** swaption
#    normal vol, not a rate: **2600** of **5507** rows lie outside any band a USD
#    par rate can occupy, running to a maximum of **164.649**, interleaved day by
#    day for a decade. Both `fed_sentiment_lead` and `fedlock_sentiment_lead`
#    regress forward changes in that series against their sentiment indices for
#    their "does it reach the price" sections; those regressions ran on a series
#    that is nearly half swaption vol. This notebook builds the 2y rate from the
#    CurveStore discount factors instead and ties it out to **4.02772** against a
#    recorded reprice of **4.02995**.
# 8. **The one number that behaves like a signal is a direction, and it points
#    the wrong way for the obvious story.** Across all three samples the top of
#    the league is dominated by **follow**, not fade: **82** of the JPM top 100
#    cells, and every one of the FedLock 21-year top ten. "Fedspeak is hawkish
#    relative to the data, so buy the front end" -- the mean-reverting reading the
#    prior studies' direction implies -- is the *losing* side of a coin that is
#    not weighted.
# 9. **Four defects found by building this, and the two that mattered most
#    flattered the NULL rather than the result -- which is the error direction a
#    study like this is actually exposed to.**
#    (a) Ranking the grid on `|Sharpe|` is wrong once a cost is charged, because
#    a round trip is paid whichever way the trade goes, so `follow` is
#    `-(p + cost) - cost` and not `-p`; the first pass reported a cell losing
#    1.71bp a trade as its winner because 1.71 is a bigger number than the 0.29
#    the other reading lost.
#    (b) The deflation ranked on a different statistic from the grid, so the two
#    named different winners.
#    (c) **264** of 2048 cells are too thin to be scored by the grid at all, yet
#    were being counted as deflation trials -- inflating N and with it the bar the
#    winner had to clear. Fixing it moved the trial count from 4032 to **3568**
#    and the JPM DSR from 0.0193 to **0.0226**: the null had been made to look
#    better established than it was.
#    (d) The Romano-Wolf stepdown ran over the top 400 cells **by observed
#    Sharpe**, which shrinks every suffix maximum and destroys familywise
#    control; that version "rejected" one FedLock SR3 cell whose own rotation p
#    was 0.0845. Over the full family it rejects none, and its rank-1 adjusted p
#    equals the rotation p exactly.
#    All four are pinned by tests, and the guards are mutation-tested.
# 10. **The engine agrees with the search device exactly.** The pre-registered
#    book re-run through `QueryDrivenBacktest` and `STIRFutureMDP`, cache-warmed
#    and network-disarmed, reproduces all 23 trades to a worst absolute difference
#    of **7.105e-15** bp. The direction gate proves a long future gains when the
#    price rises and that long and short are equal and opposite -- the
#    `STIRFutureQuery` sign trap is closed, not assumed closed.
#
# **Verdict.** The detachment between Fedspeak and the data is measurable and
# persistent, and it does not predict the front end. On the only sample where the
# sentiment side is honestly gated it is worse than noise; on the two where it is
# not gated at all it is still inside the null. The cost line never becomes the
# argument, which makes this a cleaner *no* than most: there is no version of the
# execution, the instrument or the holding period that would change it, because
# the grid already searched all three.
# %%
from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"

HERE = Path.cwd()
REPO = HERE if (HERE / "MDP").exists() else HERE.parents[1]
for p in (str(REPO), str(REPO / "notebooks" / "rv")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_detachment_data as D  # noqa: E402
import fed_detachment_engine as E  # noqa: E402
import fed_detachment_grid as G  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402
import fed_detachment_run as R  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 150)
pd.set_option("display.max_columns", 40)

BG, GRID = "#11151c", "#2a3340"
GREY, RED, BLUE, AMBER, GREEN = "#9aa7b8", "#e05353", "#4c9be8", "#e8b44c", "#5cc98c"


def style(fig, height=520, title=None):
    fig.update_layout(
        template="plotly_dark", height=height, title=title,
        paper_bgcolor=BG, plot_bgcolor=BG, margin=dict(l=60, r=60, t=60, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=12))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


T0 = time.time()
print("frozen configuration -- every knob and why it sits where it does:")
print(D.PRIMARY.describe().to_string(index=False))

# %% [markdown]
# ## The pre-registration
#
# The primary cell is written down **before** the grid runs, in
# `fed_detachment_data.PRIMARY`, with the reason for every choice. It is reported
# first whatever the grid finds. That ordering is the whole discipline: on a
# previous study on this desk **12 of 12** post-hoc defects found by adversarial
# review favoured the thesis, and a winner chosen after the fact bends every
# subsequent judgement call toward it.
#
# * `gap`, because a level difference is the plainest reading of "detached";
# * `k = 0`, because a *contemporaneous* gap is what the word means, and the
#   twenty-one-year evidence puts any real lead at +1 to +2 weeks, i.e. inside
#   the weekly grid's own resolution;
# * `threshold 1.0`, because a one-sigma gap is the conventional bar and 0.0
#   would not be "detachment" at all;
# * `4 weeks`, the shortest horizon over which a committee can visibly change
#   tack and the longest that leaves ~35 non-overlapping trades in three years;
# * `out3`, the third deferred SR3 -- where a repricing of the Fed path shows up
#   with real liquidity and with no fixing already inside the contract's window;
# * `sign = fade`, because the data is the anchor: the studies on `main` found
#   surprises leading sentiment and never the reverse, so the side expected to
#   move is the Fed's.
#
# **The grid then searches the direction too**, and every null below is scored on
# the same best-of-both-readings maximum, so not knowing the sign in advance is
# paid for rather than assumed away.

# %%
print("PRE-REGISTERED PRIMARY CELL")
print(f"  construction {D.PRIMARY.construction!r}, lead_k {D.PRIMARY.lead_k}, "
      f"threshold {D.PRIMARY.threshold}, horizon {D.PRIMARY.horizon_w}w, "
      f"structure {D.PRIMARY.structure!r}, "
      f"sign {'fade' if D.PRIMARY.sign > 0 else 'follow'}")
print(f"  round-trip cost {D.PRIMARY.cost_bp_round_trip():.2f}bp "
      f"({D.PRIMARY.cost_bp_one_way}bp one-way x "
      f"{D.STRUCTURES[D.PRIMARY.structure][2]} contract(s) x 2)")
print(f"\nthe grid: {len(D.CONSTRUCTIONS)} constructions x {len(D.LEAD_KS)} lead "
      f"alignments x {len(D.THRESHOLDS)} thresholds x {len(D.HORIZONS_W)} horizons "
      f"x {len(R.ALL_STRUCTURES)} instruments = {len(G.cell_keys())} cells, "
      f"each scored at BOTH directions")

# %% [markdown]
# ## The rate the prior studies used is half swaption vol
#
# Before anything else, because it changes what can be trusted downstream.
#
# `project_citivelo_tagcache_vol_poison` records that on 2026-08-21 the Citi tag
# cache was found serving swaption normal vol under the `RATES.OIS.USD_SOFR.PAR.*`
# tags, unrepaired. Both studies on `main` read `RATES.OIS.USD_SOFR.PAR.2Y`
# through `read_cached_rate` with no sanity check, and regress forward changes in
# it against their sentiment indices to conclude the relationship "does not reach
# the price". The conclusion may well survive -- a series with spurious variance
# biases a regression toward zero -- but the numbers in those sections were
# computed on a series that is nearly half swaption vol.
#
# The cell below measures the contamination rather than citing it, and then
# builds the 2y par rate from the **CurveStore discount factors**, which a
# different write path produced and the poisoning did not touch. The known-answer
# check is the reprice recorded in that same note.

# %%
poison = PX.tag_cache_poison_report()
print("shared Citi tag cache, RATES.OIS.USD_SOFR.PAR.2Y:")
for k, v in poison.items():
    print(f"  {k}: {v}")
print(f"\n{poison['n_impossible']} of {poison['n']} rows "
      f"({100 * poison['share_impossible']:.1f}%) are outside {PX.RATE_SANE_BAND} "
      f"and therefore cannot be a USD par rate.")

RATE = PX.curve_store_par_rate(2)
print("\nrebuilt from the CurveStore discount factors (annual pay, ACT/360, "
      "log-linear in DF -- the curve's own declared interpolation):")
print(PX.gate_rate_sanity(RATE, name="2y SOFR par"))
print(f"\nKNOWN ANSWER -- 2026-08-14 reprice recorded in the tag-poison note: 4.02995")
print(f"  this notebook: {RATE.loc[pd.Timestamp('2026-08-14')]:.5f}")
print(f"  the poisoned tag that week: 67.1 (recorded), max in the series "
      f"{poison['max_value']}")

# %%
tag = None
try:
    import fed_sentiment_lead_data as _L
    tag = _L.read_cached_rate(_L.TAG_SOFR_2Y)
except Exception as exc:  # noqa: BLE001
    print("tag cache unreadable:", exc)

fig = go.Figure()
if tag is not None:
    fig.add_trace(go.Scatter(x=tag.index, y=tag.values, name="tag cache (poisoned)",
                             line=dict(color=RED, width=1)))
fig.add_trace(go.Scatter(x=RATE.index, y=RATE.values, name="CurveStore par 2y",
                         line=dict(color=BLUE, width=1.5)))
fig.add_hrect(y0=PX.RATE_SANE_BAND[0], y1=PX.RATE_SANE_BAND[1], fillcolor=GREEN,
              opacity=0.07, line_width=0)
style(fig, 420, "The same tag, two ways. Everything above the shaded band is "
                "swaption vol wearing a par-rate name.")
fig.update_yaxes(title="percent / normal vol bp")
fig.show()

# %% [markdown]
# ## Contract coverage, before anything is backtested
#
# The study needs SR3 ranks 1-4 on every weekly grid date. A **partial Barchart
# fetch stores as complete** -- the parquet exists, reads cleanly, and simply
# begins later than the study needs -- so coverage is checked against the first
# date any rank *points at* each contract, which is the only thing that can
# detect it. Two contracts (`SR3U26`, `SR3Z26`) failed that check on the shared
# cache and were refetched and **merged**, never substituted, into a study-local
# cache: a fetch that comes back short must cost nothing.

# %%
weeks_all = pd.date_range("2018-05-04", "2026-08-21", freq="W-FRI")
rmap = PX.build_rank_map([d.date() for d in weeks_all], 4)
needed = {}
for col in rmap.columns:
    for d, sym in rmap[col].items():
        if sym not in needed or d < needed[sym]:
            needed[sym] = d
COVER = PX.gate_contract_history(sorted(needed), needed)
print(f"{len(COVER)} SR3 contracts touched by ranks 1-4 over 2018-05..2026-08")
print(f"short of what a rank needs: {int((~COVER['ok']).sum())}")
print(COVER[["symbol", "n", "first", "last", "expiry", "needed_from", "ok"]]
      .head(12).to_string(index=False))

# %% [markdown]
# ### Why there is no roll in any P&L here
#
# Rank 1 is the front contract whose reference quarter has **not yet started**,
# so a rank-N contract selected at `t` cannot expire sooner than about thirteen
# weeks later, and the longest holding period in the grid is eight. **No trade
# crosses an expiry**, so no P&L in this notebook ever differences two
# contracts.
#
# That is worth stating rather than assuming, because
# `reference_imm_roll_fomc_collision` records that **22 of 33** SR3 rolls are
# themselves FOMC decision dates. A roll jump in this study would not be noise --
# it would be correlated with the signal being traded.

# %%
worst = 10_000
for t in pd.date_range("2018-01-01", "2027-12-31", freq="W-FRI"):
    for rank in (1, 2, 3, 4):
        sym = PX.rank_symbol(t.date(), rank)
        worst = min(worst, (PX.contract_window(sym).end - t.date()).days)
print(f"over 522 weekly selections x 4 ranks, the shortest time from selection "
      f"to expiry is {worst} days")
print(f"the longest holding period in the grid is {max(D.HORIZONS_W) * 7} days")
assert worst > max(D.HORIZONS_W) * 7
print("=> no trade in this study can cross a roll")

# %% [markdown]
# ## The four constructions of "detached"
#
# All strictly trailing, all on the Friday grid, all scale-free so the two sides
# can be differenced.
#
# | | |
# |---|---|
# | `gap` | `z(S)_t - z(C)_{t-k}` |
# | `resid` | residual of `z(S)_t` on `z(C)_{t-k}` from a rolling OLS |
# | `dchg` | `(z(S)_t - z(S)_{t-m}) - (z(C)_{t-k} - z(C)_{t-k-m})` |
# | `rankgap` | trailing percentile rank of `S` minus that of `C_{t-k}` |
#
# with `k` in `{0, 2, 5, 11}`: contemporaneous; the twenty-one-year survivor
# (+2w); JWS's claim (+5w); and the lead the 2023-2026 window actually measures
# (+11w). Each `k` is a number somebody has defended.
#
# **`D > 0` means Fedspeak is more hawkish than the data warrants.**
#
# **G-D1** is the one testable property of a trailing statistic applied to the
# whole composition rather than to its parts: truncating both inputs after `t`
# must not change `D` at `t`. It is asserted for all sixteen (construction, k)
# pairs, and the test suite proves it catches a full-sample z-score.

# %%
ZC, ZS, PROV = D.load_sides(D.PRIMARY)
print("provenance:", {k: v for k, v in PROV.items() if k not in ("missing_tags",)})
print(f"\nz(composite): {len(ZC.dropna())} weeks "
      f"{ZC.dropna().index.min().date()} -> {ZC.dropna().index.max().date()}")
print(f"z(sentiment): {len(ZS.dropna())} weeks "
      f"{ZS.dropna().index.min().date()} -> {ZS.dropna().index.max().date()}")

BANK = G.build_signal_bank(ZC, ZS, D.PRIMARY)
SUP = G.common_support(BANK)
rows = []
for (c, k), s in sorted(BANK.items()):
    f = s.dropna()
    rows.append({"construction": c, "lead_k": k, "n_weeks": len(f),
                 "first": f.index.min().date(), "last": f.index.max().date(),
                 "sd": f.std(), "corr_with_gap0": f.corr(BANK[("gap", 0)])})
print("\nthe sixteen detachment series:")
print(pd.DataFrame(rows).to_string(index=False))
print(f"\ncommon support (every construction defined): {len(SUP)} weeks "
      f"{SUP.min().date()} -> {SUP.max().date()}")
print(f"the sentiment index itself starts {ZS.dropna().index.min().date()}; the "
      f"rolling regression and rolling rank cost a further "
      f"{len(BANK[('gap', 0)].dropna()) - len(SUP)} weeks")

# %%
probes = SUP[[20, 60, len(SUP) - 5]]
gates = []
for (c, k) in sorted(BANK):
    sub = dataclasses.replace(D.PRIMARY, construction=c, lead_k=k)
    out = D.gate_trailing_detachment(ZC, ZS, sub, probe_dates=probes)
    gates.append({"construction": c, "lead_k": k, "probes": len(out),
                  "worst_abs_diff": float(out["abs_diff"].max()) if len(out) else np.nan})
print("G-D1 -- truncating the inputs after t must not move D at t "
      "(asserts inside; all sixteen constructions):")
print(pd.DataFrame(gates).to_string(index=False))

# %%
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                    subplot_titles=("the two sides, standardised on trailing windows",
                                    "detachment D = z(sentiment) - z(composite), k = 0"))
fig.add_trace(go.Scatter(x=ZC.index, y=ZC.values, name="z(surprise composite)",
                         line=dict(color=GREY, width=1.6)), row=1, col=1)
fig.add_trace(go.Scatter(x=ZS.index, y=ZS.values, name="z(Fed sentiment, PIT)",
                         line=dict(color=RED, width=1.8)), row=1, col=1)
d0 = BANK[("gap", 0)]
fig.add_trace(go.Scatter(x=d0.index, y=d0.values, name="D (gap, k=0)",
                         line=dict(color=BLUE, width=1.8)), row=2, col=1)
for lvl, col in ((1.0, AMBER), (-1.0, AMBER)):
    fig.add_hline(y=lvl, line=dict(color=col, dash="dot", width=1), row=2, col=1)
fig.update_xaxes(range=[pd.Timestamp("2023-06-01"), pd.Timestamp("2026-09-15")])
style(fig, 640)
fig.show()

# %% [markdown]
# ## The pre-registered book, and the engine that has to agree with it
#
# The rule is a book somebody could run: walk the weekly grid; when flat and
# `|D| >= threshold`, take the trade, hold `horizon` weeks, go flat, resume
# looking. That gives one P&L per trade rather than an overlapping stream, so a
# Sharpe computed on it is not quietly counting the same week eight times.
#
# **The signal is read at the Friday close and filled at the NEXT session's
# settle.** Filling on the session the signal was read from lets the entry price
# be the very print the signal was computed from, and this desk has already paid
# for that (`project_cavf_grid_verdict`: "same-day fills harvest mark noise").
# Same-day entry appears below as a sensitivity, never as the headline.
#
# The grid prices trades from a settle panel because it has to do so two million
# times. That is a *second implementation* of the P&L, which is exactly the kind
# of thing that is quietly wrong -- so the pre-registered book is re-run through
# the shipped `QueryDrivenBacktest` and `STIRFutureMDP`, cache-warmed from the
# same panel and with every fetch path replaced by a raise, and the two are
# required to agree.

# %%
SYMS = PX.sr3_universe(SUP.min().date(), SUP.max().date() + pd.Timedelta(weeks=12), 4)
PANEL = PX.settle_panel(SYMS)
SESSIONS = np.asarray(pd.DatetimeIndex(PANEL.index).values, dtype="datetime64[ns]")
TRADES = D.schedule(BANK[(D.PRIMARY.construction, D.PRIMARY.lead_k)].reindex(SUP),
                    D.PRIMARY, SESSIONS)
BOOK, REASONS = D.price_book(TRADES, PANEL, D.PRIMARY)
print("pre-registered book:", REASONS)
print(BOOK[["signal_date", "entry_date", "exit_date", "detachment", "side",
            "symbols", "pnl_bp_gross", "cost_bp", "pnl_bp"]].to_string(index=False))
SCORE = D.score_book(BOOK, weeks_per_trade=D.PRIMARY.horizon_w)
print("\n" + "  ".join(f"{k}={v}" for k, v in SCORE.items()))

# %%
EP = D.episodes(BOOK)
by_ep = EP.groupby("episode").agg(trades=("pnl_bp", "size"), bp=("pnl_bp", "sum"),
                                  first=("signal_date", "min"),
                                  last=("signal_date", "max"), side=("side", "first"))
print("the book, by EPISODE -- runs of the same side close together:")
print(by_ep.to_string())
top = by_ep["bp"].abs().idxmax()
print(f"\nlargest episode: #{top}, {int(by_ep.loc[top, 'trades'])} trades, "
      f"{by_ep.loc[top, 'bp']:+.1f}bp")
print(f"the whole book is {BOOK['pnl_bp'].sum():+.1f}bp")
print(f"WITHOUT that episode the other {len(BOOK) - int(by_ep.loc[top, 'trades'])} "
      f"trades make {EP[EP['episode'] != top]['pnl_bp'].sum():+.1f}bp")
print("\nTwo heavily smoothed series do not disagree twenty-three independent "
      "times in two years. They disagree a handful of times, for months at a "
      "stretch, and the episode count is the effective sample.")

# %%
MDP = E.open_mdp()
first = BOOK.iloc[0]
print("G-E2 -- the same trade long and short, through the engine:")
print(E.gate_direction(PANEL, first["symbols"], first["entry_date"],
                       first["exit_date"], mdp=MDP))
print("\n(a long future gains when the PRICE rises, and the two readings are "
      "equal and opposite -- the STIRFutureQuery negative-contracts sign trap "
      "is closed, not assumed closed)")

REPLAY = E.replay(BOOK, PANEL, mdp=MDP)
TIE = E.tie_out(BOOK, REPLAY)
print(f"\nengine closed {len(REPLAY)} positions from "
      f"{REPLAY.attrs.get('warmed')} warmed cache entries, network disarmed")
print(TIE[["entry_date", "exit_date", "symbols", "side", "panel_pnl_bp",
           "engine_pnl_bp", "diff_bp"]].to_string(index=False))
print("\nG-E1:", E.gate_engine_tie_out(TIE))

# %% [markdown]
# ## The grid, and the null that pays for it
#
# 2,048 cells, each scored at both readings, on the tradeable sample.
#
# The conservative null is a **circular rotation of the finished detachment
# series against the price**, with every rotation re-scored across the entire
# grid. Each surrogate keeps the real signal's trend, persistence, variance and
# marginal distribution exactly; only the correspondence with the front end is
# destroyed. That matters here specifically: over this window a book with a
# standing directional tilt makes money whatever it is conditioned on, and a
# rotation preserves the tilt.
#
# `min_offset` must exceed **twice** the widest alignment the grid can examine --
# `max lead_k + max horizon = 11 + 8 = 19`, so 39.
# `reference_rotation_null_self_match` records what happens at the obvious bound:
# the surrogate reproduces the observed statistic exactly and the p-value stops
# measuring effect size. The cost is resolution: on a 121-week sample the
# reference set holds 43 distinct rotations, so **the exact p-value cannot go
# below 0.0227 however strong the signal is**. That floor is reported, never
# rounded past. The permissive phase-randomised null has as many draws as you
# like and is reported beside it.

# %%
JPM = R.run_sample(label="jpm-tradeable", source="jpm",
                   structures=R.ALL_STRUCTURES, spectral_draws=400)
print()
print(R.headline(JPM).to_string())

# %%
LG = JPM["league"].copy()
cols = ["construction", "lead_k", "threshold", "horizon_w", "structure", "sign",
        "trades", "avg_bp", "gross_avg_bp", "cost_bp", "hit", "sharpe",
        "sharpe_ann", "t_stat", "episodes", "top_episode_share"]
print("TOP 15 of 2048 -- ranked on the weekly Sharpe of the BOOK, not per trade")
print(LG.sort_values("sharpe", ascending=False).head(15)[cols].to_string(index=False))
print("\nPRE-REGISTERED PRIMARY, for comparison:")
print(JPM["primary_row"][cols].to_string(index=False))

# %%
for axis in ("structure", "construction", "lead_k", "horizon_w", "threshold", "sign"):
    print(f"\nBY {axis.upper()}")
    print(R.league_summary(LG, axis).to_string())
top100 = LG.sort_values("sharpe", ascending=False).head(100)
print(f"\ndirection among the best 100 cells: "
      f"{top100['sign'].value_counts().to_dict()}")
print(f"cells whose NET average is positive: "
      f"{int((LG['avg_bp'] > 0).sum())} of {len(LG)}")
print(f"median trades per cell: {LG['trades'].median():.0f}; "
      f"median episodes per cell: {LG['episodes'].median():.0f}")

# %%
null = JPM["rotation"]["max_abs_sharpe"]
spec = JPM["spectral"]["max_abs_sharpe"]
fig = go.Figure()
fig.add_trace(go.Histogram(x=spec, name=f"phase-randomised null ({len(spec)} draws)",
                           marker_color=GREY, opacity=0.55, nbinsx=45,
                           histnorm="probability density"))
fig.add_trace(go.Histogram(x=null, name=f"rotation null ({len(null)} exhaustive)",
                           marker_color=BLUE, opacity=0.65, nbinsx=25,
                           histnorm="probability density"))
fig.add_vline(x=JPM["observed"], line=dict(color=RED, width=3),
              annotation_text=f"observed best {JPM['observed']:.4f}",
              annotation_position="top left")
fig.add_vline(x=JPM["rotation"]["q50"], line=dict(color=AMBER, width=2, dash="dot"),
              annotation_text=f"null median {JPM['rotation']['q50']:.4f}",
              annotation_position="top right")
fig.update_layout(barmode="overlay")
style(fig, 460, "The best of 2,048 cells against the same search on a "
                "misaligned copy of its own signal")
fig.update_xaxes(title="best weekly Sharpe over the whole grid")
fig.show()
print(f"observed {JPM['observed']:.4f} sits at the "
      f"{100 * (null < JPM['observed']).mean():.0f}th percentile of the rotation null")

# %% [markdown]
# ### What a single cell would have looked like on its own
#
# The winner of the grid, tested as though it had been the only thing tried.

# %%
bj = JPM["best_index"]
best_row = LG.iloc[bj]
print("the winning cell:", dict(best_row[cols]))
print("\nshared sign-flip test on that cell ALONE:", JPM["sign_flip"])
print("\nRow permutation cannot test a Sharpe -- shuffling the order leaves the "
      "mean and the dispersion untouched, so the statistic is invariant and the "
      "p-value is uniform whatever the data says. Flipping SIGNS changes the "
      "mean and not the dispersion, which is the null a Sharpe actually has.")
print(f"\nSo: this cell alone reads p = {JPM['sign_flip']['p']:.4f}. "
      f"Corrected for the {len(JPM['keys'])}-cell search it reads "
      f"p = {JPM['p_rotation']:.4f}.")

# %% [markdown]
# ### And what the search cost, parametrically
#
# The deflated Sharpe, with the trial count estimated from the trials rather
# than assumed. It is fed **both readings of every cell**, because taking the
# maximum over a set that has already been sign-optimised would make every
# trial's Sharpe non-negative, halve the observed cross-trial variance, and lower
# the bar by exactly the amount the sign search is worth.
#
# It is reported *beside* the rotation p-value and never instead of it: with
# thousands of trials over 121 weekly observations the correlation matrix is
# ill-conditioned -- the library logs that warning itself -- so a parametric
# deflation resting on an overfit rho-bar is weaker evidence than an exact
# permutation test with a coarse floor.

# %%
dfl = JPM["deflation"]
for k in ("best_sharpe", "sr0", "dsr", "psr_vs_zero", "n_trials_raw",
          "n_trials_effective", "n_eff_evt_mc", "var_sharpe", "sharpe_spread",
          "skew", "kurtosis", "n"):
    print(f"  {k}: {dfl.get(k)}")
print(f"\nThe bar the winner had to clear was SR0 = {dfl['sr0']:.4f}; it managed "
      f"{dfl['best_sharpe']:.4f}. DSR {dfl['dsr']:.4f}.")

# %% [markdown]
# ### And the strictly harder question
#
# The rotation p-value asks whether the *best* cell beats the best cell of a
# misaligned copy. A Romano-Wolf stepdown asks how many cells, if **any**,
# survive familywise error control -- against the same surrogates, so the two
# tests are consistent with one another rather than being two different bars.
#
# It runs over the **whole** family. An earlier version ran it over the top 400
# cells by observed Sharpe, which shrinks every suffix maximum -- the null's
# competing set no longer contains the cells the observed data ranked low but a
# rotation ranks high -- so the adjusted p-values come out too small. On the
# FedLock SR3 sample that version "rejected" one cell while the grid maximum's
# own rotation p was 0.0845. With the full family, the rank-1 adjusted p is the
# rotation p exactly, and that identity is the check that it is wired up right.

# %%
fam = JPM["family"]
print(f"Romano-Wolf stepdown over all {fam['n_tested']} scoreable cells, "
      f"against {fam['draws']} rotations:")
print(fam["table"].to_string())
print(f"\ncells surviving familywise control at alpha = {fam['alpha']}: "
      f"{fam['n_rejected']}")

# %% [markdown]
# ## Is it a cost problem or a signal problem?
#
# Every previous verdict on this desk died at the cost line. This one does not
# get that far, and the distinction matters: a strategy killed by costs can be
# rescued by a cheaper instrument or a longer horizon, and one killed by noise
# cannot.

# %%
rb = JPM["return_bank"]
rows = []
for (s, h), a in sorted(rb.items()):
    f = a[np.isfinite(a)]
    cost = 2.0 * D.PRIMARY.cost_bp_one_way * D.STRUCTURES[s][2] / D.STRUCTURES[s][3]
    rows.append({"structure": s, "horizon_w": h, "n": len(f),
                 "mean_long_bp": f.mean(), "sd_bp": f.std(ddof=1),
                 "round_trip_cost_bp": cost, "cost_as_share_of_sd": cost / f.std(ddof=1)})
COSTS = pd.DataFrame(rows)
print("what one trade actually risks, against what it pays to put on:")
print(COSTS.to_string(index=False))
print(f"\nAt the four-week horizon the cost is "
      f"{100 * COSTS[COSTS.horizon_w == 4]['cost_as_share_of_sd'].median():.1f}% "
      f"of one standard deviation of the trade. It is not the binding constraint.")
print("\nNote also the drift: over this window a LONG SR3 outright loses money "
      "on average and a long 2y OIS makes it -- the market priced OUT cuts in "
      "the deferred contracts while the spot 2y fell. A book with a standing "
      "tilt earns that whatever it is conditioned on, which is exactly what the "
      "rotation null prices away.")

# %%
FREE = R.run_sample(label="cost ZERO", source="jpm", structures=R.ALL_STRUCTURES,
                    cost_bp_one_way=0.0, spectral_draws=0)
print()
print(f"With costs set to ZERO: best {FREE['observed']:.4f}, null median "
      f"{FREE['rotation']['q50']:.4f}, p = {FREE['p_rotation']:.4f}")
print("Unchanged. This is a signal problem, not a cost problem.")

# %% [markdown]
# ## Calibrating the apparatus, in both directions
#
# A checking tool that is itself wrong reports success and hides the thing it was
# built to find. So the grid, the null and the p-value are run end to end against
# a signal that cannot possibly work -- two unrelated AR(0.97) series pushed
# through `detachment` unchanged, so the surrogate bank inherits the real bank's
# internal correlation structure while carrying no information about the price --
# and the rejection rate at a nominal 5% is the size the real p-values should be
# read against.
#
# And then the other direction, because size without power is a test that never
# rejects: an edge is planted by construction and has to be found.

# %%
t = time.time()
SIZE_ROT = G.measure_harness_size(SUP, rb, D.PRIMARY, trials=40, which="rotation",
                                  show_progress=False)
print("SIZE, rotation null:", SIZE_ROT, f"[{time.time()-t:.0f}s]")
t = time.time()
SIZE_SPEC = G.measure_harness_size(SUP, rb, D.PRIMARY, trials=20, which="spectral",
                                   null_draws=150, show_progress=False)
print("SIZE, spectral null:", SIZE_SPEC, f"[{time.time()-t:.0f}s]")

# %%
POWER = []
for noise in (1.0, 3.0):
    t = time.time()
    pw = G.measure_harness_power(SUP, rb, D.PRIMARY, noise=noise, trials=15)
    pw["noise"] = noise
    POWER.append(pw)
    print(f"POWER at noise={noise}:", pw, f"[{time.time()-t:.0f}s]")
POWER = pd.DataFrame(POWER)
print("\nThe apparatus rejects when there is something there and does not when "
      "there is not. A p of 0.98 from a test with the size measured above is a "
      "real absence, not a blunt instrument.")

# %% [markdown]
# ## Twenty-one years, on a sentiment series that can never be gated
#
# FedLock V3: ~4,000 Fed speeches from 1985 scored by a pairwise TrueSkill
# tournament with Llama 3.3 70B as judge, of which 3,673 are dated.
#
# **It can never be point-in-time**, through three separate channels: one global
# `builtOn` stamp with no row-level date; TrueSkill fits every rating *jointly*
# against a comparison graph spanning the whole corpus including the future; and
# the judge has read decades of commentary about what the Fed did next --
# anonymisation strips names, not hindsight. `gate_single_vintage` asserts that
# absence rather than leaving it implicit.
#
# So everything below is **historical association, never a backtest**. It is here
# because it is the only way to ask the question over more than three years, and
# because a relationship that is absent on twenty-one years of an *un-gated*
# series is very unlikely to be present on a gated one.
#
# The raw `m` column is used, not the era-adjusted `ma`: era adjustment is
# quarterly block demeaning, so it uses within-quarter information and removes
# variation at roughly the frequency a multi-week gap lives at.

# %%
FL_SR3 = R.run_sample(label="fedlock-sr3-2018", source="fedlock",
                      structures=R.ALL_STRUCTURES, start="2018-05-04",
                      rotation_draws=400, spectral_draws=400)
print()
print(R.headline(FL_SR3).to_string())

# %% [markdown]
# ### What the SR3 leg could not price, and why that is a counted exclusion
#
# `gate_contract_history` checks the START of each contract's history, because a
# partial fetch stored as complete is the failure it exists to catch. It does not
# check the end -- but the end matters too, because an exit can fall up to eight
# weeks after a contract stops being rank-N, and Barchart's history for a front
# contract that expired in 2018 stops well before its own expiry.
#
# That does not become a wrong price. It becomes a **counted exclusion**: the
# return bank leaves the week unpriced, `run_cell` skips it by one week, and the
# diagnostic below says how many and where. Every rotation of the null sees the
# same holes, so the null pays for them too.

# %%
print("FedLock SR3 return bank -- what each (structure, horizon) could price:")
print(FL_SR3["return_diag"].fillna(0).to_string(index=False))
_missing = FL_SR3["return_diag"].get("drop: no settle")
if _missing is not None:
    print(f"\nunpriceable weeks total {int(_missing.fillna(0).sum())} across "
          f"{len(FL_SR3['return_diag'])} (structure, horizon) pairs, all of them "
          f"in the rank-1 contract whose Barchart history ends before an eight-week "
          f"exit could be marked. Excluded, never guessed.")

# %%
FL_OIS = R.run_sample(label="fedlock-ois2y-21y", source="fedlock",
                      structures=("ois2y",), rotation_draws=800, spectral_draws=400)
print()
print(R.headline(FL_OIS).to_string())

# %%
print("TOP 10 over twenty-one years (2y SOFR OIS, un-gateable sentiment):")
print(FL_OIS["league"].sort_values("sharpe", ascending=False).head(10)[cols]
      .to_string(index=False))
print("\nEvery one of them is 'follow'. If there is anything at all in the "
      "twenty-one-year sample it says hawkish Fedspeak relative to the data is "
      "followed by HIGHER front-end rates -- the opposite of the mean-reverting "
      "reading, and it does not clear its own search either.")

# %%
SUMMARY = pd.DataFrame([R.headline(JPM), R.headline(FL_SR3), R.headline(FL_OIS)])
print("THE THREE SAMPLES")
print(SUMMARY.to_string(index=False))

# %%
fig = go.Figure()
for res, colour in ((JPM, RED), (FL_SR3, AMBER), (FL_OIS, BLUE)):
    m = res["rotation"]["max_abs_sharpe"]
    fig.add_trace(go.Box(x=m, name=res["label"], marker_color=colour,
                         boxpoints=False, orientation="h"))
    fig.add_trace(go.Scatter(x=[res["observed"]], y=[res["label"]], mode="markers",
                             marker=dict(color=colour, size=14, symbol="diamond",
                                         line=dict(color="white", width=1.5)),
                             name=f"{res['label']} observed", showlegend=False))
style(fig, 400, "Observed best (diamond) against its own rotation null (box), "
                "all three samples")
fig.update_xaxes(title="best weekly Sharpe over the grid")
fig.show()

# %% [markdown]
# ### Which instrument expresses it best
#
# The handover asked for this explicitly, so here it is across every sample that
# can price each structure. The honest reading of the table is that the spread
# between instruments is small against the null's own spread -- no structure is
# meaningfully better at expressing a signal that is not there, which is what
# you would expect.

# %%
inst = pd.DataFrame({
    "jpm (121w)": R.league_summary(JPM["league"], "structure")["best_sharpe"],
    "fedlock SR3 (432w)": R.league_summary(FL_SR3["league"], "structure")["best_sharpe"],
    "fedlock 2y OIS (1081w)":
        R.league_summary(FL_OIS["league"], "structure")["best_sharpe"],
}).sort_values("jpm (121w)", ascending=False)
print("best weekly Sharpe by instrument, per sample:")
print(inst.to_string())
print(f"\nfor scale, the rotation null's own median-to-95th spread is "
      f"{JPM['rotation']['q95'] - JPM['rotation']['q50']:.4f} on the JPM sample; "
      f"the spread ACROSS instruments there is "
      f"{inst['jpm (121w)'].max() - inst['jpm (121w)'].min():.4f}.")
print("\ncost per unit of gross risk, by structure:")
print(pd.DataFrame([{"structure": s,
                     "contracts": D.STRUCTURES[s][2],
                     "bp_scale": D.STRUCTURES[s][3],
                     "round_trip_bp_of_quote":
                     dataclasses.replace(D.PRIMARY, structure=s).cost_bp_round_trip()}
                    for s in R.ALL_STRUCTURES]).to_string(index=False))

# %% [markdown]
# ## Robustness: which convention, if any, is doing the work
#
# None of these is an extra grid cell and none is deflated with the grid. Each
# asks whether a *convention* produced the headline, and the answer that matters
# is that none of them turns a dead grid into a live one. A robustness check that
# cannot rescue a null result costs the null nothing.

# %%
ROB = R.run_robustness(source="jpm", structures=R.ALL_STRUCTURES,
                       spectral_draws=0, verbose=False)
print(ROB.drop(columns=["note"]).to_string(index=False))
print()
for _, r in ROB.iterrows():
    print(f"  {r['variant']:32s} {r['note']}")
print(f"\nvariants whose search-corrected p clears 0.05: "
      f"{int((ROB['p_rotation'] < 0.05).sum())} of {len(ROB)}")
print(f"the smallest p over every testable variant is {ROB['p_rotation'].min():.4f} "
      f"against a floor of {ROB['p_floor'].min():.4f}")
short = ROB[ROB["rotations"] == 0]
if len(short):
    print(f"\n{len(short)} variant(s) cannot be rotation-tested at all: a valid "
          f"rotation needs min_offset 39 and a sample of at least 3x that, and "
          f"{short['weeks'].min()} weeks is short of it. Its highest Sharpe "
          f"({short['best_sharpe'].max():.4f}) is the largest in the table -- and "
          f"its DSR is {short['DSR'].min():.4f}, because a shorter sample buys a "
          f"bigger maximum, not a better one.")

# %% [markdown]
# ## What would have to be true for this to work
#
# The arithmetic, so the size of the gap is on the page rather than implied.

# %%
sd4 = float(COSTS[(COSTS.horizon_w == 4) & (COSTS.structure == "out3")]["sd_bp"].iloc[0])
cost = D.PRIMARY.cost_bp_round_trip()
need_sharpe = float(JPM["rotation"]["q95"])
trades_per_year = 52.0 / D.PRIMARY.horizon_w
print(f"one four-week SR3 rank-3 trade has a standard deviation of {sd4:.1f}bp")
print(f"a round trip costs {cost:.2f}bp, i.e. {100 * cost / sd4:.1f}% of that")
print(f"to sit at the null's 95th percentile a cell needs a weekly Sharpe of "
      f"{need_sharpe:.4f}, i.e. {need_sharpe * np.sqrt(52):.3f} annualised")
edge_needed = need_sharpe * np.sqrt(52.0 / trades_per_year) * sd4
print(f"on {trades_per_year:.0f} trades a year that is an edge of "
      f"{edge_needed:.2f}bp per trade, NET")
print(f"the pre-registered cell earned {SCORE['avg_bp']:.3f}bp net per trade "
      f"with a standard error of "
      f"{sd4 / np.sqrt(SCORE['trades']):.2f}bp")
print(f"\nSo the sample cannot even resolve an edge of the required size: the "
      f"standard error on 23 trades is {sd4 / np.sqrt(SCORE['trades']):.1f}bp "
      f"against a {edge_needed:.1f}bp requirement.")
print("\nFor comparison, the intraday Fed-speaker suite -- 1,056 trials, DSR>0.95 "
      "on none -- earned +0.219bp per trade against a ~0.25bp cost. That study "
      "at least had an edge to lose to costs.")

# %% [markdown]
# ## Caveats, stated rather than solved
#
# 1. **The JPM corpus carries ONE score per speech, which is today's score.** The
#    publication gate removes speeches a reader could not have seen, but it
#    cannot detect a speech that was re-scored after `t` -- there is only one row
#    per (speaker, date), so the revision is invisible in this file. The
#    measurable part, composition revision, is large: the prior study found mean
#    |revision| of 2.65 sentiment points, 39% of one standard deviation. The
#    unmeasurable part is a residual leak in the *optimistic* direction.
# 2. **The Citi snapshot is one vintage.** The surprise indices are computed from
#    actual-versus-consensus at release and do not revise, but the snapshot is a
#    current pull and a restatement would not be visible.
# 3. **`ois2y` is a vendor MID quote, not an executable price.** Its 0.50bp round
#    trip is the same order as a 2y OIS bid-offer, but nothing here proves a fill.
# 4. **The rotation p-value on the JPM sample cannot resolve below 0.0227.** The
#    reference set has 43 members. That is a floor on *significance*, not on the
#    result reported here, which is a p at the opposite end of the range.
# 5. **The threshold rule takes trades in phase.** At `threshold = 0` the book
#    enters at week 0 and every `h` weeks thereafter, which is one arbitrary
#    phase of `h`. Every surrogate shares that phase, so the null pays for it,
#    but a different phase would give slightly different cells.
# 6. **The null's power bounds what "no signal" means.** The calibration cell
#    measures 86.7% power against an edge planted one standard deviation above
#    the noise and 13.3% against one buried three below. An effect small enough
#    would not be found here -- which the 23-trade sample and the 24.4bp per-trade
#    standard deviation already imply, and which the "what would have to be true"
#    arithmetic makes explicit.
# 7. **`min_trades = 8`.** Cells thinner than that score NaN and cannot win. The
#    winner of the JPM grid has 15 trades and the runner-up 10 -- thin enough
#    that the per-trade statistics are decoration, which is why the league is
#    ranked on the weekly book and the episode count travels with every row.
# 8. **The FedLock legs are association, not backtests**, for the three reasons
#    given above. The SR3 leg is also the strongest of the three results
#    (p = 0.0845), which is the ordering you would expect if hindsight in the
#    scoring were contributing something.

# %% [markdown]
# ## Verdict

# %%
print(f"""
THE QUESTION: when Fedspeak detaches from the data, is there a tradable signal?

THE ANSWER: no.

  tradeable sample   {len(JPM['support'])} weeks, {len(JPM['keys'])} cells
                     best weekly Sharpe {JPM['observed']:.4f}
                     rotation null median {JPM['rotation']['q50']:.4f}
                     p = {JPM['p_rotation']:.4f}   (floor {JPM['rotation']['p_floor']:.4f})
                     spectral p = {JPM['p_spectral']:.4f}
                     DSR = {JPM['deflation']['dsr']:.4f}

  pre-registered     {SCORE['trades']} trades, {SCORE['avg_bp']:+.3f}bp each net,
                     t = {SCORE['t_stat']:.3f}, hit {100*SCORE['hit']:.1f}%,
                     {SCORE['episodes']} episodes

  FedLock, SR3       {len(FL_SR3['support'])} weeks, p = {FL_SR3['p_rotation']:.4f}
  FedLock, 2y OIS    {len(FL_OIS['support'])} weeks, p = {FL_OIS['p_rotation']:.4f}
  (both un-gateable on the sentiment side -- association, not backtests)

  at ZERO cost       p = {FREE['p_rotation']:.4f}   <- not a cost problem

The best cell the search could find is beaten by a random misalignment of its
own signal {100 * (null >= JPM['observed']).mean():.0f}% of the time. Nothing about the execution, the
instrument or the holding period changes that, because the grid already
searched all three.

WHAT WOULD CHANGE THE ANSWER: a point-in-time sentiment corpus with more than
three years of history. Every result here is either short (JPM, {len(JPM['support'])} weeks)
or un-gateable (FedLock). Those are the same constraint wearing two hats, and
neither study on `main` could get past it either.
""")
print(f"total notebook runtime {time.time() - T0:.0f}s")

# %% [markdown]
# ## Findings tie-out
#
# Every figure quoted in the findings block at the top, printed here from the
# result objects in exactly the form the prose quotes it. This is what
# `_audit_fed_detachment_numbers.py` reads: a figure in the prose that this cell
# does not produce fails the build, so the summary cannot drift away from the
# computation the way one silently did on the study this pattern came from.

# %%
_jr, _js, _jd = JPM["rotation"], JPM["spectral"], JPM["deflation"]
_fs, _fo = FL_SR3, FL_OIS
_prim = JPM["primary_row"].iloc[0]
_fsbest = FL_SR3["league"].iloc[FL_SR3["best_index"]]
_sd4 = float(COSTS[(COSTS.horizon_w == 4) & (COSTS.structure == "out3")]["sd_bp"].iloc[0])
_cost = D.PRIMARY.cost_bp_round_trip()
TIEOUT = {
    "1 best weekly Sharpe": f"{JPM['observed']:.4f}",
    "1 best annualised": f"{JPM['observed'] * np.sqrt(52.0):.4f}",
    "1 rotation null median": f"{_jr['q50']:.4f}",
    "1 rotation null q95": f"{_jr['q95']:.4f}",
    "1 rotation p": f"{JPM['p_rotation']:.4f}",
    "1 observed percentile of its null":
        f"{100 * (np.asarray(_jr['max_abs_sharpe']) < JPM['observed']).mean():.0f}",
    "1 spectral p": f"{JPM['p_spectral']:.4f}",
    "1 DSR": f"{_jd['dsr']:.4f}",
    "1 SR0": f"{_jd['sr0']:.4f}",
    "2 primary bp per trade": f"{SCORE['avg_bp']:+.3f}",
    "2 primary trades": f"{SCORE['trades']}",
    "2 primary t": f"{SCORE['t_stat']:.4f}",
    "2 primary hit %": f"{100 * SCORE['hit']:.2f}%",
    "2 primary weekly Sharpe": f"{float(_prim['sharpe']):.4f}",
    "2 primary total bp": f"{BOOK['pnl_bp'].sum():+.1f}",
    "2 primary bp without the largest episode":
        f"{float(_prim['pnl_ex_top_episode']):+.1f}",
    "2 trades in the largest episode": f"{int(by_ep.loc[top, 'trades'])}",
    "3 zero-cost best": f"{FREE['observed']:.4f}",
    "3 zero-cost null median": f"{FREE['rotation']['q50']:.4f}",
    "3 zero-cost p": f"{FREE['p_rotation']:.4f}",
    "3 four-week out3 sd bp": f"{_sd4:.1f}",
    "3 cost as % of that sd": f"{100 * _cost / _sd4:.1f}%",
    "4 fedlock-ois weeks": f"{len(_fo['support'])}",
    "4 fedlock-ois best": f"{_fo['observed']:.4f}",
    "4 fedlock-ois null median": f"{_fo['rotation']['q50']:.4f}",
    "4 fedlock-ois p": f"{_fo['p_rotation']:.4f}",
    "4 fedlock-ois spectral p": f"{_fo['p_spectral']:.4f}",
    "4 fedlock-ois DSR": f"{_fo['deflation']['dsr']:.4f}",
    "4 fedlock-sr3 weeks": f"{len(_fs['support'])}",
    "4 fedlock-sr3 best": f"{_fs['observed']:.4f}",
    "4 fedlock-sr3 null median": f"{_fs['rotation']['q50']:.4f}",
    "4 fedlock-sr3 p": f"{_fs['p_rotation']:.4f}",
    "4 fedlock-sr3 spectral p": f"{_fs['p_spectral']:.4f}",
    "4 fedlock-sr3 DSR": f"{_fs['deflation']['dsr']:.4f}",
    "5 sign-flip p, JPM winner": f"{JPM['sign_flip']['p']:.4f}",
    "5 sign-flip p, fedlock-ois winner": f"{_fo['sign_flip']['p']:.4f}",
    "5 sign-flip p, fedlock-sr3 winner": f"{_fs['sign_flip']['p']:.4f}",
    "5 fedlock-sr3 winner trades": f"{int(_fsbest['trades'])}",
    "5 fedlock-sr3 winner bp per trade": f"{float(_fsbest['avg_bp']):+.3f}",
    "5 fedlock-sr3 winner t": f"{float(_fsbest['t_stat']):.4f}",
    "5 Romano-Wolf rejections": f"{fam['n_rejected']}",
    "5 Romano-Wolf rank-1 adjusted p": f"{fam['rank1_adjusted_p']:.4f}",
    "5 Romano-Wolf cells tested": f"{fam['n_tested']}",
    "6 size trials": f"{SIZE_ROT['trials']}",
    "6 size rejections": f"{SIZE_ROT['rejected']}",
    "6 size": f"{SIZE_ROT['size']:.2f}",
    "6 size Wilson lo": f"{SIZE_ROT['wilson_lo']:.4f}",
    "6 size Wilson hi": f"{SIZE_ROT['wilson_hi']:.4f}",
    "6 size median p": f"{SIZE_ROT['median_p']:.3f}",
    "6 spectral size rejections": f"{SIZE_SPEC['rejected']}",
    "6 spectral size": f"{SIZE_SPEC['size']:.2f}",
    "6 spectral size Wilson lo": f"{SIZE_SPEC['wilson_lo']:.4f}",
    "6 spectral size Wilson hi": f"{SIZE_SPEC['wilson_hi']:.4f}",
    "6 power detections at noise 1.0": f"{int(POWER.iloc[0]['detected'])}",
    "6 power at noise 1.0 %": f"{100 * float(POWER.iloc[0]['power']):.1f}%",
    "6 power Wilson lo": f"{float(POWER.iloc[0]['wilson_lo']):.4f}",
    "6 power Wilson hi": f"{float(POWER.iloc[0]['wilson_hi']):.4f}",
    "6 power median p": f"{float(POWER.iloc[0]['median_p']):.4f}",
    "6 power at noise 3.0 %": f"{100 * float(POWER.iloc[1]['power']):.1f}%",
    "7 tag rows impossible": f"{poison['n_impossible']}",
    "7 tag rows total": f"{poison['n']}",
    "7 tag share impossible %": f"{100 * poison['share_impossible']:.1f}%",
    "7 tag max value": f"{poison['max_value']}",
    "7 curve store 2y on 2026-08-14":
        f"{RATE.loc[pd.Timestamp('2026-08-14')]:.5f}",
    "8 follow among the JPM top 100": f"{int((top100['sign'] == 'follow').sum())}",
    "10 engine trades": f"{len(TIE)}",
    "10 engine worst abs diff bp": f"{TIE.attrs['max_abs_diff']:.3e}",
    # finding 9's own numbers: the thin-cell trial-set defect
    "9 thin cells excluded from the trial set":
        f"{int((LG['sharpe'].isna()).sum())}",
    "9 trials after the fix (live)": f"{_jd['n_trials_raw']}",
    # measured on the PRE-FIX pass and recorded here so the prose can cite it;
    # the fix is pinned by test_thin_cells_are_not_counted_as_deflation_trials,
    # so no live run can reproduce these two again
    "9 trials before the fix (recorded)": "4032",
    "9 JPM DSR before the fix (recorded)": "0.0193",
}
for k, v in TIEOUT.items():
    print(f"  {k:44s} {v}")
