import asyncio
import datetime
import itertools
import os
import random
import re
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import pandas as pd
import pytz
import QuantLib as ql
import rateslib as rl
import requests

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import (
    _imm_cutoff,
    _next_contracts,
    cme_code_effective_date,
    first_business_day_next_month,
)
from MDP.MarketDataProvider import MarketDataProvider
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher  # type: ignore

# --- NEW IMPORTS ---
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFuturePricer
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
# --- UPDATED TYPE ---
InstrumentLike = _STIRFuturePricer


# ----------------------------- time helpers ---------------------------------
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


# ----------------------------- symbol helpers --------------------------------
def _to_barchart_symbol(sym: str) -> str:
    """
    Map internal normalized STIR roots to Barchart roots.
      SR3 -> SQ   (3M SOFR)
      SR1 -> SL   (1M SOFR)
      ZQ  -> ZQ   (Fed Funds)
    """
    s = (sym or "").strip().upper().replace("/", "")
    if s.startswith("SR3"):
        return "SQ" + s[3:]
    if s.startswith("SR1"):
        return "SL" + s[3:]
    return s


def _from_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    if s.startswith("SQ"):
        return "SR3" + s[2:]
    if s.startswith("SL"):
        return "SR1" + s[2:]
    return s


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    # If bare month code like "H26", assume SR3 root
    if re.fullmatch(r"[FGHJKMNQUVXZ]\d{2}", s):
        return f"SR3{s}"

    # Accept internal + common aliases + barchart roots
    m = re.match(r"^(SR[13]|SFR|SER|FF|ZQ|SQ|SL)([FGHJKMNQUVXZ]\d{2})$", s)
    if m:
        root, code = m.groups()
        root = root.replace("SFR", "SR3").replace("SER", "SR1").replace("FF", "ZQ").replace("SQ", "SR3").replace("SL", "SR1")
        return f"{root}{code}"

    return WebullFintechFetcher._normalize_future_symbol(s)


# ----------------------------- SER-FF (SOFR-Feds) spread helpers -------------
# Example: SERFFF26  -> SR1F26 - ZQF26
_SERFF_PAT = re.compile(
    r"^(?P<sofr>(?:SR1|SER|SL))(?P<ff>(?:ZQ|FF))(?P<code>[FGHJKMNQUVXZ]\d{2})$",
    re.IGNORECASE,
)
_FFSER_PAT = re.compile(
    r"^(?P<ff>(?:ZQ|FF))(?P<sofr>(?:SR1|SER|SL))(?P<code>[FGHJKMNQUVXZ]\d{2})$",
    re.IGNORECASE,
)


def _serff_spread_legs(alias: str) -> Optional[Tuple[str, str]]:
    """
    Return (sr1_leg, zq_leg) for SOFR-Feds spread aliases.
    Accepts either:
      - SERFFF26 / SR1ZQF26 / SLZQF26
      - FFSERF26 / ZQSR1F26 (reverse-ordered)
    """
    a = (alias or "").strip().upper().replace("/", "")
    m = _SERFF_PAT.match(a)
    if not m:
        m = _FFSER_PAT.match(a)
    if not m:
        return None
    code = m.group("code").upper()
    return (f"SR1{code}", f"ZQ{code}")


def _is_serff_spread_alias(alias: str) -> bool:
    return _serff_spread_legs(alias) is not None


# ----------------------------- alias helpers ---------------------------------
def _package_contracts(color: str, as_of: datetime.date) -> List[str]:
    color_order = ["whites", "reds", "greens", "blues", "golds", "silvers", "platinums"]
    offset = color_order.index(color) * 4
    count = offset + 4
    contracts = _next_contracts(
        as_of,
        prefix="SR3",
        count=count,
        valid_months=[3, 6, 9, 12],
        cutoff_fn=_imm_cutoff,
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
            # SOFR-Feds spreads: SERFFF26 -> [SR1F26, ZQF26]
            legs = _serff_spread_legs(alias)
            if legs is not None:
                aliases[alias] = [legs[0], legs[1]]
                continue

            # Package colors
            if lower in color_set:
                aliases[alias] = _package_contracts(lower, as_of)
                continue

            # X-Year Bundles (e.g., "2-Year", "5-year")
            # Matches strings like "2-Year", "10-year", "5Y", "2 yr"
            m_bundle = re.match(r"^(?P<years>\d+)[-\s]?(?:year|yr|y)s?$", lower)
            if m_bundle:
                years = int(m_bundle.group("years"))
                count = years * 4

                contracts = _next_contracts(as_of, prefix="SR3", count=count, valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff)
                aliases[alias] = contracts
                continue

            # Constant maturity rank: CM1, CM2... Optional root prefix.
            m_cm = re.match(r"^(?P<prefix>(sr[13]|sfr|ser|ff|zq|sq|sl)?)cm(?P<rank>\d+)$", lower)
            if m_cm:
                rank = int(m_cm.group("rank"))
                prefix = (m_cm.group("prefix") or "SR3").upper()
                root = prefix.replace("SFR", "SR3").replace("SER", "SR1").replace("FF", "ZQ").replace("SQ", "SR3").replace("SL", "SR1")
                valid_months = [3, 6, 9, 12] if root.startswith("SR3") else list(range(1, 13))
                cutoff = _imm_cutoff if root.startswith("SR3") else None
                contracts = _next_contracts(as_of, prefix=root, count=max(rank, 1), valid_months=valid_months, cutoff_fn=cutoff)
                aliases[alias] = [contracts[rank - 1]]
                continue

            norm = _normalize_symbol(alias)
            if norm:
                aliases[alias] = [norm]
                continue

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


# ----------------------------- instrument builder ----------------------------
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


# ----------------------------- barchart proxy plumbing -----------------------
def _build_socks5h(host: str) -> dict:
    user = os.getenv("NORDVPN_USER", "")
    pwd = os.getenv("NORDVPN_PASS", "")
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


# ================================ MDP ========================================
class STIRFutureMDP(MarketDataProvider[InstrumentLike], ZODBCacheMixin):
    _STIR_PRICER_CACHE = "_stir_pricer_cache"

    # process-wide state so multiple instances reuse POP + fetcher/session
    _BARCHART_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "WEBULL_STIRF-RL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        ZODBCacheMixin.__init__(self)

        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

        # ---- proxy rotation config ----
        default_hosts = [
            "atlanta.us.socks.nordhold.net",
            "chicago.us.socks.nordhold.net",
            "dallas.us.socks.nordhold.net",
            "los-angeles.us.socks.nordhold.net",
            "new-york.us.socks.nordhold.net",
            "phoenix.us.socks.nordhold.net",
            "san-francisco.us.socks.nordhold.net",
            "us.socks.nordhold.net",
            None,  # allow direct
        ]
        self._barchart_proxy_hosts: List[Optional[str]] = list(kwargs.get("barchart_proxy_hosts", default_hosts))
        random.shuffle(self._barchart_proxy_hosts)
        self._barchart_proxy_ttl: int = int(kwargs.get("barchart_proxy_ttl", 60))

        if not STIRFutureMDP._BARCHART_STATE:
            STIRFutureMDP._BARCHART_STATE = {
                "proxies": None,  # dict | None
                "host": None,  # str | None
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
                "fetcher": None,  # BarchartFetcher
                "cycler": itertools.cycle(self._barchart_proxy_hosts),
                "lock": threading.RLock(),
            }

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

    # ----------------------------- pricer build ------------------------------
    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any]) -> RLSTIRFuturePricer:
        """
        Builds a RLSTIRFuturePricer from cached dictionary arguments.
        Resolves effective/maturity dates using the symbol helper.
        """
        sym = args["symbol"]
        price = float(args["price"])
        timestamp_str = args["timestamp"]

        # Parse timestamp from string (ISO) to date for the pricer
        if isinstance(timestamp_str, str):
            try:
                ref_date = datetime.date.fromisoformat(timestamp_str.split("T")[0])
            except ValueError:
                # Fallback for pandas/other string formats
                ref_date = pd.Timestamp(timestamp_str).date()
        elif isinstance(timestamp_str, (datetime.date, datetime.datetime)):
            ref_date = _as_date(timestamp_str)
        else:
            ref_date = datetime.date.today()

        # Use helper to get rateslib object just to extract correct dates/spec
        # This avoids duplicating the logic for IMM vs ZQ dates
        _, temp_stir = _stir_future_from_symbol(sym, price)

        print(temp_stir.__dict__["kwargs"]["effective"])

        return RLSTIRFuturePricer(
            rl_stirf_id=sym,
            reference_date=ref_date,
            effective_date=temp_stir.__dict__["kwargs"]["effective"].date(),
            maturity_date=temp_stir.__dict__["kwargs"]["termination"].date(),
            price=price,
            rate=100.0 - price,
            contracts=1,
            notional=1_000_000,
            meta_data=args,
        )

    # ----------------------------- webull fetch ------------------------------
    def _fetch_webull_intraday(
        self,
        tickers: List[str],
        ts_dt: datetime.datetime,
        *,
        show_tqdm: bool,
    ) -> pd.DataFrame:
        wb = WebullFintechFetcher(debug_verbose=False, error_verbose=True)

        # Webull convention: SR3Z25 -> SR3Z5 (your existing logic)
        tickers_adj = [t[:-2] + t[-1] for t in tickers]

        df = wb.intraday_by_tickers(
            tickers=tickers_adj,
            start=ts_dt.astimezone(pytz.timezone("America/Chicago")),
            end=ts_dt.astimezone(pytz.timezone("America/Chicago")),
            show_tqdm=show_tqdm,
        )

        def ql_to_datetime_new(d):
            return datetime.datetime.fromordinal(d.serialNumber() + 693594)

        def datetime_to_ql(d):
            return ql.Date(d.day, d.month, d.year)

        # Recover full YY based on IMM year inferred from ts_dt
        new_cols = []
        for c in df.columns:
            first_part = c[:-1]
            imm_ql = ql.IMM.date(c[3:], datetime_to_ql(ts_dt))
            year = ql_to_datetime_new(imm_ql).year
            new_cols.append(first_part + str(year)[2:])  # SR3Z5 -> SR3Z25

        df.columns = new_cols
        return df

    # ----------------------------- barchart proxy helpers --------------------
    def _get_cached_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = STIRFutureMDP._BARCHART_STATE
        if time.time() - float(S["chosen_at"]) < float(S["ttl"]):
            return S["proxies"], S["host"]
        return None, None

    def _choose_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = STIRFutureMDP._BARCHART_STATE
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
        """
        Sticky proxy (TTL) + fetcher reuse + token seeding.
        Rotates once on token failure.
        """
        S = STIRFutureMDP._BARCHART_STATE
        with S["lock"]:
            proxies, host = self._get_cached_barchart_proxy()
            if proxies is None and host is None:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                S["fetcher"] = None

            bcf = S["fetcher"]
            if bcf is None:
                bcf = BarchartFetcher(proxies=proxies, debug_verbose=False, error_verbose=True)
                S["fetcher"] = bcf

            try:
                with _ProxyGuard(proxies):
                    bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = BarchartFetcher(proxies=proxies, debug_verbose=False, error_verbose=True)
                S["fetcher"] = bcf
                with _ProxyGuard(proxies):
                    bcf._fetch_session_tokens(dummy_symbol="BTC")

            return bcf

    # ----------------------------- barchart fetch ----------------------------
    def _fetch_barchart_timeseries(
        self,
        tickers: List[str],
        ts_dt: datetime.datetime,
        *,
        show_tqdm: bool,
        interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]],
        window_minutes: int = 2,
    ) -> pd.DataFrame:
        chi = pytz.timezone("America/Chicago")
        ts_chi = ts_dt.astimezone(chi)

        if interval is None:
            start = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 0, 0))
            end = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 23, 59))
        else:
            start = ts_chi - datetime.timedelta(minutes=window_minutes)
            end = ts_chi + datetime.timedelta(minutes=window_minutes)

        barchart_syms = [_to_barchart_symbol(_normalize_symbol(t) or t) for t in tickers]
        bcf = self._get_barchart_fetcher()

        def _call():
            try:
                return bcf.barchart_timeseries_api(
                    barchart_symbols=barchart_syms,
                    start_date=start,
                    end_date=end,
                    interval=interval,
                    one_df=True,
                    show_tqdm=show_tqdm,
                    max_concurrent_tasks=min(len(barchart_syms), 36) + 1,
                    max_keepalive_connections=max(36, min(len(barchart_syms), 36)) + 1,
                    # max_concurrent_tasks=1,
                )
            except TypeError:
                return bcf.barchart_timeseries_api(
                    barchart_symbols=barchart_syms,
                    start_date=start,
                    end_date=end,
                    interval=interval,
                    one_df=True,
                    show_tqdm=show_tqdm,
                )

        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False

        if not running:
            df = _call()
        else:
            holder: Dict[str, Any] = {"df": None, "err": None}

            def _worker():
                try:
                    holder["df"] = _call()
                except Exception as e:
                    holder["err"] = e

            th = threading.Thread(target=_worker, daemon=True)
            th.start()
            th.join()
            if holder["err"] is not None:
                raise holder["err"]
            df = holder["df"]

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()
        df.columns = [_from_barchart_symbol(c) for c in df.columns]
        return df

    # ----------------------------- core fetch --------------------------------
    def _get_data_for_timestamp(
        self,
        symbols: List[str],
        timestamp: DateLike,
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
    ) -> Dict[str, List[InstrumentLike]]:
        ts_dt = _as_datetime(timestamp)
        alias_map = _resolve_aliases_bulk(symbols, timestamp)
        if not alias_map:
            raise ValueError("No valid symbols resolved from request.")

        src = self.source.upper()
        if src not in {"WEBULL_STIRF-RL", "BARCHART_STIRF-RL"}:
            raise NotImplementedError(f"Unsupported source {self.source}")

        want_eod = isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime)

        self._ensure_pricer_cache()

        result: Dict[str, List[InstrumentLike]] = {}

        # For SER-FF spreads, accumulate legs here
        spread_legs: Dict[str, Dict[str, InstrumentLike]] = defaultdict(dict)

        # ---------- pass 1: cache hit ----------
        to_fetch: "OrderedDict[str, List[str]]" = OrderedDict()
        ts_iso = ts_dt.isoformat()

        for alias, tickers in alias_map.items():
            is_spread = _is_serff_spread_alias(alias)

            if not is_spread:
                insts: List[InstrumentLike] = []
                for t in tickers:
                    cache_key = f"{ts_iso}-{t}-{src}"
                    cached = None if force_refresh else self._threadsafe_cache_get(cache_key)
                    if cached is not None:
                        insts.append(self._build_pricer_from_args(cached))
                    else:
                        to_fetch.setdefault(alias, []).append(t)
                if insts:
                    result[alias] = insts
                continue

            # spread alias: cache legs individually, do not emit legs directly
            legs = _serff_spread_legs(alias)
            if legs is None:
                # defensive fallback
                to_fetch.setdefault(alias, []).extend(tickers)
                continue

            sr1_leg, zq_leg = legs
            for t in [sr1_leg, zq_leg]:
                cache_key = f"{ts_iso}-{t}-{src}"
                cached = None if force_refresh else self._threadsafe_cache_get(cache_key)
                if cached is not None:
                    spread_legs[alias][t] = self._build_pricer_from_args(cached)
                else:
                    to_fetch.setdefault(alias, []).append(t)

            if len(spread_legs[alias]) == 2:
                # Spreads are now returned as a list of two Pricers [SR1, ZQ]
                result[alias] = [spread_legs[alias][sr1_leg], spread_legs[alias][zq_leg]]

        # ---------- fetch missing ----------
        all_missing = sorted({t for lst in to_fetch.values() for t in lst})
        price_df = pd.DataFrame()

        if all_missing:
            if src == "WEBULL_STIRF-RL":
                price_df = self._fetch_webull_intraday(all_missing, ts_dt, show_tqdm=show_tqdm)
            else:
                interval = None if want_eod else 1
                price_df = self._fetch_barchart_timeseries(all_missing, ts_dt, show_tqdm=show_tqdm, interval=interval)

            if price_df.empty:
                raise RuntimeError(f"{src} returned no data for requested STIR futures.")

            # Persist all slices for future reuse
            for t in price_df.columns:
                series = price_df[t].dropna()
                for curr_ts, px in series.items():
                    args = {
                        "symbol": t,
                        "price": float(px),
                        "timestamp": curr_ts.isoformat() if hasattr(curr_ts, "isoformat") else str(curr_ts),
                        "schema": 1,
                    }
                    cache_key = f"{curr_ts.isoformat()}-{t}-{src}"
                    self._threadsafe_cache_put(cache_key, args)

        # ---------- pass 2: build outputs from cache / fetched ----------
        for alias, tickers in to_fetch.items():
            is_spread = _is_serff_spread_alias(alias)

            if not is_spread:
                insts: List[InstrumentLike] = list(result.get(alias, []))  # type: ignore[assignment]
                for t in tickers:
                    cache_key = f"{ts_iso}-{t}-{src}"
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
                            "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                            "schema": 1,
                        }
                        cache_key2 = f"{idx.isoformat()}-{t}-{src}"
                        self._threadsafe_cache_put(cache_key2, args)
                        cached = args

                    if cached is None:
                        continue

                    insts.append(self._build_pricer_from_args(cached))

                if insts:
                    result[alias] = insts
                continue

            # spread alias: fill missing legs then emit list of Pricers
            legs = _serff_spread_legs(alias)
            if legs is None:
                continue
            sr1_leg, zq_leg = legs

            for t in [sr1_leg, zq_leg]:
                if t in spread_legs[alias]:
                    continue

                cache_key = f"{ts_iso}-{t}-{src}"
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
                        "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                        "schema": 1,
                    }
                    cache_key2 = f"{idx.isoformat()}-{t}-{src}"
                    self._threadsafe_cache_put(cache_key2, args)
                    cached = args

                if cached is None:
                    continue

                spread_legs[alias][t] = self._build_pricer_from_args(cached)

            if len(spread_legs[alias]) == 2:
                result[alias] = [spread_legs[alias][sr1_leg], spread_legs[alias][zq_leg]]

        return result

    # ----------------------------- public API --------------------------------
    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[InstrumentLike]]:
        return self.get_data(request)

    def get_data(self, request: Dict[str, Any]) -> Dict[str, List[InstrumentLike]]:
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
    ) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        jobs: List[Tuple[DateLike, List[str]]] = []
        base_symbols = _clean_symbols(symbols)
        for ts in timestamps:
            jobs.append((ts, base_symbols))

        results: List[Tuple[DateLike, Dict[str, List[InstrumentLike]]]] = []

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

            out: Dict[DateLike, Dict[str, List[InstrumentLike]]] = defaultdict(dict)
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
