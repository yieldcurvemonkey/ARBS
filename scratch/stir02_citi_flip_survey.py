"""Across MANY cells: does the Citi mid keep every mark on its own side?

stir01 answered this for one instrument-day and got a clean 0/105 flips. That is
not enough to build on, for a measured reason:

  * the Citi-minus-Barchart gap on that cell was a systematic +0.645 bp;
  * RECEIVED trades there sat +1.472 bp above their mid, so they survived a
    0.645 bp shift with room to spare;
  * but table-wide the median RECEIVED spread is only +0.452 bp -- SMALLER than
    the gap. If that gap is general, the median receive crosses the line.

A chart that puts a RECEIVED mark below its own mid line is the exact complaint
this chart has already had once. So the flip rate has to be measured on a spread
of days and instruments, not on the one cell that happened to be comfortable.

It also records the SNAPSHOT POLICY and the served date for every price. stir01
logged `USD-FEDFUNDS-1D-CITIVELOEXCELMIN served a snapshot from a DIFFERENT
local date (2026-07-28 for a 2026-07-29 request)`, and a mid taken from the
previous day would manufacture exactly the systematic gap being measured. If the
gap is really a stale snapshot then the whole comparison is an artefact.
"""
from __future__ import annotations

import collections
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

warnings.simplefilter("ignore")
pd.set_option("display.width", 220)

CURVE_FOR = {"FED_FUNDS": "USD-FEDFUNDS-1D", "SOFR": "USD-SOFR-1D"}
NOTIONAL = 100_000_000
MAX_CELLS = 8
MAX_TRADES_PER_CELL = 60


def main() -> int:
    from SDRUtils.dealer_direction import midprice, snapshot

    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    pricer = rep.pricer

    conn = psycopg2.connect(resolve_pg_url())
    # A SPREAD of cells: both indices, across the window, busiest first within
    # each month so the sample is not one week of one instrument.
    cells = pd.read_sql(
        """
        SELECT as_of_date, tenor_query, rate_index_clean, count(*) n
        FROM arbs_stir_direction_v1
        WHERE dealer_direction IN ('PAID','RECEIVED')
          AND curve_mid IS NOT NULL AND curve_timestamp IS NOT NULL
          AND classification_method <> 'TICK_RULE'
          AND NOT COALESCE(is_off_market, false)
        GROUP BY 1,2,3
        HAVING count(*) >= 25
           AND count(*) FILTER (WHERE dealer_direction = 'RECEIVED') >= 5
        ORDER BY random()
        LIMIT %(k)s
        """, conn, params={"k": MAX_CELLS})

    rows = []
    policies = collections.Counter()
    stale = collections.Counter()
    for _, cell in cells.iterrows():
        ix = cell["rate_index_clean"]
        curve = CURVE_FOR.get(ix)
        if curve is None:
            continue
        eff_s, mat_s = str(cell["tenor_query"]).split("->")
        eff, mat = pd.Timestamp(eff_s).date(), pd.Timestamp(mat_s).date()
        tr = pd.read_sql(
            """
            SELECT DISTINCT ON (unit_key)
                   unit_key, curve_timestamp, dealer_direction,
                   fixed_rate, curve_mid, spread_to_mid_bps
            FROM arbs_stir_direction_v1
            WHERE as_of_date=%(d)s AND tenor_query=%(tq)s AND rate_index_clean=%(ix)s
              AND dealer_direction IN ('PAID','RECEIVED')
              AND curve_mid IS NOT NULL AND curve_timestamp IS NOT NULL
              AND classification_method <> 'TICK_RULE'
              AND NOT COALESCE(is_off_market, false)
            ORDER BY unit_key
            LIMIT %(k)s
            """, conn, params={"d": cell["as_of_date"], "tq": cell["tenor_query"],
                               "ix": ix, "k": MAX_TRADES_PER_CELL})
        for _, t0 in tr.iterrows():
            t = pd.Timestamp(t0["curve_timestamp"]).tz_convert("UTC").floor("min")
            try:
                mark = pricer.mark_curve(curve, t)
                if mark is None:
                    continue
                lp = pricer.price_leg(curve, t, eff, mat, NOTIONAL)
            except Exception:  # noqa: BLE001
                continue
            if lp is None or lp.mid_pct is None or not pd.notna(lp.mid_pct):
                continue
            pol = getattr(mark, "policy", "?")
            policies[pol] += 1
            served = getattr(mark, "served_utc", None)
            if served is not None:
                sd = pd.Timestamp(served).tz_convert("America/New_York").date()
                rd = t.tz_convert("America/New_York").date()
                if sd != rd:
                    stale[f"{pol}: served {sd} for {rd}"] += 1
            rows.append({
                "day": str(cell["as_of_date"]), "instr": cell["tenor_query"], "ix": ix,
                "direction": t0["dealer_direction"],
                "traded_pct": float(t0["fixed_rate"]) * 100.0,
                "barchart_pct": float(t0["curve_mid"]),
                "citi_pct": float(lp.mid_pct),
                "policy": pol,
            })
    conn.close()

    if not rows:
        print("no prices at all")
        return 1
    df = pd.DataFrame(rows)
    df["gap_bp"] = (df.citi_pct - df.barchart_pct) * 100
    df["sp_bar"] = (df.traded_pct - df.barchart_pct) * 100
    df["sp_citi"] = (df.traded_pct - df.citi_pct) * 100
    df["side_bar"] = df.sp_bar.apply(lambda x: "RECEIVED" if x > 0 else "PAID")
    df["side_citi"] = df.sp_citi.apply(lambda x: "RECEIVED" if x > 0 else "PAID")

    print(f"\npriced {len(df)} trades across {df.groupby(['day','instr','ix']).ngroups} cells")
    print(f"policies: {dict(policies)}")
    if stale:
        print("STALE SNAPSHOTS (served a different local date):")
        for k, v in stale.most_common(6):
            print(f"  {v:>4}  {k}")
    else:
        print("no snapshot served a different local date")

    print(f"\nCITI - BARCHART gap, bp:  median {df.gap_bp.median():+.3f}  "
          f"mean {df.gap_bp.mean():+.3f}  p05 {df.gap_bp.quantile(.05):+.3f}  "
          f"p95 {df.gap_bp.quantile(.95):+.3f}")

    agree_bar = (df.side_bar == df.direction).mean()
    agree_citi = (df.side_citi == df.direction).mean()
    flips = int((df.side_citi != df.side_bar).sum())
    print(f"\nside matches dealer_direction:  BARCHART {agree_bar*100:.1f}%   "
          f"CITI {agree_citi*100:.1f}%")
    print(f"marks that CHANGE SIDE of the line: {flips} of {len(df)} "
          f"({flips/len(df)*100:.1f}%)")
    print("\nby direction:")
    g = df.groupby("direction").agg(
        n=("gap_bp", "size"),
        med_sp_barchart=("sp_bar", "median"),
        med_sp_citi=("sp_citi", "median"),
        med_gap=("gap_bp", "median"),
        would_flip=("side_citi", lambda s: int((s != df.loc[s.index, "direction"]).sum())),
    ).round(3)
    print(g.to_string())

    print("\nper cell:")
    pc = df.groupby(["day", "instr", "ix"]).apply(
        lambda d: pd.Series({
            "n": len(d),
            "med_gap_bp": round(d.gap_bp.median(), 3),
            "flips": int((d.side_citi != d.side_bar).sum()),
        })).reset_index()
    print(pc.to_string(index=False))

    print()
    if agree_citi >= 0.98:
        print("VERDICT: swap the line. The Citi mid keeps every mark on its own side.")
    else:
        print(f"VERDICT: DO NOT silently swap the line -- {flips} marks "
              f"({flips/len(df)*100:.1f}%) would sit on the wrong side of it. "
              "The direction was derived from the Barchart mid; drawing a Citi mid "
              "under it needs either a re-derived direction or both lines, labelled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
