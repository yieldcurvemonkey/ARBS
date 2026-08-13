"""Full grid search for the V2 (exchange-vs-OTC vol) strategy, with controls.

Pre-registered before the run, so that the result is a test rather than a search:

* **Direction.** ``z < 0`` means the swaption is cheap relative to the futures option, so the
  position is long swaption vol / short futures-option vol. This sign is fixed in the code, not
  chosen after the fact.
* **Support.** Only configurations whose positions stay inside the quoted term structure are
  admissible. The 1M slot cannot satisfy this and is excluded: its apparent Sharpe of 1.94 is
  produced entirely below the shortest quoted node and inverts to -0.19 on support.
* **Sample.** Starts 2023-12-12. Before that the swaption smile is a flat fallback (NULL SABR,
  skew sd exactly 0.0000) and the ATM level steps 15.3bp at the seam.
* **Universe.** TU/FV/TY/TN/US. UL is excluded for data corruption, not for performance.
* **Kill conditions.** A cell is not alive unless it clears ALL of: deflated Sharpe > 0.95 against
  the full trial count; survival at 2x costs; a shuffled-signal placebo it beats at the 95th
  percentile; and a top-3-trade concentration below 0.6.

Outputs land in ``notebooks/backtests/basis_vs_vol/_results/``.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from RVUtils.BasisVsVol import grid as G
from RVUtils.BasisVsVol import strategy as ST
from RVUtils.BasisVsVol import surfaces as S
from RVUtils.BasisVsVol import voldata as V
from RVUtils.BasisVsVol.analytics import block_bootstrap_ci, regime_split

RESULTS = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_results"

# --- the pre-registered grid -------------------------------------------------
AXES = dict(
    expiry_label=["2M", "3M"],
    offset_bps=[-25.0, 0.0, 25.0],
    z_window=[63, 126, 252],
    entry_z=[1.0, 1.5, 2.0, 2.5],
    exit_z=[0.0, 0.5, 1.0],
    max_hold_days=[10, 21, 42],
    rehedge_days=[1, 5],
)

ALIVE = dict(min_dsr=0.95, max_top3_share=0.60, cost_mult_survive=2.0, placebo_pct=0.95)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    vd = V.load(products=list(ST.DEFAULT_UNIVERSE))
    book = S.SurfaceBook(vd)

    dq = V.data_quality_report(vd)
    dq.to_csv(RESULTS / "data_quality.csv", index=False)
    print(dq.to_string(index=False), flush=True)

    base = ST.StrategyConfig(require_on_support=True)
    cfgs = G.expand_grid(base, **AXES)
    print(f"\n{len(cfgs)} configurations x {len(ST.DEFAULT_UNIVERSE)} products", flush=True)

    # keep=False: holding 1,296 daily frames costs ~2GB and buys nothing -- the deflated
    # Sharpe needs the grid's Sharpe dispersion plus ONE daily series, which is re-run below.
    grid, _kept = G.run_pooled_grid(vd, cfgs, book=book, keep=False)
    grid.to_csv(RESULTS / "grid_pooled.csv", index=False)
    print(f"grid done in {time.time() - t0:.0f}s -> {len(grid)} rows", flush=True)

    num = pd.to_numeric(grid["sharpe"], errors="coerce")
    n_trials = int(num.notna().sum())
    sr_var = float(num.dropna().var(ddof=1))
    print(f"n_trials={n_trials}  sharpe var={sr_var:.4f}  "
          f"E[max SR]={G.expected_max_sharpe(n_trials, sr_var):.3f}", flush=True)

    ranked = grid.sort_values("sharpe", ascending=False)
    print("\n=== top 15 by Sharpe ===", flush=True)
    cols = ["expiry_label", "offset_bps", "z_window", "entry_z", "exit_z", "max_hold_days",
            "rehedge_days", "n_trades", "mean_volbp", "hit_rate", "sharpe", "t_nw", "dsr",
            "top3_share", "cost_over_gross"]
    print(ranked[cols].head(15).round(3).to_string(index=False), flush=True)

    # --- controls on the best cell ------------------------------------------
    best_key = ranked.iloc[0]["key"]
    best_cfg = next(c for c in cfgs if c.key() == best_key)
    best_daily, best_trades, best_diag = G.pool_products(vd, best_cfg, book=book)
    dfl = G.deflate_grid(grid, best_daily["pnl_volbp"])
    grid.loc[grid["key"] == best_key, "dsr"] = dfl["dsr"]
    grid.loc[grid["key"] == best_key, "expected_max_sharpe"] = dfl["expected_max_sharpe"]
    grid.to_csv(RESULTS / "grid_pooled.csv", index=False)
    ranked = grid.sort_values("sharpe", ascending=False)
    print(f"\ndeflation: {dfl}", flush=True)
    best_daily.to_csv(RESULTS / "best_daily.csv")
    best_trades.to_csv(RESULTS / "best_trades.csv", index=False)

    ladder = G.cost_ladder(vd, best_cfg, book=book)
    ladder.to_csv(RESULTS / "best_cost_ladder.csv", index=False)
    print("\n=== cost ladder (best cell) ===", flush=True)
    print(ladder[["cost_mult", "n_trades", "mean_volbp", "sharpe", "t_nw"]].round(3).to_string(index=False),
          flush=True)

    plac = G.shuffled_signal_placebo(vd, best_cfg, book=book, n_draws=500)
    if not plac.empty:
        plac.to_csv(RESULTS / "best_placebo.csv", index=False)
        act = plac.attrs["actual_total"]
        pct = float((plac["total_volbp"] < act).mean())
        print(f"\n=== shuffled-signal placebo === actual={act:.2f} volbp, "
              f"percentile vs 500 shuffles = {pct:.3f}", flush=True)
    else:
        pct = float("nan")

    mism = G.mismatched_pair_placebo(vd, best_cfg, book=book)
    mism.to_csv(RESULTS / "best_mismatched_pair.csv", index=False)
    print("\n=== mismatched-pair placebo ===", flush=True)
    print(mism[["product", "tail", "pairing", "n_trades", "mean_volbp", "sharpe", "t_nw"]]
          .round(3).to_string(index=False), flush=True)

    reg = regime_split(best_daily)
    reg.to_csv(RESULTS / "best_regime.csv", index=False)
    print("\n=== regime split (best cell) ===", flush=True)
    print(reg.round(3).to_string(index=False), flush=True)

    lo, hi = block_bootstrap_ci(best_daily["pnl_volbp"], block=21, n_boot=2000)
    br = ranked.iloc[0]
    verdict = {
        "best_key": best_key,
        "sharpe": float(br["sharpe"]),
        "dsr": float(dfl["dsr"]),
        "t_nw": float(br["t_nw"]),
        "n_trades": int(br["n_trades"]),
        "mean_volbp": float(br["mean_volbp"]),
        "top3_share": float(br["top3_share"]),
        "cost_over_gross": float(br["cost_over_gross"]),
        "sharpe_ci95": [lo, hi],
        "placebo_percentile": pct,
        "n_trials": n_trials,
        "alive_criteria": ALIVE,
        "alive": bool(
            float(dfl["dsr"] or 0) > ALIVE["min_dsr"]
            and float(br["top3_share"]) < ALIVE["max_top3_share"]
            and (not ladder.empty
                 and float(ladder.loc[ladder["cost_mult"] == ALIVE["cost_mult_survive"], "sharpe"].iloc[0]) > 0)
            and (np.isfinite(pct) and pct > ALIVE["placebo_pct"])
        ),
    }
    (RESULTS / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print("\n=== VERDICT ===", flush=True)
    print(json.dumps(verdict, indent=2, default=str), flush=True)
    print(f"\ntotal {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
