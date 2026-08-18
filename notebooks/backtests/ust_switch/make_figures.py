"""Render the study's figures from the run artefacts. Output: _out/figs/*.png"""

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

from RVUtils.USTSwitch import analytics as A  # noqa: E402
from RVUtils.USTSwitch import figures as F  # noqa: E402
from RVUtils.USTSwitch.costs import CostModel  # noqa: E402
from RVUtils.USTSwitch.data import load_prepared, select_financing  # noqa: E402
from RVUtils.USTSwitch.engine import SwitchConfig, run_switch  # noqa: E402
from RVUtils.USTSwitch.grid import TENORS  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "_out"
FIGS = OUT / "figs"
FIGS.mkdir(parents=True, exist_ok=True)

plt = F.style()


def save(fig_or_ax, name: str) -> None:
    fig = fig_or_ax.figure if hasattr(fig_or_ax, "figure") else fig_or_ax
    fig.tight_layout()
    p = FIGS / name
    fig.savefig(p, dpi=130, bbox_inches="tight", facecolor=F.SURFACE)
    plt.close(fig)
    print(f"  {p.name}")


def main() -> int:
    panel, amap = load_prepared()

    # ---- configs worth drawing --------------------------------------------------------
    baseline = SwitchConfig(tenor=10, rank_young=0, rank_old=1, direction=1,
                            entry_offset=1, exit_rule="next_roll", exit_offset=1,
                            financing_mode="modelled")
    best = SwitchConfig(tenor=10, rank_young=0, rank_old=3, direction=1,
                        entry_offset=10, exit_rule="next_roll", exit_offset=1,
                        z_window=250, z_entry=1.0, financing_mode="modelled")

    res_by_mode = {}
    for mode in ("none", "modelled", "actual"):
        cfg = SwitchConfig(**{**baseline.__dict__, "financing_mode": mode})
        res_by_mode[mode] = run_switch(select_financing(panel, mode), amap, cfg,
                                       cost_model=CostModel())
    p_mod = select_financing(panel, "modelled")
    res_base = res_by_mode["modelled"]
    res_best = run_switch(p_mod, amap, best, cost_model=CostModel())

    # 1. equity: baseline vs best, in bp
    ax = F.plot_equity(
        {
            "baseline 10Y O-vs-CT, every cycle": res_base.equity_bp,
            "best grid cell: 10Y OOO-vs-CT, e10, z-filter": res_best.equity_bp,
        },
        title="Olds-vs-currents switch — cumulative P&L, DV01-matched, net of costs (bp)",
    )
    save(ax, "01_equity_baseline_vs_best.png")

    # 2. equity under the three financing assumptions
    ax = F.plot_equity(
        {f"financing={m}": r.equity_bp for m, r in res_by_mode.items() if not r.daily.empty},
        title="Same rules, three financing assumptions — 10Y O-vs-CT (bp)",
    )
    save(ax, "02_equity_financing_modes.png")

    # 3. P&L decomposition of the baseline
    ax = F.plot_pnl_decomposition(A.pnl_decomposition(res_base),
                                  title="Baseline 10Y O-vs-CT — where the P&L went (bp per trade)")
    save(ax, "03_decomposition_baseline.png")

    # 4. league heatmaps from the saved grid
    defl = pd.read_csv(OUT / "league_deflated.csv")
    ax = F.plot_league_heatmap(defl, value="sharpe",
                               title="Best net Sharpe by tenor and rank pair (all rules)")
    save(ax, "04_league_sharpe.png")
    ax = F.plot_league_heatmap(defl, value="net_bp_per_trade",
                               title="Best net bp/trade by tenor and rank pair")
    save(ax, "05_league_net_bp.png")

    # 5. auction-cycle seasonality — pooled (the honest version) and best cell
    pooled = pd.read_csv(OUT / "auction_cycle_pooled.csv")
    g = (pooled.groupby("cycle_day")
         .apply(lambda d: pd.Series({
             "n": d["n"].sum(),
             "mean_pnl_bp": np.average(d["mean_pnl_bp"], weights=d["n"]),
         }), include_groups=False).reset_index())
    g["cum_mean_pnl_bp"] = g["mean_pnl_bp"].cumsum()
    ax = F.plot_auction_cycle(g, title="Auction-cycle seasonality, pooled over every long-old config")
    save(ax, "06_cycle_seasonality_pooled.png")
    ax = F.plot_cycle_cumulative(g)
    save(ax, "07_cycle_cumulative_pooled.png")

    cyc_best = A.auction_cycle_profile(res_best)
    ax = F.plot_auction_cycle(cyc_best, title="Auction-cycle seasonality — best cell (10Y OOO-vs-CT)")
    save(ax, "08_cycle_seasonality_best.png")

    # 6. calendar seasonality of the baseline (all-cycle book, no selection)
    seas = A.calendar_seasonality(res_base)
    fig = F.plot_calendar_seasonality(seas)
    save(fig, "09_calendar_seasonality_baseline.png")

    # 7. cost curve of the best cell
    cc = pd.read_csv(OUT / "cost_curve.csv")
    ax = F.plot_cost_curve(cc, title="Best cell — net bp/trade vs cost assumption (break-even ~2.0x)")
    save(ax, "10_cost_curve_best.png")

    # 8. the raw material: spread term structure + specialness
    ts = {t: A.spread_term_structure(panel, t) for t in TENORS}
    ts = {t: d for t, d in ts.items() if d is not None and not d.empty}
    ax = F.plot_spread_term_structure(ts)
    save(ax, "11_spread_term_structure.png")
    ax = F.plot_specialness(panel)
    save(ax, "12_specialness_by_rank.png")

    print(f"\nfigures -> {FIGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
