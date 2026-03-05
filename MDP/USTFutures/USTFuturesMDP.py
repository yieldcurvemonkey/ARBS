import datetime
import itertools
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import pandas as pd
import pytz
import requests

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from MDP.USTFutures.BARCHART.BarchartFetcher import BarchartFetcher
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer
from definitions.USTFutures import to_barchart_root

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
InstrumentLike = _USTFutureGenericPricer


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if ts == "live":
        return datetime.datetime.now(pytz.UTC)
    if isinstance(ts, datetime.datetime):
        return ts

    # 2pm chicago close
    if isinstance(ts, datetime.date):
        return pytz.timezone("America/Chicago").localize(datetime.datetime(ts.year, ts.month, ts.day, 14, 0))

    raise TypeError("timestamp must be date, datetime, or 'live'")


_INTERNAL_ROOTS = {"TU", "FV", "TY", "US", "WN", "UXY"}
_BARCHART_ROOTS = {to_barchart_root(k): k for k in _INTERNAL_ROOTS}
_CME_QUARTERLY_MONTH_CODES = {
    "H": [1, 2, 3],
    "M": [4, 5, 6],
    "U": [7, 8, 9],
    "Z": [10, 11, 12],
}


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


def _build_socks5h(host: str) -> dict:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
    return {"http": url, "https": url}


def _preflight_proxy(proxies: dict | None, timeout: int = 6) -> bool:
    try:
        r = requests.get(
            "https://api.ipify.org?format=json",
            proxies=proxies,
            timeout=timeout,
            headers={"Connection": "close"},
        )
        r.raise_for_status()
        return True
    except Exception:
        return False


class _ProxyGuard:
    """Force chosen proxies + Connection: close for token fetches (reduce WAF flakiness)."""

    def __init__(self, proxies: dict | None):
        self.proxies = proxies

    def __enter__(self):
        self._orig_get = requests.get

        def _patched_get(url, *args, **kwargs):
            hdrs = kwargs.pop("headers", {}) or {}
            title_map = {k.title(): v for k, v in hdrs.items()}
            if "Connection" not in title_map:
                hdrs["Connection"] = "close"
            kwargs["headers"] = hdrs
            if self.proxies is not None:
                kwargs["proxies"] = self.proxies
            else:
                kwargs.pop("proxies", None)
            return self._orig_get(url, *args, **kwargs)

        requests.get = _patched_get
        return self

    def __exit__(self, exc_type, exc, tb):
        requests.get = self._orig_get


class USTFuturesMDP(MarketDataProvider[InstrumentLike], DiskCacheMixin):
    _UST_PRICER_CACHE = "USTFuturePricer_Cache"
    _UST_BASKET_CACHE = "USTFutureDeliveryBasket_Cache"
    _BARCHART_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "BARCHART_USTF-RL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        DiskCacheMixin.__init__(self)
        self._open_lock = threading.RLock()
        self._open_count = 0
        self._cache_ready = False
        self._basket_cache_ready = False

        default_hosts = [
            "atlanta.us.socks.nordhold.net",
            "chicago.us.socks.nordhold.net",
            "dallas.us.socks.nordhold.net",
            "los-angeles.us.socks.nordhold.net",
            "new-york.us.socks.nordhold.net",
            "phoenix.us.socks.nordhold.net",
            "san-francisco.us.socks.nordhold.net",
            "us.socks.nordhold.net",
            None,
        ]
        self._barchart_proxy_hosts: List[Optional[str]] = list(kwargs.get("barchart_proxy_hosts", default_hosts))
        random.shuffle(self._barchart_proxy_hosts)
        self._barchart_proxy_ttl: int = int(kwargs.get("barchart_proxy_ttl", 60))

        if not USTFuturesMDP._BARCHART_STATE:
            USTFuturesMDP._BARCHART_STATE = {
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
                "fetcher": None,
                "cycler": itertools.cycle(self._barchart_proxy_hosts),
                "lock": threading.RLock(),
            }

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._UST_PRICER_CACHE):
            return
        cache_path = DiskCacheMixin.default_cache_path("USTFuturePricer_Cache")
        self.open_cache(cache_attr=self._UST_PRICER_CACHE, path=cache_path, encode=None, decode=None)
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

    def _ensure_basket_cache(self) -> None:
        if self._basket_cache_ready and hasattr(self, self._UST_BASKET_CACHE):
            return
        cache_path = DiskCacheMixin.default_cache_path("USTFutureDeliveryBasket_Cache")
        self.open_cache(cache_attr=self._UST_BASKET_CACHE, path=cache_path, encode=None, decode=None)
        self._basket_cache_ready = True

    def _threadsafe_basket_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_basket_cache()
            cache = getattr(self, self._UST_BASKET_CACHE)
            return cache.get(key)

    def _threadsafe_basket_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_basket_cache()
            cache = getattr(self, self._UST_BASKET_CACHE)
            cache[key] = value

    def _get_cached_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = USTFuturesMDP._BARCHART_STATE
        if time.time() - float(S["chosen_at"]) < float(S["ttl"]):
            return S["proxies"], S["host"]
        return None, None

    def _choose_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = USTFuturesMDP._BARCHART_STATE
        cycler = S["cycler"]

        for _ in range(len(self._barchart_proxy_hosts)):
            host = next(cycler)
            if host is None:
                return None, None
            try:
                proxies = _build_socks5h(host)
            except Exception:
                continue
            if _preflight_proxy(proxies):
                return proxies, host

        return None, None

    def _get_barchart_fetcher(self) -> BarchartFetcher:
        S = USTFuturesMDP._BARCHART_STATE
        with S["lock"]:
            def _safe_close(fetcher: Optional[BarchartFetcher]) -> None:
                if fetcher is None:
                    return
                try:
                    fetcher.close()
                except Exception:
                    pass

            def _build_fetcher(fetcher_proxies: Optional[dict], fetcher_host: Optional[str]) -> BarchartFetcher:
                scope_host = fetcher_host if fetcher_host is not None else "direct"
                return BarchartFetcher(
                    proxies=fetcher_proxies,
                    debug_verbose=False,
                    error_verbose=True,
                    session_token_ttl_seconds=max(1, int(S["ttl"])),
                    session_token_scope=f"{self.__class__.__name__}:{scope_host}",
                )

            proxies, host = self._get_cached_barchart_proxy()
            if proxies is None and host is None:
                _safe_close(S.get("fetcher"))
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                S["fetcher"] = None

            bcf = S["fetcher"]
            if bcf is None:
                bcf = _build_fetcher(proxies, host)
                S["fetcher"] = bcf

            try:
                bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                _safe_close(S.get("fetcher"))
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = _build_fetcher(proxies, host)
                S["fetcher"] = bcf
                bcf._fetch_session_tokens(dummy_symbol="BTC")

            return bcf

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
        bcf = self._get_barchart_fetcher()
        return bcf.barchart_timeseries_api(
            barchart_symbols=barchart_syms,
            start_date=start,
            end_date=end,
            interval=interval,
            one_df=True,
            show_tqdm=show_tqdm,
            max_concurrent_tasks=len(barchart_syms) + 1,
        )

    @staticmethod
    def _parse_reference_date(timestamp: Any) -> datetime.date:
        if isinstance(timestamp, str):
            try:
                return datetime.date.fromisoformat(timestamp.split("T")[0])
            except ValueError:
                return pd.Timestamp(timestamp).date()
        if isinstance(timestamp, (datetime.date, datetime.datetime)):
            return _as_datetime(timestamp).date()
        return datetime.date.today()

    def _build_pricer(
        self,
        symbol: str,
        price: float,
        ts_dt: datetime.datetime,
        *,
        delivery: Optional[Tuple[datetime.date, datetime.date]] = None,
        basket_pricers: Optional[List[Any]] = None,
        conversion_factors: Optional[List[float]] = None,
        contract_coupon: Optional[float] = None,
        currency: str = "USD",
        curve_id: str = "USD-SOFR-1D",
        calc_mode: Optional[str] = None,
        meta_data: Optional[Any] = None,
    ) -> RLUSTFuturePricer:
        return RLUSTFuturePricer(
            symbol=symbol,
            reference_date=ts_dt,
            price=float(price),
            delivery=delivery,
            basket=basket_pricers,
            conversion_factors=conversion_factors,
            coupon=contract_coupon or 6.0,
            currency=currency,
            curve_id=curve_id,
            calc_mode=calc_mode,
            meta_data=meta_data,
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
            delivery=args.get("delivery"),
            basket=args.get("basket_pricers"),
            conversion_factors=args.get("conversion_factors"),
            coupon=args.get("contract_coupon", 6.0),
            currency=args.get("currency", "USD"),
            curve_id=args.get("curve_id", "USD-SOFR-1D"),
            calc_mode=args.get("calc_mode"),
            meta_data=args,
        )

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, InstrumentLike]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamp: DateLike = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        interval = request.get("interval", 1)
        force_refresh = bool(request.get("force_refresh", False))
        include_basket = bool(request.get("include_basket", True))
        basket_source = request.get("basket_source", "RL_CME_TCF")
        curve_id = request.get("curve_id", "USD-SOFR-1D")
        currency = request.get("currency", "USD")
        contract_coupon = request.get("contract_coupon", 6)
        usts_mdp_source = request.get("usts_mdp_source")

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        ts_dt = _as_datetime(timestamp)
        ts_iso = ts_dt.isoformat()

        with self:
            out: Dict[str, InstrumentLike] = {}
            missing: List[str] = []

            for sym in symbols:
                if len(sym) <= 3:
                    import rateslib as rl

                    if rl.dt(timestamp.year, timestamp.month, timestamp.day) >= rl.get_imm(year=timestamp.year, month=timestamp.month):
                        contract_imm_date = rl.next_imm(start=rl.dt(timestamp.year, timestamp.month, timestamp.day))
                        if contract_imm_date.month == 3:
                            sym = f"{sym}{'H'}{int(contract_imm_date.strftime("%y"))}"
                        elif contract_imm_date.month == 6:
                            sym = f"{sym}{'M'}{int(contract_imm_date.strftime("%y"))}"
                        elif contract_imm_date.month == 9:
                            sym = f"{sym}{'U'}{int(contract_imm_date.strftime("%y"))}"
                        elif contract_imm_date.month == 12:
                            sym = f"{sym}{'Z'}{int(contract_imm_date.strftime("%y"))}"
                    else:
                        for m_code, month_nums in _CME_QUARTERLY_MONTH_CODES.items():
                            if timestamp.month in month_nums:
                                sym = f"{sym}{m_code}{int(timestamp.strftime("%y"))}"
                                break
                
                cache_key = f"{ts_iso}-{sym}-{self.source}"
                cached = None if force_refresh else self._threadsafe_cache_get(cache_key)
                if cached is not None:
                    ref_dt = self._parse_reference_date(cached.get("timestamp"))
                    basket_data = None
                    if include_basket:
                        basket_data = self.get_delivery_basket(
                            as_of=ts_dt.date(),
                            symbol=sym,
                            usts_mdp_source=usts_mdp_source,
                            source=basket_source,
                        )
                    out[sym] = self._build_pricer(
                        symbol=sym,
                        price=float(cached["price"]),
                        ts_dt=ref_dt,
                        delivery=basket_data["delivery"] if basket_data else None,
                        basket_pricers=basket_data["basket_pricers"] if basket_data else None,
                        conversion_factors=basket_data["conversion_factors"] if basket_data else None,
                        contract_coupon=basket_data.get("contract_coupon") if basket_data else contract_coupon,
                        currency=currency,
                        curve_id=curve_id,
                        calc_mode=basket_data.get("calc_mode") if basket_data else None,
                        meta_data=cached,
                    )
                else:
                    missing.append(sym)

            if missing:
                df = self._fetch_barchart_timeseries(missing, ts_dt, show_tqdm=show_tqdm, interval=interval)
                if df.empty:
                    raise ValueError("No data returned from Barchart for requested UST futures.")

                df = df.rename(columns={c: _from_barchart_symbol(str(c)) for c in df.columns})
                latest = df.iloc[-1]

                for sym in missing:
                    if sym not in df:
                        continue
                    series = df[sym].dropna()
                    if series.empty:
                        continue
                    if isinstance(series.index, pd.DatetimeIndex):
                        pos = series.index.get_indexer([ts_dt], method="nearest")
                        idx = series.index[pos[0]] if pos.size and pos[0] != -1 else series.index[-1]
                        ts_stamp = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                    else:
                        idx = series.index[-1]
                        ts_stamp = ts_iso
                    ref_dt = self._parse_reference_date(ts_stamp)
                    args = {
                        "symbol": sym,
                        "price": float(series.loc[idx]),
                        "timestamp": ts_stamp,
                        "schema": 1,
                    }
                    basket_data = None
                    if include_basket:
                        basket_data = self.get_delivery_basket(
                            as_of=ts_dt.date(),
                            symbol=sym,
                            usts_mdp_source=usts_mdp_source,
                            source=basket_source,
                        )
                    out[sym] = self._build_pricer(
                        symbol=sym,
                        price=float(series.loc[idx]),
                        ts_dt=ref_dt,
                        delivery=basket_data["delivery"] if basket_data else None,
                        basket_pricers=basket_data["basket_pricers"] if basket_data else None,
                        conversion_factors=basket_data["conversion_factors"] if basket_data else None,
                        contract_coupon=basket_data.get("contract_coupon") if basket_data else contract_coupon,
                        currency=currency,
                        curve_id=curve_id,
                        calc_mode=basket_data.get("calc_mode") if basket_data else None,
                        meta_data=args,
                    )
                    cache_key = f"{ts_iso}-{sym}-{self.source}"
                    cache_key2 = f"{args['timestamp']}-{sym}-{self.source}"
                    self._threadsafe_cache_put(cache_key, args)
                    self._threadsafe_cache_put(cache_key2, args)

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

    def get_delivery_basket(
        self,
        *,
        as_of: datetime.date,
        symbol: str,
        usts_mdp_source: Optional[str] = "USTS_FEDINVEST_WSJ_LIVE-RL",
        source: str = "RL_CME_TCF",
        ignore_cache: Optional[bool] = False,
    ) -> Dict[str, Any]:
        if source != "RL_CME_TCF":
            raise ValueError(f"Unsupported delivery basket source: {source}")

        import rateslib as rl
        from pandas.tseries.offsets import BMonthBegin, BMonthEnd
        from MDP.FixedRateBonds.reference_data_cache.cme_tcf import read_cme_tcf_with_headers

        usts_mdp = FixedRateBondsMDP(source=usts_mdp_source)

        # cache only the *reference* basket definition (cusips/cfs/delivery window/etc),
        # NOT the live cash pricers (they depend on usts_mdp + timestamp).
        cache_key = f"{source}|{symbol}|{as_of.isoformat()}"
        with self:
            cached = self._threadsafe_basket_cache_get(cache_key)

        if cached is None or ignore_cache:
            # explict ticker passed in e.g. USH26
            if len(symbol) > 3:
                root = symbol[:-3]
                contract_imm_date = rl.get_imm(code=symbol[-3:])
            else:
                # constant maturity passed in e.g. US
                root = symbol
                contract_imm_date = rl.next_imm(start=datetime.datetime(as_of.year, as_of.month, as_of.day))

            tcf_period = int(contract_imm_date.strftime("%Y%m"))

            cme_tcf_df = read_cme_tcf_with_headers(as_of=as_of)
            cme_tcf_df = cme_tcf_df[(cme_tcf_df["ticker"] == root) & (cme_tcf_df["period"] == tcf_period)].copy()

            if cme_tcf_df.empty:
                raise ValueError(f"No CME TCF deliverables found for {symbol} at period {tcf_period}.")

            mb_offset = BMonthBegin()
            me_offset = BMonthEnd()
            delivery_start = mb_offset.rollback(contract_imm_date)
            delivery_end = me_offset.rollforward(contract_imm_date)

            contract_coupon = 6.0
            if "futures_coupon" in cme_tcf_df.columns:
                contract_coupon = float(cme_tcf_df["futures_coupon"].iloc[0])

            calc_mode = "ust_long" if root in {"WN", "US", "UXY", "TY"} else "ust_short"

            # preserve row-order to keep conversion factors aligned with basket_pricers
            cached = {
                "schema": 1,
                "source": source,
                "as_of": as_of.isoformat(),
                "symbol": symbol,
                "root": root,
                "period": int(tcf_period),
                "delivery": (delivery_start.date().isoformat(), delivery_end.date().isoformat()),
                "cusips": cme_tcf_df["cusip"].tolist(),
                "conversion_factors": [float(x) for x in cme_tcf_df["invoice_conversion_factor"].tolist()],
                "contract_coupon": float(contract_coupon),
                "calc_mode": calc_mode,
                "contract_imm_date": contract_imm_date,
            }

            with self:
                self._threadsafe_basket_cache_put(cache_key, cached)

        # hydrate cached definition -> live cash pricers for this as_of close
        close_2pm = pytz.timezone("America/Chicago").localize(datetime.datetime(as_of.year, as_of.month, as_of.day, 14, 0))

        cusips: List[str] = list(cached["cusips"])
        cash_pricers = usts_mdp.get_data({"cusips": list(set(cusips)), "timestamp": close_2pm})

        basket_pricers: List[Any] = []
        conversion_factors: List[float] = []
        for cusip, cf in zip(cusips, cached["conversion_factors"]):
            pr = cash_pricers.get(cusip)
            if pr is None:
                continue
            basket_pricers.append(pr)
            conversion_factors.append(float(cf))

        if not basket_pricers:
            raise ValueError(f"No deliverable bond pricers resolved for {symbol}.")

        d0, d1 = cached["delivery"]
        return {
            "delivery": (datetime.date.fromisoformat(d0), datetime.date.fromisoformat(d1)),
            "basket_pricers": basket_pricers,
            "conversion_factors": conversion_factors,
            "contract_coupon": float(cached["contract_coupon"]),
            "calc_mode": cached["calc_mode"],
        }

    def get_ctd(
        self, as_of: datetime.date, symbol: str, usts_mdp: Optional[FixedRateBondsMDP] = None, repo: Optional[float] = None, source: Optional[str] = "RL_CME_TCF"
    ):
        # symbol_to_rl_spec = {
        #     "TU": "us_gb_2y",
        #     "3Y": "us_gb_3y",
        #     "FV": "us_gb_5y",
        #     "TY": "us_gb_10y",
        #     "UXY": "us_gb_10y",
        #     "US": "us_gb_30y",
        #     "TWE": "us_gb_30y",
        #     "WN": "us_gb_30y",
        # }

        if source == "RL_CME_TCF":
            import rateslib as rl
            from MDP.FixedRateBonds.reference_data_cache.cme_tcf import read_cme_tcf_with_headers
            from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

            from pandas.tseries.offsets import BMonthEnd, BMonthBegin

            if usts_mdp is None:
                usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")

            contract_imm_date = rl.next_imm(start=datetime.datetime(as_of.year, as_of.month, as_of.day))

            for m_code, month_nums in _CME_QUARTERLY_MONTH_CODES.items():
                if as_of.month in month_nums:
                    full_symbol = f"{symbol}{m_code}{int(as_of.strftime("%y"))}"
                    tcf_period = int(contract_imm_date.strftime("%Y%m"))
                    break

            cme_tcf_df = read_cme_tcf_with_headers(as_of=as_of)
            cme_tcf_df = cme_tcf_df[(cme_tcf_df["ticker"] == symbol) & (cme_tcf_df["period"] == tcf_period)]

            close_2pm = pytz.timezone("America/Chicago").localize(datetime.datetime(as_of.year, as_of.month, as_of.day, 14, 00))
            ustf_pricer = self.get_pricer(request=dict(symbols=[full_symbol], timestamp=close_2pm))
            cash_pricers = usts_mdp.get_data(dict(cusips=cme_tcf_df["cusip"].unique().tolist(), timestamp=close_2pm))

            cme_tcf_df["rl_objs"] = cme_tcf_df["cusip"].map({c: pr.build_pricable() for c, pr in cash_pricers.items()})
            cme_tcf_df["label"] = cme_tcf_df["cusip"].map({c: pr._meta_data["label"] for c, pr in cash_pricers.items()})
            cme_tcf_df["coupon"] = cme_tcf_df["cusip"].map({c: pr._cpn for c, pr in cash_pricers.items()})
            cme_tcf_df["clean_price"] = cme_tcf_df["cusip"].map({c: pr.clean_price() for c, pr in cash_pricers.items()})
            cme_tcf_df["futures_price"] = ustf_pricer[full_symbol]._price
            cme_tcf_df["gross_basis"] = cme_tcf_df["clean_price"] - (cme_tcf_df["futures_price"] * cme_tcf_df["invoice_conversion_factor"])
            cme_tcf_df = cme_tcf_df.dropna()

            me_offset = BMonthEnd()
            mb_offset = BMonthBegin()

            rl_ust_future = rl.BondFuture(
                delivery=(mb_offset.rollback(contract_imm_date), me_offset.rollforward(contract_imm_date)),
                basket=cme_tcf_df["rl_objs"].to_list(),
                # spec=symbol_to_rl_spec[symbol],
                coupon=6.0,
                currency="usd",
                calc_mode="ust_long" if symbol in ["WN", "TWE", "US", "UXY", "TY"] else "ust_short",
            )

            cme_tcf_df["gross_basis_rl"] = rl_ust_future.gross_basis(future_price=ustf_pricer[full_symbol]._price, prices=cme_tcf_df["clean_price"].to_list())

            if repo is None:
                repo = _fetch_fixings(as_of_date=as_of, curve_name="USD-SOFR-1D").sort_index().tail(1).iloc[0] * 100

            cme_tcf_df["bnoc"] = rl_ust_future.net_basis(
                future_price=ustf_pricer[full_symbol]._price,
                prices=cme_tcf_df["clean_price"].to_list(),
                repo_rate=repo,
                settlement=next(iter(cash_pricers.values())).settlement_date(),
                delivery=rl.next_imm(start=datetime.datetime(as_of.year, as_of.month, as_of.day)),
                convention="ActAct",
            )

            cme_tcf_df["irr"] = rl_ust_future.implied_repo(
                future_price=ustf_pricer[full_symbol]._price,
                prices=cme_tcf_df["clean_price"].to_list(),
                settlement=next(iter(cash_pricers.values())).settlement_date(),
            )

            return cme_tcf_df.sort_values(by="irr", ascending=False).reset_index(drop=True)

    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_pricer_cache()
                self._ensure_basket_cache()
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
                        pass  # auto-committed (DiskCache)
                finally:
                    try:
                        self.close_cache()
                    finally:
                        self._cache_ready = False
                        self._basket_cache_ready = False

    def __enter__(self):
        return self.__open__()

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))
