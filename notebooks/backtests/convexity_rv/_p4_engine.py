r"""Engine certification: re-price every reported book on DATED instruments.

The panel decides WHEN; the engine says what it was worth.  Each declared cell's
episodes are replayed through ``QueryDrivenBacktest`` as the real package the
note describes -- four SR3 contracts, a matched-maturity quarterly/quarterly
swap, and a spot 2s5s10s fly at the fitted weights, re-struck at each quarterly
refit inside the hold -- with ``assert_ran`` afterwards, because ``run()``
swallows exceptions and a failed backtest looks like a flat equity curve.

Reported per cell: the engine total and Sharpe, the panel total and Sharpe, the
daily-change correlation between the two, and the carry/residual split.  Where
they disagree the ENGINE is the number and the gap is named.

Usage:  _p4_engine.py [cell_id ...]      (default: the certification set below)

Output: notebooks/data/convexity_rv/p4_engine_{stats,equity}.parquet + json
"""
from __future__ import annotations

import datetime
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
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

from RVUtils.ConvexityRV import citi_engine as CE  # noqa: E402
from RVUtils.ConvexityRV import citi_rule as R  # noqa: E402
from RVUtils.ConvexityRV import citi_screen as SC  # noqa: E402
from RVUtils.ConvexityRV.gv_sizing import ca_theta_bp_per_year  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
S = SC.build_screen(P)
SPAN = float(json.loads((DATA / "p4_preflight.json").read_text())
             ["span_tradeable_years"])
ANN = 252.0

#: The certification set: the headline, every hedge scheme at the rung that
#: trades, both selection rules, and both secondary cells.  Declared here rather
#: than picked by result.
DEFAULT_CELLS = [
    "P|z2.0|screen_best|fitted_refit",          # the headline
    "P|z2.0|blues|fitted_refit",
    "P|z1.0|screen_best|fitted_refit",
    "P|z1.0|screen_best|fitted_frozen",
    "P|z1.0|screen_best|citi_2017",
    "P|z1.0|screen_best|unhedged",
    "P|z1.0|blues|fitted_refit",
    "S|z1.0|screen_best_all5|fitted_refit",
    "S|z1.0|screen_best_all5|citi_2017",
]
WANT = sys.argv[1:] or DEFAULT_CELLS
BY_ID = {c.cell_id: c for c in R.declared_cells()}


def _sharpe(d: pd.Series) -> float:
    d = pd.Series(d).astype(float)
    if len(d[d != 0.0]) < 3 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * np.sqrt(ANN))


def hedge_path(ep, ctx, cfg):
    """``[(struck_date, beta, w2, w10), ...]`` for one episode.

    The hedge that is ON is the one in force at the mark the position was
    filled at; a re-strike inside ``(entry_fill, exit_fill]`` adds one entry.
    ``fitted_frozen`` and ``unhedged`` never re-strike, by construction.
    """
    if cfg.hedge == "unhedged":
        return []
    e = ep.entry_fill.date()
    path = [(e, float(ep.beta_entry), float(ep.w2_entry), float(ep.w10_entry))]
    if cfg.hedge == "fitted_frozen":
        return path
    for d in ctx.restrike_dates:
        if ep.entry_fill < d <= ep.exit_fill:
            path.append((d.date(), float(ctx.beta.get(d, np.nan)),
                         float(ctx.w2.get(d, np.nan)),
                         float(ctx.w10.get(d, np.nan))))
    return [p for p in path if np.isfinite(p[1])]


rows, eq_cols, prov = [], {}, {}
for cid in WANT:
    spec = BY_ID.get(cid)
    if spec is None:
        print(f"!! {cid} is not a declared cell -- skipped")
        continue
    t0 = time.time()
    cfg = spec.config()
    ctx = R.build_contexts(P, S, cfg)
    eps = R.episodes_from_contexts(ctx, cfg, panel=P)
    print(f"\n{'=' * 78}\n{cid}   {len(eps)} episodes\n{'=' * 78}")
    if not eps:
        print("  no episodes -- nothing to certify")
        rows.append({"cell_id": cid, "n_episodes": 0})
        continue

    specs, fees = [], {}
    for ep in eps:
        hp = hedge_path(ep, ctx[ep.structure], cfg)
        sp = CE.spec_from_episode(
            structure=ep.structure, side=ep.side, entry=ep.entry_fill.date(),
            exit=ep.exit_fill.date(), ca_dv01=ep.ca_dv01, hedge_path=hp)
        specs.append(sp)
        fees[sp.tag] = (R.FUT_RT_BP + R.SWAP_RT_BP) * ep.ca_dv01
        for i, seg in enumerate(sp.fly_segments):
            fees[sp.fly_tag(i)] = R.LEG_RT_BP * seg.charged_dv01
        print(f"  {ep.structure:7s} {ep.entry_fill.date()} -> "
              f"{ep.exit_fill.date()}  {len(sp.fly_segments)} fly segment(s), "
              f"beta {ep.beta_entry:+.4f}, exit {ep.exit_reason}")

    lo = min(s.entry for s in specs)
    hi = max(s.exit for s in specs)
    grid = P.index[(P.index >= pd.Timestamp(lo) - pd.Timedelta(days=7))
                   & (P.index <= pd.Timestamp(hi) + pd.Timedelta(days=7))]
    bt = CE.run_backtest(specs, grid, show_progress=False)
    eq = CE.assert_ran(bt, specs, expect_days=len(grid))
    daily = eq.diff().fillna(0.0)
    closed = bt.portfolio.closed_positions_log
    print(f"  engine: {len(grid)} marks, {len(closed)} closed positions, "
          f"end equity ${float(eq.iloc[-1]):,.0f}   ({time.time() - t0:.0f}s)")

    # gross fee total, so the engine's NET can be quoted against the panel's
    fee_total = float(sum(fees.values()))
    panel_gross = R.book_daily(eps, ctx, cfg, index=P.index, cost_mult=0.0)
    panel_net = R.book_daily(eps, ctx, cfg, index=P.index, cost_mult=1.0)
    pg = panel_gross.reindex(grid).fillna(0.0)
    corr = float(pd.concat([daily.rename("e"), pg.rename("p")],
                           axis=1).dropna().corr().iloc[0, 1])
    theta = {lab: ca_theta_bp_per_year(P[SC.VOL_COL[lab]].astype(float),
                                       P[f"{lab.lower()}_t1mean"].astype(float))
             / 252.0 for lab in SC.SCREEN_STRUCTURES}
    carry = 0.0
    for ep in eps:
        p = R.episode_daily_pnl(ep, ctx[ep.structure], cfg)
        carry += float(cfg.side) * float(theta[ep.structure].reindex(p.index)
                                         .sum()) * float(ep.ca_dv01)

    row = {
        "cell_id": cid, "n_episodes": len(eps),
        "n_closed_positions": len(closed), "n_marks": len(grid),
        "engine_gross_usd": float(eq.iloc[-1]) + fee_total,
        "engine_net_usd": float(eq.iloc[-1]),
        "engine_sharpe_net": _sharpe(daily),
        "panel_gross_usd": float(panel_gross.sum()),
        "panel_net_usd": float(panel_net.sum()),
        "panel_sharpe_gross": _sharpe(panel_gross),
        "panel_sharpe_net": _sharpe(panel_net),
        "fee_total_usd": fee_total,
        "daily_corr_engine_panel": corr,
        "carry_usd": carry,
        "engine_residual_usd": float(eq.iloc[-1]) + fee_total - carry,
        "elapsed_s": round(time.time() - t0, 1),
    }
    rows.append(row)
    eq_cols[cid] = eq
    print(f"  panel gross ${row['panel_gross_usd']:>13,.0f}   "
          f"engine gross ${row['engine_gross_usd']:>13,.0f}   "
          f"ratio {row['engine_gross_usd'] / row['panel_gross_usd']:+.2f}"
          if row["panel_gross_usd"] else "  panel gross 0")
    print(f"  panel net   ${row['panel_net_usd']:>13,.0f}   "
          f"engine net   ${row['engine_net_usd']:>13,.0f}")
    print(f"  daily-change corr(engine, panel) {corr:+.4f}   "
          f"carry ${carry:,.0f}  residual ${row['engine_residual_usd']:,.0f}")

CERT = pd.DataFrame(rows)
print("\n" + "=" * 78)
print("ENGINE CERTIFICATION -- the engine number is the one quoted")
print("=" * 78)
print(CERT.round(4).to_string(index=False))

CERT.to_parquet(DATA / "p4_engine_stats.parquet")
if eq_cols:
    pd.DataFrame(eq_cols).to_parquet(DATA / "p4_engine_equity.parquet")
(DATA / "p4_engine_meta.json").write_text(json.dumps({
    "cells": WANT, "span_tradeable_years": SPAN,
    "cost_convention": {"fut_rt_bp": R.FUT_RT_BP, "swap_rt_bp": R.SWAP_RT_BP,
                        "leg_rt_bp": R.LEG_RT_BP},
    "note": "exits are decided on panel marks and the engine replays those "
            "exact dates; QueryDrivenBacktest takes precomputed DateTriggers "
            "so an in-engine dollar stop is not expressible",
}, indent=1))
print(f"\nwrote {DATA / 'p4_engine_stats.parquet'}")
