"""Fetch ONE day's CFTC cumulative RATES zip straight from DTCC, no cache, no window filter.

Uses DTCCFetcher._fetch_dtcc_sdr_data_helper + _extract_dataframes_from_zip, which
never touch the parquet cache and never apply the Execution-Timestamp window filter
that fetch_historical_reports applies before _save_daily_dict persists.
"""
import asyncio, sys
from pathlib import Path
import httpx
import pandas as pd

sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from SDRUtils.data.builder import DTCCFetcher

OUT = Path(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_zip")
OUT.mkdir(parents=True, exist_ok=True)

DATES = sys.argv[1:] or ["2026_06_16"]


async def main():
    f = DTCCFetcher(error_verbose=True, warning_verbose=True)
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    async with httpx.AsyncClient(limits=limits, timeout=120, verify=False, http2=True) as client:
        for ds in DATES:
            print("fetching", ds, flush=True)
            buf = await f._fetch_dtcc_sdr_data_helper(
                client=client, date_string=ds, agency="CFTC", asset_class="RATES",
                max_retries=3, backoff_factor=2,
            )
            if buf is None:
                print("  FAILED / 404", ds)
                continue
            dfs = f._extract_dataframes_from_zip(buf, convert_key_into_dt=False,
                                                 parallelize=False, use_pyarrow=True)
            for k, df in dfs.items():
                print("  member", k, "rows", len(df), "cols", len(df.columns))
                fp = OUT / f"{ds}_UNFILTERED.parquet"
                df.to_parquet(fp, index=False)
                print("  wrote", fp)


asyncio.run(main())
