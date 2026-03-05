import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pandas as pd
import pytest

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValue
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer
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
    ) -> pd.DataFrame:
        _ = n_jobs, ignore_cache, freq, timestamps
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
