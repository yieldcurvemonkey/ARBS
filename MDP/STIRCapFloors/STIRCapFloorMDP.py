from __future__ import annotations

import datetime as dt
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

import QuantLib as ql

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.MarketDataProvider import MarketDataProvider
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from MDP.STIRFutures._sofr_option_contracts import (
    _contract_to_barchart_contract,
    _format_strike4,
    _snap_to_listed_strike_for_offset,
    next_quarterly_contract,
    quarterly_contract_expiry_date,
    quarterly_reference_window,
    resolve_quarterly_contracts,
)
from Query.IRSwaps.backends.quantlib.utils import ql_date_to_datetime
from Query.IRSwaptions.utils import normalize_tenor, parse_expiry_tail_shorthandle
from Query.STIRCapFloors.pricer import STIRCapFloorLegMarket
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from SDRUtils.analytics.seasonality import get_fomc_dates


DateLike = dt.date | dt.datetime | str

# Runaway guard on the quarterly ladder walk: 50 years past the front contract.
# The walk terminates on the window's end date, so this only fires on a caller
# asking for a window further out than the contract grid is meaningful.
_MAX_LADDER_QUARTERS = 200


def _as_date(value: DateLike) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "live":
            return dt.date.today()
        return dt.date.fromisoformat(value)
    raise TypeError(f"Unsupported date type: {type(value)}")


def _py_to_ql_date(value: dt.date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _tenor_months(token: str) -> int:
    norm = normalize_tenor(token)
    if norm.endswith("Y"):
        return int(norm[:-1]) * 12
    if norm.endswith("M"):
        return int(norm[:-1])
    raise ValueError(f"STIR synthetic cap/floor supports only month/year tenors, got {token!r}")


def _quarter_multiple_months(token: str, *, label: str) -> int:
    months = _tenor_months(token)
    if months % 3 != 0:
        raise ValueError(f"{label} must be an explicit date or a multiple of 3M, got {token!r}")
    return months


def _capfloor_right(structure: str) -> str:
    token = str(structure or "").strip().upper()
    if token == "CAP":
        return "P"
    if token == "FLOOR":
        return "C"
    raise ValueError(f"Unsupported cap/floor structure {structure!r}")


def _quarter_end_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    out: list[dt.date] = []
    for year in range(start.year, end.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            d = dt.date(year, month, day)
            if start <= d < end:
                out.append(d)
    return out


def _fomc_loading(start: dt.date, end: dt.date, fomc_dates: list[dt.date]) -> float:
    total_days = max((end - start).days, 1)
    load = 0.0
    for meeting in fomc_dates:
        if start <= meeting < end:
            load += float((end - meeting).days) / float(total_days)
    return float(load)


def _discount(curve: Any, ql_date: ql.Date) -> float:
    """Discount factor to ``ql_date``, whichever library built the curve.

    Under a ``-QL`` source the handle is a ``ql.YieldTermStructureHandle`` and is
    *called*; under an ``-RL`` source (``CITIVELO_EXCEL``, ``SDR_INTRADAY-RL``,
    ``ERIS_EOD_LIVE-RL_BASIC``, ...) it is a ``rateslib.Curve`` and is
    *subscripted*. The subscript key must be a ``datetime.datetime``:
    ``rateslib.curves.Curve.__getitem__`` compares it against
    ``self.nodes.initial``, which is a ``datetime``, so BOTH a ``ql.Date`` and a
    plain ``datetime.date`` raise ``TypeError: '<' not supported between
    instances of ... and 'datetime.datetime'``. Passing the ``ql.Date`` straight
    through is what made ``strike_convention="flat_swap_rate"`` (via
    :meth:`STIRCapFloorMDP._contract_forward_price`) and
    ``weight_method="duration"`` (via :meth:`STIRCapFloorMDP._resolve_weights`)
    unusable on every rateslib-backed curve, while the QuantLib branch below hid
    it on the Eris source.

    ``ql_date_to_datetime`` is the repo's existing canonicaliser for this - the
    same one ``MDP/IRSwaps/*/rl_*`` fetchers use when they hand QuantLib dates to
    rateslib. The QuantLib branch is tried first and by duck typing rather than
    ``isinstance`` for the same reason as
    :func:`Query.IRSwaptions.pricer.discount_factor`, which solves this identical
    dispatch: test fakes supply a bare object carrying a ``discount`` method and
    an ``isinstance`` gate would silently route them into the rateslib branch.
    """
    handle = curve.handle() if hasattr(curve, "handle") else curve
    if hasattr(handle, "discount"):
        return float(handle.discount(ql_date))
    return float(handle[ql_date_to_datetime(ql_date)])


def _bachelier_price(right: str, strike: float, forward: float, vol_normal: float, tte: float, discount: float) -> float:
    option_type = ql.Option.Call if str(right).upper() == "C" else ql.Option.Put
    stddev = max(float(vol_normal), 0.0) * math.sqrt(max(float(tte), 1e-12))
    return float(ql.bachelierBlackFormula(option_type, float(strike), float(forward), float(stddev), float(discount)))


def _bachelier_greeks(right: str, strike: float, forward: float, vol_normal: float, tte: float, discount: float) -> tuple[float, float, float, float]:
    payoff = ql.PlainVanillaPayoff(ql.Option.Call if str(right).upper() == "C" else ql.Option.Put, float(strike))
    stddev = max(float(vol_normal), 0.0) * math.sqrt(max(float(tte), 1e-12))
    try:
        calc = ql.BachelierCalculator(payoff, float(forward), float(stddev), float(discount))
        return float(calc.deltaForward()), float(calc.gammaForward()), float(calc.vega(float(tte))), float(calc.theta(float(forward), float(tte)))
    except Exception:
        h_f = 0.01
        h_v = max(1e-4, abs(float(vol_normal)) * 0.01)
        dt_step = 1.0 / 365.0
        p0 = _bachelier_price(right, strike, forward, vol_normal, tte, discount)
        p_up = _bachelier_price(right, strike, forward + h_f, vol_normal, tte, discount)
        p_dn = _bachelier_price(right, strike, forward - h_f, vol_normal, tte, discount)
        delta = (p_up - p_dn) / (2.0 * h_f)
        gamma = (p_up - 2.0 * p0 + p_dn) / (h_f * h_f)
        pv_up = _bachelier_price(right, strike, forward, vol_normal + h_v, tte, discount)
        pv_dn = _bachelier_price(right, strike, forward, max(vol_normal - h_v, 1e-8), tte, discount)
        vega = (pv_up - pv_dn) / (2.0 * h_v)
        pt_up = _bachelier_price(right, strike, forward, vol_normal, tte + dt_step, discount)
        pt_dn = _bachelier_price(right, strike, forward, vol_normal, max(tte - dt_step, 1e-6), discount)
        theta = (pt_up - pt_dn) / (2.0 * dt_step)
        return float(delta), float(gamma), float(vega), float(theta)


@dataclass(frozen=True)
class STIRCapFloorMarketContext:
    structure: str
    curve_name: str
    as_of_date: dt.date
    swap_start: dt.date
    swap_end: dt.date
    weight_method: str
    strike_convention: str
    contracts: float
    curve: Any
    legs: tuple[STIRCapFloorLegMarket, ...]
    metadata: dict[str, Any]

    def id(self) -> str:
        return (
            f"{self.structure}|{self.curve_name}|{self.as_of_date.isoformat()}|"
            f"{self.swap_start.isoformat()}|{self.swap_end.isoformat()}|"
            f"{self.weight_method}|{self.strike_convention}|{self.contracts:g}"
        )

    def resolve_pricable(self, priceable: Any, risk_weight: Optional[float] = None) -> Any:
        _ = risk_weight
        return priceable

    def meta(self) -> dict[str, Any]:
        return dict(self.metadata or {})

    @property
    def pricers(self) -> "OrderedDict[str, Any]":
        out: "OrderedDict[str, Any]" = OrderedDict()
        for leg in self.legs:
            out[str(leg.option_symbol)] = leg.pricer
        return out


class STIRCapFloorMDP(MarketDataProvider[STIRCapFloorMarketContext]):
    def __init__(
        self,
        source: str = "STIRCAPFLOOR-QL",
        *,
        curve_source: str = "ERIS_EOD_LIVE-QL_BASIC",
        option_source: str = "BARCHART_STIRFO-QL",
        default_curve_name: str = "USD-SOFR-1D",
        **kwargs: Any,
    ):
        super().__init__(source=source, **kwargs)
        self.curve_source = str(curve_source)
        self.option_source = str(option_source)
        self.default_curve_name = str(default_curve_name)
        self._curve_mdp = IRSwapsMDP(source=self.curve_source, **kwargs)
        self._option_mdp = STIRFutureOptionMDP(source=self.option_source, **kwargs)
        self._runtime_cache: dict[tuple[Any, ...], STIRCapFloorMarketContext] = {}
        self._fomc_dates = get_fomc_dates()

    def get_pricer(self, request: dict[str, Any]) -> STIRCapFloorMarketContext:
        return self.get_data(request)

    def get_data(self, request: dict[str, Any]) -> STIRCapFloorMarketContext:
        req = dict(request)
        endpoint = str(req.get("endpoint", "synthetic_capfloor_snapshot")).strip().lower()
        if endpoint != "synthetic_capfloor_snapshot":
            raise NotImplementedError(f"Unsupported endpoint {endpoint!r}")

        as_of = _as_date(req.get("timestamp", dt.date.today()))
        structure = str(req.get("structure", "CAP")).strip().upper()
        curve_name = str(req.get("curve_name") or req.get("curve") or self.default_curve_name).strip()
        weight_method = str(req.get("weight_method", "equal")).strip().lower()
        strike_convention = str(req.get("strike_convention", "atm_per_caplet")).strip().lower()
        contracts = float(req.get("contracts", 1.0))
        force_refresh = bool(req.get("force_refresh", False))

        swap_start, swap_end, strip_contracts = self._resolve_window(req=req, as_of=as_of)
        cache_key = (
            as_of,
            structure,
            curve_name.upper(),
            swap_start,
            swap_end,
            weight_method,
            strike_convention,
            contracts,
            self.option_source.upper(),
        )
        if not force_refresh and cache_key in self._runtime_cache:
            return self._runtime_cache[cache_key]

        curve = self._curve_mdp.get_pricer({"curve_name": curve_name, "timestamp": as_of})
        context = self._build_context(
            as_of=as_of,
            structure=structure,
            curve_name=curve_name,
            curve=curve,
            swap_start=swap_start,
            swap_end=swap_end,
            strip_contracts=strip_contracts,
            weight_method=weight_method,
            strike_convention=strike_convention,
            contracts=contracts,
        )
        self._runtime_cache[cache_key] = context
        return context

    def _resolve_window(
        self,
        *,
        req: dict[str, Any],
        as_of: dt.date,
    ) -> tuple[dt.date, dt.date, list[str]]:
        swap_start_raw = req.get("swap_start")
        swap_end_raw = req.get("swap_end")
        if swap_start_raw is not None or swap_end_raw is not None:
            if swap_start_raw is None or swap_end_raw is None:
                raise ValueError("Explicit strip mode requires both swap_start and swap_end.")
            swap_start = _as_date(swap_start_raw)
            swap_end = _as_date(swap_end_raw)
            if swap_end <= swap_start:
                raise ValueError("swap_end must be after swap_start.")

            front_contract = resolve_quarterly_contracts(as_of, start_index=0, count=1)[0]
            front_start = quarterly_contract_expiry_date(front_contract)
            if swap_start < front_start:
                raise ValueError(
                    f"Requested strip starts on {swap_start.isoformat()}, before the first live quarterly contract "
                    f"window starting {front_start.isoformat()}."
                )

            contracts = self._contracts_for_explicit_window(as_of=as_of, swap_start=swap_start, swap_end=swap_end)
            if not contracts:
                raise ValueError(
                    f"No quarterly SFR contracts fall inside {swap_start.isoformat()}..{swap_end.isoformat()}."
                )
            return swap_start, swap_end, contracts

        shorthand = req.get("shorthand")
        expiry = req.get("expiry")
        tail = req.get("tail")
        if shorthand is not None:
            exp_token, tail_token = parse_expiry_tail_shorthandle(str(shorthand))
            expiry = expiry or exp_token
            tail = tail or tail_token

        if expiry is None or tail is None:
            raise ValueError("Synthetic cap/floor requires shorthand, expiry+tail, or swap_start+swap_end.")

        expiry_months = _quarter_multiple_months(str(expiry), label="expiry")
        tail_months = _quarter_multiple_months(str(tail), label="tail")
        leg_count = tail_months // 3
        strip_contracts = resolve_quarterly_contracts(
            as_of,
            start_index=expiry_months // 3,
            count=leg_count,
        )
        if len(strip_contracts) != leg_count:
            raise ValueError(f"Unable to resolve {leg_count} quarterly contracts for expiry={expiry}, tail={tail}.")

        swap_start = quarterly_contract_expiry_date(strip_contracts[0])
        _, swap_end = quarterly_reference_window(strip_contracts[-1])
        return swap_start, swap_end, strip_contracts

    def _contracts_for_explicit_window(self, *, as_of: dt.date, swap_start: dt.date, swap_end: dt.date) -> list[str]:
        """Quarterly SFR contracts whose reference quarters tile ``[swap_start, swap_end)``.

        The ladder is walked forward from the front contract until it reaches the
        window's **end**.  Sizing it from the window's *length* instead - which
        ``ceil(window_days / 75) + 4`` contracts taken from the front of the curve
        did - runs off the end of the ladder for any forward-starting window and
        returns a short strip with no error: measured on 2023-06-09 the rank-9
        pack window 2025-06-18..2026-06-17 came back as one contract instead of
        four, and rank 13 came back empty.

        Raises rather than returning a partial cover.  Callers aggregate over the
        legs without checking the count (``STIRCapFloorValueFunctionMap``), so a
        strip that does not tile the requested window is indistinguishable from a
        correct one; ``_resolve_window`` already raises on a window that starts
        before the front contract, and this is the same rule at the far end.
        """
        contract = resolve_quarterly_contracts(as_of, start_index=0, count=1)[0]
        out: list[str] = []
        for _ in range(_MAX_LADDER_QUARTERS):
            ref_start, _ref_end = quarterly_reference_window(contract)
            if ref_start >= swap_end:
                break
            if ref_start >= swap_start:
                out.append(contract)
            contract = next_quarterly_contract(contract)
        else:
            raise ValueError(
                f"Quarterly SFR ladder did not reach {swap_end.isoformat()} within "
                f"{_MAX_LADDER_QUARTERS} contracts of {as_of.isoformat()}."
            )

        if out:
            first_start, _ = quarterly_reference_window(out[0])
            _, last_end = quarterly_reference_window(out[-1])
            if first_start != swap_start or last_end != swap_end:
                raise ValueError(
                    f"Quarterly SFR grid does not tile {swap_start.isoformat()}..{swap_end.isoformat()}: "
                    f"{out[0]}..{out[-1]} covers {first_start.isoformat()}..{last_end.isoformat()}."
                )
        return out

    def _build_context(
        self,
        *,
        as_of: dt.date,
        structure: str,
        curve_name: str,
        curve: Any,
        swap_start: dt.date,
        swap_end: dt.date,
        strip_contracts: list[str],
        weight_method: str,
        strike_convention: str,
        contracts: float,
    ) -> STIRCapFloorMarketContext:
        right = _capfloor_right(structure)
        weights = self._resolve_weights(curve=curve, strip_contracts=strip_contracts, weight_method=weight_method)
        flat_swap_rate = self._forward_swap_rate(curve=curve, swap_start=swap_start, swap_end=swap_end)
        flat_strike_rate = float(flat_swap_rate * 100.0)
        flat_strike_price = float(100.0 - flat_strike_rate)

        legs: list[STIRCapFloorLegMarket] = []
        leg_count = len(strip_contracts)
        for idx, (contract, weight) in enumerate(zip(strip_contracts, weights)):
            ref_start, ref_end = quarterly_reference_window(contract)
            unit_quantity = float(leg_count * weight)
            quantity = float(unit_quantity * contracts)
            if strike_convention == "atm_per_caplet":
                requested_symbol = f"{contract}|ATM{right}"
                market_pricer = self._fetch_market_pricer(requested_symbol, as_of=as_of)
                if market_pricer is None:
                    raise ValueError(f"Could not resolve listed ATM option for {requested_symbol} on {as_of.isoformat()}.")
                pricer = market_pricer
                strike_price = float(pricer.strike())
                strike_rate = float(100.0 - strike_price)
                requested_strike_price = strike_price
                requested_strike_rate = strike_rate
                strike_snap_bps = 0.0
                quote_source = "market"
            elif strike_convention == "flat_swap_rate":
                requested_strike_price = float(flat_strike_price)
                requested_strike_rate = float(flat_strike_rate)
                forward_price = self._contract_forward_price(curve=curve, contract=contract)
                strike_price, actual_offset = _snap_to_listed_strike_for_offset(
                    contract=contract,
                    forward=forward_price,
                    as_of=as_of,
                    right=right,
                    offset_bps=(forward_price - requested_strike_price) * 100.0,
                )
                strike_rate = float(100.0 - strike_price)
                requested_symbol = f"{contract}|{_format_strike4(strike_price, contract=contract)}{right}"
                pricer = self._fetch_market_pricer(requested_symbol, as_of=as_of)
                quote_source = "market"
                if pricer is None:
                    pricer = self._sabr_fallback_pricer(
                        contract=contract,
                        right=right,
                        option_symbol=requested_symbol,
                        strike_price=strike_price,
                        curve=curve,
                        as_of=as_of,
                    )
                    quote_source = "sabr_fallback"
                strike_snap_bps = float((requested_strike_price - strike_price) * 100.0)
                _ = actual_offset
            else:
                raise ValueError(f"Unsupported strike_convention {strike_convention!r}")

            metadata = {
                "leg_index": idx,
                "weight_method": weight_method,
                "strike_convention": strike_convention,
                "strike_snap_bps": float(strike_snap_bps),
                "option_source": self.option_source,
                "curve_source": self.curve_source,
            }
            legs.append(
                STIRCapFloorLegMarket(
                    option_symbol=str(pricer.symbol()),
                    requested_symbol=str(requested_symbol),
                    right=right,
                    underlying_contract=contract,
                    reference_quarter_start=ref_start,
                    reference_quarter_end=ref_end,
                    strike_price=float(pricer.strike()),
                    strike_rate=float(100.0 - pricer.strike()),
                    requested_strike_price=float(requested_strike_price),
                    requested_strike_rate=float(requested_strike_rate),
                    economic_weight=float(weight),
                    unit_quantity=float(unit_quantity),
                    quantity=float(quantity),
                    quote_source=quote_source,
                    quarter_end_flag=bool(_quarter_end_dates(ref_start, ref_end)),
                    fomc_loading=_fomc_loading(ref_start, ref_end, self._fomc_dates),
                    pricer=pricer,
                    metadata=metadata,
                )
            )

        metadata = {
            "source": self.source,
            "curve_source": self.curve_source,
            "option_source": self.option_source,
            "flat_swap_rate": float(flat_swap_rate),
            "flat_swap_rate_pct": float(flat_strike_rate),
            "flat_swap_price": float(flat_strike_price),
            "contracts": float(contracts),
            "strip_contracts": list(strip_contracts),
            "weight_method": weight_method,
            "strike_convention": strike_convention,
        }
        return STIRCapFloorMarketContext(
            structure=structure,
            curve_name=curve_name,
            as_of_date=as_of,
            swap_start=swap_start,
            swap_end=swap_end,
            weight_method=weight_method,
            strike_convention=strike_convention,
            contracts=float(contracts),
            curve=curve,
            legs=tuple(legs),
            metadata=metadata,
        )

    def _resolve_weights(self, *, curve: Any, strip_contracts: list[str], weight_method: str) -> list[float]:
        token = str(weight_method or "equal").strip().lower()
        if not strip_contracts:
            raise ValueError("Cannot build a synthetic strip with no contracts.")
        if token == "equal":
            return [1.0 / float(len(strip_contracts))] * len(strip_contracts)
        if token != "duration":
            raise ValueError(f"Unsupported weight_method {weight_method!r}")

        dc = ql.Actual360()
        raw: list[float] = []
        for contract in strip_contracts:
            ref_start, ref_end = quarterly_reference_window(contract)
            ql_start = _py_to_ql_date(ref_start)
            ql_end = _py_to_ql_date(ref_end)
            tau = max(float(dc.yearFraction(ql_start, ql_end)), 1e-10)
            raw.append(max(_discount(curve, ql_end) * tau, 1e-12))
        total = sum(raw)
        return [float(x / total) for x in raw]

    def _forward_swap_rate(self, *, curve: Any, swap_start: dt.date, swap_end: dt.date) -> float:
        par_swap = curve.build_irswap(
            effective_date=swap_start,
            maturity_date=swap_end,
            fixed_rate=-0.0,
            notional=1.0,
        )
        return abs(float(curve.fair_rate(par_swap)))

    def _contract_forward_price(self, *, curve: Any, contract: str) -> float:
        ref_start, ref_end = quarterly_reference_window(contract)
        dc = ql.Actual360()
        ql_start = _py_to_ql_date(ref_start)
        ql_end = _py_to_ql_date(ref_end)
        tau = max(float(dc.yearFraction(ql_start, ql_end)), 1e-10)
        df_start = _discount(curve, ql_start)
        df_end = _discount(curve, ql_end)
        forward_rate = max((df_start / df_end - 1.0) / tau, -99.0)
        return float(100.0 - (forward_rate * 100.0))

    def _fetch_market_pricer(self, symbol: str, *, as_of: dt.date) -> Optional[QLSTIRFutureOptionPricer]:
        try:
            out = self._option_mdp.get_data(
                {
                    "endpoint": "option_snapshot",
                    "symbols": [symbol],
                    "timestamp": as_of,
                    "show_tqdm": False,
                }
            )
        except Exception:
            return None

        rows = out.get(symbol)
        if not rows:
            for candidate in out.values():
                if candidate:
                    rows = candidate
                    break
        if not rows:
            return None
        pricer = rows[0]
        if not isinstance(pricer, QLSTIRFutureOptionPricer):
            raise TypeError(f"Expected QLSTIRFutureOptionPricer for {symbol}, got {type(pricer)}")
        return pricer

    def _sabr_fallback_pricer(
        self,
        *,
        contract: str,
        right: str,
        option_symbol: str,
        strike_price: float,
        curve: Any,
        as_of: dt.date,
    ) -> QLSTIRFutureOptionPricer:
        smile = self._option_mdp.fetch_sabr_smile(
            {
                "symbol": contract,
                "as_of": as_of,
                "show_tqdm": False,
                "strike_offsets_bps": "listed",
            }
        )
        vol = float(smile.normal_vol(strike_price, strike_space="price", vol_units="price"))
        forward = float(smile.params.forward_price)
        tte = float(smile.params.time_to_expiry)
        expiry_date = smile.params.expiry_date
        discount = _discount(curve, _py_to_ql_date(expiry_date))
        price = _bachelier_price(right, strike_price, forward, vol, tte, discount)
        delta, gamma, vega, theta = _bachelier_greeks(right, strike_price, forward, vol, tte, discount)
        return QLSTIRFutureOptionPricer(
            symbol=option_symbol,
            right=right,
            underlying_symbol=contract,
            strike=float(strike_price),
            quote_timestamp=smile.quote_timestamp,
            expiry_date=expiry_date,
            market_price=float(price),
            model_price=float(price),
            iv_normal=float(vol),
            delta=float(delta),
            gamma=float(gamma),
            vega=float(vega),
            theta=float(theta),
            forward=float(forward),
            discount=float(discount),
            meta_data={
                "source": "STIRCAPFLOOR_SABR_FALLBACK",
                "quote_source": "sabr_fallback",
                "requested_symbol": option_symbol,
                "barchart_underlying": _contract_to_barchart_contract(contract),
                "sabr_params": smile.params.to_dict(),
            },
        )
