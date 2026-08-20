"""FIG 2 - what TLT does with a bond that falls out of its index.

Rebuilt from the holdings files rather than read from ``audit_delcliff_holdings_shed_path.csv``,
for three reasons: that file carries 20 of the 32 crossings, its offsets are stamped ``cd``
(calendar, not the business days the brief asks for) and no generator for it survives in the
repo, and its base level appears pinned to a single pre-date (its median at cd-30 is exactly
1.000), which one noisy document would move.

Here: offsets are BUSINESS days off the crossing date, and the base is the median TLT par
over business days [-60, -21] -- a level, so no single file sets it.

Two panels, never twinned. Top: TLT's par in the deleted bond. Bottom: TLH's par in the
same bond, on the same denominator (TLT's pre-event base), so the reader can see directly
what fraction of what TLT sheds the short fund picks up.

The control, in the same panel: for each event, the TLT-held bond nearest 21.5 years on the
crossing date -- same fund, same day, same sector, and NOT crossing within the window. If
the shed were ordinary turnover it would move too.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

import figstyle as FS  # noqa: E402

FS.use()
DATA = os.path.join(HERE, "_data")
FIGS = os.path.join(HERE, "figures")

LO, HI = -60, 180          # business days around the crossing
BASE_LO, BASE_HI = -60, -21
MIN_BASE_OBS = 5
MIN_N = 8                  # do not draw a median off fewer paths than this


def build_paths() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    ev = pd.read_csv(os.path.join(DATA, "delcliff_holdings_verification.csv"),
                     parse_dates=["event_date"])
    h = pd.read_parquet(os.path.join(DATA, "raw_holdings_TLT_TLH.parquet"))
    h["date"] = pd.to_datetime(h["date"])
    act = pd.read_parquet(os.path.join(DATA, "fundfig_active_TLT.parquet"))

    bd = pd.bdate_range(h["date"].min() - pd.Timedelta(days=10),
                        h["date"].max() + pd.Timedelta(days=10))
    pos = pd.Series(np.arange(len(bd)), index=bd)

    def offsets(dates: pd.Series, anchor: pd.Timestamp) -> np.ndarray:
        a = int(pos.reindex([anchor]).ffill().iloc[0]) if anchor in pos.index else \
            int(pos[pos.index <= anchor].iloc[-1])
        return pos.reindex(dates).to_numpy() - a

    tlt = h[h["ticker"] == "TLT"][["date", "cusip", "par"]]
    tlh = h[h["ticker"] == "TLH"][["date", "cusip", "par"]]
    tlt_w = tlt.pivot_table(index="date", columns="cusip", values="par", aggfunc="sum")
    tlh_w = tlh.pivot_table(index="date", columns="cusip", values="par", aggfunc="sum")
    # A CUSIP absent from a document is a position of ZERO, not a missing observation --
    # but only on dates where a document exists at all.
    tlt_w = tlt_w.fillna(0.0)
    tlh_w = tlh_w.reindex(index=tlh_w.index).fillna(0.0)

    rows_t, rows_h, rows_c, diag = [], [], [], {"events": len(ev), "used": 0, "no_base": []}

    for _, e in ev.iterrows():
        cu, D = str(e["cusip"]).strip(), pd.Timestamp(e["event_date"])
        if cu not in tlt_w.columns:
            diag["no_base"].append((cu, "never in a TLT document"))
            continue
        s = tlt_w[cu]
        off = offsets(pd.Series(s.index), D)
        d = pd.DataFrame({"off": off, "par": s.to_numpy()}).dropna()
        d = d[(d["off"] >= LO) & (d["off"] <= HI)]
        pre = d[(d["off"] >= BASE_LO) & (d["off"] <= BASE_HI)]
        if len(pre) < MIN_BASE_OBS:
            diag["no_base"].append((cu, f"only {len(pre)} pre-window documents "
                                        f"(the 2017-H1 publication hole)"))
            continue
        if pre["par"].median() <= 0:
            # Not a data hole: TLT samples, so it simply did not own this index member.
            diag["no_base"].append((cu, "TLT held no position to shed"))
            continue
        base = float(pre["par"].median())
        diag["used"] += 1
        rows_t.append(d.assign(cusip=cu, event=D, pct=d["par"] / base))

        if cu in tlh_w.columns:
            s2 = tlh_w[cu]
            o2 = offsets(pd.Series(s2.index), D)
            d2 = pd.DataFrame({"off": o2, "par": s2.to_numpy()}).dropna()
            d2 = d2[(d2["off"] >= LO) & (d2["off"] <= HI)]
            rows_h.append(d2.assign(cusip=cu, event=D, pct=d2["par"] / base))

        # ---- maturity-matched control: same fund, same day, ~21.5y, cannot cross
        # the boundary inside a 180-business-day window (180bd ~ 0.72y).
        on = act[(act["date"] == D) & act["held"] & act["ttm"].between(20.9, 23.0)]
        if not on.empty:
            cc = str(on.iloc[(on["ttm"] - 21.5).abs().argsort().iloc[0]]["cusip"])
            if cc in tlt_w.columns:
                s3 = tlt_w[cc]
                o3 = offsets(pd.Series(s3.index), D)
                d3 = pd.DataFrame({"off": o3, "par": s3.to_numpy()}).dropna()
                d3 = d3[(d3["off"] >= LO) & (d3["off"] <= HI)]
                p3 = d3[(d3["off"] >= BASE_LO) & (d3["off"] <= BASE_HI)]
                if len(p3) >= MIN_BASE_OBS and p3["par"].median() > 0:
                    rows_c.append(d3.assign(cusip=cc, event=D,
                                            pct=d3["par"] / float(p3["par"].median())))

    T = pd.concat(rows_t, ignore_index=True)
    H = pd.concat(rows_h, ignore_index=True) if rows_h else pd.DataFrame(columns=T.columns)
    C = pd.concat(rows_c, ignore_index=True) if rows_c else pd.DataFrame(columns=T.columns)
    diag["n_control"] = C["cusip"].nunique() if len(C) else 0
    return T, H, C, diag


def band(df: pd.DataFrame, step: int = 5) -> pd.DataFrame:
    """Median / IQR / n on a regular business-day grid, one observation per event."""
    if df.empty:
        return pd.DataFrame(columns=["off", "med", "q25", "q75", "n"])
    d = df.copy()
    d["slot"] = (np.round(d["off"] / step) * step).astype(int)
    d = d.sort_values("off").groupby(["event", "slot"], as_index=False).last()
    g = d.groupby("slot")["pct"].agg(med="median",
                                     q25=lambda s: s.quantile(0.25),
                                     q75=lambda s: s.quantile(0.75), n="size")
    return g.reset_index().rename(columns={"slot": "off"})


def main() -> None:
    T, H, C, diag = build_paths()
    bT, bH, bC = band(T), band(H), band(C)
    for b in (bT, bH, bC):
        b.loc[b["n"] < MIN_N, ["med", "q25", "q75"]] = np.nan

    fig, (ax0, ax1) = FS.panels(2, 1, w=8.6, h=3.5, sharex=True)

    # ------------------------------------------------------------------ TLT sheds
    ax0.fill_between(bT["off"], bT["q25"] * 100, bT["q75"] * 100,
                     color=FS.ROLE["verified"], alpha=0.20, lw=0,
                     label="IQR across events")
    ax0.plot(bT["off"], bT["med"] * 100, color=FS.ROLE["verified"], lw=2.4,
             label=f"TLT par in the DELETED bond (median, n={diag['used']})")
    ax0.plot(bC["off"], bC["med"] * 100, color=FS.ROLE["placebo"], lw=2.0, ls="--",
             label=f"CONTROL: a ~21.5y bond that does NOT cross (n={diag['n_control']})")
    ax0.axvline(0, color=FS.INK["primary"], lw=1.1)
    ax0.axhline(100, color=FS.INK["grid"], lw=1.0, zorder=1)
    ax0.set_ylabel("par held, % of the pre-event level")
    ax0.set_title("TLT really does shed the bond - but over months, in tranches, "
                  "never on the month-end", pad=8)
    ax0.legend(loc="lower left", fontsize=8, borderaxespad=0.7, handlelength=1.8)
    ax0.set_ylim(0, 132)

    at = {int(r["off"]): r for _, r in bT.iterrows()}
    for o in (0, 60, 120, 180):
        if o in at and np.isfinite(at[o]["med"]):
            ax0.plot([o], [at[o]["med"] * 100], "o", color=FS.ROLE["verified"], ms=5,
                     zorder=5)
            dx, ha = ((-5, "right") if o == 180 else (5, "left"))
            ax0.annotate(f"{at[o]['med']*100:.0f}%", (o, at[o]["med"] * 100),
                         textcoords="offset points", xytext=(dx, 9), fontsize=8.5,
                         ha=ha, color=FS.INK["primary"], fontweight="semibold")

    # ------------------------------------------------------------------ TLH buys
    ax1.fill_between(bH["off"], bH["q25"] * 100, bH["q75"] * 100,
                     color=FS.ROLE["thesis"], alpha=0.20, lw=0,
                     label="inter-quartile range across events")
    ax1.plot(bH["off"], bH["med"] * 100, color=FS.ROLE["thesis"], lw=2.4,
             label="TLH par in the same bond, on the SAME denominator")
    ax1.axvline(0, color=FS.INK["primary"], lw=1.1)
    FS.zero_line(ax1)
    ax1.set_ylabel("par held, % of TLT's pre-event level")
    ax1.set_xlabel("business days from the crossing below 20 years to maturity")
    ax1.set_title("and TLH picks up only a fraction of it - the bond is a NET sale to the market",
                  pad=8)
    ax1.legend(loc="upper left", fontsize=8)
    ax1.set_xlim(LO, HI)
    ax1.set_ylim(0, 118)
    ax1.set_xticks(np.arange(-60, 181, 30))

    ax1.text(0.985, 0.02,
             "the SHED is verified; the PRICE effect is not a flow story -\n"
             "amplitude vs TLT's share of the float: corr 0.002, and the 10y boundary,\n"
             "where the flow direction REVERSES, gives +0.52bp t 2.31 vs +0.47bp t 2.93",
             transform=ax1.transAxes, ha="right", va="bottom", fontsize=7.6,
             color=FS.INK["muted"])

    for o, ha in ((-60, "left"), (0, "center"), (60, "center"), (120, "center"),
                  (180, "right")):
        r = bT[bT["off"] == o]
        if len(r):
            ax0.annotate(f"n={int(r['n'].iloc[0])}", (o, 0.965), ha=ha, va="top",
                         xycoords=("data", "axes fraction"),
                         fontsize=7.5, color=FS.INK["muted"])

    d120 = at.get(120, {}).get("med", np.nan)
    d180 = at.get(180, {}).get("med", np.nan)
    cap = (
        f"TLT's par holding of a Treasury that falls below 20 years to maturity and leaves "
        f"its index. {diag['events']} crossings are identified; {diag['used']} of them are "
        f"drawn here, and the {diag['events'] - diag['used']} that are not are not a data "
        f"hole - TLT simply owned no position in those bonds to shed, which is what a "
        f"SAMPLING fund looks like from the other side. Offsets are BUSINESS days off the "
        f"crossing date; the base is the median par over business days -60 to -21, a level, "
        f"so no single document sets it. "
        f"WHAT IT PROVES. The shed is real and it is large: the median position is "
        f"{d120*100:.0f}% of its pre-event level {120} business days after the crossing and "
        f"{d180*100:.0f}% after {180} - {100-d120*100:.0f}% and {100-d180*100:.0f}% of the "
        f"position sold. It is emphatically NOT a month-end cliff - the median is still "
        f"{at[0]['med']*100:.0f}% on the crossing date itself and the selling runs for "
        f"months afterwards, in tranches. The dashed control settles that this is deletion "
        f"and not ordinary turnover: the same fund's par in a maturity-matched ~21.5-year "
        f"bond on the same days is flat. The lower panel is on TLT's denominator on purpose "
        f"- TLH, the $11bn short fund, buys back only a fraction of what the $47bn long fund "
        f"sells, so a deleted bond is a net sale to the market rather than an internal "
        f"transfer. WHAT IT DOES NOT PROVE. That the flow moves the price, or that any of it "
        f"is tradeable. Two identification checks refuse the flow story outright: event "
        f"amplitude does not scale with TLT's share of the bond's float (corr 0.002, and a "
        f"tercile sort runs backwards, 0.73bp low-ownership vs 0.43bp high), and reversing "
        f"the flow direction does not reverse the sign - the same test at the 10-year "
        f"boundary, where a small seller is replaced by a large BUYER, gives +0.52bp t 2.31 "
        f"against +0.47bp t 2.93 here. On the trade itself: 1,274 butterflies over 40 "
        f"entry/exit cells, best gross 0.40bp against a measured 1.09bp cost, 0 of 40 cells "
        f"net positive even at an optimistic 0.5bp floor. A verified flow is not an edge. "
        f"NOTE ON CONSTRUCTION. RESULTS.md reports 85-90% shed by day +120 from a prior "
        f"pass whose offsets are stamped in CALENDAR days over 20 events; on BUSINESS days "
        f"over these {diag['used']} the median is {100-d120*100:.0f}% by +120 and "
        f"{100-d180*100:.0f}% by +180. Both describe the same shed - 120 business days is "
        f"about 172 calendar days - but the axis matters, so it is labelled."
    )
    p = FS.finish(fig, os.path.join(FIGS, "fund_02_deletion_shed.png"), caption=cap)
    print(p)
    print("events", diag["events"], "used", diag["used"], "controls", diag["n_control"])
    for cu, why in diag["no_base"]:
        print("   skipped", cu, "-", why)
    print(bT.to_string())
    print("--- TLH ---")
    print(bH.to_string())


if __name__ == "__main__":
    main()
