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
from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import (
    _imm_cutoff,
    _next_contracts,
    cme_code_effective_date,
    first_business_day_next_month,
    get_quotes,
)
from MDP.MarketDataProvider import MarketDataProvider
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
InstrumentLike = _STIRFutureGenericPricer

_MONTHLY_STIR_ROOTS = {"SR1", "ZQ", "IJ", "JU"}
_IMM_STIR_ROOTS = {"SR3", "RA", "EB", "RG", "IM", "TV", "J8", "T0", "IT", "J2"}
_ROOT_ALIAS_MAP = {
    "SFR": "SR3",
    "SER": "SR1",
    "FF": "ZQ",
    "SQ": "SR3",
    "SL": "SR1",
}
_ROOT_TO_CURVE_MAP = {
    "SR1": "USD-SOFR-1D",
    "SR3": "USD-SOFR-1D",
    "ZQ": "USD-FEDFUNDS",
    "RA": "EUR-ESTR",
    "EB": "EUR-ESTR",
    "IJ": "EUR-ESTR",
    "RG": "CAD-CORRA",
    "IM": "EUR-EURIBOR-3M",
    "TV": "EUR-EURIBOR-3M",
    "J8": "GBP-SONIA",
    "JU": "GBP-SONIA",
    "T0": "JPY-TONA",
    "IT": "JPY-TONA",
    "J2": "CHF-SARON",
}
_ROOT_TO_STIR_SPEC = {
    "RA": "eur_stir",
    "EB": "eur_stir",
    "IJ": "eur_stir1",
    "IM": "eur_stir3",
    "TV": "eur_stir3",
    "J8": "gbp_stir",
    "JU": "gbp_stir",
    "RG": "cad_irs",
    "T0": "jpy_irs",
    "IT": "jpy_irs",
    "J2": "chf_irs",
}


# ----------------------------- time helpers ---------------------------------
def _as_datetime(ts: DateLike) -> datetime.datetime:
    if ts == "live":
        return datetime.datetime.now(pytz.UTC)
    if type(ts) == datetime.datetime:
        if ts.tzinfo is None:
            return pytz.timezone("America/New_York").localize(ts)
        return ts

    # NY close 5pm
    if type(ts) == datetime.date:
        # return datetime.datetime(ts.year, ts.month, ts.day)
        return pytz.timezone("America/New_York").localize(datetime.datetime.combine(ts, datetime.time(hour=17, minute=00)))
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
    if s.startswith("RA") or s.startswith("EB"):
        return s
    return s


def _from_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    if s.startswith("SQ"):
        return "SR3" + s[2:]
    if s.startswith("SL"):
        return "SR1" + s[2:]
    if s.startswith("RA") or s.startswith("EB"):
        return s
    return s


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    # If bare month code like "H26", assume SR3 root
    if re.fullmatch(r"[FGHJKMNQUVXZ]\d{2}", s):
        return f"SR3{s}"

    # Accept internal + common aliases + barchart roots
    m = re.match(r"^(SR[13]|SFR|SER|FF|ZQ|SQ|SL|RA|EB|IJ|RG|IM|TV|J8|JU|T0|IT|J2)([FGHJKMNQUVXZ]\d{2})$", s)
    if m:
        root, code = m.groups()
        root = _ROOT_ALIAS_MAP.get(root, root)
        return f"{root}{code}"

    return WebullFintechFetcher._normalize_future_symbol(s)


def _to_tos_symbol(sym: str) -> str:
    norm = _normalize_symbol(sym) or sym
    m = re.match(r"^(?P<root>SR[13]|ZQ)(?P<code>[FGHJKMNQUVXZ]\d{2})$", norm)
    if not m:
        return sym
    root = m.group("root")
    code = m.group("code")
    return f"/{root}{code}"


def _from_tos_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    if s.startswith("/"):
        s = s[1:]
    return s


def _should_use_live_quotes(timestamp: DateLike) -> bool:
    if timestamp == "live":
        return True
    if isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime):
        return timestamp == datetime.date.today()
    if isinstance(timestamp, datetime.datetime):
        ts_dt = _as_datetime(timestamp)
        now = datetime.datetime.now(pytz.UTC)
        return abs((ts_dt.astimezone(pytz.UTC) - now).total_seconds()) <= 15 * 60
    return False


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
            m_cm = re.match(r"^(?P<prefix>(sr[13]|sfr|ser|ff|zq|sq|sl|ra|eb|ij|rg|im|tv|j8|ju|t0|it|j2)?)cm(?P<rank>\d+)$", lower)
            if m_cm:
                rank = int(m_cm.group("rank"))
                prefix = (m_cm.group("prefix") or "SR3").upper()
                root = _ROOT_ALIAS_MAP.get(prefix, prefix)
                use_imm = root in _IMM_STIR_ROOTS
                valid_months = [3, 6, 9, 12] if use_imm else list(range(1, 13))
                cutoff = _imm_cutoff if use_imm else None
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

    if root in _MONTHLY_STIR_ROOTS:
        effective = cme_code_effective_date(code)
        termination = first_business_day_next_month(pd.Timestamp(effective))
        stir = rl.STIRFuture(
            effective=effective,
            termination=termination,
            spec=_ROOT_TO_STIR_SPEC.get(root, "usd_stir1"),
            roll="som",
            price=price,
        )
        return norm, stir

    effective = rl.scheduling.get_imm(code=code)
    termination = rl.scheduling.next_imm(effective)
    spec = _ROOT_TO_STIR_SPEC.get(root, "usd_stir")
    stir = rl.STIRFuture(
        effective=effective,
        termination=termination,
        spec=spec,
        price=price,
    )
    return norm, stir


def _curve_from_symbol(sym: str) -> Optional[str]:
    norm = _normalize_symbol(sym)
    if not norm:
        return None
    m = re.match(r"^(?P<root>SR[13]|ZQ|RA|EB|IJ|RG|IM|TV|J8|JU|T0|IT|J2)(?P<code>[FGHJKMNQUVXZ]\d{2})$", norm)
    if not m:
        return None
    root = m.group("root")
    return _ROOT_TO_CURVE_MAP.get(root)


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


# ================================ MDP ========================================
class STIRFutureMDP(MarketDataProvider[InstrumentLike], ZODBCacheMixin):
    _STIR_PRICER_CACHE = "_stir_pricer_cache"

    # process-wide state so multiple instances reuse POP + fetcher/session
    _BARCHART_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "WEBULL_STIRF-RL", force_refresh_fixings: Optional[bool] = False, **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        ZODBCacheMixin.__init__(self)

        self.force_refresh_fixings = force_refresh_fixings
        self.cache_full_intraday_fetch = bool(kwargs.get("cache_full_intraday_fetch", False))
        self._schwab_app_key = kwargs.get("schwab_app_key") or os.getenv("SCHWABDEV_APP_KEY") or os.getenv("SCHWAB_APP_KEY") or "zm3GYiQREbtrpBHACURcNzFJIObUq2aX"
        self._schwab_app_secret = kwargs.get("schwab_app_secret") or os.getenv("SCHWABDEV_APP_SECRET") or os.getenv("SCHWAB_APP_SECRET") or "SznUHXvKPZUnmxG9"
        self._schwab_scope = kwargs.get("schwab_scope", "pystonk")
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
    def _is_sofr_symbol(self, sym: str) -> bool:
        norm = _normalize_symbol(sym) or (sym or "").strip().upper().replace("/", "")
        return norm.startswith("SR1") or norm.startswith("SR3")

    def _reference_date_from_timestamp(self, ts: Any) -> datetime.date:
        if isinstance(ts, str):
            t = ts.strip()
            if t.lower() == "live":
                return datetime.date.today()
            try:
                return datetime.date.fromisoformat(t.split("T")[0])
            except ValueError:
                return pd.Timestamp(t).date()
        if isinstance(ts, datetime.datetime):
            return ts.date()
        if isinstance(ts, datetime.date):
            return ts
        return datetime.date.today()

    def _build_pricer_from_args(
        self,
        args: Dict[str, Any],
        fixings_memo: Optional[Dict[Tuple[str, datetime.date], pd.Series]] = None,
    ) -> RLSTIRFuturePricer:
        """
        Builds a RLSTIRFuturePricer from cached dictionary arguments.
        Resolves effective/maturity dates using the symbol helper.
        """
        sym = args["symbol"]
        price = float(args["price"])
        ref_date = self._reference_date_from_timestamp(args.get("timestamp"))
        curve_name = _curve_from_symbol(sym)

        # Use helper to get rateslib object just to extract correct dates/spec
        # This avoids duplicating the logic for IMM vs ZQ dates
        _, temp_stir = _stir_future_from_symbol(sym, price)

        meta = dict(args)
        if curve_name == "USD-SOFR-1D":
            memo = fixings_memo if fixings_memo is not None else {}
            memo_key = (curve_name, ref_date)
            # try:
            sofr_fixings = memo.get(memo_key)
            if sofr_fixings is None:
                sofr_fixings = _fetch_fixings(
                    as_of_date=ref_date,
                    curve_name=curve_name,
                    force_refresh=self.force_refresh_fixings,
                ).sort_index()
                sofr_fixings = sofr_fixings[sofr_fixings.index.date <= ref_date] * 100
                memo[memo_key] = sofr_fixings
            meta["fixings"] = sofr_fixings
            # except Exception:
            #     pass

        return RLSTIRFuturePricer(
            rl_stirf_id=sym,
            reference_date=ref_date,
            effective_date=temp_stir.__dict__["kwargs"]["effective"].date(),
            maturity_date=temp_stir.__dict__["kwargs"]["termination"].date(),
            curve=curve_name,
            price=price,
            rate=100.0 - price,
            contracts=1,
            notional=1_000_000,
            meta_data=meta,
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
        full_day_intraday: bool = False,
    ) -> pd.DataFrame:
        chi = pytz.timezone("America/Chicago")
        ts_chi = ts_dt.astimezone(chi)

        def _cme_session_bounds(anchor: datetime.datetime) -> Tuple[datetime.datetime, datetime.datetime]:
            # CME rates futures trade ~23h/day with a maintenance break around 16:00-17:00 CT.
            session_open = anchor.replace(hour=17, minute=0, second=0, microsecond=0)
            if anchor < session_open:
                session_open = session_open - datetime.timedelta(days=1)
            start_local = session_open
            end_local = session_open + datetime.timedelta(hours=23)
            return start_local, end_local

        if interval is None:
            start = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 0, 1))
            end = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 23, 59))
        elif full_day_intraday:
            start, end = _cme_session_bounds(ts_chi)
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
                    interval=1,
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
        if full_day_intraday and interval is not None and int(interval) == 1:
            # In full-session mode we want cache keys for every minute, not only
            # minutes where Barchart returned a print.
            if isinstance(df.index, pd.DatetimeIndex):
                if df.index.tz is None:
                    df.index = df.index.tz_localize(chi)
                full_index = pd.date_range(start=start, end=end, freq="1min", tz=df.index.tz)
                if len(full_index):
                    df = df.sort_index()
                    df = df.reindex(df.index.union(full_index)).sort_index().ffill().bfill()
                    df = df.loc[full_index]
        return df

    def _fetch_tos_live_quotes(self, tickers: List[str], ts_dt: datetime.datetime) -> pd.DataFrame:
        tos_map = {t: _to_tos_symbol(t) for t in tickers}
        quote_kwargs: Dict[str, Any] = {"symbols": list(tos_map.values())}
        if self._schwab_app_key and self._schwab_app_secret:
            quote_kwargs["app_key"] = self._schwab_app_key
            quote_kwargs["app_secret"] = self._schwab_app_secret
            quote_kwargs["scope"] = self._schwab_scope

        quotes = get_quotes(**quote_kwargs)
        if not quotes:
            return pd.DataFrame()

        rows: Dict[str, Tuple[datetime.datetime, float]] = {}
        for orig_sym, tos_sym in tos_map.items():
            q = quotes.get(tos_sym)
            if not q:
                q = quotes.get(_from_tos_symbol(tos_sym))
            if not q:
                continue
            price = q.get("last")
            if price is None:
                price = q.get("mid")
            if price is None:
                price = q.get("mark")
            if price is None:
                price = q.get("bid")
            if price is None:
                price = q.get("ask")
            if price is None:
                continue

            quote_time = q.get("quoteTime")
            if quote_time is None:
                quote_ts = ts_dt
            else:
                quote_ts = pd.to_datetime(quote_time, unit="ms", utc=True).tz_convert(ts_dt.tzinfo)
            rows[orig_sym] = (quote_ts, float(price))

        if not rows:
            return pd.DataFrame()

        latest_ts = max(ts for ts, _ in rows.values())
        df = pd.DataFrame({sym: [px] for sym, (_, px) in rows.items()}, index=[latest_ts])
        df.columns = [_from_tos_symbol(c) for c in df.columns]
        return df

    # ----------------------------- core fetch --------------------------------
    def _get_data_for_timestamp(
        self,
        symbols: List[str],
        timestamp: DateLike,
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        cache_full_intraday_fetch: bool = False,
    ) -> Dict[str, List[InstrumentLike]]:
        ts_dt = _as_datetime(timestamp)
        alias_map = _resolve_aliases_bulk(symbols, timestamp)
        if not alias_map:
            raise ValueError("No valid symbols resolved from request.")

        src = self.source.upper()
        live_quote_sources = {"BARCHART_TOS_LIVE_STIRF-RL", "SCHWAB_APP_STIRF-RL"}
        if src not in {"WEBULL_STIRF-RL", "BARCHART_STIRF-RL", *live_quote_sources}:
            raise NotImplementedError(f"Unsupported source {self.source}")

        want_eod = isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime)
        use_live = src in live_quote_sources and _should_use_live_quotes(timestamp)
        read_cache = not force_refresh and not use_live
        use_barchart_intraday = src != "WEBULL_STIRF-RL" and not want_eod and not use_live
        floor_req_to_minute = cache_full_intraday_fetch and use_barchart_intraday

        self._ensure_pricer_cache()

        result: Dict[str, List[InstrumentLike]] = {}
        fixings_memo: Dict[Tuple[str, datetime.date], pd.Series] = {}

        # For SER-FF spreads, accumulate legs here
        spread_legs: Dict[str, Dict[str, InstrumentLike]] = defaultdict(dict)

        def _cache_ts_iso(ts_like: Any, *, floor_minute: bool) -> str:
            ts_obj = pd.Timestamp(ts_like)
            # Normalize Barchart intraday cache keys to UTC so equivalent instants
            # from different tz representations map to the same key.
            if use_barchart_intraday and ts_obj.tzinfo is not None:
                ts_obj = ts_obj.tz_convert(pytz.UTC)
            if floor_minute:
                ts_obj = ts_obj.floor("min")
            return ts_obj.isoformat()

        # ---------- pass 1: cache hit ----------
        to_fetch: "OrderedDict[str, List[str]]" = OrderedDict()
        ts_exact_local_iso = pd.Timestamp(ts_dt).isoformat()
        ts_floor_local_iso = pd.Timestamp(ts_dt).floor("min").isoformat()
        req_ts_key_candidates: List[str] = []

        def _push_key(k: str) -> None:
            if k and k not in req_ts_key_candidates:
                req_ts_key_candidates.append(k)

        _push_key(_cache_ts_iso(ts_dt, floor_minute=floor_req_to_minute))
        if use_barchart_intraday:
            # Always probe canonical UTC cache keys so a cache primed with
            # cache_full_intraday_fetch=True can be reused even if a later call
            # omits the flag.
            _push_key(_cache_ts_iso(ts_dt, floor_minute=True))
            _push_key(_cache_ts_iso(ts_dt, floor_minute=False))
        # Legacy/local key variants for backward compatibility.
        _push_key(ts_exact_local_iso)
        _push_key(ts_floor_local_iso)

        def _get_cached_request_key(ticker: str):
            if not read_cache:
                return None
            for ts_key in req_ts_key_candidates:
                cached_local = self._threadsafe_cache_get(f"{ts_key}-{ticker}-{src}")
                if cached_local is not None:
                    return cached_local
            return None

        def _align_lookup_ts(index: pd.Index, req_ts: datetime.datetime) -> datetime.datetime:
            if not isinstance(index, pd.DatetimeIndex):
                return req_ts

            ts_obj = pd.Timestamp(req_ts)
            if index.tz is None:
                if ts_obj.tzinfo is not None:
                    ts_obj = ts_obj.tz_localize(None)
            else:
                if ts_obj.tzinfo is None:
                    ts_obj = ts_obj.tz_localize(index.tz)
                else:
                    ts_obj = ts_obj.tz_convert(index.tz)
            return ts_obj.to_pydatetime()

        for alias, tickers in alias_map.items():
            is_spread = _is_serff_spread_alias(alias)

            if not is_spread:
                insts: List[InstrumentLike] = []
                for t in tickers:
                    cached = _get_cached_request_key(t)
                    if cached is not None:
                        insts.append(self._build_pricer_from_args(cached, fixings_memo=fixings_memo))
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
                cached = _get_cached_request_key(t)
                if cached is not None:
                    spread_legs[alias][t] = self._build_pricer_from_args(cached, fixings_memo=fixings_memo)
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
            elif use_live:
                price_df = self._fetch_tos_live_quotes(all_missing, ts_dt)
            else:
                interval = None if want_eod else 1
                price_df = self._fetch_barchart_timeseries(
                    all_missing,
                    ts_dt,
                    show_tqdm=show_tqdm,
                    interval=interval,
                    full_day_intraday=floor_req_to_minute,
                )

            price_df = price_df.ffill().bfill()
            if price_df.empty:
                raise RuntimeError(f"{src} returned no data for requested STIR futures.")

            # Persist all slices for future reuse
            if not use_live:
                for t in price_df.columns:
                    series = price_df[t].dropna()
                    for curr_ts, px in series.items():
                        curr_ts_iso = _cache_ts_iso(curr_ts, floor_minute=floor_req_to_minute)
                        args = {
                            "symbol": t,
                            "price": float(px),
                            "timestamp": curr_ts_iso,
                            "schema": 1,
                        }
                        self._threadsafe_cache_put(f"{curr_ts_iso}-{t}-{src}", args)

        # ---------- pass 2: build outputs from cache / fetched ----------
        for alias, tickers in to_fetch.items():
            is_spread = _is_serff_spread_alias(alias)

            if not is_spread:
                insts: List[InstrumentLike] = list(result.get(alias, []))  # type: ignore[assignment]
                for t in tickers:
                    cached = _get_cached_request_key(t)

                    if cached is None and not price_df.empty and t in price_df:
                        series = price_df[t].dropna()
                        if series.empty:
                            continue

                        lookup_ts = _align_lookup_ts(series.index, ts_dt)
                        pos = series.index.get_indexer([lookup_ts], method="nearest")
                        idx = series.index[pos[0]] if pos.size and pos[0] != -1 else series.index[-1]

                        args = {
                            "symbol": t,
                            "price": float(series.loc[idx]),
                            "timestamp": _cache_ts_iso(idx, floor_minute=floor_req_to_minute),
                            "schema": 1,
                        }

                        idx_iso = _cache_ts_iso(idx, floor_minute=floor_req_to_minute)
                        if not use_live:
                            self._threadsafe_cache_put(f"{idx_iso}-{t}-{src}", args)
                            for req_ts_key in req_ts_key_candidates:
                                self._threadsafe_cache_put(f"{req_ts_key}-{t}-{src}", args)

                        cached = args

                    if cached is None:
                        continue

                    insts.append(self._build_pricer_from_args(cached, fixings_memo=fixings_memo))

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

                cached = _get_cached_request_key(t)

                if cached is None and not price_df.empty and t in price_df:
                    series = price_df[t].dropna()
                    if series.empty:
                        continue
                    lookup_ts = _align_lookup_ts(series.index, ts_dt)
                    pos = series.index.get_indexer([lookup_ts], method="nearest")
                    idx = series.index[pos[0]] if pos.size and pos[0] != -1 else series.index[-1]
                    args = {
                        "symbol": t,
                        "price": float(series.loc[idx]),
                        "timestamp": _cache_ts_iso(idx, floor_minute=floor_req_to_minute),
                        "schema": 1,
                    }
                    if not use_live:
                        idx_iso = _cache_ts_iso(idx, floor_minute=floor_req_to_minute)
                        self._threadsafe_cache_put(f"{idx_iso}-{t}-{src}", args)
                        for req_ts_key in req_ts_key_candidates:
                            self._threadsafe_cache_put(f"{req_ts_key}-{t}-{src}", args)
                    cached = args

                if cached is None:
                    continue

                spread_legs[alias][t] = self._build_pricer_from_args(cached, fixings_memo=fixings_memo)

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
        cache_full_intraday_fetch = bool(request.get("cache_full_intraday_fetch", self.cache_full_intraday_fetch))

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        with self:
            return self._get_data_for_timestamp(
                symbols,
                timestamp,
                show_tqdm=show_tqdm,
                force_refresh=force_refresh,
                cache_full_intraday_fetch=cache_full_intraday_fetch,
            )

    def get_bulk_pricer(self, request: Dict[str, Any]) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        return self.get_bulk_data(request)

    def get_bulk_data(self, request: Dict[str, Any]) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamps_raw = request.get("timestamps", None)
        show_tqdm = bool(request.get("show_tqdm", False))
        force_refresh = bool(request.get("force_refresh", False))
        max_workers = int(request.get("max_workers", 8))
        cache_full_intraday_fetch = bool(request.get("cache_full_intraday_fetch", self.cache_full_intraday_fetch))

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")
        if timestamps_raw is None:
            raise ValueError("Request must include 'timestamps'.")

        if isinstance(timestamps_raw, (str, datetime.date, datetime.datetime)):
            timestamps: List[DateLike] = [timestamps_raw]
        else:
            timestamps = list(timestamps_raw)

        if not timestamps:
            raise ValueError("Request 'timestamps' is empty.")

        with self:
            return self.bulk_get_data(
                timestamps=timestamps,
                symbols=symbols,
                show_tqdm=show_tqdm,
                force_refresh=force_refresh,
                max_workers=max_workers,
                cache_full_intraday_fetch=cache_full_intraday_fetch,
            )

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        symbols: Sequence[str],
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
        cache_full_intraday_fetch: bool = False,
    ) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        jobs: List[Tuple[DateLike, List[str]]] = []
        base_symbols = _clean_symbols(symbols)
        for ts in timestamps:
            jobs.append((ts, base_symbols))

        results: List[Tuple[DateLike, Dict[str, List[InstrumentLike]]]] = []

        with self:

            def _process_one(ts: DateLike, syms: List[str]):
                return ts, self._get_data_for_timestamp(
                    syms,
                    ts,
                    show_tqdm=show_tqdm,
                    force_refresh=force_refresh,
                    cache_full_intraday_fetch=cache_full_intraday_fetch,
                )

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
        self.__open__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))
