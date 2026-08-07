"""The pre-declared vol-vs-vol grid: 128 configs, both directions, 3 worlds.

    signal      {map_odd, calendar}                       2
    lambda      {none(0), one(1), tree, empirical}        4
    dte band    {<=130, >130}                             2
    threshold   {8pp, 16pp}                               2
    exit        {converge-half, hold-15}                  2
    direction   {fade, momentum}                          2

`map_odd` trades the outcome-map signal and uses the adjacent expiry as a HEDGE,
so `lambda=none` must reproduce the prior study's unhedged row exactly — that is
the control. `calendar` trades the cross-expiry residual itself, where lambda
defines the structure rather than hedging it, so `none` is meaningless and is
recorded as skipped rather than silently merged into `one`.

Usage::

    conda run -n stir python notebooks/backtests/run_volvol_grid.py
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

import outcome_map_common as omc                           # noqa: E402
import outcome_map_calendar_common as cal                  # noqa: E402
from RVUtils.OutcomeMap import run_outcome_backtest        # noqa: E402
from RVUtils.SFRRVLab.stats import nw_tstat                # noqa: E402
from MDP.STIRFutures._sofr_option_contracts import (       # noqa: E402
    sofr_option_last_trade_date)

DATA = REPO / "notebooks" / "data" / "outcome_map"
OUT = REPO / "notebooks" / "data" / "volvol"
DTE_BANDS = ((0, 130), (130, 10_000))
THRESHOLDS_PP = (8.0, 16.0)
EXITS = ("converge", "hold")
DIRECTIONS = ("fade", "momentum")
MAX_HOLD = 15
EXIT_FRAC = 0.5

t0 = time.time()


def thr_bp(pp: float) -> float:
    return pp * 0.25


def daily_series(trades) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    return pd.concat([x.daily for x in trades]).groupby(level=0).sum().sort_index()


def league_row(trades, cfg: dict) -> dict:
    row = dict(cfg)
    if not trades:
        row.update(n_trades=0, hit=np.nan, gross_bp=0.0, cost_bp=0.0,
                   net_1x_bp=0.0, net_2x_bp=0.0, per_trade_gross=np.nan,
                   per_trade_cost=np.nan, per_trade_std=np.nan, nw_t=np.nan,
                   sharpe=np.nan, n_contracts=np.nan, hold_sessions=np.nan,
                   converged=np.nan, lam_abs=np.nan)
        return row
    g = np.array([x.gross_bp for x in trades])
    c = np.array([x.opt_cost_bp + x.lin_cost_bp for x in trades])
    d = daily_series(trades)
    sd = d.std(ddof=1)
    row.update(
        n_trades=len(trades), hit=float(((g - c) > 0).mean()),
        gross_bp=float(g.sum()), cost_bp=float(c.sum()),
        net_1x_bp=float((g - c).sum()), net_2x_bp=float((g - 2 * c).sum()),
        per_trade_gross=float(g.mean()), per_trade_cost=float(c.mean()),
        per_trade_std=float(g.std(ddof=1)) if len(g) > 1 else np.nan,
        nw_t=float(nw_tstat(d.to_numpy())),
        sharpe=float(d.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan,
        n_contracts=float(np.mean([x.n_contracts for x in trades])),
        hold_sessions=float(np.mean([len(x.daily) for x in trades])),
        converged=float(np.mean([x.exit_reason == "converged"
                                 for x in trades])),
        lam_abs=float(np.mean([abs(x.meta.get("lam_used", np.nan))
                               for x in trades])),
    )
    return row


def run_world(ctx, panel, tag: str) -> tuple:
    b_bar = omc.trailing_tilt(panel)
    base = omc.signal_frame(ctx, panel, "pair_odd_dev", b_bar=b_bar)
    cf = cal.calendar_frame(ctx, panel, base)
    print(f"  [{tag}] base {len(base)} -> calendar {len(cf)} "
          f"({time.time() - t0:.0f}s)", flush=True)
    if cf.empty:
        return pd.DataFrame(), {}

    oriented = {m: cal.orient_calendar(cf, ctx, panel, m, b_bar=b_bar)
                for m in ("one", "tree", "emp")}
    rows, store = [], {}
    combos = list(itertools.product(cal.CAL_SIGNALS, cal.CAL_LAMBDAS,
                                    DTE_BANDS, THRESHOLDS_PP, EXITS,
                                    DIRECTIONS))
    for i, (sig, lam_mode, band, pp, exitr, dirn) in enumerate(combos):
        cfg = dict(world=tag, signal=sig, lam=lam_mode,
                   dte=f"{band[0]}-{band[1]}", thr_pp=pp, exit=exitr,
                   direction=dirn)
        if sig == "calendar" and lam_mode == "none":
            rows.append(league_row([], {**cfg, "skipped": True}))
            store[len(rows) - 1] = []
            continue
        ent = cf if sig == "map_odd" else oriented[lam_mode]
        ent = ent[(ent["dte"] > band[0]) & (ent["dte"] <= band[1])]
        # a config can only trade rows whose ratio exists and is affordable
        if lam_mode in ("tree", "emp"):
            col = "lam_tree" if lam_mode == "tree" else "lam_emp"
            ent = ent[ent[col].notna() & (ent[col].abs() <= 3.0)]
        if len(ent):
            ent = ent.assign(lam_used=[cal.resolve_lambda(r, lam_mode)
                                       for _, r in ent.iterrows()])
        trades = run_outcome_backtest(
            ent, cal.make_calendar_mark_fn(ctx, lam_mode),
            cal.make_calendar_signal_fn(ctx, panel, sig, lam_mode, b_bar=b_bar),
            ctx.dates, direction=dirn, threshold_bp=thr_bp(pp),
            exit_rule=exitr, exit_frac=EXIT_FRAC, max_hold=MAX_HOLD,
            contracts_fn=cal.make_calendar_contracts_fn(lam_mode),
            expiry_fn=sofr_option_last_trade_date,
            decision_after_fn=ctx.next_decision)
        rows.append(league_row(trades, {**cfg, "skipped": False}))
        store[len(rows) - 1] = trades
        if (i + 1) % 32 == 0:
            print(f"  [{tag}] {i + 1}/{len(combos)} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows), store


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = omc.Context()
    panel = pd.read_parquet(DATA / "cells.parquet")
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    print(f"context ready ({time.time() - t0:.0f}s)", flush=True)

    real, store = run_world(ctx, panel, "real")
    real.to_parquet(OUT / "league_real.parquet", index=False)
    with open(OUT / "dailies_real.pkl", "wb") as fh:
        pickle.dump({i: daily_series(t) for i, t in store.items()}, fh)
    recs = []
    for i, tr in store.items():
        for x in tr:
            recs.append({
                "config": i, "symbol": x.symbol, "entry": x.entry,
                "exit": x.exit, "side": x.side, "n_contracts": x.n_contracts,
                "entry_signal_bp": x.entry_signal_bp,
                "exit_signal_bp": x.exit_signal_bp,
                "gross_bp": x.gross_bp, "cost_bp": x.opt_cost_bp,
                "net_1x_bp": x.net_at(1.0), "net_2x_bp": x.net_at(2.0),
                "exit_reason": x.exit_reason,
                "lam_used": x.meta.get("lam_used", np.nan),
                "other": x.meta.get("other", ""),
            })
    pd.DataFrame(recs).to_parquet(OUT / "trades_real.parquet", index=False)
    print(f"real: {len(real)} configs, best net1x "
          f"{real['net_1x_bp'].max():+.1f}bp ({time.time() - t0:.0f}s)",
          flush=True)

    leagues = [real]
    for tag, path, ctx_fn in (
            ("p1_gauss", DATA / "cells_p1.parquet", omc.gaussian_context),
            ("p2_calendar", DATA / "cells_p2.parquet", omc.shifted_context)):
        if not path.exists():
            print(f"!! missing {path.name}: {tag} skipped", flush=True)
            continue
        pl = pd.read_parquet(path)
        pl["as_of"] = pd.to_datetime(pl["as_of"])
        df, _ = run_world(ctx_fn(ctx), pl, tag)
        if len(df):
            df.to_parquet(OUT / f"league_{tag}.parquet", index=False)
            leagues.append(df)
            print(f"{tag}: best net1x {df['net_1x_bp'].max():+.1f}bp "
                  f"({time.time() - t0:.0f}s)", flush=True)

    league = pd.concat(leagues, ignore_index=True)
    league.to_parquet(OUT / "league.parquet", index=False)
    print(f"LEAGUE {len(league)} rows in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
