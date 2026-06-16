from __future__ import annotations

import datetime
from typing import Any, List, Optional

from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer
from Query.USTFutureBasis._USTFutureBasisGenericPricer import _USTFutureBasisGenericPricer
from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricable import RLUSTFutureBasisPricable


class RLUSTFutureBasisPricer(_USTFutureBasisGenericPricer):
    """Delegating basis pricer.

    Wraps an :class:`RLUSTFuturePricer` (which already embeds the deliverable basket
    and computes gross/net basis, BNOC, implied repo and conversion factors) and
    selects one basket bond as the cash leg — the CTD by default, or an explicit
    cusip. All basis arithmetic is delegated to the future pricer and the per-bond
    vector is collapsed to the selected bond's scalar; nothing is re-derived here.
    """

    def __init__(
        self,
        future_pricer: RLUSTFuturePricer,
        *,
        bond_cusip: Optional[str] = None,
        repo_rate: Optional[float] = None,
        meta_data: Optional[Any] = None,
    ):
        self._future = future_pricer
        self._symbol = future_pricer.id()
        self._reference_date = future_pricer.reference_date()
        self._repo_rate = repo_rate
        self._meta_data = meta_data or {}

        self._basket: List[RLFixedRateBondPricer] = list(getattr(future_pricer, "_basket_pricers", []) or [])
        if not self._basket:
            raise ValueError(f"USTFutureBasis requires a deliverable basket; none on {self._symbol}")
        self._cfs: List[float] = [float(x) for x in future_pricer.conversion_factors()]

        # The raw CTD from rateslib (may be a WI bond not yet issued).
        raw_ctd_idx = int(future_pricer.ctd_index(ordered=False))

        # For the cash leg we need a bond that FedInvest can price, i.e. one whose
        # issue_date <= reference_date. WI bonds (auctioned but not settled) are in
        # the deliverable basket but have no FedInvest price yet.
        issued_mask = self._issued_mask(self._reference_date)
        if issued_mask[raw_ctd_idx]:
            self._ctd_idx = raw_ctd_idx
        else:
            # Fall back to the best (highest IRR) already-issued bond.
            ordered = future_pricer.ctd_index(ordered=True)
            if not isinstance(ordered, list):
                ordered = [ordered]
            self._ctd_idx = next((i for i in ordered if issued_mask[i]), raw_ctd_idx)

        self._ctd_bond = self._basket[self._ctd_idx]
        self._cf_ctd = float(self._cfs[self._ctd_idx])

        self._idx = self._ctd_idx if bond_cusip is None else self._index_of_cusip(bond_cusip)
        self._bond = self._basket[self._idx]
        self._cf = float(self._cfs[self._idx])

    # ---- helpers ----
    @staticmethod
    def _cusip_of(pr: RLFixedRateBondPricer) -> str:
        meta = pr.meta() or {}
        return str(meta.get("cusip") or pr.id())

    @staticmethod
    def _issue_date_of(pr: RLFixedRateBondPricer) -> Optional[datetime.date]:
        """Best-effort issue date from the bond pricer's meta or attributes."""
        meta = pr.meta() or {}
        for key in ("issue_date",):
            raw = meta.get(key)
            if raw is not None:
                if isinstance(raw, datetime.date):
                    return raw
                try:
                    return datetime.date.fromisoformat(str(raw)[:10])
                except Exception:
                    pass
        if hasattr(pr, "issue_date") and callable(pr.issue_date):
            try:
                d = pr.issue_date()
                if isinstance(d, datetime.date):
                    return d
            except Exception:
                pass
        return None

    def _issued_mask(self, ref_date: datetime.date) -> List[bool]:
        """True for basket bonds whose issue_date <= ref_date (already settled)."""
        mask = []
        for pr in self._basket:
            isd = self._issue_date_of(pr)
            mask.append(isd is None or isd <= ref_date)
        return mask

    def _index_of_cusip(self, cusip: str) -> int:
        cusips = [self._cusip_of(p) for p in self._basket]
        try:
            return cusips.index(str(cusip))
        except ValueError as exc:
            raise KeyError(f"{cusip} not in deliverable basket of {self._symbol}: {cusips}") from exc

    def rl_bond_by_cusip(self, cusip: Optional[str] = None) -> RLFixedRateBondPricer:
        """The deliverable basket's bond pricer for a cusip (selected/CTD if None).

        Used by the position handler to source the cash leg's daily clean price for a
        bond it holds (which stays in the contract's fixed basket for the contract life).
        """
        idx = self._idx if cusip is None else self._index_of_cusip(cusip)
        return self._basket[idx]

    def _idx_for(self, b: Optional[RLUSTFutureBasisPricable]) -> int:
        """Basket index for the bond a leg refers to (its cusip), else the default."""
        if b is not None:
            try:
                cusip = b.bond_cusip()
            except Exception:
                cusip = None
            if cusip:
                cusips = [self._cusip_of(p) for p in self._basket]
                if str(cusip) in cusips:
                    return cusips.index(str(cusip))
        return self._idx

    def _resolve_repo(self, repo_rate: Optional[float]) -> Optional[float]:
        return repo_rate if repo_rate is not None else self._repo_rate

    # ---- identity ----
    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> datetime.date:
        return self._reference_date

    def meta(self) -> Any:
        return self._meta_data

    # ---- basis analytics ----
    def gross_basis(self, b: Optional[RLUSTFutureBasisPricable] = None) -> float:
        return float(self._future.gross_basis()[self._idx_for(b)])

    def bnoc(self, b: Optional[RLUSTFutureBasisPricable] = None, repo_rate: Optional[float] = None) -> float:
        return float(self._future.bnoc(repo_rate=self._resolve_repo(repo_rate))[self._idx_for(b)])

    def net_basis(self, b: Optional[RLUSTFutureBasisPricable] = None, repo_rate: Optional[float] = None) -> float:
        return self.bnoc(b, repo_rate=repo_rate)

    def implied_repo(self, b: Optional[RLUSTFutureBasisPricable] = None) -> float:
        return float(self._future.implied_repo()[self._idx_for(b)])

    def conversion_factor(self) -> float:
        return self._cf

    def ctd_cusip(self) -> str:
        return self._cusip_of(self._ctd_bond)

    def bond_cusip(self) -> str:
        return self._cusip_of(self._bond)

    def bond_clean_price(self) -> float:
        return float(self._bond.clean_price())

    def future_price(self) -> float:
        return float(self._future.price(self._future.build_ustf()))

    # ---- risk / hedge ratio ----
    def bond_dv01(self, notional: float = 100_000.0) -> float:
        return float(self._bond.bpv(notional=float(notional)))

    def ctd_dv01(self, notional: float = 100_000.0) -> float:
        return float(self._ctd_bond.bpv(notional=float(notional)))

    def future_dv01(self, contracts: int = 1) -> float:
        return float(self._future.pv01(self._future.build_ustf(contracts=int(contracts))))

    def dv01_hedge_ratio(self, bond_notional: float = 100_000.0) -> float:
        # CME hedge ratio: HR = CF_CTD * (BPV_bond / BPV_CTD). Units cancel in the
        # ratio, so this is robust; for the CTD itself it collapses to CF_CTD.
        n = float(bond_notional)
        return self._cf_ctd * (self.bond_dv01(notional=n) / self.ctd_dv01(notional=n))

    # ---- _GenericPricer contract ----
    def npv(self, instrument: Any, /, **kwargs: Any) -> float:
        notional = float(instrument.bond_notional()) if hasattr(instrument, "bond_notional") else 1_000_000.0
        direction = int(instrument.direction()) if hasattr(instrument, "direction") else 1
        # analytic proxy only; the position handler is authoritative for backtest PnL
        return self.bnoc() * (notional / 100.0) * direction

    def build_pricable(self, /, **kwargs: Any) -> RLUSTFutureBasisPricable:
        bond_cusip = kwargs.get("bond_cusip")
        idx = self._index_of_cusip(bond_cusip) if bond_cusip else self._idx
        bond = self._basket[idx]
        return RLUSTFutureBasisPricable(
            _future_symbol=self._symbol,
            _bond_cusip=self._cusip_of(bond),
            _future_price=self.future_price(),
            _bond_clean_price=float(bond.clean_price()),
            _conversion_factor=float(self._cfs[idx]),
            _contracts=int(kwargs.get("contracts", 1)),
            _bond_notional=float(kwargs.get("bond_notional", 1_000_000.0)),
            _repo_rate=kwargs.get("repo_rate", self._repo_rate),
            _direction=int(kwargs.get("direction", 1)),
        )

    def resolve_pricable(self, priceable: Any, risk_weight: Optional[float] = None) -> Any:
        return priceable
