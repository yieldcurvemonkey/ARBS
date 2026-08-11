"""Stage 6c - a placebo, because a tight median proves nothing on its own.

The bias result is "(printed - mid) has a median of +0.02 bp with an IQR of
0.27 bp". That is only evidence the pricing is right if the SAME procedure
produces a visibly worse number when the curve is deliberately wrong. If a curve
from a week earlier also lands at +0.02 bp, then the statistic is not reading the
curve at all and the headline is unearned.

So: reprice the identical 200 prints against the same wall-clock minute SEVEN
CALENDAR DAYS earlier (same weekday, so the session bounds still hold), under
the same strict policy. Nothing else changes - same legs, same schedules, same
notionals, same code path.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import psycopg2

from dd_common import make_pricer, strict_policy
from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

CURVE = "USD-SOFR-1D"
BIAS_CSV = "C:/Users/chris/clee/ARBS-dd/scratch/out_bias200.csv"


def main() -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    base = pd.read_csv(BIAS_CSV)
    ids = tuple(str(t) for t in base["trade_id"])
    conn = psycopg2.connect(resolve_pg_url())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        legs = pd.read_sql(
            f"""SELECT trade_id, effective_date, expiration_date, notional, fixed_rate
                FROM {LEGS_TABLE} WHERE trade_id IN %(ids)s""",
            conn, params={"ids": ids})
    conn.close()
    legs = legs.drop_duplicates("trade_id").set_index("trade_id")
    print(f"{len(legs)} legs recovered for the {len(base)} priced prints")

    pricer = make_pricer(strict_policy(1))
    out = []
    for _, r in base.iterrows():
        tid = str(r["trade_id"])
        if tid not in legs.index:
            continue
        leg = legs.loc[tid]
        snap = pd.Timestamp(r["snap_et"], tz="America/New_York")
        shifted = snap - pd.Timedelta(days=7)
        if not publishes(CURVE, shifted):
            continue
        try:
            lp = pricer.price_leg(CURVE, shifted.to_pydatetime(),
                                  leg["effective_date"], leg["expiration_date"],
                                  float(leg["notional"]))
        except (SnapshotMiss, Exception):  # noqa: BLE001
            continue
        out.append({
            "trade_id": tid,
            "diff_bp_true": r["diff_bp"],
            "diff_bp_placebo": (float(leg["fixed_rate"]) * 100.0 - lp.mid_pct) * 100.0,
        })
    df = pd.DataFrame(out)
    df.to_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_placebo.csv", index=False)
    print(f"paired on {len(df)} prints\n")

    for col, label in (("diff_bp_true", "TRUE  curve at t-1min of the print"),
                       ("diff_bp_placebo", "PLACEBO curve 7 calendar days earlier")):
        x = df[col].dropna()
        print(f"{label:42s} median {x.median():+.4f}  "
              f"IQR [{x.quantile(.25):+.4f}, {x.quantile(.75):+.4f}] "
              f"(w={x.quantile(.75)-x.quantile(.25):.3f})  "
              f"|d|<=0.1bp {(x.abs()<=0.1).mean():5.1%}  "
              f"MAD {np.median(np.abs(x - x.median())):.3f}")
    w_true = df["diff_bp_true"].quantile(.75) - df["diff_bp_true"].quantile(.25)
    w_plac = df["diff_bp_placebo"].quantile(.75) - df["diff_bp_placebo"].quantile(.25)
    print(f"\nIQR ratio placebo/true = {w_plac/w_true:.1f}x")
    print("A ratio near 1 would mean the statistic never read the curve; a large "
          "ratio means the +0.02 bp median is a property of the RIGHT minute.")


if __name__ == "__main__":
    main()
