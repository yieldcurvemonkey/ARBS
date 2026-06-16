from __future__ import annotations

import datetime
from abc import ABC
from typing import Any, Optional

from Query.Base._GenericPricer import _GenericPricer
from Query.USTFutureBasis._USTFutureBasisGenericPricable import _USTFutureBasisGenericPricable


class _USTFutureBasisGenericPricer(_GenericPricer[_USTFutureBasisGenericPricable], ABC):
    """Analytics surface for a Treasury-futures basis.

    Concrete backends (rateslib) delegate the basis arithmetic to the underlying
    UST-future pricer (which embeds the deliverable basket) and select one bond
    (CTD by default) as the cash leg. The backtest PnL itself is produced by the
    position handler, not by these analytics.
    """

    # ---- identity ----
    def id(self) -> str:
        raise NotImplementedError

    def reference_date(self) -> datetime.date:
        raise NotImplementedError

    def meta(self) -> Any:
        raise NotImplementedError

    # ---- basis analytics (scalar, for the selected cash bond) ----
    def gross_basis(self, b: Optional[_USTFutureBasisGenericPricable] = None) -> float:
        raise NotImplementedError

    def net_basis(self, b: Optional[_USTFutureBasisGenericPricable] = None, repo_rate: Optional[float] = None) -> float:
        raise NotImplementedError

    def bnoc(self, b: Optional[_USTFutureBasisGenericPricable] = None, repo_rate: Optional[float] = None) -> float:
        raise NotImplementedError

    def implied_repo(self, b: Optional[_USTFutureBasisGenericPricable] = None) -> float:
        raise NotImplementedError

    def conversion_factor(self) -> float:
        raise NotImplementedError

    def dv01_hedge_ratio(self, bond_notional: float = 100_000.0) -> float:
        raise NotImplementedError

    def future_dv01(self, contracts: int = 1) -> float:
        raise NotImplementedError

    def bond_dv01(self, notional: float = 100_000.0) -> float:
        raise NotImplementedError

    def ctd_cusip(self) -> str:
        raise NotImplementedError
