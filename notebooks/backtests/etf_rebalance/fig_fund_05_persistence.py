"""FIG 5 - persistence: these gaps are not dislocations, and they do not get closed.

Left: pick the three most OVERWEIGHT and three most UNDERWEIGHT names on one date, then
watch them forward for a year. The selection is made on day 0 and never revisited, so
nothing here is chosen with hindsight.

Right: the same question asked of the whole panel, and asked of the CONTROL alongside it.
"How often is the most overweight name still the most overweight name k days later?" against
"how often is the richest bond still the richest bond k days later?". The active weight is
nearly a constant; the richness residual - the thing a trade would actually be forecasting -
decays. Two series on different clocks cannot forecast one another, and this is that fact
drawn.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

import figstyle as FS  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402

FS.use()
DATA = os.path.join(HERE, "_data")
FIGS = os.path.join(HERE, "figures")

ANCHOR = pd.Timestamp("2023-06-01")
YEAR_BD = 252
TOP_K = 3


def load():
    act = pd.read_parquet(os.path.join(DATA, "fundfig_active_TLT.parquet"))
    flow = pd.read_parquet(os.path.join(DATA, "fundfig_flow_TLT_TLH.parquet"))
    doc = set(pd.to_datetime(flow.loc[flow["ticker"] == "TLT", "date"]))
    act = act[act["date"].isin(doc) & act["ttm"].notna()].copy()
    act["aw_bp"] = act["active_w"] * 1e4
    return act


def main() -> None:
    act = load()

    # ------------------------------------------------------- the richness control panel
    p = pd.read_parquet(os.path.join(DATA, "ust_panel.parquet"))
    p["date"] = pd.to_datetime(p["date"])
    p["cusip"] = p["cusip"].astype(str)
    p = p[p["ttm"].between(20.0, 31.0) & p["ytm"].notna() &
          ~p.get("yield_gate_fail", pd.Series(False, index=p.index)).fillna(True)]
    res = CV.fit_residuals(p, deg=3, x_axis="ttm", include_coupon=True, robust=True)
    res = res[res["resid_bp"].notna()]
    print(f"residual panel {len(res):,} rows, {res['date'].nunique():,} dates")

    dates = np.sort(act["date"].unique())
    a0 = dates[np.searchsorted(dates, ANCHOR)]
    win = dates[(dates >= a0)][:YEAR_BD + 1]
    d0 = act[act["date"] == a0].dropna(subset=["aw_bp"]).sort_values("aw_bp")
    over = d0.tail(TOP_K)["cusip"].tolist()[::-1]
    under = d0.head(TOP_K)["cusip"].tolist()

    piv = (act[act["date"].isin(win)]
           .pivot_table(index="date", columns="cusip", values="aw_bp"))

    fig = plt.figure(figsize=(13.4, 4.8))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.20)
    ax = fig.add_subplot(gs[0, 0])
    axr = fig.add_subplot(gs[0, 1])

    # --------------------------------------------------------------- left: six careers
    lo = piv.quantile(0.25, axis=1)
    hi = piv.quantile(0.75, axis=1)
    ax.fill_between(piv.index, lo, hi, color=FS.INK["grid"], alpha=0.75, lw=0,
                    label="inter-quartile range of the whole board, each day")
    for i, c in enumerate(over):
        if c in piv:
            ax.plot(piv.index, piv[c], color=FS.ROLE["thesis"], lw=2.2,
                    alpha=1.0 - 0.22 * i,
                    label="the 3 most OVERWEIGHT names on day 0" if i == 0 else None)
    for i, c in enumerate(under):
        if c in piv:
            ax.plot(piv.index, piv[c], color=FS.ROLE["thesis_alt"], lw=2.2,
                    alpha=1.0 - 0.22 * i,
                    label="the 3 most UNDERWEIGHT names on day 0" if i == 0 else None)
    FS.zero_line(ax)
    ax.axvline(win[0], color=FS.INK["primary"], lw=1.1,
               label="selection date - names chosen here, never revisited")
    ax.set_ylabel("active weight (bp of fund DV01)")
    ax.set_title("Picked on one day, still there a year later", pad=8)
    ax.set_ylim(-640, 900)
    ax.legend(loc="center right", fontsize=8, ncol=1)

    n_o = int(sum(float(piv[c].iloc[-1]) > 0 for c in over if c in piv))
    n_u = int(sum(float(piv[c].iloc[-1]) < 0 for c in under if c in piv))
    # How long did the one name that DID change sign take? Measured, not asserted.
    cross_bd = []
    for c in under:
        if c in piv and float(piv[c].iloc[-1]) > 0:
            pos = np.flatnonzero((piv[c] > 0).to_numpy())
            if len(pos):
                cross_bd.append(int(pos[0]))
    tail = (f"; the one that crosses takes {min(cross_bd)} business days to do it"
            if cross_bd else "")
    ax.text(0.015, 0.03,
            f"a year on, {n_o} of {TOP_K} overweights are still overweight and "
            f"{n_u} of {TOP_K}\nunderweights are still underweight{tail}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=7.8,
            color=FS.INK["muted"])
    print(f"end-of-window signs: overweights still over {n_o}/{TOP_K}, "
          f"underweights still under {n_u}/{TOP_K}; crossings at bd {cross_bd}")

    # ---------------------------------------------- right: rank persistence vs the control
    def rank_persist(panel: pd.DataFrame, col: str, ks, *, top=True):
        pv = panel.pivot_table(index="date", columns="cusip", values=col).sort_index()
        r = pv.rank(axis=1, ascending=not top)          # rank 1 = the extreme name
        is_top1 = r.eq(1.0)
        out, base = [], []
        n = pv.notna().sum(axis=1)
        for k in ks:
            j = is_top1 & is_top1.shift(-k)
            m = is_top1.any(axis=1) & is_top1.shift(-k).any(axis=1)
            out.append(float(j.any(axis=1)[m].mean()) * 100)
            base.append(float((1.0 / n[m]).mean()) * 100)
        return np.array(out), np.array(base)

    ks = np.array([1, 2, 3, 5, 8, 13, 21, 34, 42, 63, 84, 126, 189, 252])
    aw_p, aw_base = rank_persist(act, "aw_bp", ks, top=True)
    rs_p, rs_base = rank_persist(res, "resid_bp", ks, top=False)

    axr.plot(ks, aw_p, color=FS.ROLE["thesis"], lw=2.4, marker="o", ms=4.5,
             label="the most OVERWEIGHT bond (a holdings quantity)")
    axr.plot(ks, rs_p, color=FS.ROLE["control"], lw=2.4, marker="s", ms=4.5,
             label="the RICHEST bond (the control - reads no ETF data)")
    axr.plot(ks, (aw_base + rs_base) / 2, color=FS.ROLE["placebo"], lw=1.8, ls=":",
             label="chance, if the ranking were reshuffled every day")
    axr.set_xscale("log")
    axr.set_xticks([1, 5, 21, 63, 126, 252])
    axr.set_xticklabels(["1d", "1w", "1m", "3m", "6m", "1y"])
    axr.set_ylim(0, 100)
    axr.set_xlabel("business days later")
    axr.set_ylabel("% of the time it is STILL the same bond")
    axr.set_title("The signal is a constant; its target is not", pad=8)
    axr.legend(loc="lower left", fontsize=8, bbox_to_anchor=(0.012, 0.115))
    axr.text(0.02, 0.03,
             "the richness residual's own OU half-life is 17 business days;\n"
             "a near-constant cannot forecast a series that turns over that fast",
             transform=axr.transAxes, ha="left", va="bottom", fontsize=7.8,
             color=FS.INK["muted"])

    i21 = int(np.where(ks == 21)[0][0])
    i252 = int(np.where(ks == 252)[0][0])
    cap = (
        f"Persistence of TLT's active weights. LEFT: the three most overweight and three "
        f"most underweight names in TLT's book on {pd.Timestamp(a0).date()}, followed "
        f"forward for {len(win)-1} business days. The selection rule is stated so it can be "
        f"checked - rank by active weight on the anchor date, take the top three and bottom "
        f"three, and never revisit; nothing to the right of the vertical line is used to "
        f"choose the names. The grey band is the inter-quartile range of the whole board on "
        f"each day, so the extremes can be read against the day's dispersion. RIGHT: the "
        f"same question over the whole sample, against the control. "
        f"WHAT IT PROVES. The gaps are not dislocations. A name picked as the most "
        f"overweight in the fund is still the most overweight name {aw_p[i21]:.0f}% of the "
        f"time three weeks later and {aw_p[i252]:.0f}% of the time a YEAR later, against a "
        f"reshuffling baseline of about {aw_base[i252]:.0f}%. Neighbouring bonds run "
        f"hundreds of bp of active weight in opposite directions and simply stay there. As a "
        f"description of how a sampling fund holds a curve this is real, measured, and the "
        f"most robust thing in the pack. "
        f"WHAT IT DOES NOT PROVE. Anything tradeable - and the right-hand panel is why. The "
        f"richest bond is still the richest bond only {rs_p[i21]:.0f}% of the time three "
        f"weeks out and {rs_p[i252]:.0f}% a year out; the richness residual's own OU "
        f"half-life is 17 business days. So the holdings signal is very nearly a constant "
        f"and the thing it would have to forecast turns over roughly monthly. A constant "
        f"cannot forecast that, and the measurement agrees: active weight's 63-day IC is "
        f"-0.065 (backwards) raw and +0.005bp per unit z with Newey-West t = 0.89 once "
        f"richness is controlled for, against a 0.535bp round trip. Persistence is exactly "
        f"what makes this a portrait rather than a signal - a gap that never closes is not "
        f"an opportunity, it is a policy."
    )
    p_out = FS.finish(fig, os.path.join(FIGS, "fund_05_persistence.png"), caption=cap)
    print(p_out)
    print("anchor", pd.Timestamp(a0).date(), "over", over, "under", under)
    print(pd.DataFrame({"k": ks, "active_w_top1_%": aw_p.round(1),
                        "resid_top1_%": rs_p.round(1),
                        "chance_%": ((aw_base + rs_base) / 2).round(1)}).to_string(index=False))


if __name__ == "__main__":
    main()
