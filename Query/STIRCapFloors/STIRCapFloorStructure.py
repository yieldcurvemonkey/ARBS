from __future__ import annotations

from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Tuple

from MDP.STIRCapFloors.STIRCapFloorMDP import STIRCapFloorMarketContext
from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.STIRCapFloors.pricer import STIRCapFloorLegPricable


class STIRCapFloorStructure(Enum):
    CAP = auto()
    FLOOR = auto()


class STIRCapFloorStructureFunctionMap(BaseStructureFunctionMap[STIRCapFloorStructure, STIRCapFloorLegPricable]):
    def __init__(self, context: STIRCapFloorMarketContext):
        super().__init__(STIRCapFloorStructure, context=context)
        self._map = self._create_map()

    def _create_map(self) -> Dict[STIRCapFloorStructure, Callable[..., Tuple[List[STIRCapFloorLegPricable], List[float]]]]:
        return {
            STIRCapFloorStructure.CAP: partial(self._build, expected="CAP"),
            STIRCapFloorStructure.FLOOR: partial(self._build, expected="FLOOR"),
        }

    def _build(
        self,
        *,
        expected: str,
        **_: Any,
    ) -> Tuple[List[STIRCapFloorLegPricable], List[float]]:
        context = self.common_kwargs["context"]
        if str(context.structure).upper() != expected:
            raise ValueError(f"Cap/floor context is {context.structure}, expected {expected}.")
        package = [leg.build_pricable() for leg in context.legs]
        return package, [1.0] * len(package)
