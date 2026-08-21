"""The seasonality figure pack.

Every panel carries its null or its control, because the question this pack answers is
not "is there a pattern" -- there are several -- but "is there a pattern that is not
reproduced by a holdings-free series with the same maturity profile, and is any of it
larger than one round trip". Those are different questions with different answers and the
figures are laid out so the reader cannot see one without the other.
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import figstyle as FS  # noqa: E402

FS.use()
DATA = HERE / "_data"
FIG = HERE / "figures"
FIG.mkdir(parents=True, exist_ok=True)

J = json.loads((DATA / "seas_headline_numbers.json").read_text(encoding="utf-8"))

#: The pack's measured cost line. 0.535bp is the median DV01-neutral 20-30y butterfly
#: round trip on FedInvest's own published bid/offer, 0.30bp in 2016 to 0.95bp in 2023.
COST_TLT = 0.535
COST_TLH = J["TLH"]["fly_rt_bp_median"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def cells(fund: str, key: str, h: int = 10) -> pd.DataFrame:
    d = pd.read_csv(DATA / f"seas_cells_{fund}_{key}_h{h}.csv")
    if key == "bd_me":
        d = d[d["bd_me"].between(-10, 10)]
    return d.sort_values(key).reset_index(drop=True)


# ===================================================================== figure 1

def fig1() -> str:
    """Business day relative to month end: the signal, its placebo, and the control."""
    th = cells("TLT", "bd_me")
    ct = pd.read_csv(DATA / "seas_cells_control_TLT_bd_me.csv").query("-10<=bd_me<=10")
    ct = ct.sort_values("bd_me")
    unc = J["TLT"]["uncond_bp"]
    fam = J["TLT"]["family"]
    pk = J["TLT"]["per_key"]["bd_me"]
    mc = {m["h"]: m for m in J["TLT"]["me_contrast"]}

    fig, (ax, bx) = FS.panels(1, 2, w=6.6, h=4.3, sharex=True)
    x = th["bd_me"].to_numpy()

    ax.fill_between(x, th["lo"], th["hi"], color=FS.ROLE["thesis"], alpha=0.18, lw=0,
                    label="thesis, 90% bootstrap")
    ax.plot(x, th["mean_bp"], color=FS.ROLE["thesis"], marker="o", ms=3.5,
            label="most underweight $-$ most overweight (TLT holdings)")
    ax.fill_between(x, th["plc_lo"], th["plc_hi"], color=FS.ROLE["placebo"], alpha=0.22,
                    lw=0, label="placebo, 5-95% of 100 draws")
    ax.plot(x, th["plc_mean_bp"], color=FS.ROLE["placebo"], lw=1.6, ls="-",
            label="maturity-matched placebo (no holdings)")
    FS.zero_line(ax)
    ax.axhline(unc, color=FS.INK["muted"], ls=":", lw=1.4,
               label=f"the series' own mean, {unc:+.3f}bp")
    # The reconstitution band goes in the LEGEND, not as text beside the line. A rotated
    # in-panel label at x=0 is exactly where both the legend and the verdict box want to
    # be, and it collided with each of them in turn.
    ax.axvline(0, color=FS.INK["grid"], lw=6, zorder=0,
               label="the month-end reconstitution")
    ax.set_ylim(th["lo"].min() - 0.042, th["hi"].max() + 0.014)
    ax.set_title("The month-end tilt is backwards, and a placebo covers it")
    ax.set_xlabel("business days relative to month end (0 = last trading day)")
    ax.set_ylabel("mean 10-day forward richening, bp")
    ax.legend(loc="lower left", ncol=1, fontsize=7.8)
    FS.annotate_null(
        ax,
        f"largest |HAC t| over the 21 cells: {abs(pk['t_hac']):.2f}\n"
        f"100 holdings-free placebos reach {pk['plc_med']:.2f} (median), "
        f"{pk['plc_max']:.2f} (max)\np = {pk['p_per_key']:.2f}   NOT significant",
        loc="upper left")

    bx.fill_between(ct["bd_me"], ct["lo"], ct["hi"], color=FS.ROLE["control"], alpha=0.18,
                    lw=0)
    bx.plot(ct["bd_me"], ct["mean_bp"], color=FS.ROLE["control"], marker="o", ms=3.5,
            label="cheap $-$ rich on the local curve (no ETF data)")
    FS.zero_line(bx)
    FS.cost_band(bx, COST_TLT)
    bx.axvline(0, color=FS.INK["grid"], lw=6, zorder=0,
               label="the month-end reconstitution")
    bx.set_ylim(-0.075, 0.66)
    bx.set_title("The control works every day of the month, and still under cost")
    bx.set_xlabel("business days relative to month end (0 = last trading day)")
    bx.set_ylabel("mean 10-day forward richening, bp")
    bx.legend(loc="upper left", fontsize=8.2)
    FS.annotate_null(
        bx,
        f"HAC t between {ct['t_hac'].min():.1f} and {ct['t_hac'].max():.1f} in EVERY cell,\n"
        f"but {ct['mean_bp'].mean():.2f}bp against a {COST_TLT:.2f}bp round trip",
        loc="lower right")
    ax.set_xticks(range(-10, 11, 2))

    cap = (
        "TLT 20-31y, 2016-2026, 2,502 dates, ~32 gated names a day so a decile is about "
        "three bonds; forward richening measured against the local cubic, exec_lag=1.\n"
        f"LEFT: the holdings spread runs {th.loc[th.bd_me.between(-9,-1),'mean_bp'].mean():+.3f}bp "
        f"in the nine days before the reconstitution and {th.loc[th.bd_me.between(1,9),'mean_bp'].mean():+.3f}bp "
        "in the nine days after -- but the sign is BACKWARDS (the fund's underweights subsequently "
        "cheapen, RESULTS.md 3.1).\n"
        "Seven of the 21 cells do fall below the placebo band, and that is the LEVEL rather than the "
        "season: every one of the seven is on the same side, and the series' unconditional mean is "
        f"already {unc:+.3f}bp (HAC t {J['TLT']['uncond_t_hac']:.2f}) before any calendar is applied. What asks "
        "about seasonality is the SHAPE, and the shape is what the placebo reproduces.\n"
        f"Reading the largest of 21 cells is a 21-trial search: the real maximum is |HAC t| "
        f"{abs(pk['t_hac']):.2f} against a placebo maximum whose median is {pk['plc_med']:.2f} and whose "
        f"largest of 100 is {pk['plc_max']:.2f}, i.e. p = {pk['p_per_key']:.2f}. Does NOT survive Newey-West "
        "once the search is charged.\n"
        "The one pre-specified version -- pre-month-end minus post-month-end, averaged WITHIN each "
        f"month-end cycle so nine overlapping 10-day returns count once -- gives "
        f"{mc[10]['diff_bp']:+.3f}bp at HAC t {mc[10]['t_hac']:.2f} (p = {mc[10]['p']:.2f}) at the traded "
        f"10-day horizon. It reaches HAC t {mc[1]['t_hac']:.2f} at 1 day (p = {mc[1]['p']:.2f}), which is one "
        "of four horizons looked at, and TLH's same contrast has the OPPOSITE sign at the same "
        f"horizon ({J['TLH']['me_contrast'][0]['diff_bp']:+.3f}bp, HAC t "
        f"{J['TLH']['me_contrast'][0]['t_hac']:+.2f}). Two funds on the same reconstitution calendar "
        "disagreeing on the sign is what a selected effect looks like.\n"
        "RIGHT, for scale: the bond's own richness residual -- which reads no holdings file -- earns "
        f"{ct['mean_bp'].mean():.2f}bp on the identical selection rule, {ct['mean_bp'].mean()/abs(th['mean_bp']).mean():.0f}x "
        "the holdings spread PER UNIT OF SPREAD, at HAC t 3.4-6.5 in every single cell and with no "
        "month-end shape at all. (RESULTS.md 3.3's 'thirty times more' is the same comparison per unit of "
        "signal z, where the holdings spread does not get to keep its own level; the two are different "
        "statistics, not a disagreement.) "
        f"It is still {COST_TLT/ct['mean_bp'].mean():.1f}x below the measured {COST_TLT:.2f}bp butterfly round trip.\n"
        "CONTEXT: a prior ARBS study measured a genuine month-end effect in the long end -- seasoned "
        "issues richen against current on month-end day, pooled t = 3.96, 16 of 17 years. That effect "
        "is a maturity/seasoning tilt on one day; it is not this signal, and nothing in this panel "
        "reproduces it from holdings.")
    return FS.finish(fig, FIG / "seas_01_month_end_signal_vs_control.png", caption=cap)


# ===================================================================== figure 2

def fig2() -> str:
    """Day of month, day of week, month of year -- the same spread, one hue, shared y."""
    unc = J["TLT"]["uncond_bp"]
    specs = [("dom", "day of month", None),
             ("dow", "day of week", DOW),
             ("moy", "month of year", MON)]
    fig, axes = FS.panels(1, 3, w=4.6, h=4.2)
    tabs = {k: cells("TLT", k) for k, _, _ in specs}
    lo = min(min(t["mean_bp"].min(), t["plc_lo"].min()) for t in tabs.values())
    hi = max(max(t["mean_bp"].max(), t["plc_hi"].max()) for t in tabs.values())
    rng = hi - lo
    # Headroom at the top, not a tight fit. Almost every bar is negative, so the space
    # above zero is where the per-panel verdict can sit without landing on the data --
    # and a verdict the eye has to hunt for is a verdict the reader skips.
    ylo, yhi = lo - 0.10 * rng, hi + 0.62 * rng

    for ax, (key, lab, ticks) in zip(axes, specs):
        t = tabs[key]
        x = np.arange(len(t))
        best = int(t["t_hac"].abs().idxmax())
        lws = [0.0] * len(t)
        lws[best] = 1.6
        ax.bar(x, t["mean_bp"], width=0.72, color=FS.ROLE["thesis"], alpha=0.9,
               edgecolor=FS.INK["primary"], linewidth=lws,
               label="TLT holdings spread (decile $\\approx$ 3 bonds)")
        ax.vlines(x, t["lo"], t["hi"], color=FS.ROLE["thesis"], lw=1.1, alpha=0.5)
        ax.fill_between(x, t["plc_lo"], t["plc_hi"], color=FS.ROLE["placebo"], alpha=0.30,
                        lw=0, step="mid", label="maturity-matched placebo, 5-95%")
        ax.plot(x, t["plc_mean_bp"], color=FS.ROLE["placebo"], lw=1.3,
                drawstyle="steps-mid", label="placebo mean")
        FS.zero_line(ax)
        ax.axhline(unc, color=FS.INK["muted"], ls=":", lw=1.4,
                   label=f"the series' own mean, {unc:+.3f}bp")
        ax.set_ylim(ylo, yhi)
        ax.set_xlabel(lab)
        pkj = J["TLT"]["per_key"][key]
        name = (ticks[best] if ticks is not None else f"day {int(t.loc[best, key])}")
        ax.set_title(lab)
        FS.annotate_null(
            ax,
            f"strongest cell {name}: {t.loc[best,'mean_bp']:+.3f}bp, HAC t "
            f"{t.loc[best,'t_hac']:+.2f}\n"
            f"100 placebos over these cells reach {pkj['plc_med']:.2f} (median), "
            f"{pkj['plc_max']:.2f} (max)\np = {pkj['p_per_key']:.2f}  PER KEY ONLY -- "
            f"not charged for the 70-cell search",
            loc="upper left")
        if ticks is not None:
            ax.set_xticks(x)
            ax.set_xticklabels(ticks, rotation=0, fontsize=8)
        else:
            ax.set_xticks(x[::3])
            ax.set_xticklabels(t[key].astype(int).astype(str).tolist()[::3])
    axes[0].set_ylabel("mean 10-day forward richening, bp")
    h, l = axes[0].get_legend_handles_labels()
    famj = J["TLT"]["family"]
    fig.suptitle(
        "Charge the 70-cell search and no calendar cut clears its placebo "
        f"(family-wise p = {famj['p_familywise']:.2f})",
        x=0.005, ha="left", fontsize=12.5, fontweight="semibold")
    # The per-panel p's are per KEY. Left on their own they read as significance, which is
    # the opposite of the verdict, so the family-wise number is stamped at figure level.
    fig.text(0.005, 0.915,
             f"the three p's below are each charged only for their OWN key. Across all "
             f"{famj['n_cells_searched']} cells in this figure and figure 1 the real maximum |HAC t| is "
             f"{famj['best_t']:.2f} against a placebo maximum of median {famj['plc_med']:.2f}, "
             f"p90 {famj['plc_p90']:.2f}, largest {famj['plc_max']:.2f}: "
             f"family-wise p = {famj['p_familywise']:.2f}, NOT significant",
             ha="left", va="top", fontsize=8.5, color=FS.INK["muted"])
    axes[1].text(
        0.03, 0.60,
        "the spread is negative on ALL FIVE weekdays,\nso this is the series' own LEVEL "
        "showing up in a\ncalendar cut, not a day-of-week effect",
        transform=axes[1].transAxes, ha="left", va="top", fontsize=8,
        color=FS.INK["muted"])
    fig.subplots_adjust(bottom=0.20, top=0.82)
    fig.legend(h, l, loc="lower center", ncol=4, bbox_to_anchor=(0.5, 0.005),
               fontsize=8.5)
    axes[2].text(
        0.97, 0.70,
        f"TLT's worst month is {MON[J['cross_fund']['tlt_best_month']-1]}; TLH's is "
        f"{MON[J['cross_fund']['tlh_best_month']-1]}.\nTLH in TLT's month: HAC t "
        f"{J['cross_fund']['tlh_at_tlt_best']:+.2f} (wrong sign).",
        transform=axes[2].transAxes, ha="right", va="bottom", fontsize=8,
        color=FS.INK["muted"])

    fam = J["TLT"]["family"]
    cap = (
        "TLT 20-31y, same spread and same units as figure 1, faceted on three calendar keys with a "
        "shared y-scale and one hue. Bars are the holdings spread; the grey band is the 5-95% range "
        "of 100 maturity-matched placebo series read the same way; the dotted line is the series' "
        f"own unconditional mean, {unc:+.3f}bp (HAC t {J['TLT']['uncond_t_hac']:.2f}).\n"
        "That dotted line is why the bars mislead if read against zero. The spread is negative on "
        "ALL FIVE weekdays, so 'Friday is significant' is the level showing up in a calendar cut, not "
        "a day-of-week effect. Restating the strongest cell of all -- August -- as a deviation from "
        f"the series' own mean takes it from {J['TLT']['best_cell']['mean_bp']:+.3f}bp at HAC t "
        f"{J['TLT']['best_cell']['t_vs_zero_hac']:.2f} to {J['TLT']['best_cell']['dev_bp']:+.3f}bp at HAC t "
        f"{J['TLT']['best_cell']['t_vs_level_hac']:.2f}.\n"
        f"Charging the whole search: these three keys plus figure 1's are {fam['n_cells_searched']} cells. "
        f"The largest real |HAC t| anywhere in them is {fam['best_t']:.2f}; the largest a placebo draw "
        f"produces over the SAME {fam['n_cells_searched']} cells has median {fam['plc_med']:.2f}, p90 "
        f"{fam['plc_p90']:.2f} and maximum {fam['plc_max']:.2f}. Family-wise p = {fam['p_familywise']:.2f}. "
        "NOTHING here survives Newey-West once the selection is paid for.\n"
        "Cross-fund: TLT's worst month is August and TLH's is September. Over the window both funds "
        f"cover (2022 onward, TLH's gated universe does not reach 20 names before then) the two monthly "
        f"profiles correlate {J['cross_fund_common_window']['moy_signal_corr']:.2f}, but the selected cells "
        "do not replicate -- TLT's August is "
        f"{J['cross_fund_common_window']['TLH_by_month_bp']['8']:+.3f}bp in TLH (wrong sign) and TLH's "
        f"September is {J['cross_fund_common_window']['TLT_by_month_bp']['9']:+.3f}bp in TLT.")
    return FS.finish(fig, FIG / "seas_02_calendar_cuts_small_multiples.png", caption=cap)


# ===================================================================== figure 3

def fig3() -> str:
    """The reconstitution, measured in the funds' own filings. This part is real."""
    fi = pd.read_csv(DATA / "seas_fund_intensity.csv", parse_dates=["date"])
    cal = pd.read_csv(DATA / "seas_calendar_ALL.csv", parse_dates=["date"])
    d = fi.merge(cal, on="date", how="left")
    d = d[d["gap_days"] <= 5]
    d["norm"] = d["intensity"] / d.groupby("ticker")["intensity"].transform("mean")
    w = d[d["bd_me"].between(-10, 10)]
    prof = w.pivot_table(index="bd_me", columns="ticker", values="norm", aggfunc="mean")
    # The day-of-week control EXCLUDES the month-end day itself. Roughly a fifth of
    # month ends fall on a Friday, so leaving them in would leak the very spike this
    # panel exists to be a control for -- a null contaminated by the effect is not a null.
    dprof = (d[d["bd_me"] != 0]
             .pivot_table(index="dow", columns="ticker", values="norm", aggfunc="mean"))
    fl = J["flow"]

    fig, (ax, bx) = FS.panels(1, 2, w=6.6, h=4.3)
    top = prof.mean(axis=1)
    for c in prof.columns:
        if c == "TLT":
            continue
        ax.plot(prof.index, prof[c], color=FS.ROLE["verified"], lw=1.0, alpha=0.28)
    ax.plot(prof.index, top, color=FS.ROLE["verified"], lw=2.8, marker="o", ms=4,
            label="mean of all 12 funds")
    ax.plot(prof.index, prof["TLT"], color=FS.ROLE["verified"], lw=2.2, ls="--",
            marker="s", ms=3.5, label="TLT, the fund this study trades against")
    ax.axhline(1.0, color=FS.INK["muted"], ls=":", lw=1.4,
               label="a flat calendar (every day equal)")
    ax.set_yscale("log")
    ax.set_ylim(0.22, 9.5)
    ax.set_yticks([0.25, 0.5, 1, 2, 4, 8])
    ax.set_yticklabels(["0.25x", "0.5x", "1x", "2x", "4x", "8x"])
    ax.set_xticks(range(-10, 11, 2))
    ax.set_title("The reconstitution IS there, in the funds' own filings")
    ax.set_xlabel("business days relative to month end (0 = last trading day)")
    ax.set_ylabel(r"$|\Delta$ par per share$|$, multiple of the fund's own average day")
    ax.legend(loc="upper left", fontsize=8)
    ax.annotate(f"{top.loc[0]:.1f}x", xy=(0, top.loc[0]), xytext=(9, 4),
                textcoords="offset points", fontsize=8.5, color=FS.INK["primary"])
    ax.annotate(f"TLT only {prof.loc[0, 'TLT']:.1f}x", xy=(0, prof.loc[0, "TLT"]),
                xytext=(-66, 30), textcoords="offset points", fontsize=8.5,
                color=FS.INK["primary"],
                arrowprops=dict(arrowstyle="-", lw=0.9, color=FS.INK["muted"]))
    FS.annotate_null(
        ax,
        f"{fl['me0_share_pooled']*100:.1f}% of all measured turnover lands on ONE day,\n"
        f"against {fl['me0_share_expected_pooled']*100:.1f}% if it were spread evenly. "
        f"{fl['funds_above_expected']}/{fl['funds_total']} funds.",
        loc="lower left")

    for c in dprof.columns:
        bx.plot(range(5), dprof[c].reindex(range(5)), color=FS.ROLE["placebo"], lw=1.0,
                alpha=0.28)
    bx.plot(range(5), dprof.reindex(range(5)).mean(axis=1), color=FS.ROLE["placebo"],
            lw=2.8, marker="o", ms=4, label="mean of all 12 funds")
    bx.axhline(1.0, color=FS.INK["muted"], ls=":", lw=1.4,
               label="a flat calendar (every day equal)")
    bx.set_yscale("log")
    bx.set_ylim(0.22, 9.5)
    bx.set_yticks([0.25, 0.5, 1, 2, 4, 8])
    bx.set_yticklabels(["0.25x", "0.5x", "1x", "2x", "4x", "8x"])
    bx.set_xticks(range(5))
    bx.set_xticklabels(DOW)
    bx.set_title("A calendar cut with no reconstitution in it is flat")
    bx.set_xlabel("day of week")
    bx.set_ylabel(r"$|\Delta$ par per share$|$, multiple of the fund's own average day")
    bx.legend(loc="upper left", fontsize=8)
    dm = dprof.reindex(range(5)).mean(axis=1)
    FS.annotate_null(bx, f"weekdays run {dm.min():.2f}x to {dm.max():.2f}x the average day,\n"
                         f"against {top.loc[0]:.1f}x on the single month-end day\n"
                         "(month-end days excluded from this panel)",
                     loc="lower left")

    shares = fl["me0_share_of_turnover"]
    mult = {k: shares[k] / fl["me0_share_expected"][k] for k in shares}
    cap = (
        f"Every scraped iShares fund, {fl['n_fund_days']:,} daily documents over 2016-2026, "
        f"{fl['n_funds']} funds. Daily turnover is the sum over CUSIPs of |change in par per ETF "
        "share|, computed on a DENSE bond x date frame: a diff taken over rows present in both "
        "files cannot see a bond entering or leaving the book, and a reconstitution is precisely "
        "entries and exits. Days following a file gap of more than five calendar days are dropped, "
        "because they attribute several days' trading to one bar. Par per share rather than par so "
        "a creation is not counted as a rebalance.\n"
        f"MEASURED, not inferred: the average fund trades {top.loc[0]:.1f}x its own average day on the last "
        f"trading day of the month. {fl['me0_share_pooled']*100:.1f}% of all turnover in the whole dataset "
        f"lands on that single day against {fl['me0_share_expected_pooled']*100:.1f}% under a flat calendar -- "
        f"{fl['me0_share_pooled']/fl['me0_share_expected_pooled']:.1f}x -- and every one of the "
        f"{fl['funds_total']} funds is above its own flat-calendar share, from TLT at "
        f"{shares['TLT']*100:.1f}% ({mult['TLT']:.1f}x) to SHY at {shares['SHY']*100:.1f}% "
        f"({mult['SHY']:.1f}x).\n"
        "The dashed line is the caveat that matters to this study. TLT -- the only fund whose band this "
        f"pack trades -- has the WEAKEST month-end concentration of the twelve, {mult['TLT']:.1f}x against a "
        f"cross-fund {fl['me0_share_pooled']/fl['me0_share_expected_pooled']:.1f}x. A 20+ year sampling fund "
        "spreads its reconstitution because the bonds it drops are the ones it can sell over weeks, which "
        "is exactly what the deletion study found directly: TLT sheds 85-90% of a deleted position by day "
        "+120, in two tranches rather than one month-end cliff. The day-0 spike here is real and it is not "
        "the whole trade.\n"
        "The null is beside it: the identical measure cut by day of week, with the month-end days themselves "
        f"removed so the null cannot leak the effect, runs {dm.min():.2f}x to {dm.max():.2f}x -- against "
        f"{top.loc[0]:.1f}x on the reconstitution day. So the spike is the reconstitution and not an artifact "
        "of how the intensity is built.\n"
        "This is the honest half of the pack. The funds' behaviour is emphatically seasonal and it is "
        "verified in the holdings themselves. Figures 1, 2 and 5 are what happens when the same calendar is "
        "looked for in the PRICE: nothing a maturity-matched placebo does not also produce. A holder of a "
        "median 1.7% of a bond's public float (TLT; p90 5.3%) concentrating its trading into one day does "
        f"not move a US Treasury enough to pay a {COST_TLT:.2f}bp butterfly -- and figure 4 shows the bonds "
        "are no more dispersed against each other on that day than on any other.")
    return FS.finish(fig, FIG / "seas_03_reconstitution_intensity.png", caption=cap)


# ===================================================================== figure 4

def fig4() -> str:
    """Is the OPPORTUNITY seasonal? The dispersion is the strategy's ceiling."""
    fig, (ax, bx) = FS.panels(1, 2, w=6.6, h=4.3)
    style = {"TLT": dict(ls="-", marker="o"), "TLH": dict(ls="--", marker="s")}
    costs = {"TLT": COST_TLT, "TLH": COST_TLH}

    for key, axx, xt, lab in (("bd_me", ax, range(-10, 11, 2),
                               "business days relative to month end (0 = last trading day)"),
                              ("moy", bx, None, "month of year")):
        for fund in ("TLT", "TLH"):
            d = pd.read_csv(DATA / f"seas_disp_{fund}_{key}.csv")
            if key == "bd_me":
                d = d[d[key].between(-10, 10)]
            d = d.sort_values(key)
            x = d[key].to_numpy() if key == "bd_me" else np.arange(len(d))
            axx.plot(x, d["median"], color=FS.ROLE["control"], lw=2.0, ms=4,
                     label=f"{fund} cross-sectional richness dispersion", **style[fund])
        for fund in ("TLT", "TLH"):
            axx.axhline(costs[fund], color=FS.ROLE["cost"], ls=style[fund]["ls"], lw=1.6,
                        label=f"{fund} measured butterfly round trip ({costs[fund]:.2f}bp)")
        axx.set_ylim(0, 1.28)
        axx.set_xlabel(lab)
        axx.set_ylabel("median cross-sectional sd of the richness residual, bp")
        if xt is not None:
            axx.set_xticks(list(xt))
        else:
            axx.set_xticks(range(12))
            axx.set_xticklabels(MON, rotation=60)

    ax.axvline(0, color=FS.INK["grid"], lw=6, zorder=0,
               label="the month-end reconstitution")
    dtl = pd.read_csv(DATA / "seas_disp_TLH_moy.csv")
    tlh_over = int((dtl["median"] > COST_TLH).sum())
    ax.set_title("The opportunity does NOT swell at the reconstitution")
    bx.set_title("It varies by month, and TLT's best month is still under cost")
    ax.legend(loc="lower left", fontsize=7.5)
    FS.annotate_null(
        ax,
        f"TLT range across the 21 cells: {J['TLT']['disp_bd_me']['range_pct_of_median']:.0f}%\n"
        f"TLH: {J['TLH']['disp_bd_me']['range_pct_of_median']:.0f}%.  Both flat, no step at day 0.",
        loc="upper left")
    FS.annotate_null(
        bx,
        f"TLT: 0 of 12 months clear its own round trip; best is "
        f"{MON[int(J['TLT']['disp_moy']['median_hi_cell'])-1]} at "
        f"{J['TLT']['disp_moy']['median_hi']/COST_TLT:.2f}x\n"
        f"TLH: {tlh_over} of 12 clear its own, by at most "
        f"{dtl['median'].max()/COST_TLH:.2f}x. The two funds' profiles\n"
        f"correlate {J['cross_fund']['moy_dispersion_corr']:+.2f} -- they do not agree which month.",
        loc="upper left")

    cap = (
        "The strategy's CEILING, independent of whether any signal works. The cross-sectional standard "
        "deviation of a bond's richness against its local fitted curve is the entire dispersion a "
        "butterfly among near-identical maturities can capture; the dashed lines are each fund's own "
        "measured round trip on FedInvest's published bid and offer. Medians, not means, because the "
        "pack's 0.81x headline is a median and the mean is pulled up by a handful of dislocated days.\n"
        f"LEFT: the dispersion is FLAT around the reconstitution -- {J['TLT']['disp_bd_me']['range_pct_of_median']:.0f}% "
        f"from the narrowest cell to the widest in TLT and {J['TLH']['disp_bd_me']['range_pct_of_median']:.0f}% in TLH, "
        "with no step at day 0. The day on which the twelve funds do 17% of their measured trading, and TLT "
        "7% of its own (figure 3), is not a day on which the bonds they trade are dislocated relative to "
        "each other. That is the "
        "single most useful negative in this pack: it says the reconstitution is absorbed, and it says "
        "so without reference to any signal.\n"
        f"RIGHT: there IS monthly variation -- {J['TLT']['disp_moy']['range_pct_of_median']:.0f}% peak-to-trough in TLT, "
        f"{J['TLH']['disp_moy']['range_pct_of_median']:.0f}% in TLH -- so the ceiling is genuinely seasonal. It does not "
        f"help. TLT's widest month, {MON[int(J['TLT']['disp_moy']['median_hi_cell'])-1]}, reaches "
        f"{J['TLT']['disp_moy']['median_hi']:.3f}bp, which is {J['TLT']['disp_moy']['median_hi']/COST_TLT:.2f}x of one "
        f"round trip against {0.434/COST_TLT:.2f}x pooled: 0 of 12 months put a full round trip of dispersion on the "
        "table, and a signal would have to explain more than all of it. TLH is the one place the lines cross -- its "
        f"dispersion clears its own {COST_TLH:.2f}bp round trip in {tlh_over} months, by at most "
        f"{dtl['median'].max()/COST_TLH:.2f}x. A 6% margin over gross cost, before any signal is asked to explain "
        "any of it, is not an opening; it is stated because the panel shows the crossing and a caption that "
        "did not mention it would be reading the figure for the reader.\n"
        f"The two funds also disagree about WHICH month (profile correlation "
        f"{J['cross_fund']['moy_dispersion_corr']:+.2f}, peaks in "
        f"{MON[int(J['TLT']['disp_moy']['median_hi_cell'])-1]} and "
        f"{MON[int(J['TLH']['disp_moy']['median_hi_cell'])-1]}), so even the ceiling's seasonality is not "
        "something to schedule around. No Newey-West verdict is quoted here because a dispersion level "
        "is not a return; the claim is a comparison of two measured levels, and both are below the line.")
    return FS.finish(fig, FIG / "seas_04_opportunity_dispersion.png", caption=cap)


# ===================================================================== figure 5

def fig5() -> str:
    """Year by year in the single strongest seasonal cell, and the price of finding it."""
    bc = J["TLT"]["best_cell"]
    ex = J["TLT"]["best_cell_ex_year"]
    fam = J["TLT"]["family"]
    unc = J["TLT"]["uncond_bp"]
    yb = pd.read_csv(DATA / "seas_yearly_best_TLT.csv").sort_values("year")

    fig, (ax, bx) = FS.panels(1, 2, w=6.6, h=4.3)
    x = np.arange(len(yb))
    ax.bar(x - 0.2, yb["mean_bp"], width=0.38, color=FS.ROLE["thesis"],
           label="TLT holdings spread, August")
    ax.bar(x + 0.2, yb["plc_mean_bp"], width=0.38, color=FS.ROLE["placebo"],
           label="maturity-matched placebo, August")
    ax.vlines(x - 0.2, yb["mean_bp"] - yb["se_bp"], yb["mean_bp"] + yb["se_bp"],
              color=FS.INK["secondary"], lw=1.0)
    FS.zero_line(ax)
    ax.axhline(bc["mean_bp"], color=FS.ROLE["thesis"], ls="--", lw=1.3,
               label=f"pooled {bc['mean_bp']:+.3f}bp")
    ax.axhline(unc, color=FS.INK["muted"], ls=":", lw=1.4,
               label=f"series mean {unc:+.3f}bp")
    # The observation count goes IN the tick label. A separate row of "n=" text under the
    # bars lands on whichever bar happens to be the longest -- here 2016, the one year the
    # whole cell turns on -- and the count is the point of the panel.
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(r.year)}\nn={int(r.n)}" for _, r in yb.iterrows()],
                       rotation=0, fontsize=7.5)
    lo0 = min(yb["mean_bp"].min(), yb["plc_mean_bp"].min()) - 0.06
    ax.set_ylim(lo0, max(yb["mean_bp"].max(), yb["plc_mean_bp"].max()) + 0.20)
    ax.set_title("One year carries the strongest seasonal cell in the study")
    ax.set_xlabel("year")
    ax.set_ylabel("mean 10-day forward richening, bp")
    ax.legend(loc="upper left", fontsize=7.5)
    FS.annotate_null(
        ax,
        f"{ex['years_same_sign']} of {ex['years_total']} years share the pooled sign.\n"
        f"Drop {ex['dropped_year']} ({ex['dropped_mean_bp']:+.2f}bp) and the cell falls to "
        f"{ex['mean_bp']:+.3f}bp,\nHAC t against the series mean {ex['t_vs_level_hac']:+.2f}.",
        loc="upper right")

    nl = pd.read_csv(DATA / "seas_placebo_null_TLT.csv")
    famv = nl.groupby("draw")["max_abs_t"].max().to_numpy()
    bx.hist(famv, bins=18, color=FS.ROLE["placebo"], alpha=0.75,
            label=f"100 maturity-matched placebos, best of {fam['n_cells_searched']} cells each")
    # The markers stop just above the tallest bar. A full-height rule is guaranteed to
    # run through whichever corner the legend and the verdict need, and there is nothing
    # to read in the top half of a histogram.
    bx.axvline(fam["best_t"], color=FS.ROLE["thesis"], lw=2.4, ymax=0.52,
               label=f"the real best cell, |HAC t| {fam['best_t']:.2f}")
    bx.axvline(abs(bc["t_vs_level_hac"]), color=FS.ROLE["thesis"], lw=2.0, ls="--",
               ymax=0.52,
               label=f"same cell vs the series mean, {abs(bc['t_vs_level_hac']):.2f}")
    bx.set_title("A holdings-free search beats it one time in five")
    bx.set_xlabel(f"largest |Newey-West t| found across the {fam['n_cells_searched']} calendar cells")
    bx.set_ylabel("placebo draws")
    bx.set_ylim(0, max(np.histogram(famv, bins=18)[0]) * 2.1)
    bx.legend(loc="upper left", fontsize=7.5)
    bx.text(
        0.97, 0.63,
        f"placebo median {fam['plc_med']:.2f}, p90 {fam['plc_p90']:.2f}, "
        f"max {fam['plc_max']:.2f}\n"
        f"family-wise p = {fam['p_familywise']:.2f}   NOT significant",
        transform=bx.transAxes, ha="right", va="top", fontsize=8,
        color=FS.INK["muted"])

    cap = (
        f"The strongest seasonal cell anywhere in this study is TLT's August at "
        f"{bc['mean_bp']:+.3f}bp, HAC t {bc['t_vs_zero_hac']:.2f} against zero over {bc['n']} observations. "
        "This figure is the two tests that decide whether it is a season.\n"
        f"LEFT, is it carried by one year? {ex['years_same_sign']} of {ex['years_total']} Augusts share the "
        f"pooled sign, but {ex['dropped_year']} alone prints {ex['dropped_mean_bp']:+.2f}bp -- more than three "
        f"times the pooled value -- and 2026 contributes only {int(yb.loc[yb.year==2026,'n'].iloc[0]) if (yb.year==2026).any() else 0} "
        f"days. Dropping {ex['dropped_year']} takes the cell to {ex['mean_bp']:+.3f}bp and its HAC t against "
        f"the series' own unconditional mean from {bc['t_vs_level_hac']:.2f} to {ex['t_vs_level_hac']:.2f}. The "
        "placebo bars beside each year are the same August, same maturity strata, holdings permuted "
        "away, and they are the same size as most of the real ones.\n"
        f"RIGHT, what did finding it cost? The cell was selected as the largest |HAC t| over "
        f"{fam['n_cells_searched']} calendar cells across four keys. Running the identical search over 100 "
        f"maturity-matched placebo series gives a null for that maximum: median {fam['plc_med']:.2f}, p90 "
        f"{fam['plc_p90']:.2f}, largest {fam['plc_max']:.2f}. The real {fam['best_t']:.2f} sits at family-wise "
        f"p = {fam['p_familywise']:.2f}. It does NOT survive Newey-West once the search is charged, and the "
        f"dashed line shows it falls further ({abs(bc['t_vs_level_hac']):.2f}) once it is measured against the "
        "series' own backwards level rather than against zero.\n"
        "This is RESULTS.md 3.5 happening a second time on a different search: there, a placebo boundary "
        "at 28 years beat the real 20-year deletion boundary (2.74 against 2.40); here, a fifth of "
        "holdings-free draws beat the best seasonal cell in the study. And the magnitude settles it "
        f"regardless -- {abs(bc['dev_bp']):.3f}bp of seasonal deviation against a {COST_TLT:.2f}bp round trip is "
        f"{COST_TLT/abs(bc['dev_bp']):.0f}x too small to trade even if every statistic above had held.")
    return FS.finish(fig, FIG / "seas_05_yearly_stability_search_cost.png", caption=cap)


if __name__ == "__main__":
    for fn in (fig1, fig2, fig3, fig4, fig5):
        print(fn())
