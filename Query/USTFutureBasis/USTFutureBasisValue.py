from __future__ import annotations

from enum import Enum, auto
from typing import Any, Callable, Dict, List, Tuple

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.USTFutureBasis._USTFutureBasisGenericPricable import _USTFutureBasisGenericPricable
from Query.USTFutureBasis._USTFutureBasisGenericPricer import _USTFutureBasisGenericPricer


class USTFutureBasisValue(Enum):
    GROSS_BASIS = auto()        # cash clean - F * cf, in price points
    NET_BASIS = auto()          # gross basis - carry (== BNOC)
    BNOC = auto()               # basis net of carry (alias of NET_BASIS)
    IMPLIED_REPO = auto()       # IRR, percent
    DV01_HEDGE_RATIO = auto()   # futures per bond unit: CF_CTD * BPV_bond / BPV_CTD
    FUTURE_DV01 = auto()
    BOND_DV01 = auto()
    CONVERSION_FACTOR = auto()
    NPV = auto()                # analytic proxy; handler is authoritative for PnL


class USTFutureBasisValueFunctionMap(BaseValueFunctionMap[USTFutureBasisValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _USTFutureBasisGenericPricer],
        package: List[_USTFutureBasisGenericPricable],
        risk_weights: List[float],
    ):
        super().__init__(USTFutureBasisValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[USTFutureBasisValue, Callable[..., float]]:
        return {
            USTFutureBasisValue.GROSS_BASIS: self._gross_basis,
            USTFutureBasisValue.NET_BASIS: self._bnoc,
            USTFutureBasisValue.BNOC: self._bnoc,
            USTFutureBasisValue.IMPLIED_REPO: self._implied_repo,
            USTFutureBasisValue.DV01_HEDGE_RATIO: self._hedge_ratio,
            USTFutureBasisValue.FUTURE_DV01: self._future_dv01,
            USTFutureBasisValue.BOND_DV01: self._bond_dv01,
            USTFutureBasisValue.CONVERSION_FACTOR: self._conversion_factor,
            USTFutureBasisValue.NPV: self._npv,
        }

    def _one(self, kwargs: Dict[str, Any]) -> Tuple[_USTFutureBasisGenericPricer, _USTFutureBasisGenericPricable]:
        pr = next(iter(kwargs["pricer"].values()))
        leg = kwargs["package"][0]
        return pr, leg

    def _repo_for(self, leg: Any, kwargs: Dict[str, Any]):
        rr = kwargs.get("repo_rate")
        if rr is None and hasattr(leg, "repo_rate"):
            rr = leg.repo_rate()
        return rr

    def _gross_basis(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.gross_basis(leg))

    def _bnoc(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.bnoc(leg, repo_rate=self._repo_for(leg, kwargs)))

    def _implied_repo(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.implied_repo(leg))

    def _hedge_ratio(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.dv01_hedge_ratio(bond_notional=leg.bond_notional()))

    def _future_dv01(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.future_dv01(contracts=leg.contracts()))

    def _bond_dv01(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.bond_dv01(notional=leg.bond_notional()))

    def _conversion_factor(self, **kwargs: Any) -> float:
        _, leg = self._one(kwargs)
        return float(leg.conversion_factor())

    def _npv(self, **kwargs: Any) -> float:
        pr, leg = self._one(kwargs)
        return float(pr.npv(leg))
