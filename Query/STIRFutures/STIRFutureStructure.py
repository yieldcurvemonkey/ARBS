from __future__ import annotations

import datetime
from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.STIRFutures._STIRFutureGenericPricable import _STIRFutureGenericPricable
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer


class STIRFutureStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    BASIS = auto()
    FLY = auto()

    SPREAD = CURVE


def _require_exactly_one(**kwargs: Any) -> None:
    if sum(v is not None for v in kwargs.values()) != 1:
        keys = "/".join(kwargs.keys())
        raise ValueError(f"Must specify exactly one of {keys}")


class STIRFutureStructureFunctionMap(BaseStructureFunctionMap[STIRFutureStructure, _STIRFutureGenericPricable]):
    """
    pricer schema: Dict[key, _STIRFutureGenericPricer]
      - OUTRIGHT: expects either 1 pricer in dict OR symbol resolves to a key.
      - CURVE/SPREAD: expects (front, back) pricers (2 keys) OR resolves by front_symbol/back_symbol keys.
      - FLY: expects 3 pricers OR resolves by symbols.
      - BASIS: expects 2 pricers (front/back curves) OR resolves by basis_front_key/basis_back_key.
    """

    def __init__(self, pricer: Dict[str, _STIRFutureGenericPricer]):
        super().__init__(STIRFutureStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[STIRFutureStructure, Callable[..., Tuple[List[_STIRFutureGenericPricable], List[float]]]]:
        return {
            STIRFutureStructure.OUTRIGHT: partial(self._build_outright),
            STIRFutureStructure.CURVE: partial(self._build_curve),
            STIRFutureStructure.SPREAD: partial(self._build_curve),
            STIRFutureStructure.FLY: partial(self._build_fly),
            STIRFutureStructure.BASIS: partial(self._build_basis),
        }

    # ----------------------------- key resolution -----------------------------

    def _keys(self) -> List[str]:
        return list(self.common_kwargs["pricer"].keys())

    def _resolve_key(self, *, desired: Optional[str], role: str) -> str:
        pricers: Dict[str, _STIRFutureGenericPricer] = self.common_kwargs["pricer"]

        if desired is not None and desired in pricers:
            return desired

        if len(pricers) == 1:
            return next(iter(pricers.keys()))

        raise KeyError(f"Could not resolve STIR pricer key for {role}. " f"desired={desired!r}, available_keys={list(pricers.keys())}")

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

    # ----------------------------- leg construction -----------------------------

    def _build_leg(
        self,
        *,
        key: str,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        rate: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        is_ser: Optional[bool] = False,
        **_,
    ) -> _STIRFutureGenericPricable:
        pr = self.common_kwargs["pricer"][key]

        # Prefer generic entry point if implemented; fallback to build_stirf.
        if hasattr(pr, "build_pricable"):
            return pr.build_pricable(
                effective_date=effective_date,
                maturity_date=maturity_date,
                price=price,
                rate=rate,
                contracts=contracts,
                notional=notional,
                is_ser=is_ser,
            )
        # rateslib backend implements build_stirf(...)
        return pr.build_stirf(
            effective_date=effective_date,
            maturity_date=maturity_date,
            price=price,
            rate=rate,
            contracts=contracts,
            notional=notional,
            is_ser=is_ser,
        )

    def _pv01_per_contract(self, *, key: str, is_ser: bool = False) -> float:
        """
        Used to map target bpv -> contracts when bpv is specified.
        We compute pv01 of a 1-contract instrument built by the leg’s pricer.
        """
        pr = self.common_kwargs["pricer"][key]
        one = self._build_leg(key=key, contracts=1, is_ser=is_ser)
        return float(pr.pv01(stirf=one))

    def _solve_contracts_from_risk_weights(
        self,
        *,
        keys: List[str],
        risk_weights: List[float],
        constrained_leg_index: int,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        is_ser: bool = False,
    ) -> List[int]:
        """
        Contracts choice that makes PV01 contributions proportional to risk_weights:
            contracts_i = alpha * rw_i / pv01_i(1 contract)

        Choose alpha from one constraint:
          - constrained_contracts on leg k:
                alpha = constrained_contracts * pv01_k / rw_k
          - constrained_bpv on leg k (PV01 dollars):
                alpha = constrained_bpv / rw_k
        """
        _require_exactly_one(constrained_contracts=constrained_contracts, constrained_bpv=constrained_bpv)

        rw = [float(x) for x in risk_weights]
        k = constrained_leg_index
        if not (0 <= k < len(keys)):
            raise IndexError("constrained_leg_index out of range")
        if rw[k] == 0.0:
            raise ValueError("constrained leg risk_weight cannot be 0")

        pv01s = [self._pv01_per_contract(key=kk, is_ser=is_ser) for kk in keys]
        if any(p == 0.0 for p in pv01s):
            raise ValueError(f"Encountered pv01_per_contract == 0 for keys={keys} pv01s={pv01s}")

        if constrained_contracts is not None:
            alpha = float(constrained_contracts) * pv01s[k] / rw[k]
        else:
            alpha = float(constrained_bpv) / rw[k]

        # round to nearest int; contracts must be integer for rateslib STIRFuture
        out = [int(round(alpha * rw_i / pv01_i)) for rw_i, pv01_i in zip(rw, pv01s)]
        return out

    # ----------------------------- builders -----------------------------

    def _build_outright(
        self,
        *,
        symbol: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        rate: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_ser: Optional[bool] = False,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[_STIRFutureGenericPricable], List[float]]:
        pricers: Dict[str, _STIRFutureGenericPricer] = self.common_kwargs["pricer"]

        # --- alias pack behavior: symbol not found but we have multiple pricers ---
        if symbol is not None and symbol not in pricers and len(pricers) > 1:
            keys = list(pricers.keys())

            # sizing: if user gives contracts, apply to each leg; else default 1 each
            if contracts is None and notional is None and bpv is None:
                contracts = 1

            legs = [
                self._build_leg(
                    key=k,
                    effective_date=effective_date,
                    maturity_date=maturity_date,
                    price=price,
                    rate=rate,
                    contracts=contracts,
                    notional=notional,
                    is_ser=is_ser,
                )
                for k in keys
            ]

            # weights: if provided, must match N; else all 1.0
            if risk_weights is None:
                risk_weights = [1.0] * len(keys)
            if len(risk_weights) != len(keys):
                raise ValueError(f"OUTRIGHT pack: risk_weights must have length {len(keys)}, got {len(risk_weights)}")

            return legs, [float(x) for x in risk_weights]

        # --- standard outright behavior (single leg) ---
        key = self._resolve_key(desired=symbol, role="outright.symbol")

        specified = [contracts is not None, notional is not None, bpv is not None]
        if sum(specified) > 1:
            raise ValueError("OUTRIGHT: specify at most one of contracts/notional/bpv")

        if bpv is not None:
            pv01_1 = self._pv01_per_contract(key=key, is_ser=bool(is_ser))
            print(pv01_1, "jehrehe") 
            contracts = int(round(float(bpv) / pv01_1))

        if contracts is None and notional is None and bpv is None:
            contracts = 1

        leg = self._build_leg(
            key=key,
            effective_date=effective_date,
            maturity_date=maturity_date,
            price=price,
            rate=rate,
            contracts=contracts,
            notional=notional,
            is_ser=is_ser,
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
        is_ser: Optional[bool] = False,
        # allow constraint-based sizing like FixedRateBond
        constrained_leg_index: int = 0,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        **_,
    ) -> Tuple[List[_STIRFutureGenericPricable], List[float]]:
        if risk_weights is None:
            risk_weights = [1.0, -1.0]

        # key resolution: prefer explicit symbols (as keys), else expect exactly 2 pricers in dict
        pr = self.common_kwargs["pricer"]
        if front_symbol in pr and back_symbol in pr:
            keys = [front_symbol, back_symbol]
        else:
            keys = self._resolve_keys_for_n_legs(desired=None, n=2)

        # optional contract solve from constraint
        contracts: Optional[List[int]] = None
        if constrained_contracts is not None or constrained_bpv is not None:
            contracts = self._solve_contracts_from_risk_weights(
                keys=keys,
                risk_weights=risk_weights,
                constrained_leg_index=constrained_leg_index,
                constrained_contracts=constrained_contracts,
                constrained_bpv=constrained_bpv,
                is_ser=bool(is_ser),
            )

        legs = [
            self._build_leg(key=keys[0], contracts=(contracts[0] if contracts else None), is_ser=is_ser),
            self._build_leg(key=keys[1], contracts=(contracts[1] if contracts else None), is_ser=is_ser),
        ]
        return legs, [float(x) for x in risk_weights]

    def _build_fly(
        self,
        *,
        symbols: Optional[List[str]] = None,  # preferred: [front, belly, back] (also used as keys)
        front_symbol: Optional[str] = None,
        belly_symbol: Optional[str] = None,
        back_symbol: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        is_ser: Optional[bool] = False,
        constrained_leg_index: int = 1,  # belly by default
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        **_,
    ) -> Tuple[List[_STIRFutureGenericPricable], List[float]]:
        if risk_weights is None:
            risk_weights = [1.0, -2.0, 1.0]

        # resolve keys
        pr = self.common_kwargs["pricer"]
        if symbols is not None:
            if len(symbols) != 3:
                raise ValueError("FLY: symbols must have length 3")
            keys = self._resolve_keys_for_n_legs(desired=symbols, n=3)
        elif front_symbol in pr and belly_symbol in pr and back_symbol in pr:
            keys = [front_symbol, belly_symbol, back_symbol]  # type: ignore[list-item]
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
                is_ser=bool(is_ser),
            )

        legs = [
            self._build_leg(key=keys[0], contracts=(contracts[0] if contracts else None), is_ser=is_ser),
            self._build_leg(key=keys[1], contracts=(contracts[1] if contracts else None), is_ser=is_ser),
            self._build_leg(key=keys[2], contracts=(contracts[2] if contracts else None), is_ser=is_ser),
        ]
        return legs, [float(x) for x in risk_weights]

    def _build_basis(
        self,
        *,
        symbol: Optional[str] = None,
        # basis keys explicitly if your MDP returns e.g. {"curveA": prA, "curveB": prB}
        basis_front_key: Optional[str] = None,
        basis_back_key: Optional[str] = None,
        risk_weights: Optional[List[float]] = None,
        is_ser: Optional[bool] = False,
        constrained_leg_index: int = 0,
        constrained_contracts: Optional[int] = None,
        constrained_bpv: Optional[float] = None,
        **_,
    ) -> Tuple[List[_STIRFutureGenericPricable], List[float]]:
        """
        BASIS: same symbol, two different pricers (e.g., two curves/sources).
        This assumes your MDP returns exactly two pricers for the basis request.
        """
        if risk_weights is None:
            risk_weights = [1.0, -1.0]

        pr = self.common_kwargs["pricer"]
        if basis_front_key in pr and basis_back_key in pr:
            keys = [basis_front_key, basis_back_key]  # type: ignore[list-item]
        else:
            keys = self._resolve_keys_for_n_legs(desired=None, n=2)

        contracts: Optional[List[int]] = None
        if constrained_contracts is not None or constrained_bpv is not None:
            contracts = self._solve_contracts_from_risk_weights(
                keys=keys,
                risk_weights=risk_weights,
                constrained_leg_index=constrained_leg_index,
                constrained_contracts=constrained_contracts,
                constrained_bpv=constrained_bpv,
                is_ser=bool(is_ser),
            )

        # build both legs with the *same* symbol dates/fields if needed; rate/price usually comes from pricer
        legs = [
            self._build_leg(key=keys[0], contracts=(contracts[0] if contracts else None), is_ser=is_ser),
            self._build_leg(key=keys[1], contracts=(contracts[1] if contracts else None), is_ser=is_ser),
        ]
        return legs, [float(x) for x in risk_weights]
