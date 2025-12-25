import datetime
import re
import threading
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

import pandas as pd
import pytz

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from MDP.USTFutures.BARCHART.BarchartFetcher import BarchartFetcher
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer
from definitions.USTFutures import to_barchart_root

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
InstrumentLike = _USTFutureGenericPricer


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if ts == "live":
        return datetime.datetime.now(pytz.UTC)
    if isinstance(ts, datetime.datetime):
        return ts
    if isinstance(ts, datetime.date):
        return datetime.datetime(ts.year, ts.month, ts.day, tzinfo=pytz.UTC)
    raise TypeError("timestamp must be date, datetime, or 'live'")


_INTERNAL_ROOTS = {"TU", "FV", "TY", "US", "WN", "UXY"}
_BARCHART_ROOTS = {to_barchart_root(k): k for k in _INTERNAL_ROOTS}


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s

    root = m.group("root")
    code = m.group("code")

    if root in _INTERNAL_ROOTS:
        return s
    if root in _BARCHART_ROOTS:
        return f"{_BARCHART_ROOTS[root]}{code}"
    return s


def _to_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s
    root = m.group("root")
    code = m.group("code")
    barchart_root = to_barchart_root(root)
    return f"{barchart_root}{code}"


def _from_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s
    root = m.group("root")
    code = m.group("code")
    if root in _BARCHART_ROOTS:
        return f"{_BARCHART_ROOTS[root]}{code}"
    return s


def _clean_symbols(symbols: Sequence[str]) -> List[str]:
    out = []
    for raw in symbols:
        norm = _normalize_symbol(raw)
        if norm:
            out.append(norm)
    return out


class USTFuturesMDP(MarketDataProvider[InstrumentLike], ZODBCacheMixin):
    _UST_PRICER_CACHE = "USTFuturePricer_Cache"

    def __init__(self, source: str = "BARCHART_USTF-RL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        ZODBCacheMixin.__init__(self)
        self._fetcher = None
        self._open_lock = threading.RLock()
        self._open_count = 0
        self._cache_ready = False

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._UST_PRICER_CACHE):
            return
        cache_path = ZODBCacheMixin.default_cache_path("USTFuturePricer_Cache")
        self.zodb_open_cache(cache_attr=self._UST_PRICER_CACHE, path=cache_path, encode=None, decode=None)
        self._cache_ready = True

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._UST_PRICER_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._UST_PRICER_CACHE)
            return cache.get(key)

    def _get_fetcher(self) -> BarchartFetcher:
        if self._fetcher is None:
            self._fetcher = BarchartFetcher()
        return self._fetcher

    def _fetch_barchart_timeseries(
        self,
        tickers: List[str],
        ts_dt: datetime.datetime,
        *,
        show_tqdm: bool,
        interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]],
    ) -> pd.DataFrame:
        chi = pytz.timezone("America/Chicago")
        ts_chi = ts_dt.astimezone(chi)

        start = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 0, 1))
        end = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 23, 59))

        barchart_syms = [_to_barchart_symbol(t) for t in tickers]
        bcf = self._get_fetcher()
        return bcf.barchart_timeseries_api(
            barchart_symbols=barchart_syms,
            start_date=start,
            end_date=end,
            interval=interval,
            one_df=True,
            show_tqdm=show_tqdm,
            max_concurrent_tasks=len(barchart_syms) + 1,
        )

    def _build_pricer(self, symbol: str, price: float, ts_dt: datetime.datetime) -> RLUSTFuturePricer:
        return RLUSTFuturePricer(
            symbol=symbol,
            reference_date=ts_dt,
            price=float(price),
        )

    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any]) -> RLUSTFuturePricer:
        symbol = args["symbol"]
        price = float(args["price"])
        timestamp_str = args["timestamp"]

        if isinstance(timestamp_str, str):
            try:
                ref_date = datetime.date.fromisoformat(timestamp_str.split("T")[0])
            except ValueError:
                ref_date = pd.Timestamp(timestamp_str).date()
        elif isinstance(timestamp_str, (datetime.date, datetime.datetime)):
            ref_date = _as_datetime(timestamp_str).date()
        else:
            ref_date = datetime.date.today()

        return RLUSTFuturePricer(
            symbol=symbol,
            reference_date=ref_date,
            price=price,
            meta_data=args,
        )

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, InstrumentLike]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamp: DateLike = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        interval = request.get("interval")
        force_refresh = bool(request.get("force_refresh", False))

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        ts_dt = _as_datetime(timestamp)
        ts_iso = ts_dt.isoformat()

        with self:
            out: Dict[str, InstrumentLike] = {}
            missing: List[str] = []

            for sym in symbols:
                cache_key = f"{ts_iso}-{sym}-{self.source}"
                cached = None if force_refresh else self._threadsafe_cache_get(cache_key)
                if cached is not None:
                    out[sym] = self._build_pricer_from_args(cached)
                else:
                    missing.append(sym)

            if missing:
                df = self._fetch_barchart_timeseries(missing, ts_dt, show_tqdm=show_tqdm, interval=interval)
                if df.empty:
                    raise ValueError("No data returned from Barchart for requested UST futures.")

                df = df.rename(columns={c: _from_barchart_symbol(str(c)) for c in df.columns})
                latest = df.iloc[-1]

                for sym in missing:
                    if sym not in latest:
                        continue
                    args = {
                        "symbol": sym,
                        "price": float(latest[sym]),
                        "timestamp": ts_iso,
                        "schema": 1,
                    }
                    out[sym] = self._build_pricer_from_args(args)
                    cache_key = f"{ts_iso}-{sym}-{self.source}"
                    self._threadsafe_cache_put(cache_key, args)

            if not out:
                raise ValueError("No matching UST futures prices for requested symbols.")
            return out

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        symbols: Sequence[str],
        *,
        show_tqdm: bool = False,
    ) -> Dict[DateLike, Dict[str, InstrumentLike]]:
        out: Dict[DateLike, Dict[str, InstrumentLike]] = {}
        for ts in timestamps:
            out[ts] = self.get_pricer({"symbols": symbols, "timestamp": ts, "show_tqdm": show_tqdm})
        return out

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
