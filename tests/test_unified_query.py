import datetime as dt

import pytest

from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.MarketDataProvider import MarketDataProvider
from MDP.MultiProductMDP import MultiProductMDP
from Query.EventContracts.EventContractQuery import EventContractQuery
from Query.EventContracts.EventContractStructure import EventContractStructure
from Query.EventContracts.EventContractValue import EventContractValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FXForwards.FXForwardQuery import FXForwardQuery
from Query.FXForwards.FXForwardStructure import FXForwardStructure
from Query.FXForwards.FXForwardValue import FXForwardValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
from Query.Spreads.SpreadQuery import SpreadQuery
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue
from Query.STIRCapFloors.STIRCapFloorQuery import STIRCapFloorQuery
from Query.STIRCapFloors.STIRCapFloorStructure import STIRCapFloorStructure
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValue
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from Query.USTFutureOptions.USTFutureOptionStructure import USTFutureOptionStructure
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValue
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue
from Query.Unified import DESCRIPTOR_REGISTRY, UnifiedQuery, UnifiedStructure, UnifiedValue
from tests.test_arbitrary_pricing_propagation import (
    _IRCurveStub,
    _MockSTIRFuturePricer,
    _MockUSTFuturePricer,
    _SpreadPricerStub,
)


_LOCAL_STRUCTURE_ENUMS = (
    IRSwapStructure,
    IRSwaptionStructure,
    SpreadStructure,
    STIRCapFloorStructure,
    STIRFutureOptionStructure,
    STIRFutureStructure,
    USTFutureOptionStructure,
    USTFutureStructure,
    FixedRateBondStructure,
    FXForwardStructure,
    EventContractStructure,
)

_LOCAL_VALUE_ENUMS = (
    IRSwapValue,
    IRSwaptionValue,
    SpreadValue,
    STIRCapFloorValue,
    STIRFutureOptionValue,
    STIRFutureValue,
    USTFutureOptionValue,
    USTFutureValue,
    FixedRateBondValue,
    FXForwardValue,
    EventContractValue,
)


class _SpreadContext:
    def __init__(self):
        self.pricer_a = _SpreadPricerStub(0.04)
        self.pricer_b = _SpreadPricerStub(0.05)


class _RecordingMDP(MarketDataProvider):
    def __init__(self, name: str):
        super().__init__(name)
        self.requests = []

    def get_pricer(self, request):
        self.requests.append(dict(request))
        return object()


def _now():
    return dt.datetime(2026, 3, 16, 15, 0, 0)


def test_unified_structure_bindings_cover_every_local_member_once():
    records = DESCRIPTOR_REGISTRY.binding_records(kind="structure")
    assert len(records) == sum(len(enum_cls) for enum_cls in _LOCAL_STRUCTURE_ENUMS)
    assert len(records) == len({(product, local_name) for product, local_name, _ in records})
    assert len(records) == len({unified_name for _, _, unified_name in records})


def test_unified_value_bindings_cover_every_local_member_once():
    records = DESCRIPTOR_REGISTRY.binding_records(kind="value")
    assert len(records) == sum(len(enum_cls) for enum_cls in _LOCAL_VALUE_ENUMS)
    assert len(records) == len({(product, local_name) for product, local_name, _ in records})
    assert len(records) == len({unified_name for _, _, unified_name in records})


@pytest.mark.parametrize(
    ("query", "legacy_cls", "expected_product"),
    [
        (
            UnifiedQuery(structure=UnifiedStructure.IRS_OUTRIGHT, value=UnifiedValue.IRS_RATE, selector={"tenor": "5Y", "curve": "USD-SOFR-1D"}),
            IRSwapQuery,
            "IRS",
        ),
        (
            UnifiedQuery(product="IRSWAPTION", structure="RECEIVER", value="SPOT_NPV", selector={"curve": "USD-SOFR-1D", "expiry": "1Y", "tail": "5Y"}),
            IRSwaptionQuery,
            "IRSWAPTION",
        ),
        (
            UnifiedQuery(product="IRBASIS", structure="OUTRIGHT", value="SPREAD_BPS", selector={"tenor": "5Y", "curve_a": "USD-SOFR-1D", "curve_b": "USD-FEDFUNDS"}),
            SpreadQuery,
            "IRBASIS",
        ),
        (
            UnifiedQuery(product="STIRCAPFLOOR", structure="CAP", value="PRICE", selector={"curve": "USD-SOFR-1D", "expiry": "1Y", "tail": "3Y"}),
            STIRCapFloorQuery,
            "STIRCAPFLOOR",
        ),
        (
            UnifiedQuery(selector={"symbol": "SR3H26"}),
            STIRFutureQuery,
            "STIRFUTURE",
        ),
        (
            UnifiedQuery(selector={"symbol": "SFRU26|25DC"}),
            STIRFutureOptionQuery,
            "STIRFUTUREOPTION",
        ),
        (
            UnifiedQuery(selector={"symbol": "TYM26"}),
            USTFutureQuery,
            "USTFUTURE",
        ),
        (
            UnifiedQuery(selector={"symbol": "ZNM26|1125C"}),
            USTFutureOptionQuery,
            "USTFUTUREOPTION",
        ),
        (
            UnifiedQuery(value="CLEAN_PRICE", selector={"cusip": "91282CGK1", "curve": "UST"}),
            FixedRateBondQuery,
            "FRB",
        ),
        (
            UnifiedQuery(value="FORWARD_RATE", selector={"pair": "USDCAD", "tenor": "1M"}),
            FXForwardQuery,
            "FXFORWARD",
        ),
        (
            UnifiedQuery(product="EVENT", structure="OUTRIGHT", value="PRICE", selector={"ticker": "FED_CUT_2026"}),
            EventContractQuery,
            "EVENT",
        ),
    ],
)
def test_unified_query_translates_representative_products(query, legacy_cls, expected_product):
    legacy = query.to_legacy()
    assert isinstance(legacy, legacy_cls)
    assert legacy.product == expected_product


def test_unified_query_raises_for_ambiguous_structure_name_without_product():
    with pytest.raises(ValueError, match="Ambiguous structure 'OUTRIGHT'"):
        UnifiedQuery(structure="OUTRIGHT", value=UnifiedValue.IRS_RATE, selector={"tenor": "5Y"})


def test_unified_query_raises_for_ambiguous_value_name_without_product():
    with pytest.raises(ValueError, match="Ambiguous value 'PRICE'"):
        UnifiedQuery(value="PRICE", selector={"symbol": "TYM26"})


def test_unified_query_raises_for_ambiguous_product_resolution_after_translation():
    query = UnifiedQuery(selector={"curve": "USD-SOFR-1D", "expiry": "1Y", "tail": "3Y"})
    with pytest.raises(ValueError, match="ambiguous across products"):
        query.to_legacy()


@pytest.mark.parametrize(
    ("legacy_query", "unified_query"),
    [
        (
            IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.RATE, tenor="5Y", curve="USD-SOFR-1D", structure_kwargs={"bpv": 1_000_000}),
            UnifiedQuery(structure=UnifiedStructure.IRS_OUTRIGHT, value=UnifiedValue.IRS_RATE, selector={"tenor": "5Y", "curve": "USD-SOFR-1D"}, structure_kwargs={"bpv": 1_000_000}),
        ),
        (
            SpreadQuery(structure=SpreadStructure.OUTRIGHT, value=SpreadValue.SPREAD_BPS, tenor="5Y", curve_a="USD-SOFR-1D", curve_b="USD-FEDFUNDS"),
            UnifiedQuery(product="IRSPREAD", structure="OUTRIGHT", value="SPREAD_BPS", selector={"tenor": "5Y", "curve_a": "USD-SOFR-1D", "curve_b": "USD-FEDFUNDS"}),
        ),
        (
            STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE, symbol="SR3H26"),
            UnifiedQuery(structure=UnifiedStructure.STIRFUTURE_OUTRIGHT, value=UnifiedValue.STIRFUTURE_PRICE, selector={"symbol": "SR3H26"}),
        ),
        (
            USTFutureQuery(structure=USTFutureStructure.OUTRIGHT, value=USTFutureValue.PRICE, symbol="TYM26"),
            UnifiedQuery(structure=UnifiedStructure.USTFUTURE_OUTRIGHT, value=UnifiedValue.USTFUTURE_PRICE, selector={"symbol": "TYM26"}),
        ),
    ],
)
def test_unified_query_request_parity_matches_legacy_query(legacy_query, unified_query):
    now = _now()
    assert unified_query.to_legacy().__class__ is legacy_query.__class__
    assert unified_query.to_legacy().build_mdp_request(now) == legacy_query.build_mdp_request(now)


def test_unified_query_parity_for_irs_package_and_value_map():
    curve = _IRCurveStub()
    legacy = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.RATE,
        tenor="5Y",
        curve="USD-SOFR-1D",
        structure_kwargs={"bpv": 1_000_000},
    )
    unified = UnifiedQuery(
        structure=UnifiedStructure.IRS_OUTRIGHT,
        value=UnifiedValue.IRS_RATE,
        selector={"tenor": "5Y", "curve": "USD-SOFR-1D"},
        structure_kwargs={"bpv": 1_000_000},
    )

    legacy_pkg, legacy_weights = legacy.resolve_package(pricer_or_curve=curve)
    unified_pkg, unified_weights = unified.resolve_package(pricer_or_curve=curve)

    assert legacy_weights == unified_weights
    assert legacy_pkg[0].tenor == unified_pkg[0].tenor

    legacy_value = legacy.build_value_map(pricer_or_curve=curve, package=legacy_pkg, risk_weights=legacy_weights).apply(value=IRSwapValue.RATE)
    unified_value = unified.build_value_map(pricer_or_curve=curve, package=unified_pkg, risk_weights=unified_weights).apply(value=UnifiedValue.IRS_RATE)

    assert unified_value == pytest.approx(legacy_value)


def test_unified_query_accepts_direct_curve_and_tenor_fields():
    unified = UnifiedQuery(
        product="IRS",
        structure=UnifiedStructure.IRS_OUTRIGHT,
        value=UnifiedValue.IRS_RATE,
        curve="USD-SOFR-1D-Q12STIRT",
        tenor="IMM_Z26xIMM_H27",
    )

    assert unified.selector["curve"] == "USD-SOFR-1D-Q12STIRT"
    assert unified.selector["tenor"] == "IMM_Z26xIMM_H27"
    assert unified.curve == "USD-SOFR-1D-Q12STIRT"
    assert unified.tenor == "IMM_Z26xIMM_H27"

    legacy = unified.to_legacy()
    assert isinstance(legacy, IRSwapQuery)
    assert legacy.curve == "USD-SOFR-1D-Q12STIRT"
    assert legacy.tenor == "IMM_Z26xIMM_H27"


def test_unified_query_irs_imm_forward_tenor_resolves_as_outright():
    curve = _IRCurveStub()
    unified = UnifiedQuery(
        product="IRS",
        structure=UnifiedStructure.IRS_OUTRIGHT,
        value=UnifiedValue.IRS_RATE,
        curve="USD-SOFR-1D-Q12STIRT",
        tenor="IMM_Z26xIMM_H27",
    )

    legacy = unified.to_legacy()
    resolved = legacy.resolve_query(_now(), pricer_or_curve=curve)

    assert isinstance(resolved, IRSwapQuery)
    assert resolved.structure == IRSwapStructure.OUTRIGHT
    assert resolved.structure_id == IRSwapStructure.OUTRIGHT
    assert resolved.structure_kwargs["tenor"] == "IMM_Z26xIMM_H27"
    assert "front_tenor" not in resolved.structure_kwargs
    assert "back_tenor" not in resolved.structure_kwargs

    package, risk_weights = resolved.resolve_package(pricer_or_curve=curve, is_for_timeseries=True)
    assert len(package) == 1
    assert len(risk_weights) == 1


def test_irs_forward_start_tenor_with_x_resolves_as_outright():
    curve = _IRCurveStub()
    query = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.RATE,
        tenor="2Yx5Y",
        curve="USD-SOFR-1D",
    )

    resolved = query.resolve_query(_now(), pricer_or_curve=curve)

    assert resolved.structure == IRSwapStructure.OUTRIGHT
    assert resolved.structure_id == IRSwapStructure.OUTRIGHT
    assert resolved.structure_kwargs["tenor"] == "2Yx5Y"
    assert "front_tenor" not in resolved.structure_kwargs
    assert "back_tenor" not in resolved.structure_kwargs


def test_unified_query_parity_for_spread_package_and_value_map():
    context = _SpreadContext()
    legacy = SpreadQuery(
        structure=SpreadStructure.OUTRIGHT,
        value=SpreadValue.SPREAD_BPS,
        tenor="5Y",
        curve_a="USD-SOFR-1D",
        curve_b="USD-FEDFUNDS",
    )
    unified = UnifiedQuery(
        product="IRSPREAD",
        structure="OUTRIGHT",
        value="SPREAD_BPS",
        selector={"tenor": "5Y", "curve_a": "USD-SOFR-1D", "curve_b": "USD-FEDFUNDS"},
    )

    legacy_pkg, legacy_weights = legacy.resolve_package(pricer_or_curve=context)
    unified_pkg, unified_weights = unified.resolve_package(pricer_or_curve=context)

    assert legacy_weights == unified_weights
    assert legacy_pkg[0].tenor == unified_pkg[0].tenor

    legacy_value = legacy.build_value_map(pricer_or_curve=context, package=legacy_pkg, risk_weights=legacy_weights).apply(value=SpreadValue.SPREAD_BPS)
    unified_value = unified.build_value_map(pricer_or_curve=context, package=unified_pkg, risk_weights=unified_weights).apply(value=UnifiedValue.IRSPREAD_SPREAD_BPS)

    assert unified_value == pytest.approx(legacy_value)


def test_unified_query_parity_for_stir_future_package_and_value_map():
    pricer = {"SR3H26": _MockSTIRFuturePricer("SR3H26", 95.5)}
    legacy = STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE, symbol="SR3H26", structure_kwargs={"contracts": 1})
    unified = UnifiedQuery(structure=UnifiedStructure.STIRFUTURE_OUTRIGHT, value=UnifiedValue.STIRFUTURE_PRICE, selector={"symbol": "SR3H26"}, structure_kwargs={"contracts": 1})

    legacy_pkg, legacy_weights = legacy.resolve_package(pricer_or_curve=pricer)
    unified_pkg, unified_weights = unified.resolve_package(pricer_or_curve=pricer)

    assert legacy_weights == unified_weights
    assert legacy_pkg[0].price() == unified_pkg[0].price()

    legacy_value = legacy.build_value_map(pricer_or_curve=pricer, package=legacy_pkg, risk_weights=legacy_weights).apply(value=STIRFutureValue.PRICE)
    unified_value = unified.build_value_map(pricer_or_curve=pricer, package=unified_pkg, risk_weights=unified_weights).apply(value=UnifiedValue.STIRFUTURE_PRICE)

    assert unified_value == pytest.approx(legacy_value)


def test_unified_query_parity_for_ust_future_package_and_value_map():
    pricer = {"TYM26": _MockUSTFuturePricer("TYM26", 111.25)}
    legacy = USTFutureQuery(structure=USTFutureStructure.OUTRIGHT, value=USTFutureValue.PRICE, symbol="TYM26")
    unified = UnifiedQuery(structure=UnifiedStructure.USTFUTURE_OUTRIGHT, value=UnifiedValue.USTFUTURE_PRICE, selector={"symbol": "TYM26"})

    legacy_pkg, legacy_weights = legacy.resolve_package(pricer_or_curve=pricer)
    unified_pkg, unified_weights = unified.resolve_package(pricer_or_curve=pricer)

    assert legacy_weights == unified_weights
    assert legacy_pkg[0].price() == unified_pkg[0].price()

    legacy_value = legacy.build_value_map(pricer_or_curve=pricer, package=legacy_pkg, risk_weights=legacy_weights).apply(value=USTFutureValue.PRICE)
    unified_value = unified.build_value_map(pricer_or_curve=pricer, package=unified_pkg, risk_weights=unified_weights).apply(value=UnifiedValue.USTFUTURE_PRICE)

    assert unified_value == pytest.approx(legacy_value)


def test_unified_query_preserves_direct_product_alias_for_spread_family():
    query = UnifiedQuery(product="IRBASIS", structure="OUTRIGHT", value="SPREAD_BPS", selector={"tenor": "5Y", "curve_a": "USD-SOFR-1D", "curve_b": "USD-FEDFUNDS"})
    legacy = query.to_legacy()
    assert isinstance(legacy, SpreadQuery)
    assert legacy.product == "IRBASIS"


def test_unified_query_from_legacy_round_trips_core_fields():
    legacy = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.RATE,
        tenor="5Y",
        curve="USD-SOFR-1D",
        structure_kwargs={"bpv": 1_000_000},
    )

    unified = UnifiedQuery.from_legacy(legacy)

    assert unified.product == "IRS"
    assert unified.structure == UnifiedStructure.IRS_OUTRIGHT
    assert unified.value == UnifiedValue.IRS_RATE
    assert unified.selector["tenor"] == "5Y"
    assert unified.selector["curve"] == "USD-SOFR-1D"


def test_query_engine_enriches_product_for_multiproduct_mdp_after_resolve_query():
    now = _now()
    irs_mdp = _RecordingMDP("IRS_FAKE")
    ust_mdp = _RecordingMDP("UST_FAKE")
    multi = MultiProductMDP({"USTFUTURE": ust_mdp, "IRS": irs_mdp}, default_product="USTFUTURE")
    strategy = QueryStrategy(name="test", triggers=[], default_mdp=multi)
    backtest = QueryDrivenBacktest(time_grid=TimeGrid([now]), strategy=strategy, mdp=multi, show_progress=False)

    query = UnifiedQuery(structure=UnifiedStructure.IRS_OUTRIGHT, value=UnifiedValue.IRS_RATE, selector={"tenor": "5Y", "curve": "USD-SOFR-1D"})
    backtest._pricer_for_query(query, now)

    assert len(irs_mdp.requests) == 2
    assert len(ust_mdp.requests) == 0
