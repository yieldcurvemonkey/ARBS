"""The honest contrast: six figures that settle what is real in the ETF-rebalance study.

Every panel carries its null or its control. Nothing here is recomputed -- each figure reads
a CSV/parquet written by an earlier investigation in ``_data/`` so that the picture and the
number in RESULTS.md cannot drift apart.

    python notebooks/backtests/etf_rebalance/contrast_figures.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import figstyle as FS  # noqa: E402

FS.use()

D = HERE / "_data"
FIG = HERE / "figures"
FIG.mkdir(parents=True, exist_ok=True)

COST_BP = 0.535  # median measured DV01-neutral 20-30y butterfly round trip, FedInvest bid/offer
HORIZONS = [5, 10, 21, 42, 63]


def lighten(colour: str, f: float = 0.45) -> str:
    """A lighter tint of the SAME hue. Lightness marks the variant; hue stays the entity."""
    r, g, b = mcolors.to_rgb(colour)
    return mcolors.to_hex((r + (1 - r) * f, g + (1 - g) * f, b + (1 - b) * f))


def pad_for_note(ax, frac: float = 0.30) -> None:
    """Reserve empty band at the bottom of an axes so a corner note cannot land on data."""
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo - (hi - lo) * frac, hi)


# --------------------------------------------------------------------------------------
# Figure 1 -- raw versus partial IC term structure, one panel per holdings signal
# --------------------------------------------------------------------------------------


def fig1_raw_vs_partial() -> str:
    pic = pd.read_parquet(D / "partial_ic.parquet")
    surf = pd.read_parquet(D / "ic_surface.parquet")

    order = ["active_w", "active_rel", "active_chg", "ownership",
             "ownership_chg", "flow", "deletion"]
    pretty = {
        "active_w": "active_w   fund wt − index wt",
        "active_rel": "active_rel   active / index wt",
        "active_chg": "active_chg   Δ active wt",
        "ownership": "ownership   share of float held",
        "ownership_chg": "ownership_chg",
        "flow": "flow   implied fund trade",
        "deletion": "deletion   CALENDAR, reads no holdings",
    }

    resid = (surf[(surf.signal == "z_resid") & (surf.horizon.isin(HORIZONS))]
             .sort_values("horizon"))
    resid_63 = float(resid.loc[resid.horizon == 63, "ic_mean"].iloc[0])

    fig, axes = FS.panels(2, 4, w=3.65, h=3.25)
    axes = axes.ravel()
    x = np.arange(len(HORIZONS))

    def draw(ax, sub, kind, colour, ls):
        s = sub[sub.kind == kind].set_index("horizon").reindex(HORIZONS)
        y = s["ic"].to_numpy()
        t = s["t"].to_numpy()
        ax.plot(x, y, color=colour, ls=ls, lw=2.0, alpha=0.9, zorder=3)
        sig = np.abs(t) >= 2.0
        ax.plot(x[sig], y[sig], ls="none", marker="o", ms=6.2, color=colour,
                mec=colour, mew=1.4, zorder=4)
        ax.plot(x[~sig], y[~sig], ls="none", marker="o", ms=6.2, color="white",
                mec=colour, mew=1.4, zorder=4)

    for ax, sig_name in zip(axes[:7], order):
        sub = pic[pic.signal == sig_name]
        base = FS.ROLE["null"] if sig_name == "deletion" else FS.ROLE["thesis"]
        alt = lighten(base, 0.45) if sig_name == "deletion" else FS.ROLE["thesis_alt"]
        draw(ax, sub, "raw", base, "-")
        draw(ax, sub, "partial", alt, "--")
        FS.zero_line(ax)
        ax.set_xticks(x)
        ax.set_xticklabels([str(h) for h in HORIZONS])
        ax.set_xlim(-0.35, len(HORIZONS) - 0.65)
        ax.set_title(pretty[sig_name], fontsize=9.4, pad=17)
        ax.set_xlabel("forward horizon (business days)")
        raw63 = float(sub[(sub.kind == "raw") & (sub.horizon == 63)]["ic"].iloc[0])
        par63 = float(sub[(sub.kind == "partial") & (sub.horizon == 63)]["ic"].iloc[0])
        flip = "sign FLIPS" if raw63 * par63 < 0 else "no sign change"
        ax.text(0.0, 1.015, f"63d IC  {raw63:+.3f} → {par63:+.3f}   ·   {flip}",
                transform=ax.transAxes, ha="left", va="bottom", fontsize=8.2,
                color=FS.INK["secondary"])
        pad_for_note(ax, 0.26)
        FS.annotate_null(ax, f"richness control IC @63d = {resid_63:+.3f}", loc="lower left")

    axes[0].set_ylabel("cross-sectional Spearman IC")
    axes[4].set_ylabel("cross-sectional Spearman IC")

    # the eighth panel: the same holdings signals against the control they were cleaned with
    ax = axes[7]
    for sig_name in order:
        s = (pic[(pic.signal == sig_name) & (pic.kind == "partial")]
             .set_index("horizon").reindex(HORIZONS))
        ax.plot(x, s["ic"].to_numpy(),
                color=FS.ROLE["null"] if sig_name == "deletion" else FS.ROLE["thesis"],
                lw=1.3, alpha=0.6, zorder=3)
    ax.plot(x, resid["ic_mean"].to_numpy(), color=FS.ROLE["control"], lw=2.8,
            marker="o", ms=6.2, zorder=5)
    FS.zero_line(ax)
    ax.set_xticks(x)
    ax.set_xticklabels([str(h) for h in HORIZONS])
    ax.set_xlim(-0.35, len(HORIZONS) - 0.65)
    ax.set_ylim(-0.10, 0.53)
    ax.legend(handles=[
        Line2D([], [], color=FS.ROLE["control"], lw=2.8, marker="o",
               label="richness control (no ETF data)"),
        Line2D([], [], color=FS.ROLE["null"], lw=1.3, label="calendar-only `deletion`"),
        Line2D([], [], color=FS.ROLE["thesis"], lw=1.3,
               label="the six holdings signals,\nonce the control is removed"),
    ], loc="upper left", fontsize=7.6, handlelength=1.3, labelspacing=0.45,
        borderpad=0.2)
    ax.set_title("what survives, against what it was cleaned with", fontsize=9.4, pad=17)
    ax.text(0.0, 1.015, "one axis, everything on it — this is the scale of the result",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=8.2,
            color=FS.INK["secondary"])
    ax.set_xlabel("forward horizon (business days)")
    ax.set_ylabel("cross-sectional Spearman IC")

    handles = [
        Line2D([], [], color=FS.ROLE["thesis"], lw=2.0, ls="-",
               label="raw IC — holdings signal"),
        Line2D([], [], color=FS.ROLE["thesis_alt"], lw=2.0, ls="--",
               label="same signal, orthogonalised against the richness control"),
        Line2D([], [], color=FS.ROLE["null"], lw=2.0, ls="-",
               label="calendar-only signal (reads no holdings file)"),
        Line2D([], [], color=FS.ROLE["control"], lw=2.8, marker="o",
               label="the richness control itself"),
        Line2D([], [], color=FS.INK["secondary"], ls="none", marker="o", ms=6.2,
               label="filled marker: Newey-West |t| ≥ 2"),
        Line2D([], [], color="white", mec=FS.INK["secondary"], mew=1.4, ls="none",
               marker="o", ms=6.2, label="hollow marker: |t| < 2, NOT significant"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, -0.045), fontsize=8.8)
    fig.suptitle("Remove the bond's own richness and five of six holdings signals change sign "
                 "— the sixth collapses to zero",
                 x=0.006, ha="left", fontsize=14, weight="semibold")
    fig.tight_layout(rect=(0, 0.015, 1, 0.955))

    n_sig = int((pic.kind.eq("partial") & pic.t.abs().ge(2)).sum())
    n_tot = int(pic.kind.eq("partial").sum())
    return FS.finish(
        fig, FIG / "contrast_01_raw_vs_partial_ic.png",
        caption=(
            "Raw versus richness-orthogonalised cross-sectional IC for every ETF-holdings signal, "
            "TLT 2016-2026, exec_lag=1. The raw IC on active weight is large and BACKWARDS "
            "(-0.064 at 63 days): the bonds the fund is UNDERweight subsequently cheapen, the "
            "opposite of the hypothesis, because a fund that overweights large, liquid, recently "
            "issued bonds is overweighting a set that is also systematically rich. Orthogonalising "
            "each signal against the bond's own fitted-curve richness residual flips the sign of "
            "five of the six holdings signals and collapses every one of them to |IC| <= 0.018; "
            "the sixth (flow) simply goes to zero. Markers are hollow wherever the Newey-West "
            f"t (h-1 lags) is under 2 in absolute value; only {n_sig} of {n_tot} orthogonalised "
            "points clear it. The eighth panel puts all seven cleaned signals on the same axis as "
            "the control that cleaned them: the control reaches IC 0.349 at 63 days, roughly thirty "
            "times anything the holdings produce, and the calendar-only deletion signal beats them "
            "too. Source: _data/partial_ic.parquet, _data/ic_surface.parquet."
        ))


# --------------------------------------------------------------------------------------
# Figure 2 -- naive versus Newey-West t
# --------------------------------------------------------------------------------------


def fig2_naive_vs_hac() -> str:
    rows = []

    pic = pd.read_parquet(D / "partial_ic.parquet")
    for _, r in pic.iterrows():
        rows.append((r.t_naive, r.t, "null" if r.signal == "deletion" else "thesis"))

    biv = pd.read_parquet(D / "bivariate.parquet")
    for _, r in biv.iterrows():
        rows.append((r.t_signal_naive, r.t_signal,
                     "null" if r.signal == "z_deletion" else "thesis"))

    dc = pd.read_csv(D / "deletion_control.csv")
    for _, r in dc.iterrows():
        rows.append((r.t_naive, r.t_hac,
                     "placebo" if r.variant.startswith("PLACEBO") else "null"))

    lad = pd.read_csv(D / "audit_ladder_newey_west.csv")
    for _, r in lad.iterrows():
        rows.append((r.t_naive, r.t_newey_west,
                     "null" if r.signal.endswith("_wi_NULL") else "thesis"))

    pts = pd.DataFrame(rows, columns=["naive", "hac", "role"]).dropna()

    xh = float(np.ceil(pts.naive.abs().max() / 5) * 5)
    y_top = float(np.ceil(pts.hac.max())) + 1.6
    y_bot = float(np.floor(pts.hac.min())) - 3.0

    fig, ax = FS.panels(1, 1, w=8.8, h=6.2)

    # the region a sceptic cares about: significant naively, dead once overlap is counted
    for x0, w in ((2, xh - 2), (-xh, xh - 2)):
        ax.add_patch(plt.Rectangle((x0, -2), w, 4, facecolor=FS.INK["grid"], alpha=0.7,
                                   zorder=0, lw=0))

    ax.plot([-xh, xh], [-xh, xh], color=FS.INK["secondary"], lw=1.3, zorder=2,
            label="y = x   (no inflation)")
    for f, frac, va, dy in ((5.19, 0.66, "bottom", 0.10), (5.95, 0.88, "top", -0.10)):
        ax.plot([-xh, xh], [-xh / f, xh / f], color=FS.INK["muted"], lw=1.1, ls=":",
                zorder=2)
        ax.text(xh * frac, xh * frac / f + dy, f"÷{f}", fontsize=8.4,
                color=FS.INK["muted"], ha="center", va=va)
    for v in (-2, 2):
        ax.axhline(v, color=FS.ROLE["cost"], lw=1.4, ls="--", zorder=2)
        ax.axvline(v, color=FS.INK["secondary"], lw=0.9, ls=":", zorder=2)
    FS.zero_line(ax)
    ax.axvline(0, color=FS.INK["secondary"], lw=0.9, zorder=1)
    ax.text(-xh + 0.4, 2.1, "Newey-West |t| = 2", fontsize=8.4, color=FS.ROLE["cost"],
            va="bottom")

    for role, marker, label in (("thesis", "o", "holdings-based signal"),
                                ("null", "^", "calendar-only signal / index null twin"),
                                ("placebo", "s", "matched placebo boundary")):
        s = pts[pts.role == role]
        ax.scatter(s.naive, s.hac, s=42, marker=marker, facecolor=FS.ROLE[role],
                   edgecolor="white", linewidth=0.6, alpha=0.85, zorder=5,
                   label=f"{label}   (n={len(s)})")

    adv = pd.read_csv(D / "adv_newey_west_tstats.csv")
    offsets = [(-96, 40), (34, -46)]
    for (_, r), off in zip(adv.iterrows(), offsets):
        ax.scatter([r.naive_t], [r.nw_t_lags62], s=170, marker="o", facecolor="none",
                   edgecolor=FS.INK["primary"], linewidth=1.7, zorder=6)
        ax.annotate(f"{r.fund} {r.signal}\nnaive {r.naive_t:.2f} → HAC {r.nw_t_lags62:.2f}"
                    f"   (×{r.inflation_factor:.2f})",
                    (r.naive_t, r.nw_t_lags62), textcoords="offset points", xytext=off,
                    fontsize=8.4, color=FS.INK["primary"], ha="center",
                    arrowprops=dict(arrowstyle="-", color=FS.INK["muted"], lw=0.9))

    loud = pts[pts.naive.abs() >= 2]
    dead = loud[loud.hac.abs() < 2]
    med_infl = float((loud.naive.abs() / loud.hac.abs().clip(lower=1e-9)).median())

    ax.set_xlim(-xh, xh)
    ax.set_ylim(y_bot, y_top)
    ax.set_xlabel("naive t   —   mean / (sd/√n) over overlapping windows")
    ax.set_ylabel("Newey-West t   (h−1 lags)")
    ax.set_title("Counting the overlap deletes most of the significance in this study",
                 fontsize=13.5)
    ax.legend(loc="upper left", fontsize=8.8)
    FS.annotate_null(
        ax,
        f"{len(dead)} of {len(loud)} points with naive |t| ≥ 2 land inside |t| < 2 under HAC "
        f"(the grey band)\nmedian inflation among them ×{med_infl:.2f};  no cloud reaches the "
        "y = x line",
        loc="lower right")
    fig.tight_layout()

    return FS.finish(
        fig, FIG / "contrast_02_naive_vs_hac_t.png",
        caption=(
            "Every t-statistic in the study, naive against Newey-West, one point per "
            "(signal, horizon, specification). A 63-day forward return sampled daily shares 62 of "
            "its 63 days with the next observation, so a naive t treats ~2,400 overlapping windows "
            f"as 2,400 independent draws. {len(dead)} of {len(loud)} points that clear |t| = 2 "
            f"naively fail to clear it under HAC (grey band), at a median inflation of "
            f"×{med_infl:.2f}. Two prior agents measured the factor independently at ×5.19 "
            "(TLT bucket_hist_z) and ×5.95 (GOVT bucket_active); both are circled and both rays "
            "are drawn. Nothing in the study sits near the y = x line. The direction of the "
            "correction is uniform, so the RANKING of signals survives — the significance does "
            "not. Source: _data/partial_ic.parquet, bivariate.parquet, deletion_control.csv, "
            "audit_ladder_newey_west.csv, adv_newey_west_tstats.csv."
        ))


# --------------------------------------------------------------------------------------
# Figure 3 -- the double sort
# --------------------------------------------------------------------------------------


def fig3_double_sort() -> str:
    ds = pd.read_csv(D / "realized_double_sort.csv")
    cfg = "active_k10_lag1_h10"
    sub = ds[(ds.ticker == "TLT") & (ds.config == cfg)].sort_values("qr")
    M = sub[["0", "1", "2"]].to_numpy(dtype=float).T  # 3 terciles x 5 quintiles
    hml = M[2] - M[0]

    lad = pd.read_csv(D / "ladder2_double_sort_held.csv")
    row = lad[(lad.width == 0.25) & (lad.signal == "bucket_active") & (lad.horizon == 63)]
    sv = ast.literal_eval(row.spread_values.iloc[0])
    hml63 = np.array([float(sv[i]) for i in range(5)])

    fig = plt.figure(figsize=(8.8, 8.2))
    gs = fig.add_gridspec(3, 1, height_ratios=[2.15, 1.0, 1.0], hspace=0.62,
                          left=0.150, right=0.855, top=0.880, bottom=0.095)
    ax0 = fig.add_subplot(gs[0])
    ax1 = fig.add_subplot(gs[1], sharex=ax0)
    ax2 = fig.add_subplot(gs[2], sharex=ax0)

    v = float(np.abs(M).max())
    im = ax0.imshow(M, cmap=FS.DIVERGING, vmin=-v, vmax=v, aspect="auto",
                    origin="lower", extent=(-0.5, 4.5, -0.5, 2.5))
    ax0.grid(False)
    for i in range(3):
        for j in range(5):
            ax0.text(j, i, f"{M[i, j]:+.3f}", ha="center", va="center", fontsize=10,
                     color=FS.INK["primary"])
    ax0.set_yticks([0, 1, 2])
    ax0.set_yticklabels(["low\n(most UNDERweight)", "mid", "high\n(most OVERweight)"])
    ax0.set_ylabel("active-weight tercile")
    ax0.set_title("mean forward richening (bp) — the gradient runs LEFT-TO-RIGHT with "
                  "richness,\nnot BOTTOM-TO-TOP with the fund's active weight",
                  fontsize=10.2, pad=9)
    p0 = ax0.get_position()
    cax = fig.add_axes((0.872, p0.y0, 0.017, p0.height))
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("bp", fontsize=8.8)
    cb.outline.set_linewidth(0.6)

    for ax, y, lab, colour in (
        (ax1, hml, f"TLT active_w, 10-day hold   ({cfg})", FS.ROLE["thesis"]),
        (ax2, hml63, "TLT bucket_active, 63 days, bucket composition held at entry",
         FS.ROLE["thesis_alt"]),
    ):
        ax.bar(np.arange(5), y, width=0.6, color=colour, alpha=0.92, zorder=3)
        FS.zero_line(ax)
        yl = float(np.abs(y).max())
        ax.set_ylim(-yl * 1.85, yl * 1.85)
        dp = 4 if yl < 0.01 else 3
        for j, val in enumerate(y):
            ax.text(j, val + np.sign(val) * yl * 0.13, f"{val:+.{dp}f}", ha="center",
                    va="bottom" if val >= 0 else "top", fontsize=8.8,
                    color=FS.INK["primary"])
        ax.set_ylabel("high − low (bp)")
        signs = np.sign(y)
        flips = int((signs[:-1] != signs[1:]).sum())
        ax.set_title(f"high-minus-low active weight inside each richness quintile — {lab}"
                     f"\n{flips} sign change{'s' if flips != 1 else ''} across five quintiles: "
                     "not monotone, and the same size as its own noise",
                     fontsize=9.6, pad=7)

    ax2.set_xticks(np.arange(5))
    ax2.set_xticklabels(["0\n(richest)", "1", "2", "3", "4\n(cheapest)"])
    ax2.set_xlabel("richness-residual quintile")
    ax0.set_xlim(-0.5, 4.5)
    for a in (ax0, ax1):
        plt.setp(a.get_xticklabels(), visible=False)

    fig.suptitle("Sort on richness first and the fund's active weight adds nothing — "
                 "and does not add it monotonically",
                 x=0.006, y=0.975, ha="left", fontsize=13.5, weight="semibold")
    fig.text(0.006, 0.012, "source: _data/realized_double_sort.csv (upper bar panel), "
             "_data/ladder2_double_sort_held.csv (lower bar panel)",
             fontsize=8, color=FS.INK["muted"], ha="left")

    return FS.finish(
        fig, FIG / "contrast_03_double_sort.png",
        caption=(
            "Mean forward richening by (richness quintile x active-weight tercile), TLT. In the "
            "heatmap the colour varies almost entirely along the richness axis: within a richness "
            "quintile, moving from the fund's most underweight bonds to its most overweight bonds "
            "changes the forward move by a few thousandths of a basis point. The two bar panels "
            "give the high-minus-low spread per quintile, for the 10-day book and for the 63-day "
            "bucket book with composition held fixed at entry. Both are non-monotone and "
            "sign-flipping across the five quintiles. A naive t of 4 that survives neither a HAC "
            "correction (figure 2) nor a double sort is a linear artefact. Source: "
            "_data/realized_double_sort.csv, _data/ladder2_double_sort_held.csv."
        ))


# --------------------------------------------------------------------------------------
# Figure 4 -- the placebo distribution
# --------------------------------------------------------------------------------------


def fig4_placebo() -> str:
    dc = pd.read_csv(D / "deletion_control.csv")
    x = np.arange(len(HORIZONS))

    plac = [v for v in dc.variant.unique() if v.startswith("PLACEBO")]
    P = np.vstack([dc[dc.variant == v].sort_values("horizon").t_hac.to_numpy()
                   for v in plac])

    fig, ax = FS.panels(1, 1, w=8.8, h=6.0)

    ax.fill_between(x, P.min(axis=0), P.max(axis=0), color=FS.ROLE["placebo"],
                    alpha=0.22, zorder=1, lw=0,
                    label="span of the four matched placebo boundaries")
    for v, y in zip(plac, P):
        ax.plot(x, y, color=FS.ROLE["placebo"], lw=1.3, alpha=0.9, zorder=3,
                marker="s", ms=4.2)
        ax.text(x[-1] + 0.07, float(y[-1]), "  " + v.split()[2].rstrip(","), fontsize=8.8,
                color=FS.INK["primary"], va="center")

    reals = [
        ("REAL 20y crossing-matched, fit 15-31y", "-", 2.9, 1.0,
         "REAL 20y boundary, matched to the placebos (fires 1.6% of bond-days)"),
        ("REAL 20y, fit 20-31y (20y is the EDGE)", "--", 2.1, 0.9,
         "REAL 20y, curve fitted 20-31y — 20y is the EDGE of the fit (fires 2.3%)"),
        ("REAL 20y, fit 15-31y (20y is INTERIOR)", ":", 1.8, 0.75,
         "REAL 20y maturity dummy, NOT rate-matched (fires 33%)"),
    ]
    for name, ls, lw, alpha, label in reals:
        s = dc[dc.variant == name].sort_values("horizon")
        ax.plot(x, s.t_hac.to_numpy(), color=FS.ROLE["null"], ls=ls, lw=lw, alpha=alpha,
                marker="o", ms=6.2, zorder=5, label=label)

    for v in (-2, 2):
        ax.axhline(v, color=FS.ROLE["cost"], lw=1.4, ls="--", zorder=2,
                   label="Newey-West |t| = 2" if v == 2 else None)
    FS.zero_line(ax)

    ax.set_xticks(x)
    ax.set_xticklabels([str(h) for h in HORIZONS])
    ax.set_xlim(-0.35, len(HORIZONS) - 0.50)
    ax.set_ylim(-4.3, 4.9)
    ax.set_xlabel("forward horizon (business days)")
    ax.set_ylabel("Newey-West t on the boundary dummy")
    ax.set_title("A boundary where no index does anything beats the real 20-year deletion "
                 "boundary", fontsize=13.5)
    h_, l_ = ax.get_legend_handles_labels()
    fig.legend(h_, l_, loc="lower center", ncol=2, frameon=False, fontsize=8.6,
               bbox_to_anchor=(0.52, -0.015))

    q = lambda name, h: float(dc[(dc.variant == name) & (dc.horizon == h)].t_hac.iloc[0])
    real_max = float(dc[dc.variant == reals[0][0]].t_hac.abs().max())
    plac_max = float(np.abs(P).max())
    i, j = np.unravel_index(np.abs(P).argmax(), P.shape)
    FS.annotate_null(
        ax,
        f"at 63 days the fit EDGE alone is worth {q(reals[1][0], 63):.2f} → "
        f"{q(reals[0][0], 63):.2f}\n"
        f"largest |HAC t| over all horizons:  matched real {real_max:.2f}   vs   "
        f"placebo {plac_max:.2f}  ({plac[int(i)].split()[2].rstrip(',')} @ {HORIZONS[int(j)]}d)\n"
        "the real boundary sits INSIDE its own null band, not outside it",
        loc="lower left")
    fig.tight_layout(rect=(0, 0.105, 1, 1))

    return FS.finish(
        fig, FIG / "contrast_04_placebo_distribution.png",
        caption=(
            "The calendar-only deletion signal against its own null distribution. A bond about to "
            "fall below TLT's 20-year index boundary is by construction the shortest bond in a "
            "curve fitted over 20-31 years, so the apparent effect is confounded with the edge of "
            "the fit. Widening the fit to 15-31 years makes the bond interior and costs it a third "
            f"of its 63-day statistic ({q(reals[1][0], 63):.2f} → {q(reals[0][0], 63):.2f}). Four "
            "matched placebo boundaries at 22/24/26/28 years — the same crossing shape, the same "
            "~2% firing rate, at maturities where no index does anything whatsoever — reach "
            f"|t| = {plac_max:.2f} against the matched real boundary's {real_max:.2f}. The real "
            "line sitting inside the grey band is the finding. It is drawn in the calendar-null "
            "role because that is what it is: a signal that reads no holdings file. Source: "
            "_data/deletion_control.csv."
        ))


# --------------------------------------------------------------------------------------
# Figure 5 -- the calendar beats the scrape
# --------------------------------------------------------------------------------------


def fig5_calendar_beats_scrape() -> str:
    r = pd.read_csv(D / "adv_calnull_recheck.csv")
    r = r.assign(a=r.best_holdings_ic.abs(), b=r.deletion_ic.abs())
    r = r.sort_values("b", ascending=True).reset_index(drop=True)
    y = np.arange(len(r))

    fig, ax = FS.panels(1, 1, w=8.8, h=5.4)

    for i, row in r.iterrows():
        win = row.b > row.a
        ax.plot([row.a, row.b], [i, i],
                color=FS.INK["muted"] if win else FS.ROLE["thesis"],
                lw=2.4, alpha=0.5, zorder=2, solid_capstyle="round")

    ax.scatter(r.a, y, s=115, color=FS.ROLE["thesis"], edgecolor="white", lw=0.8,
               zorder=5, label="best HOLDINGS signal   (partial IC @ 63d)")
    ax.scatter(r.b, y, s=115, color=FS.ROLE["null"], edgecolor="white", lw=0.8,
               marker="D", zorder=5,
               label="calendar-only `deletion`   (reads NO holdings file)")

    for i, row in r.iterrows():
        near_edge = row.a < 0.035
        ax.text(0.004 if near_edge else row.a, i + 0.22,
                f"{row.best_holdings_signal_ic_selection}  {row.best_holdings_ic:+.3f}",
                ha="left" if near_edge else "center", va="bottom", fontsize=8.2,
                color=FS.INK["primary"])
        ax.text(row.b, i - 0.24, f"{row.deletion_ic:+.3f}", ha="center", va="top",
                fontsize=8.6, color=FS.INK["primary"])

    ax.set_yticks(y)
    ax.set_yticklabels(r.fund)
    ax.set_ylim(-0.8, len(r) + 0.15)
    ax.set_xlim(0, max(r.b.max(), r.a.max()) * 1.14)
    ax.set_xlabel("|partial IC| at 63 days   —   magnitude; the signed value is printed "
                  "beside each mark")
    ax.set_title("On five funds of six the calendar beats the scrape — and the calendar "
                 "reads no holdings file", fontsize=13.5)
    ax.legend(loc="lower right", fontsize=8.8)

    n_win = int((r.b > r.a).sum())
    FS.annotate_null(
        ax,
        f"calendar larger on {n_win} of {len(r)} funds — GOVT the only exception\n"
        "…and figure 4 shows the calendar is itself beaten by a placebo,\n"
        "so the ranking of this study is   placebo  >  calendar  >  holdings",
        loc="upper right")
    fig.tight_layout()

    return FS.finish(
        fig, FIG / "contrast_05_calendar_beats_scrape.png",
        caption=(
            "Per fund, the best holdings-based signal against the calendar-only `deletion` signal, "
            "both as partial IC at 63 days after orthogonalising against the richness control. "
            f"The calendar version is larger in magnitude on {n_win} of {len(r)} funds; GOVT is the "
            "only fund where 22,904 scraped holdings documents beat a rule that needs nothing but "
            "a maturity and an index boundary. Combined with figure 4, where the calendar signal is "
            "itself beaten by a matched placebo, the ranking of this study is placebo > calendar > "
            "holdings. Source: _data/adv_calnull_recheck.csv."
        ))


# --------------------------------------------------------------------------------------
# Figure 6 -- the cost wall
# --------------------------------------------------------------------------------------


def fig6_cost_wall() -> str:
    frames = []
    lg = pd.read_csv(D / "grid_league.csv")
    lg["fund"] = "TLT"
    frames.append(lg[["fund", "gross_avg_bp", "avg_bp", "cost_avg_bp", "trades"]])
    for f in ("grid_TLT.parquet", "grid_TLH.parquet", "grid_IEF.parquet"):
        g = pd.read_parquet(D / f)
        frames.append(g[["fund", "gross_avg_bp", "avg_bp", "cost_avg_bp", "trades"]])
    G = pd.concat(frames, ignore_index=True)
    n_all = len(G)
    # S: cells with BOTH a gross and a net, the only ones the scatter can place.
    # Sg: every cell with a gross and its own cost -- the wider marginal.
    S = G.dropna(subset=["gross_avg_bp", "avg_bp", "cost_avg_bp"])
    Sg = G.dropna(subset=["gross_avg_bp", "cost_avg_bp"])

    fig, (ax, ax2) = FS.panels(2, 1, w=8.8, h=4.8)

    lo = float(min(S.gross_avg_bp.min(), S.avg_bp.min())) - 0.12
    hi = float(max(S.gross_avg_bp.max(), S.avg_bp.max())) + 0.12

    # the drop itself, drawn: a thin dropline from y = x down to where the config lands.
    # sampled away from the dense core so the stems read as stems rather than a smear.
    spread = S[S.gross_avg_bp.abs() > 0.06]
    drop = spread.sample(n=min(70, len(spread)), random_state=0)
    ax.vlines(drop.gross_avg_bp, drop.avg_bp, drop.gross_avg_bp,
              color=FS.ROLE["cost"], lw=0.7, alpha=0.30, zorder=3)

    ax.plot([lo, hi], [lo, hi], color=FS.INK["secondary"], lw=1.4, zorder=4,
            label="y = x   (a free round trip)")
    ax.axhline(0, color=FS.ROLE["cost"], lw=1.5, ls="--", zorder=4,
               label="net = 0   (break-even)")
    ax.axvline(0, color=FS.INK["secondary"], lw=0.9, ls=":", zorder=2)

    sc = ax.scatter(S.gross_avg_bp, S.avg_bp, c=S.cost_avg_bp, cmap=FS.SEQUENTIAL,
                    s=13, alpha=0.8, linewidth=0, zorder=5,
                    vmin=float(S.cost_avg_bp.quantile(0.01)),
                    vmax=float(S.cost_avg_bp.quantile(0.99)))
    cb = fig.colorbar(sc, ax=ax, pad=0.012, fraction=0.04)
    cb.set_label("measured round-trip cost (bp/trade)", fontsize=8.6)
    cb.outline.set_linewidth(0.6)

    tgt = drop.loc[drop.gross_avg_bp.idxmin()]
    ax.annotate("each stem is one configuration's own\nmeasured round trip — the drop IS "
                "the spread",
                xy=(float(tgt.gross_avg_bp), float((tgt.gross_avg_bp + tgt.avg_bp) / 2)),
                xytext=(-2.15, -1.30), ha="left", fontsize=8.6, color=FS.INK["primary"],
                arrowprops=dict(arrowstyle="->", color=FS.INK["muted"], lw=0.9))

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("GROSS bp per trade")
    ax.set_ylabel("NET bp per trade")
    ax.set_title("Every configuration sits a full round trip below the line", fontsize=13.0)
    ax.legend(loc="upper left", fontsize=8.4)

    n_pos_net = int((S.avg_bp > 0).sum())
    n_pos_50 = int(((S.avg_bp > 0) & (S.trades >= 50)).sum())
    # placed by hand rather than via annotate_null: the lower-left corner is where the
    # y = x line lives, and a note sitting on it is exactly the collision to avoid.
    ax.text(0.150, 0.028,
            f"{len(S):,} of {n_all:,} configurations run over 4 grids\n"
            "(TLT league + TLT/TLH/IEF wide) carry both a gross and a net\n"
            f"net > 0:  {n_pos_net} — the same single-trade cell, listed twice\n"
            f"net > 0 on ≥ 50 trades:  {n_pos_50}   ·   ALIVE by deflated Sharpe:  0",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=8,
            color=FS.INK["muted"])

    # marginal distributions, on one common bp axis -- never a second y-scale
    b_lo = float(min(Sg.gross_avg_bp.min(), 0.0))
    b_hi = float(max(Sg.gross_avg_bp.max(), Sg.cost_avg_bp.max())) + 0.05
    bins = np.linspace(b_lo, b_hi, 90)
    ax2.hist(Sg.gross_avg_bp, bins=bins, color=FS.ROLE["thesis"], alpha=0.9, zorder=3,
             label="GROSS bp per trade — what the signal earns")
    ax2.hist(Sg.cost_avg_bp, bins=bins, color=FS.ROLE["cost"], alpha=0.55, zorder=3,
             label="measured cost bp per trade — what it pays")
    ax2.axvline(COST_BP, color=FS.ROLE["cost"], ls="--", lw=1.9, zorder=5,
                label=f"median 20-30y fly round trip  ({COST_BP:.3f}bp)")
    ax2.axvline(0, color=FS.INK["secondary"], lw=0.9, zorder=4)
    ax2.set_xlim(b_lo, b_hi)
    top = float(max(np.histogram(Sg.gross_avg_bp, bins=bins)[0].max(),
                    np.histogram(Sg.cost_avg_bp, bins=bins)[0].max()))
    ax2.set_ylim(0, top * 1.60)
    ax2.set_xlabel("bp per trade")
    ax2.set_ylabel("configurations")
    ax2.set_title("The two distributions barely touch", fontsize=13.0)
    ax2.legend(loc="upper right", fontsize=8.4)

    over = Sg[Sg.gross_avg_bp > COST_BP]
    n_over = len(over)
    over_funds = "/".join(sorted(over.fund.unique()))
    over_lo, over_hi = float(over.cost_avg_bp.min()), float(over.cost_avg_bp.max())
    ax2.text(0.02, 0.955,
             f"gross > {COST_BP:.3f}bp:  {n_over} of {len(Sg):,} configurations "
             f"({100 * n_over / len(Sg):.2f}%)\n"
             f"— all {over_funds}, whose OWN measured cost is {over_lo:.2f}-{over_hi:.2f}bp\n"
             f"median gross {Sg.gross_avg_bp.median():+.4f}bp   vs   median cost "
             f"{Sg.cost_avg_bp.median():.3f}bp\n"
             "richness dispersion 0.434bp = 0.81× ONE round trip",
             transform=ax2.transAxes, ha="left", va="top", fontsize=8,
             color=FS.INK["muted"],
             bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=2.0))

    # A title names the FINDING. "The cost wall" named the topic and let the reader supply
    # the verdict; the count is the verdict.
    assert n_pos_50 == 0, f"the title claims none; {n_pos_50} cells are net-positive on 50+ trades"
    fig.suptitle(f"Of {n_all:,} configurations, none covers its own round trip on 50 trades or more",
                 x=0.006, y=0.998, ha="left", fontsize=14.5, weight="semibold")
    fig.tight_layout(rect=(0, 0, 1, 0.975))

    return FS.finish(
        fig, FIG / "contrast_06_cost_wall.png",
        caption=(
            f"Gross against net basis points per trade for the {len(S):,} grid configurations "
            f"(of {n_all:,} run across the TLT league table and the wide TLT/TLH/IEF grids) that "
            "carry both figures. Each point's vertical distance below the y = x line — drawn as a "
            "stem for a sample of them — is its own measured round-trip cost on FedInvest's "
            "published bid and offer, and the colour is that cost. The cloud sits entirely below "
            f"break-even: {n_pos_net} rows show a positive net and they are the same single-trade "
            f"cell listed twice, {n_pos_50} configurations are net-positive on 50 trades or more, "
            "and none clears the deflated-Sharpe hurdle. The lower panel puts the gross and cost "
            "distributions on one common axis rather than a second scale, over the wider set of "
            f"{len(Sg):,} cells that carry a gross: only {n_over} produce a gross larger than the "
            f"{COST_BP:.3f}bp median 20-30y butterfly round trip, and all {n_over} are {over_funds} "
            f"configurations whose own measured cost is {over_lo:.2f}-{over_hi:.2f}bp. For context "
            "the entire "
            "cross-sectional richness dispersion this trade could ever capture is 0.434bp — 0.81x "
            "of ONE round trip. Source: _data/grid_league.csv, grid_TLT.parquet, "
            "grid_TLH.parquet, grid_IEF.parquet."
        ))


if __name__ == "__main__":
    for fn in (fig1_raw_vs_partial, fig2_naive_vs_hac, fig3_double_sort,
               fig4_placebo, fig5_calendar_beats_scrape, fig6_cost_wall):
        print(fn(), flush=True)
