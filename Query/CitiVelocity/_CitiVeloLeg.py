r"""The priceable a Citi Velocity query resolves to: one tag plus what it means.

A Velocity query is unusual among ARBS products in that most of what a notebook
asks for **is already a tag**: a 10y par rate, a swap spread, a vol point, a bond
yield. So the priceable carries the tag *and* enough structure for the value layer
to reprice the same thing from a locally-built curve or cube when asked - which is
what makes the fast path and the repricing path comparable rather than merely
coexistent.

Units are declared per leg kind and are load-bearing. Citi serves par swap rates
in PERCENT, swap spreads and cross-currency bases in BASIS POINTS, and normal
swaption vols in basis points of annualised vol. A structure built from
percent-quoted legs is scaled to basis points when it has more than one leg,
matching ``Query/IRSwaps`` (outright in percent, curve and fly in bp); a structure
built from legs already quoted in bp is not rescaled. Getting this wrong is a
100x error that still "prices" without complaint, which is exactly the failure the
repo has recorded before.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, unique
from typing import Any, Dict, Optional

from Query.Base._GenericPricable import _GenericPricable

__all__ = ["CitiVeloKind", "CitiVeloUnit", "CitiVeloLeg"]


@unique
class CitiVeloUnit(Enum):
    """The unit the add-in serves a family in."""

    PERCENT = "percent"
    BASIS_POINTS = "bp"
    VOL_BP = "vol_bp"
    PRICE = "price"
    RATIO = "ratio"
    YEARS = "years"

    @property
    def scale_to_bp(self) -> float:
        """Multiplier that takes this unit to basis points for a spread structure."""
        return 100.0 if self is CitiVeloUnit.PERCENT else 1.0


@unique
class CitiVeloKind(Enum):
    """What a leg's tag refers to, and therefore how it can be repriced."""

    OIS_PAR = "ois_par"
    OIS_FWD = "ois_fwd"
    SWAP_SPREAD = "swap_spread"
    SWAP_LIBOR_PAR = "swap_libor_par"
    OIS_MEETING = "ois_meeting"
    INVOICE_SPREAD = "invoice_spread"
    BASIS_SWAP = "basis_swap"
    TSY = "tsy"
    VOL_ATM = "vol_atm"
    VOL_OTM = "vol_otm"
    BOND = "bond"
    XCCY_BASIS = "xccy_basis"
    INFLATION_SWAP = "inflation_swap"
    INFLATION_INDEX = "inflation_index"
    FUTURES = "futures"
    SPREAD_OPTION = "spread_option"
    MIDCURVE = "midcurve"
    RAW = "raw"

    @property
    def unit(self) -> CitiVeloUnit:
        return _KIND_UNITS[self]

    @property
    def repriceable(self) -> bool:
        """True when a locally-built model can reproduce this leg from quotes.

        False means the fast path is the ONLY path for this leg - Citi publishes
        the number and we do not rebuild it. That is not a gap to be papered over
        with an approximation; it is recorded so the timeseries builder can route
        honestly.
        """
        return self in _REPRICEABLE


_KIND_UNITS: Dict[CitiVeloKind, CitiVeloUnit] = {
    CitiVeloKind.OIS_PAR: CitiVeloUnit.PERCENT,
    CitiVeloKind.OIS_FWD: CitiVeloUnit.PERCENT,
    CitiVeloKind.SWAP_SPREAD: CitiVeloUnit.BASIS_POINTS,
    CitiVeloKind.SWAP_LIBOR_PAR: CitiVeloUnit.PERCENT,
    CitiVeloKind.OIS_MEETING: CitiVeloUnit.PERCENT,
    CitiVeloKind.INVOICE_SPREAD: CitiVeloUnit.BASIS_POINTS,
    CitiVeloKind.BASIS_SWAP: CitiVeloUnit.BASIS_POINTS,
    CitiVeloKind.TSY: CitiVeloUnit.PERCENT,
    CitiVeloKind.VOL_ATM: CitiVeloUnit.VOL_BP,
    CitiVeloKind.VOL_OTM: CitiVeloUnit.VOL_BP,
    CitiVeloKind.BOND: CitiVeloUnit.PERCENT,
    CitiVeloKind.XCCY_BASIS: CitiVeloUnit.BASIS_POINTS,
    CitiVeloKind.INFLATION_SWAP: CitiVeloUnit.PERCENT,
    CitiVeloKind.INFLATION_INDEX: CitiVeloUnit.RATIO,
    CitiVeloKind.FUTURES: CitiVeloUnit.PRICE,
    CitiVeloKind.SPREAD_OPTION: CitiVeloUnit.VOL_BP,
    CitiVeloKind.MIDCURVE: CitiVeloUnit.VOL_BP,
    CitiVeloKind.RAW: CitiVeloUnit.RATIO,
}

#: Kinds this package can rebuild locally from Citi quotes, in at least one of
#: the two backends. Everything else is quote-only.
_REPRICEABLE = frozenset(
    {
        CitiVeloKind.OIS_PAR,
        CitiVeloKind.OIS_FWD,
        CitiVeloKind.SWAP_LIBOR_PAR,
        CitiVeloKind.VOL_ATM,
        CitiVeloKind.VOL_OTM,
        CitiVeloKind.BOND,
        CitiVeloKind.XCCY_BASIS,
        CitiVeloKind.INFLATION_SWAP,
    }
)


@dataclass(frozen=True)
class CitiVeloLeg(_GenericPricable):
    """One resolved tag, plus the structure needed to reprice it locally.

    Attributes
    ----------
    tag
        The Velocity tag. Always populated - a leg with no tag cannot exist,
        because the tag is what makes a Velocity leg addressable at all.
    kind
        What the tag refers to; determines units and whether it is repriceable.
    citi_index
        The Citi OIS index token (``USD_SOFR``, ``EUR_EUROSTR``, ...) for rate
        legs. This is the identifier the curve builders take.
    """

    tag: str
    kind: CitiVeloKind = CitiVeloKind.RAW
    citi_index: Optional[str] = None
    currency: Optional[str] = None
    counter_currency: Optional[str] = None
    tenor: Optional[str] = None
    forward: Optional[str] = None
    expiry: Optional[str] = None
    offset_bp: Optional[float] = None
    isin: Optional[str] = None
    measure: Optional[str] = None
    notional: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def unit(self) -> CitiVeloUnit:
        return self.kind.unit

    @property
    def repriceable(self) -> bool:
        return self.kind.repriceable

    def with_notional(self, notional: float) -> "CitiVeloLeg":
        return replace(self, notional=float(notional))

    def label(self) -> str:
        """A short human label used in column names."""
        if self.kind in (CitiVeloKind.VOL_ATM, CitiVeloKind.VOL_OTM):
            offset = "" if not self.offset_bp else f"{self.offset_bp:+.0f}"
            return f"{self.currency or ''} {self.expiry}x{self.tenor}{offset}".strip()
        if self.kind is CitiVeloKind.BOND:
            return f"{self.isin} {self.measure or ''}".strip()
        if self.kind is CitiVeloKind.XCCY_BASIS:
            return f"{self.currency}{self.counter_currency} {self.tenor}".strip()
        if self.kind is CitiVeloKind.OIS_FWD:
            return f"{self.citi_index or ''} {self.forward}x{self.tenor}".strip()
        if self.tenor:
            return f"{self.citi_index or self.currency or ''} {self.tenor}".strip()
        return self.tag

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"CitiVeloLeg({self.tag})"
