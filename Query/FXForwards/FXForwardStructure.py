from __future__ import annotations

from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.FXForwards._FXForwardGenericPricer import _FXForwardGenericPricer
from Query.FXForwards.backends.rateslib.RLFXForwardPricer import RLFXForwardPricable


class FXForwardStructure(Enum):
    OUTRIGHT = auto()


class FXForwardStructureFunctionMap(BaseStructureFunctionMap[FXForwardStructure, RLFXForwardPricable]):
    def __init__(self, pricer: Dict[str, _FXForwardGenericPricer]):
        super().__init__(FXForwardStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[FXForwardStructure, Callable[..., Tuple[List[RLFXForwardPricable], List[float]]]]:
        return {
            FXForwardStructure.OUTRIGHT: partial(self._build_outright),
        }

    def _resolve_key(self, desired: Optional[str]) -> str:
        pricers = self.common_kwargs["pricer"]
        if desired is not None and desired in pricers:
            return desired
        if len(pricers) == 1:
            return next(iter(pricers))
        raise KeyError(f"Could not resolve FX forward pricer key. desired={desired!r}, available={list(pricers.keys())}")

    def _build_outright(
        self,
        *,
        symbol: Optional[str] = None,
        pair: Optional[str] = None,
        tenor: Optional[str] = None,
        spot: Optional[float] = None,
        forward_rate: Optional[float] = None,
        points_raw: Optional[float] = None,
        points_decimal: Optional[float] = None,
        **_,
    ) -> Tuple[List[RLFXForwardPricable], List[float]]:
        key = self._resolve_key(symbol)
        pr: _FXForwardGenericPricer = self.common_kwargs["pricer"][key]
        leg = pr.build_pricable(
            pair=pair or pr.pair(),
            symbol=symbol or pr.symbol(),
            tenor=tenor or pr.tenor(),
            settlement_date=pr.settlement_date(),
            quote_timestamp=pr.quote_timestamp(),
            spot=spot,
            forward_rate=forward_rate,
            points_raw=points_raw,
            points_decimal=points_decimal,
            basis_bps=pr.basis_bps(),
        )
        return [leg], [1.0]
