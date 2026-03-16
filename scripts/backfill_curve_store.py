"""One-time backfill: local CurveStore Parquet -> Supabase.

Usage:
    python scripts/backfill_curve_store.py [--dry-run] [--curve-name USD-SOFR-1D]
"""

from __future__ import annotations

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill CurveStore to Supabase")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--curve-name", type=str, default=None, help="Backfill only this curve")
    args = parser.parse_args()

    from Caching.curve_store import CurveStore
    from Caching.supabase_curve_sync import SupabaseCurveSync
    from Caching.supabase_engine import get_engine
    from Caching.curve_tag_config import load_event_calendar
    from pathlib import Path

    engine = get_engine()
    if engine is None:
        logger.error("Supabase cache engine disabled or unavailable — cannot backfill.")
        return

    store = CurveStore.default()
    sync = SupabaseCurveSync(base_dir=store.base_dir, engine=engine)

    # Load event calendar
    cal_path = Path(__file__).resolve().parent.parent / "config" / "event_calendar.yaml"
    event_calendar = load_event_calendar(cal_path)

    # List curves
    raw_dir = store.base_dir / "raw"
    if not raw_dir.exists():
        logger.info("No raw data found at %s", raw_dir)
        return

    curves = []
    for d in sorted(raw_dir.iterdir()):
        if d.name.startswith("asset="):
            curve_name = d.name[6:]
            if args.curve_name and curve_name != args.curve_name:
                continue
            curves.append(curve_name)

    logger.info("Backfilling %d curves", len(curves))
    total = 0
    for curve_name in curves:
        dates = store.available_dates(curve_name)
        logger.info("%s: %d dates to backfill", curve_name, len(dates))
        for dt in dates:
            if args.dry_run:
                total += 1
                continue
            try:
                sync.push_day(curve_name, dt, event_calendar=event_calendar)
                total += 1
            except Exception:
                logger.warning("Failed to push %s/%s", curve_name, dt, exc_info=True)

    logger.info("Backfill complete: %d day-blobs pushed", total)


if __name__ == "__main__":
    main()
