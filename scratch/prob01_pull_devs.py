"""Pull the legacy s2m deviations as a SHAPE EXERCISE ONLY.

`arbs_stir_direction_v1.spread_to_mid_bps` comes off the Barchart
`Q12xM12STIRT` curve, which LEDGER F-20 measured as biased ~0.5 bp high with
~7x the dispersion of the Citi minute curve. So these numbers are NOT the
deviations the production model will see. They are used here for two things
only:

1. shape -- does a real bucket's deviation histogram look like a symmetric
   two-component mixture at all, or is it leptokurtic?
2. a KNOWN-ANSWER test of the estimator: F-20 measured median s2m on
   RATE_VS_MID at -0.4836 bp. A `b0` that lands there is the estimator
   agreeing with an independently measured number.

Read-only. Writes nothing.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prob01_devs.parquet")

SQL = text(
    """
    SELECT as_of_date,
           spread_to_mid_bps,
           tenor_bucket,
           trade_type,
           rate_index_clean,
           classification_method,
           dealer_direction,
           direction_confidence,
           curve_suspect_trade,
           dv01,
           dv01_bucket,
           structure_dv01
      FROM arbs_stir_direction_v1
     WHERE classification_method IN ('RATE_VS_MID','SPREAD_VS_MID','FLY_VS_MID')
       AND spread_to_mid_bps IS NOT NULL
    """
)


def main() -> int:
    eng = create_engine(resolve_pg_url(), pool_pre_ping=True)
    with eng.connect() as cx:
        cx.execute(text("SET LOCAL statement_timeout = '600s'"))
        cols = cx.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'arbs_stir_direction_v1' ORDER BY ordinal_position"
        )).scalars().all()
        print(f"columns ({len(cols)}): {cols}")
        df = pd.read_sql(SQL, cx)
    print(f"rows: {len(df):,}")
    df.to_parquet(OUT)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
