"""How often is the fee sign vector NOT determined up to the global flip?

Read-only against the prod tape. For every PKG-4+ unit the gate calls
recoverable, enumerate all 2^n sign vectors and count how many distinct ones
(up to the global complement) land inside TIEOUT_MAX_BPS. More than one means
the orientation -- and so every leg's key-rate sign -- came from
``opa_sign_solver``'s lowest-mask tie-break, not from the reconciliation.
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

DAYS = sys.argv[1:] or ["2025-03-12", "2025-09-17"]


def degeneracy(opas, ptp, dv01):
    """(exact-tie classes, gap to 2nd-best class in bp, best bp, gate classes).

    A "class" is a sign vector together with its global complement -- the
    degree of freedom the module says cancels. Two DISTINCT classes at the
    same residual means the orientation came from the solver's lowest-mask
    tie-break.
    """
    n = len(opas)
    v = np.asarray(opas, dtype=float)
    masks = np.arange(1 << n, dtype=np.int64)
    plus = np.zeros(masks.shape[0])
    for i in range(n):
        plus += v[i] * ((masks >> i) & 1)
    nets = 2.0 * plus - v.sum()
    resid = np.minimum(np.abs(nets - ptp), np.abs(nets + ptp))
    bps = resid / dv01
    full = (1 << n) - 1
    best = float(bps.min())
    tol = 1e-9 * max(1.0, abs(ptp)) / dv01
    ties = {min(int(m), full ^ int(m))
            for m in np.flatnonzero(bps <= best + tol)}
    others = [float(bps[m]) for m in range(1 << n)
              if min(m, full ^ m) not in ties]
    gap = (min(others) - best) if others else float("inf")
    gate = {min(int(m), full ^ int(m))
            for m in np.flatnonzero(bps <= pp.TIEOUT_MAX_BPS)}
    return len(ties), gap, best, len(gate)


def main() -> int:
    cols = list(dict.fromkeys(list(LEG_COLUMNS)))
    sql = (f"SELECT {', '.join(cols)} FROM {LEGS_TABLE} "
           "WHERE as_of_date = %(d)s "
           "ORDER BY package_id, expiration_date, effective_date, "
           "trade_id, leg_order")
    conn = psycopg2.connect(resolve_pg_url())
    tot = amb = zero_fee_units = 0
    dup_fee_units = 0
    n_legs_tot = n_legs_zero = 0
    gaps: list = []
    gate_classes: list = []
    for d in DAYS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = pd.read_sql(sql, conn, params={"d": d})
        if raw.empty:
            print(d, "no rows")
            continue
        u = unit_frame(raw)
        df = annotate_legs(raw)
        keep = u.index[(u["n_legs"] >= 4) & u["exclusion"].isna()]
        sub = df[df["_unit_group"].isin(set(keep))]
        day_tot = day_amb = 0
        for g, s in sub.groupby("_unit_group", sort=False):
            opas = pd.to_numeric(s["other_payment_amount"],
                                 errors="coerce").to_numpy(float)
            ptp = float(pd.to_numeric(s["package_transaction_price"],
                                      errors="coerce").dropna().iloc[0])
            dv01 = float(np.nansum(np.abs(pd.to_numeric(
                s["_dv01_proxy"], errors="coerce").to_numpy(float)))) / 2.0
            if len(opas) > 20 or not np.isfinite(opas).all() or dv01 <= 0:
                continue
            k, gap, best, kgate = degeneracy(np.abs(opas), ptp, dv01)
            gaps.append(gap)
            gate_classes.append(kgate)
            day_tot += 1
            n_legs_tot += len(opas)
            nz = int((np.abs(opas) == 0).sum())
            n_legs_zero += nz
            if nz:
                zero_fee_units += 1
            if len(set(np.abs(opas))) < len(opas):
                dup_fee_units += 1
            if k > 1:
                day_amb += 1
        print(f"{d}: recoverable PKG-4+ units enumerated {day_tot}, "
              f"ambiguous (>1 sign class inside the gate) {day_amb} "
              f"({100.0 * day_amb / max(day_tot, 1):.1f}%)")
        tot += day_tot
        amb += day_amb
    conn.close()
    print(f"TOTAL {tot} units, exact-tie ambiguous {amb} "
          f"({100.0*amb/max(tot,1):.1f}%), "
          f"units with a zero fee {zero_fee_units}, "
          f"units with a duplicated fee {dup_fee_units}, "
          f"legs {n_legs_tot} of which zero-fee {n_legs_zero}")
    if gaps:
        g = np.array(gaps, dtype=float)
        fin = g[np.isfinite(g)]
        print(f"  gap to the 2nd-best sign class, bp of unit DV01: "
              f"p10 {np.percentile(fin,10):.4f} p50 {np.percentile(fin,50):.4f} "
              f"p90 {np.percentile(fin,90):.4f}; "
              f"share with gap < 0.05bp {100.0*(fin<0.05).mean():.1f}%, "
              f"< TIEOUT_MAX_BPS {100.0*(fin<pp.TIEOUT_MAX_BPS).mean():.1f}%")
        c = np.array(gate_classes, dtype=float)
        print(f"  distinct sign classes inside the 1bp gate: median "
              f"{np.median(c):.0f}, share > 1: {100.0*(c>1).mean():.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
