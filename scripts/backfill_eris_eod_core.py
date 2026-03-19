from __future__ import annotations

import argparse
import datetime
import logging
from typing import Iterable

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _chunked(values: Iterable[datetime.date], size: int) -> list[list[datetime.date]]:
    batch: list[datetime.date] = []
    out: list[list[datetime.date]] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            out.append(batch)
            batch = []
    if batch:
        out.append(batch)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill ERIS EOD raw + analytics into CORE")
    parser.add_argument("--curve-name", default="USD-SOFR-1D")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; defaults to earliest local cache day")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher

    store = CurveStore.default()
    fetcher = ErisFuturesFetcher(force_refresh=bool(args.force_refresh))

    local_dates = sorted(store.available_dates(args.curve_name))
    if args.start:
        start_date = datetime.date.fromisoformat(args.start)
    elif local_dates:
        start_date = local_dates[0]
    else:
        raise SystemExit("No local ERIS CurveStore dates found; pass --start to fetch a range.")

    end_date = datetime.date.fromisoformat(args.end) if args.end else datetime.date.today()
    bdates = [d.date() for d in pd.bdate_range(start_date, end_date)]
    if not bdates:
        logger.info("No business dates in range %s -> %s", start_date, end_date)
        return

    logger.info(
        "Backfilling ERIS EOD CORE for %s: %s -> %s (%d business days, batch_size=%d)",
        args.curve_name,
        start_date,
        end_date,
        len(bdates),
        args.batch_size,
    )

    if args.dry_run:
        logger.info("Dry run only; first batch: %s", bdates[: min(len(bdates), args.batch_size)])
        return

    curve_id = f"ERIS_EOD_LIVE-RL_BASIC-{args.curve_name}-bulk"
    batches = _chunked(bdates, max(1, int(args.batch_size)))
    for idx, batch in enumerate(batches, start=1):
        logger.info(
            "Fetching batch %d/%d: %s -> %s (%d days)",
            idx,
            len(batches),
            batch[0],
            batch[-1],
            len(batch),
        )
        fetcher.fetch_intraday_discount_curve(
            curve_id=curve_id,
            bdates=batch,
            show_tqdm=True,
            return_intraday_timestamp=False,
        )
        store.wait_for_background_pushes(timeout=300.0)

    logger.info("ERIS EOD CORE backfill complete.")


if __name__ == "__main__":
    main()
