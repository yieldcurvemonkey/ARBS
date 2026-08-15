"""SOFR (SR3) futures pack conventions and the Citi convexity screen.

A **pack** is four consecutive quarterly contracts -- Citi: *"We analyze 1y packs
(four consecutive contracts) because individual ED/FRA spreads are noisy and
hard to trade."* Citi's tables are rolling packs at every quarterly start, not
only the five colour packs; the colours (Whites/Reds/Greens/Blues/Golds) are
labels applied to four of those rolling windows.

Conventions that port from ED to SFR with **no change at all**:

* ``rate = 100 - price``, and a pack's rate is the mean of its four leg rates
  (the CME pack price is the arithmetic mean of the leg prices).
* **DV01 = $25.00 per bp per contract** -- 0.25 x $1mm x 1bp, identical for 3M
  Eurodollar and 3M SOFR. So a pack is $100/bp and *n* packs is ``n * 4 * 25``.
* Contract months are the quarterly cycle H/M/U/Z (Mar/Jun/Sep/Dec) and the
  contract's reference period starts on its IMM date, the 3rd Wednesday.

The matched-maturity swap, pinned verbatim by Citi's own trade recommendation
(*"buy 1000 of H0-Z0 packs ... and pay $1bn on a matched-maturity
(3/18/20-3/17/21) CME swap"*):

    start = IMM date of the FIRST contract in the pack
    end   = IMM date 12 months later ( = IMM of the contract after the 4th leg)
    both legs quarterly

For SR3 this tiles *exactly*: the four reference quarters concatenate to
``[start, end]``, which makes the SOFR adjustment cleaner than the ED one (3M
LIBOR deposits from each IMM date only tiled approximately).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "MONTH_CODES",
    "CODE_TO_MONTH",
    "DV01_PER_CONTRACT",
    "PACK_COLOURS",
    "imm_date",
    "third_wednesday",
    "quarterly_imm_sequence",
    "contract_code",
    "parse_contract_code",
    "pack_label",
    "year_fraction_act365",
    "pack_t1s",
    "matched_swap_dates",
]

#: Quarterly delivery-month codes, in cycle order.
MONTH_CODES: Dict[int, str] = {3: "H", 6: "M", 9: "U", 12: "Z"}
CODE_TO_MONTH: Dict[str, int] = {v: k for k, v in MONTH_CODES.items()}

#: $ per basis point per contract. Identical for ED and SR3.
DV01_PER_CONTRACT = 25.0

#: Colour ladder by 1-indexed position of the pack's first contract.
PACK_COLOURS: Dict[int, str] = {1: "Whites", 5: "Reds", 9: "Greens", 13: "Blues",
                                17: "Golds", 21: "Purples"}


def third_wednesday(year: int, month: int) -> datetime.date:
    """The 3rd Wednesday of *month* -- the IMM date."""
    d = datetime.date(year, month, 1)
    # weekday(): Mon=0 .. Wed=2
    offset = (2 - d.weekday()) % 7
    return d + datetime.timedelta(days=offset + 14)


def imm_date(year: int, month: int) -> datetime.date:
    """IMM date of a quarterly delivery month. Alias of :func:`third_wednesday`."""
    if month not in MONTH_CODES:
        raise ValueError(f"{month} is not a quarterly IMM month (3/6/9/12)")
    return third_wednesday(year, month)


def contract_code(year: int, month: int) -> str:
    """``(2024, 6) -> 'M4'`` -- the single-digit-year code Citi's tables use."""
    return f"{MONTH_CODES[month]}{year % 10}"


def parse_contract_code(code: str, reference: datetime.date) -> Tuple[int, int]:
    """``'M4'`` + a reference date -> ``(2024, 6)``.

    The single-digit year is ambiguous by decades, so it is resolved to the
    first quarterly IMM date on or after *reference* -- which is how the codes
    are read in a futures table.
    """
    code = str(code).strip().upper()
    if len(code) != 2 or code[0] not in CODE_TO_MONTH or not code[1].isdigit():
        raise ValueError(f"bad contract code {code!r}")
    month = CODE_TO_MONTH[code[0]]
    digit = int(code[1])
    base = reference.year - (reference.year % 10)
    for year in (base + digit, base + digit + 10, base + digit + 20):
        if imm_date(year, month) >= reference:
            return year, month
    raise ValueError(f"could not resolve {code!r} against {reference}")


def quarterly_imm_sequence(
    as_of: datetime.date,
    n: int,
    *,
    include_current: bool = True,
) -> List[Tuple[int, int]]:
    """The next *n* quarterly ``(year, month)`` contracts from *as_of*.

    ``include_current=True`` keeps a contract whose IMM date is still ahead of
    (or on) *as_of*, which is the live front contract.
    """
    out: List[Tuple[int, int]] = []
    year, month = as_of.year, 3
    while len(out) < n:
        for m in (3, 6, 9, 12):
            d = imm_date(year, m)
            if d > as_of or (include_current and d == as_of):
                out.append((year, m))
                if len(out) >= n:
                    break
        year += 1
    return out[:n]


def pack_label(first: Tuple[int, int], last: Tuple[int, int]) -> str:
    """``(2024,6),(2025,3) -> 'M4-H5'``."""
    return f"{contract_code(*first)}-{contract_code(*last)}"


def year_fraction_act365(start: datetime.date, end: datetime.date) -> float:
    """ACT/365 year fraction -- the convention Citi's implied vols reproduce."""
    return (end - start).days / 365.0


def pack_t1s(as_of: datetime.date, contracts: Sequence[Tuple[int, int]]) -> List[float]:
    """``T1_i`` for each contract in a pack: ACT/365 from *as_of* to its IMM date."""
    return [year_fraction_act365(as_of, imm_date(y, m)) for y, m in contracts]


def matched_swap_dates(
    contracts: Sequence[Tuple[int, int]],
) -> Tuple[datetime.date, datetime.date]:
    """``(start, end)`` of the matched-maturity forward 1y swap for a pack.

    Start is the first contract's IMM date; end is the IMM date one year later,
    i.e. the IMM date of the contract immediately after the 4th leg.
    """
    if len(contracts) != 4:
        raise ValueError(f"a pack is 4 contracts, got {len(contracts)}")
    y0, m0 = contracts[0]
    start = imm_date(y0, m0)
    end = imm_date(y0 + 1, m0)
    return start, end
