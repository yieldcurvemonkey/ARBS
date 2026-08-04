from __future__ import annotations

from enum import Enum, auto
from functools import partial
from typing import Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.STIRFutureOptions._STIRFutureOptionGenericPricable import _STIRFutureOptionGenericPricable
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer
from Query.STIRFutureOptions._risk import (
    dollar_dv01,
    dollar_gamma_01,
    dollar_vega_01,
    option_quantity,
    rebuild_leg_with_quantity,
    resolve_pricer_for_leg,
)


class STIRFutureOptionStructure(Enum):
    OUTRIGHT = auto()
    VERTICAL = auto()
    STRADDLE = auto()
    FLY = auto()


class STIRFutureOptionStructureFunctionMap(
    BaseStructureFunctionMap[STIRFutureOptionStructure, _STIRFutureOptionGenericPricable]
):
    def __init__(self, pricer: Dict[str, _STIRFutureOptionGenericPricer]):
        super().__init__(STIRFutureOptionStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(
        self,
    ) -> Dict[STIRFutureOptionStructure, Callable[..., Tuple[List[_STIRFutureOptionGenericPricable], List[float]]]]:
        def wrap(
            builder: Callable[..., Tuple[List[_STIRFutureOptionGenericPricable], List[float]]],
        ) -> Callable[..., Tuple[List[_STIRFutureOptionGenericPricable], List[float]]]:
            def _wrapped(**kwargs):
                package, risk_weights = builder(**kwargs)
                return self._apply_size_target(package=package, risk_weights=risk_weights, kwargs=kwargs)

            return _wrapped

        return {
            STIRFutureOptionStructure.OUTRIGHT: wrap(partial(self._build_outright)),
            STIRFutureOptionStructure.VERTICAL: wrap(partial(self._build_vertical)),
            STIRFutureOptionStructure.STRADDLE: wrap(partial(self._build_straddle)),
            STIRFutureOptionStructure.FLY: wrap(partial(self._build_fly)),
        }

    @staticmethod
    def _size_targets(kwargs: Dict[str, object]) -> List[Tuple[str, float]]:
        targets: List[Tuple[str, float]] = []
        for key in ("contracts", "dv01", "gamma_01", "gamma01", "vega_01", "vega01"):
            raw = kwargs.get(key)
            if raw is None:
                continue
            targets.append((str(key), abs(float(raw))))
        return targets

    def _package_metric(
        self,
        *,
        package: List[_STIRFutureOptionGenericPricable],
        risk_weights: List[float],
        metric: str,
    ) -> float:
        total = 0.0
        pricers = self.common_kwargs["pricer"]
        for idx, (rw, leg) in enumerate(zip(risk_weights, package)):
            pricer = resolve_pricer_for_leg(pricers, leg, index=idx)
            if metric == "dv01":
                leg_metric = dollar_dv01(pricer)
            elif metric in {"gamma_01", "gamma01"}:
                leg_metric = dollar_gamma_01(pricer)
            elif metric in {"vega_01", "vega01"}:
                leg_metric = dollar_vega_01(pricer)
            else:
                raise KeyError(f"Unsupported STIR option size target '{metric}'")
            total += float(rw) * float(option_quantity(leg)) * float(leg_metric)
        return float(total)

    def _scale_package(
        self,
        *,
        package: List[_STIRFutureOptionGenericPricable],
        scale: float,
    ) -> List[_STIRFutureOptionGenericPricable]:
        pricers = self.common_kwargs["pricer"]
        scaled: List[_STIRFutureOptionGenericPricable] = []
        for idx, leg in enumerate(package):
            pricer = resolve_pricer_for_leg(pricers, leg, index=idx)
            qty = abs(float(option_quantity(leg))) * float(scale)
            scaled.append(rebuild_leg_with_quantity(pricer, leg, quantity=qty))
        return scaled

    def _apply_size_target(
        self,
        *,
        package: List[_STIRFutureOptionGenericPricable],
        risk_weights: List[float],
        kwargs: Dict[str, object],
    ) -> Tuple[List[_STIRFutureOptionGenericPricable], List[float]]:
        targets = self._size_targets(kwargs)
        if not targets:
            return package, risk_weights
        if len(targets) > 1:
            labels = ", ".join(key for key, _ in targets)
            raise ValueError(f"Specify only one STIR option size target, got: {labels}")

        metric, target = targets[0]
        if metric == "contracts":
            return self._scale_package(package=package, scale=float(target)), risk_weights

        if target == 0.0:
            return self._scale_package(package=package, scale=0.0), risk_weights

        current = self._package_metric(package=package, risk_weights=risk_weights, metric=metric)
        if abs(current) < 1e-12:
            raise ValueError(f"Cannot scale STIR option package to target {metric} because current package {metric} is zero.")

        scale = float(target) / abs(float(current))
        return self._scale_package(package=package, scale=scale), risk_weights

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
        package: List[_STIRFutureOptionGenericPricable],
        kwargs: Dict[str, object],
    ) -> List[_STIRFutureOptionGenericPricable]:
        overrides = self._premium_overrides(kwargs, len(package))
        if not any(value is not None for value in overrides):
            return package

        pricers = self.common_kwargs["pricer"]
        rebuilt: List[_STIRFutureOptionGenericPricable] = []
        for idx, (leg, premium) in enumerate(zip(package, overrides)):
            if premium is None:
                rebuilt.append(leg)
                continue
            pricer = resolve_pricer_for_leg(pricers, leg, index=idx)
            rebuilt.append(
                pricer.build_pricable(
                    symbol=leg.symbol(),
                    right=leg.right(),
                    strike=leg.strike(),
                    expiry_date=leg.expiry_date(),
                    quote_timestamp=leg.quote_timestamp(),
                    quantity=float(option_quantity(leg)),
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
    ) -> Tuple[List[_STIRFutureOptionGenericPricable], List[float]]:
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
        package = [pr0.build_pricable(quantity=1.0), pr1.build_pricable(quantity=1.0)]
        return self._apply_premium_overrides(package, _), weights

    def _build_fly(
        self,
        *,
        low_symbol: Optional[str] = None,
        mid_symbol: Optional[str] = None,
        high_symbol: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_STIRFutureOptionGenericPricable], List[float]]:
        """1/-2/1 butterfly across three strikes, same right on every leg.

        Long fly (default weights ``[1, -2, 1]``) pays when the underlying
        settles at the mid strike; pass ``[-1, 2, -1]`` for the short fly.
        """
        if symbols is not None:
            keys = self._resolve_keys_for_n_legs(list(symbols), 3)
        elif low_symbol and mid_symbol and high_symbol:
            keys = self._resolve_keys_for_n_legs(
                [low_symbol, mid_symbol, high_symbol], 3)
        else:
            keys = self._resolve_keys_for_n_legs(None, 3)
        pricers = self.common_kwargs["pricer"]
        weights = ([1.0, -2.0, 1.0] if risk_weights is None
                   else [float(x) for x in risk_weights])
        if len(weights) != 3:
            raise ValueError(f"FLY requires 3 risk weights, got {len(weights)}")
        package = [pricers[k].build_pricable(quantity=1.0) for k in keys]
        return self._apply_premium_overrides(package, _), weights

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
