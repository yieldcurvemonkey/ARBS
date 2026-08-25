# %% [markdown]
# # Pay SR3 when the data says the Fed is turning hawkish. Does it work?
#
# JWS Macro #8 (23-Aug-2026) reads a chart and says:
#
# > *"we see a tidy 5 week lead of data surprise vs. Fedspeak"*
#
# and the trade that follows is the simplest one in macro: **if the economic
# data tells you what the committee is about to sound like, pay the front end
# when the data runs hot and receive it when the data softens.**
#
# Three studies on `main` have already taken the measuring end of this apart.
# The lead is **+11 to +13 weeks on 2023-2026, not five**; that window is a
# twenty-year maximum; twenty-one years of a second judge model leaves **+2
# weeks at r 0.12**; and asking whether the *gap* between the two sides trades
# gave 2048 dead cells. None of them asked the plainest question of all, which
# is the one here: **not the gap, and not the lead — the direction of the data
# itself, traded outright in SR3.**
#
# ## What was measured -- the numbers up front
#
# *(Every figure here is restated by a cell below, and the last cell of the
# notebook prints all of them together in exactly the form the prose quotes them.
# If the cells and this summary ever disagree, the cells are what ran.
# `_audit_fed_expected_sentiment_numbers.py` enforces that as part of the build.)*
#
# **The answer is no, in all three samples, and the searched maximum is below
# the null MEDIAN in every one of them.**
#
# 1. **The SR3 grid is dead, and the searched maximum is below the null MEDIAN.**
#    **672** cells / **1344** trials over **433** weeks of SR3. Best cell
#    `chg/L11/thr0.0/h8/pack1/follow` at a weekly Sharpe of **0.1090**, against a
#    rotation null whose median is **0.1155** and whose 95th percentile is
#    **0.1500**: the observation sits at the **33.5%** percentile of its own null
#    and **p = 0.6657** on an exhaustive **355**-rotation test with a floor of
#    **0.0028**. Deflated Sharpe **0.0080** against an SR0 of **0.1957**. A
#    Romano-Wolf stepdown over the whole family rejects **0** of **669** scoreable
#    cells.
# 2. **Twenty-one years makes it worse, not better -- and it flips sign.** The 2y
#    SOFR OIS over **1122** weeks from 2005. The pre-registered cell earns
#    **-1.4686bp** per trade over **280** trades, **-411.19bp** in total, t
#    **-1.0540**; the always-on weekly book loses **-47.77bp**. The grid's best is
#    **0.0561** against a null median of **0.0610**, **p = 0.6861** on **1044**
#    exhaustive rotations, DSR **0.2707**. Split those same trades at the date
#    SR3 began and the SR3-era half is **+141.41bp** over **108** trades while
#    the pre-SR3 half is **-552.60bp**: nothing about the rule changed, only
#    where the sample starts. A sign that depends on where you start is not a
#    sign. **This is also the clean re-run of the "does it reach the
#    price" sections that `fed_sentiment_lead` and `fedlock_sentiment_lead` both
#    computed on the poisoned `RATES.OIS.USD_SOFR.PAR.2Y` tag and recorded as "not
#    re-run"** -- the answer does not change, and now it rests on a series that is
#    a rate.
# 3. **The window where the lead is strongest is the deadest of the three.**
#    On the **121** weeks where the point-in-time Fed sentiment index exists --
#    the window in which two prior studies measured an +11 to +13 week lead with
#    a correlation above 0.7 -- the always-on weekly book earns **+0.75bp** in
#    total. The grid's
#    best is **0.2038** against a null median of **0.2069**, **p = 0.5682** on
#    **43** rotations, DSR **0.1490**.
# 4. **The roll is the trap, and it is worth more than the signal.** Measured on
#    **432** Fridays of which **33** contain a contract change: differencing a
#    fixed-rank price column -- the obvious construction -- gives a signed mean
#    weekly move of **+4.56bp** on roll weeks against **-0.81bp** otherwise, and
#    an absolute median of **16.5bp** against **5.0bp**. The change in the
#    contract actually HELD over those same weeks is **-2.35bp**. The gap is
#    **+6.91bp** per roll week and **+228.0bp** in total, pure fabrication --
#    more than twice the whole always-on book's **+97.25bp**. (Against the
#    INCOMING contract instead -- the other single-contract reading of the same
#    interval -- it is **+6.59bp** and **+217.5bp**; the measurement does not
#    turn on which comparator is chosen, which is why both are computed.) Off the roll weeks the
#    two constructions agree to **0.0bp**, which is the known answer that
#    certifies the measurement. The exposure is not hypothetical: **33** of the
#    pre-registered book's **108** trades -- **30.6%** -- hold a contract the rank
#    has rolled away from before they exit. Every one is priced on the contract it
#    opened, at both ends, and the worst disagreement between a booked mark and
#    the settle panel anywhere in the study is **0.0**.
# 5. **The alignment is arithmetic, not a swept parameter.** If the data leads
#    Fedspeak by L weeks, a position held h weeks is forecast by
#    `C_{t-(L-h)} - C_{t-L}` -- two lags, both pinned by (L, h). Writing the
#    signal as `zc.shift(k)` and sweeping k is the alignment for MEASURING a
#    lead, not for trading it, and it makes the signal gratuitously stale. The
#    grid's only signal axis is L, taking four values somebody has defended.
# 6. **The vintage exposure cannot be removed, only bounded -- and the bound
#    says the book is noise, not that it is clean.** The Citi surprise snapshot
#    is a single vintage with no publication axis; it is the largest un-gated
#    look-ahead in the stack. The usual test asks whether an edge SURVIVES
#    delaying its input, on the logic that a revision published within a week
#    cannot help a book that is not allowed to see it. Here the edge neither
#    survives nor dies: delaying the composite one extra week moves the 21-year
#    cell from **-411.19bp** to **+198.44bp** -- a **610bp** swing that changes
#    its sign -- the SR3 cell from **+152.50bp** to **+60.50bp**, and the
#    121-week cell from **+47.50bp** to **+196.50bp**. Nothing that quadruples,
#    quarters or changes sign on a one-week delay of its own input had a stable
#    edge for a revision to have created. So the vintage question is answered by
#    the instability rather than by the test, and the un-gated exposure remains
#    a real limitation of anything built on this composite.
# 7. **The pre-registered cell, written down before the grid ran.** `chg`,
#    lead 0, four weeks, always-on, third deferred SR3, follow: **108** trades at
#    **+1.4120bp** each, **+152.50bp** in total, hit **50.9%**, t **0.5229**,
#    shared sign-flip **p = 0.6059**, and its 108 trades live in **51** episodes.
#    Against the rotation null -- no search here, so the statistic is the cell's
#    own per-trade Sharpe -- **p = 0.2244** on SR3, **0.7771** on the 21-year OIS
#    and **0.2697** on the JPM window. **Unlike the searched maxima, the
#    pre-registered cell is ABOVE its null's median on two of three samples**; it
#    is simply nowhere near significant, and its point estimate is a fifth of a
#    basis point per week. The verdict does not rest on the primary being below a
#    median -- it rests on nothing clearing any bar.
#    The literal always-on weekly reading of the question -- receive when the data
#    softens, pay when it firms, re-decided every Friday -- earns **+147.00bp**
#    gross over **432** weeks, pays **49.75bp** of turnover for a net
#    **+97.25bp**, at an annualised Sharpe of **0.1169** and a maximum drawdown of
#    **-258.5bp**. Eight years, one third of a basis point a week, and a drawdown
#    two and a half times the total.
# 8. **The one exposure the adversarial review found that could have mattered,
#    measured and bounded.** The borrowed grid decides whether to open by reading
#    the FORWARD return, so on any week whose exit settle is missing the trade is
#    declined using information dated after the decision. That lands only on the
#    three structures containing rank 1 -- **28** weeks each on out1, spr1x3 and
#    pack1 (**3** at h=4, **25** at h=8), **0** on out2, out3, out4 and spr2x4 --
#    and the full grid's winner is a `pack1` cell at h=8, i.e. inside it. Scored
#    over only the four unaffected structures the best cell is **0.1051** against
#    a null median of **0.1146**, **p = 0.6826**: still below its own null's
#    median. The pre-registered cell has zero such weeks and is priced by code
#    that never reads the forward return at all.
# 9. **The grid does not even agree on the direction.** Across the SR3 grid
#    **48.8%** of cells prefer `follow` -- pay when the data runs hot, which is
#    the direction the claim asserts -- so a bare **majority prefer to FADE it**.
#    Among the 50 best cells the follow share is **60.0%**, a lean rather than a
#    verdict, and one drawn from a slice chosen by the same in-sample maximum the
#    rest of this notebook is at pains not to trust. Both readings of every cell
#    are scored and both are charged to the deflation, so which one wins a given
#    cell is the sign of a difference between two noisy numbers.

# %%
from __future__ import annotations

import dataclasses
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

import fed_detachment_prices as PX  # noqa: E402
import fed_expected_sentiment as E  # noqa: E402
import fed_expected_sentiment_run as R  # noqa: E402

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
                       "fed_expected_sentiment_results.pkl", "rb"))
print("samples:", list(RES))

# %% [markdown]
# ## 1. The alignment, which is the one piece of arithmetic that decides the study
#
# It is tempting to write the signal as `zc.shift(k)` and sweep `k`. That is the
# alignment for *measuring* a lead, not for *trading* it, and it makes the signal
# gratuitously stale.
#
# Do the arithmetic. If the composite `C` leads Fedspeak `S` by `L` weeks so that
# `S_t` tracks `C_{t-L}`, then a position opened at `t` and held `h` weeks is
# exposed to `S_{t+h}`, which tracks `C_{t+h-L} = C_{t-(L-h)}`. So the forecast of
# the change in the Fed's tone over the holding period is
#
# > `s_t = C_{t-(L-h)} - C_{t-L}`
#
# Both ends are lags and both are pinned by `(L, h)`. There is no free parameter,
# and the grid's only signal axis is `L` — four values each of which somebody has
# defended: **0** (no lead: trade the direction the data has already moved),
# **2** (the 21-year survivor), **5** (JWS's claim), **11** (what 2023-2026
# measures).

# %%
rows = []
for lw in E.LEADS_W:
    for h in E.HORIZONS_W:
        c = dataclasses.replace(E.PRIMARY, lead_w=lw, horizon_w=h)
        near, far = c.lags()
        rows.append({"lead_L": lw, "horizon_h": h, "lag_near": near,
                     "lag_far": far, "window_w": far - near})
LAGS = pd.DataFrame(rows)
print("the (L, h) -> (near, far) map, weeks:\n")
print(LAGS.pivot(index="lead_L", columns="horizon_h",
                 values=["lag_near", "lag_far"]).to_string())
print(f"\nlag_near is never negative: {bool((LAGS.lag_near >= 0).all())}")
print(f"lag_far always exceeds lag_near: {bool((LAGS.lag_far > LAGS.lag_near).all())}")
print(f"\nPRE-REGISTERED PRIMARY: {E.PRIMARY.label()}")
print(E.PRIMARY.describe().to_string(index=False))

# %% [markdown]
# ## 2. The roll, measured on a construction whose answer is known
#
# A weekly directional futures book is exactly the thing a naive roll destroys.
# The obvious construction — build a "rank 3 price" column and difference it —
# differences **two different contracts** on every roll week.
#
# This is run FIRST, before any book is scored, because a checking tool that is
# itself wrong reports success. The known answer is the second half: on a week
# where the rank did *not* change contract, the naive and the correct
# construction are the same arithmetic and must agree to **0.0bp**. They do. On
# the roll weeks they do not, and the gap is the fabrication.

# %%
sr3 = RES["SR3"]
rp = sr3["roll_placebo"]
ROLL = pd.Series({k: v for k, v in rp.items() if k != "series"})
print("SR3 rank 3, weekly, 2018-05-11..2026-08-21\n")
for k, v in ROLL.items():
    print(f"  {k:32s} {v if not isinstance(v, float) else round(v, 4)}")
print(f"\n  the naive construction fabricates "
      f"{rp['fabricated_mean_bp']:+.2f}bp per roll week and "
      f"{rp['fabricated_total_bp']:+.1f}bp in total,")
print(f"  and exactly {rp['fabricated_on_flat_weeks_bp']:.1f}bp on the "
      f"{rp['weeks'] - rp['roll_weeks']} weeks with no contract change.")

ser = rp["series"]
fig = go.Figure()
fig.add_trace(go.Scatter(x=ser.index[~ser["rolled"]],
                         y=ser.loc[~ser["rolled"], "d_naive_bp"], mode="markers",
                         name="no roll", marker=dict(color=GREY, size=4)))
fig.add_trace(go.Scatter(x=ser.index[ser["rolled"]],
                         y=ser.loc[ser["rolled"], "d_naive_bp"], mode="markers",
                         name="roll week (naive: two contracts)",
                         marker=dict(color=RED, size=9, symbol="x")))
fig.add_trace(go.Scatter(x=ser.index[ser["rolled"]],
                         y=ser.loc[ser["rolled"], "d_true_bp"], mode="markers",
                         name="roll week (correct: one contract)",
                         marker=dict(color=GREEN, size=9)))
style(fig, 460, "Weekly change in a rank-3 SR3 mark: what the roll fabricates")
fig.update_yaxes(title="bp")
fig.show()

# %% [markdown]
# **Nothing in this study ever differences two contracts.** The discrete book
# fixes the symbol at the filled entry and re-reads that same symbol at exit; the
# always-on book prices each week on the contract held that week and pays a full
# round trip when the contract changes. `gate_no_roll_jump` checks every priced
# row against the settle panel: each row's two marks must both be the contract it
# names.

# %%
# How much of the book is actually exposed to the trap: how many trades hold a
# contract that the RANK has rolled away from before they exit. Those are exactly
# the trades a rank-differenced construction would misprice.
_pb = RES["SR3"]["primary"]["discrete_book"]
_crossed = sum(1 for r in _pb.itertuples()
               if PX.rank_symbol(pd.Timestamp(r.exit_date).date(), 3) != r.symbols)
print(f"of the {len(_pb)} trades in the pre-registered SR3 book, {_crossed} "
      f"({_crossed / len(_pb):.1%}) hold a contract the rank has rolled")
print("away from by the time they exit. Each is priced on the contract it opened,")
print("at both ends. A rank-differenced book would have mispriced every one.")
print()

GATES = []
for name, res in RES.items():
    for which in ("discrete", "weekly"):
        g = res["primary"][f"roll_gate_{which}"]
        GATES.append({"sample": name, "book": which, "rows": g.get("rows"),
                      "marks_checked": g.get("marks_checked"),
                      "worst_mark_diff": g.get("worst_mark_diff"),
                      "roll_weeks": g.get("roll_weeks")})
GATES = pd.DataFrame(GATES)
print(GATES.to_string(index=False))
print(f"\nG-X3: worst disagreement between a booked mark and the settle panel, "
      f"anywhere: {float(pd.to_numeric(GATES['worst_mark_diff'], errors='coerce').max()):.1f}")

# %% [markdown]
# ## 3. The point-in-time gates
#
# `G-X1` truncating the inputs after `t` must not move the signal at `t`.
# `G-X2` the fill is the NEXT session after the Friday the signal is read from.
# `G-X4` a rate is a rate — the 2y OIS leg is built from the CurveStore discount
# factors, not from `RATES.OIS.USD_SOFR.PAR.2Y`, which in the shared tag cache is
# 47% swaption normal vol.

# %%
for name, res in RES.items():
    gt = res.get("gate_trailing")
    gf = res.get("gate_fill")
    print(f"{name}:")
    if gt is not None and len(gt):
        print(f"   G-X1  {len(gt)} probes, worst |diff| {float(gt['abs_diff'].max()):.1e}")
    if gf is not None and len(gf):
        print(f"   G-X2  {len(gf)} probes, every fill strictly after its signal "
              f"Friday: {bool(gf['strictly_after'].all())}")
    cg = res.get("coverage_gate")
    if cg is not None:
        print(f"   G-P3  every structure prices >= "
              f"{float(cg['share'].min()):.1%} of its weeks")
    if "rate_gate" in res:
        rg = res["rate_gate"]
        print(f"   G-X4  2y OIS: {rg['n']} days {rg['first'].date()}..{rg['last'].date()}, "
              f"range {rg['min']:.3f}%..{rg['max']:.3f}%, band {rg['band']}")

# %% [markdown]
# ## 4. The three samples
#
# They are never pooled. A Sharpe from one against a Sharpe from another compares
# instruments **and** samples at once, and `project_global_cb_hawk_dove` measured
# that the leg mix alone spanned a wider Sharpe range than the structure ranking
# it was trying to read.

# %%
HEAD = pd.DataFrame([R.headline(r) for r in RES.values()])
print(HEAD.to_string(index=False))
print()
for k, v in RES.items():
    print(f"{k:6s}  {v['note']}")

# %% [markdown]
# ## 5. The pre-registered primary cell
#
# `chg`, `lead_w = 0`, `horizon 4 weeks`, `threshold 0` (always-on, which is what
# the question asks for), third deferred SR3, **follow** — pay when the data has
# run hot. Written down before the grid ran and reported first whatever the grid
# found.
#
# Two books are priced from it. The **discrete** book takes a non-overlapping
# four-week position each time the rule fires. The **always-on weekly** book is
# the literal reading of "receive when we expect dovish, pay when we expect
# hawkish": a position, re-decided every week, that pays a cost only when it
# actually turns over — a side change, a contract change, or opening from flat.

# %%
PRIM = []
for name, res in RES.items():
    p = res["primary"]
    d, w = p["discrete_score"], p["weekly_score"]
    PRIM.append({
        "sample": name, "cell": p["config"].label(),
        "trades": d["trades"], "avg_bp": d["avg_bp"], "total_bp": d["total_bp"],
        "hit": d["hit"], "SR_ann": d["sharpe_ann"], "t": d["t_stat"],
        "sign_flip_p": (p.get("sign_flip") or {}).get("p"),
        "episodes": int(p["episodes"]["episode"].nunique()) if "episodes" in p else None,
        "wk_weeks": w["weeks"], "wk_total_bp": w["total_bp"],
        "wk_gross_bp": w["gross_total_bp"], "wk_cost_bp": w["turnover_bp"],
        "wk_SR_ann": w["sharpe_ann"], "wk_maxDD_bp": w["max_dd_bp"],
    })
PRIM = pd.DataFrame(PRIM)
print(PRIM.to_string(index=False))

print()
print("...and the pre-registered cell against the SAME null the grid gets.")
print("A sign-flip treats every trade as independent; this signal holds a sign")
print("for months, so the sign-flip overstates. No search is involved in a")
print("pre-registered cell, so the statistic is its own per-trade Sharpe rather")
print("than a maximum.\n")
PRIMNULL = []
for name, res in RES.items():
    pr = res["primary"]
    if "p_rotation" not in pr:
        continue
    n = pr.get("rotation_null", {})
    PRIMNULL.append({"sample": name,
                     "observed_SR_per_trade": pr.get("observed_sharpe_per_trade"),
                     "null_median": pr.get("null_median"),
                     "p_rotation": pr.get("p_rotation"),
                     "rotations": n.get("n_offsets"),
                     "enumerated": n.get("enumerated"),
                     "p_floor": n.get("p_floor"),
                     "sign_flip_p (secondary)": (pr.get("sign_flip") or {}).get("p")})
PRIMNULL = pd.DataFrame(PRIMNULL)
print(PRIMNULL.to_string(index=False))

# %% [markdown]
# The 21-year OIS cell is the one that changes character with the sample, so it
# is worth splitting rather than asserting. The SAME trades, cut at the date SR3
# began:

# %%
_ob = RES["OIS21"]["primary"]["discrete_book"]
_cut = pd.Timestamp("2018-05-07")
SPLIT = []
for _lab, _m in (("2005-05 .. 2018-05 (pre-SR3)",
                  pd.to_datetime(_ob["entry_date"]) < _cut),
                 ("2018-05 .. 2026-08 (the SR3 era)",
                  pd.to_datetime(_ob["entry_date"]) >= _cut),
                 ("the whole 21 years", pd.Series(True, index=_ob.index))):
    _p = _ob.loc[_m, "pnl_bp"].to_numpy(float)
    _sd = float(_p.std(ddof=1)) if len(_p) > 1 else np.nan
    SPLIT.append({"window": _lab, "trades": len(_p),
                  "avg_bp": float(_p.mean()) if len(_p) else np.nan,
                  "total_bp": float(_p.sum()) if len(_p) else np.nan,
                  "hit": float((_p > 0).mean()) if len(_p) else np.nan,
                  "t_stat": (float(_p.mean() / (_sd / np.sqrt(len(_p))))
                             if len(_p) > 1 and _sd > 0 else np.nan)})
SPLIT = pd.DataFrame(SPLIT)
print("the pre-registered OIS cell, split at the date SR3 began:\n")
print(SPLIT.to_string(index=False))
print()
print("The SR3-era half is POSITIVE and the full sample is NEGATIVE. Nothing")
print("about the rule changed; only the sample did. A sign that depends on where")
print("you start is not a sign.")

# %%
fig = make_subplots(rows=1, cols=len(RES), shared_yaxes=False,
                    subplot_titles=[f"{k}: always-on weekly book" for k in RES])
for i, (name, res) in enumerate(RES.items(), start=1):
    b = res["primary"]["weekly_book"]
    if b is None or b.empty:
        continue
    x = pd.to_datetime(b["exit_date"])
    fig.add_trace(go.Scatter(x=x, y=np.cumsum(b["pnl_bp_gross"].to_numpy(float)),
                             name="gross", line=dict(color=GREY, width=1.4),
                             showlegend=(i == 1)), row=1, col=i)
    fig.add_trace(go.Scatter(x=x, y=np.cumsum(b["pnl_bp"].to_numpy(float)),
                             name="net of turnover", line=dict(color=BLUE, width=2),
                             showlegend=(i == 1)), row=1, col=i)
    fig.add_hline(y=0, line=dict(color=GRID_C, width=1), row=1, col=i)
style(fig, 420, "Cumulative bp -- pay hot data, receive soft data, re-decided weekly")
fig.show()

# %% [markdown]
# ## 6. The grid, and the null that prices the search
#
# `reading x lead x threshold x horizon x structure`, every cell scored at BOTH
# directions inside `best_of_both`, so the trial count is twice the cell count.
# The search is paid for by rotating the weekly signal against the calendar and
# re-scoring the **entire** grid every time — the observation is a searched
# maximum, so every surrogate is scored on the same searched maximum.
#
# The rotation set is finite and is enumerated in full; `min_offset` exceeds
# twice the widest alignment searched, so no surrogate can reproduce the true
# one.

# %%
NULLS = []
for name, res in RES.items():
    n = res["null_summary"]
    NULLS.append({"sample": name, "cells": res["n_cells"], "trials": res["n_trials"],
                  "scored": res["n_scored"],
                  "best_cell": (f"{res['best_cell']['construction']}/"
                                f"L{res['best_cell']['lead_k']}/"
                                f"thr{res['best_cell']['threshold']}/"
                                f"h{res['best_cell']['horizon_w']}/"
                                f"{res['best_cell']['structure']}/"
                                f"{res['best_cell']['sign']}"),
                  "observed": res["best_sharpe"], "null_median": n["median"],
                  "null_q95": n["q95"], "percentile_of_own_null": n["observed_percentile"],
                  "p_rotation": res["p_rotation"], "rotations": n["draws"],
                  "exhaustive": n["exhaustive"], "min_offset": n["min_offset"],
                  "p_floor": n["p_floor"],
                  "DSR": (res.get("deflation") or {}).get("dsr"),
                  "SR0": (res.get("deflation") or {}).get("sr0"),
                  "n_eff_trials": (res.get("deflation") or {}).get("n_eff_evt_mc"),
                  "RW_rejected": (res.get("family") or {}).get("n_rejected"),
                  "RW_tested": (res.get("family") or {}).get("n_tested"),
                  "RW_rank1_p": (res.get("family") or {}).get("rank1_adjusted_p")})
NULLS = pd.DataFrame(NULLS)
print(NULLS.to_string(index=False))
print("\nThe wiring identity: with the FULL family, the Romano-Wolf rank-1 adjusted")
print("p equals the rotation p exactly, because the stepdown's first suffix maximum")
print("IS the grid maximum. Any difference means the two tests are looking at")
print("different families.")
for _, r in NULLS.iterrows():
    same = (abs(float(r["RW_rank1_p"]) - float(r["p_rotation"])) < 1e-12
            if pd.notna(r["RW_rank1_p"]) else None)
    print(f"   {r['sample']:6s} rotation {r['p_rotation']:.4f} vs RW rank-1 "
          f"{r['RW_rank1_p']:.4f}  identical: {same}")

# %%
fig = make_subplots(rows=1, cols=len(RES),
                    subplot_titles=[f"{k}: searched max vs its own null" for k in RES])
for i, (name, res) in enumerate(RES.items(), start=1):
    st = np.asarray(res["rotation_null"].get("max_abs_sharpe", []), float)
    if st.size == 0:
        continue
    fig.add_trace(go.Histogram(x=st, nbinsx=30, marker_color=GREY, opacity=0.85,
                               name="rotations", showlegend=(i == 1)), row=1, col=i)
    fig.add_vline(x=float(res["best_sharpe"]), line=dict(color=RED, width=2.5),
                  row=1, col=i)
    fig.add_vline(x=float(res["null_summary"]["median"]),
                  line=dict(color=AMBER, width=1.5, dash="dot"), row=1, col=i)
style(fig, 400, "Red = the grid's best cell. Amber = the null's median.")
fig.show()

# %% [markdown]
# The red line sits **left of** the amber one in all three samples. The best cell
# a several-hundred-cell search could find is worse than a typical misaligned copy
# of the same signal.

# %% [markdown]
# ## 7. What the league says about the axes
#
# Read the MEDIAN, not the best: a best-of is the maximum of however many cells
# that level happens to contain, so ranking axes by their best rewards the axis
# with the most cells.

# %%
for name, res in RES.items():
    print("=" * 76)
    print(f"{name}   ({res['n_cells']} cells, {res['n_scored']} scored)")
    print("=" * 76)
    lg = res["league"]
    for axis in ("construction", "lead_k", "horizon_w", "structure", "threshold"):
        if lg[axis].nunique() < 2:
            continue
        print(f"\n  by {axis}:")
        print("   " + R.league_summary(lg, axis).to_string().replace("\n", "\n   "))
    print(f"\n  top 5 cells:")
    cols = ["construction", "lead_k", "threshold", "horizon_w", "structure",
            "lag_near_w", "lag_far_w", "sign", "trades", "avg_bp", "sharpe",
            "t_stat", "episodes", "top_episode_share"]
    print("   " + lg.sort_values("sharpe", ascending=False).head(5)[cols]
          .to_string(index=False).replace("\n", "\n   "))

# %% [markdown]
# ### The one forward-looking condition the grid inherits, and its size
#
# `fed_detachment_grid.run_cell` decides whether to open by reading the FORWARD
# return: `ret = r[i]; if not np.isfinite(ret): i += 1; continue`. On a week whose
# exit settle is missing, the trade is declined using information dated after the
# decision — and the loop then advances by one week instead of `horizon`,
# re-phasing everything after it. It is inherited rather than forked, and this
# module's own `schedule_trades` does not do it.
#
# It cannot be waved at, because the full grid's winner sits inside it.

# %%
CLEAN = {k: v.get("clean_structures", {}) for k, v in RES.items()}
rows = []
for name, c in CLEAN.items():
    if not c:
        continue
    rows.append({"sample": name, "clean": ", ".join(c.get("clean", [])),
                 "affected": ", ".join(c.get("affected", [])) or "(none)",
                 "clean cells": c.get("cells"),
                 "clean best": c.get("best_sharpe"),
                 "clean best cell": c.get("best_cell"),
                 "clean null median": c.get("null_median"),
                 "clean p_rot": c.get("p_rotation"),
                 "still below null median": c.get("still_below_null_median")})
if rows:
    print(pd.DataFrame(rows).to_string(index=False))
    print()
print("Where 'affected' is empty the exposure does not arise: a rate series has")
print("no contract to be missing, and out2/out3/out4/spr2x4 have no gap in the")
print("settle panel at any horizon. Only rank 1 does.")
print()
print("Measured hole counts are in _probe_expect_exit_holes.py, which splits every")
print("hole into the side knowable at entry (no ENTRY settle) and the side that is")
print("not (no EXIT settle). On SR3 there are zero of the first kind and 28 of the")
print("second on each of out1, spr1x3 and pack1.")

# %% [markdown]
# ## 8. Sensitivities: the vintage bound, and what a one-week delay does
#
# The Citi surprise snapshot is a **single vintage**. It carries only today's read
# of every daily CESI value, Citi revises and periodically rebases, and there is
# no publication axis on the surprise side at all — `G1` in the lead study gates
# speeches, not data. This is the largest residual look-ahead in the stack and it
# cannot be removed here, only bounded: re-run the pre-registered cell with the
# composite delayed an extra one and two weeks. A revision published within a week
# or two of the observation cannot help a book that is not allowed to see it.

# %%
for name, res in RES.items():
    vs = res.get("vintage_sensitivity")
    if vs is None:
        continue
    print(f"{name}: the pre-registered cell with the composite delayed d weeks")
    print("   " + vs.to_string(index=False).replace("\n", "\n   "))
    d0 = vs.loc[vs["extra_delay_w"] == 0].iloc[0]
    rest = vs.loc[vs["extra_delay_w"] > 0]
    print(f"   -> delaying the composite does not DESTROY the result, it MOVES it: "
          f"avg_bp goes {float(d0['avg_bp']):+.3f} -> "
          f"{', '.join(f'{float(x):+.3f}' for x in rest['avg_bp'])}")
    print()
print("These tables are usually read as 'does the edge survive a delay'. Here")
print("nothing survives OR dies -- each cell simply lands somewhere else, by more")
print("than its own size. A book that reorders itself on a one-week delay of its")
print("own input never had a stable edge for a revision to have created. That")
print("answers the vintage question by instability rather than by the test, and")
print("the un-gated exposure stays a real limitation of the composite itself.")

# %% [markdown]
# ## 9. Verdict

# %%
print("=" * 78)
alive = []
for name, res in RES.items():
    p = res["p_rotation"]
    below = res["best_sharpe"] < res["null_summary"]["median"]
    rw = (res.get("family") or {}).get("n_rejected", 0)
    dsr = (res.get("deflation") or {}).get("dsr", np.nan)
    verdict = "DEAD" if (p > 0.05 or below) else "alive?"
    if verdict != "DEAD":
        alive.append(name)
    print(f"{name:6s}  best {res['best_sharpe']:.4f} vs null median "
          f"{res['null_summary']['median']:.4f}  "
          f"({'BELOW' if below else 'above'})  p_rot {p:.4f}  DSR {dsr:.4f}  "
          f"RW rejects {rw}  -> {verdict}")
print("=" * 78)
print(f"{len(alive)} of {len(RES)} samples alive.")
print()
print("The claim under test was that the economic-surprise composite tells you")
print("which way Fedspeak is about to turn, and that the front end has not")
print("priced it. The first half of that is real and was measured by two prior")
print("studies. The second half is what a trade needs, and across 433 weeks of")
print("SR3, 1,122 weeks of 2y OIS and 121 weeks of the point-in-time sentiment")
print("window, nothing here reaches the price.")
print()
print(f"total notebook runtime {time.time() - T0:.1f}s")

# %% [markdown]
# ## Findings tie-out
#
# Every figure the findings block quotes, printed in exactly the form the prose
# quotes it, unit included. `_audit_fed_expected_sentiment_numbers.py` requires
# each to appear verbatim in an executed cell.

# %%
_sr3, _ois, _jpm = RES["SR3"], RES["OIS21"], RES["JPM"]


def _pd(res):      # primary discrete
    return res["primary"]["discrete_score"]


def _pw(res):      # primary weekly
    return res["primary"]["weekly_score"]


def _bc(res):
    b = res["best_cell"]
    return (f"{b['construction']}/L{b['lead_k']}/thr{b['threshold']}/"
            f"h{b['horizon_w']}/{b['structure']}/{b['sign']}")


TIEOUT = {
    "1 SR3 weeks": f"{len(_sr3['support'])}",
    "1 SR3 best cell": _bc(_sr3),
    "1 SR3 best sharpe": f"{_sr3['best_sharpe']:.4f}",
    "1 SR3 null median": f"{_sr3['null_summary']['median']:.4f}",
    "1 SR3 null q95": f"{_sr3['null_summary']['q95']:.4f}",
    "1 SR3 p_rotation": f"{_sr3['p_rotation']:.4f}",
    "1 SR3 percentile of own null": f"{100 * _sr3['null_summary']['observed_percentile']:.1f}%",
    "1 SR3 rotations": f"{_sr3['null_summary']['draws']}",
    "1 SR3 p_floor": f"{_sr3['null_summary']['p_floor']:.4f}",
    "1 SR3 cells": f"{_sr3['n_cells']}",
    "1 SR3 trials": f"{_sr3['n_trials']}",
    "1 SR3 DSR": f"{_sr3['deflation']['dsr']:.4f}",
    "1 SR3 SR0": f"{_sr3['deflation']['sr0']:.4f}",
    "1 SR3 RW rejected": f"{_sr3['family']['n_rejected']}",
    "1 SR3 RW tested": f"{_sr3['family']['n_tested']}",

    "2 OIS weeks": f"{len(_ois['support'])}",
    "2 OIS primary trades": f"{_pd(_ois)['trades']}",
    "2 OIS primary avg_bp": f"{_pd(_ois)['avg_bp']:+.4f}bp",
    "2 OIS primary total_bp": f"{_pd(_ois)['total_bp']:+.2f}bp",
    "2 OIS primary t": f"{_pd(_ois)['t_stat']:.4f}",
    "2 OIS weekly total_bp": f"{_pw(_ois)['total_bp']:+.2f}bp",
    "2 OIS best sharpe": f"{_ois['best_sharpe']:.4f}",
    "2 OIS null median": f"{_ois['null_summary']['median']:.4f}",
    "2 OIS p_rotation": f"{_ois['p_rotation']:.4f}",
    "2 OIS rotations": f"{_ois['null_summary']['draws']}",
    "2 OIS DSR": f"{_ois['deflation']['dsr']:.4f}",

    "3 JPM weeks": f"{len(_jpm['support'])}",
    "3 JPM primary trades": f"{_pd(_jpm)['trades']}",
    "3 JPM primary avg_bp": f"{_pd(_jpm)['avg_bp']:+.4f}bp",
    "3 JPM weekly total_bp": f"{_pw(_jpm)['total_bp']:+.2f}bp",
    "3 JPM best sharpe": f"{_jpm['best_sharpe']:.4f}",
    "3 JPM null median": f"{_jpm['null_summary']['median']:.4f}",
    "3 JPM p_rotation": f"{_jpm['p_rotation']:.4f}",
    "3 JPM rotations": f"{_jpm['null_summary']['draws']}",
    "3 JPM DSR": f"{_jpm['deflation']['dsr']:.4f}",

    "4 roll weeks": f"{ROLL['roll_weeks']}",
    "4 roll total weeks": f"{ROLL['weeks']}",
    "4 naive roll mean": f"{ROLL['naive_roll_mean_bp']:+.2f}bp",
    "4 naive flat mean": f"{ROLL['naive_flat_mean_bp']:+.2f}bp",
    "4 naive roll abs median": f"{ROLL['naive_roll_abs_median_bp']:.1f}bp",
    "4 naive flat abs median": f"{ROLL['naive_flat_abs_median_bp']:.1f}bp",
    "4 true roll mean": f"{ROLL['true_roll_mean_bp']:+.2f}bp",
    "4 fabricated per roll week": f"{ROLL['fabricated_mean_bp']:+.2f}bp",
    "4 fabricated total": f"{ROLL['fabricated_total_bp']:+.1f}bp",
    "4 fabricated on flat weeks": f"{ROLL['fabricated_on_flat_weeks_bp']:.1f}bp",
    "4 trades crossing a rank roll": f"{_crossed}",
    "4 share crossing a rank roll": f"{100 * _crossed / len(_pb):.1f}%",
    "4 worst mark diff anywhere":
        f"{float(pd.to_numeric(GATES['worst_mark_diff'], errors='coerce').max()):.1f}",

    "7 SR3 primary trades": f"{_pd(_sr3)['trades']}",
    "7 SR3 primary avg_bp": f"{_pd(_sr3)['avg_bp']:+.4f}bp",
    "7 SR3 primary total_bp": f"{_pd(_sr3)['total_bp']:+.2f}bp",
    "7 SR3 primary t": f"{_pd(_sr3)['t_stat']:.4f}",
    "7 SR3 primary sign_flip p": f"{_sr3['primary']['sign_flip']['p']:.4f}",
    "7 SR3 primary hit": f"{100 * _pd(_sr3)['hit']:.1f}%",
    "7 SR3 weekly weeks": f"{_pw(_sr3)['weeks']}",
    "7 SR3 weekly total_bp": f"{_pw(_sr3)['total_bp']:+.2f}bp",
    "7 SR3 weekly gross_bp": f"{_pw(_sr3)['gross_total_bp']:+.2f}bp",
    "7 SR3 weekly turnover_bp": f"{_pw(_sr3)['turnover_bp']:.2f}bp",
    "7 SR3 weekly SR_ann": f"{_pw(_sr3)['sharpe_ann']:.4f}",
    "7 SR3 weekly maxDD": f"{_pw(_sr3)['max_dd_bp']:.1f}bp",
    "7 SR3 primary episodes":
        f"{int(_sr3['primary']['episodes']['episode'].nunique())}",

    "6 OIS delay-1 total": f"{float(_ois['vintage_sensitivity'].set_index('extra_delay_w').loc[1, 'total_bp']):+.2f}bp",
    "6 SR3 delay-1 total": f"{float(_sr3['vintage_sensitivity'].set_index('extra_delay_w').loc[1, 'total_bp']):+.2f}bp",
    "6 JPM delay-0 total": f"{float(_jpm['vintage_sensitivity'].set_index('extra_delay_w').loc[0, 'total_bp']):+.2f}bp",
    "6 JPM delay-1 total": f"{float(_jpm['vintage_sensitivity'].set_index('extra_delay_w').loc[1, 'total_bp']):+.2f}bp",
    "6 OIS delay-1 swing": f"{abs(float(_ois['vintage_sensitivity'].set_index('extra_delay_w').loc[1, 'total_bp']) - float(_ois['vintage_sensitivity'].set_index('extra_delay_w').loc[0, 'total_bp'])):.0f}bp",

    "2 OIS SR3-era trades": f"{int(SPLIT.iloc[1]['trades'])}",
    "2 OIS SR3-era avg_bp": f"{float(SPLIT.iloc[1]['avg_bp']):+.4f}bp",
    "2 OIS SR3-era total_bp": f"{float(SPLIT.iloc[1]['total_bp']):+.2f}bp",
    "2 OIS pre-SR3 total_bp": f"{float(SPLIT.iloc[0]['total_bp']):+.2f}bp",
    "7 SR3 primary p_rotation": f"{_sr3['primary']['p_rotation']:.4f}",
    "7 OIS primary p_rotation": f"{_ois['primary']['p_rotation']:.4f}",
    "7 JPM primary p_rotation": f"{_jpm['primary']['p_rotation']:.4f}",
    "8 clean structures": ", ".join(_sr3["clean_structures"]["clean"]),
    "8 affected structures": ", ".join(_sr3["clean_structures"]["affected"]),
    "8 clean-only best": f"{_sr3['clean_structures']['best_sharpe']:.4f}",
    "8 clean-only null median": f"{_sr3['clean_structures']['null_median']:.4f}",
    "8 clean-only p_rotation": f"{_sr3['clean_structures']['p_rotation']:.4f}",
    "8 clean-only still below median":
        f"{_sr3['clean_structures']['still_below_null_median']}",
    "7 SR3 primary null median": f"{_sr3['primary']['null_median']:.4f}",
    "7 SR3 primary rotations": f"{_sr3['primary']['rotation_null']['n_offsets']}",
    "8 SR3 follow share": f"{100 * float((_sr3['league']['sign'] == 'follow').mean()):.1f}%",
    "8 SR3 fade share": f"{100 * float((_sr3['league']['sign'] == 'fade').mean()):.1f}%",
    "8 SR3 follow share in the top 50":
        f"{100 * float((_sr3['league'].nlargest(50, 'sharpe')['sign'] == 'follow').mean()):.1f}%",
}
for k, v in TIEOUT.items():
    print(f"  {k:36s} {v}")
