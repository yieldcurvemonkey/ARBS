"""The two charts for the exclusion-skew note. PNG, light surface."""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["MPLBACKEND"] = "Agg"
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CACHE = pathlib.Path(os.environ.get("PKGSKEW_CACHE", r"D:\pkgskew_cache"))
IMG = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd\docs\dealer_direction\img")
IMG.mkdir(parents=True, exist_ok=True)

BUCKETS = ["0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y",
           "10-15Y", "15-20Y", "20-30Y", "30Y+"]

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASE = "#c3c2b7"
S_PKG4 = "#2a78d6"      # categorical slot 1, blue
S_ASWAP = "#eb6834"     # slot 2, orange
S_OTHER = "#1baf7a"     # slot 3, aqua
POS, NEG = "#2a78d6", "#e34948"   # diverging pair, blue <-> red

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": BASE, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.titlecolor": INK,
    "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
})


def load(kind):
    fs = sorted(CACHE.glob(f"{kind}_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


def main() -> int:
    legs = load("legs")
    legs["month"] = pd.to_datetime(legs["as_of_date"]).dt.to_period("M")
    CLS = ["KEPT", "PKG4", "ASSETSWAP", "OTHER_EXCL"]

    lb = legs.pivot_table(index="tenor_bucket", columns="excl_class",
                          values="dv01", aggfunc="sum", fill_value=0.0)
    lb = lb.reindex(index=BUCKETS, columns=CLS).fillna(0.0)
    lb["TOTAL"] = lb.sum(axis=1)
    rate = 100 * (lb["TOTAL"] - lb["KEPT"]) / lb["TOTAL"]
    r_p4 = 100 * lb["PKG4"] / lb["TOTAL"]
    r_as = 100 * lb["ASSETSWAP"] / lb["TOTAL"]
    r_ot = 100 * lb["OTHER_EXCL"] / lb["TOTAL"]
    tape_shr = 100 * lb["TOTAL"] / lb["TOTAL"].sum()
    kept_shr = 100 * lb["KEPT"] / lb["KEPT"].sum()
    delta = kept_shr - tape_shr

    rl = legs[(legs["excl_class"] == "PKG4") & legs["unit_any_ptp"]]
    add = rl.groupby("tenor_bucket")["dv01"].sum().reindex(BUCKETS).fillna(0.0)
    after = 100 * (lb["TOTAL"] - lb["KEPT"] - add) / lb["TOTAL"]

    grand = 100 * (lb["TOTAL"].sum() - lb["KEPT"].sum()) / lb["TOTAL"].sum()

    # ================================================== chart A
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(11.2, 8.4), height_ratios=[2.15, 1], sharex=True,
        gridspec_kw={"hspace": 0.18})
    x = np.arange(len(BUCKETS))

    b = 0.0
    for vals, col, lab in ((r_p4, S_PKG4, "PKG-4+ (no quote convention)"),
                           (r_as, S_ASWAP, "asset swap (spreadover / MM / invoice)"),
                           (r_ot, S_OTHER, "all other exclusions")):
        ax.bar(x, vals, 0.62, bottom=b, color=col, label=lab,
               edgecolor=SURFACE, linewidth=1.6, zorder=3)
        b = b + vals
    ax.hlines(after, x - 0.31, x + 0.31, color=INK, linewidth=2.0,
              zorder=5, label="rate if PKG-4+ with a package price were oriented")
    ax.axhline(grand, color=MUTED, linewidth=1.4, linestyle=(0, (5, 4)),
               zorder=2)
    ax.text(len(BUCKETS) - 0.35, grand + 1.1, f"tape average {grand:.1f}%",
            color=INK2, fontsize=9.5, ha="right")

    for i, v in enumerate(rate):
        ax.text(i, v + 1.4, f"{v:.0f}", ha="center", fontsize=9.5,
                color=INK, fontweight="600")
    ax.set_ylim(0, 66)
    ax.set_yticks([0, 10, 20, 30, 40, 50])
    ax.set_ylabel("share of the bucket's DV01 that is excluded  (%)", fontsize=10)
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9.5, loc="upper left", ncol=2,
              labelcolor=INK2, handlelength=1.6, columnspacing=1.4,
              borderaxespad=0.4)
    ax.set_title(
        "The exclusion rate is a fixed function of the curve region\n"
        "USD swaps tape, 610 days (2024-03-01 to 2026-08-07), gross DV01 proxy",
        fontsize=13, fontweight="600", loc="left", pad=12)

    cols = [POS if v > 0 else NEG for v in delta]
    ax2.bar(x, delta, 0.62, color=cols, edgecolor=SURFACE, linewidth=1.6,
            zorder=3)
    ax2.axhline(0, color=BASE, linewidth=1.2, zorder=4)
    for i, v in enumerate(delta):
        ax2.text(i, v + (0.13 if v > 0 else -0.13), f"{v:+.2f}", ha="center",
                 va="bottom" if v > 0 else "top", fontsize=9, color=INK2)
    ax2.set_ylim(-2.1, 2.4)
    ax2.set_ylabel("retained share minus\ntape share  (pp of DV01)", fontsize=10)
    ax2.grid(axis="y", zorder=0)
    ax2.set_axisbelow(True)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{b}\n{s:.1f}% of tape" for b, s in
                         zip(BUCKETS, tape_shr)], fontsize=9.5, color=INK2)
    ax2.set_title("blue = the retained sample over-represents that bucket; "
                  "red = under-represents", fontsize=9.5, color=INK2,
                  loc="left", pad=7)
    fig.savefig(IMG / "exclusion-rate-by-tenor.png", dpi=170,
                bbox_inches="tight")
    plt.close(fig)

    # ================================================== chart B
    m = legs.pivot_table(index="month", columns="excl_class", values="dv01",
                         aggfunc="sum", fill_value=0.0).reindex(columns=CLS)
    m = m.fillna(0.0)
    m["TOTAL"] = m.sum(axis=1)
    ser = {
        "all exclusions": 100 * (m["TOTAL"] - m["KEPT"]) / m["TOTAL"],
        "PKG-4+": 100 * m["PKG4"] / m["TOTAL"],
        "asset swap": 100 * m["ASSETSWAP"] / m["TOTAL"],
        "all other": 100 * m["OTHER_EXCL"] / m["TOTAL"],
    }
    t = m.index.to_timestamp()
    fig, ax = plt.subplots(figsize=(11.2, 5.2))
    styles = [(INK, 2.4), (S_PKG4, 2.0), (S_ASWAP, 2.0), (S_OTHER, 2.0)]
    for (lab, y), (col, lw) in zip(ser.items(), styles):
        ax.plot(t[:-1], y.to_numpy()[:-1], color=col, linewidth=lw, label=lab,
                zorder=4, solid_capstyle="round")
        ax.plot(t[-2:], y.to_numpy()[-2:], color=col, linewidth=lw, zorder=3,
                linestyle=(0, (2, 2)))
        ax.plot(t[-1], y.to_numpy()[-1], "o", ms=6, mfc=SURFACE, mec=col,
                mew=1.8, zorder=5)
        ax.text(t[-1] + pd.Timedelta(days=26), y.to_numpy()[-2],
                lab, color=col, fontsize=10, va="center", fontweight="600")

    brk = pd.Timestamp("2024-06-01")
    ax.axvline(brk, color=MUTED, linewidth=1.3, linestyle=(0, (4, 3)), zorder=2)
    ax.text(brk + pd.Timedelta(days=8), 55.5,
            "measured ingest break\n(NO_FIXED_RATE 5.1% -> 0.4%)",
            color=INK2, fontsize=9)
    ax.axvline(pd.Timestamp("2024-10-07"), color=BASE, linewidth=1.1,
               linestyle=(0, (2, 3)), zorder=2)
    ax.text(pd.Timestamp("2024-10-14"), 33.5, "cap-schedule\nvintage change",
            color=MUTED, fontsize=8.5)
    ax.axvspan(pd.Timestamp("2026-08-01"), t[-1] + pd.Timedelta(days=20),
               color=GRID, alpha=0.55, zorder=1)
    ax.text(pd.Timestamp("2026-08-17"), 56.0,
            "2026-08: partial\nmonth (5 sessions),\nnot fitted",
            color=MUTED, fontsize=8.5, ha="left", va="top", linespacing=1.35)

    ax.set_ylim(0, 60)
    ax.set_xlim(t[0] - pd.Timedelta(days=14), t[-1] + pd.Timedelta(days=150))
    ax.set_ylabel("share of the month's DV01 that is excluded  (%)", fontsize=10)
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)
    ax.set_title(
        "The exclusion rate is high but not drifting\n"
        "monthly, DV01-weighted; post-break mean 42.5%, sd 2.4 pp, "
        "trend -0.91 pp/yr (t = -1.16)",
        fontsize=13, fontweight="600", loc="left", pad=14)
    fig.savefig(IMG / "exclusion-rate-monthly.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

    print("wrote", IMG / "exclusion-rate-by-tenor.png")
    print("wrote", IMG / "exclusion-rate-monthly.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
