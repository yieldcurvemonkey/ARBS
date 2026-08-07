"""The pre-declared outcome-map grid: 360 configs, both directions, 3 linear legs.

    expression  {pair_raw, pair_odd, pair_odd_dev, map_full, reswin}   5
    dte band    {<=130, >130}                                          2
    threshold   {4pp, 8pp, 16pp} (= 1.0, 2.0, 4.0bp of premium)        3
    exit        {converge-half, hold-15}                               2
    linear leg  {none, zq, swap}                                       3
    direction   {fade, momentum}                                       2

plus the same grid re-run in each placebo world (Gaussian tree, wrong calendar).

Writes ``league.parquet`` (+ ``league_{real,p1,p2}.parquet``), the winner's
trade log and daily series, and a per-config daily-series store for NW t and
DSR. Costs are per contract per side (option half-tick 0.125bp, futures 0.25bp)
with the option and linear bills kept separate throughout — the study exists to
price the linear leg, so it is never folded into a single number.

Usage::

    conda run -n stir python notebooks/backtests/run_outcome_map_grid.py
"""
from __future__ import annotations

import itertools
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (REPO, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import outcome_map_common as omc                            # noqa: E402
from RVUtils.OutcomeMap import run_outcome_backtest         # noqa: E402
from RVUtils.SFRRVLab.stats import nw_tstat                 # noqa: E402
from MDP.STIRFutures._sofr_option_contracts import (        # noqa: E402
    sofr_option_last_trade_date)

DATA = REPO / "notebooks" / "data" / "outcome_map"
#: two bands about the panel's median dte; the third pre-declared band was
#: traded for a third THRESHOLD rung (see design amendment A5) because dte is
#: the least informative axis here — every map lives above 60 dte — while the
#: threshold is the axis that decides whether costs can be cleared at all
DTE_BANDS = ((0, 130), (130, 10_000))
#: a pair of butterflies is 8 contracts = 2.0bp round trip = 8pp of cell
#: probability, so the 4pp rung is BELOW break-even by arithmetic and is kept
#: only to measure the mechanism; 16pp is the first rung that can clear at 2x
THRESHOLDS_PP = (4.0, 8.0, 16.0)        # of cell probability; 1pp = 0.25bp
EXITS = ("converge", "hold")
LINEAR = ("none", "zq", "swap")
DIRECTIONS = ("fade", "momentum")
MAX_HOLD = 15
EXIT_FRAC = 0.5

t0 = time.time()


def thr_bp(pp: float) -> float:
    """A pp of cell probability is 0.25bp of butterfly premium (25bp scale)."""
    return pp * 0.25


def league_row(trades, cfg: dict) -> dict:
    row = dict(cfg)
    if not trades:
        row.update(n_trades=0, hit=np.nan, gross_bp=0.0, opt_gross_bp=0.0,
                   hedge_bp=0.0, opt_cost_bp=0.0, lin_cost_bp=0.0,
                   net_1x_bp=0.0, net_2x_bp=0.0, avg_net_1x_bp=np.nan,
                   t_stat=np.nan, nw_t=np.nan, sharpe=np.nan,
                   lin_contracts=np.nan, lin_cost_1leg_bp=0.0,
                   n_contracts=np.nan, hold_sessions=np.nan, converged=np.nan)
        return row
    gross = np.array([x.gross_bp for x in trades])
    net1 = np.array([x.net_at(1.0) for x in trades])
    net2 = np.array([x.net_at(2.0) for x in trades])
    daily = daily_series(trades)
    sd = daily.std(ddof=1)
    se = net1.std(ddof=1) / np.sqrt(len(net1)) if len(net1) > 1 else np.nan
    row.update(
        n_trades=len(trades), hit=float((net1 > 0).mean()),
        gross_bp=float(gross.sum()),
        opt_gross_bp=float(sum(x.opt_gross_bp for x in trades)),
        hedge_bp=float(sum(x.hedge_bp for x in trades)),
        opt_cost_bp=float(sum(x.opt_cost_bp for x in trades)),
        lin_cost_bp=float(sum(x.lin_cost_bp for x in trades)),
        net_1x_bp=float(net1.sum()), net_2x_bp=float(net2.sum()),
        avg_net_1x_bp=float(net1.mean()),
        t_stat=float(net1.mean() / se) if se and se > 0 else np.nan,
        nw_t=float(nw_tstat(daily.to_numpy())),
        sharpe=float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan,
        lin_contracts=float(np.mean([x.lin_contracts for x in trades])),
        # the FedWatch basket spends 3 ZQ legs per meeting; a hedger willing to
        # carry the bracketing-month residual would spend 1. Disclosed so the
        # linear leg's verdict is not an artefact of that inherited convention.
        lin_cost_1leg_bp=float(sum(x.lin_cost_bp for x in trades) / 3.0),
        n_contracts=float(np.mean([x.n_contracts for x in trades])),
        hold_sessions=float(np.mean([len(x.daily) for x in trades])),
        converged=float(np.mean([x.exit_reason == "converged"
                                 for x in trades])),
    )
    return row


def daily_series(trades) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    s = pd.concat([x.daily for x in trades])
    return s.groupby(level=0).sum().sort_index()


def run_world(ctx, panel: pd.DataFrame, tag: str, jump_fns: dict) -> tuple:
    """Every config in one world (real / P1 / P2)."""
    b_bar = omc.trailing_tilt(panel)
    frames = {e: omc.signal_frame(ctx, panel, e, b_bar=b_bar)
              for e in omc.EXPRESSIONS}
    for e, f in frames.items():
        print(f"  [{tag}] {e}: {len(f)} signals", flush=True)
    sig_fns = {m: omc.make_signal_fn(ctx, panel, m, b_bar)
               for m in ("raw", "odd", "odd_dev")}
    hedge_fn = omc.make_hedge_ctx_fn(ctx)
    mark = ctx.mark_any

    rows, store = [], {}
    combos = list(itertools.product(omc.EXPRESSIONS, DTE_BANDS, THRESHOLDS_PP,
                                    EXITS, LINEAR, DIRECTIONS))
    for i, (expr, band, pp, exitr, lin, dirn) in enumerate(combos):
        ent = frames[expr]
        if len(ent):
            ent = ent[(ent["dte"] > band[0]) & (ent["dte"] <= band[1])]
        exit_rule = "decision" if expr == "reswin" else exitr
        trades = run_outcome_backtest(
            ent, mark, sig_fns[omc.SIGNAL_MODE[expr]], ctx.dates,
            direction=dirn, threshold_bp=thr_bp(pp), exit_rule=exit_rule,
            exit_frac=EXIT_FRAC, max_hold=MAX_HOLD, linear_leg=lin,
            hedge_ctx_fn=hedge_fn, jump_fn=jump_fns.get(lin),
            expiry_fn=sofr_option_last_trade_date,
            decision_after_fn=ctx.next_decision)
        cfg = dict(world=tag, expression=expr, dte=f"{band[0]}-{band[1]}",
                   thr_pp=pp, exit=exitr, linear=lin, direction=dirn)
        rows.append(league_row(trades, cfg))
        store[len(rows) - 1] = trades
        if (i + 1) % 60 == 0:
            print(f"  [{tag}] {i + 1}/{len(combos)} configs "
                  f"({time.time() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows), store


def main() -> int:
    print("loading context...", flush=True)
    ctx = omc.Context()
    panel = pd.read_parquet(DATA / "cells.parquet")
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    zq = pd.read_parquet(DATA / "jumps_zq.parquet")
    zq["as_of"] = pd.to_datetime(zq["as_of"])
    jump_fns = {"zq": omc.jump_lookup(zq)}
    swap_path = DATA / "jumps_swap.parquet"
    if swap_path.exists():
        sw = pd.read_parquet(swap_path)
        sw["as_of"] = pd.to_datetime(sw["as_of"])
        jump_fns["swap"] = omc.jump_lookup(sw, drop_first=True)
    else:
        print("!! no swap panel: the swap leg will mark flat", flush=True)
        jump_fns["swap"] = lambda ts, e: np.nan
    print(f"context + panels ready ({time.time() - t0:.0f}s)", flush=True)

    real, store = run_world(ctx, panel, "real", jump_fns)
    real.to_parquet(DATA / "league_real.parquet", index=False)
    print(f"real: {len(real)} configs, best net1x "
          f"{real['net_1x_bp'].max():+.1f}bp ({time.time() - t0:.0f}s)",
          flush=True)

    # per-config daily series (NW t, DSR, halves) and the winner's trade log
    dailies = {i: daily_series(tr) for i, tr in store.items()}
    with open(DATA / "dailies_real.pkl", "wb") as fh:
        pickle.dump(dailies, fh)
    recs = []
    for i, tr in store.items():
        for x in tr:
            recs.append({
                "config": i, "world": "real", "expression": x.expression,
                "symbol": x.symbol, "entry": x.entry, "exit": x.exit,
                "side": x.side, "n_contracts": x.n_contracts,
                "entry_signal_bp": x.entry_signal_bp,
                "exit_signal_bp": x.exit_signal_bp,
                "opt_gross_bp": x.opt_gross_bp, "hedge_bp": x.hedge_bp,
                "opt_cost_bp": x.opt_cost_bp, "lin_cost_bp": x.lin_cost_bp,
                "lin_contracts": x.lin_contracts, "gross_bp": x.gross_bp,
                "net_1x_bp": x.net_at(1.0), "net_2x_bp": x.net_at(2.0),
                "exit_reason": x.exit_reason, "n_rebalances": x.n_rebalances,
            })
    pd.DataFrame(recs).to_parquet(DATA / "trades_real.parquet", index=False)

    leagues = [real]
    for tag, path, ctx_fn in (
            ("p1_gauss", DATA / "cells_p1.parquet", omc.gaussian_context),
            ("p2_calendar", DATA / "cells_p2.parquet", omc.shifted_context)):
        if not path.exists():
            print(f"!! missing {path.name}: placebo {tag} skipped", flush=True)
            continue
        pl = pd.read_parquet(path)
        pl["as_of"] = pd.to_datetime(pl["as_of"])
        pctx = ctx_fn(ctx)
        pj = dict(jump_fns)
        if tag == "p2_calendar":
            from linvol_grid_common import shifted_ladders
            lad = shifted_ladders(ctx.tree.ladders)
            pj["zq"] = omc.jump_lookup(pd.DataFrame(
                [{"as_of": pd.Timestamp(d), "effective": m.effective,
                  "jump_bp": float(m.jump_bp)}
                 for d, l in lad.items() for m in l]))
            pj["swap"] = pj["zq"]
        df, _ = run_world(pctx, pl, tag, pj)
        df.to_parquet(DATA / f"league_{tag}.parquet", index=False)
        leagues.append(df)
        print(f"{tag}: best net1x {df['net_1x_bp'].max():+.1f}bp "
              f"({time.time() - t0:.0f}s)", flush=True)

    league = pd.concat(leagues, ignore_index=True)
    league.to_parquet(DATA / "league.parquet", index=False)
    print(f"LEAGUE {len(league)} rows in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
