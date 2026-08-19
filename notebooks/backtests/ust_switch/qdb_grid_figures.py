"""Figures for the QDB all-pairs grid: bond switches vs matched-maturity swap boxes."""

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
OUT = HERE / "_out" / "qdb_grid"
FIGS = HERE / "_out" / "figs"


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIGS / name, dpi=130, bbox_inches="tight", facecolor=F.SURFACE)
    import matplotlib.pyplot as plt

    plt.close(fig)
    print(f"  {name}")


def main() -> int:
    plt = F.style()
    FIGS.mkdir(parents=True, exist_ok=True)
    league = pd.read_csv(OUT / "league_deflated.csv")

    # A. league heatmaps: best Sharpe by (tenor, pair), bond vs MMS side by side.
    #    Same diverging scale on both so the comparison is honest.
    piv = {}
    for inst in ("bond", "mms"):
        d = league[league["instrument"] == inst]
        if inst == "mms":
            d = d[d["swap_cost"] > 0]  # the costed version is the headline
        piv[inst] = d.pivot_table(index="tenor", columns="pair", values="sharpe", aggfunc="max")
    if piv.get("mms") is not None and len(piv["mms"]):
        import matplotlib.colors as mcolors

        order = [c for c in ("CTvO", "CTvOO", "CTvOOO", "OvOO", "OvOOO", "OOvOOO")]
        lim = max(float(np.nanmax(np.abs(p.values))) for p in piv.values() if p.size)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "pol", [F.ROLE["cost"], "#efeeea", F.ROLE["price"]])
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.2))
        for ax, inst, title in zip(
            axes, ("bond", "mms"),
            ("bond switch (2010–2026)", "matched-maturity SOFR box, swap cost 0.5bp (2018–2026)"),
        ):
            p = piv[inst].reindex(columns=[c for c in order if c in piv[inst].columns])
            im = ax.imshow(p.values, cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
            ax.set_xticks(range(p.shape[1]), p.columns, fontsize=8)
            ax.set_yticks(range(p.shape[0]), [f"{int(t)}Y" for t in p.index], fontsize=8)
            for i in range(p.shape[0]):
                for j in range(p.shape[1]):
                    v = p.values[i, j]
                    if np.isfinite(v):
                        ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7.5,
                                color=F.INK if abs(v) < lim * 0.6 else F.SURFACE)
            ax.grid(False)
            ax.set_title(f"Best net Sharpe — {title}", fontsize=10)
        fig.colorbar(im, ax=axes, fraction=0.02, pad=0.02, label="Sharpe")
        save(fig, "16_qdb_grid_league_bond_vs_mms.png")

    # B. top equity curves
    eqp = OUT / "top_equity.parquet"
    if eqp.exists():
        eq = pd.read_parquet(eqp)
        fig, ax = plt.subplots(figsize=(12, 4.6))
        for i, col in enumerate(eq.columns[:6], start=1):
            s = eq[col].dropna()
            ax.plot(s.index, s.values, color=F.PAL[min(i, 8)], lw=1.6, label=col)
        ax.axhline(0, color=F.MUTED, lw=0.9)
        ax.set_ylabel("cumulative P&L (bp)")
        ax.set_title("Grid winners by Sharpe — cumulative P&L (bp), net of costs and financing")
        ax.legend(fontsize=7.5, loc="upper left")
        save(fig, "17_qdb_grid_top_equity.png")

    # C. bond vs MMS on the SAME cell/rule — does the swap hedge help?
    b = league[(league["instrument"] == "bond")]
    m = league[(league["instrument"] == "mms") & (league["swap_cost"] > 0)]
    key = ["tenor", "pair", "direction", "entry_offset", "exit_rule", "z"]
    j = b.merge(m, on=key, suffixes=("_bond", "_mms"))
    if len(j):
        fig, ax = plt.subplots(figsize=(6.4, 5.6))
        ax.scatter(j["sharpe_bond"], j["sharpe_mms"], s=12, alpha=0.5, color=F.PAL[1],
                   edgecolors="none")
        lim = float(np.nanmax(np.abs(j[["sharpe_bond", "sharpe_mms"]].values))) * 1.05
        ax.plot([-lim, lim], [-lim, lim], color=F.MUTED, lw=1.0, ls="--")
        ax.axhline(0, color=F.GRID, lw=0.8)
        ax.axvline(0, color=F.GRID, lw=0.8)
        ax.set_xlabel("bond switch Sharpe")
        ax.set_ylabel("MMS box Sharpe (same cell, same rule, 2018+)")
        n_up = int((j["sharpe_mms"] > j["sharpe_bond"]).sum())
        ax.set_title(f"Does the matched-maturity swap hedge help?  "
                     f"{n_up}/{len(j)} cells improve", fontsize=10)
        save(fig, "18_qdb_grid_bond_vs_mms_scatter.png")
        j[key + ["sharpe_bond", "sharpe_mms", "net_bp_per_trade_bond", "net_bp_per_trade_mms"]
          ].to_csv(OUT / "bond_vs_mms_matched.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
