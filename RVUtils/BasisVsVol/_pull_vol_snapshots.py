"""Pull the ustf-vs-swaption vol snapshot tables from prod into a local parquet cache.

Read-only. Chunked by year so a long analytical read cannot die on a statement timeout while
the tape pipeline migrates schema (see ARBS notes on prod reads).

Usage:
    <env>/python.exe RVUtils/BasisVsVol/_pull_vol_snapshots.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

import pandas as pd
from sqlalchemy import create_engine, text

USTF_TABLE = "arbs_ustf_vol_snapshots_v2"
SWPT_TABLE = "arbs_swaption_vol_snapshots_v2"
CMP_TABLE = "arbs_ustf_vs_swaption_comparison_v2"

DEFAULT_OUT = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"


def _engine():
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry")
    return create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}")


def _pull(eng, table: str, years: list[int]) -> pd.DataFrame:
    frames = []
    for y in years:
        sql = text(
            f"SELECT * FROM {table} "
            f"WHERE as_of_date >= :lo AND as_of_date < :hi "
            f"ORDER BY as_of_date"
        )
        with eng.connect() as c:
            c.execute(text("SET LOCAL statement_timeout = '120s'"))
            df = pd.read_sql(sql, c, params={"lo": f"{y}-01-01", "hi": f"{y + 1}-01-01"})
        print(f"  {table} {y}: {len(df):,} rows", flush=True)
        if len(df):
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    eng = _engine()
    years = list(range(2022, 2027))

    for table in (USTF_TABLE, SWPT_TABLE, CMP_TABLE):
        print(f"pulling {table} ...", flush=True)
        df = _pull(eng, table, years)
        if df.empty:
            print(f"  !! {table} returned NO ROWS", flush=True)
            continue
        # JSONB arrives as dict/list -> store as JSON text so parquet round-trips cleanly
        for col in df.columns:
            if df[col].dtype == object and len(df) and isinstance(df[col].iloc[0], (dict, list)):
                df[col] = df[col].map(lambda v: json.dumps(v) if v is not None else None)
        path = out / f"{table}.parquet"
        df.to_parquet(path, index=False)
        print(
            f"  wrote {path}  rows={len(df):,}  "
            f"dates={df['as_of_date'].min()} -> {df['as_of_date'].max()}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
