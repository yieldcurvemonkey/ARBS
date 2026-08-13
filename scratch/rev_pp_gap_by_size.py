"""Is the fee reconciliation as sharp on PKG-4+ as on the CURVE/FLY units the
docstring validates against?

For every unit with a usable PTP and complete fees, enumerate all sign vectors
and report how far the runner-up class sits from the winner, in bp of the
unit's own DV01 -- the same scale TIEOUT_MAX_BPS is expressed in. Split by leg
count, because the known-answer population (2 and 3 legs) has 1 and 2 competing
classes while a PKG-6 has 32.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import package_price as pp
from SDRUtils.dealer_direction.universe import LEG_COLUMNS, annotate_legs, unit_frame

DAYS = sys.argv[1:] or ["2025-03-12", "2025-09-17", "2026-06-10"]


def classes(opas, ptp, dv01):
    n = len(opas)
    v = np.asarray(opas, dtype=float)
    masks = np.arange(1 << n, dtype=np.int64)
    plus = np.zeros(masks.shape[0])
    for i in range(n):
        plus += v[i] * ((masks >> i) & 1)
    nets = 2.0 * plus - v.sum()
    bps = np.minimum(np.abs(nets - ptp), np.abs(nets + ptp)) / dv01
    full = (1 << n) - 1
    best_by_class: dict = {}
    for mm in range(1 << n):
        k = min(mm, full ^ mm)
        b = float(bps[mm])
        if k not in best_by_class or b < best_by_class[k]:
            best_by_class[k] = b
    vals = sorted(best_by_class.values())
    gap = (vals[1] - vals[0]) if len(vals) > 1 else float("inf")
    ngate = sum(1 for b in vals if b <= pp.TIEOUT_MAX_BPS)
    return vals[0], gap, ngate


def main() -> int:
    cols = list(dict.fromkeys(list(LEG_COLUMNS)))
    sql = (f"SELECT {', '.join(cols)} FROM {LEGS_TABLE} "
           "WHERE as_of_date = %(d)s "
           "ORDER BY package_id, expiration_date, effective_date, "
           "trade_id, leg_order")
    conn = psycopg2.connect(resolve_pg_url())
    rec: list = []
    n_pkg4 = 0
    n_pkg4_recov = 0
    for d in DAYS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = pd.read_sql(sql, conn, params={"d": d})
        if raw.empty:
            continue
        u = unit_frame(raw)
        df = annotate_legs(raw)
        n_pkg4 += int((u["n_legs"] >= 4).sum())
        n_pkg4_recov += int(((u["n_legs"] >= 4) & u["exclusion"].isna()).sum())
        for g, s in df.groupby("_unit_group", sort=False):
            n = len(s)
            if n < 2 or n > 18:
                continue
            opas = pd.to_numeric(s["other_payment_amount"],
                                 errors="coerce").to_numpy(float)
            pv = pd.to_numeric(s["package_transaction_price"],
                               errors="coerce").dropna()
            if not len(pv):
                continue
            ptp = float(pv.iloc[0])
            if abs(ptp) <= pp.PTP_USD_FLOOR or not np.isfinite(opas).all():
                continue
            dv01 = float(np.nansum(np.abs(pd.to_numeric(
                s["_dv01_proxy"], errors="coerce").to_numpy(float)))) / 2.0
            if dv01 <= 0:
                continue
            best, gap, ngate = classes(np.abs(opas), ptp, dv01)
            if best > pp.TIEOUT_MAX_BPS:
                continue
            rec.append((n, best, gap, ngate))
    conn.close()
    r = pd.DataFrame(rec, columns=["n_legs", "best_bps", "gap_bps", "n_gate"])
    r["grp"] = np.where(r["n_legs"] == 2, "2 (CURVE)",
                        np.where(r["n_legs"] == 3, "3 (FLY)", "4+ (PKG)"))
    print(f"PKG-4+ units seen {n_pkg4}, of which universe keeps "
          f"{n_pkg4_recov} ({100.0*n_pkg4_recov/max(n_pkg4,1):.1f}%)")
    print(r.groupby("grp").agg(
        n=("best_bps", "size"),
        best_p50=("best_bps", lambda x: round(float(np.percentile(x, 50)), 4)),
        gap_p50=("gap_bps", lambda x: round(float(np.percentile(x, 50)), 4)),
        gap_lt_005=("gap_bps", lambda x: round(100.0 * float((x < 0.05).mean()), 1)),
        classes_in_gate_p50=("n_gate", lambda x: float(np.median(x))),
        classes_in_gate_max=("n_gate", "max"),
    ).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
