"""Exchange symbol -> kind, legs and leg weights, dispatched by product root.

The leg structure lives only in the symbol string -- the ``definition`` schema is
a separate file we do not have -- so this package is the single place that decodes
it.  Each root family gets its own module because the grammars genuinely differ:
SR3 lists packs, bundles, condors and double flies, with two different leg
separators in the same file, and the Treasury roots list none of that.

Public surface is unchanged from the single-module version, so existing imports
(``from RVUtils.MBO.symbols import parse_symbol``) keep working.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Dict, Sequence

from RVUtils.MBO.products import root_of, spec_for
from RVUtils.MBO.symbols._sr3 import (
    KINDS_QUOTED_IN_BP,
    MONTH_CODES,
    QUARTERLY_CODES,
    USD_PER_BP_PER_CONTRACT,
    ParsedSymbol,
    bp_per_price_unit,
    contract_month,
    quarterly_strip,
)
from RVUtils.MBO.symbols._sr3 import parse_symbol as _parse_sr3
from RVUtils.MBO.symbols._ust import parse_symbol as _parse_ust

__all__ = [
    "KINDS_QUOTED_IN_BP",
    "MONTH_CODES",
    "QUARTERLY_CODES",
    "USD_PER_BP_PER_CONTRACT",
    "ParsedSymbol",
    "bp_per_price_unit",
    "contract_month",
    "parse_symbol",
    "parse_symbols",
    "quarterly_strip",
]

_GRAMMARS: Dict[str, Callable[[str, int], ParsedSymbol]] = {
    "sr3": _parse_sr3,
    "ust": _parse_ust,
}


def parse_symbol(symbol: str, ref_year: int) -> ParsedSymbol:
    """Decode one exchange symbol.  Unknown roots come back ``kind='OTHER'``.

    Never raises on an unrecognised symbol.  A build walks 553 sessions and a
    thousand-odd instruments; one odd string must not be able to stop it, and a
    row labelled ``OTHER`` is visible in the catalogue where an exception is not.
    """
    root = root_of(symbol)
    if root is None:
        return ParsedSymbol(symbol, "OTHER", (), (), (), symbol)
    parsed = _GRAMMARS[spec_for(root).grammar](symbol, ref_year)
    return dataclasses.replace(parsed, root=root)


def parse_symbols(symbols: Sequence[str], ref_year: int) -> Dict[str, ParsedSymbol]:
    return {s: parse_symbol(s, ref_year) for s in symbols}
