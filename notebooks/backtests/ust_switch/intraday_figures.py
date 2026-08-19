"""Figures for the intraday auction-concession study."""

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

from RVUtils.USTSwitch import figures as F  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "_out" / "intraday"
FIGS = HERE / "_out" / "figs"

STAMP_ORDER = ["07:30", "09:00", "10:30", "12:00", "12:45", "13:00", "13:15", "13:30",
               "14:30", "15:00", "16:00"]


def main() -> int:
    plt = F.style()
    FIGS.mkdir(parents=True, exist_ok=True)
    g = pd.read_csv(OUT / "auction_intraday_path.csv")

    tenors = sorted(g["tenor"].unique())
    fig, axes = plt.subplots(len(tenors), 1, figsize=(12.5, 3.1 * len(tenors)), sharex=True)
    if len(tenors) == 1:
        axes = [axes]
    for ax, t in zip(axes, tenors):
        d = g[g["tenor"] == t].copy()
        # 0-based day offset so the day-boundary guides and the 13:00 marker land on
        # the data (rel_day runs -2..+2; the guides assume x starts at 0).
        d["x"] = (d["rel_day"] + 2) * len(STAMP_ORDER) + d["stamp"].map(
            {s: i for i, s in enumerate(STAMP_ORDER)})
        d = d.sort_values("x")
        ax.plot(d["x"], d["mean"], color=F.PAL[1], lw=1.8, marker="o", ms=3)
        ax.fill_between(d["x"], d["mean"] - d["se"], d["mean"] + d["se"],
                        color=F.PAL[1], alpha=0.18, linewidth=0)
        # day boundaries and the 13:00 auction stamp on day 0
        for k in range(1, 5):
            ax.axvline(k * len(STAMP_ORDER) - 0.5, color=F.GRID, lw=0.8)
        x13 = 2 * len(STAMP_ORDER) + STAMP_ORDER.index("13:00")
        ax.axvline(x13, color=F.ROLE["cost"], lw=1.4, ls="--")
        ax.text(x13, ax.get_ylim()[1], " 13:00 auction ", va="top", fontsize=8,
                color=F.ROLE["cost"])
        ax.axhline(0, color=F.MUTED, lw=0.8)
        n_ev = int(d["count"].max())
        ax.set_ylabel("bp vs D-1 15:00")
        ax.set_title(f"{t}Y — mean matched-maturity SOFR par rate around auctions "
                     f"({n_ev} events, +=cheaper)", fontsize=10)
    ticks, labels = [], []
    for k, day in enumerate(("D-2", "D-1", "D (auction)", "D+1", "D+2")):
        for i, s in enumerate(STAMP_ORDER):
            if s in ("09:00", "13:00", "15:00"):
                ticks.append(k * len(STAMP_ORDER) + i)
                labels.append(f"{day}\n{s}" if s == "13:00" else s)
    axes[-1].set_xticks(ticks, labels, fontsize=7)
    fig.suptitle("Auction concession, intraday (Citi minute SOFR curve, backward-only "
                 "snapshots): rates cheapen into the 13:00 result and richen after",
                 fontsize=12, y=0.995)
    fig.tight_layout()
    fig.savefig(FIGS / "20_intraday_auction_concession.png", dpi=130,
                bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)
    print("saved 20_intraday_auction_concession.png")

    jr_path = OUT / "auction_result_jump.csv"
    if jr_path.exists():
        jr = pd.read_csv(jr_path)
        fig, ax = plt.subplots(figsize=(7, 3.2))
        cols = [F.ROLE["price"] if v < 0 else F.ROLE["cost"] for v in jr["mean"]]
        ax.bar(range(len(jr)), jr["mean"], yerr=jr["std"] / np.sqrt(jr["count"]),
               color=cols, width=0.6, capsize=3)
        ax.set_xticks(range(len(jr)), [f"{int(t)}Y" for t in jr["tenor"]])
        ax.axhline(0, color=F.INK2, lw=1.0)
        ax.set_ylabel("bp, 13:00 → 13:30")
        ax.set_title("Auction-result window: mean rate move (negative = post-result richening)")
        for i, r in jr.iterrows():
            ax.text(i, r["mean"], f" t={r['t']:.1f}", fontsize=8, ha="left",
                    va="bottom" if r["mean"] >= 0 else "top", color=F.INK2)
        fig.tight_layout()
        fig.savefig(FIGS / "21_intraday_result_jump.png", dpi=130,
                    bbox_inches="tight", facecolor=F.SURFACE)
        plt.close(fig)
        print("saved 21_intraday_result_jump.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
