from __future__ import annotations

import datetime
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from Caching.timeseries_cache import WriteOptions, append_timeseries, append_timeseries_many, read_timeseries
from utils.storage_paths import data_root, repo_store

DateLike = Union[datetime.date, datetime.datetime]
REPO_ROOT = Path(__file__).resolve().parents[1]

#: 8.98 GB across 1.9 M files as of 2026-08-15, which is why it is the first
#: store routed off the checkout. ``ARBS_COMPUTED_TS_DIR`` pins it alone;
#: ``ARBS_DATA_ROOT`` moves it along with its peers; neither set keeps the
#: historical ``<repo>/data/ts``. See :mod:`utils.storage_paths`.
DEFAULT_COMPUTED_TS_BASE_DIR = repo_store("data", "ts", env_var="ARBS_COMPUTED_TS_DIR")

logger = logging.getLogger(__name__)


def _normalize_intraday_key(value: DateLike) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _normalize_eod_key(value: DateLike) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    return value


@dataclass(frozen=True)
class CachedTimeseriesRow:
    ref_point: DateLike
    column_name: str
    value: float


def _get_computed_ts_sync(base_dir: Union[str, Path]):
    from Caching.supabase_engine import SUPABASE_ENABLED

    if not SUPABASE_ENABLED:
        return None

    from Caching.supabase_computed_timeseries_sync import SupabaseComputedTimeseriesSync
    from Caching.supabase_engine import get_engine

    return SupabaseComputedTimeseriesSync(base_dir=Path(base_dir), engine=get_engine())


#: Symbols already reported as short this process. One line per symbol: a batch
#: read touches thousands, and a warning per row would bury the signal it is.
_SHORT_MIRROR_WARNED: set = set()


def _warn_short_mirror(symbol: str, mirror_rows: int, full_rows: int) -> None:
    """Say that the DuckDB mirror was short and Parquet made up the difference.

    Silence is why this ran unnoticed. The mirror is a cache in front of the
    authoritative tier, and a cache that quietly serves less than the tier holds
    is the single shape this estate keeps getting hurt by.
    """
    if symbol in _SHORT_MIRROR_WARNED:
        return
    _SHORT_MIRROR_WARNED.add(symbol)
    logger.warning(
        "computed TS: the DuckDB mirror held %d of %d rows for %s over the "
        "requested window; Parquet supplied the rest. The mirror is a cache, not "
        "the source of truth - this is not data loss, but a mirror that is short "
        "for many symbols means slower reads and, before this was fixed, shorter "
        "answers.",
        mirror_rows, full_rows, symbol,
    )


def _merge_preferring(primary, secondary, *, intraday: bool):
    """``primary`` rows, plus any ``secondary`` row for a key primary lacks.

    Rows are ``(reference_point, column_name, value)`` and a symbol may carry
    several columns, so the key is (normalised reference point, column name) --
    keying on the date alone would drop every column but one.

    Used to combine the authoritative Parquet answer with whatever the mirror
    had. Parquet wins on any key they share; the mirror can only ADD. That
    direction matters: the mirror is the tier that has been observed to be
    short, so it must never be able to displace a Parquet row.
    """
    def _key(row):
        ref = row[0]
        try:
            norm = _normalize_intraday_key(ref) if intraday else _normalize_eod_key(ref)
        except Exception:  # noqa: BLE001 - an unparseable stamp keys on itself
            norm = ref
        return (norm, row[1])

    out = list(primary or [])
    if not secondary:
        return out
    have = {_key(r) for r in out}
    for row in secondary:
        k = _key(row)
        if k not in have:
            have.add(k)
            out.append(row)
    return out


def default_computed_timeseries_base_dir() -> str:
    return str(DEFAULT_COMPUTED_TS_BASE_DIR)


def _resolve_computed_timeseries_base_dir(base_dir: Union[str, Path, None]) -> Path:
    """Resolve ``base_dir``, honouring the store's configured location.

    Roughly fifteen call sites pass the literal ``"./data/ts"`` rather than
    ``None`` -- ``TB/IRSwapsTB.py:417``, ``TB/FixedRateBondsTB.py:182``,
    ``TB/USTFuturesTB.py:72``, ``scripts/_ust_service_common.py:47``,
    ``scripts/eod_curve_service.py:61``, ``scripts/citivelo_intraday_ts_warm.py``
    and others. Anchoring those to ``REPO_ROOT`` bypasses the configuration
    entirely, so once the store moves they all read an empty directory -- not an
    error, a cold cache.

    Those call sites are spelling out the store's *default* location rather than
    passing ``None``, so that is what they get: ``"./data/ts"`` is a synonym for
    ``None`` and resolves through :data:`DEFAULT_COMPUTED_TS_BASE_DIR`, honouring
    ``ARBS_COMPUTED_TS_DIR``, then ``ARBS_DATA_ROOT``, then the checkout.

    Routing it through the *store's own* variable rather than the shared root
    matters, because the two deliberately differ: ``data/ts`` is 1.92 M files
    whose cluster rounding costs roughly 3x its logical size, which is why it is
    pinned to the system drive while its peers live on the data drive.

    Any other relative path is anchored to the data root when one is set, so the
    layout there stays a mirror of the checkout. With no variables set this is
    exactly the old behaviour -- :func:`utils.storage_paths.data_root` returns
    ``None`` and the anchor falls back to ``REPO_ROOT``. Absolute paths, which is
    what the tests pass, are untouched in every case.
    """
    if base_dir is None:
        return DEFAULT_COMPUTED_TS_BASE_DIR

    path = Path(base_dir)
    if path.is_absolute():
        return path

    # "./data/ts", "data/ts", ".\\data\\ts" -- the default, spelled out longhand.
    if tuple(p for p in path.parts if p not in (".", "")) == ("data", "ts"):
        return DEFAULT_COMPUTED_TS_BASE_DIR

    anchor = data_root() or REPO_ROOT
    return (anchor / path).resolve()


def _open_duckdb_graceful(db_path: str) -> Optional["DuckDBTimeseriesCache"]:
    """Try read-write, then read-only, then give up.

    Returns a DuckDBTimeseriesCache or None if the file is completely
    inaccessible (e.g. locked by another process that also blocks
    read-only access).
    """
    from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache

    # 1. Try read-write (full cache participation)
    try:
        return DuckDBTimeseriesCache(db_path=db_path)
    except Exception:
        pass

    # 2. Try read-only (concurrent reads still fast)
    try:
        cache = DuckDBTimeseriesCache(db_path=db_path, read_only=True)
        logger.info(
            "DuckDB opened read-only (write lock held by another process): %s",
            db_path,
        )
        return cache
    except Exception:
        pass

    # 3. Give up — parquet fallback
    logger.warning(
        "DuckDB unavailable (file locked), falling back to parquet-only: %s",
        db_path,
    )
    return None


class ComputedTimeseriesStore:
    def __init__(
        self,
        *,
        base_dir: Union[str, Path, None] = None,
        compression: str = "zstd",
        row_group_size: int = 256_000,
        use_duckdb: bool = True,
        duckdb_path: Optional[str] = None,
    ) -> None:
        resolved_base_dir = _resolve_computed_timeseries_base_dir(base_dir)
        self._opts = WriteOptions(
            base_dir=str(resolved_base_dir),
            compression=compression,
            row_group_size=int(row_group_size),
        )
        self._duckdb_cache: Optional["DuckDBTimeseriesCache"] = None
        self._bg_push_pending = 0
        self._bg_push_condition = threading.Condition(threading.Lock())
        if use_duckdb:
            resolved_duckdb_path = duckdb_path or str(Path(self._opts.base_dir) / "computed_ts.duckdb")
            self._duckdb_cache = _open_duckdb_graceful(resolved_duckdb_path)

    @property
    def write_options(self) -> WriteOptions:
        return self._opts

    def _read_df(
        self,
        *,
        symbol: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        return read_timeseries(
            None,
            symbol,
            start=start,
            end=end,
            columns=None,
            base_dir=self._opts.base_dir,
        )

    def _rows_from_df(
        self,
        *,
        df: pd.DataFrame,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool,
        fallback_column_name: str | None,
    ) -> List[Tuple[DateLike, str, float]]:
        if df.empty:
            return []

        if not isinstance(df.index, pd.DatetimeIndex):
            for candidate in ("Date", "date", "timestamp", "_index_ts"):
                if candidate not in df.columns:
                    continue
                candidate_index = pd.to_datetime(df[candidate], errors="coerce")
                if candidate_index.notna().any():
                    df = df.copy()
                    df.index = candidate_index
                    break

        if not isinstance(df.index, pd.DatetimeIndex):
            return []

        if df.index.hasnans:
            df = df.loc[~df.index.isna()].copy()
        if df.empty:
            return []

        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if not numeric_cols:
            return []

        value_col = "value" if "value" in numeric_cols else numeric_cols[0]
        has_column_name = "_column_name" in df.columns

        if intraday:
            by_key = {
                _normalize_intraday_key(ts): (
                    str(row["_column_name"]) if has_column_name and pd.notna(row["_column_name"]) else str(fallback_column_name or value_col),
                    float(row[value_col]),
                )
                for ts, row in df.iterrows()
                if pd.notna(row[value_col])
            }
        else:
            by_key = {
                _normalize_eod_key(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts): (
                    str(row["_column_name"]) if has_column_name and pd.notna(row["_column_name"]) else str(fallback_column_name or value_col),
                    float(row[value_col]),
                )
                for ts, row in df.iterrows()
                if pd.notna(row[value_col])
            }

        today = datetime.date.today()
        rows: List[Tuple[DateLike, str, float]] = []
        for ref_point in reference_points:
            if (not intraday) and skip_current_eod and (_normalize_eod_key(ref_point) == today):
                continue
            key = _normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point)
            hit = by_key.get(key)
            if hit is None:
                continue
            col_name, value = hit
            rows.append((ref_point, col_name, value))
        return rows

    def _prefetch_remote_range(
        self,
        *,
        symbol: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> Any:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None:
            return None
        try:
            sync.prefetch_range(symbol, start_date, end_date)
        except Exception:
            logger.warning("Computed TS L2 prefetch failed for %s", symbol, exc_info=True)
        return sync

    def _read_from_duckdb(
        self,
        *,
        symbol: str,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool,
        fallback_column_name: str | None,
    ) -> List[Tuple[DateLike, str, float]] | None:
        """Try DuckDB fast path. Returns rows or None if DuckDB unavailable."""
        if self._duckdb_cache is None:
            return None
        # DuckDB table stores one row per (symbol, date) — not suitable for intraday
        if intraday:
            return None

        start = min(reference_points)
        end = max(reference_points)
        start_date = _normalize_intraday_key(start).date() if intraday else _normalize_eod_key(start)
        end_date = _normalize_intraday_key(end).date() if intraday else _normalize_eod_key(end)

        duckdb_rows = self._duckdb_cache.read_rows(symbol, start=start_date, end=end_date)
        if not duckdb_rows:
            return None

        today = datetime.date.today()
        result: List[Tuple[DateLike, str, float]] = []
        by_date = {row[0]: (row[1], row[2]) for row in duckdb_rows}

        for ref_point in reference_points:
            key = _normalize_eod_key(ref_point) if not intraday else _normalize_intraday_key(ref_point).date()
            if (not intraday) and skip_current_eod and key == today:
                continue
            hit = by_date.get(key)
            if hit is not None:
                col_name, value = hit
                result.append((ref_point, col_name, value))

        return result if result else None

    def _sync_missing_from_postgres(
        self,
        *,
        symbol: str,
        missing_dates: list[datetime.date],
    ) -> bool:
        """Pull missing rows from Postgres into local DuckDB."""
        if self._duckdb_cache is None or not missing_dates:
            return False
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None:
            return False
        if not hasattr(sync, "pull_rows"):
            return False

        try:
            start = min(missing_dates)
            end = max(missing_dates)
            watermark = self._duckdb_cache.get_watermark(symbol)
            pulled = sync.pull_rows(
                symbol,
                start=start,
                end=end,
                since=watermark,
            )
            if not pulled:
                return False
            rows = [(r[0], r[1], r[2]) for r in pulled]
            self._duckdb_cache.upsert_rows(symbol, rows)
            max_updated = max(r[3] for r in pulled)
            self._duckdb_cache.set_watermark(symbol, max_updated)
            return True
        except Exception:
            logger.warning("DuckDB sync from Postgres failed for %s", symbol, exc_info=True)
            return False

    def _read_local_rows_without_prefetch(
        self,
        *,
        symbol: str,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool,
        fallback_column_name: str | None,
    ) -> List[Tuple[DateLike, str, float]]:
        start = min(reference_points)
        end = max(reference_points)
        read_start: DateLike = _normalize_intraday_key(start).to_pydatetime() if intraday else start
        read_end: DateLike = _normalize_intraday_key(end).to_pydatetime() if intraday else end
        df = self._read_df(symbol=symbol, start=read_start, end=read_end)
        return self._rows_from_df(
            df=df,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )

    def has_symbol(self, symbol: str) -> Optional[bool]:
        if self._duckdb_cache is None or not hasattr(self._duckdb_cache, "has_symbol"):
            return None
        try:
            return bool(self._duckdb_cache.has_symbol(symbol))
        except Exception:
            return None

    def read_many_symbols(
        self,
        *,
        symbols: Sequence[str],
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool = True,
        fallback_column_names: Mapping[str, str | None] | None = None,
        allow_partial: bool = False,
    ) -> Mapping[str, List[Tuple[DateLike, str, float]]]:
        """Batch-read rows for multiple symbols from DuckDB in a single query.

        Falls back to per-symbol read_rows for symbols not found in DuckDB.
        """
        if not symbols or not reference_points:
            return {s: [] for s in symbols}

        if intraday or self._duckdb_cache is None:
            result = {}
            for sym in symbols:
                fb = (fallback_column_names or {}).get(sym)
                result[sym] = self.read_rows(
                    symbol=sym,
                    reference_points=reference_points,
                    intraday=intraday,
                    skip_current_eod=skip_current_eod,
                    fallback_column_name=fb,
                    allow_partial=allow_partial,
                )
            return result

        start = min(reference_points)
        end = max(reference_points)
        start_date = _normalize_eod_key(start)
        end_date = _normalize_eod_key(end)

        today = datetime.date.today()
        requested = {
            _normalize_eod_key(rp)
            for rp in reference_points
            if not (skip_current_eod and _normalize_eod_key(rp) == today)
        }

        batch_rows = self._duckdb_cache.read_many_symbols(
            list(symbols), start=start_date, end=end_date,
        )

        result: dict[str, List[Tuple[DateLike, str, float]]] = {}
        for sym in symbols:
            duckdb_rows = batch_rows.get(sym, [])
            if not duckdb_rows:
                if allow_partial:
                    l2_rows = self._read_with_l2_prefetch(
                        symbol=sym,
                        reference_points=reference_points,
                        intraday=False,
                        skip_current_eod=skip_current_eod,
                        fallback_column_name=(fallback_column_names or {}).get(sym),
                    )
                    if l2_rows:
                        self._backfill_duckdb_from_rows(sym, l2_rows, intraday=False)
                    result[sym] = l2_rows
                else:
                    result[sym] = self._read_with_l2_prefetch(
                        symbol=sym,
                        reference_points=reference_points,
                        intraday=False,
                        skip_current_eod=skip_current_eod,
                        fallback_column_name=(fallback_column_names or {}).get(sym),
                    )
                continue

            by_date = {row[0]: (row[1], row[2]) for row in duckdb_rows}
            rows_out: List[Tuple[DateLike, str, float]] = []
            for ref_point in reference_points:
                key = _normalize_eod_key(ref_point)
                if skip_current_eod and key == today:
                    continue
                hit = by_date.get(key)
                if hit is not None:
                    rows_out.append((ref_point, hit[0], hit[1]))

            covered = {_normalize_eod_key(rp) for rp, _, _ in rows_out}
            if covered >= requested:
                result[sym] = rows_out
            else:
                # A SHORT MIRROR ANSWER IS NOT AN ANSWER, whatever allow_partial
                # says. This used to have an ``elif allow_partial: result[sym] =
                # rows_out`` arm, and since every production caller passes
                # allow_partial=True it was the arm that ran. See ``read_rows``
                # for the measurement and for why "partial" has to mean "after
                # Parquet was consulted".
                # remote=False: the mirror answered, just not fully, so Parquet
                # settles it locally. See ``_read_with_l2_prefetch``.
                l2_rows = self._read_with_l2_prefetch(
                    symbol=sym,
                    reference_points=reference_points,
                    intraday=False,
                    skip_current_eod=skip_current_eod,
                    fallback_column_name=(fallback_column_names or {}).get(sym),
                    remote=False,
                )
                merged = _merge_preferring(l2_rows, rows_out, intraday=False)
                if l2_rows:
                    self._backfill_duckdb_from_rows(sym, merged, intraday=False)
                if len(merged) > len(rows_out):
                    _warn_short_mirror(sym, len(rows_out), len(merged))
                result[sym] = merged

        return result

    def read_rows(
        self,
        *,
        symbol: str,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool = True,
        fallback_column_name: str | None = None,
        allow_partial: bool = False,
        skip_if_symbol_absent: bool = False,
    ) -> List[Tuple[DateLike, str, float]]:
        if not reference_points:
            return []

        if skip_if_symbol_absent:
            has_symbol = self.has_symbol(symbol)
            if has_symbol is False:
                return []

        # DuckDB fast path
        duckdb_result = self._read_from_duckdb(
            symbol=symbol,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )
        today = datetime.date.today()
        requested = {
            _normalize_eod_key(rp) if not intraday else _normalize_intraday_key(rp).date()
            for rp in reference_points
            if not ((not intraday) and skip_current_eod and _normalize_eod_key(rp) == today)
        }

        if duckdb_result is not None:
            covered = {
                (_normalize_eod_key(rp) if not intraday else _normalize_intraday_key(rp).date())
                for rp, _, _ in duckdb_result
            }
            if covered >= requested:
                return duckdb_result
            missing_dates = sorted({
                (d.date() if isinstance(d, pd.Timestamp) else d)
                for d in (requested - covered)
            })
        else:
            missing_dates = sorted({
                (d.date() if isinstance(d, pd.Timestamp) else d)
                for d in requested
            })

        # Try syncing missing dates from Postgres into DuckDB
        if self._duckdb_cache is not None and missing_dates:
            synced = self._sync_missing_from_postgres(
                symbol=symbol,
                missing_dates=missing_dates,
            )
            if synced:
                duckdb_result_2 = self._read_from_duckdb(
                    symbol=symbol,
                    reference_points=reference_points,
                    intraday=intraday,
                    skip_current_eod=skip_current_eod,
                    fallback_column_name=fallback_column_name,
                )
                if duckdb_result_2 is not None:
                    covered_2 = {
                        (_normalize_eod_key(rp) if not intraday else _normalize_intraday_key(rp).date())
                        for rp, _, _ in duckdb_result_2
                    }
                    if covered_2 >= requested:
                        return duckdb_result_2
                    duckdb_result = duckdb_result_2

        if allow_partial:
            # A SHORT MIRROR ANSWER IS NOT AN ANSWER.
            #
            # This used to be ``if duckdb_result is not None: return
            # duckdb_result`` -- hand back whatever the mirror had, even though
            # the ``covered >= requested`` test forty lines up had just FAILED.
            # Every production caller passes allow_partial=True (both timeseries
            # routers, USTFutures, IRSwaptions, and five call sites in
            # TimeseriesBuilder); allow_partial=False survives only as this
            # signature's default. So this was the arm that ran, always.
            #
            # Measured on the live store, same symbol, same reference points:
            #
            #   IRS::GSQUANT-RL::USD-OIS::c6739ceb...
            #     parquet                  5,078 rows  2006-01-03 .. 2026-03-27
            #     allow_partial=True       3,573 rows  2012-01-03 .. 2026-03-27
            #     allow_partial=False      5,078 rows
            #
            #   FRB::USTS_FEDINVEST_WSJ_LIVE-RL::37f5933f...   4,157 -> 1,538
            #   IRS::citivelo_excel_rl::USD-SOFR-1D::65276577...  815 -> 9
            #
            # 1,505 rows and six years of history, on a flag whose name promises
            # only that a partial answer is ACCEPTABLE -- not that the
            # authoritative tier will be skipped to produce one.
            #
            # AND IT SELF-ARMS, which is why it spread. A symbol the mirror has
            # never seen reads correctly (``_read_from_duckdb`` returns None
            # rather than a short list), but the backfill below then writes back
            # exactly the window that was read. Demonstrated end to end: one
            # 2015-2016 subrange read of a zero-mirror symbol returned its 504
            # rows correctly and banked them; the next full-history read of the
            # same symbol returned 504 instead of 4,077. An untouched control
            # symbol returned all 4,077. Census at the time of the fix: ~2,900
            # symbols already short, roughly half the EOD estate -- and the
            # mirror grew 461,608 -> 496,939 rows between two measurements hours
            # apart, which is this defect arming itself on live traffic.
            #
            # March 2026 fixed the EMPTY case one branch over ("Previously this
            # returned [] when DuckDB was available but empty"). This is the
            # same bug, one branch further on: empty was caught, SHORT was not.
            #
            # So: Parquet is the source of truth and is consulted whenever the
            # mirror falls short. The mirror's rows are kept only for dates
            # Parquet does not have, which costs one glob per short symbol and
            # makes the answer independent of which windows happened to be read
            # first.
            # remote= is the cost guard. When the mirror gave us nothing this is
            # the pre-existing fallback path and keeps its L2 fetch. When the
            # mirror was merely SHORT -- the case this branch was written for,
            # and the common one -- Parquet alone settles it, so the repair
            # cannot turn half the estate's reads into Supabase round trips.
            local_rows = self._read_with_l2_prefetch(
                symbol=symbol,
                reference_points=reference_points,
                intraday=intraday,
                skip_current_eod=skip_current_eod,
                fallback_column_name=fallback_column_name,
                remote=duckdb_result is None,
            )
            merged = _merge_preferring(local_rows, duckdb_result or [], intraday=intraday)
            l2_rows = local_rows
            if l2_rows:
                self._backfill_duckdb_from_rows(symbol, merged, intraday=intraday)
            if duckdb_result is not None and len(merged) > len(duckdb_result):
                _warn_short_mirror(symbol, len(duckdb_result), len(merged))
            return merged

        # Fallback to Parquet + L2 path (non-partial mode)
        return self._read_with_l2_prefetch(
            symbol=symbol,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )

    def _read_with_l2_prefetch(
        self,
        *,
        symbol: str,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool,
        fallback_column_name: str | None,
        remote: bool = True,
    ) -> List[Tuple[DateLike, str, float]]:
        """Read from local Parquet first; only contact Supabase L2 for missing dates.

        ``remote=False`` stops after the local Parquet read. Parquet is the
        source of truth, so a local-only call is a complete answer to "what does
        this store actually hold"; what it gives up is the chance to import rows
        that exist only in Supabase.

        The short-mirror repair uses it. That repair fires on roughly half the
        EOD estate, and reading Parquet costs one glob while a range prefetch is
        a round trip to production -- so a fix aimed at correctness would have
        quietly bought a network call per read. ``allow_partial=True`` says a
        partial answer is acceptable; it is not a mandate to go to the network
        to avoid one. The pre-existing empty-mirror path still passes
        ``remote=True``: this parameter adds a Parquet read, never removes an L2
        fetch that used to happen.
        """
        start = min(reference_points)
        end = max(reference_points)
        read_start: DateLike = _normalize_intraday_key(start).to_pydatetime() if intraday else start
        read_end: DateLike = _normalize_intraday_key(end).to_pydatetime() if intraday else end

        today = datetime.date.today()

        # 1) Read whatever is already on local disk (Parquet).
        df = self._read_df(symbol=symbol, start=read_start, end=read_end)
        rows = self._rows_from_df(
            df=df,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )

        if not remote:
            return rows

        # 2) Compute which dates are still missing.
        skipped_keys = {
            (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point))
            for ref_point in reference_points
            if (not intraday) and skip_current_eod and (_normalize_eod_key(ref_point) == today)
        }
        requested_keys = {
            (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point))
            for ref_point in reference_points
            if (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point)) not in skipped_keys
        }
        covered_keys = {
            (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point))
            for ref_point, _col, _value in rows
        }
        missing_dates = sorted({
            key.date() if isinstance(key, pd.Timestamp) else key
            for key in (requested_keys - covered_keys)
        })

        # If everything is locally available, skip remote entirely.
        if not missing_dates:
            return rows

        # 3) Fetch only the missing dates from Supabase L2 (batch).
        sync = self._prefetch_remote_range(
            symbol=symbol,
            start_date=min(missing_dates),
            end_date=max(missing_dates),
        )
        if sync is None:
            return rows

        local_present_dates = {
            _normalize_eod_key(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts)
            for ts in (df.index if isinstance(df.index, pd.DatetimeIndex) else [])
        }
        candidate_pull_dates = [trading_date for trading_date in missing_dates if trading_date not in local_present_dates]
        if not candidate_pull_dates:
            candidate_pull_dates = missing_dates
        if not candidate_pull_dates:
            return rows

        # Use batch pull (single SQL query) instead of per-day loop
        pulled_any = False
        pull_batch_fn = getattr(sync, "pull_days_batch", None)
        if callable(pull_batch_fn):
            try:
                fetched = pull_batch_fn(symbol, candidate_pull_dates)
                pulled_any = bool(fetched)
            except Exception:
                logger.warning(
                    "Computed TS L2 batch pull failed for %s (%d dates), falling back to per-day",
                    symbol,
                    len(candidate_pull_dates),
                    exc_info=True,
                )
                for trading_date in candidate_pull_dates:
                    try:
                        pulled_any = sync.pull_day(symbol, trading_date) or pulled_any
                    except Exception:
                        logger.warning(
                            "Computed TS L2 pull failed for %s/%s",
                            symbol,
                            trading_date,
                            exc_info=True,
                        )
        else:
            for trading_date in candidate_pull_dates:
                try:
                    pulled_any = sync.pull_day(symbol, trading_date) or pulled_any
                except Exception:
                    logger.warning(
                        "Computed TS L2 pull failed for %s/%s",
                        symbol,
                        trading_date,
                        exc_info=True,
                    )
        if not pulled_any:
            return rows

        # 4) Re-read local Parquet now that L2 data has been written locally.
        df = self._read_df(symbol=symbol, start=read_start, end=read_end)
        return self._rows_from_df(
            df=df,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )

    def _backfill_duckdb_from_rows(
        self,
        symbol: str,
        rows: List[Tuple[DateLike, str, float]],
        *,
        intraday: bool = False,
    ) -> None:
        """Backfill DuckDB from rows fetched via Parquet/L2 so subsequent reads are fast."""
        if self._duckdb_cache is None or not rows or intraday:
            return
        if getattr(self._duckdb_cache, "_read_only", False):
            return
        try:
            self._duckdb_cache.upsert_rows(symbol, rows)
        except Exception:
            logger.warning("DuckDB backfill failed for %s", symbol, exc_info=True)

    def _push_days_to_l2(
        self,
        *,
        symbol: str,
        trading_dates: Sequence[datetime.date],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not trading_dates:
            return

        unique_dates = sorted(set(trading_dates))

        def _bg_push() -> None:
            for trading_date in unique_dates:
                try:
                    sync.push_day(symbol, trading_date)
                except Exception:
                    logger.warning(
                        "Computed TS L2 push failed for %s/%s",
                        symbol,
                        trading_date,
                        exc_info=True,
                    )

        self._launch_background_push(name=f"computed-ts-day-push-{symbol}", target=_bg_push)

    def _push_rows_to_l2(
        self,
        *,
        symbol: str,
        rows: list[Tuple[DateLike, str, float]],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not rows or not hasattr(sync, "push_rows"):
            return
        row_data = [
            (_normalize_eod_key(ref_point), str(column_name), float(value))
            for ref_point, column_name, value in rows
        ]

        def _bg_push_rows() -> None:
            try:
                sync.push_rows(symbol, row_data)
            except Exception:
                logger.warning("Row-level L2 push failed for %s", symbol, exc_info=True)

        self._launch_background_push(name=f"computed-ts-row-push-{symbol}", target=_bg_push_rows)

    def _push_many_days_to_l2(
        self,
        *,
        trading_dates_by_symbol: Mapping[str, Sequence[datetime.date]],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not trading_dates_by_symbol:
            return

        normalized = {
            symbol: sorted(set(trading_dates))
            for symbol, trading_dates in trading_dates_by_symbol.items()
            if trading_dates
        }
        if not normalized:
            return

        def _bg_push() -> None:
            for symbol, trading_dates in normalized.items():
                for trading_date in trading_dates:
                    try:
                        sync.push_day(symbol, trading_date)
                    except Exception:
                        logger.warning(
                            "Computed TS L2 push failed for %s/%s",
                            symbol,
                            trading_date,
                            exc_info=True,
                        )

        self._launch_background_push(name="computed-ts-day-push-many", target=_bg_push)

    def _push_many_rows_to_l2(
        self,
        *,
        rows_by_symbol: Mapping[str, Sequence[Tuple[DateLike, str, float]]],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not rows_by_symbol or not hasattr(sync, "push_rows"):
            return

        normalized = {
            symbol: [
                (_normalize_eod_key(ref_point), str(column_name), float(value))
                for ref_point, column_name, value in rows
            ]
            for symbol, rows in rows_by_symbol.items()
            if rows
        }
        if not normalized:
            return

        def _bg_push_rows() -> None:
            for symbol, row_data in normalized.items():
                try:
                    sync.push_rows(symbol, row_data)
                except Exception:
                    logger.warning("Row-level L2 push failed for %s", symbol, exc_info=True)

        self._launch_background_push(name="computed-ts-row-push-many", target=_bg_push_rows)

    def _launch_background_push(
        self,
        *,
        name: str,
        target: Any,
    ) -> None:
        with self._bg_push_condition:
            self._bg_push_pending += 1

        def _run() -> None:
            try:
                target()
            finally:
                with self._bg_push_condition:
                    self._bg_push_pending = max(0, self._bg_push_pending - 1)
                    if self._bg_push_pending == 0:
                        self._bg_push_condition.notify_all()

        threading.Thread(target=_run, name=name, daemon=True).start()

    def wait_for_background_pushes(self, timeout: Optional[float] = None) -> int:
        """Wait for outstanding background Supabase pushes to finish.

        Returns the number of queued or in-flight background push tasks that
        were pending when the wait started.
        """
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        with self._bg_push_condition:
            waited = self._bg_push_pending
            while self._bg_push_pending > 0:
                remaining = None
                if deadline is not None:
                    remaining = max(0.0, deadline - time.monotonic())
                    if remaining <= 0.0:
                        return waited
                self._bg_push_condition.wait(timeout=remaining)
                if deadline is not None and time.monotonic() >= deadline and self._bg_push_pending > 0:
                    return waited
            return waited

    @staticmethod
    def _normalize_symbol_rows(
        rows: Iterable[Tuple[DateLike, str, float]],
    ) -> list[Tuple[pd.Timestamp, str, float]]:
        ordered: dict[pd.Timestamp, Tuple[str, float]] = {}
        for ref_point, column_name, value in rows:
            ordered[_normalize_intraday_key(ref_point)] = (str(column_name), float(value))
        return [(ts, col, val) for ts, (col, val) in ordered.items()]

    @staticmethod
    def _rows_are_intraday(normalized_rows: Sequence[Tuple[pd.Timestamp, str, float]]) -> bool:
        """True when any row carries a time-of-day component.

        EOD rows normalize to midnight, so a non-midnight stamp means these are
        intraday points and must NOT be written to the date-keyed tiers.
        """
        return any(
            (ts.hour or ts.minute or ts.second or ts.microsecond or ts.nanosecond)
            for ts, _col, _val in normalized_rows
        )

    def append_rows(
        self,
        *,
        symbol: str,
        rows: Iterable[Tuple[DateLike, str, float]],
        intraday: Optional[bool] = None,
    ) -> None:
        self.append_many_rows(rows_by_symbol={symbol: rows}, intraday=intraday)

    def append_many_rows(
        self,
        *,
        rows_by_symbol: Mapping[str, Iterable[Tuple[DateLike, str, float]]],
        intraday: Optional[bool] = None,
    ) -> None:
        """Persist computed rows.

        ``intraday`` selects which tiers are written; ``None`` auto-detects from
        the timestamps. The Parquet layer always stores full resolution. The
        DuckDB table and the row-level L2 table are keyed ``(symbol, date)`` and
        are EOD-only: writing intraday points into them collapses a whole day
        onto one arbitrary minute (last write wins, and with n_jobs>1 *which*
        minute is nondeterministic) and then serves that value to the next
        daily-frequency read of the same symbol. The reader already refuses to
        read those tiers for intraday (see ``_read_from_duckdb``); this is the
        matching guard on the writer, which never had one.
        """
        normalized_by_symbol = {
            symbol: self._normalize_symbol_rows(rows)
            for symbol, rows in rows_by_symbol.items()
        }
        normalized_by_symbol = {
            symbol: rows
            for symbol, rows in normalized_by_symbol.items()
            if rows
        }
        if not normalized_by_symbol:
            return

        frame_items = []
        duckdb_rows_by_symbol: dict[str, list[Tuple[datetime.date, str, float]]] = {}
        trading_dates_by_symbol: dict[str, list[datetime.date]] = {}
        l2_rows_by_symbol: dict[str, list[Tuple[DateLike, str, float]]] = {}

        for symbol, normalized_rows in normalized_by_symbol.items():
            index = pd.DatetimeIndex([ts for ts, _col, _val in normalized_rows])
            df = pd.DataFrame(
                {
                    "value": [val for _ts, _col, val in normalized_rows],
                    "_column_name": [col for _ts, col, _val in normalized_rows],
                },
                index=index,
            ).sort_index()
            frame_items.append((symbol, df, None))

            # The whole-day Parquet blob keeps full resolution and is the tier the
            # intraday reader actually uses, so it is pushed either way.
            trading_dates_by_symbol[symbol] = [ts.date() for ts, _col, _val in normalized_rows]

            symbol_intraday = (
                self._rows_are_intraday(normalized_rows) if intraday is None else bool(intraday)
            )
            if symbol_intraday:
                # The two date-keyed VALUE tiers are EOD-only; see the docstring.
                logger.debug(
                    "Skipping date-keyed value tiers for %d intraday row(s) of %s",
                    len(normalized_rows), symbol,
                )
                continue

            duckdb_rows = [
                (_normalize_eod_key(ts.to_pydatetime()), str(col), float(val))
                for ts, col, val in normalized_rows
            ]
            duckdb_rows_by_symbol[symbol] = duckdb_rows
            l2_rows_by_symbol[symbol] = [
                (ts.to_pydatetime(), col, val)
                for ts, col, val in normalized_rows
            ]

        append_timeseries_many(
            None,
            frame_items,
            opts=self._opts,
        )

        if self._duckdb_cache is not None:
            try:
                self._duckdb_cache.upsert_many_rows(duckdb_rows_by_symbol)
            except Exception:
                logger.warning("DuckDB bulk upsert failed", exc_info=True)

        self._push_many_days_to_l2(trading_dates_by_symbol=trading_dates_by_symbol)
        self._push_many_rows_to_l2(rows_by_symbol=l2_rows_by_symbol)
