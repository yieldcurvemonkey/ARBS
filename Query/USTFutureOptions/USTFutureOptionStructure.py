from __future__ import annotations

from enum import Enum, auto
from functools import partial
from typing import Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.USTFutureOptions._USTFutureOptionGenericPricable import _USTFutureOptionGenericPricable
from Query.USTFutureOptions._USTFutureOptionGenericPricer import _USTFutureOptionGenericPricer


class USTFutureOptionStructure(Enum):
    OUTRIGHT = auto()
    VERTICAL = auto()
    STRADDLE = auto()


class USTFutureOptionStructureFunctionMap(
    BaseStructureFunctionMap[USTFutureOptionStructure, _USTFutureOptionGenericPricable]
):
    def __init__(self, pricer: Dict[str, _USTFutureOptionGenericPricer]):
        super().__init__(USTFutureOptionStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(
        self,
    ) -> Dict[USTFutureOptionStructure, Callable[..., Tuple[List[_USTFutureOptionGenericPricable], List[float]]]]:
        return {
            USTFutureOptionStructure.OUTRIGHT: partial(self._build_outright),
            USTFutureOptionStructure.VERTICAL: partial(self._build_vertical),
            USTFutureOptionStructure.STRADDLE: partial(self._build_straddle),
        }

    def _keys(self) -> List[str]:
        return list(self.common_kwargs["pricer"].keys())

    def _resolve_key(self, desired: Optional[str], role: str) -> str:
        pricers: Dict[str, _USTFutureOptionGenericPricer] = self.common_kwargs["pricer"]
        if desired is not None and desired in pricers:
            return desired
        if len(pricers) == 1:
            return next(iter(pricers))
        raise KeyError(
            f"Could not resolve UST option pricer key for {role}. desired={desired!r}, available={list(pricers.keys())}"
        )

    def _resolve_keys_for_n_legs(self, desired: Optional[List[str]], n: int) -> List[str]:
        keys = self._keys()
        if desired is not None:
            if len(desired) != n:
                raise ValueError(f"Expected {n} symbols, got {len(desired)}")
            for k in desired:
                if k not in self.common_kwargs["pricer"]:
                    raise KeyError(f"Missing pricer for key={k!r}. available={keys}")
            return desired
        if len(keys) != n:
            raise ValueError(f"Expected exactly {n} pricers in dict, got {len(keys)}: {keys}")
        return keys

    def _resolve_pricer_for_leg(
        self,
        leg: _USTFutureOptionGenericPricable,
        *,
        index: int,
    ) -> _USTFutureOptionGenericPricer:
        pricers: Dict[str, _USTFutureOptionGenericPricer] = self.common_kwargs["pricer"]
        if leg.symbol() in pricers:
            return pricers[leg.symbol()]
        matches = [pr for pr in pricers.values() if pr.symbol() == leg.symbol()]
        if len(matches) == 1:
            return matches[0]
        flat = list(pricers.values())
        if 0 <= index < len(flat):
            return flat[index]
        raise KeyError(f"Could not resolve UST option pricer for symbol={leg.symbol()!r}")

    @staticmethod
    def _premium_overrides(kwargs: Dict[str, object], n_legs: int) -> List[Optional[float]]:
        premiums = kwargs.get("premiums")
        if premiums is not None:
            if not isinstance(premiums, (list, tuple)) or len(premiums) != n_legs:
                raise ValueError(f"premiums must be a list/tuple with {n_legs} entries")
            return [None if value is None else float(value) for value in premiums]

        premium = kwargs.get("premium")
        if premium is None:
            return [None] * n_legs
        if n_legs != 1:
            raise ValueError("Scalar premium/upfront override is only valid for outright option queries.")
        return [float(premium)]

    def _apply_premium_overrides(
        self,
        package: List[_USTFutureOptionGenericPricable],
        kwargs: Dict[str, object],
    ) -> List[_USTFutureOptionGenericPricable]:
        overrides = self._premium_overrides(kwargs, len(package))
        if not any(value is not None for value in overrides):
            return package

        rebuilt: List[_USTFutureOptionGenericPricable] = []
        for idx, (leg, premium) in enumerate(zip(package, overrides)):
            if premium is None:
                rebuilt.append(leg)
                continue
            pricer = self._resolve_pricer_for_leg(leg, index=idx)
            rebuilt.append(
                pricer.build_pricable(
                    symbol=leg.symbol(),
                    right=leg.right(),
                    strike=leg.strike(),
                    expiry_date=leg.expiry_date(),
                    quote_timestamp=leg.quote_timestamp(),
                    quantity=float(leg.quantity()),
                    premium_override=float(premium),
                )
            )
        return rebuilt

    def _build_outright(
        self,
        *,
        symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_USTFutureOptionGenericPricable], List[float]]:
        key = self._resolve_key(desired=symbol, role="outright.symbol")
        pr = self.common_kwargs["pricer"][key]
        rw = float(risk_weights[0]) if risk_weights else 1.0
        package = [pr.build_pricable(quantity=1.0)]
        return self._apply_premium_overrides(package, _), [rw]

    def _build_vertical(
        self,
        *,
        long_symbol: Optional[str] = None,
        short_symbol: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_USTFutureOptionGenericPricable], List[float]]:
        if symbols is not None:
            keys = self._resolve_keys_for_n_legs(symbols, 2)
        elif long_symbol and short_symbol:
            keys = self._resolve_keys_for_n_legs([long_symbol, short_symbol], 2)
        else:
            keys = self._resolve_keys_for_n_legs(None, 2)

        pr0 = self.common_kwargs["pricer"][keys[0]]
        pr1 = self.common_kwargs["pricer"][keys[1]]
        weights = [1.0, -1.0] if risk_weights is None else [float(x) for x in risk_weights]
        package = [pr0.build_pricable(quantity=1.0), pr1.build_pricable(quantity=1.0)]
        return self._apply_premium_overrides(package, _), weights

    def _build_straddle(
        self,
        *,
        symbol: Optional[str] = None,
        call_symbol: Optional[str] = None,
        put_symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_USTFutureOptionGenericPricable], List[float]]:
        pricers: Dict[str, _USTFutureOptionGenericPricer] = self.common_kwargs["pricer"]

        if symbol is not None and symbol in pricers:
            pr = pricers[symbol]
            weights = [1.0] if risk_weights is None else [float(risk_weights[0])]
            package = [pr.build_pricable(quantity=1.0)]
            return self._apply_premium_overrides(package, _), weights

        if symbol and symbol.upper().endswith("S"):
            call_key = f"{symbol[:-1]}C"
            put_key = f"{symbol[:-1]}P"
            keys = self._resolve_keys_for_n_legs([call_key, put_key], 2)
        elif call_symbol and put_symbol:
            keys = self._resolve_keys_for_n_legs([call_symbol, put_symbol], 2)
        else:
            keys = self._resolve_keys_for_n_legs(None, 2)

        pr0 = pricers[keys[0]]
        pr1 = pricers[keys[1]]
        weights = [1.0, 1.0] if risk_weights is None else [float(x) for x in risk_weights]
        package = [pr0.build_pricable(quantity=1.0), pr1.build_pricable(quantity=1.0)]
        return self._apply_premium_overrides(package, _), weights
