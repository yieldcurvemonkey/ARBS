"""Post-process a completed grid: deflate, run controls on the best cell, write the verdict.

Separate from run_grid_search.py so the 1,296-cell search does not have to be repeated when only
the reporting changes.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd

from RVUtils.BasisVsVol import grid as G
from RVUtils.BasisVsVol import strategy as ST
from RVUtils.BasisVsVol import surfaces as S
from RVUtils.BasisVsVol import voldata as V
from RVUtils.BasisVsVol.analytics import block_bootstrap_ci, regime_split
from RVUtils.BasisVsVol.run_grid_search import ALIVE, AXES, RESULTS


def main() -> int:
    vd = V.load(products=list(ST.DEFAULT_UNIVERSE))
    book = S.SurfaceBook(vd)
    grid = pd.read_csv(RESULTS / "grid_pooled.csv")
    cfgs = G.expand_grid(ST.StrategyConfig(require_on_support=True), **AXES)
    by_key = {c.key(): c for c in cfgs}

    ranked = grid.sort_values("sharpe", ascending=False)
    best_key = ranked.iloc[0]["key"]
    best_cfg = by_key[best_key]
    print(f"best cell: {best_key}\n", flush=True)

    cols = ["expiry_label", "offset_bps", "z_window", "entry_z", "exit_z", "max_hold_days",
            "rehedge_days", "n_trades", "mean_volbp", "hit_rate", "sharpe", "t_nw",
            "top3_share", "cost_over_gross"]
    print("=== top 10 by Sharpe ===", flush=True)
    print(ranked[cols].head(10).round(3).to_string(index=False), flush=True)

    best_daily, best_trades, best_diag = G.pool_products(vd, best_cfg, book=book)
    best_daily.to_csv(RESULTS / "best_daily.csv")
    best_trades.to_csv(RESULTS / "best_trades.csv", index=False)

    dfl = G.deflate_grid(grid, best_daily["pnl_volbp"])
    grid["dsr"] = np.nan
    grid.loc[grid["key"] == best_key, "dsr"] = dfl["dsr"]
    grid.to_csv(RESULTS / "grid_pooled.csv", index=False)
    print(f"\n=== deflation ===\n{json.dumps(dfl, indent=1, default=str)}", flush=True)

    ladder = G.cost_ladder(vd, best_cfg, book=book, mults=(0.0, 0.5, 1.0, 1.5, 2.0, 3.0))
    ladder.to_csv(RESULTS / "best_cost_ladder.csv", index=False)
    print("\n=== cost ladder ===", flush=True)
    print(ladder[["cost_mult", "n_trades", "mean_volbp", "hit_rate", "sharpe", "t_nw"]]
          .round(3).to_string(index=False), flush=True)

    plac = G.shuffled_signal_placebo(vd, best_cfg, book=book, n_draws=500)
    pct = float("nan")
    if not plac.empty:
        plac.to_csv(RESULTS / "best_placebo.csv", index=False)
        act = plac.attrs["actual_total"]
        pct = float((plac["total_volbp"] < act).mean())
        print(f"\n=== shuffled-signal placebo === actual {act:.2f} volbp, percentile {pct:.3f}",
              flush=True)

    mism = G.mismatched_pair_placebo(vd, best_cfg, book=book, wrong_tail="2Y", products=("US", "TY"))
    mism.to_csv(RESULTS / "best_mismatched_pair.csv", index=False)
    print("\n=== mismatched-pair placebo ===", flush=True)
    print(mism[["product", "tail", "pairing", "n_trades", "mean_volbp", "sharpe", "t_nw"]]
          .round(3).to_string(index=False), flush=True)

    reg = regime_split(best_daily)
    reg.to_csv(RESULTS / "best_regime.csv", index=False)
    print("\n=== regime split ===", flush=True)
    print(reg.round(3).to_string(index=False), flush=True)

    # sensitivity: lag the signal-driven exit as well as the entry
    from dataclasses import replace
    lag_daily, lag_trades, _ = G.pool_products(vd, replace(best_cfg, lag_exits=True), book=book)
    from RVUtils.BasisVsVol.analytics import summarize
    lag_s = summarize(lag_daily, lag_trades)
    print("\n=== lagged-exit sensitivity (best cell) ===", flush=True)
    print(f"  same-day exit: sharpe {ranked.iloc[0]['sharpe']:.3f}  "
          f"mean {ranked.iloc[0]['mean_volbp']:.3f} volbp", flush=True)
    print(f"  lagged exit  : sharpe {lag_s['sharpe']:.3f}  mean {lag_s['mean_volbp']:.3f} volbp",
          flush=True)

    lo, hi = block_bootstrap_ci(best_daily["pnl_volbp"], block=21, n_boot=2000)
    br = ranked.iloc[0]
    survives_2x = bool(
        not ladder.empty
        and float(ladder.loc[ladder["cost_mult"] == ALIVE["cost_mult_survive"], "sharpe"].iloc[0]) > 0)
    breakeven = ladder[ladder["sharpe"] > 0]["cost_mult"]
    verdict = {
        "best_key": best_key,
        "best_params": {k: getattr(best_cfg, k) for k in
                        ("expiry_label", "offset_bps", "z_window", "entry_z", "exit_z",
                         "max_hold_days", "rehedge_days", "require_on_support")},
        "sample": {"start": str(vd.dates().min().date()), "end": str(vd.dates().max().date()),
                   "n_days_union": int(len(vd.dates())), "products": vd.products()},
        "sharpe": float(br["sharpe"]),
        "t_nw": float(br["t_nw"]),
        "n_trades": int(br["n_trades"]),
        "mean_volbp": float(br["mean_volbp"]),
        "hit_rate": float(br["hit_rate"]),
        "top3_share": float(br["top3_share"]),
        "cost_over_gross": float(br["cost_over_gross"]),
        "sharpe_ci95": [lo, hi],
        "n_trials": int(dfl["n_trials"]),
        "expected_max_sharpe_null": float(dfl["expected_max_sharpe"]),
        "dsr": float(dfl["dsr"]),
        "placebo_percentile": pct,
        "breakeven_cost_mult": float(breakeven.max()) if len(breakeven) else 0.0,
        "survives_2x_costs": survives_2x,
        "lagged_exit_sharpe": float(lag_s["sharpe"]),
        "grid_median_sharpe": float(pd.to_numeric(grid["sharpe"], errors="coerce").median()),
        "grid_pct_positive": float((pd.to_numeric(grid["sharpe"], errors="coerce") > 0).mean()),
        "alive_criteria": ALIVE,
        "alive": bool(float(dfl["dsr"] or 0) > ALIVE["min_dsr"]
                      and float(br["top3_share"]) < ALIVE["max_top3_share"]
                      and survives_2x
                      and np.isfinite(pct) and pct > ALIVE["placebo_pct"]),
    }
    (RESULTS / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print("\n=== VERDICT ===", flush=True)
    print(json.dumps(verdict, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
