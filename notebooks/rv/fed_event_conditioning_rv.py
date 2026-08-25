# %% [markdown]
# # Does Fed *language* move the priced path? The link nobody measured
#
# The chain is `data -> Fed language -> price`. Four merged PRs measured the ends
# of it and none measured the middle.
#
# | PR | question | answer |
# |---|---|---|
# | #490 | how long is the lead? | real, **11-14 weeks not 5** |
# | #491 | does a second judge agree? | on that window yes, on 21 years no |
# | #497 | does the residual trade? | 2048 cells, dead before costs |
# | #501 | outright, and as an overlay? | both dead before costs |
#
# Those four close the *continuous timeseries* version of the question. This one
# asks the structural objection to them: **Fed communication is discretised.**
# The stance does not drift, it updates at set-piece events and is stale in
# between, so a dislocation is a stock of unacknowledged information released on
# a schedule. A signal-hold-P&L backtest averages event days with non-event days
# and dilutes a ~19-days-a-year effect by 15-25x, which is exactly what "dead
# before costs" looks like when the effect is real but mistimed.
#
# So: regress the event-window change in the **priced meeting step** on the
# contemporaneous change in the Fed sentiment index, **at communication events
# only**. One regression, and it can end the programme.
#
# ## What was measured -- the numbers up front
#
# *(Every figure here is restated by a cell below, and the last cell prints them
# all together in the form the prose quotes them.
# `_audit_fed_event_conditioning_numbers.py` enforces that as part of the build.)*
#
# 1. **The lead this desk measured predicts a HAWKISH Jackson Hole, not a dovish
#    one -- and it does so at every lead, including JWS's own five weeks.** At a
#    lead of L weeks the data surfacing in Fed language on 28-Aug-2026 is the
#    composite as it stood L weeks earlier: **z = +0.262** at L=5 (reading the
#    data of 24-Jul), **+0.580** at L=11 (**2026-06-12**), **+0.632** at L=14
#    (**2026-05-22**). All hot. The 16-Sep FOMC is hotter still on the measured
#    lead (**+1.164** at L=14). The soft patch only turns the reading negative
#    from late October, and by 9-Dec every lead agrees (**-0.373** at L=11). **If
#    the lead study is worth believing, the receiver is into December, and
#    December is where the pay leg of a 2x1 would sit.**
# 2. **Link 2 exists, is positive, and cannot be resolved.** Regressing the
#    event-window change in the priced meeting step on the contemporaneous change
#    in the sentiment index, at set-piece non-decision events: **+2.1496** bp per
#    sd (JPM, t **+0.46**, n **53**, R2 **0.0162**, bootstrap CI
#    **[-4.4962, +6.8428]**); **+2.1590** (FedLock, t **+1.18**, n **98**, CI
#    **[-1.3373, +5.9492]**); **+1.6859** (FedLock on the JPM window, t **+0.70**,
#    n **44**). Two independent judge models, one shared event calendar, the same
#    sign and near-identical magnitude -- and not one CI excludes zero.
# 3. **It is NOT too small to trade, which is what makes this different from the
#    four PRs before it.** A typical set-piece event moves the index about half a
#    standard deviation, so the fitted path move is **+0.985bp** (JPM),
#    **+0.765bp** (FedLock) and **+0.759bp** (window) per event, and **+1.362bp**
#    at a 90th-percentile event -- against a **0.50bp** SR3 round trip, at
#    **19.0** such events a year. Every earlier study died at the cost line. This
#    one clears it and dies at the standard error.
# 4. **The binding constraint is the sample, and it cannot be relieved.** To
#    reach |t| = 2 at the measured slope and noise would take **983** events on
#    the tradeable arm -- **49** more years at the current rate -- and **280**
#    events (**9** more years) even on the un-gateable FedLock arm; **16** years
#    on the same window. And the sample cannot be extended backwards: the FOMC
#    registry the meeting-step ladder needs starts **2021-01-27**, and the
#    point-in-time sentiment index starts 2023-10.
# 5. **Excluding decision days was not fastidiousness.** On the same window the
#    decision-day slope is **+29.271** against **+1.686** at non-decision events,
#    a ratio of **17.4**. Pooling them would have produced a large, apparently
#    strong coefficient that is a fact about rate DECISIONS, not about language.
# 6. **The regime reading of #491 does not survive its own test.** Split by
#    forward-guidance regime, the lead correlation is **0.0879** under balance-of-
#    risks (2003-2011) and **0.1054** under dots/guidance (2012-2025) -- the same
#    size in both -- while the argmax lag flips from **-9** weeks to **+2**. It
#    tracks nothing. The two earliest regimes are unmeasurable, and not for want
#    of Fedspeak: FedLock has 307 dated speeches in the 1990s, but Citi's daily
#    surprise sub-indices begin in 2003, so no joint week can exist before then.
#    The no-guidance regime has **32** joint weeks. #491's overfitting reading
#    stands.
# 7. **What the study is built on.** **1453** ladder dates from **2021-01-27**,
#    and a shared set-piece calendar of **152** events used identically by every
#    arm -- because the JPM corpus carries no field identifying the kind of
#    communication, so without one its set-piece universe would silently be
#    decisions and minutes only and a disagreement between arms would be a
#    difference of universe rather than of judge.

# %%
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"
T0 = time.time()

HERE = Path.cwd()
REPO = HERE if (HERE / "MDP").exists() else HERE.parents[1]
for _p in (str(REPO), str(REPO / "notebooks" / "rv")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_event_conditioning as E  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

BG, GRID_C = "#11151c", "#2a3340"
GREY, RED, BLUE, AMBER, GREEN = "#8b97a8", "#e05a52", "#5aa9e0", "#e0a83a", "#4fbf7f"


def style(fig, height=520, title=None):
    fig.update_layout(template="plotly_dark", height=height, title=title,
                      paper_bgcolor=BG, plot_bgcolor=BG,
                      margin=dict(l=60, r=30, t=60 if title else 24, b=48),
                      legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom"))
    fig.update_xaxes(gridcolor=GRID_C, zerolinecolor=GRID_C)
    fig.update_yaxes(gridcolor=GRID_C, zerolinecolor=GRID_C)
    return fig


RES = pickle.load(open(REPO / "notebooks" / "rv" /
                       "fed_event_conditioning_results.pkl", "rb"))
ARMS = RES["arms"]
print("arms:", list(ARMS))

# %% [markdown]
# ## 1. The question that prompted this, answered first
#
# The ask was for a study supporting a **receiver into Jackson Hole** — long
# SR3H27 on the thesis that the recent soft patch will show up in Warsh's tone
# on 28 August.
#
# That does not need a new study. It needs the arithmetic of the lead this desk
# already measured. At a lead of `L` weeks, the data surfacing in Fed language on
# a date `D` is the surprise composite as it stood `L` weeks before `D`.

# %%
FR = RES["forward_read"]
print(FR.to_string(index=False))
print()
jh = FR.iloc[0]
print(f"JACKSON HOLE, {jh['date']}:")
for Lw in (5, 11, 14):
    v = jh[f"z_composite_at_L{Lw}"]
    print(f"   at a {Lw:2d}-week lead it reads the data of "
          f"{jh[f'reads_data_of_L{Lw}']}, z = {v:+.3f}  -> "
          f"{'HAWKISH' if v > 0 else 'dovish'}")
print()
print("All three leads are POSITIVE at Jackson Hole -- including JWS's own five")
print("weeks. The measured lead does not support a receiver into Friday; it")
print("predicts a hawkish tone, because the data that reaches Fed language on")
print("28 August is May-July, which was hot.")

# %%
fig = go.Figure()
for Lw, col in ((5, GREY), (11, BLUE), (14, AMBER)):
    fig.add_trace(go.Bar(x=[str(d) for d in FR["date"]],
                         y=FR[f"z_composite_at_L{Lw}"],
                         name=f"lead {Lw}w", marker_color=col))
fig.add_hline(y=0, line=dict(color=RED, width=2))
style(fig, 420, "What the surprise composite implies for Fedspeak on each date")
fig.update_yaxes(title="z of the composite at the lead")
fig.show()

# %% [markdown]
# The soft patch turns the reading negative only from **late October onwards**,
# and by December every lead agrees. **If the lead study is worth believing, the
# receiver is into December, not into Friday** — and December is where the pay
# leg of an existing 2x1 would sit.

# %% [markdown]
# ## 2. The design, and the one thing that had to be got right
#
# `y` is the change in the **priced meeting step**, not an SR3 outright. An
# outright carries supply, term premium, oil and cross-market; the step carries
# only the policy path. It comes from `RVUtils.MeetingProb.meeting_ladder` — a
# CME-FedWatch anchor-walk on ZQ settles, **not** the joint least-squares fit the
# brief supposed; no such object exists in the repo.
#
# **`y` is defined on a FIXED pair of meetings.** At an FOMC event a meeting
# resolves inside the window, so "the next two meetings" at entry and at exit are
# not the same two. Differencing those sums measures the roll, not the
# repricing — and on a decision day the roll IS the decision. The panel therefore
# takes the two meetings whose effective date is strictly after the *exit*
# session and matches them by effective date on both marks.

# %%
print(f"priced meeting step: {RES['hist_summary']['dates']} dates, "
      f"{RES['hist_summary']['rows']} meeting rows, "
      f"{RES['hist_span'][0].date()}..{RES['hist_span'][1].date()}")
print(f"  stale legs {100*RES['hist_summary']['stale_share']:.1f}% "
      f"-- flagged by the ladder, dropped here")
print()
cal = RES["calendar"]
print(f"shared set-piece calendar: {len(cal)} events")
print("   " + cal["type"].value_counts().to_string().replace("\n", "\n   "))
print()
print("ONE calendar for every arm. The JPM corpus carries no field identifying")
print("the kind of communication, so without this its set-piece universe would")
print("silently be decisions and minutes only, and a disagreement between arms")
print("would be a difference of universe rather than of judge.")
print()
for k, a in ARMS.items():
    if "error" in a:
        print(f"  {k}: {a['error']}"); continue
    print(f"  {k:20s} window {a['window_start']}..  "
          f"{len(a['panel'])} events, G-E3 {a['gate_fixed_pair']}")

# %% [markdown]
# ## 3. Study A -- the decisive regression
#
# The pre-registered read is the **set-piece, non-decision** row: minutes, press
# conferences, semiannual testimony, Jackson Hole. Decision days are reported
# and labelled confounded, because there the policy move itself reprices the
# strip.

# %%
for k, a in ARMS.items():
    if "error" in a:
        continue
    print("=" * 96)
    print(f"{k}   ({a['label']})")
    print("=" * 96)
    print(a["table"].to_string(index=False))
    print()

# %%
rows = []
for k, a in ARMS.items():
    if "error" in a:
        continue
    p, b, n, s, w = (a["primary"], a["primary_boot"], a["null"], a["size"],
                     a["power"])
    rows.append({"arm": k, "n": p["n"], "beta_bp_per_sd": p["beta"],
                 "HC3 t": p["t"], "R2": p["r2"],
                 "boot_lo": b["lo"], "boot_hi": b["hi"],
                 "share_pos": b["share_positive"],
                 "null_q95": n.get("beta_q95"),
                 "bp_per_1sd_event": s["bp_per_1sd_of_x"],
                 "clears_0.50bp": s["clears_the_spread"],
                 "events_for_t2": w["events_for_abs_t_2"],
                 "more_years": w["years_at_this_rate"],
                 "alive": a["verdict"]["alive"]})
SUM = pd.DataFrame(rows)
print(SUM.to_string(index=False))
print()
print("Three arms, two independent judge models, one shared event calendar.")
print("The slope is POSITIVE in all three and of the same size. Not one of them")
print("can distinguish it from zero.")

# %%
fig = go.Figure()
for _, r in SUM.iterrows():
    fig.add_trace(go.Scatter(
        x=[r["boot_lo"], r["boot_hi"]], y=[r["arm"], r["arm"]],
        mode="lines", line=dict(color=GREY, width=6), showlegend=False))
    fig.add_trace(go.Scatter(x=[r["beta_bp_per_sd"]], y=[r["arm"]], mode="markers",
                             marker=dict(color=BLUE, size=13), showlegend=False))
    fig.add_trace(go.Scatter(x=[r["null_q95"]], y=[r["arm"]], mode="markers",
                             marker=dict(color=AMBER, size=11, symbol="x"),
                             showlegend=False))
fig.add_vline(x=0, line=dict(color=RED, width=2, dash="dash"))
style(fig, 360, "Slope with its bootstrap 95% CI (blue), and the non-event null's q95 (amber)")
fig.update_xaxes(title="bp of priced path per sd of sentiment")
fig.show()

# %% [markdown]
# Every interval crosses the red line. That is the whole verdict.

# %% [markdown]
# ## 4. Size, and why "not significant" is not the same as "too small"
#
# The four earlier studies died because the effect was absent or smaller than
# costs. **This one does not.** At face value the fitted path move at a typical
# set-piece event clears an SR3 round trip. What it cannot do is prove it is
# there.

# %%
for k, a in ARMS.items():
    if "error" in a:
        continue
    s, w = a["size"], a["power"]
    print(f"{k}:")
    print(f"   a typical event moves the index {s['sd_of_x']:.3f} sd -> fitted "
          f"path move {s['bp_per_1sd_of_x']:+.3f}bp")
    print(f"   at a 90th-percentile event {s['bp_at_the_90th_pct_event']:+.3f}bp "
          f"vs a {s['sr3_round_trip_bp']:.2f}bp round trip -> "
          f"{'CLEARS' if s['clears_the_spread'] else 'does not clear'}")
    print(f"   {s['events_per_year']:.1f} such events a year")
    print(f"   to reach |t| = 2 at this slope and noise: "
          f"{w['events_for_abs_t_2']:.0f} events "
          f"({w['extra_events_needed']:.0f} more = "
          f"{w['years_at_this_rate']:.0f} more years)")
    print()
print("That is the finding. The binding constraint is the SAMPLE, not the size")
print("and not the sign -- and the sample cannot be extended: the FOMC registry")
print("that the meeting-step ladder needs starts 2021-01-27, and the tradeable")
print("point-in-time sentiment index starts 2023-10.")

# %% [markdown]
# ## 5. The decision confound, measured
#
# The reason the primary cut excludes decision days is not fastidiousness. It is
# that the decision dominates by more than an order of magnitude.

# %%
rows = []
for k, a in ARMS.items():
    if "error" in a:
        continue
    t = a["table"].set_index("cut")
    d = t.loc["set-piece, decision (confounded)"]
    p = t.loc["PRIMARY set-piece, NON-decision"]
    rows.append({"arm": k, "decision beta": d["beta_x"], "decision n": d["n"],
                 "non-decision beta": p["beta_x"], "non-decision n": p["n"],
                 "ratio": (abs(d["beta_x"]) / abs(p["beta_x"])
                           if p["beta_x"] else np.nan)})
CONF = pd.DataFrame(rows)
print(CONF.to_string(index=False))
print()
print("Pooling those two would have produced a large, apparently significant")
print("coefficient that is a fact about rate DECISIONS, not about Fed language.")

# %% [markdown]
# ## 6. The regime reading of #491, tested rather than asserted
#
# #491 found the lead replicates recently and dies over 21 years; the default
# reading is overfitting. The competing reading is that the trade needs
# front-meeting premium, which forward guidance removed — so a long sample pools
# a regime where the mechanism is impossible with one where it might work.
#
# If the effect tracks guidance regimes, that is a mechanism. If it appears at
# random across them, #491 was right.

# %%
RG = RES["regime_split"]
print(RG.to_string(index=False))
print()
print("It does not track them. The correlation is ~0.09-0.11 in BOTH measurable")
print("regimes and the argmax lag is -9 weeks in one and +2 in the other -- a")
print("sign flip in the thing being claimed. The two earliest regimes are not")
print("unmeasured for want of Fedspeak: FedLock carries 307 dated speeches in")
print("the 1990s. It is the SURPRISE side -- Citi's daily sub-indices begin in")
print("2003 -- so no joint week can exist before then. #491's reading stands.")

# %% [markdown]
# ## 7. Verdict

# %%
print("=" * 78)
for k, a in ARMS.items():
    if "error" in a:
        print(f"{k}: {a['error']}"); continue
    v = a["verdict"]
    print(f"{k}")
    for name, ok in v["tests"].items():
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"    -> {'ALIVE' if v['alive'] else 'DEAD'}")
print("=" * 78)
alive = [k for k, a in ARMS.items() if "error" not in a and a["verdict"]["alive"]]
print(f"{len(alive)} of {len([a for a in ARMS.values() if 'error' not in a])} arms alive.")
print()
print("Study A does NOT return the zero the brief expected as the modal outcome.")
print("It returns a positive, consistent, economically meaningful slope that the")
print("available data cannot resolve. Those are different findings and they")
print("point to different next steps: the first says stop, the second says the")
print("question is open and will stay open for years.")
print()
print("Neither of them supports receiving into Jackson Hole. That call rests on")
print("a five-week lead this desk measured at 11-14, and at every lead measured")
print("the data reaching Fed language on 28 August is hot.")
print()
print(f"total notebook runtime {time.time() - T0:.1f}s")

# %% [markdown]
# ## Findings tie-out

# %%
_j = ARMS["jpm"]
_f = ARMS["fedlock"]
_w = ARMS["fedlock_jpm_window"]
_jh = FR.iloc[0]

TIEOUT = {
    "1 JH date": str(_jh["date"]),
    "1 JH z at L5": f"{_jh['z_composite_at_L5']:+.3f}",
    "1 JH z at L11": f"{_jh['z_composite_at_L11']:+.3f}",
    "1 JH z at L14": f"{_jh['z_composite_at_L14']:+.3f}",
    "1 JH reads data of (L11)": str(_jh["reads_data_of_L11"]),
    "1 JH reads data of (L14)": str(_jh["reads_data_of_L14"]),
    "1 Sep-16 z at L14": f"{FR.iloc[1]['z_composite_at_L14']:+.3f}",
    "1 Dec-09 z at L11": f"{FR.iloc[3]['z_composite_at_L11']:+.3f}",

    "2 jpm beta": f"{_j['primary']['beta']:+.4f}",
    "2 jpm t": f"{_j['primary']['t']:+.2f}",
    "2 jpm n": f"{_j['primary']['n']}",
    "2 jpm R2": f"{_j['primary']['r2']:.4f}",
    "2 jpm boot lo": f"{_j['primary_boot']['lo']:+.4f}",
    "2 jpm boot hi": f"{_j['primary_boot']['hi']:+.4f}",
    "2 fedlock beta": f"{_f['primary']['beta']:+.4f}",
    "2 fedlock t": f"{_f['primary']['t']:+.2f}",
    "2 fedlock n": f"{_f['primary']['n']}",
    "2 fedlock boot lo": f"{_f['primary_boot']['lo']:+.4f}",
    "2 fedlock boot hi": f"{_f['primary_boot']['hi']:+.4f}",
    "2 fedlock-jpm-window beta": f"{_w['primary']['beta']:+.4f}",
    "2 fedlock-jpm-window t": f"{_w['primary']['t']:+.2f}",
    "2 fedlock-jpm-window n": f"{_w['primary']['n']}",

    "3 jpm bp per 1sd event": f"{_j['size']['bp_per_1sd_of_x']:+.3f}bp",
    "3 fedlock bp per 1sd event": f"{_f['size']['bp_per_1sd_of_x']:+.3f}bp",
    "3 window bp per 1sd event": f"{_w['size']['bp_per_1sd_of_x']:+.3f}bp",
    "3 jpm bp at p90 event": f"{_j['size']['bp_at_the_90th_pct_event']:+.3f}bp",
    "3 round trip": f"{_j['size']['sr3_round_trip_bp']:.2f}bp",
    "3 events per year": f"{_j['size']['events_per_year']:.1f}",

    "4 jpm events for t2": f"{_j['power']['events_for_abs_t_2']:.0f}",
    "4 jpm more years": f"{_j['power']['years_at_this_rate']:.0f}",
    "4 fedlock events for t2": f"{_f['power']['events_for_abs_t_2']:.0f}",
    "4 fedlock more years": f"{_f['power']['years_at_this_rate']:.0f}",
    "4 window more years": f"{_w['power']['years_at_this_rate']:.0f}",

    "5 window decision beta":
        f"{_w['table'].set_index('cut').loc['set-piece, decision (confounded)', 'beta_x']:+.3f}",
    "5 window non-decision beta": f"{_w['primary']['beta']:+.3f}",
    "5 decision-to-language ratio (window)":
        f"{abs(_w['table'].set_index('cut').loc['set-piece, decision (confounded)', 'beta_x']) / abs(_w['primary']['beta']):.1f}",

    "6 balance-of-risks argmax":
        f"{RG.set_index('regime').loc['balance of risks', 'argmax_lag_w']:.0f}",
    "6 balance-of-risks corr":
        f"{RG.set_index('regime').loc['balance of risks', 'corr_at_argmax']:.4f}",
    "6 guidance argmax":
        f"{RG.set_index('regime').loc['dots / guidance', 'argmax_lag_w']:.0f}",
    "6 guidance corr":
        f"{RG.set_index('regime').loc['dots / guidance', 'corr_at_argmax']:.4f}",
    "6 no-guidance joint weeks":
        f"{RG.set_index('regime').loc['no guidance (Warsh)', 'joint_weeks']:.0f}",

    "7 ladder dates": f"{RES['hist_summary']['dates']}",
    "7 ladder first": str(RES["hist_span"][0].date()),
    "7 calendar events": f"{len(cal)}",
}
for k, v in TIEOUT.items():
    print(f"  {k:42s} {v}")
