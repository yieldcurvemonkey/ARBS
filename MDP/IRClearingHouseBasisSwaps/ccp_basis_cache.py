"""Disk cache + panel builder for the CME-vs-LCH (CCP) swap basis.

Data source
-----------
GS Quant dataset ``IR_SWAP_RATES_V1_STANDARD``.  Assets are resolved offline
against ``MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx``.
Exactly three ``(ccy, index)`` pairs carry both an LCH- and a CME-cleared asset:
``USD SOFR``, ``USD OIS``, ``USD LIBOR``.

What is cached
--------------
**Per-leg rates, never the difference.**  One key per
``(ccy, index, tenor, clearing_house, date)`` holding the rate *exactly as the
wire serves it* -- a **decimal** fraction (a 10y print is ``0.04288489``, i.e.
4.288489%).  The basis is formed in exactly one place, :func:`basis_panel`, so a
sign or unit error has a single site to go wrong in and a single test to catch
it.

Sign convention
---------------
``basis = rate[long_ch] - rate[short_ch]``, in **basis points**, with defaults
``long_ch="LCH"`` and ``short_ch="CME"``.  So the published panel is

    **LCH minus CME, in bp.  Negative means LCH is the cheaper (lower) fixed rate.**

Measured ground truth (USD SOFR 10y, 2026-08-10, one ``Dataset.get_data``):

    LCH = 0.04288489,  CME = 0.04308489  ->  LCH - CME = -2.0000 bp

:data:`SIGN_REFERENCE` freezes those two numbers and
:func:`verify_sign_convention` re-derives ``-2.0`` through the same arithmetic
helper the panel uses.  :func:`basis_panel` calls it on every build, so flipping
the subtraction raises instead of silently returning a negated panel.

Warm markers
------------
A key miss is ambiguous on its own: it can mean "cold cache" or "the CCP did not
publish that day" (LCH prints on ~62 more days than CME over 2018-2026 -- US
holidays).  Every leg therefore carries a ``warm|...`` marker listing the date
spans that have actually been fetched.  Reads outside a warm span raise
:class:`CCPBasisCacheMiss` rather than returning a hole dressed up as data.

Network
-------
:meth:`CCPBasisCache.warm` is the only method that touches the network, and it
must be asked explicitly (``allow_network=True`` on the panel path, which
defaults to ``False``).  One warm = one OAuth token request + one dataset query
+ two bookkeeping requests gs_quant issues on its own = 4 HTTP calls, regardless
of how many assets or dates are requested.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from Caching.DiskCacheMixin import DiskCacheMixin

__all__ = [
    "CCPBasisCache",
    "CCPBasisCacheMiss",
    "basis_panel",
    "default_coverage_path",
    "verify_sign_convention",
    "SIGN_REFERENCE",
    "SPOT_TENOR_LADDER",
    "DUAL_CLEARED_PAIRS",
]

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

DATASET_ID = "IR_SWAP_RATES_V1_STANDARD"
CACHE_NAME = "GSQUANT_CH_BASIS_v1"

#: Spot ladder available at both CCPs for USD SOFR (verified against the
#: offline catalogue; ``0b`` forward start).
SPOT_TENOR_LADDER: Tuple[str, ...] = (
    "1y", "2y", "3y", "4y", "5y", "7y", "10y", "15y", "20y", "25y", "30y",
)

#: ``(ccy, index)`` pairs that carry BOTH an LCH and a CME asset.
DUAL_CLEARED_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("USD", "SOFR"),
    ("USD", "OIS"),
    ("USD", "LIBOR"),
)

#: Frozen wire values used to pin the sign.  Measured 2026-08-20 from a single
#: ``Dataset.get_data`` over IR_SWAP_RATES_V1_STANDARD.
SIGN_REFERENCE: Dict[str, Any] = {
    "date": "2026-08-10",
    "ccy": "USD",
    "index": "SOFR",
    "tenor": "10y",
    "rate_lch": 0.04288489,
    "rate_cme": 0.04308489,
    "lch_minus_cme_bp": -2.0,
}

# ``USD Swap SOFR 1y ATM 0b to 10y LCH Cleared``
_NAME_RX = re.compile(
    r"^(?P<ccy>\w+)\s+Swap\s+(?P<index>\S+)\s+(?P<freq>\S+)\s+ATM\s+"
    r"(?P<start>\S+)\s+to\s+(?P<tenor>\S+)\s+(?P<clearing_house>\w+)\s+Cleared$"
)


class CCPBasisCacheMiss(LookupError):
    """Raised when a requested window is not warm in the disk cache."""


# ---------------------------------------------------------------------------
# arithmetic -- the ONLY place a basis is formed
# ---------------------------------------------------------------------------


def _basis_bp(rate_long: Any, rate_short: Any) -> Any:
    """``long`` leg minus ``short`` leg, decimal rates in, basis points out."""
    return (rate_long - rate_short) * 10_000.0


def verify_sign_convention() -> float:
    """Re-derive the frozen reference through :func:`_basis_bp`.

    Returns the measured ``LCH - CME`` in bp for the reference date.  Raises
    ``AssertionError`` if the arithmetic no longer reproduces it -- which is
    what a flipped subtraction or a decimal/percent mix-up looks like.
    """
    got = _basis_bp(SIGN_REFERENCE["rate_lch"], SIGN_REFERENCE["rate_cme"])
    want = SIGN_REFERENCE["lch_minus_cme_bp"]
    if abs(got - want) > 1e-6:
        raise AssertionError(
            f"CCP basis sign/unit convention broken: LCH-CME for "
            f"{SIGN_REFERENCE['tenor']} on {SIGN_REFERENCE['date']} should be "
            f"{want:+.4f} bp, got {got:+.4f} bp"
        )
    if not got < 0:
        raise AssertionError("reference basis must be negative (LCH below CME)")
    return got


# ---------------------------------------------------------------------------
# coverage catalogue (offline)
# ---------------------------------------------------------------------------


def default_coverage_path() -> Path:
    """Resolve the coverage workbook from *this module's* location.

    ``MDP/IRClearingHouseBasisSwaps/ccp_basis_cache.py``
      -> parents[1] == ``MDP``
      -> ``MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx``

    The previous hard-coded absolute path pointed at a different checkout, so a
    worktree silently read another tree's catalogue.
    """
    return (
        Path(__file__).resolve().parents[1]
        / "IRSwaps"
        / "GSQUANT"
        / "COVERAGE"
        / f"{DATASET_ID}_COVERAGE.xlsx"
    )


def load_coverage(coverage_path: Optional[Any] = None) -> pd.DataFrame:
    """Parsed catalogue: one row per recognisable swap-rate asset."""
    path = Path(coverage_path) if coverage_path is not None else default_coverage_path()
    raw = pd.read_excel(path)
    recs: List[Dict[str, Any]] = []
    for asset_id, name, hist in zip(raw["assetId"], raw["name"], raw.get("historyStartDate", [None] * len(raw))):
        m = _NAME_RX.match(str(name))
        if m is None:
            continue
        d = m.groupdict()
        recs.append(
            {
                "assetId": asset_id,
                "name": name,
                "ccy": d["ccy"].upper(),
                "index": d["index"].upper(),
                "freq": d["freq"],
                "start": d["start"],
                "tenor": d["tenor"],
                "clearing_house": d["clearing_house"].upper(),
                "historyStartDate": hist,
            }
        )
    return pd.DataFrame.from_records(recs)


def _split_tenor(tenor: str) -> Tuple[str, str]:
    """``"5yx10y" -> ("5y", "10y")``;  ``"10y" -> ("0b", "10y")`` (spot start)."""
    t = str(tenor).strip()
    if "x" in t.lower():
        fwd, _, tail = t.lower().partition("x")
        return fwd, tail
    return "0b", t


def find_asset(
    coverage: pd.DataFrame,
    ccy: str,
    index: str,
    tenor: str,
    clearing_house: str,
) -> str:
    """Exact-match one asset id.  Raises on 0 or >1 match.

    The predecessor matched the tenor as a *substring* of the asset name and let
    the last row win, so ``tenor="5y"`` resolved to the 15y asset and
    ``tenor="1y"`` resolved to LCH-30y against CME-12y -- a curve spread served
    as a CCP basis.  Ambiguity is an error here, never a silent pick.
    """
    fwd, mat = _split_tenor(tenor)
    hit = coverage[
        (coverage["ccy"] == str(ccy).upper())
        & (coverage["index"] == str(index).upper())
        & (coverage["start"].str.lower() == fwd.lower())
        & (coverage["tenor"].str.lower() == mat.lower())
        & (coverage["clearing_house"] == str(clearing_house).upper())
    ]
    if len(hit) == 0:
        raise ValueError(
            f"No {clearing_house} asset for {ccy} {index} {tenor} "
            f"(start={fwd!r}, tenor={mat!r}) in the coverage catalogue."
        )
    if len(hit) > 1:
        raise ValueError(
            f"Ambiguous {clearing_house} asset for {ccy} {index} {tenor}: "
            f"{len(hit)} matches -> {hit['name'].tolist()}"
        )
    return str(hit["assetId"].iloc[0])


def find_asset_pair(
    coverage: pd.DataFrame,
    ccy: str,
    index: str,
    tenor: str,
    clearing_house_a: str = "LCH",
    clearing_house_b: str = "CME",
) -> Dict[str, str]:
    """Exact-match both legs.  ``asset_id_a`` is ``clearing_house_a``'s asset."""
    return {
        "asset_id_a": find_asset(coverage, ccy, index, tenor, clearing_house_a),
        "asset_id_b": find_asset(coverage, ccy, index, tenor, clearing_house_b),
    }


# ---------------------------------------------------------------------------
# warm-span bookkeeping
# ---------------------------------------------------------------------------


def _as_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return pd.Timestamp(value).date()


def _merge_spans(spans: Iterable[Sequence[str]]) -> List[List[str]]:
    """Union of ISO date spans; touching or overlapping spans coalesce.

    Adjacency is *one calendar day*, so two fetches that abut across a weekend
    still merge, while a genuine gap stays a gap -- the point being that a read
    across a gap must miss, not be waved through.
    """
    norm = sorted(([_as_date(a), _as_date(b)] for a, b in spans), key=lambda s: s[0])
    out: List[List[datetime.date]] = []
    for lo, hi in norm:
        if out and lo <= out[-1][1] + datetime.timedelta(days=1):
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [[lo.isoformat(), hi.isoformat()] for lo, hi in out]


def _covered(spans: Iterable[Sequence[str]], start: datetime.date, end: datetime.date) -> bool:
    return any(_as_date(a) <= start and _as_date(b) >= end for a, b in spans)


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------


class CCPBasisCache(DiskCacheMixin):
    """Disk cache of per-leg cleared swap rates.

    Layout under ``%LOCALAPPDATA%/ARBS/Cache/diskcache/dump/GSQUANT_CH_BASIS_v1``:

    ==============================================  ==========================
    key                                             value
    ==============================================  ==========================
    ``rate|USD|SOFR|10y|LCH|2026-08-10``            ``0.04288489`` (decimal)
    ``warm|USD|SOFR|10y|LCH``                       ``[["2018-01-01", ...]]``
    ==============================================  ==========================
    """

    _CACHE_ATTR = "_ccp_cache"

    def __init__(
        self,
        coverage_path: Optional[Any] = None,
        gs_client_id: Optional[str] = None,
        gs_secret_key: Optional[str] = None,
        cache_name: str = CACHE_NAME,
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(force_refresh=force_refresh, **kwargs)
        self._coverage_path = Path(coverage_path) if coverage_path is not None else default_coverage_path()
        self._gs_client_id = gs_client_id
        self._gs_secret_key = gs_secret_key
        self._cache_name = cache_name
        self._coverage: Optional[pd.DataFrame] = None
        self.http_calls = 0  # cumulative outbound requests made by this instance

    # -- plumbing ---------------------------------------------------------

    @property
    def coverage_path(self) -> Path:
        return self._coverage_path

    def coverage(self) -> pd.DataFrame:
        if self._coverage is None:
            self._coverage = load_coverage(self._coverage_path)
        return self._coverage

    def _ensure_cache(self):
        # default_cache_path() honours DiskCacheMixin.CACHE_ROOT, which tests
        # point at a tmp dir; resolve it on every call so a mid-session
        # CACHE_ROOT change is not silently ignored.
        path = DiskCacheMixin.default_cache_path(self._cache_name)
        if getattr(self, "_dc_caches", {}).get(self._CACHE_ATTR) not in (None, path):
            self.close_cache()
        self.open_cache(cache_attr=self._CACHE_ATTR, path=path, encode=None, decode=None)
        return getattr(self, self._CACHE_ATTR)

    @property
    def cache_dir(self) -> str:
        return DiskCacheMixin.default_cache_path(self._cache_name)

    @staticmethod
    def rate_key(ccy: str, index: str, tenor: str, clearing_house: str, date: Any) -> str:
        return (
            f"rate|{str(ccy).upper()}|{str(index).upper()}|{str(tenor).lower()}"
            f"|{str(clearing_house).upper()}|{_as_date(date).isoformat()}"
        )

    @staticmethod
    def warm_key(ccy: str, index: str, tenor: str, clearing_house: str) -> str:
        return (
            f"warm|{str(ccy).upper()}|{str(index).upper()}|{str(tenor).lower()}"
            f"|{str(clearing_house).upper()}"
        )

    # -- warm-state introspection ----------------------------------------

    def warm_spans(self, ccy: str, index: str, tenor: str, clearing_house: str) -> List[List[str]]:
        cache = self._ensure_cache()
        return list(cache.get(self.warm_key(ccy, index, tenor, clearing_house), []) or [])

    def is_warm(self, ccy: str, index: str, tenor: str, clearing_house: str, start: Any, end: Any) -> bool:
        return _covered(self.warm_spans(ccy, index, tenor, clearing_house), _as_date(start), _as_date(end))

    def _mark_warm(self, ccy: str, index: str, tenor: str, clearing_house: str, start: Any, end: Any) -> None:
        cache = self._ensure_cache()
        key = self.warm_key(ccy, index, tenor, clearing_house)
        spans = list(cache.get(key, []) or [])
        spans.append([_as_date(start).isoformat(), _as_date(end).isoformat()])
        cache.set(key, _merge_spans(spans))

    # -- writes -----------------------------------------------------------

    def put_leg(self, ccy: str, index: str, tenor: str, clearing_house: str, date: Any, rate: float) -> None:
        """Store one decimal rate.  Test seams and manual repairs use this."""
        cache = self._ensure_cache()
        cache.set(self.rate_key(ccy, index, tenor, clearing_house, date), float(rate))

    def mark_warm(self, ccy: str, index: str, tenor: str, clearing_house: str, start: Any, end: Any) -> None:
        self._mark_warm(ccy, index, tenor, clearing_house, start, end)

    # -- reads (offline) --------------------------------------------------

    def read_leg(
        self,
        ccy: str,
        index: str,
        tenor: str,
        clearing_house: str,
        start: Any,
        end: Any,
        require_warm: bool = True,
    ) -> pd.Series:
        """Decimal rates for one leg over ``[start, end]``, cache only.

        Missing business days are simply absent from the returned Series -- but
        only after the warm marker has established that the window was fetched.
        """
        s, e = _as_date(start), _as_date(end)
        if require_warm and not self.is_warm(ccy, index, tenor, clearing_house, s, e):
            raise CCPBasisCacheMiss(
                f"{ccy} {index} {tenor} {clearing_house}: {s}..{e} is not warm in "
                f"{self.cache_dir}. Warm it with CCPBasisCache.warm(...) "
                f"(1 network fetch) or pass allow_network=True. "
                f"Warm spans present: {self.warm_spans(ccy, index, tenor, clearing_house)}"
            )
        cache = self._ensure_cache()
        idx, vals = [], []
        for ts in pd.bdate_range(s, e):
            v = cache.get(self.rate_key(ccy, index, tenor, clearing_house, ts))
            if v is not None:
                idx.append(ts)
                vals.append(float(v))
        return pd.Series(vals, index=pd.DatetimeIndex(idx, name="date"), name=f"{tenor}|{clearing_house}", dtype="float64")

    # -- the one network path ---------------------------------------------

    def warm(
        self,
        start: Any,
        end: Any,
        tenors: Sequence[str] = SPOT_TENOR_LADDER,
        ccy: str = "USD",
        index: str = "SOFR",
        clearing_houses: Sequence[str] = ("LCH", "CME"),
    ) -> Dict[str, Any]:
        """Fetch every ``(tenor, clearing_house)`` leg in ONE dataset query.

        Returns a summary dict.  ``self.http_calls`` is incremented by the exact
        number of outbound requests observed (gs_quant issues an activity ping
        and a catalog lookup of its own alongside the token and the query).
        """
        s, e = _as_date(start), _as_date(end)
        cov = self.coverage()

        asset_map: Dict[str, Tuple[str, str]] = {}
        for tenor in tenors:
            for ch in clearing_houses:
                asset_map[find_asset(cov, ccy, index, tenor, ch)] = (tenor, ch)

        df, n_calls = _fetch_rates(
            asset_ids=list(asset_map),
            start=s,
            end=e,
            gs_client_id=self._gs_client_id,
            gs_secret_key=self._gs_secret_key,
        )
        self.http_calls += n_calls

        cache = self._ensure_cache()
        written = 0
        for asset_id, sub in df.groupby("assetId"):
            tenor, ch = asset_map[str(asset_id)]
            for ts, rate in zip(sub["date"], sub["rate"]):
                if pd.isna(rate):
                    continue
                cache.set(self.rate_key(ccy, index, tenor, ch, ts), float(rate))
                written += 1
        # Clamp the warm marker to the last date the wire actually served.
        # Warming through "today" before today's print publishes would otherwise
        # mark an empty day as fetched, and every later read would treat that
        # hole as "the CCP did not publish" -- a baked-in gap no re-warm can
        # heal. Under-claiming instead makes a trailing-holiday read raise,
        # which is recoverable.
        warm_end = e
        if len(df):
            served_max = _as_date(df["date"].max())
            warm_end = min(e, served_max)
        else:
            warm_end = None

        if warm_end is not None:
            for tenor, ch in asset_map.values():
                self._mark_warm(ccy, index, tenor, ch, s, warm_end)

        return {
            "rows_written": written,
            "assets": len(asset_map),
            "http_calls": n_calls,
            "requested_start": s.isoformat(),
            "requested_end": e.isoformat(),
            "warmed_through": warm_end.isoformat() if warm_end else None,
            "cache_dir": self.cache_dir,
        }


def _fetch_rates(
    asset_ids: Sequence[str],
    start: datetime.date,
    end: datetime.date,
    gs_client_id: Optional[str],
    gs_secret_key: Optional[str],
) -> Tuple[pd.DataFrame, int]:
    """One authenticated ``Dataset.get_data``; returns (frame, http_call_count).

    The frame carries ``date``, ``assetId`` and ``rate`` only.  Rates are left
    in the wire's own units (decimal) -- conversion to bp happens once, in
    :func:`basis_panel`.
    """
    import requests

    from gs_quant.data import Dataset
    from gs_quant.session import GsSession

    from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import _resolve_gs_credentials

    calls = {"n": 0}
    original = requests.Session.request

    def counted(self, method, url, *args, **kwargs):
        calls["n"] += 1
        return original(self, method, url, *args, **kwargs)

    requests.Session.request = counted
    try:
        client_id, secret_key = _resolve_gs_credentials(gs_client_id, gs_secret_key)
        GsSession.use(client_id=client_id, client_secret=secret_key, scopes=GsSession.Scopes.get_default())
        raw = Dataset(DATASET_ID).get_data(start, end, assetId=list(asset_ids))
    finally:
        requests.Session.request = original

    raw = raw.reset_index()
    missing = {"date", "assetId", "rate"} - set(raw.columns)
    if missing:
        raise RuntimeError(f"{DATASET_ID} response is missing {sorted(missing)}; got {list(raw.columns)}")
    out = raw[["date", "assetId", "rate"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    dupes = int(out.duplicated(["assetId", "date"]).sum())
    if dupes:
        raise RuntimeError(
            f"{DATASET_ID} returned {dupes} duplicate (assetId, date) rows -- the "
            f"per-date cache key would silently keep only the last. Disambiguate "
            f"on pricingLocation/csaTerms before caching."
        )
    return out, calls["n"]


# ---------------------------------------------------------------------------
# the panel
# ---------------------------------------------------------------------------


def basis_panel(
    start: Any,
    end: Any,
    tenors: Sequence[str] = SPOT_TENOR_LADDER,
    ccy: str = "USD",
    index: str = "SOFR",
    long_ch: str = "LCH",
    short_ch: str = "CME",
    cache: Optional[CCPBasisCache] = None,
    allow_network: bool = False,
    dropna: bool = True,
) -> pd.DataFrame:
    """CCP basis panel: rows are dates, columns are tenors, values are **bp**.

    ``value = rate[long_ch] - rate[short_ch]``, i.e. **LCH minus CME** by
    default.  Negative means LCH pays the lower fixed rate.

    Only dates on which *both* legs printed are kept, so a column is never a
    stale leg differenced against a fresh one.  ``allow_network`` defaults to
    ``False``: a cold window raises :class:`CCPBasisCacheMiss` instead of
    quietly refetching or quietly returning nothing.

    The returned frame carries ``.attrs``: ``sign_convention``, ``units``,
    ``long_ch``, ``short_ch``, ``ccy``, ``index``.
    """
    verify_sign_convention()

    s, e = _as_date(start), _as_date(end)
    tenors = list(tenors)
    cache = cache or CCPBasisCache()

    cold = [
        (t, ch)
        for t in tenors
        for ch in (long_ch, short_ch)
        if not cache.is_warm(ccy, index, t, ch, s, e)
    ]
    if cold:
        if not allow_network:
            raise CCPBasisCacheMiss(
                f"{len(cold)} leg(s) cold for {s}..{e}: {cold[:6]}"
                f"{' ...' if len(cold) > 6 else ''}. "
                f"Call basis_panel(..., allow_network=True) once to warm, or "
                f"CCPBasisCache().warm({s!r}, {e!r}, tenors=...)."
            )
        cache.warm(s, e, tenors=tenors, ccy=ccy, index=index, clearing_houses=(long_ch, short_ch))

    cols: Dict[str, pd.Series] = {}
    for tenor in tenors:
        lo = cache.read_leg(ccy, index, tenor, long_ch, s, e)
        sh = cache.read_leg(ccy, index, tenor, short_ch, s, e)
        both = lo.index.intersection(sh.index)
        cols[tenor] = _basis_bp(lo.reindex(both), sh.reindex(both))

    panel = pd.DataFrame(cols)
    panel.index.name = "date"
    panel = panel.sort_index()
    if dropna:
        panel = panel.dropna(how="all")

    panel.attrs.update(
        {
            "sign_convention": f"{long_ch} minus {short_ch}",
            "units": "bp",
            "long_ch": long_ch,
            "short_ch": short_ch,
            "ccy": ccy,
            "index": index,
            "dataset": DATASET_ID,
        }
    )
    return panel
