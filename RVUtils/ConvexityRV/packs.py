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


THE IMM DATE ITSELF -- ONE CONVENTION, AND WHY IT IS THIS ONE (2026-08-19)
==========================================================================
On the ~4 days a year that are quarterly IMM dates, and on no other day, this
repo used to hold two answers to "what are the front four contracts".

:func:`quarterly_imm_sequence` with ``include_current=True`` -- the default, and
what every pack consumer uses -- **keeps** the contract whose reference quarter
begins today. ``MDP``'s ``tos._imm_cutoff`` + ``_next_contracts``, which every
colour alias, ``SFRCM{k}``, cap/floor strip and listed-option ladder resolves
through, used a strict ``<`` and **dropped** it. Measured on 2023-06-21: packs
gave ``M23,U23,Z23,H24``; the MDP gave ``U23,Z23,H24,M24``. On 2023-06-20 and
2023-06-22 they agreed exactly. **Both sites now keep it.**

CME defines the White pack as the "nearest four **forward-starting** quarterly
delivery months", and that text does not adjudicate this case. An SR3 contract
references the quarter that BEGINS at its IMM date, so on that date zero of its
~91 days have been observed: it is simultaneously the last moment of purely
forward-starting and the first moment of the new quarter. Genuinely ambiguous.
It was settled on evidence instead, and the evidence is one-sided:

* **The vendor "corroboration" for dropping it was circular.** ``SFRCM1`` never
  reaches Barchart -- it is our own alias, resolved in-process by
  ``STIRFutureMDP._resolve_aliases_bulk`` through the very function under
  question, and what goes on the wire on 2023-06-21 is the dated symbol
  ``SQU23``. Both independent findings of the disagreement bottomed out in the
  same line of our own code. There was no external witness for the drop side.
* **The settlement grid says the starting contract is the live one.** SR3 trades
  on a 0.0025 grid and finally settles at ``100 - compounded SOFR``, which is
  essentially never on that grid. Over every quarterly IMM date 2018-2026 in the
  local store, the ENDING contract is off-grid **18/18** (it has settled) and
  the STARTING contract is on-grid **32/32** (it is tradable). No exceptions.
  2023-06-21: ``SR3H23 px=95.0571``, ``SR3M23 px=94.7700``.
* **Intraday on the IMM date, same fetch:** the ending contract has 0 rows (or
  1, the settlement print); the starting contract has 1,262 rows over 8-21
  distinct prices, and its whole quoted life begins that day -- ``SR3M23``: 64
  quoted dates, 2023-06-21 through 2023-09-20, none after.
* **The matched swap makes the steelman net out.** At the 17:00 mark, day 1 of
  91 is economically in flight, which is the honest argument for dropping it.
  But :func:`matched_swap_dates` pins the pack's swap to the first leg's IMM
  date, so the 1y swap starts the same day and takes the same first fixing --
  the CA is a difference of two instruments sharing that contamination. Under
  the drop convention the rank-1 *matched swap* silently becomes a 3m-forward
  1y on four days a year, which is a definitional inconsistency in the screen's
  own reference instrument.
* **T1 crosses zero exactly here.** :func:`pack_t1s` puts the front leg at
  exactly 0.0 on the IMM date and at -1/365 the day after, so keeping it rolls
  precisely when T1 goes negative. The drop rule rolled one day early, while a
  T1 = 0, still-listed, most-open-interest contract was admissible.

So dropping it deleted the front of the curve for one session a quarter. What it
cost, measured: 24 of the 32 IMM dates in the local store carry pack depth >= 13;
the mean absolute CA offset between the window our rank-k named and the one it
should have named was 1.88bp (the clean roll_3m-magnitude estimate is ~0.4-2bp;
larger rank-5/9 readings were contaminated by stale deferred settles that
``flag_negative_ca`` catches independently). The cap/floor valuation work lost
exactly 26 cells to the disagreement, every one of them on an IMM date.

**Nature of the old defect, stated precisely, because it bounds what can move.**
It was a RELABELING, not a wrong CA. Every window was still four consecutive
contracts against its own correctly-matched swap; what shifted was which window
carried the rank/colour name. Label-keyed series (z-scores, realised vol) are
constant-contract and were untouched; only rank-following series took the roll
step a day late.

**Where the convention lives now.** One primitive: ``tos._imm_cutoff`` returns
IMM + 1 day, and ``_next_contracts`` drops a month once ``as_of >= cutoff``, so
the contract survives its own IMM date and rolls the next day. Everything on the
MDP side inherits it -- colour packs, ``CM{n}``/``SFRCM{n}``, X-year bundles,
cap/floor strips, listed-option underlying ladders, the screeners, the flow
ladder. Nothing else in the repo compares a date against an IMM date to build a
quarterly universe. ``strat2_q20.instrument_count`` used to carry a ``-1`` shim
that translated between the two ladders; it was deleted in the same change,
because with both sides keeping the contract the shim would have made the
``SFRCM`` ladder roll twice.

:func:`imm_date` / :func:`third_wednesday` (pure calendar), :func:`pack_t1s` and
:func:`matched_swap_dates` are pass-throughs -- pure functions of the contract
list handed to them. They propagate whichever ladder built it and are not a
third convention; do not "fix" them.

``tests/test_sr3_imm_roll_convention.py`` is the executable half of all this,
including the cross-site invariant that the two ladders name the same twenty
contracts on every day around every IMM date 2018-2027. It is pure date
arithmetic and never skips.
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
    (or on) *as_of*, which is the live front contract. **It is the default and
    nothing in the repo passes False** except the test that pins the difference:
    ``include_current=False`` is the convention this repo examined and rejected,
    kept only so the rejected side stays expressible. See the module docstring
    for the evidence, and ``tos._imm_cutoff`` for the MDP-side implementation
    that now agrees with it day for day.
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
