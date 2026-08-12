"""Trade the consensus surprise on the 10-year note future, optimising HIT RATE.

The hypothesis: a large surprise either overshoots and comes back (fade) or
reprices the regime (momentum). Those need opposite positions, so the strategy is
to take the fade with a TIGHT stop -- and, in the ``fade_then_flip`` variant, to
reverse into the move once the stop says the fade was the wrong read.

Ranked on hit rate, as asked, with a warning attached that is not decoration:

    HIT RATE IS NOT AN OBJECTIVE FUNCTION ON ITS OWN.

Maximising it selects a tiny target and a distant stop -- win often, lose
enormously -- and the cell that tops a hit-rate ranking is frequently the one
with the worst expectancy in the search. So every table here carries net bp per
trade and the average win/loss next to the hit rate, and the notebook reports the
frontier rather than the corner.

Run:  python surprise_ty_search.py
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
import econ_fade_surprise as S
from econ_fade_prewarm import load_events
from RVUtils.StatisticalFinance import (
    ras_bound, romano_wolf, selection_bias_pvalue, shared_sign_flip_null,
)

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

XLSX = (Path.home() / ".claude" / "uploads" / "cccd9a88-a57e-4aff-a3d9-617257228b75"
        / "54cb5dbb-econ_actual_vs_consensus.xlsx")

ZN_TICK_BP = 0.2389          # one ZN tick, in bp of yield
MIN_TRADES = 30

ENTRY_OFFSETS = [2, 5, 15]
Z_THRESHOLDS = [0.0, 1.0, 1.5, 2.0]
DIRECTIONS = ["fade", "momentum", "fade_then_flip"]
TARGETS = [1.0, 2.0, 3.0, 5.0]
STOPS = [0.5, 1.0, 2.0, 3.0, 5.0, None]      # the tight end is the point
TIME_STOPS = [30, 60, 120, 240]

REPLICA_SHIFTS = (1, 2, -1, -2)     # four matched replicas, each a full grid


def build_cfg(direction, entry, zthr):
    return {"name": f"sur|{direction}|e{entry}|z{zthr:g}",
            "instrument": {"family": "ust", "root": "TY", "rank": 1},
            "z": {"robust": True, "min_obs": 12, "min_abs_z": zthr,
                  "scale_window": 36, "z_cap": 5.0},
            "timing": {"entry_offset_min": entry},
            "signal": {"direction": "momentum" if direction == "momentum" else "fade"}}


def _stats(df, extra):
    p = df["pnl_bp"].to_numpy(float)
    wins, losses = p[p > 0], p[p <= 0]
    sd = p.std(ddof=1) if len(p) > 1 else 0.0
    row = {
        "trades": len(p), "hit_rate": float((p > 0).mean()),
        "gross_bp": float(df["pnl_bp_gross"].mean()), "net_bp": float(p.mean()),
        "total_net_bp": float(p.sum()),
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses)
        and losses.mean() != 0 else np.nan,
        "sr_per_trade": float(p.mean() / sd) if sd > 0 else 0.0,
        "t_stat": float(p.mean() / (sd / np.sqrt(len(p)))) if sd > 0 else 0.0,
        "avg_hold_min": float(df["hold_min"].mean()),
        "pct_target": float((df.exit_reason == "target").mean()),
        "pct_stop": float(df.exit_reason.isin(["stop", "trail"]).mean()),
        "pct_time": float((df.exit_reason == "time_stop").mean()),
    }
    row.update(extra)
    return row


def search(surprises, raw, label, shift_days=None):
    n_cells = (len(ENTRY_OFFSETS) * len(Z_THRESHOLDS) * len(DIRECTIONS) *
               len(TARGETS) * len(STOPS) * len(TIME_STOPS))
    print(f"\n=== {label}: {n_cells:,} cells ({len(ENTRY_OFFSETS)} entry offsets x "
          f"{len(Z_THRESHOLDS)} |z| thresholds x {len(DIRECTIONS)} directions x "
          f"{len(TARGETS)} targets x {len(STOPS)} stops x {len(TIME_STOPS)} time stops) ===")
    rows, series = [], {}
    t0 = time.time()
    for direction, entry, zthr in itertools.product(DIRECTIONS, ENTRY_OFFSETS, Z_THRESHOLDS):
        book = S.build_surprise_book(build_cfg(direction, entry, zthr), surprises, raw)
        if shift_days is not None:
            # Shift the BOOK, not the calendar. The signal is joined to the
            # calendar on DATE, so shifting the calendar destroys the join and
            # returns an EMPTY placebo -- which reads as "the placebo made
            # nothing", the most flattering possible failure. Measured: it did.
            book = S.shift_surprise_book(book, shift_days)
        if book.events.empty:
            continue
        n_base = len(book.events)
        for tp, sl, ts in itertools.product(TARGETS, STOPS, TIME_STOPS):
            nm = (f"{direction}|e{entry}|z{zthr:g}|tp{tp:g}|"
                  f"sl{'inf' if sl is None else format(sl, 'g')}|t{ts}")
            rule = X.ExitRule(name=nm, tp_bp=tp, sl_bp=sl, time_stop_min=ts, mode="close")
            if direction == "fade_then_flip":
                if sl is None:
                    continue            # nothing to flip on
                flip = X.ExitRule(name=nm + "|flip", tp_bp=tp, sl_bp=sl, mode="close")
                df = S.run_surprise_bracket(book, rule, cost_bp=ZN_TICK_BP, flip_rule=flip)
            else:
                df = MX.run_bracket_fast(book, rule, cost_bp=ZN_TICK_BP)
            if df.empty or len(df) < 5:
                continue
            rows.append(_stats(df, {
                "config": nm, "direction": direction, "entry_offset": entry,
                "z_threshold": zthr, "target_bp": tp,
                "stop_bp": np.nan if sl is None else sl, "time_stop": ts,
                "base_events": n_base,
                "legs": int(df["leg"].max()) if "leg" in df else 1}))
            series[nm] = df.groupby("release_ts")["pnl_bp"].sum()
    print(f"  {len(rows):,} priced in {time.time() - t0:.0f}s")
    if not rows:
        return pd.DataFrame(columns=["config"]).set_index("config"), series
    return pd.DataFrame(rows).set_index("config"), series


def main():
    G.load_bar_cache()
    G.load_dv01()
    raw = load_events()
    sur = S.load_surprises(XLSX)
    print(f"surprises: {len(sur):,} rows across {sur.sheet.nunique()} releases")

    base = S.build_surprise_book({"name": "base"}, sur, raw)
    print("\nFUNNEL")
    for k, v in base.funnel.items():
        print(f"  {k:<45} {v}")

    # --- does the surprise predict the first-minute move at all? -----------
    ev = base.events
    pre = [MX._minute_close(r.symbol, r.local_ts - pd.Timedelta(minutes=1))
           for _, r in ev.iterrows()]
    post = [MX._minute_close(r.symbol, r.local_ts) for _, r in ev.iterrows()]
    chk = ev.assign(pre=pre, post=post).dropna(subset=["pre", "post"])
    chk["move_bp_real"] = -(chk.post - chk.pre) / chk.px_per_bp
    agree = (np.sign(chk.move_bp_real) == chk.rate_dir)
    print(f"\nSIGN CHECK -- the surprise predicted the first-minute direction on "
          f"{agree.mean():.1%} of {len(chk)} events   "
          f"corr(z, move) = {np.corrcoef(chk.z, chk.move_bp_real)[0, 1]:+.3f}")
    for rel, g in chk.groupby("release"):
        a = (np.sign(g.move_bp_real) == g.rate_dir)
        print(f"   {rel:<28} {a.mean():>6.1%} of {len(g):>3}   "
              f"mean |first-minute move| {g.move_bp_real.abs().mean():.2f} bp")

    # --- prime the MDP over every entry offset the search uses -------------
    # Primed for the REAL book only, and only so the search pricer can be tied to
    # the engine. The replicas run through the same run_bracket_fast, which reads
    # the same bars -- priming four replicas x three offsets would write over a
    # million cache rows for a control that needs no authority beyond being
    # identical to the pricer it is compared against.
    prime = MX.open_ust_mdp(armed=True)
    for e in ENTRY_OFFSETS:
        bk = S.build_surprise_book({"name": "p", "timing": {"entry_offset_min": e}}, sur, raw)
        if bk.events.empty:
            continue
        st = MX.prime_ust_cache(prime, MX.wanted_minutes(
            bk.events.assign(m0_ts=bk.events.local_ts - pd.Timedelta(minutes=1),
                             m1_ts=bk.events.local_ts), max(TIME_STOPS)),
            show_progress=False)
        print(f"  primed real entry T+{e}: {st}")
    mdp = MX.open_ust_mdp()

    # --- tie the search pricer to QueryDrivenBacktest ----------------------
    print("\ntie-out against the engine")
    ok = True
    for rule in [X.ExitRule("tie|tp2|sl1", tp_bp=2.0, sl_bp=1.0, time_stop_min=60, mode="close"),
                 X.ExitRule("tie|tp5|slinf", tp_bp=5.0, sl_bp=None, time_stop_min=120, mode="close")]:
        f = MX.run_bracket_fast(base, rule)
        e = MX.run_bracket_engine(base, rule, mdp, show_progress=False)
        j = f[["tag", "pnl_bp_gross", "exit_reason"]].merge(
            e[["tag", "pnl_bp_gross", "exit_reason"]], on="tag", suffixes=("_f", "_e"))
        d = (j.pnl_bp_gross_f - j.pnl_bp_gross_e).abs().max()
        ag = int((j.exit_reason_f == j.exit_reason_e).sum())
        good = len(j) == len(f) == len(e) and d < 1e-9 and ag == len(j)
        ok &= good
        print(f"  {rule.name:<16} n={len(j)}  max|diff| {d:.1e}  reasons {ag}/{len(j)}  "
              f"{'PASS' if good else 'FAIL'}")
    assert ok, "the search pricer does NOT reproduce the engine"

    real, ser = search(sur, raw, "REAL surprises")
    real.to_csv(G.CACHE / "surprise_ty_real.csv")     # durable BEFORE anything else runs
    elig = real[real.trades >= MIN_TRADES].copy()
    print(f"\n{len(elig):,} of {len(real):,} real cells have >= {MIN_TRADES} trades")

    # MATCHED replicas: the identical grid, one shifted book per replica, each the
    # same size as the real book. Pooling shifts changes trades-per-cell AND
    # cells-per-grid at once and both move a maximum in opposite directions.
    rep_rows, plac_all = [], []
    for d in REPLICA_SHIFTS:
        pl, _ = search(sur, raw, f"PLACEBO shift {d:+d}bd", shift_days=d)
        if not len(pl):
            continue
        plac_all.append(pl.assign(shift=d))
        pd.concat(plac_all).to_csv(G.CACHE / "surprise_ty_placebo.csv")   # durable each pass
        el = pl[pl.trades >= MIN_TRADES]
        if len(el):
            rep_rows.append({"shift": d, "cells": len(el),
                             "median trades": float(el.trades.median()),
                             "best net_bp": float(el.net_bp.max()),
                             "best hit": float(el.hit_rate.max()),
                             "median net_bp": float(el.net_bp.median()),
                             "pct net positive": float((el.net_bp > 0).mean())})
    plac = pd.concat(plac_all) if plac_all else pd.DataFrame()
    reps = pd.DataFrame(rep_rows)
    eligp = plac[plac.trades >= MIN_TRADES] if len(plac) else plac

    cols = ["direction", "entry_offset", "z_threshold", "target_bp", "stop_bp", "time_stop",
            "trades", "hit_rate", "avg_win", "avg_loss", "payoff", "net_bp", "total_net_bp",
            "t_stat", "pct_target", "pct_stop"]
    print("\n=== TOP 20 by HIT RATE (the requested objective) ===")
    print(elig.sort_values("hit_rate", ascending=False).head(20)[cols].round(4).to_string())

    print("\n=== the same cells ranked by NET bp per trade ===")
    print(elig.sort_values("net_bp", ascending=False).head(20)[cols].round(4).to_string())

    print("\n=== hit rate is not expectancy: the frontier ===")
    b = pd.cut(elig.hit_rate, [0, .4, .5, .55, .6, .65, .7, .8, 1.0])
    print(elig.groupby(b, observed=True).agg(
        cells=("net_bp", "size"), median_net=("net_bp", "median"),
        best_net=("net_bp", "max"), median_payoff=("payoff", "median"),
        median_trades=("trades", "median")).round(4).to_string())

    print("\n=== marginals (median net bp / trade) ===")
    for col in ("direction", "entry_offset", "z_threshold", "target_bp", "stop_bp", "time_stop"):
        g = elig.groupby(col, dropna=False).agg(
            cells=("net_bp", "size"), median_hit=("hit_rate", "median"),
            best_hit=("hit_rate", "max"), median_net=("net_bp", "median"),
            best_net=("net_bp", "max")).round(4)
        print(f"\n-- by {col} --")
        print(g.to_string())

    # --- what the search cost ---------------------------------------------
    Xm = pd.DataFrame({nm: ser[nm] for nm in elig.index if nm in ser}).sort_index()
    obs = np.array([Xm[c].dropna().mean() / Xm[c].dropna().std(ddof=1)
                    if Xm[c].notna().sum() > 1 else 0.0 for c in Xm.columns])
    null = shared_sign_flip_null(Xm, draws=2000, rng=np.random.default_rng(20260811))
    p_best = selection_bias_pvalue(obs, null)
    rw = romano_wolf(obs, null, alpha=0.05, names=list(Xm.columns))
    ras = ras_bound(Xm.fillna(0.0), delta=0.05, draws=2000,
                    rng=np.random.default_rng(11), names=list(Xm.columns))
    print(f"\n=== what the search cost ===")
    print(f"family: {Xm.shape[1]:,} cells x {Xm.shape[0]:,} release minutes")
    print(f"selection-bias adjusted p for the BEST cell : {p_best:.4f}")
    print(f"Romano-Wolf rejects at 5% FWER             : {rw.n_rejected:,} of {rw.n_strategies:,}")
    print(f"Rademacher positive                        : {int((ras.bound > 0).sum()):,} of {ras.N:,}")
    print(ras.terms().round(5).to_string())

    print("\n=== real against MATCHED placebo replicas ===")
    if len(reps):
        print(reps.round(4).to_string(index=False))
        br, bh = float(elig.net_bp.max()), float(elig.hit_rate.max())
        pn, ph = reps["best net_bp"].to_numpy(), reps["best hit"].to_numpy()
        p_net = (1 + int((pn >= br).sum())) / (len(pn) + 1)
        p_hit = (1 + int((ph >= bh).sum())) / (len(ph) + 1)
        print(f"\n  REAL best net_bp {br:+.4f}   replicas {pn.min():+.4f}..{pn.max():+.4f} "
              f"(median {np.median(pn):+.4f})   exceedance p = {p_net:.4f}")
        print(f"  REAL best hit    {bh:.4f}   replicas {ph.min():.4f}..{ph.max():.4f} "
              f"(median {np.median(ph):.4f})   exceedance p = {p_hit:.4f}")
        print(f"  {len(pn)} replicas, so this test cannot report a p below "
              f"{1 / (len(pn) + 1):.3f} however large the gap")
        print(f"  net-positive cells: real {float((elig.net_bp > 0).mean()):.3f} vs "
              f"replica median {reps['pct net positive'].median():.3f}")
    else:
        print("  no placebo replica produced an eligible cell")

    best_hit = elig.sort_values("hit_rate", ascending=False).iloc[0]
    best_net = elig.sort_values("net_bp", ascending=False).iloc[0]
    verdict = {
        "best by HIT RATE": best_hit.name,
        "  hit rate": round(float(best_hit.hit_rate), 4),
        "  trades": int(best_hit.trades),
        "  net bp/trade": round(float(best_hit.net_bp), 4),
        "  avg win / avg loss": f"{best_hit.avg_win:+.3f} / {best_hit.avg_loss:+.3f}",
        "best by NET bp": best_net.name,
        "  hit rate ": round(float(best_net.hit_rate), 4),
        "  trades ": int(best_net.trades),
        "  net bp/trade ": round(float(best_net.net_bp), 4),
        "  t-stat": round(float(best_net.t_stat), 4),
        "cells searched (both grids)": int(len(real) + len(plac)),
        "selection-bias adjusted p": round(float(p_best), 4),
        "Romano-Wolf rejections": int(rw.n_rejected),
        "Rademacher positive": int((ras.bound > 0).sum()),
        "best placebo net_bp": round(float(eligp.net_bp.max()), 4) if len(eligp) else None,
        "best placebo hit": round(float(eligp.hit_rate.max()), 4) if len(eligp) else None,
    }
    print("\n=== VERDICT ===")
    for k, v in verdict.items():
        print(f"  {k:<32} {v}")
    pd.Series(verdict).to_frame("value").to_csv(G.CACHE / "surprise_ty_verdict.csv")
    print(f"\nwrote {G.CACHE / 'surprise_ty_real.csv'}")


if __name__ == "__main__":
    main()
