"""Which configuration, across every search in this study, has the best Sharpe.

Four searches ran with different cost conventions and different P&L columns, so
comparing their leaderboards side by side would compare gross against net. This
puts all ~14,000 cells on one basis:

    net bp per trade  = gross bp per trade - one round-trip tick for that contract
    Sharpe per trade  = net bp / per-trade standard deviation
    annualised Sharpe = Sharpe per trade * sqrt(trades per year)

Two warnings that belong next to the answer rather than under it.

**The best of 14,000 cells is an order statistic.** Its Sharpe is the maximum of
a distribution, not a draw from it, and every correction in
``RVUtils.StatisticalFinance`` exists to price that. They are reported here.

**Annualisation punishes and rewards frequency, not skill.** A cell trading five
times a year with a Sharpe of 0.3 per trade annualises to 0.67; one trading 150
times at 0.05 per trade annualises to 0.61. Those are very different businesses
and the ranking cannot tell them apart, so trades per year is a column.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent))

import numpy as np
import pandas as pd

import econ_fade_common as G

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

CACHE = G.CACHE
SPAN_YEARS = (pd.Timestamp("2026-08-07") - pd.Timestamp("2019-01-03")).days / 365.25

#: One round-trip tick, in bp of rate, per contract. tick_size / price-points-per-bp.
#: SR3 and ZQ are quoted as 100 - rate so a half-tick is 0.25bp and the round trip
#: is 0.5. The UST numbers come from the measured DV01 table.
TICK_BP = {"USD_STIR": 0.5, "SR3": 0.5, "GE": 0.5, "ZQ": 0.5,
           "TU": 0.223, "FV": 0.183, "TY": 0.239, "US": 0.245}


def _tick_for(name: str) -> float:
    n = str(name)
    for key in ("SR3", "ZQ", "TU", "FV", "TY", "US"):
        if key in n:
            return TICK_BP[key]
    return 0.5


def _annualise(net_bp, sd, trades):
    """Sharpe per trade and annualised, from a net mean and a per-trade sd."""
    with np.errstate(divide="ignore", invalid="ignore"):
        srt = np.where(sd > 0, net_bp / sd, np.nan)
        tpy = trades / SPAN_YEARS
        return srt, srt * np.sqrt(tpy), tpy


def load_all() -> pd.DataFrame:
    frames = []

    # --- searches whose avg_bp is GROSS: charge the tick here ---------------
    for fn, label, name_col in (("grid_results.csv", "grid search", "instrument"),
                                ("paramsearch_real.csv", "parameter search", "config")):
        p = CACHE / fn
        if not p.exists():
            continue
        d = pd.read_csv(p)
        d = d[d["trades"].fillna(0) >= 30].copy()
        # sd is recovered from the gross mean and its per-trade Sharpe, which is
        # scale-free -- charging a cost shifts the mean and leaves sd alone.
        sd = np.where(d["sr_per_trade"].abs() > 1e-12,
                      d["avg_bp"] / d["sr_per_trade"], np.nan)
        tick = np.array([_tick_for(x) for x in d[name_col].astype(str)])
        net = d["avg_bp"] - tick
        srt, ann, tpy = _annualise(net, sd, d["trades"])
        frames.append(pd.DataFrame({
            "search": label, "config": d["config"], "trades": d["trades"],
            "gross_bp": d["avg_bp"], "tick_bp": tick, "net_bp": net,
            "hit_rate": d.get("hit_rate"), "sr_per_trade": srt,
            "ann_sharpe": ann, "trades_per_year": tpy}))

    # --- searches whose net_bp is already NET -------------------------------
    for fn, label in (("cpi_ty_exit_search_real.csv", "CPI x TY brackets"),
                      ("surprise_ty_real.csv", "consensus surprise")):
        p = CACHE / fn
        if not p.exists():
            continue
        d = pd.read_csv(p)
        d = d[d["trades"].fillna(0) >= 30].copy()
        sd = np.where(d["sr_per_trade"].abs() > 1e-12,
                      d["net_bp"] / d["sr_per_trade"], np.nan)
        srt, ann, tpy = _annualise(d["net_bp"], sd, d["trades"])
        frames.append(pd.DataFrame({
            "search": label, "config": d["config"], "trades": d["trades"],
            "gross_bp": d.get("gross_bp"), "tick_bp": 0.239, "net_bp": d["net_bp"],
            "hit_rate": d["hit_rate"], "sr_per_trade": srt,
            "ann_sharpe": ann, "trades_per_year": tpy}))

    out = pd.concat(frames, ignore_index=True)
    return out[np.isfinite(out["ann_sharpe"])].reset_index(drop=True)


def main():
    all_cells = load_all()
    print(f"{len(all_cells):,} cells with >= 30 trades, across "
          f"{all_cells.search.nunique()} searches, all net of one round-trip tick")
    print(all_cells.groupby("search").agg(
        cells=("ann_sharpe", "size"), median_ann=("ann_sharpe", "median"),
        best_ann=("ann_sharpe", "max"), median_net=("net_bp", "median"),
        pct_net_positive=("net_bp", lambda s: float((s > 0).mean()))).round(4).to_string())

    cols = ["search", "config", "trades", "trades_per_year", "gross_bp", "tick_bp",
            "net_bp", "hit_rate", "sr_per_trade", "ann_sharpe"]
    print("\n=== TOP 25 by ANNUALISED Sharpe, net of cost ===")
    print(all_cells.sort_values("ann_sharpe", ascending=False).head(25)[cols]
          .round(4).to_string(index=False))

    print("\n=== TOP 15 by Sharpe PER TRADE (frequency-neutral) ===")
    print(all_cells.sort_values("sr_per_trade", ascending=False).head(15)[cols]
          .round(4).to_string(index=False))

    print("\n=== how many cells clear each annualised Sharpe, by search ===")
    rows = []
    for s, g in all_cells.groupby("search"):
        rows.append({"search": s, "cells": len(g),
                     **{f"ann>{t}": int((g.ann_sharpe > t).sum()) for t in (0, 0.25, 0.5, 1.0)}})
    print(pd.DataFrame(rows).set_index("search").to_string())

    all_cells.sort_values("ann_sharpe", ascending=False).to_csv(
        CACHE / "best_sharpe_league.csv", index=False)
    print(f"\nwrote {CACHE / 'best_sharpe_league.csv'}")


if __name__ == "__main__":
    main()
