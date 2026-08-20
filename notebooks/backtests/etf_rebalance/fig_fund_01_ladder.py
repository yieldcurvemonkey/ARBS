"""FIG 1 - the constant-maturity ladder as a heatmap over ten years.

x = date, y = constant-maturity bucket counted UP from TLT's 20-year deletion boundary,
colour = active weight in bp (fund DV01 weight minus index DV01 weight), diverging and
centred at zero.

The honest companion (right panel): the same active weights collapsed over time, median
and inter-quartile range per bucket. If the alternating over/under structure were a
sequence of dislocations that get closed, the time-collapsed distribution would centre on
zero with wide tails. It does not -- it is a stable LEVEL, which is what a sampling fund
that never intends to close the gap looks like.
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
WIDTH_Y = 0.25


def main() -> None:
    lad = pd.read_parquet(os.path.join(DATA, "fundfig_ladder_TLT.parquet"))
    lad["bucket"] = lad["bucket"].astype(float)
    lad["aw_bp"] = lad["active_w"] * 1e4
    # The ladder spans every PANEL date on which an index bond exists, which is more
    # dates than TLT publishes a document for. On a date with no document w_f is 0 and
    # the active weight is minus the whole index weight -- an "underweight everything"
    # stripe that is a missing file, not a position. Keep only dates TLT actually
    # reported.
    flow = pd.read_parquet(os.path.join(DATA, "fundfig_flow_TLT_TLH.parquet"))
    doc_dates = set(pd.to_datetime(flow.loc[flow["ticker"] == "TLT", "date"]))
    n0 = lad["date"].nunique()
    lad = lad[lad["date"].isin(doc_dates)]
    print(f"ladder dates {n0} -> {lad['date'].nunique()} (dates with a published TLT document)")
    # Buckets 0..39 = the 20-30y band in 3-month slots. Bucket -1 is below the boundary
    # (a bond TLT still holds after deletion) and has no index weight, so it is not an
    # ACTIVE weight and does not belong on a diverging scale with the rest.
    lad = lad[(lad["bucket"] >= 0) & (lad["bucket"] <= 39)]

    dates = np.sort(lad["date"].unique())
    buckets = np.arange(0, 40)
    grid = (lad.pivot_table(index="bucket", columns="date", values="aw_bp", aggfunc="mean")
               .reindex(index=buckets, columns=dates))

    # Every business day, so the 2017-H1 publication hole reads as a hole rather than as
    # a wide cell stretched across six months of missing files.
    full = pd.bdate_range(dates.min(), dates.max())
    grid = grid.reindex(columns=full)
    Z = grid.to_numpy(dtype=float)

    lim = float(np.nanpercentile(np.abs(Z), 98))
    lim = round(lim / 25) * 25
    norm = TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)
    cmap = plt.get_cmap(FS.DIVERGING).copy()
    cmap.set_bad("#F0F0F0")

    fig = plt.figure(figsize=(13.4, 5.0))
    gs = fig.add_gridspec(1, 3, width_ratios=[4.15, 1.0, 0.075], wspace=0.13)
    ax = fig.add_subplot(gs[0, 0])
    axr = fig.add_subplot(gs[0, 1], sharey=ax)
    cax = fig.add_subplot(gs[0, 2])

    # ---------------------------------------------------------------- left: the ladder
    xe = np.concatenate([full.values, [full.values[-1] + np.timedelta64(1, "D")]])
    ye = np.concatenate([buckets * WIDTH_Y, [buckets[-1] * WIDTH_Y + WIDTH_Y]])
    mesh = ax.pcolormesh(xe, ye, np.ma.masked_invalid(Z), cmap=cmap, norm=norm,
                         shading="flat", rasterized=True)
    ax.set_ylabel("years of maturity ABOVE the 20y deletion boundary")
    ax.set_title("An overweight rides DOWN the curve with the bond that carries it",
                 pad=8)
    ax.set_ylim(0, 10)
    ax.set_yticks(np.arange(0, 10.1, 1.0))
    ax.set_yticklabels([f"+{int(v)}y" for v in np.arange(0, 10.1, 1.0)])
    ax.grid(False)
    ax.axhline(0.0, color=FS.INK["primary"], lw=1.2)
    ax.text(full.values[3], 0.10, "bucket 0  =  the last 3 months before TLT must sell",
            fontsize=8, color=FS.INK["primary"], va="bottom", ha="left")

    # Direct-label the publication hole on the stripe itself rather than in a corner box.
    gap = pd.Timestamp("2017-03-20")
    ax.text(gap, 5.0, "no TLT document\npublished (2017-H1)", rotation=90, ha="center",
            va="center", fontsize=7.6, color=FS.INK["muted"])

    cb = fig.colorbar(mesh, cax=cax)
    cb.set_label("active weight, bp of fund DV01  (fund - index)", fontsize=8.5)
    cb.ax.tick_params(labelsize=8)

    # -------------------------------------------------- right: collapsed over time
    q = (lad.groupby("bucket")["aw_bp"]
            .agg(med="median", q25=lambda s: s.quantile(0.25),
                 q75=lambda s: s.quantile(0.75), n="size")
            .reindex(buckets))
    yc = buckets * WIDTH_Y + WIDTH_Y / 2.0
    axr.fill_betweenx(yc, q["q25"], q["q75"], color=FS.ROLE["thesis"], alpha=0.22, lw=0,
                      label="inter-quartile range, 2016-2026")
    axr.plot(q["med"], yc, color=FS.ROLE["thesis"], lw=2.0, label="median")
    axr.axvline(0, color=FS.INK["secondary"], lw=0.9, zorder=1)
    axr.set_xlabel("active weight (bp)")
    axr.set_title("collapsed over ten years", pad=8)
    axr.set_xlim(-470, 400)
    axr.set_xticks([-400, -200, 0, 200])
    axr.legend(loc="lower left", fontsize=7.6, handlelength=1.4, borderaxespad=0.5)
    plt.setp(axr.get_yticklabels(), visible=False)

    axr.annotate(f"freshly auctioned 30y\n{q['med'].iloc[38]:.0f}bp LIGHT",
                 xy=(q["med"].iloc[38], 38 * WIDTH_Y + WIDTH_Y / 2), xytext=(55, 9.45),
                 fontsize=7.6, color=FS.INK["primary"], ha="left", va="center",
                 arrowprops=dict(arrowstyle="-", lw=0.8, color=FS.INK["muted"]))
    axr.annotate("26-28y belly\npersistently HEAVY",
                 xy=(q["med"].iloc[27], 27 * WIDTH_Y + WIDTH_Y / 2), xytext=(-460, 7.4),
                 fontsize=7.6, color=FS.INK["primary"], ha="left", va="center",
                 arrowprops=dict(arrowstyle="-", lw=0.8, color=FS.INK["muted"]))

    # The honesty rule: a panel that shows an effect carries its own verdict. This one
    # shows very large gaps, and the caption is not where a reader looks first. The right
    # panel is too narrow to hold it without landing on the two callouts, so it goes in
    # the heatmap's pale lower-right corner.
    ax.text(0.985, 0.045,
            "NOT a signal. These gaps score a 63-day IC of -0.065 on forward richening -- "
            "BACKWARDS -- and\n+0.005bp per unit z at Newey-West t 0.89 once the bond's own "
            "richness is controlled for,\nagainst a 0.535bp round trip. A gap that never "
            "closes is a policy, not an opportunity.",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
            color=FS.INK["secondary"], zorder=8,
            bbox=dict(fc="white", ec=FS.INK["grid"], lw=0.6, alpha=0.90, pad=3.0))

    cap = (
        "TLT's active weight against its own index, by constant-maturity 3-month bucket, "
        "2016-2026 (2,528 published documents, 97,616 filled slot-days). Bucket 0 is "
        "always the last three months before the 20-year deletion boundary, so a slot "
        "keeps its economic meaning while bonds roll down through it. Colour is clipped "
        f"at +/-{lim:.0f}bp, the 98th percentile of |active weight|; grey cells are dates "
        "with no index bond in that slot, and the wide grey stripe is the known "
        "publication hole - iShares serves no TLT document before 2017-07-06. "
        "WHAT IT PROVES. Two things, both real and both verified in the holdings files "
        "themselves. First, the gaps are LARGE: the median slot runs tens of bp of fund "
        f"DV01 and the extremes several hundred, against a cross-sectional richness "
        "dispersion of 0.434bp and a 0.535bp butterfly round trip. Second, and this is "
        "what the diagonal banding is, an overweight belongs to a BOND and not to a "
        "maturity slot - it walks down the ladder at roughly one 3-month bucket per "
        "quarter for years on end. The right panel collapses ten years onto the slot axis "
        "and the shape survives: TLT is persistently light in the freshly auctioned 30-year "
        f"(bucket 38, median {q['med'].iloc[38]:.0f}bp) and in the last two years before "
        "deletion, and persistently heavy through the 26-28y belly. "
        "WHAT IT DOES NOT PROVE. That any of it is tradeable, or even that it is a "
        "dislocation. The identical picture is produced by a SAMPLING fund that holds "
        "~40 of ~50 index bonds and has no intention of ever closing the gap: a standing "
        "shape maintained on purpose, not a queue of imbalances waiting to revert. The "
        "diagonals say so directly - if these were dislocations being worked off, they "
        "would fade in place rather than ride the roll for three years. And the "
        "measurement agrees: the 63-day IC of active weight on forward richening is "
        "-0.065, i.e. BACKWARDS (underweight bonds subsequently CHEAPEN), and once the "
        "bond's own richness is controlled for it is +0.005bp per unit z with "
        "Newey-West t = 0.89 - not significant, and roughly one fortieth of a round trip. "
        "Read this panel as a portrait of a portfolio, not as a signal. "
        "NOTE ON CONSTRUCTION. The index leg is rebuilt here after recovering ttm for "
        "index members TLT does not hold; HP.ladder was dropping them, a median 10.0% of "
        "index weight and 8 bonds per date (max 27.8% / 15 bonds). No exec_lag is applied "
        "anywhere in this figure - it describes a portfolio rather than trading one."
    )
    p = FS.finish(fig, os.path.join(FIGS, "fund_01_ladder_heatmap.png"), caption=cap)
    print(p)
    print(f"colour limit +/-{lim:.0f}bp; buckets {buckets.min()}-{buckets.max()}; "
          f"dates {len(full)}; non-null cells {int(np.isfinite(Z).sum()):,}")
    print(q.round(1).to_string())


if __name__ == "__main__":
    main()
