# %% [markdown]
# # Does knowing where the data is going tell you how to trade a Fed speaker?
#
# The intraday hawk/dove book trades a speech's label: hawk short the future,
# dove long it, ~5 hours around the speech. It reads every speech the same way,
# and `project_global_cb_hawk_dove` measured what that is worth on the FED leg —
# **+0.219bp per trade against a ~0.25bp round trip**.
#
# JWS Macro #8 (23-Aug-2026) says where the missing structure might be:
#
# > *"Fed speakers will become/shift more dovish/hawkish on where the data is
# > going ... this allows us to predict how a speaker is thinking going into an
# > event."*
#
# If that is right, a speech is only NEWS to the extent it departs from what the
# data already implied. A hawk speaking into three months of hot data is telling
# the market nothing it could not have worked out. So this notebook adds a weekly
# macro state to `hawk_dove_config` and asks whether conditioning on it pays.
#
# Two states, and both are run:
#
# * **`data`** — the surprise composite alone, read `L` weeks back. Covers the
#   whole 2019-2026 event book, because the composite runs from 2005.
# * **`detach`** — the gap between where Fedspeak IS and where the data says it
#   should be. The stronger reading, and much the shorter sample: the
#   point-in-time sentiment index only starts 2023-10.
#
# ## What was measured -- the numbers up front
#
# *(Every figure here is restated by a cell below, and the last cell prints them
# all together in the form the prose quotes them.
# `_audit_macro_state_overlay_numbers.py` enforces that as part of the build.)*
#
# **No. On the live config the best of 72 conditioned books beats the
# unconditioned one by 12 basis points on a +143.5bp base, the median one loses
# 69.5bp, and every searched maximum sits at or below the median of its own
# null. On the detachment state over the live window, 0 of 72 improve on the
# baseline at all.**
#
# 1. **On the live config, conditioning is worth nothing.** The unconditioned
#    book is **399** trades, **+143.5bp**, annualised Sharpe **0.8781**, t
#    **1.8760**, shared sign-flip **p = 0.0590**. Against it, **72** conditioned
#    books -- 4 leads x 3 thresholds x 2 readings x 3 contracts, every one of
#    them trading the SAME events on the SAME entries -- give a best improvement
#    of **+12.0bp**, a median of **-69.5bp** and a worst of **-470.0bp**. The
#    searched maximum sits at the **53.4%** percentile of its own rotation null
#    (**0.0953** against a null median of **0.0932**), **p = 0.4666** on an
#    exhaustive **1077**-rotation test with a floor of **0.0009** and a minimum
#    offset of **23** weeks. *That p prices the 24-cell search WITHIN one
#    contract; the +12.0bp best is a different contract's cell, and the choice of
#    contract is a third axis this null does not charge for. Correcting it can
#    only make the p larger, and it is already 0.47.*
# 2. **Across every arm and every contract, 4 of 12 searched maxima beat their
#    own null's median and the smallest p-value anywhere is 0.3922.** Twelve
#    independent 24-cell searches, and not one of them produces a p-value that
#    would survive a single Bonferroni step, let alone the search that found it.
# 3. **On the detachment state over the live window, conditioning does not
#    merely fail -- it is uniformly harmful.** Baseline **257** trades,
#    **+80.5bp**. Of the **72** conditioned books on that window, **0** improve
#    on it: the best is **-26.0bp**, the worst **-278.0bp**, rotation p
#    **0.7647**. On the whole-book window it is not uniform -- 1 cell of 24 helps
#    in each contract, on a baseline that is itself negative -- so "every cell
#    makes it worse" is a statement about the live arm and is written as one.
#    That arm is also confined to the **2023-10-27** onwards window, because that
#    is when the point-in-time sentiment index begins -- so its baseline is
#    restricted to the same window and a conditioned book is never compared
#    against a baseline that saw four extra years.
# 4. **Gating costs money wherever the baseline makes any, and it always costs
#    trades.** On the live config the best of 24 gated books -- run through the
#    real engine, because a gate removes events before the one-position-at-a-time
#    rule and therefore trades a different book -- is **245** trades for
#    **+106.5bp** against the same-window baseline's **399** trades for
#    **+143.5bp**: **+37.0bp** and **154** trades given up to trade only the
#    speeches the state likes. On the two arms whose baseline is NEGATIVE,
#    gating improves the total -- which is what dropping three quarters of a
#    losing book does, and is not evidence about the state. Every gated book
#    trades between a quarter and two thirds of the baseline's events, and none
#    of the 96 gated cells is scored against any null at all: they are reported
#    as a description, never as a result.
# 5. **The book the overlay was meant to rescue is negative when you stop
#    filtering it.** Over the whole **748**-trade 2019-2026 FED book, reading
#    every speech as labelled loses **-159.5bp** on the third deferred contract
#    (t **-1.4818**) and **-200.5bp** on the second (t **-2.3049**, shared
#    sign-flip **p = 0.0197** -- a SECONDARY test, on one of six baselines
#    examined, so read it as "not obviously zero" rather than as a finding).
#    The live config's positive result comes from its
#    FILTERS -- voters only, at least 10 days from a meeting, SR3 era, 2022
#    onwards -- and those filters were themselves chosen from a sweep.
#    Conditioning that book on the macro state does not help either: rotation
#    **p = 0.8349**.
# 6. **Verifying the checker.** Every number here is computed by negating rows of
#    a baseline trade frame rather than by re-running the backtest -- which is
#    what makes an exact rotation null affordable, and is exactly the shortcut
#    that could quietly describe a different rule than the engine would trade.
#    One conditioned config per arm and contract was therefore put through the
#    REAL engine: **5301** trades checked, worst disagreement **0.0bp**, and the
#    engine and the shortcut flip the same rows in **12 of 12** checks.
# 7. **The knob is a perfect no-op at rest, and one real leak was found and
#    fixed while building it.** `_probe20_signal_knob.py` reproduces the
#    pre-change module trade for trade on three configs. The leak: a W-FRI weekly
#    value is that Friday's CLOSE but is stamped at that Friday's midnight, so
#    comparing an entry timestamp against the stamp let a Friday 09:00 entry read
#    a number that would not exist until 16:00. The cutoff is now the entry DAY,
#    and `G-S2` asserts the minimum state age is at least one day -- measured, it
#    is **3** days and at most **7**.

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
REPO = HERE if (HERE / "MDP").exists() else HERE.parents[2]
STUDY = REPO / "notebooks" / "backtests" / "intraday_fed_hawk_dove"
for _p in (str(REPO), str(REPO / "notebooks" / "rv"), str(STUDY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_signal_overlay as SIG  # noqa: E402

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


RES = pickle.load(open(STUDY / "_signal_overlay_results.pkl", "rb"))
print("arms:", list(RES))

# %% [markdown]
# ## 1. The knob, and the two things that make the comparison honest
#
# `hawk_dove_config` gained one new top-level block, `signal`, defaulting to
# `{"mode": "off"}` — so every config written before it existed reproduces
# **bit-identically**, which `_probe20_signal_knob.py` checks against the
# pre-change module trade for trade.
#
# ```
# "signal": {"mode": "off",       # off | flip | gate | size
#            "state": "data",     # data | detach
#            "lead_w": 0,
#            "threshold": 0.0,
#            "when": "agree"}     # agree | disagree
# ```
#
# **`flip` is book-preserving.** Same events, same entries, same exits, same
# `d_rate_bp` — only the side of the selected subset moves. That makes the
# comparison against the baseline **paired**: the difference cannot be
# confounded by the one-position-at-a-time rule choosing differently, which is
# exactly the confound `project_fomc_nonvoter_fade` measured (52 voter trades
# worth +41.5bp displaced by non-voter positions holding the slot).
#
# **`gate` is not.** It removes events *before* the overlap rule, so a later
# event can claim a slot a removed one would have blocked. Those cells go
# through the real engine and are compared only against a baseline carrying the
# same date filters.

# %%
print("The join, and what it covers. FED events are business-day only and the")
print("state grid lands on Fridays, so an equality join would match ZERO events.\n")
for st in ("data", "detach"):
    sig = SIG.normalise({"mode": "flip", "state": st, "lead_w": 0})
    state, prov = SIG.build_state(sig)
    print(f"  state {st!r}: {prov.get('weeks')} weeks "
          f"{prov.get('first')}..{prov.get('last')}")
print()
for label, res in RES.items():
    print(f"  {label:16s} first usable week "
          f"{pd.Timestamp(res['first_usable_week']).date()}   {res['window_note']}")

# %%
import pickle as _pk  # noqa: E402

with open(STUDY / "_global_cache" / "events_manual_raw.pkl", "rb") as _f:
    RAW = _pk.load(_f)["FED"]["events"]
_sig = SIG.normalise({"mode": "flip", "state": "data", "lead_w": 0})
_st, _ = SIG.build_state(_sig)
GS2 = SIG.gate_cutoff_is_before_entry(RAW, _st, _sig, n=400)
SIG.gate_join_is_not_vacuous(GS2, name="data")
print(f"G-S2: {len(GS2)} events checked; every state a trade reads was stamped")
print(f"      strictly before the DAY its position opened. State age: minimum "
      f"{int(GS2['lag_days'].min())} days, maximum {int(GS2['lag_days'].max())} days.")
print()
print("A W-FRI weekly value is that Friday's CLOSE but is stamped at that")
print("Friday's midnight, so comparing an entry TIMESTAMP against the stamp lets")
print("a Friday 09:00 entry read a number that will not exist until 16:00. The")
print("cutoff is the entry DAY for exactly that reason, and G-S2 asserts it.")

# %% [markdown]
# The `detach` state is only defined from **2023-10-27**, so conditioning on it
# is also a date filter. Every `detach` arm therefore restricts its own baseline
# to the same window — a conditioned book is never compared against a baseline
# that saw four extra years.

# %% [markdown]
# ## 2. Verifying the checker: the analytic flip against the engine
#
# Every number in this notebook is computed by negating rows of a baseline trade
# frame rather than by re-running the backtest. That is what makes an exact
# rotation null affordable. It is also exactly the kind of shortcut that can
# quietly describe a different rule than the one the engine would trade, and it
# would look completely normal if it did.
#
# So one conditioned config per (arm, instrument) is put through the **real
# engine** and the shortcut is required to reproduce it to the basis point.

# %%
TIE = []
for label, res in RES.items():
    for inst, d in res.get("instruments", {}).items():
        t = d.get("tie_out") or {}
        TIE.append({"arm": label, "instrument": inst, "cell": t.get("cell"),
                    "trades_checked": t.get("checked"),
                    "flipped_by_engine": t.get("n_flipped_engine"),
                    "flipped_here": t.get("n_flipped_here"),
                    "worst_abs_diff_bp": t.get("worst_abs_diff_bp")})
TIE = pd.DataFrame(TIE)
print(TIE.to_string(index=False))
_w = pd.to_numeric(TIE["worst_abs_diff_bp"], errors="coerce")
print(f"\nworst disagreement between the analytic flip and the engine, anywhere: "
      f"{float(_w.max()):.1f}bp over {int(TIE['trades_checked'].sum())} trades")
print(f"engine and shortcut flip the same number of rows in "
      f"{int((TIE['flipped_by_engine'] == TIE['flipped_here']).sum())} of "
      f"{len(TIE)} checks")

# %% [markdown]
# ## 3. The baselines
#
# Two windows, never pooled. `LIVE` is the notebook's own live config; `ALL` is
# the whole raw FED book. Both at a 0.50bp round trip.

# %%
BASE = []
for label, res in RES.items():
    for inst, d in res.get("instruments", {}).items():
        b = d["baseline"]
        BASE.append({"arm": label, "instrument": inst, "trades": d["n_trades"],
                     "first": d["first"], "last": d["last"],
                     "total_bp": b["total_bp"], "avg_bp": b["avg_bp"],
                     "hit": b["hit"], "SR_ann": b["sharpe_ann"], "t": b["t_stat"],
                     "maxDD_bp": b["max_dd_bp"],
                     "sign_flip_p": d["baseline_sign_flip_p"]})
BASE = pd.DataFrame(BASE)
print(BASE.to_string(index=False))

# %% [markdown]
# Read that table before anything else. **The unconditioned book is positive on
# the live config and negative on the whole book.** Reading every speech as
# labelled, over 2019-2026, loses money — on OUT_2 significantly so. Whatever
# edge the live config has comes from its *filters* (voters only, ≥10 days from a
# meeting, SR3 era, 2022 onwards), and those filters were themselves chosen from
# a sweep. That is the baseline the overlay has to improve on.

# %% [markdown]
# ## 4. Does conditioning help? The whole distribution, not the best cell
#
# 24 cells per instrument — 4 leads × 3 thresholds × 2 readings — and the
# statistic that matters is `delta_total_bp`: the conditioned book's total minus
# the paired baseline's, on the same trades.

# %%
DELTA = []
for label, res in RES.items():
    for inst, d in res.get("instruments", {}).items():
        lg = d["league"]
        DELTA.append({"arm": label, "instrument": inst, "cells": len(lg),
                      "baseline_bp": float(lg["baseline_total_bp"].iloc[0]),
                      "best_delta_bp": float(lg["delta_total_bp"].max()),
                      "median_delta_bp": float(lg["delta_total_bp"].median()),
                      "worst_delta_bp": float(lg["delta_total_bp"].min()),
                      "cells_that_helped": int((lg["delta_total_bp"] > 0).sum())})
DELTA = pd.DataFrame(DELTA)
print(DELTA.to_string(index=False))
_live = DELTA[DELTA["arm"] == "A-data-LIVE"]
print(f"\nOn the live config the best of {int(_live['cells'].sum())} conditioned "
      f"books beats its baseline by {float(_live['best_delta_bp'].max()):+.1f}bp,")
print(f"the median cell by {float(_live['median_delta_bp'].median()):+.1f}bp, and "
      f"the worst by {float(_live['worst_delta_bp'].min()):+.1f}bp.")

# %%
fig = go.Figure()
for label, res in RES.items():
    vals = np.concatenate([d["league"]["delta_total_bp"].to_numpy(float)
                           for d in res.get("instruments", {}).values()
                           if "league" in d])
    fig.add_trace(go.Box(y=vals, name=label, boxpoints="all", jitter=0.4,
                         marker=dict(size=5, opacity=0.65), line=dict(width=1.4)))
fig.add_hline(y=0, line=dict(color=RED, width=2, dash="dash"))
style(fig, 460, "Conditioned book minus its paired baseline, bp. Red = no change.")
fig.update_yaxes(title="delta total bp")
fig.show()

# %% [markdown]
# The distribution is a downward smear from zero. Conditioning has one clear
# effect and it is to lose money; the handful of cells above the line are the
# top of a search.

# %% [markdown]
# ## 5. The null that prices the search
#
# The observation is a **searched maximum** over 24 cells, so the null has to be
# scored on the same searched maximum. Rotating the weekly state against the
# calendar keeps its persistence, its marginals and its run lengths — which
# matters, because this state holds a sign for months — and destroys only its
# alignment.
#
# An event-level partition test would not do. `project_fomc_nonvoter_fade`
# measured why: flipping 155 non-voter trades beat 99.9% of random 155-of-504
# partitions, and demeaning those rows so their drift was exactly zero still
# rejected at p ≈ 0.02, because the p-value was carried by the rows that were
# **not** flipped.

# %%
NULL = []
for label, res in RES.items():
    for inst, d in res.get("instruments", {}).items():
        n = d["rotation_null"]
        NULL.append({"arm": label, "instrument": inst,
                     "observed": d["observed_max_sharpe_per_trade"],
                     "null_q50": n.get("q50"), "null_q95": n.get("q95"),
                     "percentile_of_own_null": d["null_percentile"],
                     "p_rotation": d["p_rotation"], "rotations": n.get("n_offsets"),
                     "exhaustive": n.get("exhaustive"),
                     "min_offset": n.get("min_offset"), "p_floor": n.get("p_floor")})
NULL = pd.DataFrame(NULL)
print(NULL.to_string(index=False))
print(f"\ncells whose searched maximum beats its own null's MEDIAN: "
      f"{int((NULL['observed'] > NULL['null_q50']).sum())} of {len(NULL)}")
print(f"smallest p_rotation anywhere: {float(NULL['p_rotation'].min()):.4f}")

# %%
fig = make_subplots(rows=1, cols=len(RES),
                    subplot_titles=[f"{k} (OUT_3)" for k in RES])
for i, (label, res) in enumerate(RES.items(), start=1):
    d = res.get("instruments", {}).get("OUT_3")
    if d is None or "league" not in d:
        continue
    # the null's own distribution is not stored per instrument; show the
    # observed against the stored quantiles instead
    q50, q95 = d["rotation_null"]["q50"], d["rotation_null"]["q95"]
    obs = d["observed_max_sharpe_per_trade"]
    fig.add_trace(go.Bar(x=["null median", "null q95", "OBSERVED"],
                         y=[q50, q95, obs],
                         marker_color=[GREY, AMBER, RED], showlegend=False),
                  row=1, col=i)
style(fig, 380, "Searched maximum Sharpe per trade against its own rotation null")
fig.show()

# %% [markdown]
# ## 6. The gate cells, through the real engine
#
# `gate` trades a different book, so it cannot be read off the baseline frame.
# Every cell here is a real `run_config` run, against a baseline carrying the
# same date filters.

# %%
for label, res in RES.items():
    g = res.get("gate")
    if g is None or g.empty:
        continue
    bl = g[g["cell"].str.startswith("BASELINE")].iloc[0]
    cells = g[~g["cell"].str.startswith("BASELINE")].dropna(subset=["total_bp"])
    best = cells.sort_values("total_bp", ascending=False).iloc[0]
    print(f"{label}")
    print(f"   baseline (same window):  {int(bl['trades']):4d} trades  "
          f"{bl['total_bp']:+8.1f}bp  SR {bl['sharpe_ann']:+.3f}")
    print(f"   best gated cell:         {int(best['trades']):4d} trades  "
          f"{best['total_bp']:+8.1f}bp  SR {best['sharpe_ann']:+.3f}   "
          f"({best['cell'].split('/', 1)[1]})")
    print(f"   -> gating costs {float(bl['total_bp']) - float(best['total_bp']):+.1f}bp "
          f"and {int(bl['trades']) - int(best['trades'])} trades")
    print(f"   -> gated cells trading MORE than the baseline: "
          f"{int((cells['total_bp'] > float(bl['total_bp'])).sum())} of {len(cells)}; "
          f"trade counts {int(cells['trades'].min())}-{int(cells['trades'].max())} "
          f"vs {int(bl['trades'])}\n")

# %% [markdown]
# ## 7. The pre-registered cells
#
# Written down before anything ran.
#
# **A** — `data`, `L = 0`, threshold 0.5, `agree`, `flip`, OUT_3, the whole book.
# *Reading: a speech that says what the data already said is anticipatable, so
# fade it.*
#
# **B** — `detach`, `L = 0`, threshold 1.0, `agree`, `flip`, OUT_3, the detach
# window. *Reading: when Fedspeak has already run hawkish relative to the data,
# one more hawk is priced.*

# %%
PRIMARIES = {
    "A": dict(state="data", lead_w=0, threshold=0.5, when="agree",
              window="ALL", instrument="OUT_3",
              reading="fade the speech that says what the data already said"),
    "B": dict(state="detach", lead_w=0, threshold=1.0, when="agree",
              window="LIVE", instrument="OUT_3",
              reading="when Fedspeak has run hawkish vs the data, one more hawk is priced"),
}
rows = []
for key, spec in PRIMARIES.items():
    for label, res in RES.items():
        if res.get("state") != spec["state"] or res.get("window") != spec["window"]:
            continue
        d = res["instruments"][spec["instrument"]]
        lg = d["league"]
        m = ((lg["lead_w"] == spec["lead_w"]) & (lg["threshold"] == spec["threshold"])
             & (lg["when"] == spec["when"]))
        r = lg.loc[m].iloc[0]
        rows.append(pd.Series({
            "arm": label, "reading": spec["reading"],
            "trades": int(r["trades"]), "selected": int(r["n_selected"]),
            "share_selected": float(r["share_selected"]),
            "baseline_bp": float(r["baseline_total_bp"]),
            "conditioned_bp": float(r["total_bp"]),
            "delta_bp": float(r["delta_total_bp"]),
            "baseline_SR": float(r["baseline_sharpe_ann"]),
            "conditioned_SR": float(r["sharpe_ann"]),
            "delta_SR": float(r["delta_sharpe"]),
            "p_rotation_of_the_search": float(d["p_rotation"]),
        }, name=f"{key}: {label}"))
PRIM = pd.DataFrame(rows)
print(PRIM.to_string())

# %% [markdown]
# ## 8. Verdict

# %%
print("=" * 78)
for label, res in RES.items():
    ps = [d["p_rotation"] for d in res.get("instruments", {}).values()
          if "p_rotation" in d]
    ds = [float(d["league"]["delta_total_bp"].max())
          for d in res.get("instruments", {}).values() if "league" in d]
    beats = sum(1 for d in res.get("instruments", {}).values()
                if d.get("observed_max_sharpe_per_trade", -np.inf)
                > d.get("rotation_null", {}).get("q50", np.inf))
    print(f"{label:16s} min p_rotation {min(ps):.4f}   best delta over all cells "
          f"{max(ds):+.1f}bp   instruments beating their own null median: "
          f"{beats}/{len(ps)}   -> DEAD")
print("=" * 78)
print()
print("The premise is sound and was measured by two studies already on `main`:")
print("Fed speakers do lean with the data. What this notebook adds is that")
print("knowing it does not change how a speaker's speech should be traded. On")
print("the live config, conditioning is worth +12.0bp on a +143.5bp book at its")
print("very best and -470.0bp at its worst; the searched maximum sits at the 53rd")
print("percentile of its own null; gating gives up between a third and three")
print("quarters of the events and, wherever the baseline earns anything, money")
print("with them; and on the detachment state over that window every one of the")
print("72 conditioned books makes the book worse.")
print()
print(f"total notebook runtime {time.time() - T0:.1f}s")

# %% [markdown]
# ## Findings tie-out

# %%
_liveA = RES["A-data-LIVE"]["instruments"]["OUT_3"]
_allA = RES["A-data-ALL"]["instruments"]["OUT_3"]
_all2 = RES["A-data-ALL"]["instruments"]["OUT_2"]
_detL = RES["B-detach-LIVE"]["instruments"]["OUT_3"]
_liveD = DELTA[DELTA["arm"] == "A-data-LIVE"]
_detD = pd.concat([RES[k]["instruments"][i]["league"]
                   for k in ("B-detach-LIVE",) for i in ("OUT_2", "OUT_3", "OUT_4")])
_gl = RES["A-data-LIVE"]["gate"]
_glb = _gl[_gl["cell"].str.startswith("BASELINE")].iloc[0]
_glbest = _gl[~_gl["cell"].str.startswith("BASELINE")].dropna(
    subset=["total_bp"]).sort_values("total_bp", ascending=False).iloc[0]

TIEOUT = {
    "1 live baseline trades": f"{_liveA['n_trades']}",
    "1 live baseline total": f"{_liveA['baseline']['total_bp']:+.1f}bp",
    "1 live baseline SR": f"{_liveA['baseline']['sharpe_ann']:.4f}",
    "1 live baseline t": f"{_liveA['baseline']['t_stat']:.4f}",
    "1 live baseline sign-flip p": f"{_liveA['baseline_sign_flip_p']:.4f}",
    "1 live conditioned books": f"{int(_liveD['cells'].sum())}",
    "1 live best delta": f"{float(_liveD['best_delta_bp'].max()):+.1f}bp",
    "1 live worst delta": f"{float(_liveD['worst_delta_bp'].min()):+.1f}bp",
    "1 live median delta": f"{float(_liveD['median_delta_bp'].median()):+.1f}bp",
    "1 live observed max": f"{_liveA['observed_max_sharpe_per_trade']:.4f}",
    "1 live null median": f"{_liveA['rotation_null']['q50']:.4f}",
    "1 live percentile of own null": f"{100 * _liveA['null_percentile']:.1f}%",
    "1 live p_rotation": f"{_liveA['p_rotation']:.4f}",
    "1 live rotations": f"{_liveA['rotation_null']['n_offsets']}",
    "1 live min_offset": f"{_liveA['rotation_null']['min_offset']}",
    "1 live p_floor": f"{_liveA['rotation_null']['p_floor']:.4f}",

    "2 cells beating their own null median":
        f"{int((NULL['observed'] > NULL['null_q50']).sum())} of {len(NULL)}",
    "2 smallest p_rotation anywhere": f"{float(NULL['p_rotation'].min()):.4f}",

    "3 detach baseline trades": f"{_detL['n_trades']}",
    "3 detach baseline total": f"{_detL['baseline']['total_bp']:+.1f}bp",
    "3 detach best delta": f"{float(_detD['delta_total_bp'].max()):+.1f}bp",
    "3 detach worst delta": f"{float(_detD['delta_total_bp'].min()):+.1f}bp",
    "3 detach cells that helped": f"{int((_detD['delta_total_bp'] > 0).sum())}",
    "3 detach cells total": f"{len(_detD)}",
    "3 detach p_rotation": f"{_detL['p_rotation']:.4f}",
    "3 detach state first week": "2023-10-27",

    "4 gate baseline trades": f"{int(_glb['trades'])}",
    "4 gate baseline total": f"{float(_glb['total_bp']):+.1f}bp",
    "4 gate best trades": f"{int(_glbest['trades'])}",
    "4 gate best total": f"{float(_glbest['total_bp']):+.1f}bp",
    "4 gate cost in bp":
        f"{float(_glb['total_bp']) - float(_glbest['total_bp']):+.1f}bp",
    "4 gate cost in trades": f"{int(_glb['trades']) - int(_glbest['trades'])}",

    "5 whole-book trades": f"{_allA['n_trades']}",
    "5 whole-book total OUT_3": f"{_allA['baseline']['total_bp']:+.1f}bp",
    "5 whole-book t OUT_3": f"{_allA['baseline']['t_stat']:.4f}",
    "5 whole-book total OUT_2": f"{_all2['baseline']['total_bp']:+.1f}bp",
    "5 whole-book t OUT_2": f"{_all2['baseline']['t_stat']:.4f}",
    "5 whole-book sign-flip p OUT_2": f"{_all2['baseline_sign_flip_p']:.4f}",
    "5 whole-book p_rotation OUT_3": f"{_allA['p_rotation']:.4f}",

    "6 tie-out trades checked": f"{int(TIE['trades_checked'].sum())}",
    "6 tie-out worst diff": f"{float(_w.max()):.1f}bp",
    "6 tie-out flip counts agree":
        f"{int((TIE['flipped_by_engine'] == TIE['flipped_here']).sum())} of {len(TIE)}",
    "4 gated cells beating the baseline, live":
        f"{int((_gl[~_gl['cell'].str.startswith('BASELINE')].dropna(subset=['total_bp'])['total_bp'] > float(_glb['total_bp'])).sum())} of "
        f"{len(_gl[~_gl['cell'].str.startswith('BASELINE')].dropna(subset=['total_bp']))}",
    "4 gated cells scored against a null": "0 of 96",
    "3 detach-ALL cells that helped, per contract":
        f"{int((RES['B-detach-ALL']['instruments']['OUT_3']['league']['delta_total_bp'] > 0).sum())} of 24",
    "7 min state age days": f"{int(GS2['lag_days'].min())}",
    "7 max state age days": f"{int(GS2['lag_days'].max())}",
    "7 G-S2 events checked": f"{len(GS2)}",
}
for k, v in TIEOUT.items():
    print(f"  {k:40s} {v}")
