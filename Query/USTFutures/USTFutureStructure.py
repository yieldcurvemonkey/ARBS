from __future__ import annotations

import datetime
from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.USTFutures._USTFutureGenericPricable import _USTFutureGenericPricable
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer


class USTFutureStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    FLY = auto()
    SPREAD = auto()
    WEIGHTED_FLY = auto()


class USTFutureStructureFunctionMap(BaseStructureFunctionMap[USTFutureStructure, _USTFutureGenericPricable]):
    def __init__(self, pricer: Dict[str, _USTFutureGenericPricer]):
        super().__init__(USTFutureStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[USTFutureStructure, Callable[..., Tuple[List[_USTFutureGenericPricable], List[float]]]]:
        return {
            USTFutureStructure.OUTRIGHT: partial(self._build_outright),
            USTFutureStructure.CURVE: partial(self._build_curve),
            USTFutureStructure.SPREAD: partial(self._build_curve),
            USTFutureStructure.FLY: partial(self._build_fly),
            USTFutureStructure.WEIGHTED_FLY: partial(self._build_weighted_fly),
        }

    def _keys(self) -> List[str]:
        return list(self.common_kwargs["pricer"].keys())

    def _resolve_key(self, *, desired: Optional[str], role: str) -> str:
        pricers: Dict[str, _USTFutureGenericPricer] = self.common_kwargs["pricer"]
        if desired is not None and desired in pricers:
            return desired
        if len(pricers) == 1:
            return next(iter(pricers.keys()))
        raise KeyError(f"Could not resolve UST pricer key for {role}. desired={desired!r}, available={list(pricers.keys())}")

    def _resolve_keys_for_n_legs(self, desired: Optional[List[str]], n: int) -> List[str]:
        keys = self._keys()
        if desired is not None:
            if len(desired) != n:
                raise ValueError(f"Expected {n} pricer keys, got {len(desired)}")
            for k in desired:
                if k not in self.common_kwargs["pricer"]:
                    raise KeyError(f"Missing pricer for key={k!r}. available={keys}")
            return desired
        if len(keys) != n:
            raise ValueError(f"Expected exactly {n} pricers in dict, got {len(keys)}: {keys}")
        return keys

    def _build_leg(
        self,
        *,
        key: str,
        contract_code: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        **kwargs,
    ) -> _USTFutureGenericPricable:
        pr = self.common_kwargs["pricer"][key]
        if hasattr(pr, "build_pricable"):
            return pr.build_pricable(
                contract_code=contract_code,
                effective_date=effective_date,
                maturity_date=maturity_date,
                price=price,
                contracts=contracts,
                notional=notional,
            )
        return pr.build_ustf(
            contract_code=contract_code,
            effective_date=effective_date,
            maturity_date=maturity_date,
            price=price,
            contracts=contracts,
            notional=notional,
        )

    def _pv01_per_contract(self, *, key: str) -> float:
        pr = self.common_kwargs["pricer"][key]
        one = self._build_leg(key=key, contracts=1)
        return float(pr.pv01(one))

    def _solve_contracts_from_risk_weights(
        self,
        *,
        keys: List[str],
        risk_weights: List[float],
        constrained_leg_index: int,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
    ) -> List[int]:
        if sum(v is not None for v in (constrained_contracts, constrained_bpv)) != 1:
            raise ValueError("Must specify exactly one of constrained_contracts or constrained_bpv")

        rw = [float(x) for x in risk_weights]
        if not (0 <= constrained_leg_index < len(keys)):
            raise IndexError("constrained_leg_index out of range")
        if rw[constrained_leg_index] == 0.0:
            raise ValueError("constrained leg risk_weight cannot be 0")

        pv01s = [self._pv01_per_contract(key=kk) for kk in keys]
        if any(p == 0.0 for p in pv01s):
            raise ValueError(f"Encountered pv01_per_contract == 0 for keys={keys} pv01s={pv01s}")

        if constrained_contracts is not None:
            alpha = float(constrained_contracts) * pv01s[constrained_leg_index] / rw[constrained_leg_index]
        else:
            alpha = float(constrained_bpv) / rw[constrained_leg_index]

        return [int(round(alpha * rw_i / pv01_i)) for rw_i, pv01_i in zip(rw, pv01s)]

    def _leg_kwargs(
        self,
        *,
        key: str,
        prefix: str,
        contracts: Optional[int],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        leg_kwargs: Dict[str, Any] = {"key": key}
        for field in ("contract_code", "effective_date", "maturity_date", "price", "notional"):
            prefixed = kwargs.get(f"{prefix}_{field}") if prefix else None
            shared = kwargs.get(field)
            value = prefixed if prefixed is not None else shared
            if value is not None:
                leg_kwargs[field] = value

        prefixed_contracts = kwargs.get(f"{prefix}_contracts") if prefix else None
        if prefixed_contracts is not None:
            leg_kwargs["contracts"] = prefixed_contracts
        elif contracts is not None:
            leg_kwargs["contracts"] = contracts

        return leg_kwargs

    def _build_outright(
        self,
        *,
        symbol: Optional[str] = None,
        contract_code: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        risk_weights: Optional[List[float]] = None,
        **kwargs,
    ) -> Tuple[List[_USTFutureGenericPricable], List[float]]:
        key = self._resolve_key(desired=symbol, role="outright.symbol")

        if contracts is None and notional is None:
            contracts = 1

        leg = self._build_leg(
            key=key,
            contract_code=contract_code,
            effective_date=effective_date,
            maturity_date=maturity_date,
            price=price,
            contracts=contracts,
            notional=notional,
        )

        rw = risk_weights[0] if risk_weights else 1.0
        if (contracts is not None and contracts < 0) or (notional is not None and notional < 0):
            rw = -abs(float(rw))

        return [leg], [float(rw)]

    def _build_curve(
        self,
        *,
        front_symbol: Optional[str] = None,
        back_symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        constrained_leg_index: int = 0,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        dv01_weighted: bool = False,
        **kwargs,
    ) -> Tuple[List[_USTFutureGenericPricable], List[float]]:
        if risk_weights is None:
            risk_weights = [1.0, -1.0]

        pr = self.common_kwargs["pricer"]
        if front_symbol in pr and back_symbol in pr:
            keys = [front_symbol, back_symbol]
        else:
            keys = self._resolve_keys_for_n_legs(desired=None, n=2)

        if dv01_weighted:
            pv01s = [self._pv01_per_contract(key=k) for k in keys]
            risk_weights = [1.0, -pv01s[0] / pv01s[1]]

        contracts: Optional[List[int]] = None
        if constrained_contracts is not None or constrained_bpv is not None:
            contracts = self._solve_contracts_from_risk_weights(
                keys=keys,
                risk_weights=risk_weights,
                constrained_leg_index=constrained_leg_index,
                constrained_contracts=constrained_contracts,
                constrained_bpv=constrained_bpv,
            )

        legs = [
            self._build_leg(**self._leg_kwargs(key=keys[0], prefix="front", contracts=(contracts[0] if contracts else None), kwargs=kwargs)),
            self._build_leg(**self._leg_kwargs(key=keys[1], prefix="back", contracts=(contracts[1] if contracts else None), kwargs=kwargs)),
        ]
        return legs, [float(x) for x in risk_weights]

    def _build_fly(
        self,
        *,
        symbols: Optional[List[str]] = None,
        front_symbol: Optional[str] = None,
        belly_symbol: Optional[str] = None,
        back_symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        constrained_leg_index: int = 1,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        **kwargs,
    ) -> Tuple[List[_USTFutureGenericPricable], List[float]]:
        if risk_weights is None:
            risk_weights = [1.0, -2.0, 1.0]

        pr = self.common_kwargs["pricer"]
        if symbols is not None:
            if len(symbols) != 3:
                raise ValueError("FLY: symbols must have length 3")
            keys = self._resolve_keys_for_n_legs(desired=symbols, n=3)
        elif front_symbol in pr and belly_symbol in pr and back_symbol in pr:
            keys = [front_symbol, belly_symbol, back_symbol]
        else:
            keys = self._resolve_keys_for_n_legs(desired=None, n=3)

        contracts: Optional[List[int]] = None
        if constrained_contracts is not None or constrained_bpv is not None:
            contracts = self._solve_contracts_from_risk_weights(
                keys=keys,
                risk_weights=risk_weights,
                constrained_leg_index=constrained_leg_index,
                constrained_contracts=constrained_contracts,
                constrained_bpv=constrained_bpv,
            )

        legs = [
            self._build_leg(**self._leg_kwargs(key=keys[0], prefix="front", contracts=(contracts[0] if contracts else None), kwargs=kwargs)),
            self._build_leg(**self._leg_kwargs(key=keys[1], prefix="belly", contracts=(contracts[1] if contracts else None), kwargs=kwargs)),
            self._build_leg(**self._leg_kwargs(key=keys[2], prefix="back", contracts=(contracts[2] if contracts else None), kwargs=kwargs)),
        ]
        return legs, [float(x) for x in risk_weights]

    def _build_weighted_fly(
        self,
        *,
        symbols: Optional[List[str]] = None,
        front_symbol: Optional[str] = None,
        belly_symbol: Optional[str] = None,
        back_symbol: Optional[str] = None,
        constrained_leg_index: int = 1,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        **kwargs,
    ) -> Tuple[List[_USTFutureGenericPricable], List[float]]:
        pr = self.common_kwargs["pricer"]
        if symbols is not None:
            if len(symbols) != 3:
                raise ValueError("WEIGHTED_FLY: symbols must have length 3")
            keys = self._resolve_keys_for_n_legs(desired=symbols, n=3)
        elif front_symbol in pr and belly_symbol in pr and back_symbol in pr:
            keys = [front_symbol, belly_symbol, back_symbol]
        else:
            keys = self._resolve_keys_for_n_legs(desired=None, n=3)

        pv01s = [self._pv01_per_contract(key=k) for k in keys]
        belly_weight = -(pv01s[0] + pv01s[2]) / pv01s[1]
        risk_weights = [1.0, belly_weight, 1.0]

        contracts: Optional[List[int]] = None
        if constrained_contracts is not None or constrained_bpv is not None:
            contracts = self._solve_contracts_from_risk_weights(
                keys=keys,
                risk_weights=risk_weights,
                constrained_leg_index=constrained_leg_index,
                constrained_contracts=constrained_contracts,
                constrained_bpv=constrained_bpv,
            )

        legs = [
            self._build_leg(**self._leg_kwargs(key=keys[0], prefix="front", contracts=(contracts[0] if contracts else None), kwargs=kwargs)),
            self._build_leg(**self._leg_kwargs(key=keys[1], prefix="belly", contracts=(contracts[1] if contracts else None), kwargs=kwargs)),
            self._build_leg(**self._leg_kwargs(key=keys[2], prefix="back", contracts=(contracts[2] if contracts else None), kwargs=kwargs)),
        ]
        return legs, [float(x) for x in risk_weights]
