from pathlib import Path
import datetime
from typing import Optional, Literal
import os
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import GoodFriday, USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FixingsFetcher import FixingsFetcher


class _SOFRPublishCalendar(USFederalHolidayCalendar):
    """US government securities market calendar, for SOFR publication dates.

    SOFR is published on US government securities market business days, which
    follow SIFMA -- and SIFMA closes on Good Friday, which
    USFederalHolidayCalendar does not know about. Without this rule the
    "expected latest fixing" for the first business day after every Good Friday
    lands on a day SOFR never publishes, so the cache-accept gate, the
    cache-write gate and the cached_fallback re-check all fail forever: every
    _fetch_fixings call for such an as_of date did a full NY Fed HTTP pull
    (14-17x slower, ~150s and 992 remote hits for a single-day intraday replay)
    and never persisted anything. Affects one weekday per year, in perpetuity:
    2018-04-02, 2018-12-06, 2019-04-22, 2020-04-13, 2021-04-05, 2022-04-18,
    2023-04-10, 2024-04-01, 2025-04-21, 2026-04-06, 2027-03-29, ...
    """

    rules = USFederalHolidayCalendar.rules + [GoodFriday]


_PUBLISH_CAL = _SOFRPublishCalendar()
_CBD = CustomBusinessDay(calendar=_PUBLISH_CAL)
_KEEP_LAST_N_DATED_DIRS = 3  # retain recent caches for fallback
_NY_TZ = ZoneInfo("America/New_York")
_SOFR_PUBLISH_TIME_ET = datetime.time(hour=8, minute=0)
_SOFR_CURVES = {"USD-SOFR-1D"}


def _last_usbd_before(d: datetime.date) -> pd.Timestamp:
    return (pd.Timestamp(d) - _CBD).normalize()


def _has_date(series: pd.Series, target: pd.Timestamp) -> bool:
    if series is None or series.empty:
        return False
    idx = pd.to_datetime(series.index, errors="coerce").normalize()
    return target in set(idx)


def _read_cached_if_valid(root: Path, curve_name: str, expected_dt: pd.Timestamp) -> Optional[pd.Series]:
    dated_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)  # newest first
    for d in dated_dirs:
        csvs = sorted(d.glob("*.csv"))
        if not csvs:
            continue
        try:
            dfs = [pd.read_csv(p) for p in csvs]
            df = pd.concat(dfs, ignore_index=True)
            if curve_name not in df.columns or "Fixing" not in df.columns:
                continue
            df = df.set_index(curve_name)
            df.index = pd.to_datetime(df.index, errors="coerce")
            df = df.loc[~df.index.duplicated(keep="first"), :]
            s = df["Fixing"].copy()
            if _has_date(s, expected_dt):
                return s
        except Exception:
            # ignore malformed/partial cache files
            continue
    return None


def _latest_cache_refresh_time(root: Path) -> Optional[datetime.datetime]:
    latest_mtime: Optional[float] = None
    for p in root.rglob("*.csv"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime

    if latest_mtime is None:
        return None

    return datetime.datetime.fromtimestamp(latest_mtime, tz=datetime.timezone.utc).astimezone(_NY_TZ)


def _should_refresh_for_runtime_staleness(root: Path, curve_name: str, as_of_date: datetime.date) -> bool:
    """
    For SOFR, refresh same-day cache if the last cache refresh was before 8:00 ET.
    This ensures a 6:00 ET cache snapshot is re-fetched after publication time.
    """
    curve_key = (curve_name or "").upper().strip()
    if curve_key not in _SOFR_CURVES:
        return False

    now_et = datetime.datetime.now(tz=_NY_TZ)
    if as_of_date != now_et.date():
        return False

    publish_cutoff = datetime.datetime.combine(now_et.date(), _SOFR_PUBLISH_TIME_ET, tzinfo=_NY_TZ)
    if now_et < publish_cutoff:
        return False

    last_refresh = _latest_cache_refresh_time(root)
    if last_refresh is None:
        return True

    return last_refresh < publish_cutoff


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
) -> pd.Series:

    if as_of_date == "live":
        as_of_date = datetime.datetime.now(tz=_NY_TZ).date()

    fixings_cache = _resolve_fixings_cache_dir(curve_name)

    tday = datetime.datetime.now(tz=_NY_TZ).date()
    today_dir = fixings_cache / tday.strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)

    expected_dt = _last_usbd_before(as_of_date)
    runtime_stale = _should_refresh_for_runtime_staleness(fixings_cache, curve_name, as_of_date)

    # If we have a valid cache anywhere (today or a recent prior day) and not force-refreshing, use it.
    if not force_refresh and not runtime_stale:
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

    fixings_series = pd.Series(fixings_dict)
    fixings_series.index = pd.to_datetime(fixings_series.index, errors="coerce").normalize()
    fixings_series.index.name = curve_name
    fixings_series.name = "Fixing"

    # Only cache if the expected (T-1 USBD) fixing is present (i.e., it has been published).
    if _has_date(fixings_series, expected_dt):
        out_csv = today_dir / "fixings.csv"
        try:
            fixings_series.to_csv(out_csv)
        except Exception as e:
            print(f"[cache] Failed to write cache file {out_csv}: {e}")
    else:
        # print(f"[cache] Skipping cache write: expected fixing {expected_dt.date()} not yet published for {curve_name}.")
        # Optional: if a valid recent cache exists, prefer returning that over the live (incomplete) pull.
        # (Comment out if you always want the freshest pull, even if incomplete.)
        cached_fallback = _read_cached_if_valid(fixings_cache, curve_name, expected_dt)
        if cached_fallback is not None:
            return cached_fallback

    # Light cleanup of very old dated dirs (keeps recent for resilience).
    _cleanup_old_cache_dirs(fixings_cache, keep_last=_KEEP_LAST_N_DATED_DIRS)

    return fixings_series
