"""Twenty matched placebo replicas for the consensus-surprise strategy.

Four replicas cannot report an exceedance p-value below 0.200 however large the
gap; twenty take that floor to 0.048. Each replica is the IDENTICAL grid on a
book of the same size, shifted by k business days.

Two corrections over the first attempt, both of which change what the control
means.

**Shifted minutes that land on another real tier-1/2 release are dropped.**
Measured on this book: a -1 business-day shift of payrolls lands on jobless
claims at the same 08:30, and 59% of that replica's events sat on a real release
minute (+1bd 38%, +2bd 40%, +3bd 43%, +5bd 44%). A control that is half made of
other releases is not a no-news control, and the first four-replica result was
built on one.

**Both variants are reported.** ``clean`` removes the collisions and asks "is a
release minute special against a quiet one". ``any-day`` keeps them and asks the
harder question, "is THIS release special against whatever else was going on".
They bracket the answer.

Run:  python surprise_replicas.py
"""

from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent))

import numpy as np
import pandas as pd

import econ_fade_common as G
import econ_fade_exits as X
import econ_fade_mdp_exits as MX
import econ_fade_surprise as S
from econ_fade_prewarm import load_events
from surprise_ty_search import (XLSX, ZN_TICK_BP, MIN_TRADES, ENTRY_OFFSETS,
                                Z_THRESHOLDS, DIRECTIONS, TARGETS, STOPS,
                                TIME_STOPS, build_cfg, _stats)

pd.set_option("display.width", 250)

SHIFTS = [d for d in range(-10, 11) if d != 0]      # 20 replicas


def grid(book_for):
    """The identical search, whatever book it is handed."""
    rows = []
    for direction, entry, zthr in itertools.product(DIRECTIONS, ENTRY_OFFSETS, Z_THRESHOLDS):
        book = book_for(direction, entry, zthr)
        if book is None or book.events.empty:
            continue
        for tp, sl, ts in itertools.product(TARGETS, STOPS, TIME_STOPS):
            nm = (f"{direction}|e{entry}|z{zthr:g}|tp{tp:g}|"
                  f"sl{'inf' if sl is None else format(sl, 'g')}|t{ts}")
            rule = X.ExitRule(name=nm, tp_bp=tp, sl_bp=sl, time_stop_min=ts, mode="close")
            if direction == "fade_then_flip":
                if sl is None:
                    continue
                df = S.run_surprise_bracket(
                    book, rule, cost_bp=ZN_TICK_BP,
                    flip_rule=X.ExitRule(nm + "|f", tp_bp=tp, sl_bp=sl, mode="close"))
            else:
                df = MX.run_bracket_fast(book, rule, cost_bp=ZN_TICK_BP)
            if df.empty or len(df) < 5:
                continue
            rows.append(_stats(df, {"config": nm, "direction": direction,
                                    "entry_offset": entry, "z_threshold": zthr,
                                    "target_bp": tp,
                                    "stop_bp": np.nan if sl is None else sl,
                                    "time_stop": ts}))
    return pd.DataFrame(rows).set_index("config") if rows else pd.DataFrame()


def main():
    G.load_bar_cache()
    G.load_dv01()
    raw = load_events()
    sur = S.load_surprises(XLSX)
    real_minutes = set(pd.to_datetime(raw["release_ts"], utc=True))
    print(f"{len(real_minutes):,} real tier-1/2 release minutes to avoid")

    # Built once and reused by every replica -- the shift is applied to the book.
    base = {}
    for d, e, z in itertools.product(DIRECTIONS, ENTRY_OFFSETS, Z_THRESHOLDS):
        base[(d, e, z)] = S.build_surprise_book(build_cfg(d, e, z), sur, raw)

    t0 = time.time()
    real = grid(lambda d, e, z: base[(d, e, z)])
    real.to_csv(G.CACHE / "surprise_replicas_real.csv")
    elig = real[real.trades >= MIN_TRADES]
    print(f"REAL: {len(real):,} cells ({len(elig):,} eligible) in {time.time() - t0:.0f}s   "
          f"best net {elig.net_bp.max():+.4f}   best hit {elig.hit_rate.max():.4f}")

    for variant, avoid in (("clean", real_minutes), ("any-day", None)):
        rows, allc = [], []
        for k in SHIFTS:
            t0 = time.time()
            g = grid(lambda d, e, z, _k=k, _a=avoid:
                     S.shift_surprise_book(base[(d, e, z)], _k, avoid=_a))
            if not len(g):
                continue
            el = g[g.trades >= MIN_TRADES]
            allc.append(g.assign(shift=k, variant=variant))
            pd.concat(allc).to_csv(G.CACHE / f"surprise_replicas_{variant}.csv")
            if len(el):
                rows.append({"shift": k, "cells": len(el),
                             "median trades": float(el.trades.median()),
                             "best net_bp": float(el.net_bp.max()),
                             "best hit": float(el.hit_rate.max()),
                             "median net_bp": float(el.net_bp.median()),
                             "pct net positive": float((el.net_bp > 0).mean())})
                print(f"  {variant} shift {k:+3d}: {len(el):>5} eligible, "
                      f"best net {el.net_bp.max():+.4f}, best hit {el.hit_rate.max():.4f} "
                      f"({time.time() - t0:.0f}s)")
        reps = pd.DataFrame(rows)
        if not len(reps):
            print(f"{variant}: no replica produced an eligible cell")
            continue
        reps.to_csv(G.CACHE / f"surprise_replicas_{variant}_summary.csv", index=False)

        br, bh = float(elig.net_bp.max()), float(elig.hit_rate.max())
        pn, ph = reps["best net_bp"].to_numpy(), reps["best hit"].to_numpy()
        p_net = (1 + int((pn >= br).sum())) / (len(pn) + 1)
        p_hit = (1 + int((ph >= bh).sum())) / (len(ph) + 1)
        print(f"\n=== {variant.upper()}: {len(reps)} replicas ===")
        print(reps.round(4).to_string(index=False))
        print(f"  REAL best net {br:+.4f}  vs replicas {pn.min():+.4f}..{pn.max():+.4f} "
              f"(median {np.median(pn):+.4f})   exceedance p = {p_net:.4f}")
        print(f"  REAL best hit {bh:.4f}  vs replicas {ph.min():.4f}..{ph.max():.4f} "
              f"(median {np.median(ph):.4f})   exceedance p = {p_hit:.4f}")
        print(f"  floor on {len(pn)} replicas is {1 / (len(pn) + 1):.4f}")
        print(f"  net-positive cells: real {float((elig.net_bp > 0).mean()):.3f} vs "
              f"replica median {reps['pct net positive'].median():.3f}")


if __name__ == "__main__":
    main()
