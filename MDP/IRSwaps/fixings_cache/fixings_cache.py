from pathlib import Path
import datetime
from typing import Optional, Literal
import os

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FixingsFetcher import FixingsFetcher


_PUBLISH_CAL = USFederalHolidayCalendar()
_CBD = CustomBusinessDay(calendar=_PUBLISH_CAL)
_KEEP_LAST_N_DATED_DIRS = 10  # retain recent caches for fallback


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
