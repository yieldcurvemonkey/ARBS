r"""Score the 23 declared cells of the Citi-framework pre-registration.

Frozen list: ``docs/convexityrv/citi-framework-preregistration.md`` §7, committed
before this ran.  The panel is a signal tool and produces the DECISION DATES and
the shape; every book worth reporting is then re-priced through
``QueryDrivenBacktest`` by ``_p4_engine.py`` and the engine number is the one
quoted.

Outputs (notebooks/data/convexity_rv/):
  p4_grid_stats.parquet      one row per declared cell
  p4_grid_episodes.parquet   every episode of every cell
  p4_grid_returns.parquet    daily P&L per cell at 1x cost
  p4_grid_binding.parquet    per-condition refusal rates per cell
  p4_grid_meta.json          window, span, null bars, provenance
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 200)

from RVUtils.ConvexityRV import citi_rule as R  # noqa: E402
from RVUtils.ConvexityRV import citi_screen as SC  # noqa: E402
from RVUtils.ConvexityRV.gv_sizing import ca_theta_bp_per_year  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
S = SC.build_screen(P)
PRE = json.loads((DATA / "p4_preflight.json").read_text())
SPAN = float(PRE["span_tradeable_years"])
print(f"panel {P.shape}  tradeable span {SPAN:.3f} y from {PRE['first_defined']}")

THETA = {lab: ca_theta_bp_per_year(P[SC.VOL_COL[lab]].astype(float),
                                   P[f"{lab.lower()}_t1mean"].astype(float)) / 252.0
         for lab in SC.SCREEN_STRUCTURES}

CELLS = R.declared_cells()
print(f"{len(CELLS)} declared cells\n")

t0 = time.time()
results, ep_rows, ret_cols, bind_rows = [], [], {}, []
for i, spec in enumerate(CELLS):
    r = R.run_cell(spec, P, S, theta_bp_per_bd=THETA)
    results.append(r)
    ret_cols[spec.cell_id] = r.daily_by_mult[1.0]
    for e in r.episodes:
        ep_rows.append({
            "cell_id": spec.cell_id, "structure": e.structure,
            "entry_decision": e.entry_decision, "entry_fill": e.entry_fill,
            "exit_decision": e.exit_decision, "exit_fill": e.exit_fill,
            "hold_bd": e.hold_bd, "side": e.side, "ca_dv01": e.ca_dv01,
            "beta_entry": e.beta_entry, "w2_entry": e.w2_entry,
            "w10_entry": e.w10_entry, "exit_reason": e.exit_reason,
            "z_model": e.z_model, "z_fly": e.z_fly, "rich_bp": e.rich_bp,
            "impl_rlzd": e.impl_rlzd, "z_pos": e.z_pos,
            "n_restrikes": e.n_restrikes,
            "gross_usd": float(R.episode_daily_pnl(
                e, R.build_contexts(P, S, r.cfg,
                                    structures=[e.structure])[e.structure],
                r.cfg).sum()),
        })
    if r.binding is not None:
        b = r.binding.reset_index()
        b.insert(0, "cell_id", spec.cell_id)
        bind_rows.append(b)
    print(f"  [{i + 1:2d}/{len(CELLS)}] {spec.cell_id:42s} "
          f"episodes {r.n_episodes:3d}  net1x ${r.daily_by_mult[1.0].sum():>12,.0f}")

STATS = R.stats_frame(results, span_years=SPAN)
EPS = pd.DataFrame(ep_rows)
RET = pd.DataFrame(ret_cols, index=P.index)
BIND = pd.concat(bind_rows, ignore_index=True) if bind_rows else pd.DataFrame()

print(f"\nscored in {time.time() - t0:.0f}s\n")

NB = {str(n): R.null_bars(n, n_eff=float(np.nanmedian(STATS["n_eff"]))
                          if STATS["n_eff"].notna().any() else 6.0,
                          span_years=SPAN)
      for n in (1, 2, 16, 23)}
print("E[max SR | null] at the declared trial count, tradeable span "
      f"{SPAN:.3f} y, n_eff = median over cells:")
for k, v in NB.items():
    print(f"  {k:>4s} trials   annualised {v['emax_annualised']:.4f}   "
          f"per-hold {v['emax_perhold']:.4f}")
BAR = NB["23"]["emax_annualised"]

cols = ["cell_id", "tier", "headline", "hedge", "selection", "n_conditions",
        "n_episodes", "mean_hold_bd", "n_eff", "hit_rate", "mean_abs_beta",
        "n_restrikes", "exit_target", "exit_stop", "exit_max_hold",
        "exit_end_of_sample", "net_0.0", "sharpe_0.0", "net_1.0", "sharpe_1.0",
        "net_2.0", "sharpe_2.0", "breakeven_bp", "carry_usd", "residual_usd",
        "carry_share"]
print("\n" + "=" * 78)
print("THE DECLARED GRID")
print("=" * 78)
print(STATS[cols].round(4).to_string(index=False))

STATS["alive_1x"] = STATS["sharpe_1.0"] > BAR
alive = STATS[STATS["alive_1x"].fillna(False)]
print(f"\ncells clearing the {BAR:.4f} annualised bar at 1x costs: "
      f"{len(alive)} of {len(STATS)}")
if len(alive):
    print(alive[["cell_id", "n_episodes", "sharpe_0.0", "sharpe_1.0",
                 "carry_share"]].round(4).to_string(index=False))

head = STATS[STATS["headline"]]
print("\n" + "=" * 78)
print("THE HEADLINE -- the note's own trade at the note's own thresholds")
print("=" * 78)
print(head[cols].T.to_string())

STATS.to_parquet(DATA / "p4_grid_stats.parquet")
if len(EPS):
    EPS.to_parquet(DATA / "p4_grid_episodes.parquet")
RET.to_parquet(DATA / "p4_grid_returns.parquet")
if len(BIND):
    BIND.to_parquet(DATA / "p4_grid_binding.parquet")
(DATA / "p4_grid_meta.json").write_text(json.dumps({
    "window": [str(P.index.min().date()), str(P.index.max().date())],
    "n_dates": int(len(P)),
    "span_tradeable_years": SPAN,
    "first_defined": PRE["first_defined"],
    "n_cells": len(CELLS),
    "null_bars": NB,
    "bar_annualised_23": BAR,
    "n_alive_1x": int(len(alive)),
    "elapsed_s": round(time.time() - t0, 1),
    "preregistration": "docs/convexityrv/citi-framework-preregistration.md",
}, indent=1))
print(f"\nwrote {DATA / 'p4_grid_stats.parquet'} and four siblings")
