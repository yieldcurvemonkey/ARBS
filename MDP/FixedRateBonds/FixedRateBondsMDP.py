import contextlib
import dataclasses
import datetime
import importlib.util
import itertools
import logging
import os
import random
import re
import threading
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote as urlquote

import pandas as pd
import pytz
import QuantLib as ql
import requests
import tqdm

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricable import _GenericPricable
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Nord proxy helpers (mirrors STIRFutureMDP pattern)
# ---------------------------------------------------------------------------
_NORD_HOSTS = [
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

_FRB_PROXY_STATE: Dict[str, Any] = {}
_FRB_PROXY_LOCK = threading.RLock()


@dataclasses.dataclass(frozen=True)
class _CitiVeloPrefetch:
    """What ``_citivelo_prefetch_range`` warmed, per mode.

    The per-mode flags are **data-bearing**: True only when the warm actually put
    rows in the tag cache for that mode. ``bulk_get_data`` reads
    ``intraday_ok`` to decide that per-point reads may go OFFLINE, and an offline
    read of a cache that was never warmed does not fail - it returns an empty
    column, which downstream reads as "Citi served nothing in this window". So
    "the prefetch did not raise" is the wrong test; a prefetch that quietly did
    nothing has to leave the old online behaviour in place.
    """

    tags: int = 0
    eod_ok: bool = False
    intraday_ok: bool = False


def _socksio_available() -> bool:
    return importlib.util.find_spec("socksio") is not None


def _build_socks5h(host: str) -> dict:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{urlquote(user, safe='')}:{urlquote(pwd, safe='')}@{host}:1080"
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


def _init_frb_proxy_state() -> None:
    """Lazily initialize the process-wide proxy rotation state."""
    if not _FRB_PROXY_STATE:
        hosts = list(_NORD_HOSTS)
        random.shuffle(hosts)
        _FRB_PROXY_STATE["cycler"] = itertools.cycle(hosts)
        _FRB_PROXY_STATE["proxies"] = None
        _FRB_PROXY_STATE["host"] = None
        _FRB_PROXY_STATE["chosen_at"] = 0.0
        _FRB_PROXY_STATE["ttl"] = 120
        _FRB_PROXY_STATE["failures"] = 0


def _choose_frb_proxy(*, force_rotate: bool = False) -> dict | None:
    """Pick the next working Nord proxy (round-robin with preflight).

    Args:
        force_rotate: If True, invalidate the current proxy and cycle to
            the next one regardless of TTL. Use after a fetch-time failure.
    """
    if not _socksio_available():
        return None

    import time

    with _FRB_PROXY_LOCK:
        _init_frb_proxy_state()
        now = time.time()

        # Return cached proxy if still valid and not force-rotating
        if (
            not force_rotate
            and _FRB_PROXY_STATE["proxies"] is not None
            and (now - _FRB_PROXY_STATE["chosen_at"]) < _FRB_PROXY_STATE["ttl"]
        ):
            return _FRB_PROXY_STATE["proxies"]

        if force_rotate:
            old_host = _FRB_PROXY_STATE.get("host")
            _FRB_PROXY_STATE["failures"] = _FRB_PROXY_STATE.get("failures", 0) + 1
            _logger.warning(
                "FRB proxy rotation forced (prev=%s, consecutive_failures=%d)",
                old_host or "direct",
                _FRB_PROXY_STATE["failures"],
            )

        # Try each host until one works
        for _ in range(len(_NORD_HOSTS)):
            host = next(_FRB_PROXY_STATE["cycler"])
            if host is None:
                proxies = None
            else:
                proxies = _build_socks5h(host)

            if _preflight_proxy(proxies):
                _FRB_PROXY_STATE["proxies"] = proxies
                _FRB_PROXY_STATE["host"] = host
                _FRB_PROXY_STATE["chosen_at"] = now
                _FRB_PROXY_STATE["failures"] = 0
                _logger.info("FRB proxy selected: %s", host or "direct")
                return proxies

        _logger.warning("All Nord proxies failed preflight, falling back to direct")
        _FRB_PROXY_STATE["proxies"] = None
        _FRB_PROXY_STATE["host"] = None
        _FRB_PROXY_STATE["chosen_at"] = now
        return None


def _invalidate_frb_proxy() -> None:
    """Mark the current proxy as failed so the next call rotates."""
    with _FRB_PROXY_LOCK:
        _FRB_PROXY_STATE["chosen_at"] = 0.0


def _validate_proxy_pool(*, max_proxies: int = 4, timeout: int = 6) -> list[tuple[str | None, dict | None]]:
    """Preflight multiple Nord proxies in parallel and return validated ones."""
    if not _socksio_available():
        return [(None, None)]

    from concurrent.futures import ThreadPoolExecutor

    candidates = [h for h in _NORD_HOSTS if h is not None]
    random.shuffle(candidates)
    # Always include direct as fallback
    candidates_with_direct: list[str | None] = candidates + [None]

    def _check(host: str | None) -> tuple[str | None, dict | None, bool]:
        proxies = _build_socks5h(host) if host else None
        ok = _preflight_proxy(proxies, timeout=timeout)
        return host, proxies, ok

    valid: list[tuple[str | None, dict | None]] = []
    with ThreadPoolExecutor(max_workers=min(len(candidates_with_direct), 8)) as pool:
        for host, proxies, ok in pool.map(_check, candidates_with_direct):
            if ok:
                valid.append((host, proxies))
                if len(valid) >= max_proxies:
                    break

    if not valid:
        _logger.warning("No proxies passed preflight, using direct")
        return [(None, None)]

    _logger.info(
        "Validated %d proxies: %s",
        len(valid),
        [h or "direct" for h, _ in valid],
    )
    return valid


def _webull_fetch_multi_proxy(
    *,
    cusips: list,
    start,
    end,
    show_tqdm: bool,
    max_proxies: int = 4,
    max_concurrent_per_proxy: int = 64,
) -> pd.DataFrame:
    """Fetch Webull intraday data striped across multiple Nord proxies.

    Partitions CUSIPs across validated proxies and fetches each partition
    in a separate thread with its own httpx.AsyncClient. This multiplies
    effective throughput by the number of proxies.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher

    pool_proxies = _validate_proxy_pool(max_proxies=max_proxies)
    n = len(pool_proxies)

    # Round-robin partition CUSIPs across proxies
    chunks: list[list] = [[] for _ in range(n)]
    for i, cusip in enumerate(cusips):
        chunks[i % n].append(cusip)

    _logger.info(
        "Multi-proxy fetch: %d cusips across %d proxies (%s cusips/proxy)",
        len(cusips),
        n,
        "/".join(str(len(c)) for c in chunks),
    )

    # Scale down concurrency per proxy to avoid aggregate rate-limiting
    effective_concurrent = min(max_concurrent_per_proxy, max(8, 128 // n))

    def _fetch_chunk(chunk_cusips: list, proxy_info: tuple, chunk_idx: int) -> pd.DataFrame:
        host, proxies = proxy_info
        concurrent = effective_concurrent if proxies else 32
        wb = WebullFintechFetcher(
            debug_verbose=False,
            error_verbose=True,
            proxies=proxies,
            global_timeout=15,
        )
        return wb.intraday_by_cusips(
            cusips=chunk_cusips,
            start=start,
            end=end,
            show_tqdm=(show_tqdm and chunk_idx == 0),  # tqdm on first chunk only
            max_concurrent_tasks=concurrent,
            max_keepalive_connections=concurrent,
        )

    results: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = {
            pool.submit(_fetch_chunk, chunk, proxy, idx): (idx, proxy[0], len(chunk))
            for idx, (chunk, proxy) in enumerate(zip(chunks, pool_proxies))
            if chunk
        }
        for future in as_completed(futures):
            idx, host, chunk_size = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    results.append(df)
                    _logger.info("Proxy %s: fetched %d columns", host or "direct", len(df.columns))
            except Exception as exc:
                _logger.warning("Multi-proxy fetch failed for proxy %s (%d cusips): %s", host or "direct", chunk_size, exc)

    if not results:
        return pd.DataFrame()
    return pd.concat(results, axis=1).sort_index()


def _webull_fetch_with_proxy_fallback(
    *,
    cusips: list,
    start,
    end,
    show_tqdm: bool,
    max_retries: int = 2,
    error_verbose: bool = True,
) -> pd.DataFrame:
    """Fetch Webull intraday data with automatic proxy rotation on failure.

    Tries the current proxy first. On SOCKS5 auth errors, connection
    failures, or rate-limit responses, rotates to the next proxy and
    retries up to ``max_retries`` times.
    """
    from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        force_rotate = attempt > 0
        proxies = _choose_frb_proxy(force_rotate=force_rotate)
        max_concurrent = 64 if proxies else 32

        try:
            wb = WebullFintechFetcher(
                debug_verbose=False,
                error_verbose=error_verbose,
                proxies=proxies,
            )
            result = wb.intraday_by_cusips(
                cusips=cusips,
                start=start,
                end=end,
                show_tqdm=show_tqdm,
                max_concurrent_tasks=max_concurrent,
                max_keepalive_connections=max_concurrent,
            )
            return result
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            is_proxy_error = any(
                kw in exc_str
                for kw in (
                    "socks",
                    "proxy",
                    "authentication",
                    "connection",
                    "timeout",
                    "429",
                    "too many",
                    "reset by peer",
                    "closed",
                )
            )
            if is_proxy_error and attempt < max_retries:
                _logger.warning(
                    "Webull fetch attempt %d/%d failed (proxy error): %s — rotating proxy",
                    attempt + 1, max_retries + 1, exc,
                )
                _invalidate_frb_proxy()
                continue
            # Non-proxy error or out of retries
            raise

    raise last_exc  # type: ignore[misc]

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
_BulkOut = Dict[DateLike, Dict[str, "_FixedRateBondGenericPricer"]]


@contextlib.contextmanager
def _closer(obj):
    try:
        yield obj
    finally:
        getattr(obj, "close_cache", lambda: None)()


def _alias_to_cusip(alias: str, ref_table: pd.DataFrame) -> Optional[str]:
    if not isinstance(alias, str):
        return None

    # Backward-compat: normalize legacy '/' to '-'
    alias = alias.strip().replace("/", "-")

    m = re.match(r"^(?P<mm>\d{2})(?P<yy>\d{2})(?:-(?P<oi>\d{1,2}))?$", alias)
    if not m:
        return None

    mm = int(m.group("mm"))
    yy = int(m.group("yy"))
    if not (1 <= mm <= 12):
        raise ValueError(f"Invalid alias month in '{alias}'")

    # 80–99 -> 1900s, else 2000s (tweak if you expect many 1980s bonds)
    year = 1900 + yy if yy >= 80 else 2000 + yy
    prev_month = 12 if mm == 1 else (mm - 1)

    # Parse maturity dates
    mats = pd.to_datetime(ref_table["maturity_date"], errors="coerce")
    if mats.isna().all():
        raise ValueError("All maturity_date values failed to parse as dates")

    def _is_eom(ts: pd.Timestamp) -> bool:
        d = ts.date()
        qd = ql.Date(d.day, d.month, d.year)
        return qd == ql.UnitedStates(ql.UnitedStates.GovernmentBond).endOfMonth(qd)

    mask_target = (mats.dt.year.eq(year)) & (mats.dt.month.eq(mm))
    fam = ref_table.loc[mask_target].copy()
    if fam.empty:
        prev_month = 12 if mm == 1 else (mm - 1)
        prev_year = year - 1 if mm == 1 else year
        is_cal_eom = mats.dt.is_month_end
        mask_prev_eom = (mats.dt.year.eq(prev_year)) & (mats.dt.month.eq(prev_month)) & is_cal_eom
        fam = ref_table.loc[mask_prev_eom].copy()

    if fam.empty:
        raise KeyError(f"Alias '{alias}' did not resolve to any CUSIP in reference data")

    oi_num = m.group("oi")
    if oi_num:
        want = str(int(oi_num))

        def _norm_oi_cell(x) -> str:
            if pd.isna(x):
                return ""
            s = str(x)
            mnum = re.search(r"(\d+)", s)
            return mnum.group(1) if mnum else s.strip()

        fam = fam[fam["oi"].map(_norm_oi_cell).str.casefold() == want.casefold()]
        if fam.empty:
            raise KeyError(f"Alias '{alias}' with oi '{want}' found no matches")
    else:
        # Require disambiguation if multiple OI buckets exist
        if "oi" in fam.columns:

            def _oi_num_set(col: pd.Series):
                out = set()
                for v in col.dropna().astype(str):
                    mnum = re.search(r"(\d+)", v)
                    out.add(mnum.group(1) if mnum else v.strip())
                return sorted(out)

            oi_set = _oi_num_set(fam["oi"])
            if len(oi_set) > 1:
                raise AssertionError(
                    f"Ambiguous alias '{alias}'. Multiple original-issue buckets found: {', '.join(oi_set)}. "
                    f"Use an oi-aware alias like 'MMYY-10' (e.g., '{alias}-{oi_set[0]}')."
                )

    sort_cols = [c for c in ["maturity_date", "issue_date"] if c in fam.columns]
    if sort_cols:
        fam = fam.sort_values(sort_cols)
    unique_cusips = fam["cusip"].astype(str).unique()

    if len(unique_cusips) != 1:
        raise AssertionError(f"Alias '{alias}' maps to multiple CUSIPs: {', '.join(unique_cusips)}. " f"Please specify oi explicitly (e.g., '{alias}-30').")

    return unique_cusips[0]


def _filter_and_rank_ref_df(
    ref_df: pd.DataFrame,
    as_of: datetime.date,
) -> pd.DataFrame:
    """Filter reference data to bonds active on *as_of* and rank by recency.

    Roll timing uses auction_date + 1 business day: the new on-the-run
    (CT10, etc.) takes effect the day after auction, avoiding the
    pre-settlement cheapening window on the old issue.  Falls back to
    issue_date when auction_date is unavailable.
    """
    if "auction_date" in ref_df.columns and ref_df["auction_date"].notna().any():
        _cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        as_of_ql = ql.Date(as_of.day, as_of.month, as_of.year)

        def _auction_plus_1bd(ad):
            if pd.isna(ad):
                return pd.NaT
            ql_ad = ql.Date(ad.day, ad.month, ad.year)
            nxt = _cal.advance(ql_ad, ql.Period("1D"))
            return datetime.date(nxt.year(), nxt.month(), nxt.dayOfMonth())

        roll_date = ref_df["auction_date"].apply(_auction_plus_1bd)
        roll_date = roll_date.fillna(ref_df["issue_date"])
    else:
        roll_date = ref_df["issue_date"]

    eligible = (roll_date < as_of) & (ref_df["maturity_date"] >= as_of)
    # Exclude bonds whose roll_date has passed but haven't actually been
    # issued yet (no FedInvest data until issue_date).  Fall back to old
    # on-the-run for auction-to-settlement gap.
    eligible = eligible & (ref_df["issue_date"] < as_of)

    out = ref_df[eligible].copy()
    out["rank"] = out.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1
    return out


class FixedRateBondsMDP(MarketDataProvider[_GenericPricable], LayeredCacheMixin):

    _FRB_PRICER_CACHE = "_frb_pricer_cache"

    #: Vintage of the Velocity pricer cache. The key is otherwise
    #: ``{date}-{cusip}-{source}``, none of which changes when the code that BUILDS
    #: the pricer changes - so a cached entry outlives any correction to how it was
    #: made, silently and forever.
    #:
    #: That is not hypothetical. The quote sanity screen refuses Citi's
    #: ``PRICE = -0.562509`` for the on-the-run 2-year on 2026-07-14, and on a
    #: machine whose cache predates the screen the refusal never ran: the pricer
    #: came back from disk still carrying the negative price.
    #:
    #: **Bump this whenever the pricer's inputs or construction change.**
    #: v2: quotes are screened by ``bonds.sanity`` before they can price.
    CITIVELO_PRICER_CACHE_VERSION = "v2"

    def __init__(self, source: str = "USTS_FEDINVEST_WSJ_LIVE-QL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        LayeredCacheMixin.__init__(self)

        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False
        self._pending_cache_writes: Dict[str, dict] = {}

        if source == "USTS_FEDINVEST_WSJ_LIVE-QL" or source == "USTS_FEDINVEST_WSJ_LIVE-RL":
            from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher

            self.fi = FedInvestDataFetcher()

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._FRB_PRICER_CACHE):
            return
        cache_path = LayeredCacheMixin.default_cache_path("FixedRateBondPricer_Cache")
        self.open_cache(
            cache_attr=self._FRB_PRICER_CACHE,
            path=cache_path,
            encode=None,
            decode=None,
        )
        self._cache_ready = True

    @staticmethod
    def _py_scalar(v):
        try:
            import numpy as np

            if isinstance(v, np.generic):
                return v.item()
        except Exception:
            pass

        if isinstance(v, (pd.Timestamp, datetime.datetime, datetime.date)):
            return v.isoformat()
        return v

    @classmethod
    def _pyify_meta(cls, meta: Dict[str, Any]) -> Dict[str, Any]:
        return {k: cls._py_scalar(v) for k, v in dict(meta or {}).items()}

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        # Buffer writes in memory; flushed to diskcache on __close__.
        self._pending_cache_writes[key] = value

    def _threadsafe_cache_get(self, key: str):
        # Check pending writes first (L0), then diskcache (L1).
        pending = self._pending_cache_writes.get(key)
        if pending is not None:
            return pending
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            return cache.get(key)

    def _flush_pending_cache_writes(self, *, background: bool = True) -> None:
        """Flush buffered writes to diskcache, optionally in a background thread."""
        if not self._pending_cache_writes:
            return
        batch = dict(self._pending_cache_writes)
        self._pending_cache_writes.clear()

        # Grab a reference to the cache now so the background thread can
        # write without holding _open_lock (avoids blocking subsequent __enter__).
        self._ensure_pricer_cache()
        cache_ref = getattr(self, self._FRB_PRICER_CACHE, None)
        if cache_ref is None:
            return

        def _do_flush():
            for key, value in batch.items():
                try:
                    cache_ref[key] = value
                except Exception:
                    pass

        if background:
            t = threading.Thread(target=_do_flush, daemon=True, name="frb-cache-flush")
            t.start()
        else:
            _do_flush()

    def _citivelo_option(self, name: str, kwargs: Optional[Dict[str, Any]] = None, *, default: Any = None) -> Any:
        """A Velocity bond option, from the REQUEST first and the constructor second.

        Both levels exist because both callers exist and only one of them can pass
        a request kwarg. ``_get_multi_pricers(kwargs=...)`` is reachable when
        something calls the MDP directly; a ``TimeseriesBuilder`` run is not -
        ``TB.FixedRateBondsTB`` calls ``bulk_get_data`` with a fixed signature and
        forwards nothing, so without a constructor level there is no way to make a
        timeseries build read ``offline=True``.

        That matters more than convenience. A build phase that cannot be forced
        offline is a build phase that opens Excel on a cache miss - on a scheduled
        task, against an add-in whose memory only ever grows and that only a human
        restart clears. It wedged at 5,249 MB on 2026-08-07.

        Request beats constructor so a single call can still opt out, and ``None``
        means "not specified" at both levels rather than "off": passing
        ``offline=None`` explicitly must not defeat a constructor that said True.
        """
        if kwargs is not None:
            value = kwargs.get(name)
            if value is not None:
                return value
        value = self.config.get(name)
        return default if value is None else value

    def _resolve_aliases_bulk(
        self,
        symbols: List[str],
        timestamp: Union[datetime.datetime, datetime.date, Literal["live"]],
        *,
        ref_df: pd.DataFrame,
    ) -> Tuple[OrderedDict, Dict[str, dict]]:
        alias_to_cusip: "OrderedDict[str, str]" = OrderedDict()
        meta_by_cusip: Dict[str, dict] = {}

        # Pre-computed ref view for the as-of filter is already passed in
        # and includes the 'rank' column.
        for raw in symbols:
            alias = raw.strip()
            cusip = alias  # default: treat as CUSIP
            # Constant-maturity aliases
            m_ct = re.match(r"^CT(\d+)$", alias, re.IGNORECASE)
            m_o = re.match(r"^(O{1,3})(\d+)$", alias, re.IGNORECASE)
            m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", alias, re.IGNORECASE)

            try:
                if m_ct:
                    rank, tenor = 0, int(m_ct.group(1))
                    oi = f"{tenor}-Year"
                    hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
                    if hit.empty:
                        raise KeyError(f"No CT{tenor} in ref data for {alias}")
                    cusip = str(hit.iloc[0]["cusip"])
                elif m_o:
                    rank, tenor = len(m_o.group(1)), int(m_o.group(2))
                    oi = f"{tenor}-Year"
                    hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
                    if hit.empty:
                        raise KeyError(f"No O{'O'* (rank-1)}{tenor} match for {alias}")
                    cusip = str(hit.iloc[0]["cusip"])
                elif m_ox:
                    rank, tenor = int(m_ox.group(1)), int(m_ox.group(2))
                    oi = f"{tenor}-Year"
                    hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
                    if hit.empty:
                        raise KeyError(f"No Ox{rank}{tenor} match for {alias}")
                    cusip = str(hit.iloc[0]["cusip"])
                else:
                    # Monthly alias (MMYY or MMYY-oi)
                    try:
                        resolved = _alias_to_cusip(alias, ref_df)
                        if resolved:
                            cusip = resolved
                    except AssertionError:
                        # bubble "need oi disambiguation" up unchanged
                        raise

            except Exception:
                # not an alias we handle -> keep original (CUSIP expected)
                cusip = alias

            # attach meta (first row for that cusip)
            row = ref_df[ref_df["cusip"] == cusip]
            if row.empty:
                # TODO handle missing cusips in reference data (most likely between auction date and issue date)
                # raise KeyError(f"CUSIP {cusip} not present in reference set for {timestamp}")
                continue

            meta_by_cusip[cusip] = row.iloc[0].to_dict()
            alias_to_cusip[raw] = cusip

        return alias_to_cusip, meta_by_cusip

    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any], issue_date_key: str, maturity_date_key: str, cpn_key: str) -> _FixedRateBondGenericPricer:
        def _iso_to_date(s: str) -> datetime.date:
            try:
                return datetime.date.fromisoformat(s)
            except ValueError:
                return datetime.datetime.fromisoformat(s).date()

        if "ql_frb_id" in args:
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

            meta = args.get("meta_data") or {}
            kwargs = dict(
                ql_frb_id=args["ql_frb_id"],
                reference_date=_iso_to_date(args["reference_date"]),
                issue_date=_iso_to_date(meta[issue_date_key]),
                maturity_date=_iso_to_date(meta[maturity_date_key]),
                cpn=meta[cpn_key],
                meta_data=meta,
            )
            if "ytm" in args and args["ytm"] is not None:
                kwargs["ytm"] = float(args["ytm"])
            elif "clean_price" in args and args["clean_price"] is not None:
                kwargs["clean_price"] = float(args["clean_price"])
            else:
                raise ValueError("Cached args must include either 'ytm' or 'clean_price'.")

            return QLFixedRateBondPricer(**kwargs)

        elif "rl_frb_id" in args:
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            meta = args.get("meta_data") or {}
            kwargs = dict(
                rl_frb_id=args["rl_frb_id"],
                reference_date=_iso_to_date(args["reference_date"]),
                issue_date=_iso_to_date(meta[issue_date_key]),
                maturity_date=_iso_to_date(meta[maturity_date_key]),
                cpn=meta[cpn_key],
                meta_data=meta,
            )
            if "ytm" in args and args["ytm"] is not None:
                kwargs["ytm"] = float(args["ytm"])
            elif "clean_price" in args and args["clean_price"] is not None:
                kwargs["clean_price"] = float(args["clean_price"])
            else:
                raise ValueError("Cached args must include either 'ytm' or 'clean_price'.")

            return RLFixedRateBondPricer(**kwargs)

        else:

            raise NotImplementedError()

    def get_pricer(self, request: dict) -> Dict[str, _FixedRateBondGenericPricer]:
        pricers = self.get_data(request)  # reuse the existing logic
        if pricers is None:
            raise RuntimeError(f"FixedRateBondsMDP could not build a pricer(s) for request: {request}")
        return pricers

    def get_data(self, request: dict) -> Optional[Dict[str, _FixedRateBondGenericPricer]]:
        cusips = request.pop("cusips")
        timestamp = request.pop("timestamp")

        if not cusips or not timestamp:
            raise ValueError("Request must contain 'cusips' and 'timestamp'.")

        return self._get_multi_pricers(cusips=cusips, timestamp=timestamp, kwargs=request)

    def _get_multi_pricers(
        self, cusips: Union[str, List[str]], timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[Dict[str, _FixedRateBondGenericPricer]]:
        clean_cusips = []
        for c in cusips:
            if "x" in c and "Ox" not in c:
                clean_cusips.extend(c.split("x"))
            elif "/" in c and not re.match(r"^\d{2}\d{2}/\d{1,2}$", c):
                clean_cusips.extend(c.split("/"))
            else:
                clean_cusips.append(c)

        show_tqdm = kwargs.get("show_tqdm", False)
        today = datetime.date.today()
        is_live = (timestamp == "live") or (type(timestamp) == datetime.date and timestamp == today)
        wsj_buffer = self._wsj_buffer_date()
        ts_qldate = ql.Date(timestamp.day, timestamp.month, timestamp.year) if hasattr(timestamp, "day") else ql.Date.todaysDate()
        is_in_wsj_buffer = ts_qldate > wsj_buffer

        if self.source.upper() in ["USTS_FEDINVEST_WSJ_LIVE-QL", "USTS_FEDINVEST_WSJ_LIVE-RL"] and (is_live or is_in_wsj_buffer):
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            force_refresh = bool(kwargs.get("force_refresh", False))
            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp
            if hasattr(as_of_ref, "date"):
                as_of_ref = as_of_ref.date()
            ref_df = update_reference_data(
                source="fiscaldata",
                force_refresh=force_refresh,
            )
            ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)
            alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(clean_cusips, timestamp, ref_df=ref_df)

            out: Dict[str, _FixedRateBondGenericPricer] = {}

            if is_live:
                wsj = WSJFetcher()
                live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                for original, cusip in alias_to_cusip.items():
                    try:
                        meta = dict(meta_by_cusip[cusip])
                        meta["timestamp"] = live_data[cusip]["timestamp"]
                        if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                            out[original] = RLFixedRateBondPricer(
                                rl_frb_id="USTS",
                                reference_date=live_data[cusip]["timestamp"].date(),
                                issue_date=meta["issue_date"],
                                maturity_date=meta["maturity_date"],
                                cpn=meta["cpn"],
                                ytm=float(live_data[cusip]["ytm"]),
                                meta_data=meta,
                            )
                        else:
                            out[original] = QLFixedRateBondPricer(
                                ql_frb_id="USTS",
                                reference_date=live_data[cusip]["timestamp"].date(),
                                issue_date=meta["issue_date"],
                                maturity_date=meta["maturity_date"],
                                cpn=meta["cpn"],
                                ytm=float(live_data[cusip]["ytm"]),
                                meta_data=meta,
                            )
                    except:
                        # TODO handle errors
                        pass
                return out

            if is_in_wsj_buffer:
                self._ensure_pricer_cache()
                cache = getattr(self, self._FRB_PRICER_CACHE)
                force_refresh = bool(kwargs.get("force_refresh", False))

                alias_to_fetch: Dict[str, str] = {}
                for original, cusip in alias_to_cusip.items():
                    cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"
                    cached = cache.get(cache_key)
                    if cached is not None and not force_refresh:
                        if isinstance(cached, dict) and cached.get("source") == "fedinvest":
                            out[original] = self._build_pricer_from_args(
                                cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                            )
                            continue
                        if hasattr(cached, "__class__") and cached.__class__.__name__ in (
                            "RLFixedRateBondPricer",
                            "QLFixedRateBondPricer",
                        ):
                            out[original] = cached
                            continue
                        if isinstance(cached, dict) and cached.get("source") == "wsj_intraday":
                            alias_to_fetch[original] = cusip
                            continue
                        out[original] = self._build_pricer_from_args(
                            cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                        )
                        continue
                    alias_to_fetch[original] = cusip

                # FedInvest-first: try ground-truth EOD before falling back to WSJ intraday
                if alias_to_fetch:
                    ts_date = timestamp.date() if hasattr(timestamp, "date") else timestamp
                    timestamp_dt = datetime.datetime(ts_date.year, ts_date.month, ts_date.day)
                    try:
                        fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh)
                        fi_df = fi_map.get(timestamp_dt)
                    except Exception:
                        fi_df = None

                    if fi_df is not None and not fi_df.empty:
                        fi_df_indexed = fi_df.set_index("cusip")
                        fi_covered = []
                        for original, cusip in alias_to_fetch.items():
                            if cusip in fi_df_indexed.index:
                                clean_price = float(fi_df_indexed.loc[cusip]["eod_price"])
                                if not (50.0 <= clean_price <= 250.0):
                                    continue
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = timestamp
                                if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                                    args = {
                                        "rl_frb_id": "USTS",
                                        "reference_date": ts_date.isoformat(),
                                        "clean_price": clean_price,
                                        "meta_data": self._pyify_meta(meta),
                                        "schema": 2,
                                        "source": "fedinvest",
                                    }
                                else:
                                    args = {
                                        "ql_frb_id": "USTS",
                                        "reference_date": ts_date.isoformat(),
                                        "clean_price": clean_price,
                                        "meta_data": self._pyify_meta(meta),
                                        "schema": 2,
                                        "source": "fedinvest",
                                    }
                                cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"
                                cache[cache_key] = args
                                out[original] = self._build_pricer_from_args(
                                    args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                                )
                                fi_covered.append(original)
                        for original in fi_covered:
                            del alias_to_fetch[original]

                # WSJ fallback for dates FedInvest hasn't published yet
                if alias_to_fetch:
                    wsj = WSJFetcher()
                    mapping = {get_isin_from_cusip(c, "US")[2:]: c for c in alias_to_fetch.values()}
                    wide = wsj.ust_intraday_timeseries(mapping, show_tqdm=show_tqdm)

                    if wide.empty:
                        return out

                    est = pytz.timezone("America/New_York")
                    t_3pm = est.localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0, 0)).astimezone(pytz.UTC)
                    idx = wide.index
                    pos = idx.get_indexer([t_3pm], method="nearest")[0]
                    nearest_ts = idx[pos]
                    if abs(nearest_ts - t_3pm) > pd.Timedelta("360min"):
                        raise ValueError(f"No intraday snapshot within 60min of 3pm ET. Nearest: {nearest_ts}")

                    for original, cusip in alias_to_fetch.items():
                        try:
                            y = wide[cusip].iloc[pos]
                            ts_for_meta = nearest_ts
                            if pd.isna(y):
                                col = wide[cusip].dropna()
                                if col.empty:
                                    raise ValueError(f"No intraday data for {cusip} near 3pm")
                                ts_for_meta = col.index[col.index.get_indexer([t_3pm], method="nearest")[0]]
                                y = col.loc[ts_for_meta]

                            meta = dict(meta_by_cusip[cusip])
                            meta["timestamp"] = ts_for_meta
                            if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                                args = {
                                    "rl_frb_id": "USTS",
                                    "reference_date": ts_for_meta.date().isoformat(),
                                    "ytm": float(y),
                                    "meta_data": self._pyify_meta(meta),
                                    "schema": 1,
                                    "source": "wsj_intraday",
                                }
                            else:
                                args = {
                                    "ql_frb_id": "USTS",
                                    "reference_date": ts_for_meta.date().isoformat(),
                                    "ytm": float(y),
                                    "meta_data": self._pyify_meta(meta),
                                    "schema": 1,
                                    "source": "wsj_intraday",
                                }
                            cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"
                            cache[cache_key] = args
                            out[original] = self._build_pricer_from_args(
                                args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                            )
                        except Exception:
                            # TODO handle errors
                            pass
                return out

        elif self.source.upper() == "USTS_TRADINGVIEW_LIVE-RL":
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.TRADINGVIEW.TradingViewFetcher import (
                fetch_cusip_prices_eod_timeseries_parallel as fetch_cusip_eod_timeseries_parallel,
            )
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            force_refresh = bool(kwargs.get("force_refresh", False))
            today = datetime.date.today()

            if timestamp == "live":
                as_of_date = today
                is_live_request = True
            elif isinstance(timestamp, datetime.datetime):
                as_of_date = timestamp.date()
                is_live_request = as_of_date == today
            elif isinstance(timestamp, datetime.date):
                as_of_date = timestamp
                is_live_request = as_of_date == today
            else:
                raise TypeError("timestamp must be 'live', datetime.date, or datetime.datetime")

            ref_df = update_reference_data(source="treasurydirect", force_refresh=force_refresh)
            alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(clean_cusips, timestamp, ref_df=ref_df)

            out: Dict[str, _FixedRateBondGenericPricer] = {}
            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)

            cache_ts = timestamp if isinstance(timestamp, datetime.datetime) else as_of_date
            alias_to_cusip_to_fetch = {}
            for original, cusip in alias_to_cusip.items():
                cache_key = f"{cache_ts.isoformat()}-{cusip}-{self.source.upper()}"
                cached = cache.get(cache_key)
                if cached is not None and not force_refresh:
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                        out[original] = cached
                        continue
                    out[original] = self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    continue
                alias_to_cusip_to_fetch[original] = cusip

            if alias_to_cusip_to_fetch:
                tv_df = fetch_cusip_eod_timeseries_parallel(
                    cusips=list(alias_to_cusip_to_fetch.values()),
                    start=as_of_date,
                    end=as_of_date,
                    val_to_return="close",
                )
                for original, cusip in alias_to_cusip_to_fetch.items():
                    if tv_df.empty or cusip not in tv_df.columns:
                        continue
                    series = tv_df[cusip].dropna()
                    if series.empty:
                        continue

                    if is_live_request:
                        ts = series.index[-1]
                        price = float(series.iloc[-1])
                    elif not isinstance(series.index, pd.DatetimeIndex):
                        continue
                    else:
                        idx = series.index
                        day_rows = series[idx.date == as_of_date]
                        if day_rows.empty:
                            continue
                        ts = day_rows.index[-1]
                        price = float(day_rows.iloc[-1])

                    meta = dict(meta_by_cusip[cusip])
                    meta["timestamp"] = ts
                    args = {
                        "rl_frb_id": "USTS",
                        "reference_date": ts.date().isoformat(),
                        "clean_price": price,
                        "meta_data": self._pyify_meta(meta),
                        "schema": 2,
                        "source": "tradingview",
                    }
                    cache_key = f"{cache_ts.isoformat()}-{cusip}-{self.source.upper()}"
                    cache[cache_key] = args
                    out[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    # auto-committed (DiskCache)

            return out

        elif self.source.upper() == "USTS_WEBULL_WSJ_LIVE-RL":
            from pandas.tseries.offsets import BDay

            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            force_refresh = bool(kwargs.get("force_refresh", False))
            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp.date()
            ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
            ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)
            alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(clean_cusips, timestamp, ref_df=ref_df)

            out: Dict[str, _FixedRateBondGenericPricer] = {}

            if is_live:
                wsj = WSJFetcher()
                live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                for original, cusip in alias_to_cusip.items():
                    try:
                        meta = dict(meta_by_cusip[cusip])
                        meta["timestamp"] = live_data[cusip]["timestamp"]
                        out[original] = RLFixedRateBondPricer(
                            rl_frb_id="USTS",
                            reference_date=live_data[cusip]["timestamp"].date(),
                            issue_date=meta["issue_date"],
                            maturity_date=meta["maturity_date"],
                            cpn=meta["cpn"],
                            ytm=float(live_data[cusip]["ytm"]),
                            meta_data=meta,
                        )
                    except:
                        # TODO handle errors
                        pass
                return out

            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            alias_to_cusip_to_fetch = {}
            for original, cusip in alias_to_cusip.items():
                cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"
                cached = cache.get(cache_key)
                if cached is not None and not kwargs.get("force_refresh", False):
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                        out[original] = cached
                        continue

                    out[original] = self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    continue

                cache_key = f"{timestamp.isoformat()}-{original}-{self.source.upper()}"
                cached = cache.get(cache_key)
                if cached is not None and not kwargs.get("force_refresh", False):
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                        return cached
                    out[original] = self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    continue

                alias_to_cusip_to_fetch[original] = cusip

            t = timestamp
            ny = pytz.timezone("America/New_York")
            start_ny = ny.localize(datetime.datetime(t.year, t.month, t.day, 7, 0, 0)) - BDay(1)
            end_ny = ny.localize(datetime.datetime(t.year, t.month, t.day, 17, 0, 0)) + BDay(1)
            wide = _webull_fetch_with_proxy_fallback(
                cusips=list(alias_to_cusip_to_fetch.values()),
                start=start_ny,
                end=end_ny,
                show_tqdm=bool(kwargs.get("show_tqdm", True)),
            )
            # print(wide)
            for original, cusip in alias_to_cusip_to_fetch.items():
                for curr_ts, ytm in wide[cusip].items():
                    cache_key = f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}"
                    meta = dict(meta_by_cusip[cusip])
                    meta["timestamp"] = curr_ts.isoformat()
                    args = {
                        "rl_frb_id": "USTS",
                        "reference_date": curr_ts.date().isoformat(),
                        "ytm": ytm,
                        "meta_data": self._pyify_meta(meta),
                        "schema": 1,
                        "source": cache_key,
                    }
                    cache[cache_key] = args
                    # auto-committed (DiskCache)

                    if curr_ts == timestamp:
                        out[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

            return out

        elif self.source.upper() in ["USTS_CITIVELO-QL", "USTS_CITIVELO-RL"]:
            # Citi Velocity bond quotes, read through the Excel add-in seam.
            #
            # The real work lives in MDP/CitiVelocityExcel/bonds/fetcher.py; this
            # branch only resolves identifiers, consults the cache and hands the
            # quote to a pricer. Three things about it are load-bearing:
            #
            #  * the ALIAS table runs first. By the time resolve_bonds() sees a
            #    string it is already a CUSIP, which is why UnifiedQuery(cusip="CT10")
            #    works and why there is no fourth alias implementation in the
            #    Velocity package.
            #  * the MODE is decided by resolve_request(), the same function the
            #    Velocity curve source uses. It is not an isinstance ladder:
            #    pd.Timestamp subclasses datetime subclasses date, so such a ladder
            #    is wrong in both directions, and a midnight Timestamp means EOD.
            #  * LIVE is not cached. An EOD or intraday quote is a fixed historical
            #    fact and caches soundly; caching "live" under today's date would
            #    serve the 09:31 print at 16:00 and call it live.
            #
            # Request kwargs this branch reads:
            #   citivelo_quotes  an existing CitiVeloQuotes to reuse. Without one a
            #                    fresh connection is opened and CLOSED per call - safe
            #                    (this package has a recorded workbook leak, 62
            #                    accumulated) but wrong for a warm, which should pass
            #                    one in and close it once at the end.
            #   offline          serve from the tag cache only; never open Excel.
            #   citivelo_values  override fetcher.DEFAULT_BOND_VALUES. Pass OAS here
            #                    (with a wide eod_lookback) - it is deliberately not
            #                    a default, being empty over any short window.
            #   citivelo_universe  a BondUniverse to resolve against, instead of the
            #                    committed 349-name catalog. See _citivelo_option.
            #
            # Each of those may ALSO be given to the constructor, which is the only
            # route a TimeseriesBuilder run has - TB.FixedRateBondsTB calls
            # bulk_get_data with a fixed kwarg set and passes nothing through. See
            # _citivelo_option.
            #
            # bulk_get_data has NO branch for this source: a timeseries query over
            # it raises NotImplementedError. Loud, not silent, and the per-date
            # _get_multi_pricers path works.
            from MDP.CitiVelocityExcel.bonds import fetcher as _citivelo_bond_fetcher
            from MDP.CitiVelocityExcel.bonds.values import NoQuotedPriceError
            from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import resolve_request, wire_timezone

            CitiVeloBondFetcher = _citivelo_bond_fetcher.CitiVeloBondFetcher

            source_upper = self.source.upper()
            backend = "QL" if source_upper.endswith("-QL") else "RL"
            force_refresh = bool(kwargs.get("force_refresh", False))

            request = resolve_request(timestamp)
            # The WIRE zone, not the machine's. Everything else in this package is
            # anchored there (fetcher._window_bounds does the same job the same
            # way), and timestamps.py contemplates running from another zone via
            # CITIVELO_EXCEL_WIRE_TZ. Run from London at 02:00 BST - 21:00 the
            # previous day in New York - date.today() returns tomorrow's date, so
            # _filter_and_rank_ref_df is asked for a day on which the current
            # on-the-run may not yet be eligible and CT10 resolves to a different
            # CUSIP than the quotes were fetched for.
            as_of_ref = (
                datetime.datetime.now(wire_timezone()).date() if request.mode == "live"
                else (request.eod_date if request.mode == "eod" else request.wire_instant.date())
            )

            ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
            ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)
            alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(clean_cusips, timestamp, ref_df=ref_df)

            out: Dict[str, _FixedRateBondGenericPricer] = {}
            if not alias_to_cusip:
                return out

            cache = None
            cache_stamp = ""
            if request.mode != "live":
                self._ensure_pricer_cache()
                cache = getattr(self, self._FRB_PRICER_CACHE)
                cache_stamp = (
                    f"{self.CITIVELO_PRICER_CACHE_VERSION}-"
                    + (
                        request.eod_date.isoformat()
                        if request.mode == "eod"
                        else request.wire_instant.isoformat()
                    )
                )

            to_fetch: "OrderedDict[str, str]" = OrderedDict()
            for original, cusip in alias_to_cusip.items():
                if cache is not None and not force_refresh:
                    cached = cache.get(f"{cache_stamp}-{cusip}-{source_upper}")
                    if cached is not None:
                        out[original] = self._build_pricer_from_args(
                            cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                        )
                        continue
                to_fetch[original] = cusip

            if to_fetch:
                # strict=False: one bond outside Citi's 349-name UST subset must not
                # lose the other 299 in a warm. Citi carries a liquid subset, so
                # off-the-runs, bills, TIPS and just-auctioned issues do miss.
                #
                # ... and a HISTORICAL query misses far more than that, which is why
                # the universe is overridable. Citi's listing is today's set: over
                # ten years the 28 constant-maturity aliases resolve to 597 bonds
                # and only 307 are still listed. The other 290 matured, and a
                # matured bond is unrecoverable from CVCURVEBOND. Their TAGS still
                # serve - measured on ten of them - so a backfill passes
                # citivelo_universe=historic_universe(...) and gets the whole
                # chained series instead of a hole wherever the constituent has
                # since redeemed.
                resolved, failures = resolve_bonds(
                    list(dict.fromkeys(to_fetch.values())),
                    universe=self._citivelo_option("citivelo_universe", kwargs),
                    strict=False,
                )
                for token, reason in failures.items():
                    _logger.warning("citivelo bonds: %s not resolvable to a quoted bond: %s", token, reason)

                fetcher = CitiVeloBondFetcher(
                    quotes=self._citivelo_option("citivelo_quotes", kwargs),
                    offline=bool(self._citivelo_option("offline", kwargs, default=False)),
                    values=self._citivelo_option("citivelo_values", kwargs),
                )
                try:
                    bond_quotes = fetcher.fetch(
                        list(resolved.values()), timestamp, force_refresh=force_refresh
                    )
                finally:
                    fetcher.close()

                for original, cusip in to_fetch.items():
                    resolution = resolved.get(cusip)
                    if resolution is None:
                        continue
                    quote = bond_quotes.get(resolution.isin)
                    if quote is None:
                        continue
                    try:
                        args = _citivelo_bond_fetcher.build_pricer_args(
                            quote,
                            backend=backend,
                            ref_meta=meta_by_cusip[cusip],
                            source=source_upper,
                        )
                    except NoQuotedPriceError as exc:
                        # This ONE bond cannot be priced from this window: no PRICE
                        # row, or a PRICE materially staler than the rest of its own
                        # response. Reported, not substituted, and the other 299 in
                        # a warm survive it.
                        #
                        # Narrow on purpose. build_pricer_args also raises plain
                        # ValueError for an unknown backend, and float() raises it
                        # for a non-numeric cell; catching the base class turned
                        # "every bond in this basket hit a bug" into an empty dict
                        # and a WARNING line that read like Citi had no data.
                        # BondQuoteTransportError is a RuntimeError for the same
                        # reason and deliberately takes the whole basket down: a
                        # dead add-in is not a market observation.
                        _logger.warning("citivelo bonds: %s -> %s", original, exc)
                        continue
                    args["meta_data"] = self._pyify_meta(args["meta_data"])
                    if cache is not None:
                        cache[f"{cache_stamp}-{cusip}-{source_upper}"] = args
                        # auto-committed (DiskCache)
                    out[original] = self._build_pricer_from_args(
                        args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                    )

            return out

        pricers = {}
        clean_cusips_iter = tqdm.tqdm(clean_cusips, desc="FETCHING CUSIPS...") if show_tqdm else clean_cusips
        for c in clean_cusips_iter:
            try:
                pricers[c] = self._get_single_pricer(cusip=c, timestamp=timestamp, kwargs=kwargs)
            except Exception as e:
                _logger.warning("Failed to fetch pricer for %s @ %s: %s", c, timestamp, e)

        return pricers

    def _get_single_pricer(
        self, cusip: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[_FixedRateBondGenericPricer]:

        if self.source.upper() in ["USTS_TRADINGVIEW_LIVE-RL", "USTS_CITIVELO-QL", "USTS_CITIVELO-RL"]:
            # These sources only have a multi implementation - one batched vendor
            # call for the whole basket. Without this delegation a single-CUSIP
            # request would fall through to the per-source blocks below and be
            # answered by a DIFFERENT vendor than the one that was asked for.
            pricers = self._get_multi_pricers([cusip], timestamp, kwargs)
            if not pricers:
                return None
            return pricers.get(cusip)

        if self.source.upper() in ["USTS_PUBLICDOTCOM_WSJ_LIVE-QL"]:
            from MDP.FixedRateBonds.PUBLICDOTCOM.PublicDotcomDataFetcher import PublicDotcomDataFetcher
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

            ref_df = update_reference_data(source="fiscaldata", force_refresh=kwargs.get("force_refresh", False))
            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp
            ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)

            original_cusip_alias = cusip
            match_ct = re.match(r"^CT(\d+)$", cusip, re.IGNORECASE)
            match_o = re.match(r"^(O{1,3})(\d+)$", cusip, re.IGNORECASE)
            match_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", cusip, re.IGNORECASE)

            rank, tenor = None, None
            if match_ct:
                rank = 0
                tenor = int(match_ct.group(1))
            elif match_o:
                rank = len(match_o.group(1))
                tenor = int(match_o.group(2))
            elif match_ox:
                rank = int(match_ox.group(1))
                tenor = int(match_ox.group(2))

            if rank is not None and tenor is not None:
                oi_str = f"{tenor}-Year"
                target_bond = ref_df[(ref_df["oi"] == oi_str) & (ref_df["rank"] == rank)]
                if not target_bond.empty:
                    cusip = target_bond.iloc[0]["cusip"]
                else:
                    raise KeyError(f"Could not resolve constant maturity alias '{original_cusip_alias}'")
            else:
                try:
                    resolved = _alias_to_cusip(original_cusip_alias, ref_df)
                    if resolved:
                        cusip = resolved
                except AssertionError as e:
                    # Surface explicit "oi required" assertions
                    raise
                except Exception:
                    # Not an alias we handle (fall through to treat input as CUSIP)
                    pass

            ref_df = ref_df[ref_df["cusip"] == cusip]

            if timestamp == "live":
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]
                live_ytm_quote = WSJFetcher().wsj_timeseries_api(wsj_ticker_keys=[wsj_key], append_most_recent_last=True)[wsj_key]
                meta_data = ref_df.iloc[0].to_dict()
                meta_data["timestamp"] = live_ytm_quote.iloc[0, 0]
                return QLFixedRateBondPricer(
                    ql_frb_id="USTS",
                    reference_date=live_ytm_quote.iloc[0, 0].date(),
                    issue_date=meta_data["issue_date"],
                    maturity_date=meta_data["maturity_date"],
                    cpn=meta_data["cpn"],
                    ytm=live_ytm_quote.iloc[0, 1],
                    meta_data=meta_data,
                )

            if type(timestamp) == datetime.date:
                self._ensure_pricer_cache()
                cache = getattr(self, self._FRB_PRICER_CACHE)
                cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"

                cached = cache.get(cache_key)
                if cached is not None and not kwargs.get("force_refresh", False):
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "QLFixedRateBondPricer":
                        return cached
                    return self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

                ts_df = PublicDotcomDataFetcher().public_dotcom_timeseries_api(cusips=[cusip], refresh_jwt=True)[cusip]
                if ts_df.empty:
                    raise KeyError(f"No Public.com timeseries for {cusip} on {timestamp}")

                ts_df = ts_df.dropna(subset=["YTM"]).sort_values("Date").copy()
                ts_df["asof_date"] = ts_df["Date"].dt.date

                day_rows = ts_df[ts_df["asof_date"] == timestamp]
                interpolated = False
                interp_bounds = None

                if not day_rows.empty:
                    ytm_on_day = float(day_rows.sort_values("Date")["YTM"].iloc[-1])
                else:
                    before = ts_df[ts_df["asof_date"] < timestamp].tail(1)
                    after = ts_df[ts_df["asof_date"] > timestamp].head(1)

                    if not before.empty and not after.empty:
                        d0 = before["asof_date"].iloc[0]
                        y0 = float(before["YTM"].iloc[0])
                        d1 = after["asof_date"].iloc[0]
                        y1 = float(after["YTM"].iloc[0])

                        total_days = (d1 - d0).days
                        w = ((timestamp - d0).days / total_days) if total_days > 0 else 0.0
                        ytm_on_day = y0 + (y1 - y0) * w

                        interpolated = True
                        interp_bounds = (d0.isoformat(), d1.isoformat())
                    elif not before.empty or not after.empty:
                        near = before if not before.empty else after
                        ytm_on_day = float(near["YTM"].iloc[0])
                        interpolated = True
                        b = near["asof_date"].iloc[0].isoformat()
                        interp_bounds = (b, None) if not after.empty else (None, b)
                    else:
                        raise KeyError(f"No Public.com timeseries neighbors to interpolate {cusip} on {timestamp}")

                args = {
                    "ql_frb_id": "USTS",
                    "reference_date": timestamp.isoformat(),  # mark as the requested date
                    "ytm": float(ytm_on_day),
                    "meta_data": self._pyify_meta(ref_df.iloc[0].to_dict()),
                    "schema": 1,
                }

                if interpolated:
                    md = args["meta_data"]
                    md["ytm_interpolated"] = True
                    md["ytm_interp_method"] = "linear" if interp_bounds and all(interp_bounds) else "nearest"
                    md["ytm_interp_bounds"] = interp_bounds

                cache[cache_key] = args
                # auto-committed (DiskCache)

                return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

        if self.source.upper() in ["USTS_FEDINVEST_WSJ_LIVE-QL", "USTS_FEDINVEST_WSJ_LIVE-RL"]:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp
            if hasattr(as_of_ref, "date"):
                as_of_ref = as_of_ref.date()
            # ref_df = update_reference_data(source="treasurydirect", source_kwargs={"as_of": as_of_ref}, force_refresh=kwargs.get("force_refresh", False))
            ref_df = update_reference_data(source="fiscaldata", force_refresh=kwargs.get("force_refresh", False))
            ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)

            original_cusip_alias = cusip
            match_ct = re.match(r"^CT(\d+)$", cusip, re.IGNORECASE)
            match_o = re.match(r"^(O{1,3})(\d+)$", cusip, re.IGNORECASE)
            match_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", cusip, re.IGNORECASE)

            rank, tenor = None, None
            if match_ct:
                rank = 0
                tenor = int(match_ct.group(1))
            elif match_o:
                rank = len(match_o.group(1))
                tenor = int(match_o.group(2))
            elif match_ox:
                rank = int(match_ox.group(1))
                tenor = int(match_ox.group(2))

            if rank is not None and tenor is not None:
                oi_str = f"{tenor}-Year"
                target_bond = ref_df[(ref_df["oi"] == oi_str) & (ref_df["rank"] == rank)]
                if not target_bond.empty:
                    cusip = target_bond.iloc[0]["cusip"]
                else:
                    raise KeyError(f"Could not resolve constant maturity alias '{original_cusip_alias}'")
            else:
                try:
                    resolved = _alias_to_cusip(original_cusip_alias, ref_df)
                    if resolved:
                        cusip = resolved
                except AssertionError as e:
                    # Surface explicit "oi required" assertions
                    raise
                except Exception:
                    # Not an alias we handle (fall through to treat input as CUSIP)
                    pass

                if "CTD_" in cusip:
                    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

                    delivery = "A" if "CTD_LD_" in cusip else "D"
                    token_substr = "CTD_LD_" if "CTD_LD_" in cusip else "CTD_ED_"

                    for m_code, month_nums in {
                        "H": [1, 2, 3],
                        "M": [4, 5, 6],
                        "U": [7, 8, 9],
                        "Z": [10, 11, 12],
                    }.items():
                        if as_of_ref.month in month_nums:
                            full_symbol = f"{cusip.split(token_substr)[1]}{m_code}{int(as_of_ref.strftime("%y"))}"

                    ustf_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
                    close_2pm = pytz.timezone("America/Chicago").localize(datetime.datetime(as_of_ref.year, as_of_ref.month, as_of_ref.day, 14, 00))
                    ustf_pricer = ustf_mdp.get_pricer(request=dict(symbols=[full_symbol], timestamp=close_2pm, include_basket=True))
                    ctd_pricer = ustf_pricer[full_symbol].ctd(delivery)
                    cusip = ctd_pricer._meta_data["cusip"]

            ref_df = ref_df[ref_df["cusip"] == cusip]

            if timestamp == "live" or timestamp == datetime.date.today():
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]
                live_ytm_quote = WSJFetcher().wsj_timeseries_api(wsj_ticker_keys=[wsj_key], append_most_recent_last=True)[wsj_key]
                meta_data = ref_df.iloc[0].to_dict()
                meta_data["timestamp"] = live_ytm_quote.iloc[0, 0]
                if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                    return RLFixedRateBondPricer(
                        rl_frb_id="USTS",
                        reference_date=live_ytm_quote.iloc[0, 0].date(),
                        issue_date=meta_data["issue_date"],
                        maturity_date=meta_data["maturity_date"],
                        cpn=meta_data["cpn"],
                        ytm=live_ytm_quote.iloc[0, 1],
                        meta_data=meta_data,
                    )
                else:
                    return QLFixedRateBondPricer(
                        ql_frb_id="USTS",
                        reference_date=live_ytm_quote.iloc[0, 0].date(),
                        issue_date=meta_data["issue_date"],
                        maturity_date=meta_data["maturity_date"],
                        cpn=meta_data["cpn"],
                        ytm=live_ytm_quote.iloc[0, 1],
                        meta_data=meta_data,
                    )

            wsj_buffer = ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(ql.Date.todaysDate(), ql.Period("-3D"))
            if ql.Date(timestamp.day, timestamp.month, timestamp.year) > wsj_buffer:
                self._ensure_pricer_cache()
                cache = getattr(self, self._FRB_PRICER_CACHE)
                cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"
                force_refresh_flag = kwargs.get("force_refresh", False)
                cached = cache.get(cache_key)
                if cached is not None and not force_refresh_flag:
                    if isinstance(cached, dict) and cached.get("source") == "fedinvest":
                        return self._build_pricer_from_args(
                            cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                        )
                    if hasattr(cached, "__class__") and cached.__class__.__name__ in (
                        "RLFixedRateBondPricer",
                        "QLFixedRateBondPricer",
                    ):
                        return cached
                    if not (isinstance(cached, dict) and cached.get("source") == "wsj_intraday"):
                        return self._build_pricer_from_args(
                            cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                        )

                # FedInvest-first: try ground-truth EOD before WSJ intraday
                ts_date = timestamp.date() if hasattr(timestamp, "date") else timestamp
                timestamp_dt = datetime.datetime(ts_date.year, ts_date.month, ts_date.day)
                try:
                    fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh_flag)
                    fi_df = fi_map.get(timestamp_dt)
                    if fi_df is not None and not fi_df.empty:
                        fi_df_idx = fi_df.set_index("cusip")
                        if cusip in fi_df_idx.index:
                            clean_price = float(fi_df_idx.loc[cusip]["eod_price"])
                            if 50.0 <= clean_price <= 250.0:
                                meta_data = self._pyify_meta(ref_df.iloc[0].to_dict())
                                if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                                    args = {
                                        "rl_frb_id": "USTS",
                                        "reference_date": ts_date.isoformat(),
                                        "clean_price": clean_price,
                                        "meta_data": meta_data,
                                        "schema": 2,
                                        "source": "fedinvest",
                                    }
                                else:
                                    args = {
                                        "ql_frb_id": "USTS",
                                        "reference_date": ts_date.isoformat(),
                                        "clean_price": clean_price,
                                        "meta_data": meta_data,
                                        "schema": 2,
                                        "source": "fedinvest",
                                    }
                                cache[cache_key] = args
                                return self._build_pricer_from_args(
                                    args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                                )
                except Exception:
                    pass

                # WSJ intraday fallback
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]

                # pandas series with timezone aware datetime index in utc
                intraday_df = WSJFetcher().ust_intraday_timeseries(wsj_ticker_keys={wsj_key: cusip})[cusip]
                if intraday_df.empty:
                    raise ValueError("intraday_df is empty")

                ust_3pm_close = pytz.timezone("America/New_York").localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0, 0))
                # ust_5pm_close = pytz.timezone("America/New_York").localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 17, 0, 0))

                ts_utc = ust_3pm_close.astimezone(pytz.UTC)
                intraday_df = intraday_df.sort_index()
                pos = intraday_df.index.get_indexer([ts_utc], method="nearest")[0]
                nearest_ts = intraday_df.index[pos]
                tolerance = pd.Timedelta("30min")
                if abs(nearest_ts - ts_utc) > tolerance:
                    raise ValueError(f"No snapshot within {tolerance} of 3pm close")

                closest_snapshot_time = nearest_ts
                closest_snapshot = intraday_df.loc[nearest_ts]
                meta_data = ref_df.iloc[0].to_dict()
                meta_data["timestamp"] = closest_snapshot_time
                if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                    args = {
                        "rl_frb_id": "USTS",
                        "reference_date": closest_snapshot_time.date().isoformat(),
                        "ytm": float(closest_snapshot),
                        "meta_data": self._pyify_meta(meta_data),
                        "schema": 1,
                        "source": "wsj_intraday",
                    }
                else:
                    args = {
                        "ql_frb_id": "USTS",
                        "reference_date": closest_snapshot_time.date().isoformat(),
                        "ytm": float(closest_snapshot),
                        "meta_data": self._pyify_meta(meta_data),
                        "schema": 1,
                        "source": "wsj_intraday",
                    }
                cache[cache_key] = args
                return self._build_pricer_from_args(
                    args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                )

            timestamp_dt = datetime.datetime(timestamp.year, timestamp.month, timestamp.day)

            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"

            cached = cache.get(cache_key)
            if cached is not None and not kwargs.get("force_refresh", False):
                if hasattr(cached, "__class__") and cached.__class__.__name__ == "QLFixedRateBondPricer":
                    return cached
                return self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

            fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=kwargs.get("force_refresh", False))
            fi_df = fi_map.get(timestamp_dt)
            if fi_df is None or fi_df.empty:
                raise KeyError(f"No FedInvest snapshot for {timestamp} (key: {timestamp_dt})")

            fi_df = fi_df.set_index("cusip")
            if cusip not in fi_df.index:
                raise KeyError(f"FedInvest snapshot missing CUSIP {cusip} for {timestamp}")

            clean_price = float(fi_df.loc[cusip]["eod_price"])
            meta_data = self._pyify_meta(ref_df.iloc[0].to_dict())

            if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                args = {
                    "rl_frb_id": "USTS",
                    "reference_date": timestamp.isoformat(),
                    "clean_price": clean_price,
                    "meta_data": meta_data,
                    "schema": 2,
                    "source": "fedinvest",
                }
            else:
                args = {
                    "ql_frb_id": "USTS",
                    "reference_date": timestamp.isoformat(),
                    "clean_price": clean_price,
                    "meta_data": meta_data,
                    "schema": 1,
                    "source": "fedinvest",
                }

            cache[cache_key] = args
            # auto-committed (DiskCache)

            return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

        elif self.source.upper() in ["USTS_WEBULL_WSJ_LIVE-RL"]:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            if timestamp == "live":
                as_of_date = datetime.date.today()
            elif isinstance(timestamp, datetime.datetime):
                as_of_date = timestamp.date()
            elif isinstance(timestamp, datetime.date):
                raise NotImplementedError("must be a timestamp")
            else:
                raise TypeError("timestamp must be 'live', datetime.date, or datetime.datetime")

            ref_df = update_reference_data(source="fiscaldata", force_refresh=kwargs.get("force_refresh", False))
            ref_df = _filter_and_rank_ref_df(ref_df, as_of_date)

            original_cusip_alias = cusip
            m_ct = re.match(r"^CT(\d+)$", cusip, re.IGNORECASE)
            m_o = re.match(r"^(O{1,3})(\d+)$", cusip, re.IGNORECASE)
            m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", cusip, re.IGNORECASE)
            rank = tenor = None
            if m_ct:
                rank, tenor = 0, int(m_ct.group(1))
            elif m_o:
                rank, tenor = len(m_o.group(1)), int(m_o.group(2))
            elif m_ox:
                rank, tenor = int(m_ox.group(1)), int(m_ox.group(2))

            if rank is not None and tenor is not None:
                oi_str = f"{tenor}-Year"
                tgt = ref_df[(ref_df["oi"] == oi_str) & (ref_df["rank"] == rank)]
                if not tgt.empty:
                    cusip = str(tgt.iloc[0]["cusip"])
                else:
                    raise KeyError(f"Could not resolve constant maturity alias '{original_cusip_alias}'")
            else:
                try:
                    resolved = _alias_to_cusip(original_cusip_alias, ref_df)
                    if resolved:
                        cusip = resolved
                except AssertionError:
                    raise  # surface "oi required"
                except Exception:
                    pass  # treat input as raw CUSIP

            row = ref_df[ref_df["cusip"] == cusip]
            if row.empty:
                raise KeyError(f"CUSIP {cusip} not present in reference set for {as_of_date}")
            meta_data = row.iloc[0].to_dict()

            if timestamp == "live":
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]
                live_ytm_quote = WSJFetcher().wsj_timeseries_api(wsj_ticker_keys=[wsj_key], append_most_recent_last=True)[wsj_key]
                meta_data["timestamp"] = live_ytm_quote.iloc[0, 0]
                return RLFixedRateBondPricer(
                    rl_frb_id="USTS",
                    reference_date=live_ytm_quote.iloc[0, 0].date(),
                    issue_date=meta_data["issue_date"],
                    maturity_date=meta_data["maturity_date"],
                    cpn=meta_data["cpn"],
                    ytm=live_ytm_quote.iloc[0, 1],
                    meta_data=meta_data,
                )

            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"

            cached = cache.get(cache_key)
            if cached is not None and not kwargs.get("force_refresh", False):
                if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                    return cached
                return self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

            ts_quote_df = _webull_fetch_with_proxy_fallback(
                cusips=[cusip],
                start=timestamp,
                end=timestamp,
                show_tqdm=False,
            )
            meta_data["timestamp"] = timestamp.isoformat()
            args = {
                "rl_frb_id": "USTS",
                "reference_date": ts_quote_df.index[0].date().isoformat(),
                "ytm": ts_quote_df.iloc[0, 0],
                "meta_data": self._pyify_meta(meta_data),
                "schema": 1,
                "source": cache_key,
            }
            cache[cache_key] = args
            # auto-committed (DiskCache)
            return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

    # ------------------------------------------------------------------
    # Cash spline construction (CORE: compute once, read everywhere)
    # ------------------------------------------------------------------
    def fetch_cash_spline(
        self,
        as_of_date: datetime.date,
        *,
        config: Optional["CashSplineConfig"] = None,
        cusips: Optional[List[str]] = None,
        force_refresh: bool = False,
        **kwargs,
    ) -> Optional["CashSpline"]:
        """Build (or retrieve from cache) a fitted cash spline for *as_of_date*.

        Parameters
        ----------
        as_of_date : date
            Valuation date.
        config : CashSplineConfig, optional
            Spline configuration.  Defaults to ``JPM_PAR_CURVE_CONFIG``.
        cusips : list[str], optional
            Restrict to these CUSIPs (after reference-data filtering).
            When *None*, uses all eligible CUSIPs from reference data.
        force_refresh : bool
            Bypass cache and refit.

        Returns
        -------
        CashSpline or None
        """
        from MDP.FixedRateBonds.cash_spline import (
            CashSpline,
            CashSplineBuilder,
            CashSplineConfig,
            JPM_PAR_CURVE_CONFIG,
            get_cached_spline,
            put_cached_spline,
        )

        if config is None:
            config = JPM_PAR_CURVE_CONFIG

        # --- Cache check ---
        if not force_refresh:
            cached = get_cached_spline(as_of_date, config)
            if cached is not None:
                return cached

        # --- Load reference data & pricers ---
        ref_df = self.get_bond_reference_data(as_of_date=as_of_date, kwargs=kwargs)
        if ref_df is None or ref_df.empty:
            _logger.warning("No reference data for %s", as_of_date)
            return None

        eligible_cusips = ref_df["cusip"].tolist() if "cusip" in ref_df.columns else []
        if cusips:
            eligible_cusips = [c for c in eligible_cusips if c in set(cusips)]
        if not eligible_cusips:
            _logger.warning("No eligible CUSIPs for spline on %s", as_of_date)
            return None

        # Fetch pricers for all eligible bonds
        pricers = self.get_data({
            "cusips": eligible_cusips,
            "timestamp": as_of_date,
            **kwargs,
        })
        if not pricers:
            _logger.warning("No pricers returned for %s", as_of_date)
            return None

        # --- Build bond data frame ---
        rows = []
        for cusip, pricer in pricers.items():
            try:
                ttm = float(pricer.time_to_maturity())
                ytm_val = float(pricer.ytm())
                meta = pricer.meta() if hasattr(pricer, "meta") else {}
                rank = None
                if isinstance(meta, dict):
                    rank = meta.get("rank")
                elif hasattr(meta, "rank"):
                    rank = meta.rank

                row = {
                    "cusip": cusip,
                    "ttm": ttm,
                    "ytm": ytm_val,
                }
                if rank is not None:
                    row["rank"] = rank

                # BPV weight = mod_dur * dirty_price / 10000
                try:
                    mdur = float(pricer.mod_duration())
                    dp = float(pricer.dirty_price())
                    row["bpv"] = mdur * dp / 10_000.0
                except Exception:
                    pass

                rows.append(row)
            except Exception:
                continue

        if not rows:
            _logger.warning("Could not extract bond data for spline on %s", as_of_date)
            return None

        bond_df = pd.DataFrame(rows)

        # Apply BPV weighting if configured
        import numpy as _np

        weights = None
        if config.weighting == "bpv" and "bpv" in bond_df.columns:
            bpv = bond_df["bpv"].to_numpy(dtype=float)
            bpv = _np.where(_np.isfinite(bpv) & (bpv > 0), bpv, _np.nan)
            # Weight = 1/BPV (normalize to yield-space)
            inv_bpv = 1.0 / bpv
            inv_bpv = _np.where(_np.isfinite(inv_bpv), inv_bpv, 0.0)
            if inv_bpv.sum() > 0:
                weights = inv_bpv / inv_bpv.sum()

        # --- Fit ---
        builder = CashSplineBuilder(config)
        try:
            spline = builder.fit(
                ttm=bond_df["ttm"].to_numpy(),
                y=bond_df["ytm"].to_numpy(),
                cusips=bond_df["cusip"].to_numpy(),
                ranks=bond_df["rank"].to_numpy() if "rank" in bond_df.columns else None,
                weights=weights,
                as_of_date=as_of_date,
            )
        except ValueError as exc:
            _logger.warning("Spline fit failed for %s: %s", as_of_date, exc)
            return None

        # --- Cache ---
        put_cached_spline(spline)
        return spline

    def bulk_fetch_cash_splines(
        self,
        dates: Sequence[datetime.date],
        *,
        config: Optional["CashSplineConfig"] = None,
        cusips: Optional[List[str]] = None,
        force_refresh: bool = False,
        max_workers: int = 4,
        show_tqdm: bool = False,
        **kwargs,
    ) -> Dict[datetime.date, Optional["CashSpline"]]:
        """Build splines for multiple dates (parallelized).

        Returns dict mapping each date to its fitted CashSpline (or None).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: Dict[datetime.date, Any] = {}
        dates_to_fetch = list(dates)

        def _fetch_one(d: datetime.date):
            return d, self.fetch_cash_spline(
                d, config=config, cusips=cusips,
                force_refresh=force_refresh, **kwargs,
            )

        iterator = dates_to_fetch
        if show_tqdm:
            try:
                iterator = tqdm.tqdm(dates_to_fetch, desc="Cash splines")
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_fetch_one, d): d for d in dates_to_fetch}
            for fut in as_completed(futs):
                try:
                    dt, spline = fut.result()
                    results[dt] = spline
                except Exception as exc:
                    results[futs[fut]] = None
                    _logger.warning("Spline build failed for %s: %s", futs[fut], exc)

        return results

    def get_bond_reference_data(self, as_of_date: datetime.date, kwargs={}):
        if kwargs.get("cme_tcf", None):
            from MDP.FixedRateBonds.reference_data_cache.cme_tcf import read_cme_tcf_with_headers

            return read_cme_tcf_with_headers(as_of=as_of_date)

        if self.source.upper() in ["USTS_FEDINVEST_WSJ_LIVE-QL", "USTS_WEBULL_WSJ_LIVE-RL"]:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import _fetch_fiscaldata

            return _fetch_fiscaldata(fetch_as_of=as_of_date, process_as_of=as_of_date, **kwargs)

    def _wsj_buffer_date(self) -> ql.Date:
        return ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(ql.Date.todaysDate(), ql.Period("-3D"))

    def _rl_prefetch_intraday(
        self,
        intraday_timestamps: List[datetime.datetime],
        symbols: List[str],
        *,
        force_refresh: bool = False,
        show_tqdm: bool = False,
    ) -> bool:
        """Pre-fetch Webull intraday data ONCE for all timestamps and populate the pricer cache.

        This avoids N redundant Webull HTTP fetches when bulk_get_data fans out
        timestamps to threads. Each thread then only does cheap cache lookups.

        Returns True if prefetch succeeded and cache was populated.
        """
        from pandas.tseries.offsets import BDay

        from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
        from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

        if not intraday_timestamps or not symbols:
            return False

        # Determine the date range we need to cover
        ny = pytz.timezone("America/New_York")
        all_dates = sorted(set(ts.date() for ts in intraday_timestamps))
        earliest_date = all_dates[0]
        latest_date = all_dates[-1]

        # Resolve aliases once (use the earliest timestamp as reference)
        ref_ts = intraday_timestamps[0]
        as_of_ref = ref_ts.date()
        ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
        ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)

        alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(symbols, ref_ts, ref_df=ref_df)
        unique_cusips = list(dict.fromkeys(alias_to_cusip.values()))

        if not unique_cusips:
            return False

        # Check if cache already has data for all timestamps (skip prefetch if so)
        if not force_refresh:
            self._ensure_pricer_cache()
            all_cached = True
            # Spot-check first, middle, last timestamps
            check_points = [intraday_timestamps[0]]
            if len(intraday_timestamps) > 2:
                check_points.append(intraday_timestamps[len(intraday_timestamps) // 2])
            check_points.append(intraday_timestamps[-1])
            for ts in check_points:
                for cusip in unique_cusips:
                    cache_key = f"{ts.isoformat()}-{cusip}-{self.source.upper()}"
                    if self._threadsafe_cache_get(cache_key) is None:
                        all_cached = False
                        break
                if not all_cached:
                    break
            if all_cached:
                _logger.info("RL prefetch: all spot-check timestamps already cached, skipping Webull fetch")
                return True

        # Single Webull fetch covering the full date range (with BDay padding)
        start_ny = ny.localize(datetime.datetime(earliest_date.year, earliest_date.month, earliest_date.day, 7, 0, 0)) - BDay(1)
        end_ny = ny.localize(datetime.datetime(latest_date.year, latest_date.month, latest_date.day, 17, 0, 0)) + BDay(1)

        _logger.info(
            "RL prefetch: fetching Webull intraday for %d cusips, %s → %s (covering %d timestamps)",
            len(unique_cusips), start_ny.isoformat(), end_ny.isoformat(), len(intraday_timestamps),
        )
        try:
            wide: pd.DataFrame = _webull_fetch_multi_proxy(
                cusips=unique_cusips,
                start=start_ny,
                end=end_ny,
                show_tqdm=show_tqdm,
                max_proxies=4,
                max_concurrent_per_proxy=64,
            )
        except Exception as ex:
            _logger.warning("RL prefetch: Webull fetch failed, falling back to per-timestamp: %s", ex)
            return False

        if wide is None or (hasattr(wide, "empty") and wide.empty):
            _logger.warning("RL prefetch: Webull returned empty DataFrame")
            return False

        # Populate the pricer cache for ALL data points in a single pass
        self._ensure_pricer_cache()
        write_count = 0
        for cusip in unique_cusips:
            if cusip not in wide.columns:
                continue
            series = wide[cusip].dropna()
            meta = meta_by_cusip.get(cusip, {})
            for curr_ts, ytm in series.items():
                args = {
                    "rl_frb_id": "USTS",
                    "reference_date": curr_ts.date().isoformat(),
                    "ytm": float(ytm),
                    "meta_data": self._pyify_meta({**meta, "timestamp": curr_ts.isoformat()}),
                    "schema": 1,
                    "source": f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}",
                }
                cache_key = f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}"
                self._threadsafe_cache_put(cache_key, args)
                write_count += 1

        _logger.info("RL prefetch: cached %d pricer entries for %d cusips", write_count, len(unique_cusips))
        return True

    def _citivelo_prefetch_range(
        self,
        *,
        timestamps: Sequence[DateLike],
        symbols: Sequence[str],
        force_refresh: bool = False,
    ) -> "_CitiVeloPrefetch":
        """Warm the Velocity tag cache for a whole range, EOD and intraday alike.

        The Velocity tag cache stores a whole SERIES per tag, not a row per
        instant, so fetching per point re-requests the same history once per
        point. One warm over ``[min, max]`` covers every point, and every
        subsequent per-point build is a cache read that opens no workbook. That
        matters beyond speed: the add-in's memory only ever grows and only a
        human restart clears it, so N workbook round trips for one backfill is
        the failure mode the ceiling exists to prevent.

        The two modes are warmed SEPARATELY, because they are different tag
        cliffs and different value sets
        -------------------------------------------------------------------
        EOD warms ``DAILY`` over ``[min_date, max_date]`` in one request, exactly
        as before. Its per-date reads stay online, and they cost nothing extra:
        ``CitiVeloBondFetcher._fetch_frame`` takes its CACHED branch for
        ``DAILY`` whatever the offline flag says, so a warm range is answered off
        disk and only the 21-day lookback head before ``min_date`` can reach
        Excel - once, on the first date, not once per date.

        INTRADAY is the case this method used to miss entirely, and missing it
        cost 500 s of ``time.sleep`` in a 593 s, 60-point profile. An intraday
        range prefetched nothing, so every point took ``_fetch_frame``'s ONLINE
        branch - ``windowed.fetch_windowed``, which talks to the COM client
        directly and therefore bypasses the tag cache in both directions. Warming
        it here means the per-point reads can be served offline; see
        :meth:`bulk_get_data`, which only does that when this reports success.

        ``MI01`` also has a measured downsampling cliff at 6 days, which the
        online chunker used to own. The warm goes through
        ``CitiVeloBondFetcher.prefetch`` -> ``windowed.warm_windows``, which
        bounds every request by it.

        Aliases are resolved at BOTH ends of the range
        ----------------------------------------------
        The old comment said earlier dates whose on-the-run differs are "still
        correct - ``_process_one`` re-resolves per date and any tag this missed is
        simply fetched then". That backstop is exactly what going offline
        removes: a missed tag is then an empty column, not a live call. So the
        union of the resolutions at the first and last date is warmed, and a
        range spanning an auction keeps both the old and the new on-the-run.

        Resolving at both ends is still only TWO days, which is right for a
        nightly range and wrong for a decade: over ten years the 28
        constant-maturity aliases pass through 597 bonds, so a two-day union warms
        a few dozen and every other date reads a tag nobody fetched. A deep
        backfill therefore warms its own constituent set first and then builds
        with this MDP ``offline`` - see
        ``scripts/citivelo_ust_timeseries_warm.py``.

        Skipped entirely when this MDP is configured ``offline``. That flag means
        "never open a workbook", and this is the one call on the path that would.

        Returns
        -------
        _CitiVeloPrefetch
            Tag count, and a per-mode flag that is True only when the warm
            actually put data in the cache.
        """
        from MDP.CitiVelocityExcel.bonds.fetcher import CitiVeloBondFetcher
        from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds
        from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
        from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import resolve_request

        if bool(self._citivelo_option("offline", default=False)):
            _logger.info("citivelo prefetch: skipped, this MDP is configured offline")
            return _CitiVeloPrefetch()

        eod_dates: List[datetime.date] = []
        intraday_instants: List[datetime.datetime] = []
        for ts in timestamps:
            if isinstance(ts, str) and ts.strip().lower() == "live":
                continue
            # resolve_request, not an isinstance ladder: pd.Timestamp subclasses
            # datetime subclasses date, so a ladder is wrong in both directions
            # and a midnight Timestamp means EOD. This is the same function the
            # per-point read decides its own mode with, so the two cannot
            # disagree about which bucket a timestamp is in.
            request = resolve_request(ts)
            if request.mode == "eod":
                eod_dates.append(request.eod_date)
            elif request.mode == "intraday":
                intraday_instants.append(request.wire_instant)

        if not eod_dates and not intraday_instants:
            return _CitiVeloPrefetch()

        all_dates = list(eod_dates) + [i.date() for i in intraday_instants]
        first, last = min(all_dates), max(all_dates)

        ref_raw = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
        cusips: List[str] = []
        for as_of in dict.fromkeys((last, first)):
            ref_df = _filter_and_rank_ref_df(ref_raw, as_of)
            alias_to_cusip, _ = self._resolve_aliases_bulk(list(symbols), as_of, ref_df=ref_df)
            cusips.extend(alias_to_cusip.values())
        if not cusips:
            return _CitiVeloPrefetch()

        resolved, failures = resolve_bonds(
            list(dict.fromkeys(cusips)),
            universe=self._citivelo_option("citivelo_universe"),
            strict=False,
        )
        for token, reason in failures.items():
            _logger.info("citivelo prefetch: %s not quoted by Citi, skipped (%s)", token, reason)
        if not resolved:
            return _CitiVeloPrefetch()

        fetcher = CitiVeloBondFetcher(values=self._citivelo_option("citivelo_values"))
        try:
            tags = 0
            eod_ok = intraday_ok = False
            if eod_dates:
                # lookback=0 keeps the DAILY request bounds byte-for-byte what
                # they were before intraday joined this method. The EOD per-date
                # read stays ONLINE, so it still tops up its own 21-day head;
                # widening the warm here would change the shape of the nightly
                # job's request for no measured gain.
                result = fetcher.prefetch(
                    list(resolved.values()), min(eod_dates), max(eod_dates),
                    mode="eod", lookback=datetime.timedelta(0),
                    force_refresh=force_refresh,
                )
                tags += len(result.tags)
                eod_ok = result.ok
            if intraday_instants:
                result = fetcher.prefetch(
                    list(resolved.values()), min(intraday_instants), max(intraday_instants),
                    mode="intraday", force_refresh=force_refresh,
                )
                tags += len(result.tags)
                intraday_ok = result.ok
            return _CitiVeloPrefetch(tags=tags, eod_ok=eod_ok, intraday_ok=intraday_ok)
        finally:
            fetcher.close()

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        cusips: Sequence[str],
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
    ) -> _BulkOut:
        # if not timestamps or not cusips:
        #     return {}

        # -------- helpers (mirror your existing patterns) --------
        def _clean_list(symbols: Iterable[str]) -> List[str]:
            out: List[str] = []
            for s in symbols:
                s = (s or "").strip()
                if "x" in s and "Ox" not in s:
                    out.extend([p for p in s.split("x") if p])
                elif "/" in s and not re.match(r"^\d{2}\d{2}/\d{1,2}$", s):
                    out.extend([p for p in s.split("/") if p])
                else:
                    out.append(s)
            return out

        def _is_live(ts: DateLike) -> bool:
            today = datetime.date.today()
            return (ts == "live") or (isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime) and ts == today)

        def _as_of_ref(ts: DateLike) -> datetime.date:
            return datetime.date.today() if ts == "live" else (ts.date() if isinstance(ts, datetime.datetime) else ts)

        def _ts_to_ql_date(ts: DateLike):
            if ts == "live":
                return ql.Date.todaysDate()
            if isinstance(ts, datetime.datetime):
                d = ts.date()
            else:
                d = ts
            return ql.Date(d.day, d.month, d.year)

        # Use open/close lifecycle.
        with self:
            out: _BulkOut = defaultdict(dict)

            # Pre-prepare per-timestamp jobs
            jobs: List[Tuple[DateLike, List[str]]] = []
            base_cusips = _clean_list(cusips)
            for ts in timestamps:
                jobs.append((ts, base_cusips))

            # ----------------------------------------------------------------
            # RL INTRADAY FAST PATH: pre-fetch Webull data ONCE for all
            # intraday datetime timestamps, populate the pricer cache in a
            # single pass, then let _process_one only do cheap cache lookups.
            # This avoids N redundant Webull HTTP fetches and the resulting
            # L2 cache write storm that caused queue overflow / hangs.
            # ----------------------------------------------------------------
            _rl_prefetched: bool = False
            if self.source.upper() == "USTS_WEBULL_WSJ_LIVE-RL":
                intraday_ts = [ts for ts in timestamps if isinstance(ts, datetime.datetime)]
                if intraday_ts and not all(_is_live(ts) for ts in intraday_ts):
                    _rl_prefetched = self._rl_prefetch_intraday(
                        intraday_timestamps=intraday_ts,
                        symbols=base_cusips,
                        force_refresh=force_refresh,
                        show_tqdm=show_tqdm,
                    )

            # ----------------------------------------------------------------
            # CITIVELO PREFETCH: one warm for the WHOLE range, then every
            # per-point build is a cache read with no Excel.
            #
            # Without this the loop below would open a workbook per point, which
            # is both slow and the thing the memory ceiling exists to avoid -
            # the add-in's memory only ever grows. The tag cache stores whole
            # series, so a per-point loop re-fetches the same history once per
            # point; one warm over [min, max] covers them all. It is also why a
            # real branch beats "just loop get_data" here.
            #
            # Failure is deliberately NOT fatal: a warm that already populated
            # the cache makes this a no-op, and a transport failure should
            # surface per point below (where it is classified) rather than as one
            # opaque error for the whole range.
            # ----------------------------------------------------------------
            _citivelo_prefetch = _CitiVeloPrefetch()
            if self.source.upper() in ("USTS_CITIVELO-QL", "USTS_CITIVELO-RL"):
                try:
                    _citivelo_prefetch = self._citivelo_prefetch_range(
                        timestamps=timestamps,
                        symbols=base_cusips,
                        force_refresh=force_refresh,
                    )
                except Exception as exc:  # noqa: BLE001 - reported, then retried per date
                    _logger.warning("citivelo bulk prefetch failed (%s); falling back to per-date reads", exc)
                    _citivelo_prefetch = _CitiVeloPrefetch()

            def _process_one(ts: DateLike, symbols: List[str]) -> Tuple[DateLike, Dict[str, "_FixedRateBondGenericPricer"]]:
                # --- alias resolution per timestamp ---
                from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

                as_of_ref = _as_of_ref(ts)
                ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
                ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)

                alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(symbols, ts, ref_df=ref_df)

                result: Dict[str, "_FixedRateBondGenericPricer"] = {}

                # -------------------- QL path (FedInvest/WSJ) --------------------
                if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-QL":
                    from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
                    from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

                    is_live = _is_live(ts)
                    wsj_buffer = self._wsj_buffer_date()
                    ts_qldate = _ts_to_ql_date(ts)
                    in_wsj_buffer = ts_qldate > wsj_buffer

                    if is_live:
                        wsj = WSJFetcher()
                        live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                        for original, cusip in alias_to_cusip.items():
                            try:
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = live_data[cusip]["timestamp"]
                                result[original] = QLFixedRateBondPricer(
                                    ql_frb_id="USTS",
                                    reference_date=live_data[cusip]["timestamp"].date(),
                                    issue_date=meta["issue_date"],
                                    maturity_date=meta["maturity_date"],
                                    cpn=meta["cpn"],
                                    ytm=float(live_data[cusip]["ytm"]),
                                    meta_data=meta,
                                )
                            except Exception:
                                pass
                        return ts, result

                    if in_wsj_buffer:
                        # FedInvest-first: try ground-truth EOD before WSJ intraday
                        alias_to_wsj_ql = dict(alias_to_cusip)
                        timestamp_dt = datetime.datetime(as_of_ref.year, as_of_ref.month, as_of_ref.day)
                        try:
                            fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh)
                            fi_df = fi_map.get(timestamp_dt)
                            if fi_df is not None and not fi_df.empty:
                                fi_df_idx = fi_df.set_index("cusip")
                                self._ensure_pricer_cache()
                                cache = getattr(self, self._FRB_PRICER_CACHE)
                                for original, cusip in list(alias_to_wsj_ql.items()):
                                    if cusip in fi_df_idx.index:
                                        clean_price = float(fi_df_idx.loc[cusip]["eod_price"])
                                        if not (50.0 <= clean_price <= 250.0):
                                            continue
                                        meta = self._pyify_meta(meta_by_cusip[cusip])
                                        args = {
                                            "ql_frb_id": "USTS",
                                            "reference_date": as_of_ref.isoformat(),
                                            "clean_price": clean_price,
                                            "meta_data": meta,
                                            "schema": 2,
                                            "source": "fedinvest",
                                        }
                                        cache_key = f"{as_of_ref.isoformat()}-{cusip}-{self.source.upper()}"
                                        self._threadsafe_cache_put(cache_key, args)
                                        result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                                        del alias_to_wsj_ql[original]
                        except Exception:
                            pass

                        # WSJ fallback for cusips FedInvest didn't cover
                        if alias_to_wsj_ql:
                            wsj = WSJFetcher()
                            mapping = {get_isin_from_cusip(c, "US")[2:]: c for c in alias_to_wsj_ql.values()}
                            wide = wsj.ust_intraday_timeseries(mapping, show_tqdm=show_tqdm)

                            est = pytz.timezone("America/New_York")
                            assert isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime)
                            t_3pm = est.localize(datetime.datetime(ts.year, ts.month, ts.day, 15, 0, 0)).astimezone(pytz.UTC)
                            idx = wide.index
                            pos = idx.get_indexer([t_3pm], method="nearest")[0]
                            nearest_ts = idx[pos]
                            if abs(nearest_ts - t_3pm) > pd.Timedelta("120min"):
                                raise ValueError("No intraday snapshot within 120min of 3pm ET")

                            for original, cusip in alias_to_wsj_ql.items():
                                try:
                                    y = wide[cusip].iloc[pos]
                                    if pd.isna(y):
                                        col = wide[cusip].dropna()
                                        if col.empty:
                                            raise ValueError(f"No intraday data for {cusip} near 3pm")
                                        nearest_ts = col.index[col.index.get_indexer([t_3pm], method="nearest")[0]]
                                        y = col.loc[nearest_ts]
                                    meta = dict(meta_by_cusip[cusip])
                                    meta["timestamp"] = nearest_ts
                                    result[original] = QLFixedRateBondPricer(
                                        ql_frb_id="USTS",
                                        reference_date=nearest_ts.date(),
                                        issue_date=meta["issue_date"],
                                        maturity_date=meta["maturity_date"],
                                        cpn=meta["cpn"],
                                        ytm=float(y),
                                        meta_data=meta,
                                    )
                                except Exception:
                                    pass
                        return ts, result

                    # Historical daily close via FedInvest
                    from pandas.tseries.offsets import BDay

                    timestamp_dt = datetime.datetime(as_of_ref.year, as_of_ref.month, as_of_ref.day)

                    self._ensure_pricer_cache()
                    cache = getattr(self, self._FRB_PRICER_CACHE)

                    # One FedInvest snapshot per date; then fill pricers
                    fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh)
                    fi_df = fi_map.get(timestamp_dt)
                    if fi_df is None or fi_df.empty:
                        raise KeyError(f"No FedInvest snapshot for {as_of_ref} (key: {timestamp_dt})")

                    fi_df = fi_df.set_index("cusip")

                    from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

                    for original, cusip in alias_to_cusip.items():
                        try:
                            clean_price = float(fi_df.loc[cusip]["eod_price"])
                        except Exception:
                            continue

                        meta = self._pyify_meta(meta_by_cusip[cusip])
                        args = {
                            "ql_frb_id": "USTS",
                            "reference_date": as_of_ref.isoformat(),
                            "clean_price": clean_price,
                            "meta_data": meta,
                            "schema": 1,
                            "source": "fedinvest",
                        }
                        cache_key = f"{as_of_ref.isoformat()}-{cusip}-{self.source.upper()}"
                        self._threadsafe_cache_put(cache_key, args)  # guarded writer
                        result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    return ts, result

                # -------------------- RL path (FedInvest/WSJ) --------------------
                elif self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-RL":
                    from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
                    from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

                    is_live = _is_live(ts)
                    wsj_buffer = self._wsj_buffer_date()
                    ts_qldate = _ts_to_ql_date(ts)
                    in_wsj_buffer = ts_qldate > wsj_buffer

                    if is_live:
                        wsj = WSJFetcher()
                        live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                        for original, cusip in alias_to_cusip.items():
                            try:
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = live_data[cusip]["timestamp"]
                                result[original] = RLFixedRateBondPricer(
                                    rl_frb_id="USTS",
                                    reference_date=live_data[cusip]["timestamp"].date(),
                                    issue_date=meta["issue_date"],
                                    maturity_date=meta["maturity_date"],
                                    cpn=meta["cpn"],
                                    ytm=float(live_data[cusip]["ytm"]),
                                    meta_data=meta,
                                )
                            except Exception:
                                pass
                        return ts, result

                    if in_wsj_buffer:
                        # FedInvest-first: try ground-truth EOD before WSJ intraday
                        alias_to_wsj = dict(alias_to_cusip)
                        timestamp_dt = datetime.datetime(as_of_ref.year, as_of_ref.month, as_of_ref.day)
                        try:
                            fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh)
                            fi_df = fi_map.get(timestamp_dt)
                            if fi_df is not None and not fi_df.empty:
                                fi_df_idx = fi_df.set_index("cusip")
                                self._ensure_pricer_cache()
                                cache = getattr(self, self._FRB_PRICER_CACHE)
                                for original, cusip in list(alias_to_wsj.items()):
                                    if cusip in fi_df_idx.index:
                                        clean_price = float(fi_df_idx.loc[cusip]["eod_price"])
                                        if not (50.0 <= clean_price <= 250.0):
                                            continue
                                        meta = self._pyify_meta(meta_by_cusip[cusip])
                                        args = {
                                            "rl_frb_id": "USTS",
                                            "reference_date": as_of_ref.isoformat(),
                                            "clean_price": clean_price,
                                            "meta_data": meta,
                                            "schema": 2,
                                            "source": "fedinvest",
                                        }
                                        cache_key = f"{as_of_ref.isoformat()}-{cusip}-{self.source.upper()}"
                                        self._threadsafe_cache_put(cache_key, args)
                                        result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                                        del alias_to_wsj[original]
                        except Exception:
                            pass

                        # WSJ fallback for cusips FedInvest didn't cover
                        if alias_to_wsj:
                            wsj = WSJFetcher()
                            mapping = {get_isin_from_cusip(c, "US")[2:]: c for c in alias_to_wsj.values()}
                            wide = wsj.ust_intraday_timeseries(mapping, show_tqdm=show_tqdm)

                            est = pytz.timezone("America/New_York")
                            assert isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime)
                            t_3pm = est.localize(datetime.datetime(ts.year, ts.month, ts.day, 15, 0, 0)).astimezone(pytz.UTC)
                            idx = wide.index
                            pos = idx.get_indexer([t_3pm], method="nearest")[0]
                            nearest_ts = idx[pos]
                            if abs(nearest_ts - t_3pm) > pd.Timedelta("120min"):
                                raise ValueError("No intraday snapshot within 120min of 3pm ET")

                            for original, cusip in alias_to_wsj.items():
                                try:
                                    y = wide[cusip].iloc[pos]
                                    if pd.isna(y):
                                        col = wide[cusip].dropna()
                                        if col.empty:
                                            raise ValueError(f"No intraday data for {cusip} near 3pm")
                                        nearest_ts = col.index[col.index.get_indexer([t_3pm], method="nearest")[0]]
                                        y = col.loc[nearest_ts]
                                    meta = dict(meta_by_cusip[cusip])
                                    meta["timestamp"] = nearest_ts
                                    result[original] = RLFixedRateBondPricer(
                                        rl_frb_id="USTS",
                                        reference_date=nearest_ts.date(),
                                        issue_date=meta["issue_date"],
                                        maturity_date=meta["maturity_date"],
                                        cpn=meta["cpn"],
                                        ytm=float(y),
                                        meta_data=meta,
                                    )
                                except Exception:
                                    pass
                        return ts, result

                    # Historical daily close via FedInvest
                    from pandas.tseries.offsets import BDay

                    timestamp_dt = datetime.datetime(as_of_ref.year, as_of_ref.month, as_of_ref.day)

                    self._ensure_pricer_cache()
                    cache = getattr(self, self._FRB_PRICER_CACHE)

                    fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh)
                    fi_df = fi_map.get(timestamp_dt)
                    if fi_df is None or fi_df.empty:
                        raise KeyError(f"No FedInvest snapshot for {as_of_ref} (key: {timestamp_dt})")

                    fi_df = fi_df.set_index("cusip")

                    for original, cusip in alias_to_cusip.items():
                        try:
                            clean_price = float(fi_df.loc[cusip]["eod_price"])
                        except Exception:
                            continue

                        meta = self._pyify_meta(meta_by_cusip[cusip])
                        args = {
                            "rl_frb_id": "USTS",
                            "reference_date": as_of_ref.isoformat(),
                            "clean_price": clean_price,
                            "meta_data": meta,
                            "schema": 2,
                            "source": "fedinvest",
                        }
                        cache_key = f"{as_of_ref.isoformat()}-{cusip}-{self.source.upper()}"
                        self._threadsafe_cache_put(cache_key, args)
                        result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    return ts, result

                # -------------------- RL path (Webull/WSJ live) --------------------
                elif self.source.upper() == "USTS_WEBULL_WSJ_LIVE-RL":
                    from pandas.tseries.offsets import BDay

                    from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
                    from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher
                    from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

                    is_live = _is_live(ts)
                    if is_live:
                        wsj = WSJFetcher()
                        live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                        for original, cusip in alias_to_cusip.items():
                            try:
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = live_data[cusip]["timestamp"]
                                result[original] = RLFixedRateBondPricer(
                                    rl_frb_id="USTS",
                                    reference_date=live_data[cusip]["timestamp"].date(),
                                    issue_date=meta["issue_date"],
                                    maturity_date=meta["maturity_date"],
                                    cpn=meta["cpn"],
                                    ytm=float(live_data[cusip]["ytm"]),
                                    meta_data=meta,
                                )
                            except Exception:
                                pass
                        return ts, result

                    # non-live intraday: try cache first, then batch fetch via Webull
                    self._ensure_pricer_cache()
                    cache = getattr(self, self._FRB_PRICER_CACHE)
                    to_fetch: "OrderedDict[str, str]" = OrderedDict()

                    # exact ts is required (your RL branch keys on exact timestamp)
                    if isinstance(ts, datetime.datetime):
                        # When _rl_prefetched is True, the prefetch already did a
                        # fresh Webull fetch and populated the cache — trust it even
                        # when force_refresh is set to avoid redundant HTTP calls.
                        _trust_cache = (not force_refresh) or _rl_prefetched

                        # Check for cached pricers/args under both (cusip, original)
                        for original, cusip in alias_to_cusip.items():
                            hit = None
                            for key_c in (cusip, original):
                                cache_key = f"{ts.isoformat()}-{key_c}-{self.source.upper()}"
                                hit = self._threadsafe_cache_get(cache_key)
                                if hit is not None:
                                    break
                            if hit is not None and _trust_cache:
                                # build pricer whether cached object or args
                                if hasattr(hit, "__class__") and hit.__class__.__name__ == "RLFixedRateBondPricer":
                                    result[original] = hit  # already a pricer
                                else:
                                    result[original] = self._build_pricer_from_args(
                                        hit, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                                    )
                            else:
                                to_fetch[original] = cusip

                        if not to_fetch:
                            return ts, result

                        # Batch fetch all needed cusips around the day, then fill cache for *all* points
                        ny = pytz.timezone("America/New_York")
                        start_ny = ny.localize(datetime.datetime(ts.year, ts.month, ts.day, 7, 0, 0)) - BDay(1)
                        end_ny = ny.localize(datetime.datetime(ts.year, ts.month, ts.day, 17, 0, 0)) + BDay(1)

                        wide: pd.DataFrame = _webull_fetch_with_proxy_fallback(
                            cusips=list(to_fetch.values()),
                            start=start_ny,
                            end=end_ny,
                            show_tqdm=show_tqdm,
                        )

                        # Persist all timeslices to cache (same scheme as your RL branch)
                        for original, cusip in to_fetch.items():
                            if cusip not in wide.columns:
                                continue
                            series = wide[cusip].dropna()
                            for curr_ts, ytm in series.items():
                                args = {
                                    "rl_frb_id": "USTS",
                                    "reference_date": curr_ts.date().isoformat(),
                                    "ytm": float(ytm),
                                    "meta_data": self._pyify_meta({**meta_by_cusip[cusip], "timestamp": curr_ts.isoformat()}),
                                    "schema": 1,
                                    "source": f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}",
                                }
                                cache_key = f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}"
                                self._threadsafe_cache_put(cache_key, args)

                            # Return the exact request point if present; else leave missing
                            if ts in series.index:
                                curr_ts = ts
                                ytm = float(series.loc[curr_ts])
                                args = {
                                    "rl_frb_id": "USTS",
                                    "reference_date": curr_ts.date().isoformat(),
                                    "ytm": ytm,
                                    "meta_data": self._pyify_meta({**meta_by_cusip[cusip], "timestamp": curr_ts.isoformat()}),
                                    "schema": 1,
                                    "source": f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}",
                                }
                                result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

                        # auto-committed (DiskCache)
                        return ts, result

                    # If we got here, user passed a date (not datetime) for RL non-live; no canonical source
                    # for an RL daily close in your repo; we’ll just raise to match your existing semantics.
                    raise NotImplementedError("For RL, pass an intraday datetime for timestamp or ‘live’.")

                # -------------------- Citi Velocity --------------------
                # The batched historical read this wants is one warm for the
                # whole range, which _citivelo_prefetch_range has already done
                # above; every call here is then a tag-cache read with no Excel.
                # Delegating to _get_multi_pricers keeps ONE implementation of
                # the resolution, provenance and staleness rules rather than a
                # second copy that drifts.
                #
                # OFFLINE for intraday, and only once the warm has actually put
                # data in the cache. This is the flag that closes the read path:
                # _fetch_frame takes its cached branch when the freq is DAILY *or*
                # the fetcher is offline, so without it an intraday point goes to
                # windowed.fetch_windowed, which takes the COM client directly and
                # bypasses the tag cache in both directions - one live Excel round
                # trip per minute bar, measured at 500 s of sleep over 60 points.
                #
                # EOD is deliberately left online: its cached branch is taken on
                # the freq alone, so it is already served from disk, and the flag
                # would only stop it topping up the 21-day head it legitimately
                # needs on the first date of a range.
                elif self.source.upper() in ("USTS_CITIVELO-QL", "USTS_CITIVELO-RL"):
                    from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import resolve_request

                    ts_kwargs: Dict[str, Any] = {"force_refresh": force_refresh}
                    if _citivelo_prefetch.intraday_ok and resolve_request(ts).mode == "intraday":
                        ts_kwargs["offline"] = True
                    return ts, (self._get_multi_pricers(
                        cusips=symbols, timestamp=ts, kwargs=ts_kwargs,
                    ) or {})

                # -------------------- Unsupported source --------------------
                # USTS_TRADINGVIEW-* still has no branch here, so a UnifiedQuery
                # TIMESERIES over it raises from this line. It fails loudly
                # rather than silently, and _get_multi_pricers per date is the
                # working route.
                else:
                    raise NotImplementedError(f"Unsupported source {self.source}")

            # -------- RL FAST PATH: build pricers directly from prefetched cache --------
            if _rl_prefetched:
                from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

                # Resolve aliases ONCE (not per-timestamp)
                ref_ts0 = timestamps[0]
                as_of_ref = _as_of_ref(ref_ts0)
                ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
                ref_df = _filter_and_rank_ref_df(ref_df, as_of_ref)
                alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(base_cusips, ref_ts0, ref_df=ref_df)

                self._ensure_pricer_cache()
                cache = getattr(self, self._FRB_PRICER_CACHE)
                hit_count = 0
                miss_count = 0
                skipped_count = 0

                # Filter timestamps to valid Webull session hours (7:00-17:00 ET)
                # to avoid pointless cache lookups for overnight timestamps.
                _session_open = datetime.time(7, 0)
                _session_close = datetime.time(17, 0)
                ny = pytz.timezone("America/New_York")

                def _in_session(ts):
                    if not isinstance(ts, datetime.datetime):
                        return True  # dates always valid
                    t = ts.astimezone(ny).time() if ts.tzinfo else ts.time()
                    return _session_open <= t <= _session_close

                valid_timestamps = []
                for ts in timestamps:
                    if not isinstance(ts, datetime.datetime) or _is_live(ts):
                        # Non-intraday or live — fall through to _process_one
                        out[ts].update(_process_one(ts, base_cusips)[1])
                    elif _in_session(ts):
                        valid_timestamps.append(ts)
                    else:
                        skipped_count += 1

                if skipped_count:
                    _logger.info(
                        "RL fast path: skipped %d timestamps outside session (%s-%s ET), %d valid",
                        skipped_count, _session_open, _session_close, len(valid_timestamps),
                    )

                # Batch cache reads: read all keys at once, then build pricers
                source_upper = self.source.upper()
                alias_items = list(alias_to_cusip.items())

                # Pre-read all cache keys in one pass per alias
                ts_args: list[tuple[DateLike, str, dict]] = []  # (ts, original, args_dict)
                for original, cusip in alias_items:
                    keys = [f"{ts.isoformat()}-{cusip}-{source_upper}" for ts in valid_timestamps]
                    for ts, key in zip(valid_timestamps, keys):
                        hit = cache.get(key)
                        if hit is not None:
                            if hasattr(hit, "__class__") and hit.__class__.__name__ == "RLFixedRateBondPricer":
                                out[ts][original] = hit
                            else:
                                ts_args.append((ts, original, hit))
                            hit_count += 1
                        else:
                            miss_count += 1

                # Parallelize pricer construction from args dicts
                if ts_args:
                    def _build(item):
                        ts, original, args = item
                        return ts, original, self._build_pricer_from_args(
                            args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                        )

                    build_workers = min(max_workers, len(ts_args))
                    if build_workers > 1:
                        with ThreadPoolExecutor(max_workers=build_workers, thread_name_prefix="frb-build") as pool:
                            build_iter = pool.map(_build, ts_args, chunksize=max(1, len(ts_args) // (build_workers * 4)))
                            if show_tqdm:
                                build_iter = tqdm.tqdm(build_iter, total=len(ts_args), desc="BUILDING PRICERS FROM CACHE")
                            for ts, original, pricer in build_iter:
                                out[ts][original] = pricer
                    else:
                        build_iter = ((_build(item) for item in ts_args))
                        if show_tqdm:
                            build_iter = tqdm.tqdm(build_iter, total=len(ts_args), desc="BUILDING PRICERS FROM CACHE")
                        for ts, original, pricer in build_iter:
                            out[ts][original] = pricer

                _logger.info(
                    "RL fast path: %d cache hits, %d misses, %d skipped (out-of-session) across %d timestamps",
                    hit_count, miss_count, skipped_count, len(timestamps),
                )
                return dict(out)

            # -------- fan out (timestamp-level) with threads --------
            results: List[Tuple[DateLike, Dict[str, "_FixedRateBondGenericPricer"]]] = []
            if max_workers == 1 or len(jobs) == 1:
                iterable = jobs
                if show_tqdm:
                    iterable = tqdm.tqdm(iterable, desc="FETCHING PRICERS")
                for ts, syms in iterable:
                    results.append(_process_one(ts, syms))
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="frb-mdp") as pool:
                    futures = {pool.submit(_process_one, ts, syms): (ts, syms) for ts, syms in jobs}
                    iterator = as_completed(futures)
                    if show_tqdm:
                        iterator = tqdm.tqdm(iterator, total=len(futures), desc="FETCHING PRICERS")
                    for fut in iterator:
                        results.append(fut.result())

            for ts, res in results:
                if res:
                    out[ts].update(res)

            return dict(out)

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
                        self._flush_pending_cache_writes()
                finally:
                    try:
                        self.close_cache()
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
