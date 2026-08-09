"""Treasury futures symbology: outright, calendar, listed butterfly, micro spread.

The four forms below are every form present in the ZT/ZF/ZN/TN/ZB/UB archives,
taken by resolving each product's parent symbol rather than reconstructed from a
specification.  There are no packs, bundles, condors or double flies on these
roots -- that vocabulary is SR3's, and it lives in :mod:`._sr3`.

Two differences from SR3 that matter downstream:

* **Treasury spreads do not quote in basis points.**  An SR3 calendar prints 6.500
  meaning 6.5 bp; a Treasury calendar prints a price *difference* in points.  A bp
  here needs a CTD DV01, which is why :class:`~RVUtils.MBO.products.ProductSpec`
  leaves ``usd_per_bp_per_lot`` as ``None`` for these roots.
* **Inter-commodity spreads have known legs.**  ``TNU6-MTNU6`` and ``UBZ6-MWNZ6``
  are the full-size contract against its micro.  SR3's inter-commodity spreads
  reference a product we hold no data for and are deliberately left unmodelled;
  these are not, so their legs are populated.
"""
from __future__ import annotations

import re

from RVUtils.MBO.symbols._sr3 import ParsedSymbol, contract_month

__all__ = ["parse_symbol"]

_MY = r"([FGHJKMNQUVXZ])(\d)"
#: ``([A-Z0-9]+)`` is greedy and backtracks to leave the month/year pair, so
#: ``ZNU6`` splits as root ``ZN`` and ``U6`` rather than swallowing the whole
#: string.  ``MTNU6`` splits as ``MTN`` + ``U6`` for the same reason.
_OUTRIGHT_RE = re.compile(rf"^([A-Z0-9]+){_MY}$")
_PAIR_RE = re.compile(rf"^([A-Z0-9]+){_MY}-([A-Z0-9]+){_MY}$")
_BF_RE = re.compile(rf"^([A-Z0-9]+):BF\s+{_MY}-{_MY}-{_MY}$")


def parse_symbol(symbol: str, ref_year: int) -> ParsedSymbol:
    """Decode one Treasury futures symbol.  Unrecognised forms come back ``OTHER``."""
    s = symbol.strip()

    m = _BF_RE.match(s)
    if m:
        r = m.group(1)
        months = tuple(
            contract_month(m.group(i), m.group(i + 1), ref_year) for i in (2, 4, 6)
        )
        legs = tuple(f"{r}{m.group(i)}{m.group(i + 1)}" for i in (2, 4, 6))
        step = (months[1].year - months[0].year) * 12 + (
            months[1].month - months[0].month
        )
        return ParsedSymbol(s, "BUTTERFLY", legs, (1, -2, 1), months, f"{step}m fly")

    m = _PAIR_RE.match(s)
    if m:
        r1, r2 = m.group(1), m.group(4)
        a = contract_month(m.group(2), m.group(3), ref_year)
        b = contract_month(m.group(5), m.group(6), ref_year)
        legs = (f"{r1}{m.group(2)}{m.group(3)}", f"{r2}{m.group(5)}{m.group(6)}")
        if r1 == r2:
            span = (b.year - a.year) * 12 + (b.month - a.month)
            return ParsedSymbol(
                s, "CALENDAR", legs, (1, -1), (a, b), f"{span}m calendar"
            )
        return ParsedSymbol(
            s, "INTERCOMMODITY", legs, (1, -1), (a, b), f"{r1} vs {r2}"
        )

    m = _OUTRIGHT_RE.match(s)
    if m:
        month = contract_month(m.group(2), m.group(3), ref_year)
        return ParsedSymbol(s, "OUTRIGHT", (s,), (1,), (month,), s)

    return ParsedSymbol(s, "OTHER", (), (), (), s)
