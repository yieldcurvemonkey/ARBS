from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from Query.Base._GenericPricable import _GenericPricable


def _instrument_key(instr: _GenericPricable) -> str:
    """
    Prefer a stable key if the instrument exposes one; fall back to repr.
    """
    for attr in ("id", "key", "signature", "name"):
        val = getattr(instr, attr, None)
        if callable(val):
            try:
                return str(val())
            except Exception:
                pass
        elif val is not None:
            return str(val)
    return repr(instr)


@dataclass
class Position:
    instrument: _GenericPricable
    opened: dt.datetime
    meta: dict = field(default_factory=dict)


@dataclass
class Portfolio:
    """
    IRS-centric: each trade is a fully-specified instrument with embedded notional/side.
    We track a trade ledger (list of Positions). No separate qty notion.
    """

    positions: List[Position] = field(default_factory=list)
    orders_log: List = field(default_factory=list)
    trades_log: List = field(default_factory=list)

    def add(self, instrument: _GenericPricable, opened: dt.datetime, meta: Optional[dict] = None) -> None:
        self.positions.append(Position(instrument=instrument, opened=opened, meta=meta or {}))

    def trade_count_between(self, start: dt.datetime, end: dt.datetime) -> int:
        return sum(1 for p in self.positions if start <= p.opened <= end)

    @property
    def instruments_by_key(self) -> Dict[str, _GenericPricable]:
        # Handy view if you want keyed access; latest trade wins per key.
        out: Dict[str, _GenericPricable] = {}
        for p in self.positions:
            out[_instrument_key(p.instrument)] = p.instrument
        return out

    def iter_instruments(self) -> Iterable[_GenericPricable]:
        for p in self.positions:
            yield p.instrument
