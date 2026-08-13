"""A minimal ARBS product for a forward-starting cross-currency basis position.

Why this exists. ARBS can *quote* the instrument — ``CitiVeloKind.XCCY_BASIS`` is wired and Citi
serves a full forward × tenor grid — but a quote is not a position: ``QueryDrivenBacktest`` needs
something it can resolve, mark and unwind. This module supplies the smallest product that does
that, registered on import, so the book runs through the real engine rather than a private loop.

The position is deliberately simple, and matches how the instrument actually behaves: a
cross-currency basis swap is struck at zero MtM and its P&L is the **change in the basis** times
the DV01 of the spread leg (see the market description in the references). So

    NPV = (basis_now − basis_at_entry) × dv01 × direction

with the entry basis stamped onto the leg when the position is resolved. Nothing here models the
notional exchange or the FX leg — that is the right scope for a basis RV book, and the wrong scope
for anything that needs true cash accounting.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from Query.Base.BaseQuery import BaseQuery
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Base.product_adapter import ProductAdapter, register_product

__all__ = [
    "XccyBasisValue",
    "XccyBasisStructure",
    "XccyBasisQuery",
    "XccyBasisLeg",
    "XccyPanelMDP",
    "PRODUCT",
]

PRODUCT = "XCCYB"


class XccyBasisStructure(Enum):
    OUTRIGHT = auto()


class XccyBasisValue(Enum):
    NPV = auto()          # P&L vs entry, in currency
    BASIS_BP = auto()     # the level, in bp
    DV01 = auto()         # currency per bp


@dataclass
class XccyBasisLeg:
    """One resolved position. ``entry_basis_bp`` is stamped at resolve time and never re-stamped.

    ``carry_bp_per_year`` is the carry-and-roll the position earns while held. It matters far more
    than it looks: on the archive's own 2007-2015 panel the *price* return of the basis nets to
    approximately nothing over eight years, and essentially all of the book's P&L is carry. An
    engine that marks only ``basis_now - basis_entry`` therefore reports a flat book and looks
    correct while measuring the wrong thing.

    Accrual is at the entry rate, held constant over the life of the position. That is what a
    carry signal actually claims -- the carry observed when the trade is put on -- and it keeps the
    leg self-contained; a daily-reset accrual would need the whole carry panel at mark time.
    """

    instrument: str
    dv01: float
    direction: float
    entry_basis_bp: float
    carry_bp_per_year: float = 0.0
    entry_ts: Optional[pd.Timestamp] = None

    def __repr__(self) -> str:
        return (
            f"<XccyBasisLeg {self.instrument} dir={self.direction:+.4g} "
            f"dv01={self.dv01:,.0f} entry={self.entry_basis_bp:.3f}bp "
            f"carry={self.carry_bp_per_year:+.2f}bp/y>"
        )


@dataclass(frozen=True)
class XccyBasisQuery(BaseQuery):
    instrument: Optional[str] = None
    structure: XccyBasisStructure = XccyBasisStructure.OUTRIGHT
    value: Union[XccyBasisValue, List[XccyBasisValue]] = XccyBasisValue.NPV
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    product: str = field(init=False, default=PRODUCT)
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", PRODUCT)
        object.__setattr__(self, "structure_id", self.structure)
        mr = dict(self.market_request or {})
        if self.instrument and "instrument" not in mr:
            mr["instrument"] = self.instrument
        object.__setattr__(self, "market_request", mr)
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["XccyBasisQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        v = self.value.name if isinstance(self.value, XccyBasisValue) else "MULTI"
        return f"{self.instrument} {v}"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        return f"`{self.col_name(cube_name=cube_name)}`"

    def default_mtm_value_id(self) -> Any:
        return XccyBasisValue.NPV


# ------------------------------------------------------------------ pricer / MDP
class _XccyPricer:
    """The basis strip as at one timestamp, plus the resolve/lookup the engine needs."""

    def __init__(self, basis_row: pd.Series, timestamp):
        self._row = basis_row
        self.timestamp = timestamp

    def basis_bp(self, instrument: str) -> float:
        v = self._row.get(instrument, np.nan)
        return float(v) if pd.notna(v) else float("nan")

    def resolve_pricable(self, pricable: Any, risk_weight: float = 1.0) -> Any:
        """Positions are already resolved; the engine re-resolves each mark, so pass through.

        Re-stamping ``entry_basis_bp`` here would silently make every mark a fresh trade and the
        book would show no P&L at all.
        """
        return pricable

    def __repr__(self) -> str:
        return f"<_XccyPricer {self.timestamp} n={len(self._row)}>"


class XccyPanelMDP:
    """A MarketDataProvider over a dates × instruments basis panel.

    Source-agnostic on purpose: hand it the banked archive panel or the Citi one and the engine
    cannot tell the difference.
    """

    def __init__(self, basis_bp: pd.DataFrame, name: str = "xccy_panel"):
        self.basis = basis_bp.sort_index()
        self.basis.index = pd.DatetimeIndex(self.basis.index)
        self.name = name

    def _row_for(self, ts) -> pd.Series:
        ts = pd.Timestamp(ts)
        idx = self.basis.index[self.basis.index <= ts]
        if len(idx) == 0:
            return pd.Series(dtype=float)
        return self.basis.loc[idx.max()]

    def get_pricer(self, request: Dict[str, Any]) -> _XccyPricer:
        ts = request.get("timestamp")
        return _XccyPricer(self._row_for(ts), ts)

    def __repr__(self) -> str:
        return f"<XccyPanelMDP {self.name} {self.basis.shape[0]}d x {self.basis.shape[1]}>"


# ---------------------------------------------------------------------- adapter
class _XccyStructureMap:
    def __init__(self, pricer: Any):
        self._pricer = pricer

    def apply(self, structure: Any, **kwargs: Any):
        instrument = kwargs.get("instrument")
        dv01 = float(kwargs.get("dv01", 1.0))
        direction = float(kwargs.get("direction", 1.0))
        entry = kwargs.get("entry_basis_bp")
        if entry is None:
            entry = self._pricer.basis_bp(instrument)
        leg = XccyBasisLeg(
            instrument=instrument,
            dv01=dv01,
            direction=direction,
            entry_basis_bp=float(entry),
            carry_bp_per_year=float(kwargs.get("carry_bp_per_year", 0.0) or 0.0),
            entry_ts=pd.Timestamp(self._pricer.timestamp) if self._pricer.timestamp is not None else None,
        )
        return [leg], [1.0]


class XccyBasisValueFunctionMap(BaseValueFunctionMap[XccyBasisValue, float]):
    def __init__(self, pricer: Any, package: Sequence[Any], **common_kwargs: Any):
        self._pricer = pricer
        self._package = list(package)
        super().__init__(XccyBasisValue, pricer=pricer, package=list(package), **common_kwargs)

    def _create_map(self) -> Dict[XccyBasisValue, Callable[..., float]]:
        return {
            XccyBasisValue.NPV: self._npv,
            XccyBasisValue.BASIS_BP: self._basis,
            XccyBasisValue.DV01: self._dv01,
        }

    def _legs(self, **kw) -> List[XccyBasisLeg]:
        pkg = kw.get("package") or self._package
        return [p for p in pkg if isinstance(p, XccyBasisLeg)]

    def _npv(self, **kw) -> float:
        """Price return plus accrued carry, both in currency."""
        pricer = kw.get("pricer") or self._pricer
        total = 0.0
        for leg in self._legs(**kw):
            now = pricer.basis_bp(leg.instrument)
            if np.isfinite(now):
                total += (now - leg.entry_basis_bp) * leg.dv01 * leg.direction
            if leg.carry_bp_per_year and leg.entry_ts is not None and pricer.timestamp is not None:
                days = (pd.Timestamp(pricer.timestamp) - leg.entry_ts).days
                if days > 0:
                    total += leg.carry_bp_per_year * (days / 365.0) * leg.dv01 * leg.direction
        return float(total)

    def _basis(self, **kw) -> float:
        pricer = kw.get("pricer") or self._pricer
        legs = self._legs(**kw)
        if not legs:
            return float("nan")
        return float(pricer.basis_bp(legs[0].instrument))

    def _dv01(self, **kw) -> float:
        return float(sum(leg.dv01 * leg.direction for leg in self._legs(**kw)))


class XccyBasisProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return _XccyStructureMap(pricer=pricer_or_curve)

    def build_value_map(
        self, *, pricer_or_curve: Any, package: List[Any], risk_weights: List[float]
    ) -> XccyBasisValueFunctionMap:
        return XccyBasisValueFunctionMap(pricer=pricer_or_curve, package=package)

    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        return q


register_product(PRODUCT, XccyBasisProductAdapter)
