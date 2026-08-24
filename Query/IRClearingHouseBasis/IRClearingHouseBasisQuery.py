r"""Query for the LCH-vs-CME clearing-house basis, so it composes with the rest.

The basis already had a ``MarketDataProvider``
(:class:`MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP`) but no
``BaseQuery`` and no timeseries router, which meant every consumer reached past
the query layer and called ``basis_panel`` directly. That works, and it is why
the CCP-basis overlay in the convexity work reads differently from every other
series beside it. This closes the seam: a ``CHBASIS`` query routes through
``TimeseriesBuilder`` exactly like an ``IRS`` or ``IRSWAPTION`` one.

Sign convention, stated once and pinned by a test: ``basis_bps`` is
**clearing_house_a minus clearing_house_b**, i.e. **LCH minus CME** on the
defaults, in **bp**. The MDP's own measured reference is USD SOFR 10y on
2026-08-10 = **-2.00 bp** (LCH 0.04288489, CME 0.04308489).

Units: ``BASIS_BPS`` is bp; ``RATE_A``/``RATE_B`` are **decimal** as the vendor
serves them, not percent and not bp. Mixing those is the classic 1e4 error, so
the value enum names the units and :func:`value_units` returns them.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from Query.Base.BaseQuery import BaseQuery

__all__ = [
    "PRODUCT",
    "IRClearingHouseBasisQuery",
    "IRClearingHouseBasisValue",
    "value_column",
    "value_units",
]

#: The product key ``TimeseriesBuilder`` routes on.
PRODUCT = "CHBASIS"


class IRClearingHouseBasisValue(Enum):
    """What to read off the pricer's ``basis_data`` frame."""

    BASIS_BPS = "basis_bps"
    RATE_A = "rate_a"
    RATE_B = "rate_b"


#: value -> column in ``ClearingHouseBasisPricer.basis_data``
def value_column(value: IRClearingHouseBasisValue) -> str:
    return IRClearingHouseBasisValue(value).value


def value_units(value: IRClearingHouseBasisValue) -> str:
    """``"bp"`` for the basis, ``"decimal"`` for either leg rate."""
    return "bp" if IRClearingHouseBasisValue(value) is \
        IRClearingHouseBasisValue.BASIS_BPS else "decimal"


@dataclass(frozen=True)
class IRClearingHouseBasisQuery(BaseQuery):
    """One (currency, index, tenor, clearing-house pair) basis series.

    ``allow_network`` defaults to **False** and is deliberately not plumbed to
    True anywhere by default: every call used to hit the network, which made a
    backtest unrunnable. A cold window raises rather than refetching.
    """

    tenor: str = "10y"
    ccy: str = "USD"
    index: str = "SOFR"
    clearing_house_a: str = "LCH"
    clearing_house_b: str = "CME"
    value: IRClearingHouseBasisValue = IRClearingHouseBasisValue.BASIS_BPS
    allow_network: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "product", PRODUCT)
        object.__setattr__(self, "structure_id", "OUTRIGHT")
        object.__setattr__(self, "value", IRClearingHouseBasisValue(self.value))

    # ------------------------------------------------------------------
    def instrument_key(self) -> tuple:
        """Everything except the value and the date -- one MDP fetch per key."""
        return (self.ccy.upper(), self.index.upper(), self.tenor.lower(),
                self.clearing_house_a.upper(), self.clearing_house_b.upper(),
                bool(self.allow_network))

    def build_mdp_request(self, now: Any) -> Dict[str, Any]:
        """A single-DAY request, so the query is usable on its own.

        The router overrides this with one window-wide request per instrument,
        because the MDP returns a whole panel and asking it per date would
        re-read the same cache once per business day.
        """
        d = now.date() if isinstance(now, datetime.datetime) else now
        return self.window_request(d, d)

    def window_request(self, start: Any, end: Any) -> Dict[str, Any]:
        return {
            "tenor": self.tenor,
            "ccy": self.ccy,
            "index": self.index,
            "clearing_house_a": self.clearing_house_a,
            "clearing_house_b": self.clearing_house_b,
            "start": start,
            "end": end,
            "allow_network": bool(self.allow_network),
        }

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        if self.name:
            return str(self.name)
        return (f"{self.ccy.upper()}-{self.index.upper()} {self.tenor.upper()} "
                f"{self.clearing_house_a.upper()}-"
                f"{self.clearing_house_b.upper()} "
                f"{self.value.name}")

    def return_query(self) -> Any:
        """Expand a list-valued ``value`` into one query per metric, so
        ``[q]`` and ``q`` behave the same way the IRS query does."""
        if isinstance(self.value, (list, tuple)):
            return [IRClearingHouseBasisQuery(
                tenor=self.tenor, ccy=self.ccy, index=self.index,
                clearing_house_a=self.clearing_house_a,
                clearing_house_b=self.clearing_house_b, value=v,
                allow_network=self.allow_network, name=self.name,
                tags=self.tags, meta=dict(self.meta or {}))
                for v in self.value]
        return [self]

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        return f"`{self.col_name(cube_name=cube_name)}`"

    def default_mtm_value_id(self) -> Any:
        return self.value
