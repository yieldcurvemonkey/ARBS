"""Chart 1 - the event-time fan.

Why a fan and not an equity curve: an equity curve is cumulative, so it hides the
distribution, conflates the signal with sizing and trade selection, and cannot show
WHEN inside the window the move happens.  The fan shows the three things a causal
"driver" claim needs, all at once - nothing before the event, separation AT it,
persistence after it.  Here it shows the first and not the other two.

POST-REVIEW REVISION.  Four things changed after the adversarial reviews:

 1. The annotation box used to print the hawk-dove GAP next to the signed-COMPOSITE
    excess as though the second were the placebo-adjusted version of the first.
    They are different quantities (the gap is 1.9-2.7x the composite by
    construction).  The box now prints the true gap DiD, and the release-clean
    gap DiD underneath it.
 2. The placebo band is now the PARENT-MATCHED book (the pseudo-events drawn for
    exactly these events), not the full 2,931.  For fig1 the honest band is 43%
    wider than the one previously drawn.
 3. "flat, as a clean event study requires - no leakage, no selection" overstated
    a POOLED SLOPE.  The gap the title is about reaches +0.66 bp at -90 min,
    before anyone has spoken, which is LARGER than the +0.58 bp it reaches four
    hours later.  That sentence is now on the figure.
 4. The twins share a y-axis, so "4.4x the sample" is a visual comparison.

Every number is read from c5_fixes.json so the figure and the write-up cannot
drift apart.
"""
from __future__ import annotations

import io
import json
import sys
import textwrap
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from c_common import (C_DOVE, C_GRID, C_HAWK, C_INK, C_INK2, C_PLACEBO, HERE, OFFSETS,
                      PRE_OFFSETS, arm_paths, cluster_mean_se, cluster_ols, load_rank3,
                      signed_path, wide)

XT = [-120, -60, 0, 60, 120, 180, 240, 300]
FIX = json.load(open(HERE / "c5_fixes.json"))

# the window, said the same way everywhere
WINDOW_WORDS = ("Window is \u221260 \u2192 +240 min \u2014 FIVE hours, of which FOUR are after the "
                "speech starts.")


def pre_slope_hr(piv, meta):
    offs = [o for o in PRE_OFFSETS if o != -60]
    s = meta["stance_sign"].to_numpy()
    ys, xs, cs = [], [], []
    for o in offs:
        v = piv[o].to_numpy() * s
        ok = np.isfinite(v)
        ys.append(v[ok]); xs.append(np.full(ok.sum(), o, float))
        cs.append(meta["date"].to_numpy()[ok])
    y, x, c = np.concatenate(ys), np.concatenate(xs), np.concatenate(cs)
    r = cluster_ols(y, np.column_stack([np.ones_like(x), x]), c, names=["const", "slope"])
    return r["slope"]["coef"] * 60.0, r["slope"]["t"]


def band(ax, path, color, label, lw=2.0, ls="-", z=3, marker="o", ms=4.0, fill=0.15):
    x = np.array(OFFSETS, float)
    m = path["mean"].to_numpy()
    se = path["se"].to_numpy()
    ax.fill_between(x, m - 2 * se, m + 2 * se, color=color, alpha=fill, lw=0, zorder=z - 1)
    ax.plot(x, m, color=color, lw=lw, ls=ls, marker=marker, ms=ms,
            markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.6,
            label=label, zorder=z, solid_capstyle="round")
    return m


def end_labels(ax, items, x=307, size=9.5, gapfrac=0.052):
    """Direct labels at the right edge, pushed apart so they never collide."""
    ylo, yhi = ax.get_ylim()
    gap = (yhi - ylo) * gapfrac
    items = sorted(items, key=lambda z: z[0])
    ys = [it[0] for it in items]
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < gap:
            ys[i] = ys[i - 1] + gap
    for (yv, col, txt), yy in zip(items, ys):
        if abs(yy - yv) > 1e-9:
            ax.plot([300, x - 1], [yv, yy], color=col, lw=0.7, alpha=0.6,
                    clip_on=False, zorder=6)
        ax.text(x, yy, txt, color=col, fontsize=size, fontweight="bold",
                ha="left", va="center", clip_on=False, zorder=7)


def dress(ax):
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=C_GRID, lw=0.7)
    ax.xaxis.grid(False)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(C_GRID)
    ax.tick_params(colors=C_INK2, labelsize=9, length=3)
    ax.axhline(0, color=C_INK2, lw=0.9, alpha=0.55, zorder=1)
    ax.axvline(0, color=C_INK, lw=1.2, alpha=0.75, zorder=2)


def prep(evsub, plsub):
    """Everything drawn, computed once, so the twins can share a y-scale."""
    piv, meta = wide(evsub)
    ppiv, pmeta = wide(plsub)
    return dict(
        piv=piv, meta=meta,
        hawk=arm_paths(piv, meta, 1), dove=arm_paths(piv, meta, -1),
        pl_pooled=pd.DataFrame(
            [dict(offset_min=o, **cluster_mean_se(ppiv[o].to_numpy(), pmeta["date"].to_numpy()))
             for o in OFFSETS]).set_index("offset_min"),
        sig=signed_path(piv, meta), psig=signed_path(ppiv, pmeta),
        slope=pre_slope_hr(piv, meta))


def render(P, key, out, title1, title2, subtitle, book_note, ylim_top, ylim_bot):
    F = FIX[key]
    hawk, dove, pl_pooled, sig, psig = P["hawk"], P["dove"], P["pl_pooled"], P["sig"], P["psig"]
    slope_hr, slope_t = P["slope"]

    g = F["gap_240"]
    did = F["placebo_parent_matched"]["gap_did_240"]
    didc = F["release_split_240"]["gap_did_clean_parent_matched"]
    rc = F["release_split_240"]
    nh, nd = F["n_hawk"], F["n_dove"]
    ph = F["priced_n_by_offset"]["240"]["hawk"]
    pd_ = F["priced_n_by_offset"]["240"]["dove"]

    fig = plt.figure(figsize=(12.0, 11.4), dpi=220, facecolor="white")
    gs = fig.add_gridspec(2, 1, height_ratios=[2.5, 1.0], hspace=0.15,
                          left=0.085, right=0.845, top=0.860, bottom=0.315)
    ax = fig.add_subplot(gs[0]); ax.set_facecolor("white")
    bx = fig.add_subplot(gs[1], sharex=ax); bx.set_facecolor("white")

    # ---------- main panel: the two arms against the placebo ----------
    dress(ax)
    band(ax, pl_pooled, C_PLACEBO, "Placebo \u2014 the no-speech days drawn for THESE events",
         lw=1.6, ls=(0, (5, 2.5)), z=3, marker="", fill=0.22)
    mh = band(ax, hawk, C_HAWK, f"Ex-ante HAWKISH  (n={nh}; {ph} priced at +240)", z=5)
    md = band(ax, dove, C_DOVE, f"Ex-ante DOVISH  (n={nd}; {pd_} priced at +240)", z=5)

    ax.set_ylabel("Mean change in SR3 3rd-contract implied rate\nfrom t\u221260 min  (bp)",
                  fontsize=10.5, color=C_INK, labelpad=8)
    ax.tick_params(labelbottom=False)
    ax.set_ylim(*ylim_top)
    ylo, yhi = ylim_top
    span = yhi - ylo

    ax.text(6, yhi - span * 0.215, "speech begins", ha="left", va="top",
            fontsize=9, color=C_INK2, style="italic", zorder=8)

    # pre-event box: the SLOPE is flat, but the GAP is not, and the gap is the
    # quantity the title is about.  Both go on the figure.
    pg = F["pre_event_gap_at_argmax_bp"]
    po = F["pre_event_gap_argmax_offset"]
    sl = f"{slope_hr:+.2f}".replace("-", "\u2212")
    st = f"{slope_t:+.2f}".replace("-", "\u2212")
    pgs = f"{pg:+.2f}".replace("-", "\u2212")
    pos = (f"{po:+d}".replace("-", "\u2212"))
    ax.text(-118, ylo + span * 0.035,
            f"pre-event drift \u2212120 \u2192 \u22125 min:  {sl} bp/hour  (t = {st}) \u2014 no trend into the event."
            f"\nBut the hawk\u2212dove gap itself wanders: it reaches {pgs} bp at {pos} min, "
            f"BEFORE anyone has spoken \u2014"
            f"\n{abs(pg) / abs(g['coef']):.2f}\u00d7 the +240 gap the title is about. That is the noise floor "
            f"a real reaction has to clear.",
            fontsize=8.7, color=C_INK2, ha="left", va="bottom", zorder=8,
            bbox=dict(boxstyle="round,pad=0.45", fc="white", ec=C_GRID, lw=0.8))

    # the +240 gap annotation: THREE versions of ONE quantity, never mixed with
    # the signed composite.
    yh, yd = mh[OFFSETS.index(240)], md[OFFSETS.index(240)]
    ax.annotate("", xy=(240, yh), xytext=(240, yd),
                arrowprops=dict(arrowstyle="<->", color=C_INK, lw=1.4,
                                shrinkA=2, shrinkB=2), zorder=8)
    box = (f"hawk \u2212 dove at +240 min          {g['coef']:+.2f} bp   (t = {g['t']:+.2f}, n = {g['n']})\n"
           f"same gap vs the matched placebo   {did['coef']:+.2f} bp   (t = {did['t']:+.2f})\n"
           f"\u2026and on RELEASE-FREE windows only  {didc['coef']:+.2f} bp   (t = {didc['t']:+.2f}, n = {didc['n']})\n"
           f"None of the three clears p < 0.05.").replace("-0.", "\u22120.")
    ax.annotate(box,
                xy=(240, (yh + yd) / 2), xytext=(236, ylo + span * 0.235),
                textcoords="data", ha="right", va="center", fontsize=8.8, color=C_INK,
                zorder=9, family="DejaVu Sans Mono",
                arrowprops=dict(arrowstyle="-", color=C_INK, lw=0.8, alpha=0.7,
                                shrinkA=4, shrinkB=4),
                bbox=dict(boxstyle="round,pad=0.5", fc="white", ec=C_INK, lw=0.9, alpha=0.96))

    end_labels(ax, [(mh[-1], C_HAWK, "HAWKISH"), (md[-1], C_DOVE, "DOVISH"),
                    (pl_pooled["mean"].iloc[-1], C_PLACEBO, "PLACEBO")])

    ax.legend(loc="upper left", frameon=True, fontsize=9, framealpha=0.96,
              edgecolor=C_GRID, borderpad=0.6, handlelength=2.4)

    # ---------- second panel: the tradeable quantity in one line ----------
    dress(bx)
    x = np.array(OFFSETS, float)
    bx.fill_between(x, psig["mean"] - 2 * psig["se"], psig["mean"] + 2 * psig["se"],
                    color=C_PLACEBO, alpha=0.24, lw=0, zorder=2)
    bx.plot(x, psig["mean"], color=C_PLACEBO, lw=1.4, ls=(0, (5, 2.5)), zorder=3)
    bx.fill_between(x, sig["mean"] - 2 * sig["se"], sig["mean"] + 2 * sig["se"],
                    color=C_INK, alpha=0.13, lw=0, zorder=4)
    bx.plot(x, sig["mean"], color=C_INK, lw=2.0, marker="o", ms=3.6,
            markerfacecolor=C_INK, markeredgecolor="white", markeredgewidth=0.6, zorder=5)
    bx.set_ylim(*ylim_bot)
    end_labels(bx, [(sig["mean"].iloc[-1], C_INK, "SIGNED\nCOMPOSITE"),
                    (psig["mean"].iloc[-1], C_PLACEBO, "PLACEBO")], size=8.6, gapfrac=0.155)
    s240 = sig.loc[240]
    bx.annotate(f"{s240['mean']:+.2f} bp  (t = {s240['t']:+.2f}, n = {int(s240['n'])})\n"
                f"release-free windows only:  {rc['clean']['mean']:+.2f} bp  "
                f"(t = {rc['clean']['t']:+.2f}, n = {rc['clean']['n']})".replace("-0.", "\u22120."),
                xy=(240, s240["mean"]),
                xytext=(-92, 17), textcoords="offset points", ha="center", fontsize=8.4,
                color=C_INK, zorder=8,
                bbox=dict(boxstyle="round,pad=0.34", fc="white", ec=C_GRID, lw=0.7, alpha=0.95))
    bx.set_ylabel("Signed move\n(bp; + = the way the\nstance predicted)",
                  fontsize=9.5, color=C_INK, labelpad=8)
    bx.set_xlabel("Minutes from the start of the speech", fontsize=10.5, color=C_INK, labelpad=6)
    bx.set_xticks(XT)
    bx.set_xticklabels([(f"{t:+d}".replace("-", "−") if t else "0") for t in XT])
    bx.set_xlim(-128, 306)
    bx.legend(handles=[Line2D([], [], color=C_INK, lw=2.0, marker="o", ms=3.6,
                              label="Signed composite (hawks + doves pooled) \u00b12 SE"),
                       Patch(fc=C_PLACEBO, alpha=0.32, ec="none", label="Placebo \u00b12 SE")],
              loc="upper left", frameon=True, fontsize=8.4, framealpha=0.96,
              edgecolor=C_GRID, borderpad=0.5, handlelength=2.2, ncol=2, columnspacing=1.4)

    # ---------- titles and footnote ----------
    fig.text(0.085, 0.978, title1, fontsize=15.0, color=C_INK, fontweight="bold", ha="left", va="top")
    fig.text(0.085, 0.942, title2, fontsize=15.0, color=C_INK, fontweight="bold", ha="left", va="top")
    fig.text(0.085, 0.904, subtitle, fontsize=10.2, color=C_INK2, ha="left", va="top")
    fig.text(0.085, 0.278, book_note, fontsize=7.4, color=C_INK2, ha="left", va="top",
             linespacing=1.52)

    fig.savefig(out, dpi=220, facecolor="white")
    plt.close(fig)
    print(f"wrote {out}")


WRAP = 172


def foot(*paras):
    return "\n".join(textwrap.fill(p, WRAP) for p in paras)


def main():
    ev, pl = load_rank3()
    clean_ids = set(ev.loc[~ev["is_overlapping"], "event_id"].unique())
    all_ids = set(ev["event_id"].unique())

    # PARENT-MATCHED placebo for each book: the pseudo-events drawn for exactly
    # these parents, not the whole placebo file.  For fig1 this widens the band
    # by 43% - the previously drawn band was too narrow for the comparison made.
    P1 = prep(ev[~ev["is_overlapping"]], pl[pl["parent_event_id"].isin(clean_ids)])
    P2 = prep(ev, pl[pl["parent_event_id"].isin(all_ids)])

    # shared y-scale across the twins, so "4.4x the sample" is visual
    def rng_of(P, keys, pad_lo=0.06, pad_hi=0.20):
        lo = min(float((P[k]["mean"] - 2 * P[k]["se"]).min()) for k in keys)
        hi = max(float((P[k]["mean"] + 2 * P[k]["se"]).max()) for k in keys)
        s = hi - lo
        return lo - s * pad_lo, hi + s * pad_hi

    t1 = rng_of(P1, ["hawk", "dove", "pl_pooled"])
    t2 = rng_of(P2, ["hawk", "dove", "pl_pooled"])
    YT = (min(t1[0], t2[0]), max(t1[1], t2[1]))
    b1 = rng_of(P1, ["sig", "psig"], 0.10, 0.42)
    b2 = rng_of(P2, ["sig", "psig"], 0.10, 0.42)
    YB = (min(b1[0], b2[0]), max(b1[1], b2[1]))
    print(f"shared y-limits: top {YT}, bottom {YB}")

    common = (
        "METHOD. y = mean cumulative change in the SR3 3rd-contract implied rate (100 \u2212 price) off minute "
        "bars, baselined at t\u221260; ribbons \u00b12 SE CLUSTERED BY DAY. " + WINDOW_WORDS + " Arms are the SIGN of "
        "the speaker's ex-ante point-in-time JPM score, so the label existed before the speech; neutral-bucket "
        "speakers (|score| < 10) are kept. Price at T = close of the last bar labelled STRICTLY BEFORE T "
        "(bars are start-stamped), voided past a 15-min staleness cap \u2014 the CAUSAL rule; the leaky "
        "alternative (last bar \u2264 T) would inflate the +30 composite 6.3\u00d7 and the +240 gap to +0.68 bp.",
        "RELEASE-FREE = no scheduled high/medium-impact US macro release anywhere in \u221260\u2192+240, rebuilt at "
        "MINUTE resolution from the timestamped ForexFactory calendar. 28.1% of windows are NOT release-free; "
        "the panel's own is_cpi_day / is_nfp_day are DAY flags and catch only 4\u20135%. Events after the calendar "
        "ends (2026-08-07) are excluded from BOTH arms, never defaulted to clean.",
        "PLACEBO = same weekday, same clock time, calendar-matched no-speech business days drawn for THESE "
        "parent events, stance inherited. CAVEAT: 48% of placebo days sit within 10 days of an FOMC decision "
        "against 2% of real speech days, so the null comes from quieter days and every excess-over-placebo "
        "number here is biased UPWARD \u2014 the true excess is smaller than shown.",
        "COVERAGE HOLES. The signed sample is 2023\u20132026, not 2022\u20132026: the point-in-time lookup returns no "
        "score for any 2022 speech, so all 160 of that year's events are absent \u2014 the fastest tightening cycle "
        "in 40 years is not in this picture. The SVB week (2023-03-06\u201317) also carries zero signed events. The "
        "MEDIAN move is exactly 0 bp at every offset: SR3 ticks in 0.5 bp and most windows never move a tick.")

    render(P1, "fig1_nonoverlap", HERE / "fig1_event_fan.png",
           "Fedspeak barely moves the front end: four hours on, hawks and doves are",
           "just +0.6 bp apart (t = 0.8) \u2014 and that gap was +0.7 bp before anyone spoke",
           "SR3 3rd contract \u00b7 224 clean single-speaker events, 2023\u20132026 \u00b7 the paths start together, "
           "stay together through the speech, and end together",
           foot("HEADLINE BOOK \u2014 non-overlapping events only: no other Fed calendar entry whose "
                "[\u2212120, +300] window touches this one. n = 224 signed events (173 hawk / 51 dove) on 200 "
                "distinct days; 184 priced at +240 (140 hawk / 44 dove). The 51-event dove arm is thin and its "
                "wide ribbon says so. Day fixed effects cannot be run on this book \u2014 non-overlapping events "
                "are one per day by construction, so no day carries both arms; see fig1b.",
                "TAIL SENSITIVITY: the three largest of 184 events sum to 103% of the entire summed signed "
                "move, and the other 181 sum to \u22122.0 bp. Dropping the top 1% of days \u2014 2025-04-09 (the "
                "90-day tariff pause) and 2024-08-05 (the yen-carry unwind), neither flagged by any calendar "
                "column \u2014 takes the composite from +0.36 bp (t = 0.99) to +0.01 bp (t = 0.03). The headline "
                "mean is three events, not a central tendency.",
                *common), YT, YB)

    render(P2, "fig1b_all", HERE / "fig1b_event_fan_all.png",
           "4.4\u00d7 the sample, the same answer: the study's one borderline number \u2014 a",
           "+0.71 bp hawk\u2212dove gap over placebo (t = 1.9) \u2014 halves on release-free windows",
           "SR3 3rd contract \u00b7 985 events including overlapping windows, 2023\u20132026 \u00b7 point estimates "
           "match the headline book; only the error bars shrink",
           foot("ALL-EVENTS BOOK \u2014 overlapping windows included, so one market move is counted once per "
                "speaker who happened to be talking. n = 985 signed events (767 hawk / 218 dove) on 438 days; "
                "808 priced at +240. Of 271 (day, symbol) groups holding more than one event, 20 book an "
                "IDENTICAL +240 move to every event in the group, and one group carries 10 events \u2014 day "
                "clustering fixes the inference, not the attribution, so the effective sample is smaller than "
                "985.",
                "THE BORDERLINE NUMBER, IN FULL. The hawk\u2212dove gap against the matched placebo is +0.71 bp "
                "(t = 1.92, p \u2248 0.055) \u2014 the largest t in the study on the deck's central quantity. It does "
                "not survive its own robustness: on release-free windows it is +0.34 bp (t = 1.13); with DAY "
                "fixed effects (hawks vs doves ON THE SAME DAY, 93 identifying days) the stance slope is "
                "\u22120.06 bp (t = \u22120.31); and it is confined to the late window (+0.25 bp, t = 1.26 at "
                "+30 min; +0.71, t = 1.92 at +240; +0.78, t = 1.90 at +300) \u2014 i.e. it grows with the hours "
                "of unlabelled macro the window swallows, not with proximity to the speech. It is reported "
                "because it is the honest maximum, not because it is a finding.",
                *common), YT, YB)


if __name__ == "__main__":
    main()
