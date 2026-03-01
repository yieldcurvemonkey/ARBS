from __future__ import annotations

from enum import Enum, auto
from functools import partial
from typing import Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.STIRFutureOptions._STIRFutureOptionGenericPricable import _STIRFutureOptionGenericPricable
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer


class STIRFutureOptionStructure(Enum):
    OUTRIGHT = auto()
    VERTICAL = auto()
    STRADDLE = auto()


class STIRFutureOptionStructureFunctionMap(
    BaseStructureFunctionMap[STIRFutureOptionStructure, _STIRFutureOptionGenericPricable]
):
    def __init__(self, pricer: Dict[str, _STIRFutureOptionGenericPricer]):
        super().__init__(STIRFutureOptionStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(
        self,
    ) -> Dict[STIRFutureOptionStructure, Callable[..., Tuple[List[_STIRFutureOptionGenericPricable], List[float]]]]:
        return {
            STIRFutureOptionStructure.OUTRIGHT: partial(self._build_outright),
            STIRFutureOptionStructure.VERTICAL: partial(self._build_vertical),
            STIRFutureOptionStructure.STRADDLE: partial(self._build_straddle),
        }

    def _keys(self) -> List[str]:
        return list(self.common_kwargs["pricer"].keys())

    def _resolve_key(self, desired: Optional[str], role: str) -> str:
        pricers: Dict[str, _STIRFutureOptionGenericPricer] = self.common_kwargs["pricer"]
        if desired is not None and desired in pricers:
            return desired
        if len(pricers) == 1:
            return next(iter(pricers))
        raise KeyError(f"Could not resolve STIR option pricer key for {role}. desired={desired!r}, available={list(pricers.keys())}")

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

    def _build_outright(
        self,
        *,
        symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_STIRFutureOptionGenericPricable], List[float]]:
        key = self._resolve_key(desired=symbol, role="outright.symbol")
        pr = self.common_kwargs["pricer"][key]
        rw = float(risk_weights[0]) if risk_weights else 1.0
        return [pr.build_pricable(quantity=1.0)], [rw]

    def _build_vertical(
        self,
        *,
        long_symbol: Optional[str] = None,
        short_symbol: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_STIRFutureOptionGenericPricable], List[float]]:
        if symbols is not None:
            keys = self._resolve_keys_for_n_legs(symbols, 2)
        elif long_symbol and short_symbol:
            keys = self._resolve_keys_for_n_legs([long_symbol, short_symbol], 2)
        else:
            keys = self._resolve_keys_for_n_legs(None, 2)

        pr0 = self.common_kwargs["pricer"][keys[0]]
        pr1 = self.common_kwargs["pricer"][keys[1]]
        weights = [1.0, -1.0] if risk_weights is None else [float(x) for x in risk_weights]
        return [pr0.build_pricable(quantity=1.0), pr1.build_pricable(quantity=1.0)], weights

    def _build_straddle(
        self,
        *,
        symbol: Optional[str] = None,
        call_symbol: Optional[str] = None,
        put_symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_STIRFutureOptionGenericPricable], List[float]]:
        pricers: Dict[str, _STIRFutureOptionGenericPricer] = self.common_kwargs["pricer"]

        if symbol is not None and symbol in pricers:
            pr = pricers[symbol]
            weights = [1.0] if risk_weights is None else [float(risk_weights[0])]
            return [pr.build_pricable(quantity=1.0)], weights

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
        return [pr0.build_pricable(quantity=1.0), pr1.build_pricable(quantity=1.0)], weights
