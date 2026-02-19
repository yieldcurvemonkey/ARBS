import datetime
import logging

from definitions.IRSwaps import CURVE_DEFINITIONS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded fallback dates.
#
# These serve as the baseline when web scraping is unavailable or returns
# incomplete data (e.g. the ECB page only shows the current year, and past
# meetings are removed).  The automated fetcher merges scraped data on top
# of this, so any *new* meetings announced by central banks are picked up
# automatically while historical data is preserved.
# ---------------------------------------------------------------------------

_FALLBACK_DATES = {
    "USD-SOFR-1D": {
        "feb23": (datetime.date(2023, 2, 1), datetime.date(2023, 3, 22)),
        "mar23": (datetime.date(2023, 3, 22), datetime.date(2023, 5, 3)),
        "may23": (datetime.date(2023, 5, 3), datetime.date(2023, 6, 14)),
        "jun23": (datetime.date(2023, 6, 14), datetime.date(2023, 7, 26)),
        "jul23": (datetime.date(2023, 7, 26), datetime.date(2023, 9, 20)),
        "sep23": (datetime.date(2023, 9, 20), datetime.date(2023, 11, 1)),
        "nov23": (datetime.date(2023, 11, 1), datetime.date(2023, 12, 13)),
        "dec23": (datetime.date(2023, 12, 13), datetime.date(2024, 1, 31)),
        "jan24": (datetime.date(2024, 1, 31), datetime.date(2024, 3, 20)),
        "mar24": (datetime.date(2024, 3, 20), datetime.date(2024, 5, 1)),
        "may24": (datetime.date(2024, 5, 1), datetime.date(2024, 6, 12)),
        "jun24": (datetime.date(2024, 6, 12), datetime.date(2024, 7, 31)),
        "jul24": (datetime.date(2024, 7, 31), datetime.date(2024, 9, 18)),
        "sep24": (datetime.date(2024, 9, 18), datetime.date(2024, 11, 7)),
        "nov24": (datetime.date(2024, 11, 7), datetime.date(2024, 12, 18)),
        "dec24": (datetime.date(2024, 12, 18), datetime.date(2025, 1, 29)),
        "jan25": (datetime.date(2025, 1, 29), datetime.date(2025, 3, 19)),
        "mar25": (datetime.date(2025, 3, 19), datetime.date(2025, 5, 7)),
        "may25": (datetime.date(2025, 5, 7), datetime.date(2025, 6, 18)),
        "jun25": (datetime.date(2025, 6, 18), datetime.date(2025, 7, 30)),
        "jul25": (datetime.date(2025, 7, 30), datetime.date(2025, 9, 17)),
        "sep25": (datetime.date(2025, 9, 17), datetime.date(2025, 10, 29)),
        "oct25": (datetime.date(2025, 10, 29), datetime.date(2025, 12, 10)),
        "dec25": (datetime.date(2025, 12, 10), datetime.date(2026, 1, 28)),
        "jan26": (datetime.date(2026, 1, 28), datetime.date(2026, 3, 18)),
        "mar26": (datetime.date(2026, 3, 18), datetime.date(2026, 4, 29)),
        "apr26": (datetime.date(2026, 4, 29), datetime.date(2026, 6, 17)),
        "jun26": (datetime.date(2026, 6, 17), datetime.date(2026, 7, 29)),
        "jul26": (datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)),
        "sep26": (datetime.date(2026, 9, 16), datetime.date(2026, 10, 28)),
        "oct26": (datetime.date(2026, 10, 28), datetime.date(2026, 12, 9)),
        "dec26": (datetime.date(2026, 12, 9), datetime.date(2027, 1, 27)),
        "jan27": (datetime.date(2027, 1, 27), datetime.date(2027, 3, 17)),
        "mar27": (datetime.date(2027, 3, 17), datetime.date(2027, 4, 28)),
        "apr27": (datetime.date(2027, 4, 28), datetime.date(2027, 6, 9)),
        "jun27": (datetime.date(2027, 6, 9), datetime.date(2027, 7, 28)),
        "jul27": (datetime.date(2027, 7, 28), datetime.date(2027, 9, 15)),
        "sep27": (datetime.date(2027, 9, 15), datetime.date(2027, 10, 27)),
        "oct27": (datetime.date(2027, 10, 27), datetime.date(2027, 12, 8)),
        "dec27": (datetime.date(2027, 12, 8), datetime.date(2028, 1, 26)),
    },
    "USD-FEDFUNDS": {
        "feb23": (datetime.date(2023, 2, 1), datetime.date(2023, 3, 22)),
        "mar23": (datetime.date(2023, 3, 22), datetime.date(2023, 5, 3)),
        "may23": (datetime.date(2023, 5, 3), datetime.date(2023, 6, 14)),
        "jun23": (datetime.date(2023, 6, 14), datetime.date(2023, 7, 26)),
        "jul23": (datetime.date(2023, 7, 26), datetime.date(2023, 9, 20)),
        "sep23": (datetime.date(2023, 9, 20), datetime.date(2023, 11, 1)),
        "nov23": (datetime.date(2023, 11, 1), datetime.date(2023, 12, 13)),
        "dec23": (datetime.date(2023, 12, 13), datetime.date(2024, 1, 31)),
        "jan24": (datetime.date(2024, 1, 31), datetime.date(2024, 3, 20)),
        "mar24": (datetime.date(2024, 3, 20), datetime.date(2024, 5, 1)),
        "may24": (datetime.date(2024, 5, 1), datetime.date(2024, 6, 12)),
        "jun24": (datetime.date(2024, 6, 12), datetime.date(2024, 7, 31)),
        "jul24": (datetime.date(2024, 7, 31), datetime.date(2024, 9, 18)),
        "sep24": (datetime.date(2024, 9, 18), datetime.date(2024, 11, 7)),
        "nov24": (datetime.date(2024, 11, 7), datetime.date(2024, 12, 18)),
        "dec24": (datetime.date(2024, 12, 18), datetime.date(2025, 1, 29)),
        "jan25": (datetime.date(2025, 1, 29), datetime.date(2025, 3, 19)),
        "mar25": (datetime.date(2025, 3, 19), datetime.date(2025, 5, 7)),
        "may25": (datetime.date(2025, 5, 7), datetime.date(2025, 6, 18)),
        "jun25": (datetime.date(2025, 6, 18), datetime.date(2025, 7, 30)),
        "jul25": (datetime.date(2025, 7, 30), datetime.date(2025, 9, 17)),
        "sep25": (datetime.date(2025, 9, 17), datetime.date(2025, 10, 29)),
        "oct25": (datetime.date(2025, 10, 29), datetime.date(2025, 12, 10)),
        "dec25": (datetime.date(2025, 12, 10), datetime.date(2026, 1, 28)),
        "jan26": (datetime.date(2026, 1, 28), datetime.date(2026, 3, 18)),
        "mar26": (datetime.date(2026, 3, 18), datetime.date(2026, 4, 29)),
        "apr26": (datetime.date(2026, 4, 29), datetime.date(2026, 6, 17)),
        "jun26": (datetime.date(2026, 6, 17), datetime.date(2026, 7, 29)),
        "jul26": (datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)),
        "sep26": (datetime.date(2026, 9, 16), datetime.date(2026, 10, 28)),
        "oct26": (datetime.date(2026, 10, 28), datetime.date(2026, 12, 9)),
        "dec26": (datetime.date(2026, 12, 9), datetime.date(2027, 1, 27)),
        "jan27": (datetime.date(2027, 1, 27), datetime.date(2027, 3, 17)),
        "mar27": (datetime.date(2027, 3, 17), datetime.date(2027, 4, 28)),
        "apr27": (datetime.date(2027, 4, 28), datetime.date(2027, 6, 9)),
        "jun27": (datetime.date(2027, 6, 9), datetime.date(2027, 7, 28)),
        "jul27": (datetime.date(2027, 7, 28), datetime.date(2027, 9, 15)),
        "sep27": (datetime.date(2027, 9, 15), datetime.date(2027, 10, 27)),
        "oct27": (datetime.date(2027, 10, 27), datetime.date(2027, 12, 8)),
        "dec27": (datetime.date(2027, 12, 8), datetime.date(2028, 1, 26)),
    },
    "EUR-ESTR": {
        "feb23": (datetime.date(2023, 2, 2), datetime.date(2023, 3, 16)),
        "mar23": (datetime.date(2023, 3, 16), datetime.date(2023, 5, 4)),
        "may23": (datetime.date(2023, 5, 4), datetime.date(2023, 6, 15)),
        "jun23": (datetime.date(2023, 6, 15), datetime.date(2023, 7, 27)),
        "jul23": (datetime.date(2023, 7, 27), datetime.date(2023, 9, 14)),
        "sep23": (datetime.date(2023, 9, 14), datetime.date(2023, 10, 26)),
        "oct23": (datetime.date(2023, 10, 26), datetime.date(2023, 12, 14)),
        "dec23": (datetime.date(2023, 12, 14), datetime.date(2024, 1, 25)),
        "jan24": (datetime.date(2024, 1, 25), datetime.date(2024, 3, 7)),
        "mar24": (datetime.date(2024, 3, 7), datetime.date(2024, 4, 11)),
        "apr24": (datetime.date(2024, 4, 11), datetime.date(2024, 6, 6)),
        "jun24": (datetime.date(2024, 6, 6), datetime.date(2024, 7, 18)),
        "jul24": (datetime.date(2024, 7, 18), datetime.date(2024, 9, 12)),
        "sep24": (datetime.date(2024, 9, 12), datetime.date(2024, 10, 17)),
        "oct24": (datetime.date(2024, 10, 17), datetime.date(2024, 12, 12)),
        "dec24": (datetime.date(2024, 12, 12), datetime.date(2025, 1, 30)),
        "jan25": (datetime.date(2025, 1, 30), datetime.date(2025, 3, 6)),
        "mar25": (datetime.date(2025, 3, 6), datetime.date(2025, 4, 17)),
        "apr25": (datetime.date(2025, 4, 17), datetime.date(2025, 6, 5)),
        "jun25": (datetime.date(2025, 6, 5), datetime.date(2025, 7, 24)),
        "jul25": (datetime.date(2025, 7, 24), datetime.date(2025, 9, 11)),
        "sep25": (datetime.date(2025, 9, 11), datetime.date(2025, 10, 30)),
        "oct25": (datetime.date(2025, 10, 30), datetime.date(2025, 12, 18)),
        "dec25": (datetime.date(2025, 12, 18), datetime.date(2026, 2, 5)),
        "feb26": (datetime.date(2026, 2, 5), datetime.date(2026, 3, 19)),
        "mar26": (datetime.date(2026, 3, 19), datetime.date(2026, 4, 30)),
        "apr26": (datetime.date(2026, 4, 30), datetime.date(2026, 6, 11)),
        "jun26": (datetime.date(2026, 6, 11), datetime.date(2026, 7, 23)),
        "jul26": (datetime.date(2026, 7, 23), datetime.date(2026, 9, 10)),
        "sep26": (datetime.date(2026, 9, 10), datetime.date(2026, 10, 29)),
        "oct26": (datetime.date(2026, 10, 29), datetime.date(2026, 12, 17)),
        "dec26": (datetime.date(2026, 12, 17), datetime.date(2027, 1, 27)),
    },
    "JPY-TONA": {
        "jan23": (datetime.date(2023, 1, 18), datetime.date(2023, 3, 10)),
        "mar23": (datetime.date(2023, 3, 10), datetime.date(2023, 4, 28)),
        "apr23": (datetime.date(2023, 4, 28), datetime.date(2023, 6, 16)),
        "jun23": (datetime.date(2023, 6, 16), datetime.date(2023, 7, 28)),
        "jul23": (datetime.date(2023, 7, 28), datetime.date(2023, 9, 22)),
        "sep23": (datetime.date(2023, 9, 22), datetime.date(2023, 10, 31)),
        "oct23": (datetime.date(2023, 10, 31), datetime.date(2023, 12, 19)),
        "dec23": (datetime.date(2023, 12, 19), datetime.date(2024, 1, 23)),
        "jan24": (datetime.date(2024, 1, 23), datetime.date(2024, 3, 19)),
        "mar24": (datetime.date(2024, 3, 19), datetime.date(2024, 4, 26)),
        "apr24": (datetime.date(2024, 4, 26), datetime.date(2024, 6, 14)),
        "jun24": (datetime.date(2024, 6, 14), datetime.date(2024, 7, 31)),
        "jul24": (datetime.date(2024, 7, 31), datetime.date(2024, 9, 20)),
        "sep24": (datetime.date(2024, 9, 20), datetime.date(2024, 10, 31)),
        "oct24": (datetime.date(2024, 10, 31), datetime.date(2024, 12, 19)),
        "dec24": (datetime.date(2024, 12, 19), datetime.date(2025, 1, 24)),
        "jan25": (datetime.date(2025, 1, 24), datetime.date(2025, 3, 19)),
        "mar25": (datetime.date(2025, 3, 19), datetime.date(2025, 5, 1)),
        "may25": (datetime.date(2025, 5, 1), datetime.date(2025, 6, 17)),
        "jun25": (datetime.date(2025, 6, 17), datetime.date(2025, 7, 31)),
        "jul25": (datetime.date(2025, 7, 31), datetime.date(2025, 9, 19)),
        "sep25": (datetime.date(2025, 9, 19), datetime.date(2025, 10, 30)),
        "oct25": (datetime.date(2025, 10, 30), datetime.date(2025, 12, 19)),
        "dec25": (datetime.date(2025, 12, 19), datetime.date(2026, 1, 23)),
        "jan26": (datetime.date(2026, 1, 23), datetime.date(2026, 3, 19)),
        "mar26": (datetime.date(2026, 3, 19), datetime.date(2026, 4, 28)),
        "apr26": (datetime.date(2026, 4, 28), datetime.date(2026, 6, 16)),
        "jun26": (datetime.date(2026, 6, 16), datetime.date(2026, 7, 31)),
        "jul26": (datetime.date(2026, 7, 31), datetime.date(2026, 9, 18)),
        "sep26": (datetime.date(2026, 9, 18), datetime.date(2026, 10, 30)),
        "oct26": (datetime.date(2026, 10, 30), datetime.date(2026, 12, 18)),
        "dec26": (datetime.date(2026, 12, 18), datetime.date(2027, 1, 27)),
    },
}


# ---------------------------------------------------------------------------
# Load dates: try cache/scrape, merge with fallback
# ---------------------------------------------------------------------------


def _load_central_bank_dates():
    """Load central bank dates from cache/web, falling back to hardcoded data."""
    try:
        from Query.IRSwaps._central_bank_dates_fetcher import fetch_central_bank_dates

        return fetch_central_bank_dates(fallback=_FALLBACK_DATES)
    except Exception:
        logger.debug("Central bank date auto-fetch unavailable, using fallback", exc_info=True)
        return _FALLBACK_DATES


_CENTRAL_BANK_DATES = _load_central_bank_dates()
