"""FIG 4 - creations and redemptions, and what is actually IN a basket.

Top: TLT's shares outstanding over ten years, with every flow day of 2% or more marked and
coloured by direction.

Bottom left: how much of a day's gross par movement one pro-rata scaling of the whole book
explains, on creation/redemption days against ordinary days -- the question "is a basket
chosen, or is it just the fund made bigger" answered as a distribution.

Bottom right: the largest genuine creation in the sample, bond by bond. If a basket is
pro-rata, every bond sits on one ray through the origin.

Two measurements this rests on, both made rather than assumed
-------------------------------------------------------------
**The share count is stamped one document LATE.** Within one iShares document the par book
and the ``shares_outstanding`` line do not refer to the same session: pairing
par(t)/par(t-1) with the share change reported on t+1 explains 99.9% of the gross par move,
against -121.8% for the same-day pairing and -18.7% for the other direction.
``HP.flag_flow_days`` stamps ``is_flow_day`` on t, so it labels the document AFTER the one
that holds the basket.

**The 2017-H1 hole is not a 38% creation.** TLT's largest apparent share-count jump,
+37.8% on 2017-07-06, is a ``diff()`` taken across a six-month publication gap. Any pair of
documents more than five calendar days apart is dropped here.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import TwoSlopeNorm  # noqa: E402

import figstyle as FS  # noqa: E402

FS.use()
DATA = os.path.join(HERE, "_data")
FIGS = os.path.join(HERE, "figures")

TKR = "TLT"
FLOW_T = 0.02
MAX_GAP_D = 5


def build():
    h = pd.read_parquet(os.path.join(DATA, "raw_holdings_TLT_TLH.parquet"))
    h["date"] = pd.to_datetime(h["date"])
    d = h[h["ticker"] == TKR]
    par = d.pivot_table(index="date", columns="cusip", values="par", aggfunc="sum").fillna(0.0)
    sh = d.groupby("date")["shares_out"].first().reindex(par.index)

    o = pd.DataFrame(index=par.index)
    o["shares_out"] = sh
    o["gap_d"] = par.index.to_series().diff().dt.days
    o["flow_pct"] = sh.pct_change(fill_method=None).shift(-1)
    o["gap_next"] = o["gap_d"].shift(-1)

    dpar, prev = par.diff(), par.shift()
    o["gross"] = dpar.abs().sum(axis=1)
    pro = prev.mul(o["flow_pct"], axis=0)
    o["resid"] = (dpar - pro).abs().sum(axis=1)
    o["prorata_pct"] = (1.0 - o["resid"] / o["gross"].replace(0, np.nan)) * 100.0

    ok = (o["gap_d"] <= MAX_GAP_D) & (o["gap_next"] <= MAX_GAP_D) & o["flow_pct"].notna()
    o["usable"] = ok
    o["is_flow"] = ok & (o["flow_pct"].abs() >= FLOW_T)
    return o, par, dpar, prev


def main() -> None:
    o, par, dpar, prev = build()
    u = o[o["usable"]]
    fl = o[o["is_flow"]]
    qt = u[~u["is_flow"]]
    print(f"documents {len(o):,}; usable pairs {len(u):,}; flow days >= {FLOW_T:.0%} "
          f"{len(fl):,} ({int((fl['flow_pct']>0).sum())} creations / "
          f"{int((fl['flow_pct']<0).sum())} redemptions)")
    print("pro-rata % flow :",
          fl["prorata_pct"].describe(percentiles=[.05, .25, .5, .75]).round(2).to_dict())
    print("pro-rata % quiet:",
          qt["prorata_pct"].describe(percentiles=[.05, .25, .5, .75]).round(2).to_dict())

    fig = plt.figure(figsize=(13.0, 7.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.02], hspace=0.42, wspace=0.24)
    ax0 = fig.add_subplot(gs[0, 0:2])
    cax = ax0.inset_axes([1.008, 0.0, 0.011, 1.0])
    axL = fig.add_subplot(gs[1, 0])
    axR = fig.add_subplot(gs[1, 1])

    lim = float(np.nanpercentile(fl["flow_pct"].abs(), 95)) * 100
    norm = TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)
    cmap = plt.get_cmap(FS.DIVERGING)

    # -------------------------------------------------------------- shares outstanding
    ax0.plot(o.index, o["shares_out"] / 1e6, color=FS.INK["secondary"], lw=1.3,
             label="shares outstanding", zorder=2)
    sc = ax0.scatter(fl.index, fl["shares_out"] / 1e6, c=fl["flow_pct"] * 100, cmap=cmap,
                     norm=norm, s=14 + 260 * fl["flow_pct"].abs(), zorder=5, lw=0.4,
                     edgecolor="white",
                     label=f"a day the share count moved {FLOW_T:.0%} or more "
                           f"(n={len(fl)}; marker size = |move|)")
    ax0.set_ylabel("shares outstanding (millions)")
    ax0.set_title(f"TLT creates and redeems constantly - {len(fl)} days of "
                  f"{FLOW_T:.0%} or more in ten years", pad=8)
    ax0.legend(loc="upper left", fontsize=8.2)
    cb = fig.colorbar(sc, cax=cax)
    cb.set_label("share-count change on the day (%)", fontsize=8)
    cb.ax.tick_params(labelsize=7.5)

    seam = o[~o["usable"] & (o["gap_d"] > MAX_GAP_D)]
    if len(seam):
        s0 = seam.index[0]
        ax0.annotate("the 2017-H1 publication gap - a +37.8%\n"
                     "'creation' that never happened, dropped",
                     xy=(s0, float(o.loc[s0, "shares_out"]) / 1e6),
                     xytext=(pd.Timestamp("2018-02-01"), 300), fontsize=7.8,
                     color=FS.INK["primary"], ha="left", va="center",
                     arrowprops=dict(arrowstyle="->", lw=0.9, color=FS.INK["muted"]))

    # ------------------------------------------------- bottom left: the two distributions
    for name, v, col, lw in (
            ("creation / redemption day", fl["prorata_pct"], FS.ROLE["thesis"], 2.4),
            ("ordinary day", qt["prorata_pct"], FS.ROLE["placebo"], 2.0)):
        x = np.sort(v.dropna().to_numpy())
        name = f"{name} (n={len(x):,})"
        y = 100.0 - 100.0 * np.arange(len(x)) / len(x)
        axL.step(x, y, where="post", lw=lw, color=col,
                 label=f"{name}  -  median {np.median(x):.1f}%")
    axL.set_xlim(0, 100)
    axL.set_ylim(0, 100)
    axL.set_xlabel("% of the day's gross par move explained by ONE pro-rata scaling")
    axL.set_ylabel("% of days at least this pro-rata")
    axL.set_title("A basket is the fund made bigger", pad=8)
    axL.legend(loc="lower left", fontsize=8.2)
    axL.text(0.035, 0.46,
             f"a creation day is MORE mechanical than an ordinary one\n"
             f"(mean {fl['prorata_pct'].mean():.1f}% against "
             f"{qt['prorata_pct'].mean():.1f}%): whatever reallocation\n"
             f"the manager does, creation is not when it happens",
             transform=axL.transAxes, ha="left", va="bottom", fontsize=7.8,
             color=FS.INK["muted"])

    # ------------------------------------------------- bottom right: the exemplar basket
    D = fl["flow_pct"].idxmax()
    f0 = float(fl.loc[D, "flow_pct"])
    x = prev.loc[D] / 1e6
    y = dpar.loc[D] / 1e6
    keep = (x > 0) | (y.abs() > 0)
    axR.scatter(x[keep], y[keep], s=34, color=FS.ROLE["thesis"], alpha=0.85, lw=0.4,
                edgecolor="white", zorder=5, label=f"one bond ({int(keep.sum())} held)")
    xx = np.array([0, float(x.max()) * 1.05])
    axR.plot(xx, xx * f0, color=FS.ROLE["placebo"], lw=1.8, ls="--", zorder=3,
             label=f"a perfectly pro-rata basket (+{f0*100:.1f}% of every line)")
    FS.zero_line(axR)
    axR.set_xlabel("the fund's par in the bond the day before ($mm)")
    axR.set_ylabel("change in par on the day ($mm)")
    axR.set_title(f"The largest creation, bond by bond ({D.date()})", pad=8)
    axR.legend(loc="upper left", fontsize=8.2)
    dev = ((y / x.replace(0, np.nan)) - f0).abs() * 100
    axR.text(0.98, 0.07,
             f"{int((dev < 0.5).sum())} of {int(dev.notna().sum())} bonds land within 0.5pp\n"
             f"of the one common scaling factor",
             transform=axR.transAxes, ha="right", va="bottom", fontsize=7.8,
             color=FS.INK["muted"])

    cap = (
        f"TLT's shares outstanding, 2016-2026, and what a creation basket contains. "
        f"{len(fl)} of {len(u):,} usable document pairs moved the share count by "
        f"{FLOW_T:.0%} or more ({int((fl['flow_pct']>0).sum())} creations, "
        f"{int((fl['flow_pct']<0).sum())} redemptions). "
        f"WHAT IT PROVES. Creation and redemption is not an occasional event - TLT went from "
        f"{o['shares_out'].dropna().iloc[0]/1e6:.0f}m to "
        f"{o['shares_out'].dropna().iloc[-1]/1e6:.0f}m shares in hundreds of discrete steps, "
        f"the largest a single-day {fl['flow_pct'].abs().max()*100:.1f}%. But the two lower "
        f"panels are the finding, and it is a negative: a basket is overwhelmingly the fund "
        f"made bigger rather than a set of bonds anyone picked. One pro-rata scaling of the "
        f"whole book explains a median {fl['prorata_pct'].median():.1f}% of the gross par "
        f"movement on a flow day, and on the largest creation in the sample "
        f"({D.date()}, +{f0*100:.1f}%) {int((dev < 0.5).sum())} of {int(dev.notna().sum())} "
        f"bonds sit within half a percentage point of the same scaling factor. "
        f"WHAT IT DOES NOT PROVE. That there is no discretion at all - the distribution has "
        f"a real left tail, with a 5th percentile of {fl['prorata_pct'].quantile(0.05):.0f}% "
        f"on flow days. But note which way the comparison runs: an ordinary day is LESS "
        f"pro-rata than a creation day (mean {qt['prorata_pct'].mean():.1f}% against "
        f"{fl['prorata_pct'].mean():.1f}%), so whatever reallocation the manager does is not "
        f"something creation reveals. And the residual is the smallest signal in the study: "
        f"`flow` scores a 63-day IC of +0.006 with a naive t of 1.3 - and the naive t is the "
        f"inflated one. Conditioning on creation, redemption and quiet days leaves the share "
        f"of positive outcomes at 0.52-0.56, the same as every other cut tried. "
        f"NOTE ON CONSTRUCTION. Two corrections are applied here that the pack's other "
        f"numbers do not carry. (1) Within one iShares document the par book and the "
        f"shares_outstanding line are NOT the same session: pairing par(t)/par(t-1) with the "
        f"share change reported on t+1 explains 99.9% of the gross par move, against -121.8% "
        f"same-day and -18.7% the other way, so HP.flag_flow_days stamps the flow on the "
        f"document AFTER the one holding the basket. (2) TLT's largest apparent creation, "
        f"+37.8% on 2017-07-06, is a diff() across the six-month publication gap; every "
        f"document pair more than {MAX_GAP_D} calendar days apart is dropped."
    )
    p = FS.finish(fig, os.path.join(FIGS, "fund_04_creation_redemption.png"), caption=cap)
    print(p)
    print(f"exemplar {D.date()} flow {f0*100:.2f}%  bonds within 0.5pp of the ray: "
          f"{int((dev < 0.5).sum())}/{int(dev.notna().sum())}")


if __name__ == "__main__":
    main()
