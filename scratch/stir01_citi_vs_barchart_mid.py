"""Can the STIR flow chart's mid come from CITI VELOCITY instead of Barchart?

`arbs_stir_direction_v1.curve_mid` is the mid the STIR classifier used, and it
comes from the Barchart STIR curve (USD-OIS-Q12xM12STIRT-SERFFX-MIX23). The ask
is to draw the Citi Velocity curve instead -- the same minute store that already
backs arbs_dd_curve_mid_v1.

That is not a front-end change, and it is not free either. `dealer_direction`
was DERIVED from the Barchart mid: the classifier's own identity is
sign(spread_to_mid_bps) == direction, and spread_to_mid_bps is measured against
that mid. Swap the line for a different curve and the marks may land on the
other side of it -- which is precisely the "green above the line" complaint this
chart has already had once, for a different reason.

So before building anything, three numbers:

  1. Can the Citi store even price a meeting-to-meeting OIS -- a
     FORWARD-STARTING structure on an exact (effective, maturity) date pair,
     not a constant-maturity tenor?
  2. How far apart are the two mids, in bp?
  3. HOW OFTEN WOULD THE DEALER'S SIDE FLIP if the spread were measured against
     Citi instead? That is the number that decides whether the line can simply
     be swapped, or whether swapping it means re-deriving the direction too.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

warnings.simplefilter("ignore")
pd.set_option("display.width", 210)

# The reference cell: the notebook's own case. 2026-07-29 is an FOMC date and
# 2026-09-16 is the next one, so this is the July->September meeting structure.
DAY = "2026-07-29"
EFF = "2026-07-29"
MAT = "2026-09-16"
INDEX = "FED_FUNDS"
CURVE = "USD-FEDFUNDS-1D"
NOTIONAL = 100_000_000


def main() -> int:
    from SDRUtils.dealer_direction import midprice, snapshot

    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    pricer = rep.pricer
    print(f"citi source token: {snapshot.CURVE_SOURCE}")

    conn = psycopg2.connect(resolve_pg_url())
    trades = pd.read_sql(
        """
        SELECT DISTINCT ON (unit_key)
               unit_key, execution_timestamp, curve_timestamp,
               dealer_direction, classification_method,
               fixed_rate, curve_mid, spread_to_mid_bps, is_off_market
        FROM arbs_stir_direction_v1
        WHERE as_of_date = %(d)s AND tenor_query = %(tq)s
          AND rate_index_clean = %(ix)s
          AND dealer_direction IN ('PAID','RECEIVED')
          AND curve_mid IS NOT NULL AND curve_timestamp IS NOT NULL
        ORDER BY unit_key, execution_timestamp
        """,
        conn, params={"d": DAY, "tq": f"{EFF}->{MAT}", "ix": INDEX},
    )
    conn.close()
    print(f"{len(trades)} trades with a stored mid on {DAY} {EFF}->{MAT} {INDEX}\n")
    if trades.empty:
        print("nothing to compare")
        return 1

    eff = pd.Timestamp(EFF).date()
    mat = pd.Timestamp(MAT).date()

    rows = []
    failures = {}
    for _, tr in trades.iterrows():
        t = pd.Timestamp(tr["curve_timestamp"]).tz_convert("UTC").floor("min")
        try:
            mark = pricer.mark_curve(CURVE, t)
            if mark is None:
                failures["no curve served"] = failures.get("no curve served", 0) + 1
                continue
            lp = pricer.price_leg(CURVE, t, eff, mat, NOTIONAL)
            citi = lp.mid_pct
        except Exception as e:  # noqa: BLE001
            k = f"{type(e).__name__}: {str(e)[:70]}"
            failures[k] = failures.get(k, 0) + 1
            continue
        if citi is None or not pd.notna(citi):
            failures["non-finite mid"] = failures.get("non-finite mid", 0) + 1
            continue
        rows.append({
            "direction": tr["dealer_direction"],
            "method": tr["classification_method"],
            "traded_pct": float(tr["fixed_rate"]) * 100.0,   # FRACTION -> percent
            "barchart_pct": float(tr["curve_mid"]),          # already percent
            "citi_pct": float(citi),
            "spread_stored": float(tr["spread_to_mid_bps"]),
        })

    if failures:
        print("PRICING FAILURES:")
        for k, v in sorted(failures.items(), key=lambda kv: -kv[1]):
            print(f"  {v:>4}  {k}")
        print()

    if not rows:
        print("CITI COULD NOT PRICE THIS INSTRUMENT AT ALL -- see failures above.")
        return 1

    df = pd.DataFrame(rows)
    df["mid_diff_bp"] = (df.citi_pct - df.barchart_pct) * 100
    df["spread_citi"] = (df.traded_pct - df.citi_pct) * 100
    df["spread_barchart"] = (df.traded_pct - df.barchart_pct) * 100

    print(f"1. CITI PRICED {len(df)} of {len(trades)} trades "
          f"({len(df)/len(trades)*100:.1f}%)\n")

    print("2. HOW FAR APART ARE THE TWO MIDS (citi - barchart, bp)")
    print(f"   median {df.mid_diff_bp.median():+.3f}   mean {df.mid_diff_bp.mean():+.3f}   "
          f"p05 {df.mid_diff_bp.quantile(.05):+.3f}   p95 {df.mid_diff_bp.quantile(.95):+.3f}   "
          f"max|.| {df.mid_diff_bp.abs().max():.3f}\n")

    # the stored spread should reproduce the barchart one -- a control on the
    # unit conversion before any conclusion is drawn from the citi numbers
    err = (df.spread_barchart - df.spread_stored).abs()
    print(f"   control: reconstructed barchart spread vs stored spread_to_mid_bps, "
          f"median |err| {err.median():.6f} bp, max {err.max():.6f} bp")
    print("   (if this is not ~0 the unit conversion is wrong and nothing below holds)\n")

    print("3. WOULD THE DEALER'S SIDE FLIP?")
    df["side_barchart"] = df.spread_barchart.apply(lambda x: "RECEIVED" if x > 0 else "PAID")
    df["side_citi"] = df.spread_citi.apply(lambda x: "RECEIVED" if x > 0 else "PAID")
    mid_based = df[df.method != "TICK_RULE"]
    agree_stored = (mid_based.side_barchart == mid_based.direction).mean()
    agree_citi = (mid_based.side_citi == mid_based.direction).mean()
    print(f"   mid-based trades: {len(mid_based)}")
    print(f"   sign(traded - BARCHART mid) matches dealer_direction: {agree_stored*100:.1f}%")
    print(f"   sign(traded - CITI     mid) matches dealer_direction: {agree_citi*100:.1f}%")
    flips = (mid_based.side_citi != mid_based.side_barchart).sum()
    print(f"   marks that would CHANGE SIDE of the line: {flips} of {len(mid_based)} "
          f"({flips/max(len(mid_based),1)*100:.1f}%)\n")

    print(df.groupby("direction")[["spread_barchart", "spread_citi", "mid_diff_bp"]]
          .median().round(3).to_string())

    print()
    if agree_citi >= 0.98:
        print("VERDICT: the Citi mid preserves the classifier's side. The line can be "
              "swapped without re-deriving direction.")
    else:
        print(f"VERDICT: the Citi mid does NOT preserve the side ({agree_citi*100:.1f}%). "
              "Drawing it under a Barchart-derived direction would put "
              f"{flips} marks on the wrong side of their own line. Either reprice the "
              "DIRECTION against Citi too, or draw both mids and label them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
