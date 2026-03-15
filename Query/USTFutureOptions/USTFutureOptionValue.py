from __future__ import annotations

from enum import Enum, auto
import math
from typing import Any, Callable, Dict, Iterable, Tuple

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Base.bachelier import bachelier_greeks_fd, implied_normal_vol
from Query.USTFutureOptions._USTFutureOptionGenericPricable import _USTFutureOptionGenericPricable
from Query.USTFutureOptions._USTFutureOptionGenericPricer import _USTFutureOptionGenericPricer


class USTFutureOptionValue(Enum):
    PRICE = auto()
    NPV = auto()
    DELTA = auto()
    GAMMA = auto()
    VEGA = auto()
    THETA = auto()
    IV_NORMAL_BPS = auto()


class USTFutureOptionValueFunctionMap(BaseValueFunctionMap[USTFutureOptionValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _USTFutureOptionGenericPricer],
        package: list[_USTFutureOptionGenericPricable],
        risk_weights: list[float],
    ):
        super().__init__(USTFutureOptionValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[USTFutureOptionValue, Callable[..., float]]:
        return {
            USTFutureOptionValue.PRICE: self._price,
            USTFutureOptionValue.NPV: self._npv,
            USTFutureOptionValue.DELTA: self._delta,
            USTFutureOptionValue.GAMMA: self._gamma,
            USTFutureOptionValue.VEGA: self._vega,
            USTFutureOptionValue.THETA: self._theta,
            USTFutureOptionValue.IV_NORMAL_BPS: self._iv_normal_bps,
        }

    @staticmethod
    def _premium_override(leg: _USTFutureOptionGenericPricable) -> float | None:
        if not hasattr(leg, "premium_override"):
            return None
        override = leg.premium_override
        value = override() if callable(override) else override
        if value is None:
            return None
        return abs(float(value))

    @staticmethod
    def _resolve_pricer_for_leg(
        pricers: Dict[str, _USTFutureOptionGenericPricer],
        leg: _USTFutureOptionGenericPricable,
        *,
        index: int | None = None,
    ) -> _USTFutureOptionGenericPricer:
        symbol = leg.symbol()
        if symbol in pricers:
            return pricers[symbol]

        matches = [pr for pr in pricers.values() if pr.symbol() == symbol]
        if len(matches) == 1:
            return matches[0]
        if index is not None:
            flat = list(pricers.values())
            if 0 <= index < len(flat):
                return flat[index]
        raise KeyError(f"Could not resolve UST option pricer for symbol={symbol!r}")

    @classmethod
    def _iter_components(
        cls,
        *,
        pricer: Dict[str, _USTFutureOptionGenericPricer],
        package: list[_USTFutureOptionGenericPricable],
        risk_weights: list[float],
        **_: Any,
    ) -> Iterable[Tuple[float, _USTFutureOptionGenericPricer, _USTFutureOptionGenericPricable, float]]:
        for idx, (rw, leg) in enumerate(zip(risk_weights, package)):
            resolved = cls._resolve_pricer_for_leg(pricer, leg, index=idx)
            yield float(rw), resolved, leg, float(leg.quantity())

    @classmethod
    def _effective_metrics(
        cls,
        pr: _USTFutureOptionGenericPricer,
        leg: _USTFutureOptionGenericPricable,
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
        fv01 = float(pr.fv01())
        iv_normal_bps = float(iv) / fv01 if math.isfinite(iv) and fv01 > 0.0 else float("nan")
        return {
            "price": float(premium_override),
            "delta": float(delta),
            "gamma": float(gamma),
            "vega": float(vega),
            "theta": float(theta),
            "iv_normal_bps": iv_normal_bps,
        }

    def _price(self, **kwargs: Any) -> float:
        return sum(rw * self._effective_metrics(pr, leg)["price"] for rw, pr, leg, _ in self._iter_components(**kwargs))

    def _npv(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["price"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _delta(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["delta"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _gamma(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["gamma"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _vega(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["vega"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _theta(self, **kwargs: Any) -> float:
        return sum(rw * qty * self._effective_metrics(pr, leg)["theta"] for rw, pr, leg, qty in self._iter_components(**kwargs))

    def _iv_normal_bps(self, **kwargs: Any) -> float:
        return sum(rw * self._effective_metrics(pr, leg)["iv_normal_bps"] for rw, pr, leg, _ in self._iter_components(**kwargs))
