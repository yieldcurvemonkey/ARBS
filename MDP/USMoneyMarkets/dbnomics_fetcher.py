"""Thin keyless DBnomics v22 client with a dated-directory CSV cache.

Mirrors the MDP/IRSwaps/fixings_cache conventions: one dated directory per
fetch day under the ARBS cache root, newest-first fallback to recent prior
days, and a small keep-last cleanup.  DBnomics mirrors official releases
(Fed H.4.1, BEA NIPA) without an API key.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import requests

try:
    from platformdirs import user_cache_dir as _user_cache_dir
except Exception:  # pragma: no cover - platformdirs is a repo dependency
    _user_cache_dir = None

_DBNOMICS_URL = "https://api.db.nomics.world/v22/series/{provider}/{dataset}/{code}?observations=1"
_UA = {"User-Agent": "Mozilla/5.0 (rates-research)"}
_KEEP_LAST_N_DATED_DIRS = 3


def _resolve_cache_dir(series_slug: str, base_cache_dir: Optional[Union[str, Path]] = None) -> Path:
    if base_cache_dir:
        base = Path(base_cache_dir)
    elif os.getenv("ARBS_CACHE_DIR"):
        base = Path(os.getenv("ARBS_CACHE_DIR"))
    elif _user_cache_dir:
        base = Path(_user_cache_dir(appname="ARBS/MDP/USMoneyMarkets"))
    else:
        base = Path.home() / ".cache" / "arbs" / "MDP" / "USMoneyMarkets"

    cache_dir = base / "dbnomics_cache" / series_slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cleanup_old_cache_dirs(root: Path, keep_last: int = _KEEP_LAST_N_DATED_DIRS) -> None:
    dated = sorted([p for p in root.iterdir() if p.is_dir()])
    for p in dated[:-keep_last]:
        try:
            for f in p.glob("*.csv"):
                f.unlink()
            p.rmdir()
        except Exception:
            pass


def _read_cached(root: Path) -> Optional[pd.Series]:
    dated_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
    for d in dated_dirs:
        csvs = sorted(d.glob("*.csv"))
        if not csvs:
            continue
        try:
            df = pd.read_csv(csvs[0], index_col=0, parse_dates=True)
            s = df.iloc[:, 0]
            s.index = pd.to_datetime(s.index)
            return s.dropna().sort_index()
        except Exception:
            continue
    return None


def _parse_dbnomics_doc(doc: dict, *, quarterly: bool) -> pd.Series:
    if quarterly:
        idx = pd.PeriodIndex(doc["period"], freq="Q").to_timestamp(how="end").normalize()
    else:
        idx = pd.to_datetime(doc["period"])
    s = pd.Series(pd.to_numeric(doc["value"], errors="coerce"), index=idx)
    return s.dropna().sort_index()


def fetch_dbnomics_series(
    provider: str,
    dataset: str,
    code: str,
    *,
    quarterly: bool = False,
    force_refresh: bool = False,
    base_cache_dir: Optional[Union[str, Path]] = None,
    timeout: int = 60,
) -> pd.Series:
    """Fetch a DBnomics series, cached one CSV per fetch day.

    Same-day cache hits short-circuit the network; on network failure the most
    recent prior day's cache is served instead of raising.
    """
    slug = f"{provider}_{dataset}_{code}".replace("/", "-").replace(".", "_")
    root = _resolve_cache_dir(slug, base_cache_dir)

    today_dir = root / datetime.date.today().strftime("%Y-%m-%d")
    today_csv = today_dir / "series.csv"

    if not force_refresh and today_csv.exists():
        cached = _read_cached(root)
        if cached is not None:
            return cached

    url = _DBNOMICS_URL.format(provider=provider, dataset=dataset, code=code)
    try:
        res = requests.get(url, headers=_UA, timeout=timeout)
        res.raise_for_status()
        doc = res.json()["series"]["docs"][0]
        s = _parse_dbnomics_doc(doc, quarterly=quarterly)
    except Exception:
        cached = _read_cached(root)
        if cached is not None:
            return cached
        raise

    today_dir.mkdir(parents=True, exist_ok=True)
    try:
        s.rename("value").to_csv(today_csv)
        _cleanup_old_cache_dirs(root)
    except Exception:
        pass
    return s
