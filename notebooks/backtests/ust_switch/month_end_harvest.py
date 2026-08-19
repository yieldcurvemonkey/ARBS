"""The Month-End Switch Harvest -- the catalyst the loop found, packaged honestly.

Signal
------
Hold LONG old / SHORT current (CTvO, DV01-matched, $1/bp per tenor) over the LAST THREE
BUSINESS DAYS of every month, flat otherwise. That is the entire rule. No parameters were
fit: the window is where the calendar diagnostic located the effect (month-end day
t=3.96 pooled, the day before t=2.12, everything else flat), and the diagnostic was run
BEFORE the strategy existed, on the QDB marks of trades built for other purposes.

Mechanism
---------
Month-end is the index duration-extension / rebalancing day and, at the front end, the
settlement day of the month's new issues. The current (benchmark) issue is the vehicle
for that flow -- it cheapens relative to its predecessor into the close; the old, which
no index tracks and no flow needs, richens relatively. The effect is positive in 16 of
17 years, in both halves of the sample, at 6 of 7 tenors, and does NOT fully reverse in
the first days of the next month (reversal ~-0.10bp day-0 vs +0.32bp gained, t=-1.6) --
so it is repricing around real flow, not a month-end mark artifact.

The cost line, stated before the equity curve
---------------------------------------------
Gross: +14.2bp/yr on a 7-tenor $1/bp book, monthly hit 61%, event t=+5.70.
A full SR1170 round trip of the book costs 6.25bp per month-end. Break-even is
**0.19x institutional cost** pooled (best single tenor ~0.6x). This strategy is real
money for a desk that can run the switch at near-mid (internalised flow, resting orders);
it is NOT tradeable at taker costs, and no amount of parameter engineering changes that.
"""

from __future__ import annotations

import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")
import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.BasisVsVol.analytics import newey_west_tstat, sharpe  # noqa: E402
from RVUtils.USTSwitch import figures as F  # noqa: E402
from RVUtils.USTSwitch.costs import CostModel  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
SEGS = HERE / "_out" / "qdb_allpairs"
OUT = HERE / "_out" / "month_end"
FIGS = HERE / "_out" / "figs"
TENORS = (2, 3, 5, 7, 10, 20, 30)
WINDOW_BD = 2  # bd_to_me <= 2  -> last three business days


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    plt = F.style()

    parts = []
    for t in TENORS:
        s = pd.read_parquet(SEGS / f"segs_{t}_CTvO.parquet")
        s["date"] = pd.to_datetime(s["date"])
        s = s[s["pnl_bp"] != 0.0]
        s["tenor"] = t
        parts.append(s)
    d = pd.concat(parts, ignore_index=True)
    idx = pd.DatetimeIndex(sorted(d["date"].unique()))
    me = {dt: int(np.busday_count(dt.date(), (dt + pd.offsets.BMonthEnd(0)).date())) for dt in idx}
    d["bd_to_me"] = d["date"].map(me)
    w = d[d["bd_to_me"] <= WINDOW_BD]

    # per-tenor daily books and the pooled book (gross, $1/bp per tenor)
    per_tenor = w.pivot_table(index="date", columns="tenor", values="pnl_bp", aggfunc="sum")
    book = per_tenor.sum(axis=1).sort_index()
    per_tenor.to_parquet(OUT / "per_tenor_daily.parquet")
    book.to_frame("pnl_bp").to_parquet(OUT / "book_daily_gross.parquet")

    cm = CostModel()
    md = {2: 1.9, 3: 2.8, 5: 4.5, 7: 6.1, 10: 7.9, 20: 13.0, 30: 17.5}
    rt = {t: cm.round_trip_yield_bp(t, 1, 0, md[t], md[t]) for t in TENORS}

    # ---- per-tenor economics
    ev = w.groupby(["tenor", w["date"].dt.to_period("M")])["pnl_bp"].sum().reset_index()
    per = ev.groupby("tenor")["pnl_bp"].agg(["mean", "std", "count"])
    per["t"] = per["mean"] / (per["std"] / np.sqrt(per["count"]))
    per["rt_cost"] = [rt[t] for t in per.index]
    per["breakeven_x"] = per["mean"] / per["rt_cost"]
    print("=== per-tenor month-end event economics (gross bp/event) ===")
    print(per.round(3).to_string())
    per.to_csv(OUT / "per_tenor_economics.csv")

    # ---- pooled book stats at cost multipliers
    mm = book.groupby(book.index.to_period("M")).sum()
    rt_book = sum(rt.values())
    print(f"\npooled book: {len(mm)} month-ends, gross/event {mm.mean():+.3f}bp, "
          f"monthly hit {(mm > 0).mean():.3f}, event t "
          f"{mm.mean() / (mm.std() / np.sqrt(len(mm))):+.2f}")
    rows = []
    for m in (0.0, 0.1, 0.15, 0.2, 0.25, 0.5, 1.0):
        net = mm - m * rt_book
        rows.append({"cost_x": m, "net_per_event_bp": round(net.mean(), 3),
                     "monthly_hit": round(float((net > 0).mean()), 3),
                     "event_t": round(float(net.mean() / (net.std() / np.sqrt(len(net)))), 2),
                     "bp_per_yr": round(net.mean() * 12, 1),
                     "ann_sharpe_events": round(float(net.mean() / net.std() * np.sqrt(12)), 2)})
    cost_tbl = pd.DataFrame(rows)
    print(cost_tbl.to_string(index=False))
    cost_tbl.to_csv(OUT / "cost_frontier.csv", index=False)

    # ---------------- figures ----------------
    # 22: daily MTM equity, gross + cost bands
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for i, (m, lab) in enumerate([(0.0, "gross (execution at mid)"),
                                  (0.1, "0.1× SR1170"), (0.2, "0.2× SR1170 (break-even)"),
                                  (1.0, "full SR1170 taker cost")], start=1):
        costs = pd.Series(0.0, index=book.index)
        first_of_event = book.index.to_period("M")
        is_last = ~pd.Series(first_of_event, index=book.index).duplicated(keep="last")
        costs[is_last.values] = m * rt_book
        eq = (book - costs).cumsum()
        ax.plot(eq.index, eq.values, color=F.PAL[min(i, 8)], lw=1.7, label=lab)
    ax.axhline(0, color=F.MUTED, lw=0.9)
    ax.set_ylabel("cumulative P&L (bp)")
    ax.set_title("Month-End Switch Harvest — long old/short current, last 3bd of each month, "
                 "7 tenors × $1/bp (daily MTM)")
    ax.legend(fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIGS / "22_month_end_harvest_equity.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)

    # 23: yearly bars (gross)
    ann = book.groupby(book.index.year).sum()
    fig, ax = plt.subplots(figsize=(10, 3.4))
    cols = [F.ROLE["price"] if v >= 0 else F.ROLE["cost"] for v in ann.values]
    ax.bar(ann.index.astype(str), ann.values, color=cols, width=0.7)
    ax.axhline(0, color=F.INK2, lw=1.0)
    ax.set_ylabel("bp (gross)")
    ax.set_title(f"Month-end harvest by year — positive {int((ann > 0).sum())}/{len(ann)} years")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(FIGS / "23_month_end_by_year.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)

    # 24: per-tenor mean event bar + break-even multiple
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    axes[0].bar([f"{t}Y" for t in per.index], per["mean"], color=F.PAL[1], width=0.6,
                yerr=per["std"] / np.sqrt(per["count"]), capsize=3)
    axes[0].axhline(0, color=F.INK2, lw=1.0)
    axes[0].set_ylabel("gross bp per month-end")
    axes[0].set_title("Effect size by tenor")
    axes[1].bar([f"{t}Y" for t in per.index], per["breakeven_x"], color=F.PAL[3], width=0.6)
    axes[1].axhline(1.0, color=F.ROLE["cost"], lw=1.4, ls="--")
    axes[1].text(0.02, 1.0, " tradeable at full cost above this line", fontsize=8,
                 color=F.ROLE["cost"], va="bottom", transform=axes[1].get_yaxis_transform())
    axes[1].set_ylabel("break-even cost multiple")
    axes[1].set_title("Cost frontier by tenor")
    fig.tight_layout()
    fig.savefig(FIGS / "24_month_end_per_tenor.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)
    print(f"\nfigures 22-24 -> {FIGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
