from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer

SOFR_OPTION_POINT_VALUE = 2500.0
SOFR_OPTION_BP_SIZE = 0.01
SOFR_OPTION_BP_VALUE = SOFR_OPTION_POINT_VALUE * SOFR_OPTION_BP_SIZE
SOFR_OPTION_BP_SQUARED_VALUE = SOFR_OPTION_POINT_VALUE * SOFR_OPTION_BP_SIZE * SOFR_OPTION_BP_SIZE


def option_quantity(leg: Any) -> float:
    if hasattr(leg, "quantity"):
        q = leg.quantity
        return float(q() if callable(q) else q)
    return 1.0


def option_symbol(obj: Any) -> str:
    if hasattr(obj, "symbol"):
        sym = obj.symbol
        return str(sym() if callable(sym) else sym).strip().upper()
    return ""


def extract_pricer(entry: Any) -> _STIRFutureOptionGenericPricer:
    candidate = entry[0] if isinstance(entry, list) and entry else entry
    if not isinstance(candidate, _STIRFutureOptionGenericPricer):
        raise TypeError(f"Expected STIR future option pricer, got {type(candidate)}")
    return candidate


def resolve_pricer_for_leg(
    pricers: Mapping[str, Any],
    leg: Any,
    *,
    index: int | None = None,
) -> _STIRFutureOptionGenericPricer:
    symbol = option_symbol(leg)
    if symbol and symbol in pricers:
        return extract_pricer(pricers[symbol])

    matches: list[_STIRFutureOptionGenericPricer] = []
    for entry in pricers.values():
        try:
            pricer = extract_pricer(entry)
        except TypeError:
            continue
        if option_symbol(pricer) == symbol:
            matches.append(pricer)

    if len(matches) == 1:
        return matches[0]

    if index is not None:
        flat: list[_STIRFutureOptionGenericPricer] = []
        for entry in pricers.values():
            try:
                flat.append(extract_pricer(entry))
            except TypeError:
                continue
        if 0 <= int(index) < len(flat):
            return flat[int(index)]

    raise KeyError(f"Could not resolve STIR option pricer for symbol={symbol!r}")


def rebuild_leg_with_quantity(
    pricer: _STIRFutureOptionGenericPricer,
    leg: Any,
    *,
    quantity: float,
) -> Any:
    premium_override = None
    if hasattr(leg, "premium_override"):
        override_attr = leg.premium_override
        premium_override = override_attr() if callable(override_attr) else override_attr
    return pricer.build_pricable(
        symbol=leg.symbol(),
        right=leg.right(),
        strike=leg.strike(),
        expiry_date=leg.expiry_date(),
        quote_timestamp=leg.quote_timestamp(),
        quantity=float(quantity),
        premium_override=premium_override,
    )


def dollar_dv01(pricer: _STIRFutureOptionGenericPricer) -> float:
    return float(pricer.delta()) * SOFR_OPTION_BP_VALUE


def dollar_gamma_01(pricer: _STIRFutureOptionGenericPricer) -> float:
    return float(pricer.gamma()) * SOFR_OPTION_BP_SQUARED_VALUE


def dollar_vega_01(pricer: _STIRFutureOptionGenericPricer) -> float:
    return float(pricer.vega()) * SOFR_OPTION_BP_VALUE
