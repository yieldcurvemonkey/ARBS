from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

import QuantLib as ql

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.MarketDataProvider import MarketDataProvider
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.Base.query_resolution import resolve_query
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

_CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
_Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")
_BENCHMARK_SPREAD_VALUES = {IRSwapValue.MMSS, IRSwapValue.SPREADOVER}
_ASW_VALUES = {
    IRSwapValue.PAR_PAR_ASW,
    IRSwapValue.TRUE_ASW,
    IRSwapValue.PROCEEDS_ASW,
    IRSwapValue.MARKET_ASW,
}


def _ct_alias_to_y(tenor: str) -> str:
    return _CT_RE.sub(r"\1Y", str(tenor))


def _y_alias_to_ct(tenor: str) -> str:
    return _Y_RE.sub(r"CT\1", str(tenor))


def _normalize_value(value: Any) -> IRSwapValue:
    if isinstance(value, IRSwapValue):
        return value
    if isinstance(value, str):
        return IRSwapValue[value.upper()]
    raise TypeError(f"Unsupported IR swap spread value: {value!r}")


def _curve_name_from_pricer(curve: _IRSwapGenericCurve, fallback: Optional[str] = None) -> str:
    for key in ("requested_curve_name", "curve_name", "reference_key"):
        try:
            meta = curve.meta()
            if isinstance(meta, Mapping):
                candidate = meta.get(key)
                if candidate:
                    return str(candidate)
        except Exception:
            continue
    if fallback:
        return str(fallback)
    raise KeyError("Could not determine QuantLib curve definition key for asset swap pricing.")


def fair_asset_swap_spread_bps(
    swap_curve: _IRSwapGenericCurve,
    frb_pricer: _FixedRateBondGenericPricer,
    *,
    curve_name: Optional[str] = None,
    par_par_asw: bool = True,
) -> float:
    from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_discount_curve_from_nodes
    from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
    from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

    ql.Settings.instance().evaluationDate = datetime_to_ql_date(swap_curve.reference_date())

    ql_bond = frb_pricer.build_fixed_rate_bond(
        issue_date=frb_pricer.issue_date(),
        maturity_date=frb_pricer.maturity_date(),
        coupon=frb_pricer.coupon(),
        notional=100,
    )

    ql_curve_handle = ql.YieldTermStructureHandle(
        build_discount_curve_from_nodes(
            swap_curve.nodes(),
            ql_dc=ql.Actual360(),
            ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            interpolation_algo="df_log_linear",
        )
    )
    definition_key = _curve_name_from_pricer(swap_curve, fallback=curve_name)
    ql_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[definition_key]["ReferenceRate"](ql_curve_handle)

    index_fixings = swap_curve.index()
    if hasattr(index_fixings, "to_dict"):
        fixings_dict = index_fixings.to_dict()
    elif isinstance(index_fixings, Mapping):
        fixings_dict = dict(index_fixings)
    else:
        fixings_dict = {}

    for d, f in fixings_dict.items():
        try:
            ql_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
        except Exception:
            continue

    swap = ql.AssetSwap(
        True,
        ql_bond,
        frb_pricer.clean_price(),
        ql_index,
        0.0,
        ql.Schedule(
            datetime_to_ql_date(frb_pricer.issue_date()),
            datetime_to_ql_date(frb_pricer.maturity_date()),
            ql.Period(6, ql.Months),
            ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            ql.ModifiedFollowing,
            ql.ModifiedFollowing,
            ql.DateGeneration.Forward,
            False,
        ),
        ql_index.dayCounter(),
        par_par_asw,
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(ql_curve_handle))
    return float(swap.fairSpread()) * 10_000


@dataclass
class IRSwapSpreadPricer:
    swap_curve: _IRSwapGenericCurve
    bond_pricer: _FixedRateBondGenericPricer
    value: IRSwapValue
    swap_query: Optional[IRSwapQuery] = None
    requested_curve_name: Optional[str] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)

    def _resolve_swap_query(self) -> IRSwapQuery:
        if self.swap_query is None:
            raise ValueError("Swap spread pricing requires an IRSwapQuery for the swap leg.")
        return resolve_query(
            self.swap_query,
            timestamp=self.swap_curve.reference_date(),
            pricer_or_curve=self.swap_curve,
        )

    def swap_rate_percent(self) -> float:
        q_eff = self._resolve_swap_query()
        if getattr(q_eff, "structure", None) is not None and str(q_eff.structure.name) != "OUTRIGHT":
            raise NotImplementedError("IRSwapSpreadsMDP currently supports outright IRS-vs-bond spreads only.")

        package, risk_weights = q_eff.resolve_package(
            pricer_or_curve=self.swap_curve,
            is_for_timeseries=True,
        )
        value_map = q_eff.build_value_map(
            pricer_or_curve=self.swap_curve,
            package=package,
            risk_weights=risk_weights,
        )
        return float(value_map.apply(value=q_eff.value, **(q_eff.value_kwargs or {})))

    def cash_yield_percent(self) -> float:
        return float(self.bond_pricer.ytm())

    def spread_bps(self) -> float:
        return (self.swap_rate_percent() - self.cash_yield_percent()) * 100.0

    def asset_swap_spread_bps(self) -> float:
        return fair_asset_swap_spread_bps(
            self.swap_curve,
            self.bond_pricer,
            curve_name=self.requested_curve_name,
            par_par_asw=self.value == IRSwapValue.PAR_PAR_ASW,
        )

    def value_bps(self) -> float:
        if self.value in _BENCHMARK_SPREAD_VALUES:
            return self.spread_bps()
        if self.value in _ASW_VALUES:
            return self.asset_swap_spread_bps()
        raise NotImplementedError(f"Unsupported IRSwap spread metric: {self.value}")


class IRSwapSpreadsMDP(MarketDataProvider[IRSwapSpreadPricer]):
    """
    IRS-vs-UST spread provider backed by an IRSwapsMDP and a FixedRateBondsMDP.

    Supported request shape:
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": date|datetime|"live",
            "value": IRSwapValue.MMSS | IRSwapValue.SPREADOVER | IRSwapValue.PAR_PAR_ASW | ...,
            "tenor": "CT10" | "10Y" | "<cusip>",
        }

    Optional keys:
        swap_query: explicit IRSwapQuery for the swap leg
        bond_symbol / cusip / symbol: explicit cash-leg identifier
        curve_request: dict of extra kwargs forwarded to IRSwapsMDP.get_pricer()
        bond_request: dict of extra kwargs forwarded to FixedRateBondsMDP.get_pricer()
    """

    def __init__(
        self,
        irs_source: str = "CME_NY_EOD_LIVE-ql_basic",
        frb_source: str = "USTS_FEDINVEST_WSJ_LIVE-QL",
        *,
        source_a: Optional[str] = None,
        source_b: Optional[str] = None,
        _irs_mdp: Optional[IRSwapsMDP] = None,
        _frb_mdp: Optional[FixedRateBondsMDP] = None,
        _mdp_a: Optional[Any] = None,
        _mdp_b: Optional[Any] = None,
        **kwargs: Any,
    ):
        super().__init__(source="IRSWAP_SPREAD", **kwargs)

        if source_a is not None:
            irs_source = source_a
        if source_b is not None:
            frb_source = source_b

        self.irs_mdp = _irs_mdp or _mdp_a or IRSwapsMDP(source=irs_source)
        self.frb_mdp = _frb_mdp or _mdp_b or FixedRateBondsMDP(source=frb_source)

    @staticmethod
    def build_request_from_query(q: IRSwapQuery, timestamp: Any) -> Dict[str, Any]:
        request = dict(q.market_request or {})
        if q.curve is not None and "curve_name" not in request:
            request["curve_name"] = q.curve
        request[q.mdp_time_key] = timestamp
        request["value"] = q.value
        if q.tenor is not None:
            request["tenor"] = q.tenor
        return request

    @staticmethod
    def _resolve_bond_symbol(request: Mapping[str, Any], value: IRSwapValue) -> str:
        token = (
            request.get("bond_symbol")
            or request.get("cusip")
            or request.get("symbol")
            or request.get("tenor")
        )
        if token is None:
            raise ValueError("IR swap spread request requires 'tenor', 'bond_symbol', 'cusip', or 'symbol'.")

        token = str(token)
        if value == IRSwapValue.SPREADOVER and _Y_RE.search(token):
            return _y_alias_to_ct(token)
        return token

    @staticmethod
    def _build_swap_query(
        request: Mapping[str, Any],
        *,
        curve_name: str,
        value: IRSwapValue,
    ) -> Optional[IRSwapQuery]:
        if value not in _BENCHMARK_SPREAD_VALUES:
            return None

        explicit_query = request.get("swap_query")
        if explicit_query is not None:
            if not isinstance(explicit_query, IRSwapQuery):
                raise TypeError("request['swap_query'] must be an IRSwapQuery.")
            if explicit_query.value != IRSwapValue.RATE:
                return IRSwapQuery(
                    structure=explicit_query.structure,
                    value=IRSwapValue.RATE,
                    tenor=explicit_query.tenor,
                    effective_date=explicit_query.effective_date,
                    maturity_date=explicit_query.maturity_date,
                    is_mms=explicit_query.is_mms,
                    curve=explicit_query.curve or curve_name,
                    structure_kwargs=explicit_query.structure_kwargs,
                    value_kwargs=explicit_query.value_kwargs,
                    risk_weight=explicit_query.risk_weight,
                    name=explicit_query.name,
                    tags=explicit_query.tags,
                    meta=explicit_query.meta,
                    market_request=explicit_query.market_request,
                    mdp_time_key=explicit_query.mdp_time_key,
                )
            return explicit_query

        raw_tenor = request.get("swap_tenor") or request.get("tenor")
        if raw_tenor is None:
            raise ValueError("IR swap spread request requires 'tenor' or 'swap_tenor'.")

        tenor = str(raw_tenor)
        if value == IRSwapValue.SPREADOVER and _CT_RE.search(tenor):
            tenor = _ct_alias_to_y(tenor)

        return IRSwapQuery(
            curve=curve_name,
            tenor=tenor,
            value=IRSwapValue.RATE,
        )

    def get_pricer(self, request: Dict[str, Any]) -> IRSwapSpreadPricer:
        req = dict(request)
        value = _normalize_value(req.pop("value", req.pop("spread_type", IRSwapValue.MMSS)))
        curve_name = req.pop("curve_name", req.pop("curve", None))
        timestamp = req.pop("timestamp", None)

        if not curve_name:
            raise ValueError("IR swap spread request requires 'curve_name'.")
        if timestamp is None:
            raise ValueError("IR swap spread request requires 'timestamp'.")

        swap_query = self._build_swap_query(req, curve_name=str(curve_name), value=value)
        bond_symbol = self._resolve_bond_symbol(req, value)

        curve_request = dict(req.pop("curve_request", {}) or {})
        curve_request["curve_name"] = curve_name
        curve_request["timestamp"] = timestamp
        swap_curve = self.irs_mdp.get_pricer(dict(curve_request))

        bond_request = dict(req.pop("bond_request", {}) or {})
        bond_request["cusips"] = [bond_symbol]
        bond_request["timestamp"] = timestamp
        bond_pricers = self.frb_mdp.get_pricer(dict(bond_request))
        if not bond_pricers:
            raise RuntimeError(f"FixedRateBondsMDP returned no pricer for {bond_symbol!r} at {timestamp!r}.")

        bond_pricer = next(iter(bond_pricers.values()))
        return IRSwapSpreadPricer(
            swap_curve=swap_curve,
            bond_pricer=bond_pricer,
            value=value,
            swap_query=swap_query,
            requested_curve_name=str(curve_name),
            meta_data={
                "curve_name": curve_name,
                "timestamp": timestamp,
                "bond_symbol": bond_symbol,
                "value": value,
            },
        )
