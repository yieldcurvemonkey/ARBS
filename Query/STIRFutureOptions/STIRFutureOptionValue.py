from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from enum import Enum, auto
from typing import Any, Callable, Dict, Tuple

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Base.bachelier import bachelier_greeks_fd, implied_normal_vol
from Query.STIRFutureOptions._STIRFutureOptionGenericPricable import _STIRFutureOptionGenericPricable
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer
from Query.STIRFutureOptions._risk import (
    SOFR_OPTION_BP_SIZE,
    SOFR_OPTION_BP_VALUE,
    SOFR_OPTION_BP_SQUARED_VALUE,
    option_quantity,
    resolve_pricer_for_leg,
)


class STIRFutureOptionValue(Enum):
    PRICE = auto()
    NPV = auto()
    DV01 = auto()
    DELTA = auto()
    GAMMA = auto()
    GAMMA_01 = auto()
    VEGA = auto()
    VEGA_01 = auto()
    THETA = auto()
    IV_NORMAL_BPS = auto()
    BID = auto()
    ASK = auto()
    MID = auto()
    LAST = auto()
    BID_SIZE = auto()
    ASK_SIZE = auto()
    MARK = auto()
    NET_CHANGE = auto()
    QUOTE_TIME = auto()
    RAW_QUOTE = auto()


class STIRFutureOptionValueFunctionMap(BaseValueFunctionMap[STIRFutureOptionValue, Any]):
    def __init__(
        self,
        pricer: Dict[str, _STIRFutureOptionGenericPricer],
        package: list[_STIRFutureOptionGenericPricable],
        risk_weights: list[float],
    ):
        super().__init__(STIRFutureOptionValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[STIRFutureOptionValue, Callable[..., Any]]:
        return {
            STIRFutureOptionValue.PRICE: self._price,
            STIRFutureOptionValue.NPV: self._npv,
            STIRFutureOptionValue.DV01: self._dv01,
            STIRFutureOptionValue.DELTA: self._delta,
            STIRFutureOptionValue.GAMMA: self._gamma,
            STIRFutureOptionValue.GAMMA_01: self._gamma_01,
            STIRFutureOptionValue.VEGA: self._vega,
            STIRFutureOptionValue.VEGA_01: self._vega_01,
            STIRFutureOptionValue.THETA: self._theta,
            STIRFutureOptionValue.IV_NORMAL_BPS: self._iv_normal_bps,
            STIRFutureOptionValue.BID: self._bid,
            STIRFutureOptionValue.ASK: self._ask,
            STIRFutureOptionValue.MID: self._mid,
            STIRFutureOptionValue.LAST: self._last,
            STIRFutureOptionValue.BID_SIZE: self._bid_size,
            STIRFutureOptionValue.ASK_SIZE: self._ask_size,
            STIRFutureOptionValue.MARK: self._mark,
            STIRFutureOptionValue.NET_CHANGE: self._net_change,
            STIRFutureOptionValue.QUOTE_TIME: self._quote_time,
            STIRFutureOptionValue.RAW_QUOTE: self._raw_quote,
        }

    @staticmethod
    def _iter_components(
        *,
        pricer: Dict[str, _STIRFutureOptionGenericPricer],
        package: list[_STIRFutureOptionGenericPricable],
        risk_weights: list[float],
        **_: Any,
    ) -> Iterable[Tuple[float, _STIRFutureOptionGenericPricer, _STIRFutureOptionGenericPricable, float]]:
        pricers = pricer
        package = package
        risk_weights = risk_weights
        for idx, (rw, leg) in enumerate(zip(risk_weights, package)):
            pricer = resolve_pricer_for_leg(pricers, leg, index=idx)
            qty = float(option_quantity(leg))
            yield float(rw), pricer, leg, qty

    @staticmethod
    def _quote_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(out):
            return None
        return out

    @classmethod
    def _quote_value(cls, quote: Mapping[str, Any], *keys: str) -> float | None:
        for key in keys:
            if key in quote:
                return cls._quote_float(quote.get(key))
        return None

    @staticmethod
    def _quote_dict(value: Any) -> Dict[str, Any] | None:
        if isinstance(value, Mapping):
            return dict(value)
        return None

    @classmethod
    def _quote_legs_for_pricer(cls, pricer: _STIRFutureOptionGenericPricer) -> list[tuple[str, Dict[str, Any]]]:
        meta = pricer.meta()
        meta_dict = meta if isinstance(meta, Mapping) else {}

        raw_quote_legs = meta_dict.get("raw_quote_legs")
        if isinstance(raw_quote_legs, Mapping):
            out: list[tuple[str, Dict[str, Any]]] = []
            for symbol, quote in raw_quote_legs.items():
                quote_dict = cls._quote_dict(quote)
                if quote_dict is not None:
                    out.append((str(symbol), quote_dict))
            if out:
                return out

        vendor_legs = meta_dict.get("vendor_legs")
        if isinstance(vendor_legs, Iterable) and not isinstance(vendor_legs, (str, bytes, Mapping)):
            out = []
            for idx, row in enumerate(vendor_legs):
                quote_dict = cls._quote_dict(row)
                if quote_dict is None:
                    continue
                symbol = str(quote_dict.get("symbol") or f"{pricer.symbol()}#{idx}")
                out.append((symbol, quote_dict))
            if out:
                return out

        quote_dict = cls._quote_dict(meta_dict.get("raw_quote"))
        if quote_dict is None:
            quote_dict = cls._quote_dict(meta_dict.get("vendor_quote"))
        if quote_dict is None:
            quote_dict = cls._quote_dict(meta_dict.get("vendor_row"))
        if quote_dict is None:
            return []
        return [(str(quote_dict.get("symbol") or pricer.symbol()), quote_dict)]

    @classmethod
    def _iter_quote_legs(
        cls,
        **kwargs: Any,
    ) -> Iterable[Tuple[float, str, Dict[str, Any]]]:
        for rw, pr, _, _ in cls._iter_components(**kwargs):
            for symbol, quote in cls._quote_legs_for_pricer(pr):
                yield float(rw), symbol, quote

    @classmethod
    def _aggregate_quote_field(cls, *keys: str, **kwargs: Any) -> float:
        total = 0.0
        seen = False
        for rw, _, quote in cls._iter_quote_legs(**kwargs):
            value = cls._quote_value(quote, *keys)
            if value is None:
                return float("nan")
            total += float(rw) * float(value)
            seen = True
        return total if seen else float("nan")

    @classmethod
    def _aggregate_side_quote(cls, *, side: str, **kwargs: Any) -> float:
        total = 0.0
        seen = False
        for rw, _, quote in cls._iter_quote_legs(**kwargs):
            keys = ("bid", "Bid") if (side == "bid") == (rw >= 0.0) else ("ask", "Ask")
            value = cls._quote_value(quote, *keys)
            if value is None:
                return float("nan")
            total += float(rw) * float(value)
            seen = True
        return total if seen else float("nan")

    @classmethod
    def _aggregate_size(cls, *, side: str, **kwargs: Any) -> float:
        sizes: list[float] = []
        for rw, _, quote in cls._iter_quote_legs(**kwargs):
            scale = abs(float(rw))
            if scale <= 0.0:
                continue
            keys = ("bidSize", "BidSize") if (side == "bid") == (rw >= 0.0) else ("askSize", "AskSize")
            value = cls._quote_value(quote, *keys)
            if value is None:
                return float("nan")
            sizes.append(float(value) / scale)
        if not sizes:
            return float("nan")
        return min(sizes)

    @staticmethod
    def _premium_override(leg: _STIRFutureOptionGenericPricable) -> float | None:
        if not hasattr(leg, "premium_override"):
            return None
        override = leg.premium_override
        value = override() if callable(override) else override
        if value is None:
            return None
        return abs(float(value))

    @classmethod
    def _effective_metrics(
        cls,
        pr: _STIRFutureOptionGenericPricer,
        leg: _STIRFutureOptionGenericPricable,
    ) -> Dict[str, float]:
        premium_override = cls._premium_override(leg)
        if premium_override is None:
            return {
                "price": float(pr.price()),
                "delta": float(pr.delta()),
                "gamma": float(pr.gamma()),
                "vega": float(pr.vega()),
                "theta": float(pr.theta()),
                "iv_normal_bps": float(pr.iv_normal_bps()),
            }

        tte = max((leg.expiry_date() - pr.quote_timestamp().date()).days / 365.0, 1e-12)
        iv = implied_normal_vol(
            right=leg.right(),
            strike=float(leg.strike()),
            forward=float(pr.forward()),
            tte=float(tte),
            price=float(premium_override),
            discount=float(pr.discount()),
        )
        delta, gamma, vega, theta = bachelier_greeks_fd(
            right=leg.right(),
            strike=float(leg.strike()),
            forward=float(pr.forward()),
            vol_normal=float(iv),
            tte=float(tte),
            discount=float(pr.discount()),
        )
        return {
            "price": float(premium_override),
            "delta": float(delta),
            "gamma": float(gamma),
            "vega": float(vega),
            "theta": float(theta),
            "iv_normal_bps": float(iv) / SOFR_OPTION_BP_SIZE if math.isfinite(iv) else float("nan"),
        }

    def _price(self, **kwargs: Any) -> float:
        return sum(rw * self._effective_metrics(pr, leg)["price"] for rw, pr, leg, _ in self._iter_components(**kwargs))

    def _npv(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, pk)["price"] for rw, pr, pk, qty in self._iter_components(**kwargs))

    def _dv01(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["delta"] * SOFR_OPTION_BP_VALUE for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _delta(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["delta"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _gamma(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["gamma"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _gamma_01(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["gamma"] * SOFR_OPTION_BP_SQUARED_VALUE for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _vega(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["vega"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _vega_01(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["vega"] * SOFR_OPTION_BP_VALUE for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _theta(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["theta"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _iv_normal_bps(self, **kwargs: Any) -> float:
        return sum(rw * self._effective_metrics(pr, leg)["iv_normal_bps"] for rw, pr, leg, _ in self._iter_components(**kwargs))

    def _bid(self, **kwargs: Any) -> float:
        return self._aggregate_side_quote(side="bid", **kwargs)

    def _ask(self, **kwargs: Any) -> float:
        return self._aggregate_side_quote(side="ask", **kwargs)

    def _mid(self, **kwargs: Any) -> float:
        bid = self._bid(**kwargs)
        ask = self._ask(**kwargs)
        if math.isfinite(bid) and math.isfinite(ask):
            return (bid + ask) / 2.0
        return self._aggregate_quote_field("mid", "Mid", **kwargs)

    def _last(self, **kwargs: Any) -> float:
        return self._aggregate_quote_field("last", "Last", "lastPrice", **kwargs)

    def _bid_size(self, **kwargs: Any) -> float:
        return self._aggregate_size(side="bid", **kwargs)

    def _ask_size(self, **kwargs: Any) -> float:
        return self._aggregate_size(side="ask", **kwargs)

    def _mark(self, **kwargs: Any) -> float:
        return self._aggregate_quote_field("mark", "Mark", **kwargs)

    def _net_change(self, **kwargs: Any) -> float:
        return self._aggregate_quote_field("netChange", "NetChange", **kwargs)

    def _quote_time(self, **kwargs: Any) -> int | float:
        quote_times: list[float] = []
        for _, _, quote in self._iter_quote_legs(**kwargs):
            value = self._quote_value(quote, "quoteTime", "QuoteTime")
            if value is not None:
                quote_times.append(float(value))
        if not quote_times:
            return float("nan")
        latest = max(quote_times)
        return int(latest) if latest.is_integer() else latest

    def _raw_quote(self, **kwargs: Any) -> Dict[str, Any]:
        quotes = list(self._iter_quote_legs(**kwargs))
        if not quotes:
            return {}
        if len(quotes) == 1:
            return dict(quotes[0][2])

        out: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for idx, (_, symbol, quote) in enumerate(quotes):
            key = str(symbol)
            if key in out:
                key = f"{key}#{idx}"
            out[key] = dict(quote)
        return dict(out)
