import datetime
import threading
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union

import pandas as pd
import pytz
import rateslib as rl
from pandas.tseries.offsets import BDay

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import (
    _imm_cutoff,
    _next_contracts,
    cme_code_effective_date,
    first_business_day_next_month,
)
from MDP.MarketDataProvider import MarketDataProvider

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if ts == "live":
        return datetime.datetime.now(pytz.UTC)
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            return pytz.timezone("America/New_York").localize(ts)
        return ts
    if isinstance(ts, datetime.date):
        return pytz.timezone("America/New_York").localize(datetime.datetime.combine(ts, datetime.time(hour=12)))
    raise TypeError("timestamp must be date, datetime, or 'live'")


def _as_date(ts: DateLike) -> datetime.date:
    if ts == "live":
        return datetime.date.today()
    if isinstance(ts, datetime.datetime):
        return ts.date()
    if isinstance(ts, datetime.date):
        return ts
    raise TypeError("timestamp must be date, datetime, or 'live'")


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    # If bare month code like "H26", assume SR3 root (3M SOFR)
    if re.fullmatch(r"[FGHJKMNQUVXZ]\d{2}", s):
        return f"SR3{s}"

    m = re.match(r"^(SR[13]|SFR|SER|FF|ZQ)([FGHJKMNQUVXZ]\d{2})$", s)
    if m:
        root, code = m.groups()
        root = root.replace("SFR", "SR3").replace("SER", "SR1").replace("FF", "ZQ")
        return f"{root}{code}"

    return WebullFintechFetcher._normalize_future_symbol(s)


def _package_contracts(color: str, as_of: datetime.date) -> List[str]:
    color_order = ["whites", "reds", "greens", "blues", "golds", "silvers", "platinums"]
    offset = color_order.index(color) * 4
    count = offset + 4
    contracts = _next_contracts(
        as_of, prefix="SR3", count=count, valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff
    )
    return contracts[offset:count]


def _resolve_aliases_bulk(symbols: Iterable[str], timestamp: DateLike) -> "OrderedDict[str, List[str]]":
    aliases: "OrderedDict[str, List[str]]" = OrderedDict()
    as_of = _as_date(timestamp)
    color_set = {"whites", "reds", "greens", "blues", "golds", "silvers", "platinums"}

    for raw in symbols:
        alias = (raw or "").strip()
        if not alias:
            continue

        lower = alias.lower()
        try:
            # Package colors: whites/reds/greens/... map to consecutive IMM months
            if lower in color_set:
                aliases[alias] = _package_contracts(lower, as_of)
                continue

            # Constant maturity rank: CM1 = front, CM2 = 2nd, etc. Optional root prefix.
            m_cm = re.match(r"^(?P<prefix>(sr[13]|sfr|ser|ff|zq)?)cm(?P<rank>\d+)$", lower)
            if m_cm:
                rank = int(m_cm.group("rank"))
                prefix = (m_cm.group("prefix") or "SR3").upper()
                root = prefix.replace("SFR", "SR3").replace("SER", "SR1").replace("FF", "ZQ")
                valid_months = [3, 6, 9, 12] if root.startswith("SR3") else list(range(1, 13))
                cutoff = _imm_cutoff if root.startswith("SR3") else None
                contracts = _next_contracts(as_of, prefix=root, count=max(rank, 1), valid_months=valid_months, cutoff_fn=cutoff)
                aliases[alias] = [contracts[rank - 1]]
                continue

            norm = _normalize_symbol(alias)
            if norm:
                aliases[alias] = [norm]
                continue

            # If we reach here, we will keep the raw alias to avoid dropping inputs
            aliases[alias] = [alias]
        except Exception:
            aliases[alias] = [alias]

    return aliases


def _clean_symbols(symbols: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for s in symbols:
        token = (s or "").strip()
        if not token:
            continue
        if "x" in token:
            cleaned.extend([p for p in token.split("x") if p])
        elif "/" in token:
            cleaned.extend([p for p in token.split("/") if p])
        else:
            cleaned.append(token)
    return cleaned


def _stir_future_from_symbol(sym: str, price: float) -> Tuple[str, rl.STIRFuture]:
    norm = _normalize_symbol(sym)
    if not norm:
        raise ValueError(f"Invalid STIR future symbol: {sym}")

    m = re.match(r"^(?P<root>[A-Z0-9]+)(?P<code>[FGHJKMNQUVXZ]\d{2})$", norm)
    if not m:
        raise ValueError(f"Could not parse STIR future symbol: {sym}")

    root = m.group("root")
    code = m.group("code")

    if root.startswith("SR1") or root.startswith("ZQ"):
        effective = cme_code_effective_date(code)
        termination = first_business_day_next_month(pd.Timestamp(effective))
        stir = rl.STIRFuture(
            effective=effective,
            termination=termination,
            spec="usd_stir1",
            roll="som",
            price=price,
        )
        return norm, stir

    effective = rl.scheduling.get_imm(code=code)
    termination = rl.scheduling.next_imm(effective)
    stir = rl.STIRFuture(
        effective=effective,
        termination=termination,
        spec="usd_stir",
        price=price,
    )
    return norm, stir


class STIRFutureMDP(MarketDataProvider[rl.STIRFuture], ZODBCacheMixin):
    _STIR_PRICER_CACHE = "_stir_pricer_cache"

    def __init__(self, source: str = "WEBULL_STIRF-RL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        ZODBCacheMixin.__init__(self)

        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

    # ----------------------------- cache helpers -----------------------------
    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._STIR_PRICER_CACHE):
            return
        cache_path = ZODBCacheMixin.default_cache_path("STIRFuturePricer_Cache")
        self.zodb_open_cache(cache_attr=self._STIR_PRICER_CACHE, path=cache_path, encode=None, decode=None)
        self._cache_ready = True

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._STIR_PRICER_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._STIR_PRICER_CACHE)
            return cache.get(key)

    # ----------------------------- helpers -----------------------------------
    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any]) -> rl.STIRFuture:
        sym = args["symbol"]
        price = float(args["price"])
        _, stir = _stir_future_from_symbol(sym, price)
        return stir

    def _fetch_webull_intraday(
        self,
        tickers: List[str],
        ts_dt: datetime.datetime,
        *,
        show_tqdm: bool,
    ) -> pd.DataFrame:
        chi = pytz.timezone("America/Chicago")
        ts_chi = ts_dt.astimezone(chi)
        start = (pd.Timestamp(ts_chi) - BDay(1)).to_pydatetime()
        end = (pd.Timestamp(ts_chi) + BDay(1)).to_pydatetime()

        wb = WebullFintechFetcher(debug_verbose=False, error_verbose=True)
        return wb.intraday_by_tickers(
            tickers=tickers,
            start=start,
            end=end,
            show_tqdm=show_tqdm,
        )

    def _get_data_for_timestamp(
        self,
        symbols: List[str],
        timestamp: DateLike,
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
    ) -> Dict[str, List[rl.STIRFuture]]:
        ts_dt = _as_datetime(timestamp)
        alias_map = _resolve_aliases_bulk(symbols, timestamp)
        if not alias_map:
            raise ValueError("No valid symbols resolved from request.")

        if self.source.upper() != "WEBULL_STIRF-RL":
            raise NotImplementedError(f"Unsupported source {self.source}")

        self._ensure_pricer_cache()
        result: Dict[str, List[rl.STIRFuture]] = {}

        # First try cache for exact timestamp
        to_fetch: "OrderedDict[str, List[str]]" = OrderedDict()
        ts_iso = ts_dt.isoformat()
        for alias, tickers in alias_map.items():
            futs: List[rl.STIRFuture] = []
            for t in tickers:
                cache_key = f"{ts_iso}-{t}-{self.source.upper()}"
                cached = None if force_refresh else self._threadsafe_cache_get(cache_key)
                if cached is not None:
                    futs.append(self._build_pricer_from_args(cached))
                else:
                    to_fetch.setdefault(alias, []).append(t)
            if futs:
                result[alias] = futs

        all_missing = sorted({t for lst in to_fetch.values() for t in lst})
        price_df = pd.DataFrame()
        if all_missing:
            price_df = self._fetch_webull_intraday(all_missing, ts_dt, show_tqdm=show_tqdm)
            if price_df.empty:
                raise RuntimeError("Webull returned no data for requested STIR futures.")

            # Persist all slices for future reuse
            for t in price_df.columns:
                series = price_df[t].dropna()
                for curr_ts, px in series.items():
                    args = {
                        "symbol": t,
                        "price": float(px),
                        "timestamp": curr_ts.isoformat(),
                        "schema": 1,
                    }
                    cache_key = f"{curr_ts.isoformat()}-{t}-{self.source.upper()}"
                    self._threadsafe_cache_put(cache_key, args)

        # Build outputs for any still missing
        for alias, tickers in to_fetch.items():
            futs: List[rl.STIRFuture] = result.get(alias, [])
            for t in tickers:
                cache_key = f"{ts_iso}-{t}-{self.source.upper()}"
                cached = None if force_refresh else self._threadsafe_cache_get(cache_key)
                if cached is None and not price_df.empty and t in price_df:
                    series = price_df[t].dropna()
                    if series.empty:
                        continue
                    pos = series.index.get_indexer([ts_dt], method="nearest")
                    idx = series.index[pos[0]] if pos.size and pos[0] != -1 else series.index[-1]
                    args = {
                        "symbol": t,
                        "price": float(series.loc[idx]),
                        "timestamp": idx.isoformat(),
                        "schema": 1,
                    }
                    cache_key = f"{idx.isoformat()}-{t}-{self.source.upper()}"
                    self._threadsafe_cache_put(cache_key, args)
                    cached = args

                if cached is None:
                    continue

                futs.append(self._build_pricer_from_args(cached))
            if futs:
                result[alias] = futs

        return result

    # ----------------------------- public API --------------------------------
    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[rl.STIRFuture]]:
        return self.get_data(request)

    def get_data(self, request: Dict[str, Any]) -> Dict[str, List[rl.STIRFuture]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamp: DateLike = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        force_refresh = bool(request.get("force_refresh", False))

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        with self.__open__():
            return self._get_data_for_timestamp(
                symbols,
                timestamp,
                show_tqdm=show_tqdm,
                force_refresh=force_refresh,
            )

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        symbols: Sequence[str],
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
    ) -> Dict[DateLike, Dict[str, List[rl.STIRFuture]]]:
        jobs: List[Tuple[DateLike, List[str]]] = []
        base_symbols = _clean_symbols(symbols)
        for ts in timestamps:
            jobs.append((ts, base_symbols))

        results: List[Tuple[DateLike, Dict[str, List[rl.STIRFuture]]]] = []

        with self.__open__():
            def _process_one(ts: DateLike, syms: List[str]):
                return ts, self._get_data_for_timestamp(syms, ts, show_tqdm=show_tqdm, force_refresh=force_refresh)

            if max_workers == 1 or len(jobs) == 1:
                iterable = jobs
                if show_tqdm:
                    import tqdm

                    iterable = tqdm.tqdm(iterable, desc="FETCHING STIR FUTURES")
                for ts, syms in iterable:
                    results.append(_process_one(ts, syms))
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="stir-mdp") as pool:
                    futures = {pool.submit(_process_one, ts, syms): (ts, syms) for ts, syms in jobs}
                    iterator = as_completed(futures)
                    if show_tqdm:
                        import tqdm

                        iterator = tqdm.tqdm(iterator, total=len(futures), desc="FETCHING STIR FUTURES")
                    for fut in iterator:
                        results.append(fut.result())

            out: Dict[DateLike, Dict[str, List[rl.STIRFuture]]] = defaultdict(dict)
            for ts, res in results:
                if res:
                    out[ts].update(res)
            return dict(out)

    # --------------------------- context managers ----------------------------
    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_pricer_cache()
            self._open_count += 1
        return self

    def __close__(self, *, commit: bool = True):
        with self._open_lock:
            if self._open_count <= 0:
                return
            self._open_count -= 1
            if self._open_count == 0:
                try:
                    if commit:
                        self.zodb_commit()
                finally:
                    try:
                        self.close_zodb()
                    finally:
                        self._cache_ready = False

    def __enter__(self):
        return self.__open__()

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))
