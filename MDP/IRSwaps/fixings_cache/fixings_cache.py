# ABOUTME: Cache layer for interest rate fixings data with smart fallback and cleanup.
# ABOUTME: Fetches fixings from live sources, validates against expected business days, and manages dated cache directories.
from pathlib import Path
import datetime
from typing import Optional, Literal
import os

import polars as pl

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FixingsFetcher import FixingsFetcher

# US Federal Holidays (minimal set for business day calculations)
# New Year's Day, MLK Day, Presidents Day, Memorial Day, Independence Day,
# Labor Day, Columbus Day, Veterans Day, Thanksgiving, Christmas
_FEDERAL_HOLIDAYS_2020_2030 = {
    # This is a simplified implementation - in production, use the holidays library
    datetime.date(2024, 1, 1), datetime.date(2024, 1, 15), datetime.date(2024, 2, 19),
    datetime.date(2024, 5, 27), datetime.date(2024, 7, 4), datetime.date(2024, 9, 2),
    datetime.date(2024, 10, 14), datetime.date(2024, 11, 11), datetime.date(2024, 11, 28),
    datetime.date(2024, 12, 25),
    datetime.date(2025, 1, 1), datetime.date(2025, 1, 20), datetime.date(2025, 2, 17),
    datetime.date(2025, 5, 26), datetime.date(2025, 7, 4), datetime.date(2025, 9, 1),
    datetime.date(2025, 10, 13), datetime.date(2025, 11, 11), datetime.date(2025, 11, 27),
    datetime.date(2025, 12, 25),
}

_KEEP_LAST_N_DATED_DIRS = 3  # retain recent caches for fallback


def _is_business_day(d: datetime.date) -> bool:
    """Check if date is a US business day (Mon-Fri, not a federal holiday)."""
    # Weekend check
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    # Holiday check
    if d in _FEDERAL_HOLIDAYS_2020_2030:
        return False
    # If holiday falls on weekend, it's typically observed on adjacent weekday
    # For simplicity, we're using the minimal set above
    return True


def _last_usbd_before(d: datetime.date) -> datetime.date:
    """Get the last US business day before the given date."""
    current = d - datetime.timedelta(days=1)
    while not _is_business_day(current):
        current -= datetime.timedelta(days=1)
    return current


def _has_date(df: Optional[pl.DataFrame], target: datetime.date, date_col: str) -> bool:
    """Check if target date exists in the date column of the DataFrame."""
    if df is None or df.is_empty():
        return False
    try:
        # Extract dates and convert to date objects for comparison
        dates = df[date_col].dt.date()
        return target in dates.to_list()
    except Exception:
        return False


def _read_cached_if_valid(root: Path, curve_name: str, expected_dt: datetime.date) -> Optional[pl.DataFrame]:
    """Read cached fixings DataFrame if valid and contains expected date."""
    dated_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)  # newest first
    for d in dated_dirs:
        csvs = sorted(d.glob("*.csv"))
        if not csvs:
            continue
        try:
            dfs = [pl.read_csv(p) for p in csvs]
            df = pl.concat(dfs)
            if curve_name not in df.columns or "Fixing" not in df.columns:
                continue

            # Parse the date column - handle various date formats flexibly
            try:
                df = df.with_columns(
                    pl.col(curve_name).str.strptime(pl.Datetime, strict=False)
                )
            except Exception:
                # If strptime fails, try direct conversion
                df = df.with_columns(
                    pl.col(curve_name).cast(pl.Datetime, strict=False)
                )

            # Remove duplicates based on date column, keeping first occurrence
            df = df.unique(subset=[curve_name], keep="first")

            if _has_date(df, expected_dt, curve_name):
                return df
        except Exception:
            # ignore malformed/partial cache files
            continue
    return None


def _cleanup_old_cache_dirs(root: Path, keep_last: int = _KEEP_LAST_N_DATED_DIRS) -> None:
    # Keep only the most recent N date folders; remove older ones if empty after file cleanup.
    dated_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
    for d in dated_dirs[keep_last:]:
        # best-effort remove CSVs; if something else is there, we leave it
        for p in d.glob("*.csv"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            # remove dir if now empty
            next(d.iterdir())
        except StopIteration:
            try:
                d.rmdir()
            except Exception:
                pass


try:
    from platformdirs import user_cache_dir as _user_cache_dir
except Exception:
    _user_cache_dir = None


def _resolve_fixings_cache_dir(curve_name: str, base_cache_dir: Optional[str | Path] = None) -> Path:
    """
    Resolve an OS-appropriate, user-agnostic cache directory with sensible fallbacks.

    Priority:
      1) base_cache_dir argument (if provided)
      2) $ARBS_CACHE_DIR environment variable
      3) platformdirs.user_cache_dir("ARBS/MDP/IRSwaps")
      4) ~/.cache/arbs/MDP/IRSwaps  (cross-platform fallback)
    """
    if base_cache_dir:
        base = Path(base_cache_dir)
    elif os.getenv("ARBS_CACHE_DIR"):
        base = Path(os.getenv("ARBS_CACHE_DIR"))
    elif _user_cache_dir:
        base = Path(_user_cache_dir(appname="ARBS/MDP/IRSwaps"))
    else:
        base = Path.home() / ".cache" / "arbs" / "MDP" / "IRSwaps"

    fixings_cache = base / "fixings_cache" / f"{curve_name}_fixings"
    fixings_cache.mkdir(parents=True, exist_ok=True)
    return fixings_cache


def _fetch_fixings(
    as_of_date: datetime.date | Literal["live"],
    curve_name: str,
    force_refresh: Optional[bool] = False,
) -> pl.DataFrame:
    """Fetch fixings data for a curve, using cache when available.

    Returns a polars DataFrame with columns: [curve_name (datetime), "Fixing" (float)]
    """
    if as_of_date == "live":
        as_of_date = datetime.date.today()

    fixings_cache = _resolve_fixings_cache_dir(curve_name)

    tday = datetime.date.today()
    today_dir = fixings_cache / tday.strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)

    expected_dt = _last_usbd_before(as_of_date)

    # If we have a valid cache anywhere (today or a recent prior day) and not force-refreshing, use it.
    if not force_refresh:
        cached = _read_cached_if_valid(fixings_cache, curve_name, expected_dt)
        if cached is not None:
            return cached

    # If force_refresh, clear only today's files (do NOT delete prior days – we may need them as fallback).
    if force_refresh:
        for p in today_dir.glob("*.csv"):
            try:
                p.unlink()
            except Exception as e:
                print(f"[cache] Could not delete cache file during force_refresh: {p} ({e})")

    # Live fetch
    try:
        fixings_dict = FixingsFetcher().get_fixings(curve=curve_name)
    except Exception:
        fixings_dict = FixingsFetcher(fred_api_key="e06f51338bf093283ce1331c2826b3db").get_fixings(curve=curve_name, use_fred=True)

    # Convert dict to polars DataFrame
    # Handle various date formats in the dict keys
    dates = []
    values = []
    for k, v in fixings_dict.items():
        # Convert key to string first to ensure consistent handling
        if isinstance(k, str):
            dates.append(k)
        elif isinstance(k, (datetime.date, datetime.datetime)):
            dates.append(k.isoformat())
        else:
            dates.append(str(k))
        values.append(v)

    fixings_df = pl.DataFrame({
        curve_name: dates,
        "Fixing": values
    })

    # Parse date column to datetime
    try:
        fixings_df = fixings_df.with_columns(
            pl.col(curve_name).str.strptime(pl.Datetime, strict=False)
        )
    except Exception:
        # If parsing fails, try direct cast
        fixings_df = fixings_df.with_columns(
            pl.col(curve_name).cast(pl.Datetime, strict=False)
        )

    # Only cache if the expected (T-1 USBD) fixing is present (i.e., it has been published).
    if _has_date(fixings_df, expected_dt, curve_name):
        out_csv = today_dir / "fixings.csv"
        try:
            fixings_df.write_csv(out_csv)
        except Exception as e:
            print(f"[cache] Failed to write cache file {out_csv}: {e}")
    else:
        # Optional: if a valid recent cache exists, prefer returning that over the live (incomplete) pull.
        cached_fallback = _read_cached_if_valid(fixings_cache, curve_name, expected_dt)
        if cached_fallback is not None:
            return cached_fallback

    # Light cleanup of very old dated dirs (keeps recent for resilience).
    _cleanup_old_cache_dirs(fixings_cache, keep_last=_KEEP_LAST_N_DATED_DIRS)

    return fixings_df
