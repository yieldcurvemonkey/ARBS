"""Probe 17: where the 16 ms/unit goes, and what a dust floor buys in rows.

(a) cProfile of the shipped path on a 400-leg slice of a real day.
(b) rows vs dropped gross DV01 for a range of dust floors, so the default is a
    measured trade rather than a taste.
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np
import pandas as pd

from dd_measure import LEG_COLS, connect, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import krd as K
from SDRUtils.dealer_direction import midprice
from SDRUtils.dealer_direction import types as T
from SDRUtils.dealer_direction.midprice import SessionBranchPricer

pd.set_option("display.width", 240)
DAY = "2026-04-01"
N = 400


def load():
    conn = connect()
    legs = read_sql(conn, f"""
        SELECT {LEG_COLS} FROM {LEGS_TABLE} l
        WHERE l.as_of_date = %(d)s
          AND l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
          AND l.rate_index_clean IN ('SOFR','FED_FUNDS')
          AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
          AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
        ORDER BY l.execution_timestamp, l.trade_id""", {"d": DAY})
    conn.close()
    units, calls = [], []
    strata = {}
    for _, r in legs.iterrows():
        u, snap, _ = unit_from_leg(r)
        s = midprice.start_class(r["effective_date"], snap)
        strata[s] = strata.get(s, 0) + 1
        units.append(u)
        calls.append(T.DirectionCall(
            unit_key=u.unit_key, rule=conv.RULE_RATE, deviation_bps=1.0, p=0.9,
            signed_weight=conv.signed_weight(0.9), dealer_sign=1,
            tau_bucket="SOFR_5Y", tau_bps=0.35))
    print(f"{DAY}: {len(units)} legs; start strata {strata}")
    return units, calls


def main() -> None:
    units, calls = load()

    # ---------------------------------------------------- (a) profile a slice
    proj = K.KrdProjector(SessionBranchPricer(), block_minutes=60)
    sl = slice(0, N)
    pr = cProfile.Profile()
    pr.enable()
    frame, _ = proj.krd_frame(units[sl], calls[sl])
    pr.disable()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(22)
    print("\n=== cProfile, first %d legs ===" % N)
    print("\n".join(buf.getvalue().splitlines()[4:34]))

    # ------------------------------------------- (b) dust floor vs rows kept
    print("\n=== dust floor: rows kept and gross |DV01| dropped, whole day ===")
    proj2 = K.KrdProjector(SessionBranchPricer(), block_minutes=60)
    t0 = time.perf_counter()
    with proj2.day_scope():
        full, _ = proj2.krd_frame(units, calls)
    print(f"  full frame: {len(full):,} rows in {time.perf_counter()-t0:.0f}s")
    v = full["dv01_if_received"].abs().to_numpy()
    gross = v.sum()
    per_unit_gross = full.groupby("unit_key")["dv01_if_received"].transform(
        lambda s: s.abs().sum()).to_numpy()
    for dust in (0.0, 0.05, 0.5, 1.0, 5.0, 25.0):
        keep = v > dust
        rel = (v[~keep] / np.maximum(per_unit_gross[~keep], 1e-12))
        print(f"  dust={dust:6.2f} USD/bp  rows {keep.sum():8,d} "
              f"({keep.mean():6.1%})  gross dropped {1 - v[keep].sum()/gross:8.5%}  "
              f"worst single dropped bucket = "
              f"{(rel.max() if rel.size else 0.0):.4%} of its unit's gross")


if __name__ == "__main__":
    main()
