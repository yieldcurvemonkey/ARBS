"""Warm the UST futures pricer + delivery basket caches.

Replaces scripts/_ustf_cache_warmer.py, which only warmed the price
timeseries. The SDR invoice-swap enrichment in
``_build_invoice_swap_lookup`` also needs the delivery-basket cache
(``USTFutureDeliveryBasket_Cache``); without it the
"FETCHING DELIVERY BASKETS..." stage runs ~15s per root even when the
price cache is hot.

Usage:

    # Daily warm (today only — matches the incremental SDR ingest)
    python scripts/warm_ustf_cache.py

    # Warm a window ending today (e.g. before a multi-day backfill)
    python scripts/warm_ustf_cache.py --backfill-days 7

    # Warm specific backfill dates (matches `pipeline backfill --date`)
    python scripts/warm_ustf_cache.py --target-dates 2026-04-09
    python scripts/warm_ustf_cache.py --target-dates 2026-04-09,2026-04-10

    # Restrict to a subset of roots
    python scripts/warm_ustf_cache.py --roots TY,US,WN

    # Force refresh (rebuild both caches)
    python scripts/warm_ustf_cache.py --force
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
from typing import List

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ustf-warmer")

# Import after sys.path setup so the repo modules resolve.
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP  # noqa: E402
from MDP.USTFutures.treasury_conversion_factors import resolve_delivery_contract  # noqa: E402
from TB.USTFuturesTB import USTFuturesTB  # noqa: E402
from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: E402
from Query.USTFutures.USTFutureQuery import USTFutureQuery  # noqa: E402
from Query.USTFutures.USTFutureValue import USTFutureValue  # noqa: E402

_DEFAULT_ROOTS = ("TU", "FV", "TY", "UXY", "US", "WN")
_IMM_MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}
_USTS_MDP_SOURCES = ("USTS_FEDINVEST_WSJ_LIVE-RL", "USTS_TRADINGVIEW_LIVE-RL")


def _front_month_symbol(root: str, as_of: datetime.date) -> str:
    _, imm_date, _ = resolve_delivery_contract(root, as_of)
    mc = _IMM_MONTH_CODE[imm_date.month]
    return f"{root}{mc}{imm_date.year % 100:02d}"


def _warm_price_timeseries(
    mdp: USTFuturesMDP,
    symbols: List[str],
    start: datetime.date,
    end: datetime.date,
) -> None:
    """Warm the computed-timeseries cache for futures prices."""
    if not symbols:
        return
    tb = TimeseriesBuilder(ustfutures_tb=USTFuturesTB(mdp, show_tqdm=True))
    queries = [USTFutureQuery(symbol=s, value=USTFutureValue.PRICE) for s in symbols]
    log.info("Warming prices: %s -> %s for %s", start, end, symbols)
    df = tb.get_timeseries(start=start, end=end, queries=queries, n_jobs=1)
    log.info("Price warm complete: shape=%s", df.shape)


def _warm_delivery_baskets(
    mdp: USTFuturesMDP,
    roots: List[str],
    as_of_days: List[datetime.date],
    *,
    force: bool,
) -> int:
    """Warm the delivery-basket cache, UST pricer cache, and FRB cash-bond cache
    along the exact path used by ``_build_invoice_swap_lookup``.

    Uses ``mdp.get_pricer(include_basket=True)`` rather than the lower-level
    ``get_delivery_basket`` so the UST pricer cache also gets populated for
    the specific ``(timestamp=as_of, symbol, source)`` key that the SDR
    invoice lookup reads. Warming only the basket cache still leaves
    ``get_pricer`` to fetch Barchart prices on first use.

    Returns the number of (root, as_of) pairs that failed to warm.
    """
    failures = 0
    for as_of in as_of_days:
        for root in roots:
            try:
                symbol = _front_month_symbol(root, as_of)
            except Exception as exc:
                log.warning("Failed to resolve front-month for %s @ %s: %s", root, as_of, exc)
                failures += 1
                continue

            warmed = False
            for usts_src in _USTS_MDP_SOURCES:
                try:
                    mdp.get_pricer(
                        request={
                            "symbols": [symbol],
                            "timestamp": as_of,
                            "usts_mdp_source": usts_src,
                            "include_basket": True,
                            "force_refresh": force,
                        }
                    )
                    warmed = True
                    log.info("Basket+pricer warmed: %s @ %s via %s", symbol, as_of, usts_src)
                    break
                except Exception as exc:
                    log.debug("Basket warm failed (%s / %s): %s", symbol, usts_src, exc)
                    continue
            if not warmed:
                failures += 1
                log.warning("Basket warm failed for %s @ %s (all sources)", symbol, as_of)
    return failures


def _business_days(end: datetime.date, count: int) -> List[datetime.date]:
    """Return the last ``count`` business days ending at ``end`` (inclusive).

    Used for basket warming so we cover the set of as_of dates the SDR pipeline
    is likely to query. Prices are warmed across a calendar window separately.
    """
    if count <= 1:
        return [end]
    window_start = end - datetime.timedelta(days=max(count * 2, 14))
    bdays = pd.bdate_range(start=window_start, end=end).date.tolist()
    return bdays[-count:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--roots",
        type=lambda s: [r.strip().upper() for r in s.split(",") if r.strip()],
        default=list(_DEFAULT_ROOTS),
        help=f"Comma-separated contract roots (default: {','.join(_DEFAULT_ROOTS)}).",
    )
    parser.add_argument(
        "--price-window-days",
        type=int,
        default=7,
        help="Days of price history to warm (calendar days, default: 7).",
    )
    parser.add_argument(
        "--basket-days",
        type=int,
        default=1,
        help="Number of business days (ending today) to warm delivery baskets for (default: 1).",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=None,
        help="Shortcut: set both --price-window-days and --basket-days to this value.",
    )
    parser.add_argument(
        "--target-dates",
        type=lambda s: [datetime.date.fromisoformat(d.strip()) for d in s.split(",") if d.strip()],
        default=None,
        help=(
            "Comma-separated ISO dates to warm (e.g. 2026-04-09 or 2026-04-09,2026-04-10). "
            "When set, overrides --basket-days / --backfill-days for basket warming and "
            "covers the price-timeseries window to span the earliest target through today."
        ),
    )
    parser.add_argument(
        "--skip-prices",
        action="store_true",
        help="Skip the price-timeseries warm (only warm baskets).",
    )
    parser.add_argument(
        "--skip-baskets",
        action="store_true",
        help="Skip the delivery-basket warm (legacy behavior).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild of warmed entries even if present.",
    )
    args = parser.parse_args()

    if args.backfill_days is not None:
        if args.backfill_days <= 0:
            parser.error("--backfill-days must be > 0")
        args.price_window_days = args.backfill_days
        args.basket_days = args.backfill_days

    today = datetime.date.today()

    if args.target_dates:
        target_dates = sorted(set(args.target_dates))
        basket_days = target_dates
        earliest = target_dates[0]
        # Cover the whole span earliest..today so the price-timeseries cache
        # hits for any as_of in the requested set (prices are warmed as a
        # continuous calendar window; baskets only for the specific dates).
        span_days = max((today - earliest).days, args.price_window_days)
        price_start = today - datetime.timedelta(days=span_days)
    else:
        basket_days = _business_days(today, args.basket_days)
        price_start = today - datetime.timedelta(days=args.price_window_days)

    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")

    symbol_as_of = basket_days[-1] if basket_days else today
    symbols: List[str] = []
    for root in args.roots:
        try:
            symbols.append(_front_month_symbol(root, symbol_as_of))
        except Exception as exc:
            log.warning("Failed to resolve front-month for %s: %s", root, exc)

    if not args.skip_prices:
        _warm_price_timeseries(mdp, symbols, price_start, today)

    basket_failures = 0
    if not args.skip_baskets:
        basket_failures = _warm_delivery_baskets(
            mdp, args.roots, basket_days, force=args.force
        )

    log.info(
        "Warm complete: roots=%s, price_window=%s->%s, basket_days=%s, basket_failures=%d",
        args.roots,
        price_start,
        today,
        basket_days,
        basket_failures,
    )
    return 1 if basket_failures else 0


if __name__ == "__main__":
    sys.exit(main())
