"""CPI on the 10-year note future, with a threshold entry and a bracket exit.

Answers one question with a large search and then says what the search cost:
does filtering to the big CPI prints and leaving at a LEVEL rather than at a
clock time turn the fade into something tradeable?

Run:  python cpi_ty_exit_search.py
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent))

import numpy as np
import pandas as pd

import econ_fade_common as G
import econ_fade_config as C
import econ_fade_exits as X
import econ_fade_mdp_exits as MX
from econ_fade_prewarm import load_events
from RVUtils.StatisticalFinance import (
    ras_bound, romano_wolf, selection_bias_pvalue, shared_sign_flip_null, timer_pvalue,
)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

CPI = {"currencies": ["USD"], "impacts": ["high", "medium"], "require_actual": True,
       "include_cb_decisions": False, "titles_include": [r"\bCPI\b"]}

#: One ZN tick is 1/64 of a point, which on a 10-year future is about 0.24 bp of
#: yield. The bid-ask is a tick wide, so a round trip that crosses it costs about
#: one tick. Stop fills additionally carry a tick of slippage INSIDE the price,
#: so a stop-heavy rule is charged roughly twice -- deliberately conservative.
ZN_TICK_BP = 0.2389

THRESHOLDS = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0]
TRAILS = [None, 2.0, 4.0]
TIME_STOPS = [30, 58, 118, 238]
DIRECTIONS = ["fade", "momentum"]

FRAC_TP = [0.25, 0.5, 0.75, 1.0, 1.5]
FRAC_SL = [0.5, 1.0, 1.5, 2.0, None]
ABS_TP = [1.0, 2.0, 3.0, 5.0]
ABS_SL = [2.0, 4.0, 8.0, None]


def bracket_shapes():
    """Two parameterisations of the same idea, both searched and both counted.

    A fractional bracket scales with the burst -- a 12bp CPI print and a 1bp one
    do not deserve the same target. An absolute bracket does not, which is what a
    desk with a fixed risk budget would actually run. Neither is obviously right,
    so both are tried and the family correction pays for both.
    """
    out = []
    for tp, sl in itertools.product(FRAC_TP, FRAC_SL):
        out.append(("frac", dict(tp_frac=tp, sl_frac=sl),
                    f"tp{tp:g}f|sl{'inf' if sl is None else format(sl, 'g')}f"))
    for tp, sl in itertools.product(ABS_TP, ABS_SL):
        out.append(("abs", dict(tp_bp=tp, sl_bp=sl),
                    f"tp{tp:g}b|sl{'inf' if sl is None else format(sl, 'g')}b"))
    return out


def build_cfg(direction, threshold):
    return C.spec(f"cpi_ty|{direction}|mv{threshold:g}",
                  instrument={"family": "ust", "root": "TY", "rank": 1}, events=CPI,
                  timing={"measure_end_min": 1, "entry_offset_min": 2, "exit_offset_min": 60},
                  signal={"direction": direction, "min_move_bp": threshold})


def search(raw, label):
    shapes = bracket_shapes()
    n_cells = len(THRESHOLDS) * len(DIRECTIONS) * len(shapes) * len(TRAILS) * len(TIME_STOPS)
    print(f"\n=== {label}: {n_cells:,} cells "
          f"({len(THRESHOLDS)} thresholds x {len(DIRECTIONS)} directions x "
          f"{len(shapes)} brackets x {len(TRAILS)} trails x {len(TIME_STOPS)} time stops) ===")

    rows, series = [], {}
    t0 = time.time()
    for direction, thr in itertools.product(DIRECTIONS, THRESHOLDS):
        book = X.build_base_book(build_cfg(direction, thr), raw)
        if book.events.empty:
            continue
        n_base = len(book.events)
        for family, kw, shape_name in shapes:
            for trail, ts in itertools.product(TRAILS, TIME_STOPS):
                nm = f"{direction}|mv{thr:g}|{shape_name}|tr{'-' if trail is None else format(trail, 'g')}|t{ts}"
                # mode="close": a desk polling the print once a minute, which is
                # what the engine can see and therefore what can be verified.
                rule = X.ExitRule(name=nm, trail_bp=trail, time_stop_min=ts, mode="close", **kw)
                df = MX.run_bracket_fast(book, rule, cost_bp=ZN_TICK_BP)
                if df.empty:
                    continue
                p = df["pnl_bp"].to_numpy(float)
                g = df["pnl_bp_gross"].to_numpy(float)
                sd = p.std(ddof=1) if len(p) > 1 else 0.0
                rows.append({
                    "config": nm, "direction": direction, "threshold": thr,
                    "bracket_family": family, "bracket": shape_name,
                    "trail": np.nan if trail is None else trail, "time_stop": ts,
                    "base_trades": n_base, "trades": len(df),
                    "gross_bp": float(g.mean()), "net_bp": float(p.mean()),
                    "total_net_bp": float(p.sum()), "hit_rate": float((p > 0).mean()),
                    "sr_per_trade": float(p.mean() / sd) if sd > 0 else 0.0,
                    "t_stat": float(p.mean() / (sd / np.sqrt(len(p)))) if sd > 0 else 0.0,
                    "avg_hold_min": float(df["hold_min"].mean()),
                    "pct_target": float((df.exit_reason == "target").mean()),
                    "pct_stop": float((df.exit_reason.isin(["stop", "trail"])).mean()),
                    "pct_time": float((df.exit_reason == "time_stop").mean()),
                })
                series[nm] = df.set_index("release_ts")["pnl_bp"]
    print(f"  {len(rows):,} priced in {time.time() - t0:.0f}s")
    return pd.DataFrame(rows).set_index("config"), series


def main():
    G.load_bar_cache()
    G.load_dv01()
    raw = load_events()

    # The placebo is built from EIGHT business-day shifts pooled, not one.
    # CPI prints ~11 times a year, so a single shift leaves a placebo book too
    # small to have any cell with enough trades to compare against -- the first
    # run produced ZERO eligible placebo cells, which is not a passing yardstick,
    # it is a missing one. Pooling shifts keeps the clock, the contract and the
    # gate identical and simply gives the null the sample size it needs.
    PLACEBO_SHIFTS = (1, 2, 3, 5, -1, -2, -3, -5)
    _parts = []
    for _d in PLACEBO_SHIFTS:
        _q = C.placebo_shift(raw, days=_d)
        _q["placebo_shift"] = _d
        _parts.append(_q)
    raw_p = pd.concat(_parts, ignore_index=True)
    raw_p = raw_p.drop_duplicates(subset=["release_ts"]).sort_values(
        "release_ts").reset_index(drop=True)
    print(f"placebo book pooled over {PLACEBO_SHIFTS}: {len(raw_p):,} release minutes "
          f"against {len(raw):,} real")

    # --- prime the real MDP, then prove the fast path IS the engine -------
    base_book = X.build_base_book(build_cfg("fade", 0.0), raw)
    prime = MX.open_ust_mdp(armed=True)
    for label, bk in (("real", base_book),
                      ("placebo", X.build_base_book(build_cfg("fade", 0.0), raw_p))):
        st = MX.prime_ust_cache(prime, MX.wanted_minutes(bk.events, max(TIME_STOPS)),
                                show_progress=False)
        print(f"primed USTFuturesMDP cache ({label}): {st}")
    mdp = MX.open_ust_mdp()          # disarmed: a cache miss now raises

    print("\ntie-out: the search's pricer against QueryDrivenBacktest")
    ok = True
    for rule in [X.ExitRule("tie|tp1f|sl2f", tp_frac=1.0, sl_frac=2.0, time_stop_min=58, mode="close"),
                 X.ExitRule("tie|tp2b|tr3", tp_bp=2.0, sl_bp=4.0, trail_bp=3.0,
                            time_stop_min=118, mode="close")]:
        f = MX.run_bracket_fast(base_book, rule)
        e = MX.run_bracket_engine(base_book, rule, mdp, show_progress=False)
        j = f[["tag", "pnl_bp_gross", "exit_reason"]].merge(
            e[["tag", "pnl_bp_gross", "exit_reason"]], on="tag", suffixes=("_f", "_e"))
        d = (j.pnl_bp_gross_f - j.pnl_bp_gross_e).abs().max()
        agree = int((j.exit_reason_f == j.exit_reason_e).sum())
        good = len(j) == len(f) == len(e) and d < 1e-9 and agree == len(j)
        ok &= good
        print(f"  {rule.name:<18} n={len(j)}  max|diff| {d:.1e}  reasons {agree}/{len(j)}  "
              f"{'PASS' if good else 'FAIL'}")
    assert ok, "the search pricer does NOT reproduce the engine"

    # --- the reference: the plain clock exit ------------------------------
    plain = G.fast_backtest(base_book)
    print(f"reference: CPI on TY, fade, plain T+60 clock exit -> {len(plain)} trades, "
          f"{plain.pnl_bp_gross.mean():+.4f} bp/trade gross, "
          f"{plain.pnl_bp_gross.mean() - ZN_TICK_BP:+.4f} net of one ZN tick")

    real, ser = search(raw, "REAL CPI")
    plac, _ = search(raw_p, "PLACEBO (CPI shifted +1 business day)")

    real.to_csv(G.CACHE / "cpi_ty_exit_search_real.csv")
    plac.to_csv(G.CACHE / "cpi_ty_exit_search_placebo.csv")

    MIN_TRADES = 25
    elig = real[real.trades >= MIN_TRADES].copy()
    eligp = plac[plac.trades >= MIN_TRADES]
    print(f"\n{len(elig):,} of {len(real):,} real cells have >= {MIN_TRADES} trades "
          f"({len(eligp):,} placebo cells)")

    print("\n=== TOP 15 by NET bp per trade (after one ZN tick) ===")
    print(elig.sort_values("net_bp", ascending=False).head(15)[
        ["direction", "threshold", "bracket", "trail", "time_stop", "trades",
         "gross_bp", "net_bp", "total_net_bp", "hit_rate", "sr_per_trade", "t_stat",
         "avg_hold_min", "pct_target", "pct_stop"]].round(4).to_string())

    print("\n=== TOP 15 by Sharpe per trade ===")
    print(elig.sort_values("sr_per_trade", ascending=False).head(15)[
        ["direction", "threshold", "bracket", "trail", "time_stop", "trades",
         "gross_bp", "net_bp", "hit_rate", "sr_per_trade", "t_stat"]].round(4).to_string())

    print("\n=== marginals: does each knob move the answer? (median net bp/trade) ===")
    for col in ("direction", "threshold", "bracket_family", "trail", "time_stop"):
        g = elig.groupby(col, dropna=False).agg(
            cells=("net_bp", "size"), median_net=("net_bp", "median"),
            best_net=("net_bp", "max"), median_trades=("trades", "median")).round(4)
        print(f"\n-- by {col} --")
        print(g.to_string())

    # --- what the search cost ---------------------------------------------
    X_ = pd.DataFrame({nm: ser[nm] for nm in elig.index if nm in ser}).sort_index()
    obs = np.array([X_[c].dropna().mean() / X_[c].dropna().std(ddof=1)
                    if X_[c].notna().sum() > 1 else 0.0 for c in X_.columns])
    null = shared_sign_flip_null(X_, draws=2000, rng=np.random.default_rng(20260811))
    p_best = selection_bias_pvalue(obs, null)
    rw = romano_wolf(obs, null, alpha=0.05, names=list(X_.columns))
    ras = ras_bound(X_.fillna(0.0), delta=0.05, draws=2000,
                    rng=np.random.default_rng(7), names=list(X_.columns))

    print(f"\n=== what the search cost ===")
    print(f"family matrix: {X_.shape[1]:,} cells x {X_.shape[0]:,} CPI prints")
    print(f"selection-bias adjusted p for the BEST cell : {p_best:.4f}")
    print(f"Romano-Wolf rejects at 5% FWER             : {rw.n_rejected:,} of {rw.n_strategies:,}")
    print(f"Rademacher positive                        : {int((ras.bound > 0).sum()):,} of {ras.N:,}")
    print(ras.terms().round(5).to_string())

    # --- the yardstick -----------------------------------------------------
    print(f"\n=== real against placebo ===")
    cmp_ = pd.DataFrame([
        {"grid": "REAL CPI", "cells": len(elig), "median net_bp": elig.net_bp.median(),
         "BEST net_bp": elig.net_bp.max(), "BEST sr/trade": elig.sr_per_trade.max(),
         "% net positive": float((elig.net_bp > 0).mean())},
        {"grid": "placebo +1bd", "cells": len(eligp), "median net_bp": eligp.net_bp.median(),
         "BEST net_bp": eligp.net_bp.max(), "BEST sr/trade": eligp.sr_per_trade.max(),
         "% net positive": float((eligp.net_bp > 0).mean())},
    ]).set_index("grid")
    print(cmp_.round(4).to_string())

    best = elig.sort_values("sr_per_trade", ascending=False).iloc[0]
    rw_row = rw.table[rw.table.strategy == best.name].iloc[0]
    tp = timer_pvalue(ser[best.name].to_numpy(float),
                      np.sign(ser[best.name].to_numpy(float) + 1e-12),
                      draws=4999, rng=np.random.default_rng(3))
    verdict = {
        "best cell": best.name,
        "trades": int(best.trades), "of base trades": int(best.base_trades),
        "gross bp/trade": round(float(best.gross_bp), 4),
        "ZN round trip (bp)": ZN_TICK_BP,
        "net bp/trade": round(float(best.net_bp), 4),
        "total net bp over the sample": round(float(best.total_net_bp), 2),
        "hit rate": round(float(best.hit_rate), 4),
        "Sharpe per trade": round(float(best.sr_per_trade), 4),
        "t-stat": round(float(best.t_stat), 4),
        "avg hold (min)": round(float(best.avg_hold_min), 1),
        "exits at target / stop / time": (round(float(best.pct_target), 3),
                                          round(float(best.pct_stop), 3),
                                          round(float(best.pct_time), 3)),
        "cells searched": int(len(real) * 2),
        "selection-bias adjusted p": round(float(p_best), 4),
        "Romano-Wolf adjusted p": round(float(rw_row.p_adjusted), 4),
        "RAS lower bound": round(float(ras.table().loc[best.name, "ras_lower_bound"]), 4),
        "best placebo cell net_bp": round(float(eligp.net_bp.max()), 4),
        "beats the placebo search": bool(best.net_bp > eligp.net_bp.max()),
    }
    print("\n=== VERDICT ===")
    for k, v in verdict.items():
        print(f"  {k:<34} {v}")
    pd.Series(verdict).to_frame("value").to_csv(G.CACHE / "cpi_ty_exit_verdict.csv")
    print(f"\nwrote {G.CACHE / 'cpi_ty_exit_search_real.csv'}")


if __name__ == "__main__":
    main()
