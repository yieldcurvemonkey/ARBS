from __future__ import annotations

from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.USTFutureBasis._USTFutureBasisGenericPricable import _USTFutureBasisGenericPricable
from Query.USTFutureBasis._USTFutureBasisGenericPricer import _USTFutureBasisGenericPricer


class USTFutureBasisStructure(Enum):
    BASIS = auto()


class USTFutureBasisStructureFunctionMap(BaseStructureFunctionMap[USTFutureBasisStructure, _USTFutureBasisGenericPricable]):
    def __init__(self, pricer: Dict[str, _USTFutureBasisGenericPricer]):
        super().__init__(USTFutureBasisStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[USTFutureBasisStructure, Callable[..., Tuple[List[_USTFutureBasisGenericPricable], List[float]]]]:
        return {USTFutureBasisStructure.BASIS: partial(self._build_basis)}

    def _resolve_key(self, symbol: Optional[str]) -> str:
        pricers = self.common_kwargs["pricer"]
        if symbol is not None and symbol in pricers:
            return symbol
        if len(pricers) == 1:
            return next(iter(pricers))
        raise KeyError(f"Could not resolve basis pricer key. symbol={symbol!r}, available={list(pricers)}")

    def _build_basis(
        self,
        *,
        symbol: Optional[str] = None,
        bond_cusip: Optional[str] = None,
        bond_notional: Optional[float] = None,
        contracts: Optional[int] = None,
        direction: int = 1,
        repo_rate: Optional[float] = None,
        **kwargs: Any,
    ) -> Tuple[List[_USTFutureBasisGenericPricable], List[float]]:
        key = self._resolve_key(symbol)
        pr = self.common_kwargs["pricer"][key]

        # Probe a unit leg to read the selected bond's conversion factor.
        probe = pr.build_pricable(
            bond_cusip=bond_cusip,
            contracts=1,
            bond_notional=(bond_notional if bond_notional is not None else 1_000_000.0),
            direction=direction,
            repo_rate=repo_rate,
        )
        cf = float(probe.conversion_factor()) or 1.0

        if bond_notional is None:
            # Size from contracts (default 1): cash face = contracts / CF * 100k.
            n_contracts = int(contracts) if contracts is not None else 1
            bond_notional = (n_contracts / cf) * 100_000.0
        else:
            # CF-weight the futures to the given cash face: n_f = round(face/100k * CF).
            n_contracts = int(contracts) if contracts is not None else max(1, int(round((float(bond_notional) / 100_000.0) * cf)))

        leg = pr.build_pricable(
            bond_cusip=bond_cusip,
            contracts=int(n_contracts),
            bond_notional=float(bond_notional),
            direction=int(direction),
            repo_rate=repo_rate,
        )
        return [leg], [1.0]
