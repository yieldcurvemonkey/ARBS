"""The trigger pack: what the signal actually does, trade by trade.

Five figures, all off the BASELINE config's own trade log (`_extract_trigger.py`).

Two rules hold across the pack. Every panel that shows an effect carries the measured
round-trip cost at the SAME scale, because at this size the effect and the cost are only
comparable on a shared axis. And the equity curve is never shown alone: the identical
machinery is run on the richness control (`resid`, reads no ETF file) and on the
calendar-only null (`deletion`, reads no ETF file either), so the reader can see what the
holdings actually added.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

import figstyle as FS  # noqa: E402

FS.use()

DATA = HERE / "_data"
FIGS = HERE / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

#: median FedInvest-measured DV01-neutral 20-30y butterfly round trip, RESULTS.md sec.2
COST_MEDIAN = 0.535
#: this book's own realised mean cost per completed package
COST_BOOK = 0.502038

C = pd.read_parquet(DATA / "trig_closed.parquet").sort_values("opened_at").reset_index(drop=True)
CTRL = pd.read_parquet(DATA / "trig_closed_control_resid.parquet").sort_values("opened_at")
NULL = pd.read_parquet(DATA / "trig_closed_null_deletion.parquet").sort_values("opened_at")
LEGS = pd.read_parquet(DATA / "trig_legs.parquet")
SCORES = pd.read_parquet(DATA / "trig_scores.parquet")
META = json.loads((DATA / "trig_meta.json").read_text(encoding="utf-8"))
LT = META["last_trade"]
BELLY = META["last_belly"]

RED = plt.get_cmap(FS.DIVERGING)(0.98)
BLU = plt.get_cmap(FS.DIVERGING)(0.02)


# ============================================================== 1. trigger timeline
def fig01() -> str:
    fig, (ax0, ax1, ax2) = FS.panels(3, 1, w=11.6, h=3.45, sharex=True,
                                     gridspec_kw={"height_ratios": [1.1, 1.0, 1.0]})

    d = pd.to_datetime(C["opened_at"])
    cum_g = C["gross_bp"].cumsum()
    cum_n = C["pnl_bp"].cumsum()

    # ---- A: everything the signal earned, and where it went -----------------------
    ax0.fill_between(d, cum_n, cum_g, color=FS.ROLE["cost"], alpha=0.22, lw=0,
                     label=f"cumulative execution cost ({-C['cost_bp'].sum():,.0f}bp)")
    ax0.plot(d, cum_g, color=FS.ROLE["thesis"], lw=2.2,
             label=f"GROSS ({cum_g.iloc[-1]:+.1f}bp over 1,407 flies)")
    ax0.plot(d, cum_n, color=FS.INK["primary"], lw=2.2,
             label=f"NET ({cum_n.iloc[-1]:+.0f}bp)")
    FS.zero_line(ax0)
    ax0.set_ylabel("cumulative P&L (bp / belly DV01)")
    ax0.set_title("Every basis point the signal found was spent 112 times over on the spread")
    ax0.legend(loc="lower left")
    FS.annotate_null(
        ax0, "TLT ladder, active-weight z, 10d hold, exec_lag = 1.\n"
             "gross +0.0045bp per trade against 0.502bp of measured cost",
        loc="upper right")
    ax0.set_ylim(cum_n.iloc[-1] * 1.08, 185)

    # ---- B: the gross curve on its own scale, with the triggers on it -------------
    ax1.plot(d, cum_g, color=FS.ROLE["thesis"], lw=1.1, alpha=0.55, zorder=2)
    FS.zero_line(ax1)
    long_m = (C["side"] > 0).to_numpy()
    size = 7.0 + 26.0 * (C["score"].abs() / C["score"].abs().max()) ** 2
    ax1.scatter(d[long_m], cum_g[long_m], s=size[long_m], marker="^", c=[RED],
                alpha=0.8, lw=0.4, edgecolor="white", zorder=3)
    ax1.scatter(d[~long_m], cum_g[~long_m], s=size[~long_m], marker="v", c=[BLU],
                alpha=0.8, lw=0.4, edgecolor="white", zorder=3)

    lo = cum_g.min() - 2.6
    ax1.axhspan(lo, lo + COST_MEDIAN, color=FS.ROLE["cost"], alpha=0.30, lw=0)
    ax1.text(d.iloc[3], lo + COST_MEDIAN + 0.25,
             f"the orange band is ONE round trip ({COST_MEDIAN:.3f}bp), to scale",
             color=FS.ROLE["cost"], fontsize=8.5, va="bottom")
    ax1.set_ylabel("cumulative GROSS P&L (bp)")
    ax1.set_title("1,407 triggers, and a gross total worth twelve round trips")
    ax1.set_ylim(lo - 0.5, cum_g.max() + 3.4)
    ax1.legend(handles=[
        Line2D([], [], color=FS.ROLE["thesis"], lw=1.4, alpha=0.7,
               label="cumulative GROSS P&L"),
        Line2D([], [], ls="none", marker="^", ms=7, mfc=RED, mec="white",
               label=f"LONG the belly, {int(long_m.sum())} (fund UNDERweight)"),
        Line2D([], [], ls="none", marker="v", ms=7, mfc=BLU, mec="white",
               label=f"SHORT the belly, {int((~long_m).sum())} (fund OVERweight)"),
        Line2D([], [], ls="none", marker="o", ms=5, mfc=FS.INK["muted"], mec="none",
               label="marker area proportional to |z|"),
    ], loc="upper left", ncol=2)
    FS.annotate_null(ax1, "the gross curve is flat-to-negative for eight of ten years;\n"
                          "all of the +6.3bp arrives after mid-2025", loc="lower right")

    # ---- C: the same machinery on the control and on the calendar null ------------
    for frame, role, lbl in ((C, "thesis", "THESIS: active weight (reads the holdings)"),
                             (CTRL, "control", "CONTROL: own richness residual (no ETF data)"),
                             (NULL, "null", "NULL: 20y deletion calendar (no ETF data)")):
        f = frame.sort_values("opened_at")
        ax2.plot(pd.to_datetime(f["opened_at"]), f["gross_bp"].cumsum(),
                 color=FS.ROLE[role], lw=2.0,
                 label=f"{lbl}   [net {f['pnl_bp'].mean():+.3f}bp/trade]")
    FS.zero_line(ax2)
    # No cost band here: at 61bp of cumulative control gross a 0.535bp band is two
    # pixels tall and reads as a decoration. The cost is stated per trade instead, which
    # is the unit that decides the trade, and panels A and B carry it visually.
    ax2.set_ylim(-32.0, CTRL["gross_bp"].cumsum().max() + 20.0)
    ax2.set_ylabel("cumulative GROSS P&L (bp)")
    ax2.set_xlabel("entry date")
    ax2.set_title("The control that reads no holdings file grosses eight times as much, "
                  "and also loses")
    ax2.legend(loc="upper left")
    FS.annotate_null(
        ax2, "gross per trade: thesis +0.0045, control +0.0372, null -0.0041bp\n"
             "cost per trade:  thesis  0.502, control  0.583, null  0.913bp\n"
             "NOT ONE of the three covers its own execution", loc="lower right")

    fig.align_ylabels([ax0, ax1, ax2])
    return FS.finish(
        fig, FIGS / "fig01_trigger_timeline.png",
        caption=(
            "Baseline TLT book, 1,407 DV01-neutral butterflies, 2016-01-11 to 2026-08-17, "
            "in bp per unit of belly DV01. TOP: cumulative gross ends at +6.3bp; the shaded "
            "wedge is the 706.4bp of measured FedInvest round-trip cost the same trades "
            "paid, leaving -700.1bp net (-0.498bp per trade). MIDDLE: the gross curve on "
            "its own scale with every entry marked -- up-triangle = long the belly (the "
            "fund is underweight it), down-triangle = short, marker area proportional to "
            "|z|. The orange band is one round trip drawn to the same scale: the ten-year "
            "gross total is twelve of them, and the book paid 1,407. BOTTOM: the identical "
            "engine, universe, wings and cost model driven by the richness control and by "
            "the calendar-only deletion null. The control reads no ETF file and grosses "
            "eight times more per trade (+0.0372 vs +0.0045bp); it too loses, because its "
            "own cost is 0.583bp."))


# ============================================================== 2. anatomy of a trade
def fig02() -> str:
    from RVUtils.ETFRebalance import curve as CV

    day = pd.read_parquet(DATA / "trig_lastday.parquet")
    path = pd.read_parquet(DATA / "trig_lastpath.parquet")
    legs = LEGS[LEGS["trade_id"] == LT["trade_id"]].set_index("role")
    tdate = pd.Timestamp(LT["opened_at"])
    xdate = pd.Timestamp(LT["closed_at"])
    front, back = legs.loc["front", "cusip"], legs.loc["back", "cusip"]

    # refit the local curve exactly as prepare_universe did, to recover beta
    g = day.dropna(subset=["ytm", "ttm"]).sort_values("ttm").copy()
    x = g["ttm"].to_numpy(float)
    xs = (x - x.mean()) / max(1e-9, x.std())
    y = g["ytm"].to_numpy(float)
    cpn = g["cpn"].to_numpy(float)
    A = CV._design(xs, 3, cpn)
    beta = CV._huber_fit(A, y)
    b_cpn, cpn_bar = float(beta[-1]), float(cpn.mean())
    # coupon-adjusted yield: what each bond would yield at the average coupon, so the
    # fitted curve becomes a smooth function of maturity alone and can be drawn as a line.
    g["y_adj"] = y - b_cpn * (cpn - cpn_bar)
    xg = np.linspace(x.min(), x.max(), 300)
    xgs = (xg - x.mean()) / max(1e-9, x.std())
    fit_g = CV._design(xgs, 3, np.full_like(xg, cpn_bar)) @ beta

    fig, (axA, axB, axC) = FS.panels(1, 3, w=5.3, h=4.5)
    LEG3 = (("front", front, "s"), ("belly", BELLY, "o"), ("back", back, "s"))

    # ---- A: the local curve and where the three legs sit on it --------------------
    axA.scatter(g["ttm"], g["y_adj"], s=26, color=FS.ROLE["placebo"], alpha=0.8, lw=0,
                label=f"{len(g)} eligible TLT bonds")
    axA.plot(xg, fit_g, color=FS.ROLE["control"], lw=2.0,
             label="local robust cubic fit (+coupon)")
    for role, cus, mk in LEG3:
        r = g[g["cusip"] == cus].iloc[0]
        col = FS.ROLE["thesis"] if role == "belly" else FS.ROLE["thesis_alt"]
        axA.scatter([r["ttm"]], [r["y_adj"]], s=155 if role == "belly" else 95, marker=mk,
                    color=col, zorder=5, edgecolor="white", lw=1.2)
    axA.annotate("BELLY 912810TB4\n1.875% Nov-2051  (SELL)",
                 xy=(LT["ttm_belly"], g.loc[g["cusip"] == BELLY, "y_adj"].iloc[0]),
                 xytext=(0.46, 0.30), textcoords="axes fraction", fontsize=8.5,
                 color=FS.INK["primary"],
                 arrowprops=dict(arrowstyle="->", color=FS.INK["muted"], lw=1.0))
    axA.set_xlabel("time to maturity (years)")
    axA.set_ylabel("coupon-adjusted yield (%)")
    axA.set_title(f"At curve scale the trade is invisible  ({tdate.date()})")
    for _r, _c, _m in LEG3:
        axA.axvline(float(g.loc[g["cusip"] == _c, "ttm"].iloc[0]), color=FS.INK["muted"],
                    lw=0.7, ls=":", zorder=1)
    axA.set_ylim(min(g["y_adj"].min(), fit_g.min()) - 0.0025, g["y_adj"].max() + 0.0055)
    axA.legend(loc="lower left")
    FS.annotate_null(axA, "dotted guides: the three legs, 0.50y apart",
                     loc="upper right")

    # ---- B: the same day in residual bp, with one round trip drawn to scale -------
    axB.scatter(g["ttm"], g["resid_bp"], s=26, color=FS.ROLE["placebo"], alpha=0.8, lw=0)
    FS.zero_line(axB)
    off = {"front": (0, 17), "belly": (16, -4), "back": (0, -21)}
    ha = {"front": "center", "belly": "left", "back": "center"}
    for role, cus, mk in LEG3:
        r = g[g["cusip"] == cus].iloc[0]
        col = FS.ROLE["thesis"] if role == "belly" else FS.ROLE["thesis_alt"]
        axB.scatter([r["ttm"]], [r["resid_bp"]], s=155 if role == "belly" else 95, marker=mk,
                    color=col, zorder=5, edgecolor="white", lw=1.2)
        axB.annotate(f"{role} {r['resid_bp']:+.2f}bp", xy=(r["ttm"], r["resid_bp"]),
                     xytext=off[role], textcoords="offset points", ha=ha[role],
                     fontsize=8.5, color=FS.INK["primary"], zorder=6,
                     bbox=dict(fc="white", ec="none", alpha=0.88, pad=1.4))
    xr, yr = g["ttm"].min() + 0.30, g["resid_bp"].min() - 0.18
    axB.annotate("", xy=(xr, yr), xytext=(xr, yr + LT["cost_bp"]),
                 arrowprops=dict(arrowstyle="|-|,widthA=0.45,widthB=0.45",
                                 color=FS.ROLE["cost"], lw=2.0))
    axB.text(xr + 0.32, yr + LT["cost_bp"] / 2,
             f"this fly's round trip\n{LT['cost_bp']:.3f}bp", color=FS.ROLE["cost"],
             fontsize=8.5, va="center")
    axB.set_xlabel("time to maturity (years)")
    axB.set_ylabel("residual vs the fitted curve (bp; + = cheap)")
    axB.set_title("The dislocation is a third of the spread")
    axB.set_ylim(yr - 0.22, g["resid_bp"].max() + 0.66)
    axB.legend(handles=[
        Line2D([], [], ls="none", marker="o", ms=8, mfc=FS.ROLE["thesis"], mec="white",
               label="belly: signal z = -3.46, SELL"),
        Line2D([], [], ls="none", marker="s", ms=7, mfc=FS.ROLE["thesis_alt"], mec="white",
               label="wings: DV01 and slope neutral"),
        Line2D([], [], ls="none", marker="o", ms=5, mfc=FS.ROLE["placebo"], mec="none",
               label="other eligible bonds"),
    ], loc="upper right")

    # ---- C: the fly rate through the hold, cost band to scale ---------------------
    piv = path.pivot_table(index="date", columns="cusip", values="ytm").sort_index()
    a = float(LT["a"])
    R = (piv[BELLY] - a * piv[front] - (1 - a) * piv[back]) * 100.0
    R0 = float(LT["R_entry_bp"])
    be = R0 + LT["cost_bp"]                       # SHORT belly: profits when R RISES
    be_carry = be - LT["carry_bp"]

    axC.axhspan(R0, be, color=FS.ROLE["cost"], alpha=0.16, lw=0)
    axC.axhline(be, color=FS.ROLE["cost"], ls="--", lw=1.6)
    axC.axhline(be_carry, color=FS.ROLE["cost"], ls=":", lw=1.4)
    axC.plot(R.index, R.to_numpy(), color=FS.ROLE["thesis"], lw=2.2, marker="o", ms=4)
    axC.scatter([R.index[0]], [R0], s=145, marker="v", color=FS.ROLE["thesis"],
                zorder=6, edgecolor="white", lw=1.2)
    axC.scatter([R.index[-1]], [float(LT["R_exit_bp"])], s=145, marker="X",
                color=FS.INK["primary"], zorder=6, edgecolor="white", lw=1.2)
    axC.annotate(f"ENTER short belly  {R0:+.3f}bp", xy=(R.index[0], R0),
                 xytext=(10, 16), textcoords="offset points", fontsize=8.5,
                 color=FS.INK["primary"])
    axC.annotate(f"EXIT  {float(LT['R_exit_bp']):+.3f}bp\nthe belly cheapened "
                 f"{float(LT['R_exit_bp']) - R0:+.3f}bp,\nthe way the signal said",
                 xy=(R.index[-1], float(LT["R_exit_bp"])), xytext=(-20, 34),
                 textcoords="offset points", ha="right", fontsize=8.5,
                 color=FS.INK["primary"],
                 arrowprops=dict(arrowstyle="->", color=FS.INK["muted"], lw=1.0))
    axC.text(R.index[1], be + 0.030,
             f"break-even: the fly must widen {LT['cost_bp']:.3f}bp (round trip)",
             color=FS.ROLE["cost"], fontsize=8.5, va="bottom")
    axC.text(R.index[1], be_carry - 0.030,
             f"break-even after +{LT['carry_bp']:.3f}bp of carry", color=FS.ROLE["cost"],
             fontsize=8, va="top")
    axC.set_ylabel("fly rate   belly - ½front - ½back   (bp)")
    axC.set_xlabel(f"{tdate.date()} to {xdate.date()}  (10 business days)")
    axC.set_title("The signal was right, and the trade still lost")
    axC.set_ylim(min(R.min(), R0) - 0.28, be + 0.30)
    axC.set_xticks(list(R.index)[::2])
    axC.tick_params(axis="x", rotation=30)
    FS.annotate_null(
        axC, f"price {LT['price_bp']:+.3f}  +  carry {LT['carry_bp']:+.3f}  =  GROSS "
             f"{LT['gross_bp']:+.3f}bp\ncost {LT['cost_bp']:.3f}bp   ->   NET "
             f"{LT['pnl_bp']:+.3f}bp", loc="lower right")

    fig.suptitle("The most recent trigger: TLT 1.875% Nov-2051, read as of 2026-07-31, "
                 "traded 2026-08-03", fontsize=12.5, fontweight="semibold", x=0.006,
                 ha="left", y=1.03)
    return FS.finish(
        fig, FIGS / "fig02_one_trade_anatomy.png",
        caption=(
            "One trade, end to end. The fund was 3.46 robust-z OVERWEIGHT 912810TB4 "
            "(1.875% Nov-2051, 25.3y), so the rule sold the belly against 912810SZ2 and "
            "912810TD0 at half weights each. LEFT: at yield scale the dislocation cannot "
            "be seen at all. MIDDLE: in residual bp the belly is +0.18bp cheap to its "
            "local cubic -- about a third of the 0.517bp this package pays to trade, drawn "
            "beside it to scale. RIGHT: over the 10-day hold the belly cheapened by "
            "+0.097bp, the direction the signal called, and with +0.036bp of carry the "
            "package grossed +0.133bp against 0.517bp of cost, for -0.384bp net. The trade "
            "did not fail because the signal was wrong. It failed because the move it was "
            "right about was a fifth of the spread."))


# ============================================================== 3. score distribution
def fig03() -> str:
    s_all = SCORES.dropna(subset=["score"])
    s_ent = s_all[s_all["is_entry_day"]]
    s = s_all["score"].to_numpy(float)
    se = s_ent["score"].to_numpy(float)
    sel = C["score"].to_numpy(float)
    bins = np.linspace(-5, 5, 81)

    fig, (axA, axB) = FS.panels(1, 2, w=6.5, h=4.5)

    axA.hist(s, bins=bins, color=FS.ROLE["placebo"], alpha=0.75,
             label=f"all gated bond-days (n = {len(s):,})")
    axA.hist(sel, bins=bins, color=FS.ROLE["thesis"], alpha=0.95,
             label=f"selected as a butterfly belly (n = {len(sel):,};  mean |z| "
                   f"{np.abs(sel).mean():.2f})")
    axA.set_yscale("log")
    axA.axvline(float(LT["score"]), color=FS.ROLE["cost"], lw=1.6, ls="--")
    pct_tail = 100.0 * float((s <= float(LT["score"])).mean())
    axA.annotate(f"the 2026-08-03 trigger, z = {float(LT['score']):+.2f}\n"
                 f"(the extreme {pct_tail:.2f}% of the distribution)\n"
                 f"net {LT['pnl_bp']:+.3f}bp",
                 xy=(float(LT["score"]), 2.4e3), xytext=(8, 0),
                 textcoords="offset points", ha="left", fontsize=8,
                 color=FS.ROLE["cost"], zorder=6,
                 bbox=dict(fc="white", ec="none", alpha=0.9, pad=1.6))
    axA.set_xlabel("active-weight z (robust, cross-sectional, clipped at ±5)")
    axA.set_ylabel("bond-days (log scale)")
    axA.set_title("A trigger is a rank, not a threshold")
    axA.legend(loc="upper left")
    axA.set_ylim(0.55, 1.1e5)

    # selection rate by z bin, on ENTRY DAYS only -- the days the rule actually looks
    edges = np.arange(-5, 5.01, 0.5)
    ctr = 0.5 * (edges[:-1] + edges[1:])
    nb = len(edges) - 1

    def _count(v):
        i = np.digitize(v, edges) - 1
        i = i[(i >= 0) & (i < nb)]
        return np.bincount(i, minlength=nb).astype(float)

    n_ent, n_sel = _count(se), _count(sel)
    # A bin holding one bond-day reports 0% or 100% and nothing in between, so it is a
    # label for a coin flip, not a rate. Drawn only from five observations up.
    rate = np.where(n_ent >= 5, 100.0 * n_sel / np.maximum(n_ent, 1), np.nan)
    sparse = (n_ent < 40) & (n_ent >= 5)
    solid = n_ent >= 40
    axB.bar(ctr[solid], rate[solid], width=0.46, color=FS.ROLE["thesis"], alpha=0.92,
            label="share of entry-day bond-days that became a trade")
    axB.bar(ctr[sparse], rate[sparse], width=0.46, color=FS.ROLE["thesis"], alpha=0.30,
            hatch="///", edgecolor=FS.ROLE["thesis"], lw=0.6,
            label="fewer than 40 observations in the bin")
    # Bins are 0.5 wide, so a two-line label above a bar collides with its neighbour and
    # with the note above. One line above the bar; the sparse bins' n goes INSIDE the bar,
    # rotated, where it has the whole bar height to itself.
    for cx, rr, ne, sp in zip(ctr, rate, n_ent, sparse):
        if np.isfinite(rr) and rr > 2.0:
            axB.text(cx, rr + 2.0, f"{rr:.0f}%", ha="center", fontsize=7.5,
                     color=FS.INK["secondary"])
            if sp:
                axB.text(cx, 2.0, f"n={int(ne)}", ha="center", va="bottom", rotation=90,
                         fontsize=7.0, color=FS.INK["secondary"], zorder=6)
    axB.set_xlabel("active-weight z bin")
    axB.set_ylabel("selected as a belly, % of entry-day bond-days")
    axB.set_title("It does pick the extremes -- and the merely largest as well")
    axB.set_ylim(0, 108)
    axB.set_xlim(-5.3, 5.3)
    axB.legend(loc="upper left")
    axB.text(0.0, 26.0, "no bond near z = 0 is ever selected", ha="center",
             fontsize=8.5, color=FS.INK["muted"], zorder=6,
             bbox=dict(fc="white", ec="none", alpha=0.9, pad=2.0))
    axB.text(-0.4, 73.0,
             "half the |z| > 3 tail becomes a trade -- but so does 14-16% of\n"
             "the |z| ~ 1.5 body, because three highest and three lowest fire\n"
             "on all 467 entry days whatever the cross-section looks like",
             ha="center", va="bottom", fontsize=8, color=FS.INK["muted"], zorder=6,
             bbox=dict(fc="white", ec="none", alpha=0.9, pad=2.0))

    return FS.finish(
        fig, FIGS / "fig03_score_distribution.png",
        caption=(
            "What it takes to fire. LEFT: the active-weight z over all 80,912 scored TLT "
            "bond-days (grey) against the 1,407 that were selected as a butterfly belly "
            "(blue), log count axis. Mean |z| at selection is 1.93, median 1.78, and the "
            "smallest ever selected is 0.15. RIGHT: among bond-days on the 467 dates that "
            "produced at least one package -- the denominator excludes the handful of "
            "entry dates where no fly could be built, so the rates run a few per cent "
            "high -- the share in each z bin that became a trade; bins holding "
            "fewer than five observations are not drawn and those under forty are hatched. "
            "This is a rank rule -- three highest and three lowest each entry day -- not a "
            "threshold, so it takes half of the |z| > 3 tail but also 14-16% of the |z| ~ "
            "1.5 body, picking up bonds whose dislocation is inside the noise. The "
            "2026-08-03 trigger at z = -3.46 sits in the extreme 0.41% of the whole "
            "distribution and still lost 0.384bp."))


# ============================================================== 4. edge by dislocation
BUCKETS = [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 10.0]
BLABEL = ["0-1.0", "1.0-1.5", "1.5-2.0", "2.0-2.5", "2.5-3.0", ">3.0"]


def fig04() -> str:
    c = C.copy()
    c["bkt"] = pd.cut(c["score"].abs(), BUCKETS, labels=BLABEL, include_lowest=True)
    g = c.groupby("bkt", observed=True).agg(
        n=("gross_bp", "size"), gross=("gross_bp", "mean"), net=("pnl_bp", "mean"),
        gsd=("gross_bp", "std"),
        ghit=("gross_bp", lambda v: (v > 0).mean()),
        nhit=("pnl_bp", lambda v: (v > 0).mean()))
    g["gse"] = g["gsd"] / np.sqrt(g["n"])
    x = np.arange(len(g))
    ticks = [f"{lab}\nn={int(n)}" for lab, n in zip(g.index, g["n"])]
    w = 0.38

    fig, (axA, axB, axC) = FS.panels(1, 3, w=5.3, h=4.5)

    # ---- A: gross on its own scale -- does the edge scale with the dislocation? ----
    axA.bar(x, g["gross"], width=0.62, color=FS.ROLE["thesis"], alpha=0.92,
            yerr=2 * g["gse"], error_kw=dict(ecolor=FS.INK["secondary"], lw=1.2, capsize=3),
            label="mean GROSS bp per trade (±2 s.e.)")
    FS.zero_line(axA)
    axA.set_xticks(x, ticks)
    axA.set_ylim(-0.205, 0.125)
    axA.set_xlabel("|z| at entry")
    axA.set_ylabel("mean gross P&L per trade (bp)")
    axA.set_title("Gross edge does not scale with the dislocation")
    axA.legend(loc="upper right")
    FS.annotate_null(
        axA, "-0.042, -0.001, +0.003, +0.013, +0.018, -0.005bp:\n"
             "non-monotone, sign-flipping, every bucket within\n"
             "2 s.e. of zero -- and the >3 bucket is NEGATIVE.\n"
             "NOTE the axis: the cost line is 0.502bp, 4x off the top.",
        loc="lower left")

    # ---- B: the same bars against the cost, on one axis ---------------------------
    axB.bar(x - w / 2, g["gross"], width=w, color=FS.ROLE["thesis"], alpha=0.92,
            label="GROSS")
    axB.bar(x + w / 2, g["net"], width=w, color=FS.INK["primary"], alpha=0.92,
            label="NET (gross - measured cost)")
    FS.zero_line(axB)
    FS.cost_band(axB, COST_BOOK, label="book's realised round trip")
    axB.set_xticks(x, ticks)
    axB.set_ylim(-0.80, 1.02)
    axB.set_xlabel("|z| at entry")
    axB.set_ylabel("mean P&L per trade (bp)")
    axB.set_title("At the cost's own scale, nothing in any bucket")
    axB.legend(loc="upper left", ncol=1)
    FS.annotate_null(axB, "the blue bars are drawn -- they are 0.005bp tall",
                     loc="lower left")

    # ---- C: hit rate ---------------------------------------------------------------
    axC.bar(x - w / 2, 100 * g["ghit"], width=w, color=FS.ROLE["thesis"], alpha=0.92,
            label="GROSS hit rate")
    axC.bar(x + w / 2, 100 * g["nhit"], width=w, color=FS.INK["primary"], alpha=0.92,
            label="NET hit rate")
    axC.axhline(50, color=FS.ROLE["placebo"], ls="--", lw=1.5, label="a coin (50%)")
    for xi, v in zip(x, 100 * g["ghit"]):
        axC.text(xi - w / 2, v + 1.4, f"{v:.0f}", ha="center", fontsize=8,
                 color=FS.INK["secondary"])
    for xi, v in zip(x, 100 * g["nhit"]):
        axC.text(xi + w / 2, v + 1.4, f"{v:.1f}", ha="center", fontsize=8,
                 color=FS.INK["secondary"])
    axC.set_xticks(x, ticks)
    axC.set_ylim(0, 78)
    axC.set_xlabel("|z| at entry")
    axC.set_ylabel("share of trades with positive P&L (%)")
    axC.set_title("A coin gross; 1-5% net, at every dislocation size")
    axC.legend(loc="upper right")
    FS.annotate_null(
        axC, "gross 46-55%, no trend in |z|;\nnet 1.0-5.0%, because the cost IS the trade",
        loc="upper left")

    return FS.finish(
        fig, FIGS / "fig04_edge_by_dislocation.png",
        caption=(
            "If the holdings signal carried information, a bigger dislocation would pay "
            "more. It does not. LEFT: mean gross P&L per trade by |z| bucket on the gross "
            "scale, ±2 standard errors -- non-monotone (-0.042, -0.001, +0.003, +0.013, "
            "+0.018, -0.005bp), every bucket indistinguishable from zero, and the extreme "
            "|z| > 3 bucket, where the effect should be largest, is negative. MIDDLE: the "
            "same bars against the book's own 0.502bp round trip, which is the scale that "
            "decides the trade. RIGHT: gross hit rate is 46-55% with no trend in |z|, and "
            "net hit rate is 1.0-5.0%, because a 0.5bp cost against a 0.005bp edge turns "
            "almost every trade into a loss however extreme the signal was."))


# ============================================================== 5. P&L waterfall
def fig05() -> str:
    price = float(C["price_bp"].sum())
    carry = float(C["carry_bp"].sum())
    gross = price + carry
    cost = -float(C["cost_bp"].sum())
    net = gross + cost
    n = len(C)

    fig, (axA, axB) = FS.panels(1, 2, w=6.5, h=4.5,
                                gridspec_kw={"width_ratios": [1.35, 1.0]})

    # ---- A: the book total ---------------------------------------------------------
    labels = ["price", "carry", "GROSS", "cost", "NET"]
    vals = [price, carry, gross, cost, net]
    bottoms = [0.0, price, 0.0, gross, 0.0]
    kinds = ["delta", "delta", "total", "delta", "total"]
    # carry wears the PLACEBO grey deliberately: a DV01-neutral package accrues it
    # whatever the signal said, so colouring it as a thesis quantity would credit the
    # holdings with the only positive bar in the decomposition.
    cols = [FS.ROLE["thesis"], FS.ROLE["placebo"], FS.ROLE["thesis"],
            FS.ROLE["cost"], FS.INK["primary"]]
    x = np.arange(len(labels))
    for xi, (v, b, k, col) in enumerate(zip(vals, bottoms, kinds, cols)):
        axA.bar(xi, v, bottom=b, width=0.62, color=col,
                alpha=0.95 if k == "total" else 0.85, edgecolor="white", lw=0.8)
        top = b + v
        axA.annotate(f"{v:+,.1f}", xy=(xi, top), xytext=(0, 9 if v >= 0 else -9),
                     textcoords="offset points", ha="center",
                     va="bottom" if v >= 0 else "top", fontsize=9.5,
                     fontweight="semibold" if k == "total" else "normal",
                     color=FS.INK["primary"])
    for xi, (v, b) in enumerate(zip(vals[:-1], bottoms[:-1])):
        axA.plot([xi + 0.31, xi + 1 - 0.31], [b + v, b + v], color=FS.INK["muted"],
                 lw=0.9, ls=":")
    FS.zero_line(axA)
    axA.set_xticks(x, labels)
    axA.set_ylabel("book total (bp per unit belly DV01)")
    axA.set_title("The cost bar IS the result")
    axA.set_ylim(net * 1.20, 150)
    FS.annotate_null(
        axA, f"{n:,} butterflies, 2016-2026.\nexecution is {abs(cost) / gross:.0f}x the "
             f"entire gross P&L of the strategy", loc="lower left")

    # ---- B: the gross block, zoomed, with the cost bar to scale off the bottom ------
    ylo, yhi = -4.6, 13.0
    heights = abs(cost) / (yhi - ylo)
    x2 = np.arange(3)
    axB.bar(x2, [price, carry, gross], bottom=[0.0, price, 0.0], width=0.6,
            color=[FS.ROLE["thesis"], FS.ROLE["placebo"], FS.ROLE["thesis"]],
            alpha=0.9, edgecolor="white", lw=0.8)
    for xi, (v, b) in enumerate(zip([price, carry, gross], [0.0, price, 0.0])):
        axB.annotate(f"{v:+.2f}bp", xy=(xi, b + v), xytext=(0, 8 if v >= 0 else -8),
                     textcoords="offset points", ha="center",
                     va="bottom" if v >= 0 else "top", fontsize=9.5,
                     color=FS.INK["primary"])
    FS.zero_line(axB)
    axB.set_xticks(x2, ["price", "carry", "GROSS"])
    axB.set_ylabel("book total (bp)")
    axB.set_title(f"Zoomed {(950 / (yhi - ylo)):.0f}x: what the signal actually earned")
    axB.set_ylim(ylo, yhi)
    axB.annotate(f"the cost bar, at THIS scale, runs {abs(cost):,.0f}bp\n"
                 f"-- {heights:.0f} panel-heights below the axis",
                 xy=(0.5, ylo + 0.30), xytext=(0.5, 1.3), ha="center",
                 fontsize=8, color=FS.ROLE["cost"], zorder=6,
                 bbox=dict(fc="white", ec="none", alpha=0.92, pad=2.0),
                 arrowprops=dict(arrowstyle="-|>", color=FS.ROLE["cost"], lw=1.8))
    axB.legend(handles=[
        Line2D([], [], marker="s", ls="none", ms=8, mfc=FS.ROLE["thesis"], mec="none",
               label="what the signal drove"),
        Line2D([], [], marker="s", ls="none", ms=8, mfc=FS.ROLE["placebo"], mec="none",
               label="carry: earned by the structure, not the signal"),
    ], loc="upper left")
    FS.annotate_null(
        axB, f"per trade: price {price / n:+.4f}, carry {carry / n:+.4f},\n"
             f"gross {gross / n:+.4f} against cost {abs(cost) / n:.3f}bp\n"
             f"break-even cost multiple {gross / abs(cost):.4f}", loc="lower right")

    return FS.finish(
        fig, FIGS / "fig05_pnl_waterfall.png",
        caption=(
            "Where the 1,407 trades' P&L went. LEFT: the book total decomposed -- price "
            "-2.1bp, carry +8.4bp, gross +6.3bp, measured FedInvest execution -706.4bp, "
            "net -700.1bp. Execution is 112x the entire gross P&L, which is why the cost "
            "bar is the only one that can be seen. RIGHT: the gross block zoomed 54x. The "
            "price leg -- the part the signal is supposed to drive -- is NEGATIVE over ten "
            "years; the positive gross is carry on a DV01-neutral package, which no signal "
            "produced. Per trade that is +0.0045bp of gross against 0.502bp of cost, a "
            "break-even cost multiple of 0.0089."))


FIGS_MAP = {1: fig01, 2: fig02, 3: fig03, 4: fig04, 5: fig05}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig", type=int, nargs="*", default=sorted(FIGS_MAP))
    a = ap.parse_args()
    for k in a.fig:
        print(FIGS_MAP[k]())
