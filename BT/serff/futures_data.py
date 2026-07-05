"""ZQ / SR3 / SR1 EOD settlement history via the repo's Barchart plumbing.

Per-symbol full-history fetches through ``BarchartFetcher`` (canonical<->
Barchart symbol mapping borrowed from STIRFutureMDP), cached one parquet per
contract under the ARBS user cache dir.  Fetches are SERIALIZED in small
batches by default -- the Barchart proxy pool is flaky under fan-out (see
repo notes); pass a larger ``max_concurrent`` deliberately.

Also provides the settlement-reconciliation data-quality gate: recompute
final settlements from published fixings and compare against the last
exchange print for every expired contract.
"""

from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from BT.serff.mechanics import (
    contract_window,
    settlement_rate,
    sr3_quarterly_symbols,
    zq_monthly_symbols,
)

logger = logging.getLogger(__name__)

try:
    from platformdirs import user_cache_dir as _user_cache_dir
except Exception:  # pragma: no cover
    _user_cache_dir = None


def _cache_dir(base_cache_dir: Optional[str | Path] = None) -> Path:
    if base_cache_dir:
        base = Path(base_cache_dir)
    elif os.getenv("ARBS_CACHE_DIR"):
        base = Path(os.getenv("ARBS_CACHE_DIR"))
    elif _user_cache_dir:
        base = Path(_user_cache_dir(appname="ARBS/BT/serff"))
    else:
        base = Path.home() / ".cache" / "arbs" / "BT" / "serff"
    d = base / "eod_settles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _to_barchart(symbol: str) -> str:
    from MDP.STIRFutures.STIRFutureMDP import _to_barchart_symbol

    return _to_barchart_symbol(symbol)


def universe(start: datetime.date, end: datetime.date, include_sr1: bool = False) -> List[str]:
    syms = sr3_quarterly_symbols(start, end) + zq_monthly_symbols(start, end)
    if include_sr1:
        syms += [s.replace("ZQ", "SR1") for s in zq_monthly_symbols(start, end)]
    return syms


def _cache_path(symbol: str, cache_dir: Path) -> Path:
    return cache_dir / f"{symbol.upper()}.parquet"


def _is_expired(symbol: str, as_of: datetime.date) -> bool:
    return contract_window(symbol).end <= as_of


def load_cached(symbol: str, base_cache_dir: Optional[str | Path] = None) -> Optional[pd.DataFrame]:
    p = _cache_path(symbol, _cache_dir(base_cache_dir))
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def _fetch_batch(
    symbols: List[str],
    start: datetime.date,
    end: datetime.date,
    *,
    max_concurrent: int,
    show_progress: bool,
) -> Dict[str, pd.DataFrame]:
    from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher

    bc_syms = [_to_barchart(s) for s in symbols]
    bcf = BarchartFetcher(global_timeout=30)
    try:
        raw = bcf.barchart_timeseries_api(
            barchart_symbols=bc_syms,
            start_date=datetime.datetime.combine(start, datetime.time.min),
            end_date=datetime.datetime.combine(end, datetime.time.max),
            interval=None,  # EOD
            one_df=False,
            show_tqdm=show_progress,
            max_concurrent_tasks=max_concurrent,
            max_keepalive_connections=max(2, max_concurrent),
            max_requests_per_second=3,
        )
    finally:
        try:
            bcf.close()
        except Exception:
            pass

    out: Dict[str, pd.DataFrame] = {}
    for canonical, bc in zip(symbols, bc_syms):
        df = raw.get(bc) if isinstance(raw, dict) else None
        if df is None or df.empty:
            continue
        df = df.copy()
        if "Date" in df.columns:
            df = df.set_index("Date")
        df.index = pd.to_datetime(df.index).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        out[canonical] = df
    return out


def backfill_settles(
    start: datetime.date,
    end: datetime.date,
    *,
    include_sr1: bool = False,
    symbols: Optional[Iterable[str]] = None,
    force_refresh: bool = False,
    max_concurrent: int = 2,
    batch_size: int = 6,
    show_progress: bool = True,
    base_cache_dir: Optional[str | Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Load (cache-first) full EOD history per contract.

    Expired contracts with a cached parquet are never re-fetched; live
    contracts are re-fetched when the cache is stale relative to ``end``.
    """
    cache = _cache_dir(base_cache_dir)
    today = datetime.date.today()
    syms = list(symbols) if symbols is not None else universe(start, end, include_sr1)

    out: Dict[str, pd.DataFrame] = {}
    to_fetch: List[str] = []
    for s in syms:
        cached = None if force_refresh else load_cached(s, base_cache_dir)
        if cached is not None and not cached.empty:
            if _is_expired(s, today) or cached.index.max().date() >= min(end, today):
                out[s] = cached
                continue
        to_fetch.append(s)

    for i in range(0, len(to_fetch), batch_size):
        batch = to_fetch[i : i + batch_size]
        if show_progress:
            logger.info("Barchart EOD backfill batch %d/%d: %s", i // batch_size + 1, (len(to_fetch) + batch_size - 1) // batch_size, batch)
        try:
            fetched = _fetch_batch(batch, start, end, max_concurrent=max_concurrent, show_progress=show_progress)
        except Exception as exc:
            logger.warning("Barchart batch failed (%s): %s", batch, exc)
            continue
        for s, df in fetched.items():
            out[s] = df
            try:
                df.to_parquet(_cache_path(s, cache))
            except Exception as exc:
                logger.warning("Could not cache %s: %s", s, exc)

    missing = [s for s in syms if s not in out]
    if missing:
        logger.warning("No EOD history retrieved for %d contracts: %s", len(missing), missing)
    return out


def settle_panel(
    histories: Dict[str, pd.DataFrame],
    *,
    price_col_candidates: Tuple[str, ...] = ("Close", "Last", "Settle", "close"),
) -> pd.DataFrame:
    """Wide panel of daily settle prices (date x contract symbol)."""
    cols = {}
    for sym, df in histories.items():
        col = next((c for c in price_col_candidates if c in df.columns), None)
        if col is None:
            numeric = df.select_dtypes("number")
            if numeric.empty:
                continue
            col = numeric.columns[0]
        cols[sym] = pd.to_numeric(df[col], errors="coerce")
    panel = pd.DataFrame(cols).sort_index()
    panel.index = pd.to_datetime(panel.index).normalize()
    return panel


def reconcile_settlements(
    settles: pd.DataFrame,
    sofr_fixings: pd.Series,
    effr_fixings: pd.Series,
    *,
    tolerance_bp: float = 0.35,
    as_of: Optional[datetime.date] = None,
) -> pd.DataFrame:
    """Recompute final settlements from fixings vs the last exchange print.

    Returns one row per expired contract: recomputed settle rate, last
    exchange price/rate, difference in bp, pass/fail vs ``tolerance_bp``.
    The recomputed value is the truth for terminal backtest cash flows; a
    failure is a data-quality flag on either the price history tail or the
    fixings, and is reported -- never silently patched.
    """
    as_of = as_of or datetime.date.today()
    rows = []
    for sym in settles.columns:
        window = contract_window(sym)
        if window.end > as_of:
            continue
        fixings = sofr_fixings if window.root == "SR3" else effr_fixings
        try:
            recomputed_rate = settlement_rate(fixings, sym)
        except ValueError as exc:
            rows.append({"symbol": sym, "recomputed_rate": None, "exchange_rate": None, "diff_bp": None, "ok": False, "note": str(exc)})
            continue
        px = settles[sym].dropna()
        if px.empty:
            rows.append({"symbol": sym, "recomputed_rate": recomputed_rate, "exchange_rate": None, "diff_bp": None, "ok": False, "note": "no price history"})
            continue
        exchange_rate = 100.0 - float(px.iloc[-1])
        diff_bp = (recomputed_rate - exchange_rate) * 100.0
        rows.append(
            {
                "symbol": sym,
                "recomputed_rate": recomputed_rate,
                "exchange_rate": exchange_rate,
                "diff_bp": diff_bp,
                "ok": abs(diff_bp) <= tolerance_bp,
                "note": "",
            }
        )
    return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()
