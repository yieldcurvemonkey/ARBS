from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
from tqdm import tqdm as _tqdm

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.IRSwaptions.IRSwaptionMDP import (
    IRSwaptionMDP,
    IRSwaptionMarketContext,
    resolve_timestamp_mode,
)
from Query.Base.query_resolution import resolve_query
import Query.IRSwaptions.adapter  # noqa: F401
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery, IRSwaptionQueryWrapper
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns

_LOGGER_NAME = "IRSwaptionsTB"


def _query_fingerprint(q: IRSwaptionQuery, *, include_name: bool = True) -> str:
    payload = {
        "curve": q.curve,
        "structure": q.structure.name if getattr(q, "structure", None) else None,
        "value": _canonicalize_value(q.value.name if hasattr(q.value, "name") else q.value),
        "structure_kwargs": _canonicalize_value(q.structure_kwargs or {}),
        "value_kwargs": _canonicalize_value(q.value_kwargs or {}),
        "trade_date": _canonicalize_value(q.trade_date),
        "risk_weight": q.risk_weight,
    }
    if include_name:
        # Retain the existing L1 cache identity. A name is only presentational for
        # static queries, but old diskcache rows include it and must stay valid.
        payload["name"] = q.name
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _value_fingerprint(q: IRSwaptionQuery) -> str:
    """Identity for a persisted *value*, rather than an output column label.

    Static named/unnamed queries price the same economic package.  Keeping their
    durable value in one symbol avoids doubling the daily warm solely to support
    a caller's display label. Trade-date queries resolve to date-specific legs,
    so retain their full identity until that resolution can be represented in a
    stable cache key.
    """
    return _query_fingerprint(q, include_name=getattr(q, "trade_date", None) is not None)


_NON_VALUE_REQUEST_DEFAULTS = frozenset({
    "verify",
    "offline",
    "offline_only",
    "curve_ignore_cache",
    "force_refresh",
    "snapshot_policy",
})


_ATMF_OFFSET_RE = re.compile(
    r"^\s*ATM[FS]\s*(?:([+-])\s*(\d+(?:\.\d+)?)\s*B?P?S?)?\s*$",
    re.IGNORECASE,
)


def _value_request_token(mdp: Any) -> str:
    """Namespace values by inputs that can change a number, not cache controls."""
    defaults = dict(getattr(mdp, "_default_request_kwargs", {}) or {})
    value_defaults = {
        key: value
        for key, value in defaults.items()
        if key not in _NON_VALUE_REQUEST_DEFAULTS
    }
    token_fn = getattr(mdp, "_request_kwargs_token", None)
    if callable(token_fn):
        try:
            return str(token_fn(value_defaults))
        except Exception:
            pass
    if not value_defaults:
        return "default"
    try:
        blob = json.dumps(_canonicalize_value(value_defaults), sort_keys=True, separators=(",", ":"))
    except Exception:
        blob = repr(sorted((str(k), repr(v)) for k, v in value_defaults.items()))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _flatten_queries_with_wrappers(
    queries: List[IRSwaptionQuery | List[IRSwaptionQuery] | IRSwaptionQueryWrapper],
) -> tuple[list[IRSwaptionQuery], list[IRSwaptionQueryWrapper]]:
    flat: list[IRSwaptionQuery] = []
    wrappers: list[IRSwaptionQueryWrapper] = []

    def _expand_one(item):
        if isinstance(item, IRSwaptionQueryWrapper):
            wrappers.append(item)
            flat.extend(item.return_query())
            return
        if isinstance(item, list):
            for sub in item:
                _expand_one(sub)
            return
        if hasattr(item, "return_query"):
            expanded = item.return_query()
            if isinstance(expanded, list):
                flat.extend(expanded)
            else:
                flat.append(expanded)
            return
        flat.append(item)

    for q in queries:
        _expand_one(q)

    return flat, wrappers


def _group_queries_by_curve(queries: Iterable[IRSwaptionQuery]) -> Dict[str, List[IRSwaptionQuery]]:
    out: Dict[str, List[IRSwaptionQuery]] = defaultdict(list)
    for q in queries:
        if not q.curve:
            raise ValueError("Each IRSwaptionQuery must set .curve for IRSwaptionsTB.")
        out[q.curve].append(q)
    return dict(out)


def _is_today(d: DateLike) -> bool:
    if isinstance(d, datetime.datetime):
        return d.date() == datetime.date.today()
    if isinstance(d, datetime.date):
        return d == datetime.date.today()
    return False


def _eod_key(d: DateLike) -> DateLike:
    return d.date() if isinstance(d, datetime.datetime) else d


def _is_eod_reference_point(d: DateLike) -> bool:
    if d == "live":
        return False
    try:
        return resolve_timestamp_mode(d) == "eod"
    except Exception:
        return isinstance(d, datetime.date)


def _cached_row_for_query(
    row: Tuple[DateLike, str, float],
    q: IRSwaptionQuery,
) -> Tuple[DateLike, str, float]:
    """Restore a static query's requested display label on a shared value row."""
    if getattr(q, "trade_date", None) is not None:
        return row
    column_name = str(q.name) if getattr(q, "name", None) else q.col_name()
    return row[0], column_name, float(row[2])


def _durable_row_for_query(
    row: Tuple[DateLike, str, float],
    q: IRSwaptionQuery,
) -> Tuple[DateLike, str, float]:
    """Persist a canonical display label so named/unnamed reads share a value."""
    if getattr(q, "trade_date", None) is not None or not getattr(q, "name", None):
        return row[0], str(row[1]), float(row[2])
    unnamed = replace(q, name=None)
    return row[0], unnamed.col_name(), float(row[2])


def _atmf_offset_bps(value: Any) -> Optional[float]:
    """Return a static ATMF/ATMS strike offset, or ``None`` for curve-aware specs."""
    if not isinstance(value, str):
        return None
    match = _ATMF_OFFSET_RE.match(value)
    if match is None:
        return None
    sign, magnitude = match.groups()
    if sign is None:
        return 0.0
    bump = float(magnitude)
    return bump if sign == "+" else -bump


def _citivelo_native_nvol_components(
    q: IRSwaptionQuery,
) -> Optional[tuple[str, str, list[tuple[float, float]]]]:
    """Static raw-cube components for standard Citi NVOL packages.

    The normal-vol selector is a weighted average of individual leg normal
    vols. For tenor-mode packages whose strikes are ``ATMF`` plus fixed bp
    wings, every leg's cube offset is known without recovering the curve
    forward. This makes the raw cube authoritative for the result: no pricer,
    curve, or convention approximation is involved.

    Costless 1x2s and ladders are deliberately excluded. Their solved strike is
    a function of the full smile, so they retain the ordinary exact RL path.
    Explicit dates, delta strikes, premiums, and other rich parameters likewise
    retain that path.
    """
    if q.value is not IRSwaptionValue.NVOL:
        return None
    if getattr(q, "trade_date", None) is not None or getattr(q, "risk_weight", None) is not None:
        return None
    if getattr(q, "value_kwargs", None):
        return None
    if not q.expiry or not q.tail or "x" in str(q.tail).lower():
        return None

    skw = dict(q.structure_kwargs or {})
    allowed_kwargs = {"expiry", "tail", "strike", "side", "wing_bps", "spread_bps"}
    if set(skw) - allowed_kwargs:
        return None
    base = _atmf_offset_bps(skw.get("strike", q.strike))
    if base is None:
        return None

    try:
        wing = float(skw.get("wing_bps", 25.0))
        spread = float(skw.get("spread_bps", 25.0))
    except (TypeError, ValueError):
        return None

    # Payer/receiver/straddle share the one static offset. A straddle has two
    # identical legs, so retaining one component produces the same average.
    if q.structure in {
        IRSwaptionStructure.PAYER,
        IRSwaptionStructure.RECEIVER,
        IRSwaptionStructure.STRADDLE,
    }:
        components = [(base, 1.0)]
    elif q.structure == IRSwaptionStructure.STRANGLE:
        components = [(base - wing, 1.0), (base + wing, 1.0)]
    elif q.structure in {
        IRSwaptionStructure.RECEIVER_SPREAD,
        IRSwaptionStructure.PAYER_SPREAD,
    }:
        components = [(base, 1.0), (base + spread, 1.0)]
    elif q.structure in {
        IRSwaptionStructure.RECEIVER_FLY,
        IRSwaptionStructure.PAYER_FLY,
    }:
        components = [(base - spread, 1.0), (base, 2.0), (base + spread, 1.0)]
    elif q.structure == IRSwaptionStructure.RISK_REVERSAL:
        components = [(base - wing, 1.0), (base + wing, 1.0)]
    else:
        return None
    return str(q.expiry), str(q.tail), components


def _is_citivelo_native_nvol_query(q: IRSwaptionQuery) -> bool:
    """Whether a missing stored cube can be skipped in strict offline mode."""
    return (
        _citivelo_native_nvol_components(q) is not None
        or _is_citivelo_native_costless_nvol_query(q)
    )


def _citivelo_native_standard_package_nvol(
    q: IRSwaptionQuery,
    stored_cube: Any,
) -> Optional[float]:
    """Read exact standard package NVOL directly from the raw Citi smile."""
    components = _citivelo_native_nvol_components(q)
    if components is None:
        return None
    expiry, tail, offsets = components
    try:
        weighted = sum(
            abs(float(weight)) * float(stored_cube.data.vol(expiry, tail, offset_bp=float(offset)))
            for offset, weight in offsets
        )
        denominator = sum(abs(float(weight)) for _offset, weight in offsets) or 1.0
        return float(weighted / denominator)
    except Exception:
        return None


def _is_citivelo_native_costless_nvol_query(q: IRSwaptionQuery) -> bool:
    """Whether a standard 1x2/ladder can solve entirely in raw-smile space."""
    if q.value is not IRSwaptionValue.NVOL:
        return False
    if q.structure not in {
        IRSwaptionStructure.RECEIVER_1x2,
        IRSwaptionStructure.PAYER_1x2,
        IRSwaptionStructure.RECEIVER_LADDER,
        IRSwaptionStructure.PAYER_LADDER,
    }:
        return False
    if getattr(q, "trade_date", None) is not None or getattr(q, "risk_weight", None) is not None:
        return False
    if getattr(q, "value_kwargs", None):
        return False
    if not q.expiry or not q.tail or "x" in str(q.tail).lower():
        return False

    skw = dict(q.structure_kwargs or {})
    allowed_kwargs = {"expiry", "tail", "strike", "side", "wing_bps", "costless"}
    if set(skw) - allowed_kwargs:
        return False
    if not bool(skw.get("costless", True)):
        return False
    if _atmf_offset_bps(skw.get("strike", q.strike)) is None:
        return False
    try:
        return float(skw.get("wing_bps", 25.0)) > 0.0
    except (TypeError, ValueError):
        return False


def _citivelo_native_costless_package_nvol(
    q: IRSwaptionQuery,
    stored_cube: Any,
    native_cube: Any,
) -> Optional[float]:
    """Solve default 1x2/ladder NVOL in the exact raw Citi smile.

    In the ordinary RL path, a costless structure solves an equation between
    Bachelier option premia. All legs share one forward, annuity, and notional,
    so those quantities cancel when the equation is expressed in *bp from ATMF*.
    The remaining inputs are the published smile and expiry date. A vol-only
    ``IRSplineCube`` therefore reproduces the full RL solver exactly while
    avoiding a curve/context build for every EOD day.
    """
    if not _is_citivelo_native_costless_nvol_query(q):
        return None
    if native_cube is None or not bool(getattr(stored_cube, "has_smile", False)):
        return None

    try:
        from scipy.optimize import brentq, newton
        import rateslib as rl

        from Query.Base.bachelier import bachelier_price

        data = stored_cube.data
        as_of = data.as_of
        eval_date = datetime.datetime(as_of.year, as_of.month, as_of.day)
        exercise_date = rl.add_tenor(eval_date, str(q.expiry), "mf", "nyc")
        exercise_date = exercise_date.date() if isinstance(exercise_date, datetime.datetime) else exercise_date
        tte = max((exercise_date - as_of).days / 365.0, 1e-10)
        skw = dict(q.structure_kwargs or {})
        base = _atmf_offset_bps(skw.get("strike", q.strike))
        if base is None:
            return None
        wing_bps = float(skw.get("wing_bps", 25.0))
        direction = 1.0 if q.structure in {
            IRSwaptionStructure.PAYER_1x2,
            IRSwaptionStructure.PAYER_LADDER,
        } else -1.0
        right = "C" if direction > 0.0 else "P"
        smile = native_cube.get_smile(str(q.expiry), str(q.tail))

        def vol_bps(offset_bps: float) -> float:
            # Rateslib's native smile is indexed by bp-from-forward in percent
            # rates. A fixed placeholder forward is valid by construction.
            return float(smile.get_from_strike(3.0 + float(offset_bps) / 100.0, f=3.0).vol)

        def premium(offset_bps: float) -> float:
            return bachelier_price(
                right,
                float(offset_bps) / 10_000.0,
                0.0,
                vol_bps(offset_bps) / 10_000.0,
                tte,
                1.0,
            )

        guess = float(base) + direction * wing_bps
        lo, hi = guess - abs(wing_bps), guess + abs(wing_bps)
        base_premium = premium(float(base))
        if q.structure in {
            IRSwaptionStructure.PAYER_1x2,
            IRSwaptionStructure.RECEIVER_1x2,
        }:
            objective = lambda offset: base_premium - 2.0 * premium(float(offset))
        else:
            objective = lambda offset: (
                base_premium
                - premium(float(offset))
                - premium(float(offset) + direction * wing_bps)
            )

        try:
            f_lo, f_hi = objective(lo), objective(hi)
            if f_lo == 0.0:
                solved = lo
            elif f_hi == 0.0:
                solved = hi
            elif f_lo * f_hi < 0.0:
                solved = float(brentq(objective, lo, hi, maxiter=200))
            else:
                solved = float(newton(objective, x0=guess, maxiter=100))
        except Exception:
            solved = float(newton(objective, x0=guess, maxiter=100))

        if q.structure in {
            IRSwaptionStructure.PAYER_1x2,
            IRSwaptionStructure.RECEIVER_1x2,
        }:
            return float((vol_bps(float(base)) + 2.0 * vol_bps(solved)) / 3.0)
        return float(
            (
                vol_bps(float(base))
                + vol_bps(solved)
                + vol_bps(solved + direction * wing_bps)
            )
            / 3.0
        )
    except Exception:
        # The normal pricing path remains the semantic backstop for a bad/cold
        # raw cube or a solver edge case.
        return None


def _build_row_for_query(
    context: IRSwaptionMarketContext,
    q: IRSwaptionQuery,
    ref_dt: DateLike,
) -> tuple[DateLike, str, float]:
    q_eff = resolve_query(q, timestamp=ref_dt, pricer_or_curve=context)
    if getattr(q, "name", None):
        col = str(q.name)
    else:
        col = q_eff.col_name()
    package, risk_weights = q_eff.resolve_package(pricer_or_curve=context, is_for_timeseries=True)
    vmap = q_eff.build_value_map(pricer_or_curve=context, package=package, risk_weights=risk_weights)
    value = vmap.apply(value=q_eff.value, **(q_eff.value_kwargs or {}))
    return ref_dt, col, float(value)


def _context_for(built_map: Dict[Any, Any], d: DateLike) -> Optional[Any]:
    """The context for one reference point, whatever type the two sides used.

    ``IRSwaptionMDP.bulk_get_data`` keys its result by ``datetime.date``
    (``_normalize_dates`` flattens every input). ``build_reference_points``
    returns ``datetime.date`` for the ordinary ``start``/``end`` path but
    ``datetime.datetime`` when the caller passes ``timestamps=`` - and
    ``datetime(2026, 7, 27) != date(2026, 7, 27)`` and hashes differently, so a
    plain ``built_map.get(d)`` misses EVERY row on that path.

    The failure is silent and looks exactly like missing data: one "No swaption
    context" warning per date and an empty frame. Measured on a 10-day warm:
    every context was built (the cubes logged their round-trip) and every lookup
    missed. The pre-existing ``if ctx is None and d == date.today()`` line was a
    partial attempt at the same normalisation that could only ever fix today.

    Mirrors ``IRSwaptionMDP._extract_curve_for_date``, which already solves this
    for the curve map.
    """
    ctx = built_map.get(d)
    if ctx is not None:
        return ctx
    as_date = d.date() if isinstance(d, datetime.datetime) else d
    ctx = built_map.get(as_date)
    if ctx is not None:
        return ctx
    for key, value in built_map.items():
        key_date = key.date() if isinstance(key, datetime.datetime) else key
        if key_date == as_date:
            return value
    return None


class IRSwaptionsTB(LayeredCacheMixin, BaseTimeseriesTB):
    _CACHE_ATTR_BASE = "_irswaptions_tb_cache"
    _CACHE_VERSION = "v1"
    _DEFAULT_PRICING_MESSAGE = "PRICING IRSWAPTIONS."

    def __init__(
        self,
        mdp: IRSwaptionMDP,
        *,
        date_col: str = "Date",
        cache_stem: Optional[str] = None,
        force_refresh: bool = False,
        use_btree: bool = True,
        show_tqdm: bool = True,
        logger: Optional[logging.Logger] = None,
        use_ts_cache: bool = True,
        ts_base_dir: Optional[str] = "./data/ts",
        ts_row_group_size: int = 256_000,
        ts_compression: str = "zstd",
        use_duckdb: bool = True,
        duckdb_path: Optional[str] = None,
    ):
        LayeredCacheMixin.__init__(
            self,
            use_btree=use_btree,
            force_refresh=force_refresh,
            mdp=mdp,
            date_col=date_col,
            show_tqdm=show_tqdm,
        )
        self._logger = logger or logging.getLogger(_LOGGER_NAME)
        # curve_source is part of the stem, and has to be. A swaption VALUE is a
        # function of the curve as well as the vol - the discount curve prices the
        # premium and anchors the ATMF strike - but neither the stem nor
        # _cache_key carried it, so values computed against
        # ERIS_EOD_LIVE-RL_BASIC were served to a reader on curve_source=CITIVELO
        # under the same key. Harmless while only one curve_source was ever used
        # per source token; a value warm over thousands of days makes it a
        # persistent, silently wrong cache. Separate stems keep the two apart
        # without invalidating anything already written under the old name for a
        # single-curve_source user.
        curve_token = str(getattr(mdp, "curve_source", "") or "default")
        stem = cache_stem or (
            f"IRSwaptionsTB_{self._CACHE_VERSION}_{mdp.source}_{curve_token}"
        )
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"
        self.open_cache(cache_attr=self._cache_attr, path=self._cache_path)
        self._use_ts_cache = bool(use_ts_cache)
        self._value_request_token = _value_request_token(mdp)
        self._computed_ts_store = ComputedTimeseriesStore(
            base_dir=ts_base_dir or "./data/ts",
            compression=ts_compression,
            row_group_size=int(ts_row_group_size),
            use_duckdb=use_duckdb,
            duckdb_path=duckdb_path,
        )
        # Only the default costless structures need a continuously-interpolated
        # smile. Retain one lightweight, vol-only native cube per stored EOD
        # snapshot for this TB instance; contexts/pricers are never persisted.
        self._citivelo_native_smile_cubes: dict[int, Any] = {}
        self._citivelo_native_smile_cubes_lock = threading.RLock()

    def close(self):
        if hasattr(self, self._cache_attr):
            self.close_cache()
        self._citivelo_native_smile_cubes.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _cache_key(self, d: DateLike, curve_name: str, q: IRSwaptionQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{curve_name}|{ns}|{qh}"

    def _ts_symbol_for_query(self, curve_name: str, q: IRSwaptionQuery) -> str:
        curve_source = str(getattr(self.mdp, "curve_source", "") or "default")
        return (
            f"IRSWAPTION::{self.mdp.source}::{curve_source}::"
            f"{self._value_request_token}::{curve_name}::{_value_fingerprint(q)}"
        )

    def _citivelo_native_smile_cube(self, stored_cube: Any) -> Any:
        """A curve-free native smile for one stored Citi EOD cube, if available."""
        data = getattr(stored_cube, "data", None)
        as_of = getattr(data, "as_of", None)
        if not isinstance(as_of, datetime.date):
            return None
        key = id(data)
        with self._citivelo_native_smile_cubes_lock:
            if key in self._citivelo_native_smile_cubes:
                return self._citivelo_native_smile_cubes[key]
            try:
                from MDP.CitiVelocityExcel.vol.rl_native_cube import (
                    RATESLIB_NATIVE_AVAILABLE,
                    build_rl_native_cube,
                )

                if not RATESLIB_NATIVE_AVAILABLE:
                    native = None
                else:
                    native = build_rl_native_cube(
                        cube=data,
                        citi_index="USD_SOFR",
                        eval_date=datetime.datetime(as_of.year, as_of.month, as_of.day),
                        verify=False,
                    )
            except Exception as exc:
                self._logger.debug("Citi native smile fast path unavailable: %s", exc)
                native = None
            self._citivelo_native_smile_cubes[key] = native
            return native

    def _native_citivelo_cube_rows(
        self,
        *,
        curve_name: str,
        missing_by_date: Mapping[DateLike, list[IRSwaptionQuery]],
    ) -> tuple[
        list[tuple[tuple[DateLike, str, float], IRSwaptionQuery, str, DateLike]],
        dict[DateLike, list[IRSwaptionQuery]],
    ]:
        """Serve exact standard Citi NVOL packages without rebuilding a context.

        This is intentionally a *value* fast path, not a generic vectorized
        curve/pricer. Fixed ATMF-relative packages read the authoritative raw
        smile nodes; default costless 1x2s/ladders solve in that same native
        smile after cancelling their common forward/annuity/notional. No
        convention approximation is introduced. It applies only to the RL
        source requested by the notebook; QL, rich value selectors, explicit
        dates, midcurves, delta strikes, and custom packages retain the ordinary
        convention-complete pricing path.
        """
        source = str(getattr(self.mdp, "source", "")).upper()
        if source != "CITIVELO-RL" or curve_name.upper() != "USD-SOFR-1D":
            return [], {d: list(qs) for d, qs in missing_by_date.items()}
        if any(not _is_eod_reference_point(d) for d in missing_by_date):
            return [], {d: list(qs) for d, qs in missing_by_date.items()}

        try:
            from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes, stored_gap_dates

            date_keys = sorted({_eod_key(d) for d in missing_by_date})
            stored_by_date = load_stored_cubes("USD", date_keys)
            # Dates the store is warm either side of but holds nothing for -
            # market holidays. The provider already refuses to drive Excel for
            # them; recognising them here as well means the ordinary path is not
            # entered at all, so there is no context build and no per-date
            # "No swaption context" warning for a day that has no market.
            gap_dates = (
                stored_gap_dates("USD", [d for d in date_keys if d not in stored_by_date])
                if stored_by_date
                else frozenset()
            )
        except Exception as exc:  # never let a fast-path cache read block pricing
            self._logger.debug("Citi native cube fast path unavailable: %s", exc)
            return [], {d: list(qs) for d, qs in missing_by_date.items()}

        rows: list[tuple[tuple[DateLike, str, float], IRSwaptionQuery, str, DateLike]] = []
        remaining: dict[DateLike, list[IRSwaptionQuery]] = {}
        offline_only = bool(
            (getattr(self.mdp, "_default_request_kwargs", {}) or {}).get("offline_only", False)
        )
        for d, queries in missing_by_date.items():
            stored = stored_by_date.get(_eod_key(d))
            is_store_gap = _eod_key(d) in gap_dates
            unresolved: list[IRSwaptionQuery] = []
            for q in queries:
                value = None if stored is None else _citivelo_native_standard_package_nvol(q, stored)
                if value is None and stored is not None and _is_citivelo_native_costless_nvol_query(q):
                    value = _citivelo_native_costless_package_nvol(
                        q,
                        stored,
                        self._citivelo_native_smile_cube(stored),
                    )
                if value is None:
                    # A weekday with no stored cube is a coverage gap (normally a
                    # market holiday), not a reason to enter Excel.  Leave the row
                    # absent, matching the curve side's treatment of a non-session
                    # date.  `offline_only` says so as a policy; `is_store_gap`
                    # says so from the store's own shape, which is why an
                    # interactive caller no longer has to set the flag to avoid a
                    # fetch that cannot succeed.  A date PAST the warm is neither,
                    # and still falls through to the live path below.
                    if (offline_only or is_store_gap) and _is_citivelo_native_nvol_query(q):
                        continue
                    unresolved.append(q)
                    continue
                column = str(q.name) if getattr(q, "name", None) else q.col_name()
                rows.append(((d, column, float(value)), q, curve_name, d))
            if unresolved:
                remaining[d] = unresolved
        return rows, remaining

    def _flatten_queries(
        self,
        queries: List[IRSwaptionQuery | List[IRSwaptionQuery] | IRSwaptionQueryWrapper],
    ) -> List[IRSwaptionQuery]:
        flat, _ = _flatten_queries_with_wrappers(queries)
        return flat

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwaptionQuery | List[IRSwaptionQuery] | IRSwaptionQueryWrapper],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
    ) -> pd.DataFrame:
        assert start <= end, "must have end >= start"
        ref_points = self._build_reference_points(start=start, end=end, freq=freq, timestamps=timestamps)
        if not ref_points:
            return pd.DataFrame(columns=[self._date_col]).set_index(pd.Index([], name=self._date_col))

        flat, wrappers = _flatten_queries_with_wrappers(queries)
        if not flat:
            return pd.DataFrame(columns=[self._date_col]).set_index(pd.Index([], name=self._date_col))

        by_curve = _group_queries_by_curve(flat)
        cache_map = getattr(self, self._cache_attr)

        # EOD values are durable data, not merely a convenient in-process result.
        # The scalar diskcache remains useful as a tiny L1/legacy tier, but a
        # comprehensive historical pull should be one DuckDB/Parquet batch read
        # rather than hundreds of individual diskcache probes and pricer builds.
        is_eod_request = bool(ref_points) and all(_is_eod_reference_point(d) for d in ref_points)
        use_eod_ts_cache = (
            bool(getattr(self, "_use_ts_cache", False))
            and not bool(ignore_cache)
            and is_eod_request
        )

        def _row_key(d: DateLike, q: IRSwaptionQuery) -> tuple[DateLike, str]:
            if use_eod_ts_cache:
                return _eod_key(d), _value_fingerprint(q)
            return d, _query_fingerprint(q)

        cached_rows: list[tuple[DateLike, str, float]] = []
        cached_row_keys: set[tuple[DateLike, str]] = set()

        if use_eod_ts_cache:
            for curve_name, qs in by_curve.items():
                symbol_queries: dict[str, list[IRSwaptionQuery]] = defaultdict(list)
                fallback_columns: dict[str, str] = {}
                for q in qs:
                    symbol = self._ts_symbol_for_query(curve_name, q)
                    symbol_queries[symbol].append(q)
                    fallback_columns.setdefault(symbol, q.col_name())
                try:
                    batch_rows = self._computed_ts_store.read_many_symbols(
                        symbols=list(symbol_queries),
                        reference_points=ref_points,
                        intraday=False,
                        skip_current_eod=True,
                        fallback_column_names=fallback_columns,
                        allow_partial=True,
                    )
                except Exception as exc:  # cache failure must never block pricing
                    self._logger.debug("Swaption computed-timeseries read failed for curve='%s': %s", curve_name, exc)
                    batch_rows = {}

                for symbol, symbol_qs in symbol_queries.items():
                    for q in symbol_qs:
                        for row in batch_rows.get(symbol, []):
                            cached_rows.append(_cached_row_for_query(row, q))
                            cached_row_keys.add(_row_key(row[0], q))

        # Track misses at the (date, query) level. Building a context once per
        # date is cheap; re-pricing a query that was already found in the durable
        # cache is not.
        to_fetch: DefaultDict[str, DefaultDict[DateLike, list[IRSwaptionQuery]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for d in ref_points:
            for curve_name, qs in by_curve.items():
                for q in qs:
                    if _row_key(d, q) in cached_row_keys:
                        continue
                    if _is_today(d):
                        to_fetch[curve_name][d].append(q)
                        continue
                    k = self._cache_key(d, curve_name, q)
                    if (k in cache_map) and not ignore_cache:
                        cached_rows.append(cache_map[k])
                        cached_row_keys.add(_row_key(d, q))
                    else:
                        to_fetch[curve_name][d].append(q)

        new_rows_with_meta: list[tuple[tuple[DateLike, str, float], IRSwaptionQuery, str, DateLike]] = []

        curve_iter = _tqdm(
            list(to_fetch.items()),
            desc=self._pricing_message(flat),
            disable=not self._show_tqdm,
        )
        for curve_name, missing_by_date in curve_iter:
            if not missing_by_date:
                continue

            native_rows, remaining_by_date = self._native_citivelo_cube_rows(
                curve_name=curve_name,
                missing_by_date=missing_by_date,
            )
            new_rows_with_meta.extend(native_rows)
            missing_by_date = remaining_by_date
            if not missing_by_date:
                continue

            missing_dates = sorted(missing_by_date)

            built_map = self.mdp.bulk_get_data(
                {
                    "endpoint": "swaption_snapshot",
                    "curve_name": curve_name,
                    "timestamps": sorted(missing_dates),
                    "ignore_cache": bool(ignore_cache),
                    # Citi's exact CurveStore bulk loader can reconstruct the
                    # full historical context batch in parallel.  This is a
                    # context-build knob, not a pricing semantic, so it is safe
                    # to inherit the caller's TimeseriesBuilder worker budget.
                    "n_jobs": max(1, int(n_jobs or 1)),
                }
            )
            tasks: list[tuple[DateLike, IRSwaptionQuery, IRSwaptionMarketContext]] = []
            for d in missing_dates:
                ctx = _context_for(built_map, d)
                if ctx is None:
                    self._logger.warning(f"No swaption context for curve='{curve_name}', date='{d}'.")
                    continue
                for q in missing_by_date[d]:
                    tasks.append((d, q, ctx))

            if not tasks:
                continue

            if (n_jobs or 1) > 1:
                max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else 1
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    fut_map = {ex.submit(_build_row_for_query, ctx, q, d): (d, q, ctx) for d, q, ctx in tasks}
                    for fut in _tqdm(
                        as_completed(fut_map),
                        total=len(fut_map),
                        desc=f"VALUING IRSWAPTIONS [{curve_name}]",
                        disable=not self._show_tqdm,
                        leave=False,
                    ):
                        d, q, _ctx = fut_map[fut]
                        try:
                            row = fut.result()
                            new_rows_with_meta.append((row, q, curve_name, d))
                        except Exception as exc:
                            self._logger.exception(f"Swaption pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {exc}")
            else:
                for d, q, ctx in _tqdm(
                    tasks,
                    desc=f"VALUING IRSWAPTIONS [{curve_name}]",
                    disable=not self._show_tqdm,
                    leave=False,
                ):
                    try:
                        row = _build_row_for_query(ctx, q, d)
                        new_rows_with_meta.append((row, q, curve_name, d))
                    except Exception as exc:
                        self._logger.exception(f"Swaption pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {exc}")

        with self.batched():
            mapping = getattr(self, self._cache_attr)
            for row, q, curve_name, d in new_rows_with_meta:
                if _is_today(d):
                    continue
                mapping[self._cache_key(d, curve_name, q)] = row

        if bool(getattr(self, "_use_ts_cache", False)) and new_rows_with_meta:
            grouped_rows: DefaultDict[str, list[tuple[DateLike, str, float]]] = defaultdict(list)
            for row, q, curve_name, d in new_rows_with_meta:
                if _is_today(d) or not _is_eod_reference_point(d):
                    continue
                grouped_rows[self._ts_symbol_for_query(curve_name, q)].append(
                    _durable_row_for_query(row, q)
                )
            if grouped_rows:
                try:
                    self._computed_ts_store.append_many_rows(
                        rows_by_symbol=grouped_rows,
                        intraday=False,
                    )
                except Exception as exc:  # priced values remain valid if persistence fails
                    self._logger.warning("[TS cache] swaption bulk append failed: %s", exc)

        all_rows = cached_rows + [r for (r, _q, _cn, _d) in new_rows_with_meta]
        # Historical value rows were written by both date-based EOD callers and
        # timestamp-based notebooks. They are the same EOD observation, but
        # pandas cannot sort/group a mixed ``date``/``datetime`` index. Keep
        # intraday points untouched and canonicalise every EOD row at the output
        # boundary, after all cache identities have already been resolved.
        all_rows = [
            (_eod_key(row[0]) if is_eod_request else row[0], row[1], row[2])
            for row in all_rows
        ]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col]).set_index(pd.Index([], name=self._date_col))

        out = self._rows_to_frame(all_rows)

        if wrappers:
            for w in wrappers:
                expr = w.eval_expression()
                try:
                    out[w.col_name()] = out.eval(expr, engine="python")
                except Exception as exc:
                    self._logger.warning(f"Wrapper expression failed for '{w.col_name()}': {exc}")

        return out.sort_index()
