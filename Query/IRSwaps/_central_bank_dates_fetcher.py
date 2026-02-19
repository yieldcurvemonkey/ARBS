"""Automated fetching and caching of central bank monetary policy meeting dates.

Scrapes meeting schedules from:
- Federal Reserve (FOMC): https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- ECB (Governing Council): https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
- Bank of Japan (MPM): https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm
- Bank of England (MPC): https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates
- Bank of Canada (BOC): https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/
- Swiss National Bank (SNB): https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions

Results are cached to a local JSON file and only refetched when the cache is stale
(default: 30 days). Hardcoded fallback dates are used when fetching fails.
"""

import calendar
import datetime
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MONTH_ABBR = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTH_FULL = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}

CACHE_MAX_AGE_DAYS = 30
_FETCH_TIMEOUT = 15
_CACHE_SCHEMA = 1

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Cache path helpers
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "central_bank_dates"
    except Exception:
        if os.name == "nt":
            return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "central_bank_dates"
        return Path.home() / ".cache" / "arbs" / "central_bank_dates"


def _cache_path() -> Path:
    return _cache_dir() / "meeting_dates_v1.json"


# ---------------------------------------------------------------------------
# Cache read / write
# ---------------------------------------------------------------------------

MeetingMap = Dict[str, Tuple[datetime.date, datetime.date]]
AllDatesMap = Dict[str, MeetingMap]


def _serialize_dates(dates: AllDatesMap) -> dict:
    """Convert AllDatesMap to JSON-serializable dict."""
    out: dict = {}
    for curve_id, meeting_map in dates.items():
        out[curve_id] = {label: [d[0].isoformat(), d[1].isoformat()] for label, d in meeting_map.items()}
    return out


def _deserialize_dates(raw: dict) -> AllDatesMap:
    """Convert JSON dict back to AllDatesMap."""
    out: AllDatesMap = {}
    for curve_id, meeting_map in raw.items():
        out[curve_id] = {}
        for label, pair in meeting_map.items():
            out[curve_id][label] = (
                datetime.date.fromisoformat(pair[0]),
                datetime.date.fromisoformat(pair[1]),
            )
    return out


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != _CACHE_SCHEMA:
            return False
        ts = datetime.datetime.fromisoformat(data["fetched_at"])
        age = datetime.datetime.now(datetime.timezone.utc) - ts
        return age.days < CACHE_MAX_AGE_DAYS
    except Exception:
        return False


def _load_cache(path: Path) -> Optional[AllDatesMap]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != _CACHE_SCHEMA:
            return None
        return _deserialize_dates(data["dates"])
    except Exception:
        return None


def _save_cache(path: Path, dates: AllDatesMap) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": _CACHE_SCHEMA,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "dates": _serialize_dates(dates),
        }
        tmp = path.with_suffix(f".tmp-{threading.get_ident()}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        logger.debug("Failed to save central bank dates cache", exc_info=True)


# ---------------------------------------------------------------------------
# FOMC fetcher
# ---------------------------------------------------------------------------


def _fetch_fomc_dates() -> List[datetime.date]:
    """Fetch FOMC meeting decision dates from the Federal Reserve website.

    Returns the *last day* of each FOMC meeting, sorted chronologically.
    Notation-vote-only entries are excluded.
    """
    import requests

    resp = requests.get(
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        timeout=_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ARBS)"},
    )
    resp.raise_for_status()
    html = resp.text

    meetings: List[datetime.date] = []
    panels = re.split(r'<div class="panel panel-default">', html)

    for panel in panels[1:]:
        year_match = re.search(r"(\d{4}) FOMC Meetings", panel)
        if not year_match:
            continue
        year = int(year_match.group(1))

        months = re.findall(r"fomc-meeting__month[^>]*>(.*?)</div>", panel, re.DOTALL)
        dates = re.findall(r"fomc-meeting__date[^>]*>(.*?)</div>", panel, re.DOTALL)

        months = [re.sub(r"<[^>]+>", "", m).strip() for m in months]
        dates = [re.sub(r"<[^>]+>", "", d).strip() for d in dates]

        for month_str, date_str in zip(months, dates):
            if "notation" in date_str.lower():
                continue
            date_str = date_str.replace("*", "").strip()

            # Extract the last day number from the date string
            day_match = re.search(r"(\d+)\s*$", date_str)
            if not day_match:
                continue
            end_day = int(day_match.group(1))

            # Determine month: "January" → January, "Apr/May" → May (end month)
            if "/" in month_str:
                _, end_month_str = month_str.split("/")
                end_month_str = end_month_str.strip()
            else:
                end_month_str = month_str.strip()

            month_num = _MONTH_FULL.get(end_month_str.lower())
            if month_num is None:
                month_num = _MONTH_ABBR.get(end_month_str.lower()[:3])
            if month_num is None:
                continue

            try:
                meetings.append(datetime.date(year, month_num, end_day))
            except ValueError:
                continue

    return sorted(meetings)


# ---------------------------------------------------------------------------
# ECB fetcher
# ---------------------------------------------------------------------------


def _fetch_ecb_dates() -> List[datetime.date]:
    """Fetch ECB monetary policy meeting decision dates.

    Returns the date of the press conference (Day 2 for two-day meetings,
    or the single meeting day for older one-day format).
    """
    import requests

    resp = requests.get(
        "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
        timeout=_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ARBS)"},
    )
    resp.raise_for_status()
    html = resp.text

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    meetings: List[datetime.date] = []
    seen: set = set()

    # Find entries: DD/MM/YYYY followed by description
    entries = re.findall(r"(\d{2}/\d{2}/\d{4})\s+(.*?)(?=\d{2}/\d{2}/\d{4}|$)", text)

    for date_str, description in entries:
        desc_lower = description.lower()
        # Must be a monetary-policy meeting but NOT a "non-monetary policy" meeting
        if "monetary policy" not in desc_lower or "non-monetary policy" in desc_lower:
            continue
        # We want the decision day: "Day 2" or "press conference"
        if "day 2" in desc_lower or "press conference" in desc_lower:
            day, month, year = date_str.split("/")
            try:
                dt = datetime.date(int(year), int(month), int(day))
                if dt not in seen:
                    meetings.append(dt)
                    seen.add(dt)
            except ValueError:
                continue

    # For single-day monetary policy meetings (older format without Day 1/Day 2),
    # also capture entries that don't mention "day 1"
    for date_str, description in entries:
        desc_lower = description.lower()
        if "monetary policy" not in desc_lower or "non-monetary policy" in desc_lower:
            continue
        if "day 1" in desc_lower or "day 2" in desc_lower:
            continue
        day, month, year = date_str.split("/")
        try:
            dt = datetime.date(int(year), int(month), int(day))
            if dt not in seen:
                meetings.append(dt)
                seen.add(dt)
        except ValueError:
            continue

    return sorted(meetings)


# ---------------------------------------------------------------------------
# BOJ fetcher
# ---------------------------------------------------------------------------


def _fetch_boj_dates() -> List[datetime.date]:
    """Fetch Bank of Japan monetary policy meeting decision dates.

    Returns the *last day* of each MPM, sorted chronologically.
    """
    import requests

    resp = requests.get(
        "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
        timeout=_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ARBS)"},
    )
    resp.raise_for_status()
    html = resp.text

    meetings: List[datetime.date] = []

    # Find year headings and their associated tables
    # Split HTML by <h2> or year markers to associate years with tables
    # The page has: <h2>2026</h2> ... <table>...</table> ... <h2>2025</h2> ... <table>...</table>
    year_table_pairs = re.findall(
        r"<h\d[^>]*>\s*(\d{4})\s*</h\d>.*?<table(.*?)</table>",
        html,
        re.DOTALL,
    )

    for year_str, table_html in year_table_pairs:
        year = int(year_str)

        # Extract first cell (Date of MPM) from each data row
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
            if not cells:
                continue
            first_cell = re.sub(r"<[^>]+>", "", cells[0]).strip()

            # Skip header rows
            if "Date of MPM" in first_cell or "Outlook" in first_cell or not first_cell:
                continue

            # Remove PDF references
            first_cell = re.sub(r"\[PDF[^\]]*\]", "", first_cell).strip()

            # Parse patterns:
            #   "Mon. DD (Day), DD (Day)"         → same month, second DD
            #   "Mon1. DD (Day), Mon2 DD (Day)"   → cross-month, Mon2 DD
            # The parenthesized day-of-week may have periods: "(Thurs.)" etc.

            # Cross-month pattern: "Apr. 30 (Wed.), May 1 (Thurs.)"
            cross_match = re.match(
                r"(\w+\.?)\s+\d+\s*\([^)]*\)\s*,\s*(\w+\.?)\s+(\d+)\s*\([^)]*\)",
                first_cell,
            )
            if cross_match:
                end_month_str = cross_match.group(2).rstrip(".")
                end_day = int(cross_match.group(3))
                month_num = _MONTH_ABBR.get(end_month_str.lower()[:3])
                if month_num is not None:
                    end_year = year
                    # Handle cross-year (Dec→Jan)
                    start_month_str = cross_match.group(1).rstrip(".")
                    start_month = _MONTH_ABBR.get(start_month_str.lower()[:3], 0)
                    if start_month > month_num:
                        end_year = year + 1
                    try:
                        meetings.append(datetime.date(end_year, month_num, end_day))
                    except ValueError:
                        pass
                continue

            # Same-month pattern: "Jan. 22 (Thurs.), 23 (Fri.)"
            same_match = re.match(
                r"(\w+\.?)\s+\d+\s*\([^)]*\)\s*,\s*(\d+)\s*\([^)]*\)",
                first_cell,
            )
            if same_match:
                month_str = same_match.group(1).rstrip(".")
                end_day = int(same_match.group(2))
                month_num = _MONTH_ABBR.get(month_str.lower()[:3])
                if month_num is not None:
                    try:
                        meetings.append(datetime.date(year, month_num, end_day))
                    except ValueError:
                        pass
                continue

    return sorted(meetings)


# ---------------------------------------------------------------------------
# BOE fetcher
# ---------------------------------------------------------------------------


def _fetch_boe_dates() -> List[datetime.date]:
    """Fetch Bank of England MPC announcement dates.

    Returns the decision/announcement date for each MPC meeting, sorted
    chronologically.  The BOE page lists upcoming years in tables preceded
    by headings like "2026 confirmed dates" / "2027 provisional dates".
    """
    import requests

    resp = requests.get(
        "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
        timeout=_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ARBS)"},
    )
    resp.raise_for_status()
    html = resp.text

    meetings: List[datetime.date] = []

    # The page contains year headings followed by tables.
    # Strategy: find "<hN>YYYY ...</hN>" headings, then parse the next table.
    # We split the HTML by tables and walk backwards to find the year heading.
    tables = re.findall(r"<table.*?</table>", html, re.DOTALL)

    for table in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL)

        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
            if not cells:
                continue
            first_cell = re.sub(r"<[^>]+>", " ", cells[0])
            first_cell = re.sub(r"&nbsp;", " ", first_cell).strip()

            # Skip non-MPC rows (cookie table, headers, etc.)
            # MPC rows start with a day-of-week: "Thursday 5 February"
            day_match = re.match(
                r"(?:Monday|Tuesday|Wednesday|Thursday|Friday)\s+(\d{1,2})\s+(\w+)",
                first_cell,
            )
            if not day_match:
                continue

            day = int(day_match.group(1))
            month_str = day_match.group(2).lower()
            month_num = _MONTH_FULL.get(month_str)
            if month_num is None:
                continue

            meetings.append((month_num, day))

    if not meetings:
        return []

    # Determine years from headings.
    # The page has headings like "2026 confirmed dates" and "2027 provisional dates"
    year_headings = re.findall(r"<h\d[^>]*>[^<]*?(\d{4})\s+(?:confirmed|provisional)", html)
    years = [int(y) for y in year_headings]

    if not years:
        # Fallback: try to find any 4-digit year in headings
        year_headings = re.findall(r"<h\d[^>]*>\s*(\d{4})", html)
        years = sorted(set(int(y) for y in year_headings if 2020 <= int(y) <= 2040))

    # Associate meetings with years.
    # The BOE has 8 meetings per year, and each table corresponds to one year.
    # Tables appear in the same order as the year headings.
    result: List[datetime.date] = []
    meeting_idx = 0
    for year in years:
        # Count how many meetings likely belong to this year (8 per year typically)
        year_meetings = []
        while meeting_idx < len(meetings):
            month_num, day = meetings[meeting_idx]
            # Sanity check: if we've already assigned 8+ meetings to this year,
            # the rest likely belong to the next year
            if len(year_meetings) >= 8:
                break
            try:
                year_meetings.append(datetime.date(year, month_num, day))
            except ValueError:
                pass
            meeting_idx += 1
        result.extend(year_meetings)

    return sorted(result)


# ---------------------------------------------------------------------------
# BOC fetcher
# ---------------------------------------------------------------------------


def _fetch_boc_dates() -> List[datetime.date]:
    """Fetch Bank of Canada interest rate decision dates.

    Scrapes the policy interest rate page which lists decision dates in a
    table with ``data-date`` attributes in ISO format (YYYY-MM-DD).  Returns
    all available dates sorted chronologically.
    """
    import requests

    resp = requests.get(
        "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
        timeout=_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ARBS)"},
    )
    resp.raise_for_status()
    html = resp.text

    meetings: List[datetime.date] = []
    seen: set = set()

    # The table has <th data-date="YYYY-MM-DD"> for each decision date
    for m in re.finditer(r'data-date="(\d{4}-\d{2}-\d{2})"', html):
        try:
            dt = datetime.date.fromisoformat(m.group(1))
            if dt not in seen:
                meetings.append(dt)
                seen.add(dt)
        except ValueError:
            continue

    return sorted(meetings)


# ---------------------------------------------------------------------------
# SNB fetcher
# ---------------------------------------------------------------------------


def _fetch_snb_dates() -> List[datetime.date]:
    """Fetch Swiss National Bank monetary policy assessment dates.

    Scrapes the SNB decisions page and extracts assessment dates from press
    release URLs which follow the pattern ``/pre_YYYYMMDD``.  Returns all
    available dates sorted chronologically.
    """
    import requests

    resp = requests.get(
        "https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions",
        timeout=_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ARBS)"},
    )
    resp.raise_for_status()
    html = resp.text

    meetings: List[datetime.date] = []
    seen: set = set()

    # Press release URLs follow the pattern: /pre_YYYYMMDD
    for m in re.finditer(r"/pre_(\d{4})(\d{2})(\d{2})", html):
        try:
            dt = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if dt not in seen:
                meetings.append(dt)
                seen.add(dt)
        except ValueError:
            continue

    return sorted(meetings)


# ---------------------------------------------------------------------------
# Meeting map builder
# ---------------------------------------------------------------------------


def _build_meeting_map(
    meeting_dates: List[datetime.date],
) -> MeetingMap:
    """Convert a sorted list of decision dates into {label: (effective, maturity)} format.

    Each entry spans from one meeting's decision date to the next:
        label = abbreviated month+year of the effective date (e.g., "mar25")
        effective = decision date of meeting N
        maturity  = decision date of meeting N+1
    """
    result: MeetingMap = {}
    for i in range(len(meeting_dates) - 1):
        effective = meeting_dates[i]
        maturity = meeting_dates[i + 1]
        label = effective.strftime("%b%y").lower()
        result[label] = (effective, maturity)
    return result


def _merge_meeting_maps(base: MeetingMap, overlay: MeetingMap) -> MeetingMap:
    """Merge two meeting maps, with overlay taking precedence for duplicate labels."""
    merged = dict(base)
    merged.update(overlay)
    return dict(sorted(merged.items(), key=lambda kv: kv[1][0]))


# ---------------------------------------------------------------------------
# Curve-ID to central-bank mapping
# ---------------------------------------------------------------------------

_CURVE_TO_CB = {
    "USD-SOFR-1D": "FOMC",
    "USD-FEDFUNDS": "FOMC",
    "EUR-ESTR": "ECB",
    "JPY-TONA": "BOJ",
    "GBP-SONIA": "BOE",
    "CAD-CORRA": "BOC",
    "CHF-SARON": "SNB",
}

_CB_FETCHERS = {
    "FOMC": _fetch_fomc_dates,
    "ECB": _fetch_ecb_dates,
    "BOJ": _fetch_boj_dates,
    "BOE": _fetch_boe_dates,
    "BOC": _fetch_boc_dates,
    "SNB": _fetch_snb_dates,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def fetch_central_bank_dates(
    fallback: Optional[AllDatesMap] = None,
    *,
    force_refresh: bool = False,
    cache_max_age_days: int = CACHE_MAX_AGE_DAYS,
) -> AllDatesMap:
    """Get central bank meeting date maps, using cache and web scraping.

    Strategy:
        1. If cache is fresh and not force_refresh → return cached data.
        2. Otherwise, attempt to scrape each central bank website.
        3. Merge scraped data with fallback (fallback fills gaps for
           historical dates or banks whose scrape failed).
        4. Save merged result to cache.

    Parameters
    ----------
    fallback : optional dict
        Hardcoded fallback dates (same shape as _CENTRAL_BANK_DATES).
    force_refresh : bool
        If True, ignore cache and re-scrape.
    cache_max_age_days : int
        Maximum cache age in days before re-scraping.

    Returns
    -------
    AllDatesMap
        Dict mapping curve IDs to their meeting date maps.
    """
    with _lock:
        return _fetch_central_bank_dates_locked(fallback, force_refresh, cache_max_age_days)


def _fetch_central_bank_dates_locked(
    fallback: Optional[AllDatesMap],
    force_refresh: bool,
    cache_max_age_days: int,
) -> AllDatesMap:
    cache_file = _cache_path()

    # 1. Try cache
    if not force_refresh and _cache_is_fresh(cache_file):
        cached = _load_cache(cache_file)
        if cached is not None:
            logger.debug("Loaded central bank dates from cache: %s", cache_file)
            return cached

    # 2. Scrape each central bank
    scraped_dates: Dict[str, List[datetime.date]] = {}
    for cb_name, fetcher in _CB_FETCHERS.items():
        try:
            dates = fetcher()
            if dates:
                scraped_dates[cb_name] = dates
                logger.debug("Fetched %d %s meeting dates", len(dates), cb_name)
        except Exception:
            logger.debug("Failed to fetch %s dates", cb_name, exc_info=True)

    # 3. Build meeting maps from scraped dates
    scraped_maps: AllDatesMap = {}
    for curve_id, cb_name in _CURVE_TO_CB.items():
        if cb_name in scraped_dates:
            scraped_maps[curve_id] = _build_meeting_map(scraped_dates[cb_name])

    # 4. Merge with fallback
    if fallback is None:
        fallback = {}

    result: AllDatesMap = {}
    all_curve_ids = set(list(fallback.keys()) + list(scraped_maps.keys()))
    for curve_id in all_curve_ids:
        fb = fallback.get(curve_id, {})
        sc = scraped_maps.get(curve_id, {})
        result[curve_id] = _merge_meeting_maps(fb, sc)

    # 5. Save to cache (only if we scraped at least something)
    if scraped_dates:
        _save_cache(cache_file, result)

    return result
