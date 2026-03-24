import datetime
import uuid
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pandas as pd
import pytz
import pytest

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValue
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer
from Query.Unified import UnifiedQuery, UnifiedStructure, UnifiedValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.STIRFutures._STIRFutureGenericPricable import _STIRFutureGenericPricable
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureValue import USTFutureValue
from Query.USTFutures._USTFutureGenericPricable import _USTFutureGenericPricable
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from definitions.USTFutureOptions import decode_strike_token
from TB.STIRFutureOptionsTB import STIRFutureOptionsTB
from TB.STIRFuturesTB import STIRFuturesTB
from TB.IRSwapsTB import IRSwapsTB
from TB.TimeseriesBuilder import TimeseriesBuilder, _safe_col_name
from TB.USTFutureOptionsTB import USTFutureOptionsTB
from TB.USTFuturesTB import USTFuturesTB


class _FakeRouter:
    def __init__(
        self,
        col_values: Optional[Dict[str, float]] = None,
        *,
        auto_cols: bool = False,
        auto_value: float = 0.04,
        date_col: str = "Date",
    ):
        self.col_values = col_values
        self.auto_cols = auto_cols
        self.auto_value = auto_value
        self.date_col = date_col
        self.mdp = MagicMock()
        self.received_queries: List[Any] = []

    def get_timeseries(
        self,
        start,
        end,
        queries,
        *,
        n_jobs=1,
        ignore_cache=False,
        freq=None,
        timestamps=None,
        _prefetched_ts_rows_by_symbol=None,
    ) -> pd.DataFrame:
        _ = n_jobs, ignore_cache, freq, timestamps, _prefetched_ts_rows_by_symbol
        self.received_queries.extend(queries)
        dates = pd.bdate_range(start, end).date.tolist()
        if not dates:
            return pd.DataFrame()

        data: Dict[str, List[float]] = {}
        if self.col_values:
            for col, val in self.col_values.items():
                data[col] = [val] * len(dates)
        elif self.auto_cols:
            for q in queries:
                col = _safe_col_name(q, f"col_{id(q)}")
                data[col] = [self.auto_value] * len(dates)
        else:
            return pd.DataFrame()

        return pd.DataFrame(data, index=pd.Index(dates, name=self.date_col))


class _NoCallRouter(_FakeRouter):
    def __init__(self, mdp: Any):
        super().__init__(auto_cols=True, auto_value=0.0)
        self.mdp = mdp
        self.call_count = 0

    def get_timeseries(self, *args, **kwargs) -> pd.DataFrame:
        self.call_count += 1
        raise AssertionError("router fallback should not be used")


class _ConcurrentFakeRouter(_FakeRouter):
    def __init__(
        self,
        shared_state: Dict[str, int],
        shared_lock: threading.Lock,
        *args,
        delay_s: float = 0.05,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._shared_state = shared_state
        self._shared_lock = shared_lock
        self._delay_s = float(delay_s)

    def get_timeseries(
        self,
        start,
        end,
        queries,
        *,
        n_jobs=1,
        ignore_cache=False,
        freq=None,
        timestamps=None,
    ) -> pd.DataFrame:
        with self._shared_lock:
            current = self._shared_state.get("current", 0) + 1
            self._shared_state["current"] = current
            self._shared_state["max"] = max(self._shared_state.get("max", 0), current)
        try:
            time.sleep(self._delay_s)
            return super().get_timeseries(
                start,
                end,
                queries,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )
        finally:
            with self._shared_lock:
                self._shared_state["current"] -= 1


class _PartialFallbackRouter(_FakeRouter):
    def __init__(self, mdp: Any, fallback_value: float = 0.052):
        super().__init__(auto_cols=False)
        self.mdp = mdp
        self.call_count = 0
        self.fallback_value = float(fallback_value)
        self.fallback_requests: List[List[Any]] = []

    def get_timeseries(self, start, end, queries, *, n_jobs=1, ignore_cache=False, freq=None, timestamps=None) -> pd.DataFrame:
        _ = start, end, n_jobs, ignore_cache, freq
        self.call_count += 1
        if timestamps:
            points = list(timestamps)
        else:
            points = pd.bdate_range(start, end).date.tolist()
        self.fallback_requests.append(list(points))
        idx = pd.Index(points, name=self.date_col)
        return pd.DataFrame(
            {
                q.col_name(): [self.fallback_value] * len(idx)
                for q in queries
            },
            index=idx,
        )


class _FakeIRSCurveStore:
    def __init__(self, timestamps: List[datetime.datetime], analytics_df: Optional[pd.DataFrame] = None):
        self.timestamps = list(timestamps)
        self.analytics_df = analytics_df if analytics_df is not None else pd.DataFrame()
        self.raw_reads: List[Dict[str, Any]] = []
        self.raw_day_reads: List[Tuple[str, datetime.date]] = []
        self.analytics_reads: List[Tuple[str, datetime.date, datetime.date]] = []
        self.analytics_column_requests: List[Optional[List[str]]] = []
        self.reconstruct_workers: List[int] = []

    def read_analytics(self, curve_name: str, *, start=None, end=None, tenors=None, metrics=None, timestamps_utc=None, columns=None) -> pd.DataFrame:
        _ = tenors, metrics, timestamps_utc
        self.analytics_reads.append((curve_name, start, end))
        self.analytics_column_requests.append(list(columns) if columns is not None else None)
        return self.analytics_df.copy()

    def read_raw_nodes(
        self,
        curve_name: str,
        *,
        start=None,
        end=None,
        session_minute_min=None,
        session_minute_max=None,
        timestamps_utc=None,
    ) -> pd.DataFrame:
        self.raw_reads.append(
            {
                "curve_name": curve_name,
                "start": start,
                "end": end,
                "session_minute_min": session_minute_min,
                "session_minute_max": session_minute_max,
                "timestamps_utc": list(timestamps_utc or []),
            }
        )
        rows = [pd.Timestamp(ts.astimezone(datetime.timezone.utc)) for ts in self.timestamps]
        if timestamps_utc:
            requested = {
                pd.Timestamp(ts.astimezone(datetime.timezone.utc).replace(microsecond=0))
                for ts in timestamps_utc
            }
            rows = [ts for ts in rows if ts.replace(microsecond=0) in requested]
        return pd.DataFrame(
            {
                "timestamp_utc": rows,
                "trading_date": [ts.date() for ts in rows],
            }
        )

    def read_raw_day(self, curve_name: str, trading_date: datetime.date) -> pd.DataFrame:
        self.raw_day_reads.append((curve_name, trading_date))
        chi = pytz.timezone("America/Chicago")
        return pd.DataFrame(
            {
                "timestamp_utc": [
                    pd.Timestamp(ts.astimezone(datetime.timezone.utc))
                    for ts in self.timestamps
                    if (
                        (ts.astimezone(chi) + datetime.timedelta(days=1)).date()
                        if ts.astimezone(chi).hour >= 17
                        else ts.astimezone(chi).date()
                    ) == trading_date
                ],
                "trading_date": [trading_date for _ in range(sum(
                    1
                    for ts in self.timestamps
                    if (
                        (ts.astimezone(chi) + datetime.timedelta(days=1)).date()
                        if ts.astimezone(chi).hour >= 17
                        else ts.astimezone(chi).date()
                    ) == trading_date
                ))],
            }
        )

    def reconstruct_curves_batch(
        self,
        df: pd.DataFrame,
        *,
        cfg=None,
        max_workers: int = 4,
        progress_callback=None,
    ) -> Dict[datetime.datetime, Any]:
        _ = cfg
        self.reconstruct_workers.append(max_workers)
        result = {}
        for row in df.itertuples(index=False):
            result[row.timestamp_utc.to_pydatetime().replace(tzinfo=datetime.timezone.utc)] = (
                f"curve::{row.timestamp_utc.isoformat()}"
            )
            if progress_callback is not None:
                progress_callback(1)
        return result


class _FakeIRSCurveStoreMDP:
    def __init__(
        self,
        store: _FakeIRSCurveStore,
        source: str = "BARCHART_STIRF-RL",
        *,
        bulk_results: Optional[Dict[Any, Any]] = None,
    ):
        self.source = source
        self._store = store
        self.resolve_calls: List[Tuple[str, Dict[str, Any]]] = []
        self.wrap_calls: List[Tuple[str, str, Any]] = []
        self.bulk_calls = 0
        self.bulk_results = dict(bulk_results or {})
        self.bulk_requests: List[Dict[str, Any]] = []

    def _is_barchart_source(self) -> bool:
        return self.source.upper().startswith("BARCHART_STIRF")

    def _get_curve_store(self):
        return self._store

    def _supports_curve_store_fast_path(self):
        return True

    def _supports_curve_store_raw_curve_fast_path(self):
        return not self.source.upper().startswith("ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")

    def _supports_curve_store_analytics_fast_path(self):
        return True

    def _get_curve_store_builder(self):
        return self._get_barchart_stirf_curve_builder() if self._is_barchart_source() else None

    def _get_barchart_stirf_curve_builder(self):
        return SimpleNamespace(
            _STIRF_CURVE_CONFIGS={
                "USD-SOFR-Q12": {"reference_key": "USD-SOFR-1D"}
            }
        )

    def _resolve_barchart_stirf_curve_name(self, requested_curve_name: str, kwargs: Dict[str, Any], builder: Any) -> str:
        _ = builder
        self.resolve_calls.append((requested_curve_name, dict(kwargs)))
        return "USD-SOFR-Q12"

    def _resolve_curve_store_curve_name(self, requested_curve_name: str, kwargs: Dict[str, Any], builder: Any = None) -> str:
        if self._is_barchart_source():
            return self._resolve_barchart_stirf_curve_name(requested_curve_name, kwargs, builder)
        self.resolve_calls.append((requested_curve_name, dict(kwargs)))
        return requested_curve_name

    def _to_barchart_stirf_timestamp(self, timestamp: datetime.datetime) -> datetime.datetime:
        if isinstance(timestamp, datetime.datetime):
            if timestamp.tzinfo is None:
                return timestamp.replace(tzinfo=datetime.timezone.utc)
            return timestamp.astimezone(datetime.timezone.utc)
        return datetime.datetime.combine(timestamp, datetime.time(17, 0), tzinfo=datetime.timezone.utc)

    def _to_curve_store_timestamp(self, timestamp: Any) -> datetime.datetime:
        if self._is_barchart_source():
            return self._to_barchart_stirf_timestamp(timestamp)
        if isinstance(timestamp, datetime.datetime):
            dt = timestamp.astimezone(datetime.timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=datetime.timezone.utc)
            return datetime.datetime(dt.year, dt.month, dt.day, 20, 0, tzinfo=datetime.timezone.utc)
        return datetime.datetime.combine(timestamp, datetime.time(20, 0), tzinfo=datetime.timezone.utc)

    def _build_barchart_stirf_rl_curve(
        self,
        *,
        requested_curve_name: str,
        resolved_curve_name: str,
        request_timestamp: Any,
        rl_curve_handle: Any,
        builder: Any,
        fixings_cache: Any = None,
    ):
        _ = request_timestamp, builder, fixings_cache
        self.wrap_calls.append((requested_curve_name, resolved_curve_name, rl_curve_handle))
        return {
            "requested_curve_name": requested_curve_name,
            "resolved_curve_name": resolved_curve_name,
            "curve": rl_curve_handle,
        }

    def _wrap_curve_store_curve(
        self,
        *,
        requested_curve_name: str,
        resolved_curve_name: str,
        request_timestamp: Any,
        rl_curve_handle: Any,
        builder: Any = None,
        fixings_cache: Any = None,
    ):
        return self._build_barchart_stirf_rl_curve(
            requested_curve_name=requested_curve_name,
            resolved_curve_name=resolved_curve_name,
            request_timestamp=request_timestamp,
            rl_curve_handle=rl_curve_handle,
            builder=builder,
            fixings_cache=fixings_cache,
        )

    def bulk_get_data(self, request: Dict[str, Any]) -> Dict[Any, Any]:
        self.bulk_calls += 1
        self.bulk_requests.append(dict(request))
        timestamps = list(request.get("timestamps", []) or [])
        return {
            ts: self.bulk_results[ts]
            for ts in timestamps
            if ts in self.bulk_results
        }


class _MockSTIRFuturePricable(_STIRFutureGenericPricable):
    def __init__(self, price: float = 95.125):
        self._price = float(price)
        self._fixed_rate = 100.0 - self._price

    def effective_date(self) -> datetime.date:
        return datetime.date(2026, 1, 1)

    def maturity_date(self) -> datetime.date:
        return datetime.date(2026, 3, 31)

    def price(self) -> float:
        return self._price

    def fixed_rate(self) -> float:
        return self._fixed_rate

    def set_fixed_rate(self, rate_decimal: float) -> None:
        self._fixed_rate = float(rate_decimal) * 100.0
        self._price = 100.0 - self._fixed_rate

    def nominal(self) -> float:
        return 1_000_000.0

    def with_notional(self, notional: float) -> "_STIRFutureGenericPricable":
        _ = notional
        return self

    def fair_rate(self) -> float:
        return self._fixed_rate / 100.0

    def npv(self) -> float:
        return self._price

    def pv01(self) -> float:
        return 1.0

    def dv01(self, shift: float = 1e-4) -> float:
        _ = shift
        return 1.0

    def gamma(self, shift: float = 1e-4) -> float:
        _ = shift
        return 0.0

    def dollar_carry(self, horizon: str) -> float:
        _ = horizon
        return 0.0

    def carry_bps_running(self, horizon: str) -> float:
        _ = horizon
        return 0.0

    def roll_bps_running(self, horizon: str) -> float:
        _ = horizon
        return 0.0

    def carry_and_roll_bps_running(self, horizon: str) -> float:
        _ = horizon
        return 0.0


class _MockSTIRFuturePricer(_STIRFutureGenericPricer):
    def __init__(self, symbol: str, price: float = 95.125):
        self._symbol = symbol
        self._price = float(price)

    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> datetime.date:
        return datetime.date(2026, 1, 2)

    def calendar(self) -> Any:
        return None

    def calendar_advance(self, dt1: datetime.date, dt2: datetime.date) -> datetime.date:
        _ = dt2
        return dt1

    def handle(self) -> Any:
        return None

    def index(self) -> Any:
        return None

    def meta(self) -> Any:
        return {}

    def effective_date(self, stirf: _STIRFutureGenericPricable = None) -> datetime.date:
        _ = stirf
        return datetime.date(2026, 1, 1)

    def maturity_date(self, stirf: _STIRFutureGenericPricable = None) -> datetime.date:
        _ = stirf
        return datetime.date(2026, 3, 31)

    def fixed_rate(self, stirf: _STIRFutureGenericPricable = None) -> float:
        _ = stirf
        return 100.0 - self._price

    def set_fixed_rate(self, stirf: _STIRFutureGenericPricable = None, rate_decimal: float = 0.0) -> None:
        _ = stirf, rate_decimal

    def notional(self, stirf: _STIRFutureGenericPricable = None) -> float:
        _ = stirf
        return 1_000_000.0

    def fair_rate(self, stirf: _STIRFutureGenericPricable = None) -> float:
        _ = stirf
        return (100.0 - self._price) / 100.0

    def npv(self, stirf: _STIRFutureGenericPricable = None) -> float:
        _ = stirf
        return self._price

    def pv01(self, stirf: _STIRFutureGenericPricable = None, contracts=None, notional=None) -> float:
        _ = stirf, contracts, notional
        return 1.0

    def dv01(self, stirf: _STIRFutureGenericPricable = None, shift: float = 1e-4) -> float:
        _ = stirf, shift
        return 1.0

    def gamma(self, stirf: _STIRFutureGenericPricable = None, shift: float = 1e-4) -> float:
        _ = stirf, shift
        return 0.0

    def dollar_carry(self, stirf: _STIRFutureGenericPricable = None, horizon: str = "1M") -> float:
        _ = stirf, horizon
        return 0.0

    def carry_bps_running(self, stirf: _STIRFutureGenericPricable = None, horizon: str = "1M") -> float:
        _ = stirf, horizon
        return 0.0

    def roll_bps_running(self, stirf: _STIRFutureGenericPricable = None, horizon: str = "1M") -> float:
        _ = stirf, horizon
        return 0.0

    def carry_and_roll_bps_running(self, stirf: _STIRFutureGenericPricable = None, horizon: str = "1M") -> float:
        _ = stirf, horizon
        return 0.0

    def resolve_pricable(self, stirf: _STIRFutureGenericPricable, risk_weight: Optional[float] = None) -> _STIRFutureGenericPricable:
        _ = risk_weight
        return stirf

    def build_pricable(self, /, **kwargs: Any) -> _STIRFutureGenericPricable:
        price = kwargs.get("price")
        if price is None:
            price = self._price
        return _MockSTIRFuturePricable(price=price)

    def build_stirf(
        self,
        fwd: Optional[str] = None,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_ser: Optional[bool] = False,
    ) -> Any:
        _ = fwd, tenor, effective_date, maturity_date, fixed_rate, notional, bpv, is_ser
        return _MockSTIRFuturePricable(price=self._price)

    def price(self) -> float:
        return self._price


class _MockUSTFuturePricable(_USTFutureGenericPricable):
    def __init__(self, symbol: str, price: float = 110.5):
        self._symbol = symbol
        self._price = float(price)

    def contract_code(self) -> str:
        return self._symbol

    def effective_date(self) -> datetime.date:
        return datetime.date(2026, 1, 1)

    def maturity_date(self) -> datetime.date:
        return datetime.date(2026, 12, 31)

    def price(self) -> float:
        return self._price

    def contracts(self) -> int:
        return 1

    def notional(self) -> float:
        return 100_000.0


class _MockUSTFuturePricer(_USTFutureGenericPricer):
    def __init__(self, symbol: str, price: float = 110.5):
        self._symbol = symbol
        self._price = float(price)

    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> datetime.date:
        return datetime.date(2026, 1, 2)

    def meta(self) -> Any:
        return {}

    def effective_date(self, ustf: _USTFutureGenericPricable) -> datetime.date:
        return ustf.effective_date()

    def maturity_date(self, ustf: _USTFutureGenericPricable) -> datetime.date:
        return ustf.maturity_date()

    def price(self, ustf: _USTFutureGenericPricable) -> float:
        _ = ustf
        return self._price

    def yield_to_maturity(self, ustf: _USTFutureGenericPricable) -> float:
        _ = ustf
        return 0.04

    def pv01(self, ustf: _USTFutureGenericPricable) -> float:
        _ = ustf
        return 1.0

    def dv01(self, ustf: _USTFutureGenericPricable) -> float:
        _ = ustf
        return 1.0

    def npv(self, instrument: _USTFutureGenericPricable, /, **kwargs: Any) -> float:
        _ = instrument, kwargs
        return self._price

    def resolve_pricable(self, ustf: _USTFutureGenericPricable, risk_weight: Optional[float] = None) -> _USTFutureGenericPricable:
        _ = risk_weight
        return ustf

    def build_pricable(self, /, **kwargs: Any) -> _USTFutureGenericPricable:
        symbol = kwargs.get("contract_code", self._symbol)
        price = kwargs.get("price")
        if price is None:
            price = self._price
        return _MockUSTFuturePricable(symbol=symbol, price=price)

    def build_ustf(
        self,
        contract_code: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        _ = effective_date, maturity_date, contracts, notional, kwargs
        return _MockUSTFuturePricable(symbol=contract_code or self._symbol, price=price or self._price)


def _mk_option_pricer(symbol: str, price: float = 0.21) -> QLSTIRFutureOptionPricer:
    right = symbol[-1].upper()
    strike = float(int(symbol.split("|", 1)[1][:-1])) / 100.0
    return QLSTIRFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=symbol.split("|", 1)[0],
        strike=strike,
        quote_timestamp=datetime.datetime(2026, 1, 2, 17, 0, tzinfo=datetime.timezone.utc),
        expiry_date=datetime.date(2026, 12, 16),
        market_price=price,
        model_price=price,
        iv_normal=0.8,
        delta=0.5,
        gamma=0.3,
        vega=0.1,
        theta=-0.02,
        forward=96.0,
        discount=0.99,
        meta_data={},
    )


def _mk_ust_option_pricer(symbol: str, price: float = 1.20) -> QLUSTFutureOptionPricer:
    right = symbol[-1].upper()
    contract, tail = symbol.split("|", 1)
    strike = float(decode_strike_token(contract_or_root=contract, strike_token=tail[:-1]))
    return QLUSTFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=contract,
        strike=strike,
        quote_timestamp=datetime.datetime(2026, 1, 2, 17, 0, tzinfo=datetime.timezone.utc),
        expiry_date=datetime.date(2026, 12, 16),
        market_price=price,
        model_price=price,
        iv_normal=1.0,
        delta=0.5 if right == "C" else -0.5,
        gamma=0.3,
        vega=0.1,
        theta=-0.02,
        forward=112.5,
        discount=0.99,
        meta_data={},
    )


class _MockSTIRFutureMDP(MarketDataProvider):
    def __init__(self, price: float = 95.125):
        super().__init__(source="MOCK_STIR")
        self.price = float(price)

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[_MockSTIRFuturePricer]]:
        symbols = request.get("symbols", [])
        return {sym: [_MockSTIRFuturePricer(sym, price=self.price)] for sym in symbols}


class _BulkAwareSTIRFutureMDP(_MockSTIRFutureMDP):
    def __init__(self, price: float = 95.125):
        super().__init__(price=price)
        self.get_pricer_calls = 0
        self.get_bulk_data_calls = 0
        self.bulk_requests: List[Dict[str, Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[_MockSTIRFuturePricer]]:
        self.get_pricer_calls += 1
        return super().get_pricer(request)

    def get_bulk_data(self, request: Dict[str, Any]) -> Dict[datetime.date, Dict[str, List[_MockSTIRFuturePricer]]]:
        self.get_bulk_data_calls += 1
        self.bulk_requests.append(dict(request))
        timestamps = list(request.get("timestamps", []) or [])
        symbols = list(request.get("symbols", []) or [])
        return {
            ts: {sym: [_MockSTIRFuturePricer(sym, price=self.price)] for sym in symbols}
            for ts in timestamps
        }


class _MockFixedRateBondMDP(MarketDataProvider):
    def __init__(self):
        super().__init__(source="MOCK_FRB")

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {}


class _MockUSTFutureMDP(MarketDataProvider):
    def __init__(self, price: float = 110.5):
        super().__init__(source="MOCK_UST")
        self.price = float(price)

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, _MockUSTFuturePricer]:
        symbols = request.get("symbols", [])
        return {sym: _MockUSTFuturePricer(sym, price=self.price) for sym in symbols}


class _MockSTIRFutureOptionMDP(MarketDataProvider):
    def __init__(self, price: float = 0.21):
        super().__init__(source="MOCK_STIR_OPT")
        self.price = float(price)

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[QLSTIRFutureOptionPricer]]:
        symbols = request.get("symbols", [])
        return {sym: [_mk_option_pricer(sym, price=self.price)] for sym in symbols}


class _MockUSTFutureOptionMDP(MarketDataProvider):
    def __init__(self, price: float = 1.20):
        super().__init__(source="MOCK_UST_OPT")
        self.price = float(price)

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[QLUSTFutureOptionPricer]]:
        symbols = request.get("symbols", [])
        return {sym: [_mk_ust_option_pricer(sym, price=self.price)] for sym in symbols}


class _FlakyUSTFutureOptionMDP(_MockUSTFutureOptionMDP):
    def __init__(self, price: float = 1.20, fail_dates: Optional[set[datetime.date]] = None):
        super().__init__(price=price)
        self.fail_dates = set(fail_dates or set())

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[QLUSTFutureOptionPricer]]:
        ts = request.get("timestamp")
        if isinstance(ts, datetime.datetime):
            ts = ts.date()
        if ts in self.fail_dates:
            raise ValueError(f"synthetic ust option failure for {ts}")
        return super().get_pricer(request)


class _ForceRefreshOnceUSTFutureOptionMDP(_MockUSTFutureOptionMDP):
    def __init__(self, price: float = 1.20):
        super().__init__(price=price)
        self.force_refresh_calls = 0
        self.force_refresh_flags: List[bool] = []

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[QLUSTFutureOptionPricer]]:
        force_refresh = bool(request.get("force_refresh", False))
        self.force_refresh_flags.append(force_refresh)
        if force_refresh:
            self.force_refresh_calls += 1
            if self.force_refresh_calls > 1:
                raise ValueError("unexpected second forced refresh")
        return super().get_pricer(request)


class _RecordingDualUSTFutureOptionMDP(_MockUSTFutureOptionMDP):
    def __init__(self, price: float = 1.20):
        super().__init__(price=price)
        self.source = "USTFO_DUAL-QL"
        self.requests: List[Dict[str, Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[QLUSTFutureOptionPricer]]:
        self.requests.append(dict(request))
        return super().get_pricer(request)


@dataclass(frozen=True)
class _UnsupportedProductQuery(BaseQuery):
    fake_product: str = "UNKNOWN"

    def __post_init__(self):
        object.__setattr__(self, "product", self.fake_product)
        object.__setattr__(self, "structure_id", "OUTRIGHT")
        object.__setattr__(self, "value_id", "PRICE")

    def return_query(self) -> List[BaseQuery]:
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        return "unsupported"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        return "unsupported"


def _make_builder() -> Tuple[TimeseriesBuilder, _FakeRouter, _FakeRouter]:
    irs = _FakeRouter(auto_cols=True, auto_value=0.045)
    frb = _FakeRouter(auto_cols=True, auto_value=0.040)
    tb = TimeseriesBuilder(
        irswaps_tb=irs,
        fixedratebonds_tb=frb,
        stirfutures_tb=STIRFuturesTB(_MockSTIRFutureMDP(), show_tqdm=False),
        ustfutures_tb=USTFuturesTB(_MockUSTFutureMDP(), show_tqdm=False),
        stirfutureoptions_tb=STIRFutureOptionsTB(_MockSTIRFutureOptionMDP(), show_tqdm=False),
        ustfutureoptions_tb=USTFutureOptionsTB(_MockUSTFutureOptionMDP(), show_tqdm=False),
    )
    return tb, irs, frb


START = datetime.date(2025, 1, 6)
END = datetime.date(2025, 1, 10)


def test_mixed_product_routing_joins_output_columns():
    tb, _, _ = _make_builder()
    irs_q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)
    stir_q = STIRFutureQuery(symbol="SR3H26", curve="USD-SOFR-1D", value=STIRFutureValue.PRICE)

    out = tb.get_timeseries(start=START, end=END, queries=[irs_q, stir_q])

    assert not out.empty
    assert irs_q.col_name() in out.columns
    assert stir_q.col_name() in out.columns


def test_timeseries_builder_normalizes_unified_irs_queries_before_special_routing():
    irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
    tb = TimeseriesBuilder(irswaps_tb=irs_router)
    unified = UnifiedQuery(
        structure=UnifiedStructure.IRS_OUTRIGHT,
        value=UnifiedValue.IRS_RATE,
        selector={"curve": "USD-SOFR-1D", "tenor": "5Y"},
    )

    out = tb.get_timeseries(start=START, end=END, queries=[unified])

    assert not out.empty
    assert irs_router.received_queries
    assert all(isinstance(q, IRSwapQuery) for q in irs_router.received_queries)


def test_base_timeseries_tb_prefers_bulk_mdp_fetch_when_available():
    mdp = _BulkAwareSTIRFutureMDP(price=95.25)
    tb = STIRFuturesTB(mdp, show_tqdm=False)
    q = STIRFutureQuery(symbol="SR3H26", curve="USD-SOFR-1D", value=STIRFutureValue.PRICE)

    out = tb.get_timeseries(start=START, end=END, queries=[q])

    assert not out.empty
    assert mdp.get_bulk_data_calls == 1
    assert mdp.get_pricer_calls == 0
    assert len(mdp.bulk_requests) == 1
    assert mdp.bulk_requests[0]["timestamps"] == pd.bdate_range(START, END).date.tolist()


def test_timeseries_builder_uses_curve_store_fast_path_for_irs_intraday(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1, ts2])
    mdp = _FakeIRSCurveStoreMDP(store)
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05 if ref_dt == ts1 else 0.051),
    )

    out = tb.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2], n_jobs=4)

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [0.05, 0.051]
    assert router.call_count == 0
    assert len(store.raw_reads) == 1
    assert store.raw_reads[0]["curve_name"] == "USD-SOFR-Q12"
    assert store.raw_reads[0]["start"] == ts1.date()
    assert store.raw_reads[0]["end"] == ts2.date()
    assert store.raw_reads[0]["session_minute_min"] == 120
    assert store.raw_reads[0]["session_minute_max"] == 180
    assert store.raw_reads[0]["timestamps_utc"] == [ts1, ts2]
    assert store.reconstruct_workers == [4]
    assert mdp.wrap_calls


def test_timeseries_builder_routes_alias_backed_irs_queries_away_from_curve_store():
    mdp = _FakeIRSCurveStoreMDP(_FakeIRSCurveStore([]), source="ERIS_EOD_LIVE-RL_BASIC")
    router = _FakeRouter(auto_cols=True, auto_value=0.045)
    router.mdp = mdp
    tb = TimeseriesBuilder(irswaps_tb=router)

    benchmark_q = IRSwapQuery(curve="USD-SOFR-1D", tenor="7Y/20Y", value=IRSwapValue.RATE)
    alias_q = IRSwapQuery(curve="USD-SOFR-1D", tenor="CT7/CT20", value=IRSwapValue.RATE)

    benchmark_plan = tb._build_request_plan(
        flat_queries=[benchmark_q],
        merged_routers={"IRS": router},
        merged_mdps={},
        start=START,
        end=END,
        ignore_cache=False,
        freq=None,
        timestamps=None,
    )
    alias_plan = tb._build_request_plan(
        flat_queries=[alias_q],
        merged_routers={"IRS": router},
        merged_mdps={},
        start=START,
        end=END,
        ignore_cache=False,
        freq=None,
        timestamps=None,
    )

    assert len(benchmark_plan.product_plans) == 1
    assert benchmark_plan.product_plans[0].strategy == "irs_curve_store"
    assert len(alias_plan.product_plans) == 1
    assert alias_plan.product_plans[0].strategy == "route"


def test_timeseries_builder_curve_store_fast_path_shows_pricing_tqdm_by_default(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module
    import TB.TimeseriesBuilder as ts_builder_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1, ts2])
    mdp = _FakeIRSCurveStoreMDP(store)
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    calls = []

    class _RecordingTqdm:
        def __init__(self, iterable=None, **kwargs):
            self.iterable = iterable
            self.kwargs = kwargs
            self.updates: List[int] = []
            self.n = 0
            calls.append(self)

        def __iter__(self):
            if self.iterable is None:
                return iter(())
            return iter(self.iterable)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def update(self, n=1):
            inc = int(n)
            self.updates.append(inc)
            self.n += inc

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05 if ref_dt == ts1 else 0.051),
    )
    monkeypatch.setattr(ts_builder_module, "_tqdm", _RecordingTqdm)

    out = tb.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2], n_jobs=2)

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [0.05, 0.051]
    assert calls
    raw_curve_calls = [call for call in calls if "LOADING" in call.kwargs.get("desc", "")]
    assert raw_curve_calls
    assert raw_curve_calls[0].kwargs["disable"] is False
    assert raw_curve_calls[0].kwargs["total"] == 2
    assert raw_curve_calls[0].updates == [1, 1]
    pricing_calls = [call for call in calls if "curve-store" in call.kwargs.get("desc", "")]
    assert pricing_calls
    assert pricing_calls[0].kwargs["disable"] is False
    assert pricing_calls[0].kwargs["total"] == 2
    assert sum(pricing_calls[0].updates) == 2


def test_timeseries_builder_curve_store_fast_path_filters_out_of_session_intraday_minutes(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    chi = pytz.timezone("America/Chicago")
    start = chi.localize(datetime.datetime(2025, 1, 6, 15, 58))
    end = chi.localize(datetime.datetime(2025, 1, 6, 17, 2))
    expected_points = [
        chi.localize(datetime.datetime(2025, 1, 6, 15, 58)),
        chi.localize(datetime.datetime(2025, 1, 6, 15, 59)),
        chi.localize(datetime.datetime(2025, 1, 6, 16, 0)),
        chi.localize(datetime.datetime(2025, 1, 6, 17, 0)),
        chi.localize(datetime.datetime(2025, 1, 6, 17, 1)),
        chi.localize(datetime.datetime(2025, 1, 6, 17, 2)),
    ]
    store = _FakeIRSCurveStore(expected_points)
    mdp = _FakeIRSCurveStoreMDP(store)
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05),
    )

    out = tb.get_timeseries(start=start, end=end, queries=[q], freq="1min", n_jobs=2)

    assert list(out.index) == expected_points
    assert list(out[q.col_name()]) == [0.05] * len(expected_points)
    assert router.call_count == 0


def test_timeseries_builder_route_skips_all_out_of_session_barchart_irs_requests():
    chi = pytz.timezone("America/Chicago")
    start = chi.localize(datetime.datetime(2025, 1, 6, 16, 1))
    end = chi.localize(datetime.datetime(2025, 1, 6, 16, 59))
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    class _FailIfCalledRouter:
        def __init__(self):
            self.mdp = SimpleNamespace(source="BARCHART_STIRF-RL")
            self.call_count = 0

        def get_timeseries(self, *args, **kwargs) -> pd.DataFrame:
            self.call_count += 1
            raise AssertionError("out-of-session BARCHART IRS requests should be discarded before routing")

    router = _FailIfCalledRouter()
    tb = TimeseriesBuilder(irswaps_tb=router)

    out = tb.get_timeseries(start=start, end=end, queries=[q], freq="1min", ignore_cache=True)

    assert out.empty
    assert router.call_count == 0


def test_timeseries_builder_curve_store_fast_path_supports_eod_freq_alias(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    nyc = pytz.timezone("America/New_York")
    start = nyc.localize(datetime.datetime(2025, 7, 28, 0, 1))
    end = nyc.localize(datetime.datetime(2025, 8, 1, 17, 0))
    expected_points = [
        nyc.localize(datetime.datetime(2025, 7, 28, 17, 0)),
        nyc.localize(datetime.datetime(2025, 7, 29, 17, 0)),
        nyc.localize(datetime.datetime(2025, 7, 30, 17, 0)),
        nyc.localize(datetime.datetime(2025, 7, 31, 17, 0)),
        nyc.localize(datetime.datetime(2025, 8, 1, 17, 0)),
    ]
    store = _FakeIRSCurveStore(expected_points)
    mdp = _FakeIRSCurveStoreMDP(store)
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="IMM_Z25xIMM_H26", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05),
    )

    out = tb.get_timeseries(start=start, end=end, queries=[q], freq="eod", n_jobs=2)

    assert list(out.index) == expected_points
    assert list(out[q.col_name()]) == [0.05] * len(expected_points)
    assert router.call_count == 0
    assert len(store.raw_reads) == 1
    assert store.raw_reads[0]["curve_name"] == "USD-SOFR-Q12"
    assert store.raw_reads[0]["start"] == datetime.date(2025, 7, 28)
    assert store.raw_reads[0]["end"] == datetime.date(2025, 8, 1)
    assert store.raw_reads[0]["session_minute_min"] == 600
    assert store.raw_reads[0]["session_minute_max"] == 600
    assert store.raw_reads[0]["timestamps_utc"] == expected_points


def test_timeseries_builder_curve_store_full_computed_cache_hit_skips_follow_on_work(monkeypatch, tmp_path):
    ts1 = datetime.date(2026, 1, 2)
    ts2 = datetime.date(2026, 1, 5)
    store = _FakeIRSCurveStore([])
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    router._computed_ts_store = ComputedTimeseriesStore(base_dir=tmp_path, use_duckdb=False)
    router._ts_symbol_for_query = lambda curve_name, q: f"IRS::{curve_name}::{q.tenor}::{q.value.name}"
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    router._computed_ts_store.append_rows(
        symbol=router._ts_symbol_for_query(q.curve, q),
        rows=[
            (ts1, q.col_name(), 4.25),
            (ts2, q.col_name(), 4.30),
        ],
    )

    monkeypatch.setattr(
        tb,
        "_write_irs_computed_cache_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("computed cache write should not run on cache hit")),
    )

    out = tb.get_timeseries(
        start=ts1,
        end=ts2,
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0
    assert store.analytics_reads == []
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_curve_store_full_computed_cache_hit_scales_legacy_decimal_rows(tmp_path):
    ts1 = datetime.date(2026, 1, 2)
    ts2 = datetime.date(2026, 1, 5)
    store = _FakeIRSCurveStore([])
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    router._computed_ts_store = ComputedTimeseriesStore(base_dir=tmp_path, use_duckdb=False)
    router._ts_symbol_for_query = lambda curve_name, q: f"IRS::{curve_name}::{q.tenor}::{q.value.name}"
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    router._computed_ts_store.append_rows(
        symbol=router._ts_symbol_for_query(q.curve, q),
        rows=[
            (ts1, "10Y", 0.0425),
            (ts2, "10Y", 0.0430),
        ],
    )

    out = tb.get_timeseries(
        start=ts1,
        end=ts2,
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0
    assert store.analytics_reads == []
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_route_full_computed_cache_hit_skips_irs_router(monkeypatch, tmp_path):
    ts1 = datetime.date(2026, 1, 2)
    ts2 = datetime.date(2026, 1, 5)
    mdp = _FakeIRSCurveStoreMDP(_FakeIRSCurveStore([]), source="MOCK_IRS_ROUTE")
    monkeypatch.setattr(mdp, "_supports_curve_store_fast_path", lambda: False)
    router = _NoCallRouter(mdp)
    router._computed_ts_store = ComputedTimeseriesStore(base_dir=tmp_path / "irs-route", use_duckdb=False)
    router._ts_symbol_for_query = lambda curve_name, q: f"IRS::{curve_name}::{q.tenor}::{q.value.name}"
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    router._computed_ts_store.append_rows(
        symbol=router._ts_symbol_for_query(q.curve, q),
        rows=[
            (ts1, q.col_name(), 4.25),
            (ts2, q.col_name(), 4.30),
        ],
    )

    out = tb.get_timeseries(
        start=ts1,
        end=ts2,
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0
    assert mdp.bulk_calls == 0


def test_timeseries_builder_route_partial_computed_cache_hit_reuses_prefetched_irs_rows(monkeypatch, tmp_path):
    import TB.IRSwapsTB as irs_tb_module

    class _PartialCacheIRSMdp(MarketDataProvider):
        def __init__(self):
            super().__init__(source=f"TEST_IRS_PARTIAL_{uuid.uuid4().hex}")
            self.bulk_calls = 0
            self.bulk_requests: List[Dict[str, Any]] = []

        def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
            return dict(request)

        def bulk_get_data(self, request: Dict[str, Any]) -> Dict[datetime.date, str]:
            self.bulk_calls += 1
            self.bulk_requests.append(dict(request))
            return {
                ts: f"curve::{ts.isoformat()}"
                for ts in request["timestamps"]
            }

    ts1 = datetime.date(2025, 1, 6)
    ts2 = datetime.date(2025, 1, 7)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)
    mdp = _PartialCacheIRSMdp()
    router = IRSwapsTB(mdp, show_tqdm=False, ts_base_dir=str(tmp_path), use_duckdb=False)
    symbol = router._ts_symbol_for_query(q.curve, q)
    router._computed_ts_store.append_rows(
        symbol=symbol,
        rows=[(ts1, q.col_name(q.curve), 4.25)],
    )

    read_rows_calls = 0
    original_read_rows = router._computed_ts_store.read_rows

    def _record_read_rows(*args, **kwargs):
        nonlocal read_rows_calls
        read_rows_calls += 1
        return original_read_rows(*args, **kwargs)

    monkeypatch.setattr(router._computed_ts_store, "read_rows", _record_read_rows)
    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(q.curve), 4.25 if ref_dt == ts1 else 4.30),
    )

    tb = TimeseriesBuilder(irswaps_tb=router)
    out = tb.get_timeseries(start=ts1, end=ts2, queries=[q], n_jobs=2)

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert read_rows_calls == 1
    assert mdp.bulk_calls == 1
    assert mdp.bulk_requests == [
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [ts2],
            "ignore_cache": False,
            "n_jobs": 2,
        }
    ]


def test_timeseries_builder_curve_store_fast_path_recovers_missing_points_via_bulk_mdp(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1])
    mdp = _FakeIRSCurveStoreMDP(store, bulk_results={ts2: "mdp::curve::2025-01-06T15:00:00+00:00"})
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.053 if str(curve).startswith("mdp::") else 0.05),
    )

    out = tb.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2], n_jobs=2)

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [0.05, 0.053]
    assert router.call_count == 0
    assert mdp.bulk_calls == 1
    assert mdp.bulk_requests == [
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [ts2],
            "ignore_cache": False,
            "n_jobs": 2,
        }
    ]


def test_timeseries_builder_curve_store_fast_path_reprices_without_forcing_raw_refetch(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([])
    mdp = _FakeIRSCurveStoreMDP(store, bulk_results={ts1: "mdp::curve::2025-01-06T14:00:00+00:00", ts2: "mdp::curve::2025-01-06T15:00:00+00:00"})
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05 if ref_dt == ts1 else 0.051),
    )

    out = tb.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2], n_jobs=2, ignore_cache=True)

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [0.05, 0.051]
    assert mdp.bulk_calls == 1
    assert mdp.bulk_requests == [
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [ts1, ts2],
            "ignore_cache": False,
            "n_jobs": 2,
        }
    ]


def test_timeseries_builder_curve_store_fast_path_falls_back_only_for_points_missing_after_bulk_recovery(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    ts3 = datetime.datetime(2025, 1, 6, 16, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1])
    mdp = _FakeIRSCurveStoreMDP(store, bulk_results={ts2: "mdp::curve::2025-01-06T15:00:00+00:00"})
    router = _PartialFallbackRouter(mdp, fallback_value=0.054)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.053 if str(curve).startswith("mdp::") else 0.05),
    )

    out = tb.get_timeseries(start=ts1, end=ts3, queries=[q], timestamps=[ts1, ts2, ts3], n_jobs=2)

    assert list(out.index) == [ts1, ts2, ts3]
    assert list(out[q.col_name()]) == [0.05, 0.053, 0.054]
    assert mdp.bulk_calls == 1
    assert mdp.bulk_requests == [
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [ts2, ts3],
            "ignore_cache": False,
            "n_jobs": 2,
        }
    ]
    assert router.call_count == 1
    assert router.fallback_requests == [[ts3]]


def test_timeseries_builder_curve_store_eod_fallback_does_not_emit_redundant_date_column(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1])
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _PartialFallbackRouter(mdp, fallback_value=0.052)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05),
    )

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert "Date" not in out.columns
    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == [0.05, 0.052]


def test_timeseries_builder_uses_eris_curve_analytics_fast_path_skips_usd_sofr_holidays():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_10Y": [4.25, 4.30],
            "rate_10Y": [4.25, 4.30],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0
    assert store.analytics_reads == [
        ("USD-SOFR-1D", datetime.date(2026, 1, 2), datetime.date(2026, 1, 5))
    ]
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_scales_legacy_eris_curve_analytics_decimals():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [780, 780],
            "par_rate_10Y": [pd.NA, pd.NA],
            "rate_10Y": [0.0425, 0.0430],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_route_full_computed_cache_hit_skips_frb_router_with_business_day_filter(tmp_path):
    import QuantLib as ql

    ts1 = datetime.date(2026, 1, 2)
    ts2 = datetime.date(2026, 1, 5)
    router = _NoCallRouter(_MockFixedRateBondMDP())
    router._computed_ts_store = ComputedTimeseriesStore(base_dir=tmp_path / "frb-route", use_duckdb=False)
    router._ts_symbol_for_query = lambda q: f"FRB::{q.cusip}::{q.value.name}"
    router._skip_non_business = True
    router._cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    tb = TimeseriesBuilder(fixedratebonds_tb=router)
    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)

    router._computed_ts_store.append_rows(
        symbol=router._ts_symbol_for_query(q),
        rows=[
            (ts1, q.col_name(), 4.25),
            (ts2, q.col_name(), 4.30),
        ],
    )

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0


def test_timeseries_builder_uses_eris_curve_analytics_fast_path():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_10Y": [4.25, 4.30],
            "rate_10Y": [4.25, 4.30],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert router.call_count == 0
    assert store.analytics_reads == [
        ("USD-SOFR-1D", datetime.date(2026, 1, 2), datetime.date(2026, 1, 5))
    ]
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_projects_only_needed_analytics_columns():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_7Y": [4.05, 4.10],
            "rate_7Y": [4.05, 4.10],
            "par_rate_20Y": [4.55, 4.60],
            "rate_20Y": [4.55, 4.60],
            "par_rate_30Y": [4.75, 4.80],
            "rate_30Y": [4.75, 4.80],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q7 = IRSwapQuery(curve="USD-SOFR-1D", tenor="7Y", value=IRSwapValue.RATE)
    q20 = IRSwapQuery(curve="USD-SOFR-1D", tenor="20Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q7, q20],
        n_jobs=2,
    )

    assert list(out[q7.col_name()]) == [4.05, 4.10]
    assert list(out[q20.col_name()]) == [4.55, 4.60]
    assert len(store.analytics_column_requests) == 1
    requested_columns = set(store.analytics_column_requests[0] or [])
    assert requested_columns == {
        "timestamp_utc",
        "trading_date",
        "session_minute",
        "par_rate_7Y",
        "rate_7Y",
        "par_rate_20Y",
        "rate_20Y",
    }
    assert "par_rate_30Y" not in requested_columns
    assert "rate_30Y" not in requested_columns


def test_timeseries_builder_uses_eris_curve_analytics_fast_path_for_curve_spreads():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_2Y": [3.80, 3.85],
            "rate_2Y": [3.80, 3.85],
            "par_rate_10Y": [4.25, 4.30],
            "rate_10Y": [4.25, 4.30],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y/10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == pytest.approx([45.0, 45.0])
    assert router.call_count == 0
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_scales_legacy_eris_curve_analytics_curve_spreads_to_bps():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [780, 780],
            "par_rate_2Y": [pd.NA, pd.NA],
            "rate_2Y": [0.0380, 0.0385],
            "par_rate_10Y": [pd.NA, pd.NA],
            "rate_10Y": [0.0425, 0.0430],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y/10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == pytest.approx([45.0, 45.0])
    assert router.call_count == 0
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_uses_eris_curve_analytics_fast_path_for_forward_fly_queries():
    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [780, 780],
            "par_rate_1Y2Y": [pd.NA, pd.NA],
            "rate_1Y2Y": [0.0400, 0.0405],
            "par_rate_1Y5Y": [pd.NA, pd.NA],
            "rate_1Y5Y": [0.0450, 0.0455],
            "par_rate_1Y10Y": [pd.NA, pd.NA],
            "rate_1Y10Y": [0.0500, 0.0505],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="1Y2Y/1Y5Y/1Y10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == pytest.approx([0.0, 0.0])
    assert router.call_count == 0
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_option_uses_vectorized_pricing_for_forward_fly_queries(monkeypatch):
    import Caching.eod_vectorized_engine as vectorized_engine

    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1, ts2], analytics_df=pd.DataFrame())
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    monkeypatch.setattr(mdp, "_curve_store_match_on_trading_date", lambda: True, raising=False)
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="1Y2Y/1Y5Y/1Y10Y", value=IRSwapValue.RATE)

    panel = pd.DataFrame(
        {
            "1Y2Y": [0.0400, 0.0405],
            "1Y5Y": [0.0460, 0.0465],
            "1Y10Y": [0.05075, 0.0510],
        },
        index=pd.DatetimeIndex(
            [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            name="trading_date",
        ),
    )

    monkeypatch.setattr(vectorized_engine, "compute_eod_rate_panel", lambda raw_nodes_df, tenors, **kwargs: panel)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
        use_irs_vectorized_pricing=True,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == pytest.approx([12.5, 15.0])
    assert store.raw_reads
    assert store.reconstruct_workers == []
    assert router.call_count == 0
    assert mdp.bulk_calls == 0


def test_timeseries_builder_get_timeseries_can_prebuild_irs_router_without_duckdb(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    captured: Dict[str, Any] = {}

    class _RecordingIRSwapsTB:
        def __init__(self, mdp, **kwargs):
            captured["mdp"] = mdp
            captured.update(kwargs)
            self.mdp = mdp

        def get_timeseries(self, start, end, queries, *, n_jobs=1, ignore_cache=False, freq=None, timestamps=None):
            _ = n_jobs, ignore_cache, freq, timestamps
            idx = pd.Index(pd.bdate_range(start, end).date.tolist(), name="Date")
            return pd.DataFrame(
                {queries[0].col_name(): [4.25] * len(idx)},
                index=idx,
            )

    monkeypatch.setattr(irs_tb_module, "IRSwapsTB", _RecordingIRSwapsTB)

    mdp = _FakeIRSCurveStoreMDP(_FakeIRSCurveStore([]), source="MOCK_IRS_ROUTE")
    monkeypatch.setattr(mdp, "_supports_curve_store_fast_path", lambda: False)
    tb = TimeseriesBuilder()
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        mdps={"IRS": mdp},
        use_duckdb=False,
    )

    assert captured["mdp"] is mdp
    assert captured["use_duckdb"] is False
    assert list(out[q.col_name()]) == [4.25, 4.25]


def test_timeseries_builder_uses_eris_curve_store_raw_fast_path_for_forward_fly_queries(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2026, 1, 2, 20, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 20, 0, tzinfo=datetime.timezone.utc)
    store = _FakeIRSCurveStore([ts1, ts2])
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="1Y5Y/1Y10Y/1Y30Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.05),
    )

    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 2),
        end=datetime.date(2026, 1, 5),
        queries=[q],
        n_jobs=2,
    )

    assert list(out.index) == [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)]
    assert list(out[q.col_name()]) == [0.05, 0.05]
    assert router.call_count == 0
    assert len(store.raw_reads) == 1
    assert store.raw_reads[0]["session_minute_min"] is None
    assert store.raw_reads[0]["session_minute_max"] is None
    assert store.raw_day_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_auto_parallelizes_large_eris_raw_curve_reconstruction(monkeypatch):
    import TB.IRSwapsTB as irs_tb_module
    import TB.TimeseriesBuilder as ts_builder_module

    business_days = pd.bdate_range(datetime.date(2026, 1, 2), periods=70).date.tolist()
    timestamps = [
        datetime.datetime.combine(day, datetime.time(20, 0), tzinfo=datetime.timezone.utc)
        for day in business_days
    ]
    store = _FakeIRSCurveStore(timestamps)
    mdp = _FakeIRSCurveStoreMDP(store, source="ERIS_EOD_LIVE-RL_BASIC")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="1Y5Y/1Y10Y/1Y30Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(), 12.5),
    )

    calls = []

    class _RecordingTqdm:
        def __init__(self, iterable=None, **kwargs):
            self.iterable = iterable
            self.kwargs = kwargs
            calls.append(self)

        def __iter__(self):
            if self.iterable is None:
                return iter(())
            return iter(self.iterable)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def update(self, n=1):
            _ = n

    monkeypatch.setattr(ts_builder_module, "_tqdm", _RecordingTqdm)

    out = tb.get_timeseries(
        start=business_days[0],
        end=business_days[-1],
        queries=[q],
    )

    assert len(out.index) >= 64
    assert store.reconstruct_workers
    assert store.reconstruct_workers[0] >= 2
    pricing_calls = [call for call in calls if "curve-store" in call.kwargs.get("desc", "")]
    assert pricing_calls
    assert "workers=1" not in pricing_calls[0].kwargs["desc"]
    assert router.call_count == 0
    assert mdp.bulk_calls == 0


def test_timeseries_builder_uses_barchart_stirt_analytics_fast_path_for_forward_start():
    ts1 = datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_1Y1Y": [4.05, 4.10],
            "rate_1Y1Y": [4.05, 4.10],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="BARCHART_STIRF-RL")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="1Y1Y", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
        end=datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
        queries=[q],
        n_jobs=2,
        timestamps=[
            datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
        ],
    )

    assert list(out.index) == [
        datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
        datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
    ]
    assert list(out[q.col_name()]) == [4.05, 4.10]
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_uses_barchart_stirt_analytics_fast_path_for_ranked_fomc():
    ts1 = datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_FOMC_1": [4.15, 4.20],
            "rate_FOMC_1": [4.15, 4.20],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="BARCHART_STIRF-RL")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="fomc_1", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
        end=datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
        queries=[q],
        n_jobs=2,
        timestamps=[
            datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
        ],
    )

    assert list(out[q.col_name()]) == [4.15, 4.20]
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_uses_barchart_stirt_analytics_fast_path_for_explicit_imm_pair():
    ts1 = datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc)
    analytics_df = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp(ts1), pd.Timestamp(ts2)],
            "trading_date": [datetime.date(2026, 1, 2), datetime.date(2026, 1, 5)],
            "session_minute": [480, 480],
            "par_rate_IMM_1xIMM_2": [4.25, 4.30],
            "rate_IMM_1xIMM_2": [4.25, 4.30],
        }
    )
    store = _FakeIRSCurveStore([], analytics_df=analytics_df)
    mdp = _FakeIRSCurveStoreMDP(store, source="BARCHART_STIRF-RL")
    router = _NoCallRouter(mdp)
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="IMM_H26xIMM_M26", value=IRSwapValue.RATE)

    out = tb.get_timeseries(
        start=datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
        end=datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
        queries=[q],
        n_jobs=2,
        timestamps=[
            datetime.datetime(2026, 1, 2, 15, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 5, 15, 0, tzinfo=datetime.timezone.utc),
        ],
    )

    assert list(out[q.col_name()]) == [4.25, 4.30]
    assert store.raw_reads == []
    assert mdp.bulk_calls == 0


def test_timeseries_builder_parallelizes_product_plans(monkeypatch):
    import TB.TimeseriesBuilder as ts_builder_module

    executors = []

    class _RecordingExecutor:
        def __init__(self, max_workers=None, thread_name_prefix=None):
            self.max_workers = max_workers
            self.thread_name_prefix = thread_name_prefix
            self.submitted = []
            executors.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def submit(self, fn, *args, **kwargs):
            fut = Future()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                fut.set_exception(exc)
            else:
                fut.set_result(result)
            self.submitted.append((fn, args, kwargs))
            return fut

    monkeypatch.setattr(ts_builder_module, "ThreadPoolExecutor", _RecordingExecutor)

    stir_router = _FakeRouter(auto_cols=True, auto_value=95.0)
    ust_router = _FakeRouter(auto_cols=True, auto_value=111.0)
    tb = TimeseriesBuilder(stirfutures_tb=stir_router, ustfutures_tb=ust_router)
    q_stir = STIRFutureQuery(symbol="SR3H26", curve="USD-SOFR-1D", value=STIRFutureValue.PRICE)
    q_ust = USTFutureQuery(symbol="TYM26", value=USTFutureValue.PRICE)

    out = tb.get_timeseries(start=START, end=END, queries=[q_stir, q_ust], n_jobs=4)

    assert not out.empty
    assert executors
    assert executors[0].max_workers == 2
    assert len(executors[0].submitted) == 2


def test_timeseries_builder_auto_wraps_frb_mdp_with_specialized_tb(monkeypatch):
    import TB.FixedRateBondsTB as frb_tb_module

    created = []

    class _RecordingFixedRateBondsTB:
        def __init__(self, mdp, *, date_col="Date", show_tqdm=True):
            self.mdp = mdp
            self.date_col = date_col
            self.show_tqdm = show_tqdm
            self.calls = []
            created.append(self)

        def get_timeseries(
            self,
            start,
            end,
            queries,
            *,
            n_jobs=1,
            ignore_cache=False,
            freq=None,
            timestamps=None,
        ) -> pd.DataFrame:
            self.calls.append(
                {
                    "start": start,
                    "end": end,
                    "queries": list(queries),
                    "n_jobs": n_jobs,
                    "ignore_cache": ignore_cache,
                    "freq": freq,
                    "timestamps": list(timestamps or []),
                }
            )
            idx = pd.Index(list(timestamps or []), name=self.date_col)
            return pd.DataFrame(
                {queries[0].col_name(): [4.25] * len(idx)},
                index=idx,
            )

    monkeypatch.setattr(frb_tb_module, "FixedRateBondsTB", _RecordingFixedRateBondsTB)

    mdp = _MockFixedRateBondMDP()
    tb = TimeseriesBuilder()
    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)

    out = tb.get_timeseries(
        start=ts1,
        end=ts2,
        queries=[q],
        mdps={"FRB": mdp},
        timestamps=[ts1, ts2],
        n_jobs=3,
    )

    assert not out.empty
    assert len(created) == 1
    assert created[0].mdp is mdp
    assert created[0].calls[0]["timestamps"] == [ts1, ts2]
    assert created[0].calls[0]["n_jobs"] == 3
    assert list(out.index) == [ts1, ts2]
    assert list(out[q.col_name()]) == [4.25, 4.25]


def test_irswaption_router_coverage():
    irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
    irswp_router = _FakeRouter(auto_cols=True, auto_value=0.012)
    frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)
    tb = TimeseriesBuilder(
        irswaps_tb=irs_router,
        irswaptions_tb=irswp_router,
        fixedratebonds_tb=frb_router,
    )

    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="5Y",
        value=IRSwaptionValue.NVOL,
    )
    out = tb.get_timeseries(start=START, end=END, queries=[q])
    assert q.col_name() in out.columns
    assert len(irswp_router.received_queries) == 1
    assert isinstance(irswp_router.received_queries[0], IRSwaptionQuery)


def test_stir_ust_option_integration_with_mock_mdps():
    tb, _, _ = _make_builder()
    q_stir = STIRFutureQuery(symbol="SR3H26", curve="USD-SOFR-1D", value=STIRFutureValue.PRICE)
    q_ust = USTFutureQuery(symbol="TYH26", value=USTFutureValue.PRICE)
    q_opt = STIRFutureOptionQuery(symbol="SR3H26|9700C", value=STIRFutureOptionValue.PRICE)
    q_uopt = USTFutureOptionQuery(symbol="ZNM26|1125C", value=USTFutureOptionValue.PRICE)

    out = tb.get_timeseries(start=START, end=END, queries=[q_stir, q_ust, q_opt, q_uopt])

    assert q_stir.col_name() in out.columns
    assert q_ust.col_name() in out.columns
    assert q_opt.col_name() in out.columns
    assert q_uopt.col_name() in out.columns
    assert out[q_stir.col_name()].tolist() == pytest.approx([95.125] * len(out))
    assert out[q_ust.col_name()].tolist() == pytest.approx([110.5] * len(out))
    assert out[q_opt.col_name()].tolist() == pytest.approx([0.21] * len(out))
    assert out[q_uopt.col_name()].tolist() == pytest.approx([1.20] * len(out))


def test_timeseries_builder_survives_single_ust_option_date_failure():
    fail_date = datetime.date(2025, 1, 8)
    irswp_router = _FakeRouter(auto_cols=True, auto_value=0.012)
    tb = TimeseriesBuilder(
        irswaptions_tb=irswp_router,
        ustfutureoptions_tb=USTFutureOptionsTB(
            _FlakyUSTFutureOptionMDP(fail_dates={fail_date}),
            show_tqdm=False,
        ),
    )

    q_irswp = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="5Y",
        value=IRSwaptionValue.NVOL,
    )
    q_uopt = USTFutureOptionQuery(symbol="ZNM26|1125C", value=USTFutureOptionValue.PRICE)

    out = tb.get_timeseries(start=START, end=END, queries=[q_irswp, q_uopt])

    assert q_irswp.col_name() in out.columns
    assert q_uopt.col_name() in out.columns
    assert fail_date in out.index
    assert pd.isna(out.loc[fail_date, q_uopt.col_name()])
    assert out.loc[fail_date, q_irswp.col_name()] == pytest.approx(0.012)

    surviving_dates = [d for d in out.index if d != fail_date]
    assert out.loc[surviving_dates, q_uopt.col_name()].tolist() == pytest.approx([1.20] * len(surviving_dates))


def test_ust_option_tb_ignore_cache_only_forces_first_window_fetch():
    mdp = _ForceRefreshOnceUSTFutureOptionMDP()
    tb = TimeseriesBuilder(
        ustfutureoptions_tb=USTFutureOptionsTB(
            mdp,
            show_tqdm=False,
        ),
    )

    q_uopt = USTFutureOptionQuery(symbol="ZNM26|1125C", value=USTFutureOptionValue.PRICE)

    out = tb.get_timeseries(start=START, end=END, queries=[q_uopt], ignore_cache=True)

    assert q_uopt.col_name() in out.columns
    assert out[q_uopt.col_name()].tolist() == pytest.approx([1.20] * len(out))
    assert mdp.force_refresh_calls == 1
    assert mdp.force_refresh_flags.count(True) == 1


def test_ust_option_tb_dual_cm_queries_use_scalar_option_snapshot_requests():
    mdp = _RecordingDualUSTFutureOptionMDP()
    ust_tb = USTFutureOptionsTB(
        mdp,
        show_tqdm=False,
    )

    q_uopt = USTFutureOptionQuery(symbol="TY_30|25DC", value=USTFutureOptionValue.PRICE)

    bulk = ust_tb._bulk_fetch(
        reference_points=[START, END],
        queries=[q_uopt],
        n_jobs=None,
        ignore_cache=False,
    )
    result_by_ref_group = bulk["result_by_ref_group"]

    assert len(result_by_ref_group) == 2
    assert all(req.get("endpoint") == "option_snapshot" for req in mdp.requests)
    assert all("window_start" not in req for req in mdp.requests)
    assert all("window_end" not in req for req in mdp.requests)
    assert all("bulk_timeseries" not in req for req in mdp.requests)


def test_ust_option_tb_forwards_show_tqdm_to_mdp_requests():
    mdp = _RecordingDualUSTFutureOptionMDP()
    ust_tb = USTFutureOptionsTB(
        mdp,
        show_tqdm=True,
    )

    q_uopt = USTFutureOptionQuery(symbol="TY_30|25DC", value=USTFutureOptionValue.PRICE)

    _ = ust_tb._bulk_fetch(
        reference_points=[START, END],
        queries=[q_uopt],
        n_jobs=None,
        ignore_cache=False,
    )

    assert mdp.requests
    assert all(req.get("show_tqdm") is True for req in mdp.requests)


def test_unknown_product_without_router_or_mdp_raises_clear_error():
    tb, _, _ = _make_builder()
    q = _UnsupportedProductQuery(fake_product="NONEXISTENT")
    with pytest.raises(KeyError) as exc_info:
        tb.get_timeseries(start=START, end=END, queries=[q])
    msg = str(exc_info.value)
    assert "NONEXISTENT" in msg
    assert "IRS" in msg
    assert "FRB" in msg


def test_fx_forward_query_guardrail_when_query_type_missing():
    tb, _, _ = _make_builder()
    q = _UnsupportedProductQuery(fake_product="FXFORWARD")
    with pytest.raises(NotImplementedError, match="not supported yet"):
        tb.get_timeseries(start=START, end=END, queries=[q])


def test_mmss_regression_routes_derived_irs_and_frb_queries():
    irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
    frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)
    tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

    q_mmss = IRSwapQuery(curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MMSS)
    out = tb.get_timeseries(start=START, end=END, queries=[q_mmss])

    assert not any(
        isinstance(q, IRSwapQuery) and q.value == IRSwapValue.MMSS
        for q in irs_router.received_queries
    )
    assert any(
        isinstance(q, IRSwapQuery) and q.value == IRSwapValue.RATE
        for q in irs_router.received_queries
    )
    assert any(
        isinstance(q, FixedRateBondQuery) and q.value == FixedRateBondValue.YTM
        for q in frb_router.received_queries
    )
    assert not out.empty


def test_spreadover_alias_mapping_regression_ct_vs_y():
    irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
    frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)
    tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.SPREADOVER)
    tb.get_timeseries(start=START, end=END, queries=[q])

    assert any(
        isinstance(x, FixedRateBondQuery) and x.cusip == "CT10"
        for x in frb_router.received_queries
    )
    assert any(
        isinstance(x, IRSwapQuery) and x.tenor == "10Y" and x.value == IRSwapValue.RATE
        for x in irs_router.received_queries
    )


def test_spreadover_component_fetches_run_in_parallel():
    shared_state = {"current": 0, "max": 0}
    shared_lock = threading.Lock()
    irs_router = _ConcurrentFakeRouter(
        shared_state,
        shared_lock,
        auto_cols=True,
        auto_value=0.045,
    )
    frb_router = _ConcurrentFakeRouter(
        shared_state,
        shared_lock,
        auto_cols=True,
        auto_value=0.040,
    )
    tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="7Y/20Y", value=IRSwapValue.SPREADOVER)
    out = tb.get_timeseries(start=START, end=END, queries=[q])

    assert not out.empty
    assert shared_state["max"] >= 2
    assert any(
        isinstance(x, FixedRateBondQuery) and x.cusip == "CT7/CT20"
        for x in frb_router.received_queries
    )
    assert any(
        isinstance(x, IRSwapQuery) and x.tenor == "7Y/20Y" and x.value == IRSwapValue.RATE
        for x in irs_router.received_queries
    )


def test_spreadover_reuses_existing_component_frames_and_only_fetches_missing_curve_components():
    irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
    frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)
    tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

    q_curve = IRSwapQuery(curve="USD-SOFR-1D", tenor="7Y/20Y", value=IRSwapValue.SPREADOVER)
    q_7y = IRSwapQuery(curve="USD-SOFR-1D", tenor="7Y", value=IRSwapValue.SPREADOVER)
    q_20y = IRSwapQuery(curve="USD-SOFR-1D", tenor="20Y", value=IRSwapValue.SPREADOVER)
    q_rate_7y = IRSwapQuery(curve="USD-SOFR-1D", tenor="7Y", value=IRSwapValue.RATE)
    q_rate_20y = IRSwapQuery(curve="USD-SOFR-1D", tenor="20Y", value=IRSwapValue.RATE)
    q_cash_7y = FixedRateBondQuery(cusip="CT7", value=FixedRateBondValue.YTM)
    q_cash_20y = FixedRateBondQuery(cusip="CT20", value=FixedRateBondValue.YTM)

    out = tb.get_timeseries(
        start=START,
        end=END,
        queries=[q_curve, q_7y, q_20y, q_rate_7y, q_rate_20y, q_cash_7y, q_cash_20y],
    )

    irs_rate_queries = [
        q
        for q in irs_router.received_queries
        if isinstance(q, IRSwapQuery) and q.value == IRSwapValue.RATE
    ]
    frb_ytm_queries = [
        q
        for q in frb_router.received_queries
        if isinstance(q, FixedRateBondQuery) and q.value == FixedRateBondValue.YTM
    ]

    assert sum(str(q.tenor) == "7Y" for q in irs_rate_queries) == 1
    assert sum(str(q.tenor) == "20Y" for q in irs_rate_queries) == 1
    assert sum(str(q.tenor) == "7Y/20Y" for q in irs_rate_queries) == 1
    assert sum(str(q.cusip) == "CT7" for q in frb_ytm_queries) == 1
    assert sum(str(q.cusip) == "CT20" for q in frb_ytm_queries) == 1
    assert sum(str(q.cusip) == "CT7/CT20" for q in frb_ytm_queries) == 1

    assert not out.empty
    assert float(out.iloc[0][q_7y.col_name()]) == pytest.approx(0.5)
    assert float(out.iloc[0][q_20y.col_name()]) == pytest.approx(0.5)
    assert float(out.iloc[0][q_curve.col_name()]) == pytest.approx(0.005)
