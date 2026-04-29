"""Prime the SFR Convex Screener on-disk cache one as_of at a time.

Sequential primer that walks a date range, calls
``RVUtils.SFRConvexScreener.build_snapshot`` per date, and persists each
result via ``SnapshotCache``. Designed for cache priming work that has to
survive Barchart 429 storms — every snapshot is committed to disk before
the next one starts so a crash mid-priming doesn't lose the work.

Usage::

    conda run -n stir python scripts/prime_screener_cache.py \\
        --start 2025-10-28 --end 2026-04-28
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
import time
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("prime_cache")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
)
from RVUtils.SFRConvexScreener._backtest_cache import (  # noqa: E402
    SnapshotCache,
    snapshot_cache_key,
)
from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache  # noqa: E402
from RVUtils.SFRConvexScreener.screener import build_snapshot  # noqa: E402


def _make_screener_cfg() -> SFRConvexScreenerConfig:
    return SFRConvexScreenerConfig(
        universe_size=12,
        include_outrights=True,
        jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        correlation_window=60,
        n_simulations=50_000,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="ISO start date")
    p.add_argument("--end", required=True, help="ISO end date")
    p.add_argument("--cache-root", default="data/screener_results/sfr_convex_screener_backtest_cache")
    args = p.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    dates = sorted(d.date() for d in pd.bdate_range(start, end))
    cfg = _make_screener_cfg()
    cache = SnapshotCache(root=args.cache_root)
    cs = _config_summary_for_cache(cfg)
    logger.info("priming %d dates [%s -> %s] | cache_root=%s",
                len(dates), start, end, args.cache_root)

    n_hit = 0
    n_built = 0
    n_failed = 0
    t0 = time.monotonic()
    for d in dates:
        if cache.get(d, cs) is not None:
            n_hit += 1
            logger.info("%s | cache HIT (%d/%d)", d, n_hit + n_built + n_failed, len(dates))
            continue
        ts = time.monotonic()
        try:
            snap = build_snapshot(cfg, as_of=d)
        except Exception as exc:  # noqa: BLE001
            n_failed += 1
            logger.warning("%s | build FAILED after %.0fs: %r",
                           d, time.monotonic() - ts, exc)
            continue
        cache.put(snap, cs)
        n_built += 1
        elapsed = time.monotonic() - ts
        total_elapsed = time.monotonic() - t0
        logger.info(
            "%s | built+cached in %.0fs (total elapsed %.0fs, %d/%d done)",
            d, elapsed, total_elapsed, n_hit + n_built + n_failed, len(dates),
        )

    total = time.monotonic() - t0
    logger.info("PRIME DONE: %d hit, %d built, %d failed in %.0fs",
                n_hit, n_built, n_failed, total)
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
