"""FIG 3 - the scale question: who actually owns these bonds.

Every holder is measured on ONE denominator, the bond's total amount outstanding, so the
three distributions are comparable. (The study's own ownership signal uses publicly held
float -- outstanding minus SOMA -- which is the right denominator for a scarcity story and
the wrong one for a scale comparison, because the Fed's holding is exactly what the two
denominators differ by. Both numbers are quoted in the caption.)

Left: where each holder's share of a bond sits, over every bond-day in the sample.
Right: the same thing as a median with a 10th-90th percentile whisker, one row per holder,
so the order-of-magnitude gap is a distance on the page rather than a pair of numbers.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

import figstyle as FS  # noqa: E402

FS.use()
DATA = os.path.join(HERE, "_data")
FIGS = os.path.join(HERE, "figures")

FUNDS = ["SHY", "GOVT", "IEI", "TLH", "TLT", "IEF"]
#: SOMA is neither the thesis nor the richness control, so it does not take a ROLE colour.
SOMA_INK = "#2E2E2E"


def main() -> None:
    a = pd.read_parquet(os.path.join(DATA, "aggown_full_panel.parquet"))
    cols = ["date", "cusip", "outstanding_amt", "free_float", "soma_holdings", "agg_par"] \
        + [f"par_{f}" for f in FUNDS]
    u = a[cols].drop_duplicates(subset=["date", "cusip"]).copy()
    print(f"unique bond-days {len(u):,}  ({u['date'].min().date()} .. {u['date'].max().date()})")

    out = u["outstanding_amt"].replace(0, np.nan)
    u["s_soma"] = u["soma_holdings"] / out
    u["s_agg"] = u["agg_par"] / out
    u["s_TLT"] = u["par_TLT"] / out
    for f in FUNDS:
        u[f"s_{f}"] = u[f"par_{f}"] / out
    u["ff_TLT"] = u["par_TLT"] / u["free_float"].replace(0, np.nan)
    u["ff_agg"] = u["agg_par"] / u["free_float"].replace(0, np.nan)

    def nz(col: str) -> np.ndarray:
        v = u[col].to_numpy(dtype=float)
        return v[np.isfinite(v) & (v > 0)]

    series = [
        ("Fed SOMA", nz("s_soma"), SOMA_INK, "-"),
        ("all 6 scraped ETFs combined", nz("s_agg"), FS.ROLE["thesis_alt"], "-"),
        ("TLT alone", nz("s_TLT"), FS.ROLE["thesis"], "-"),
    ]

    fig = plt.figure(figsize=(13.2, 4.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.20)
    ax = fig.add_subplot(gs[0, 0])
    axr = fig.add_subplot(gs[0, 1])

    # --------------------------------------------------------------- left: where they live
    # Survival curves, not histograms. On a log axis a density is an artefact of the
    # binning; "what share of bond-days does this holder own at least x of" is not, and
    # the HORIZONTAL distance between two curves is the scale statement directly.
    for name, v, col, ls in series:
        xs = np.sort(v)
        ys = 1.0 - np.arange(len(xs)) / len(xs)
        ax.step(xs, ys * 100, where="post", lw=2.4, color=col, ls=ls,
                label=f"{name}  -  median {np.median(v)*100:.2f}%")
        ax.plot([np.median(v)], [50], "o", color=col, ms=7, zorder=5)
    ax.axhline(50, color=FS.INK["secondary"], lw=0.9, ls=":", zorder=1)
    ax.set_xscale("log")
    ax.set_xlim(1e-4, 1.0)
    ax.set_ylim(0, 100)
    ax.set_xlabel("holder's share of the bond's TOTAL amount outstanding (log scale)")
    ax.set_ylabel("% of bond-days where the holder owns AT LEAST this much")
    ax.set_title("The Fed owns a fifth of a Treasury issue. TLT owns about one per cent.",
                 pad=8)
    ax.legend(loc="lower left", fontsize=8.2)
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda x, _: f"{x*100:g}%" if x >= 0.001 else f"{x*100:.2f}%"))
    ax.annotate("the Fed's 70% per-issue cap",
                xy=(0.695, 2.0), xytext=(0.0135, 13), fontsize=7.8,
                color=FS.INK["primary"], ha="left", va="center",
                arrowprops=dict(arrowstyle="->", lw=0.9, color=FS.INK["muted"],
                                connectionstyle="arc3,rad=-0.12"))

    # -------------------------------------------------------- right: the gap as a distance
    # Every one of these IS a scraped holdings entity, so every one wears the thesis
    # colour. Grey in this pack means "a placebo / nothing real here" and must never be
    # spent on de-emphasis; the non-traded funds are dimmed instead, not recoloured.
    rows = [(f, nz(f"s_{f}"), FS.ROLE["thesis"], 1.0 if f == "TLT" else 0.42)
            for f in FUNDS]
    rows.append(("all 6 combined", nz("s_agg"), FS.ROLE["thesis_alt"], 1.0))
    rows.append(("Fed SOMA", nz("s_soma"), SOMA_INK, 1.0))
    y = np.arange(len(rows))
    for i, (name, v, col, al) in enumerate(rows):
        p10, med, p90 = np.percentile(v, [10, 50, 90])
        axr.plot([p10, p90], [i, i], color=col, lw=2.6, alpha=0.45 * al,
                 solid_capstyle="butt")
        axr.plot([med], [i], "o", color=col, ms=8, zorder=5, alpha=al)
        axr.annotate(f"{med*100:.2f}%", (med, i), textcoords="offset points",
                     xytext=(0, 11), ha="center", fontsize=8.2, color=FS.INK["primary"],
                     fontweight="semibold" if name in ("TLT", "Fed SOMA") else "normal")
    axr.set_yticks(y)
    axr.set_yticklabels([r[0] for r in rows])
    axr.set_ylim(-1.9, len(rows) - 0.25)
    axr.set_xscale("log")
    axr.set_xlim(4e-4, 1.0)
    axr.set_xlabel("share of total amount outstanding (log scale; dot = median, bar = p10-p90)")
    axr.set_title("Two orders of magnitude, and the small one is doing the trading", pad=8)
    axr.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x*100:g}%"))
    axr.grid(axis="y", visible=False)
    axr.axhline(len(rows) - 2.5, color=FS.INK["grid"], lw=0.8)
    axr.text(0.01, 0.02,
             "a holder of ~1% of a Treasury does not price it: regressing a bond's SAME-DAY "
             "richening on that\nfund's own realised trade in it gives |t| <= 0.94 across all "
             "five funds tested, so the flow is not\ndetectable even contemporaneously - "
             "which is the feasibility test, not the signal",
             transform=axr.transAxes, ha="left", va="bottom", fontsize=7.8,
             color=FS.INK["muted"])

    med_tlt = np.median(nz("s_TLT")) * 100
    med_agg = np.median(nz("s_agg")) * 100
    med_soma = np.median(nz("s_soma")) * 100
    med_tlt_ff = np.median(nz("ff_TLT")) * 100
    med_agg_ff = np.median(nz("ff_agg")) * 100
    cap = (
        f"Who owns a US Treasury, over {len(u):,} unique bond-days, 2018-2026 (the window "
        f"on which the aggregate-ownership panel is built). Every share on this figure uses "
        f"the same denominator - the bond's TOTAL amount outstanding - so the three "
        f"distributions can be read against each other; positions of exactly zero are "
        f"excluded. On the study's own denominator, publicly held float (outstanding minus "
        f"SOMA), the same medians are TLT {med_tlt_ff:.2f}% and the six funds combined "
        f"{med_agg_ff:.2f}%. The 1.72% quoted elsewhere in this pack is the same statistic "
        f"over TLT's OWN 20+ universe back to 2016 rather than over this six-fund union "
        f"panel from 2018; both are reproduced, and neither changes the conclusion. "
        f"WHAT IT PROVES. Scale, and it is the number that settles the project. The Fed "
        f"holds a median {med_soma:.1f}% of a Treasury issue and up to the 70% per-issue "
        f"cap that shows as the hard right edge of its distribution. TLT holds a median "
        f"{med_tlt:.2f}%; all six scraped iShares funds together hold {med_agg:.2f}%. The "
        f"two live nearly two orders of magnitude apart, and the small one is the one this "
        f"study proposed to trade behind. "
        f"WHAT IT DOES NOT PROVE. That ownership is irrelevant - it is not. Aggregate ETF "
        f"ownership co-moves with richness contemporaneously at +0.032bp per percentage "
        f"point of float owned, and that survives a Newey-West correction (t 32 -> 8.8). "
        f"What the scale does rule out is the mechanism the trade needed. A holder of ~1.5% "
        f"of an issue cannot push it: regressing a bond's SAME-DAY richening on the fund's "
        f"own realised trade in it, as a share of float, gives |t| <= 0.94 across all five "
        f"funds tested (TLT -0.11, TLH -0.11, GOVT +0.39, IEF +0.78, IEI +0.94). That is a "
        f"feasibility test rather than a signal - if a fund's trade cannot be found in the "
        f"same day's price, no predictive version of it can work - and it fails. The "
        f"contemporaneous ownership coefficient dies predictively too (multivariate 21-day "
        f"t = 0.58), and SOMA's coefficient is NEGATIVE (-0.005bp/pp, HAC t -4.7), the wrong "
        f"sign for scarcity, which marks the whole channel as a proxy for issue "
        f"characteristics rather than a supply effect."
    )
    p = FS.finish(fig, os.path.join(FIGS, "fund_03_ownership_scale.png"), caption=cap)
    print(p)
    for name, v, _c, _a in rows:
        print(f"  {name:22s} n={len(v):7,}  p10={np.percentile(v,10)*100:7.3f}%  "
              f"med={np.median(v)*100:7.3f}%  p90={np.percentile(v,90)*100:7.3f}%  "
              f"max={v.max()*100:7.3f}%")
    print(f"  TLT on free float: med={med_tlt_ff:.3f}%   agg on free float: {med_agg_ff:.3f}%")


if __name__ == "__main__":
    main()
