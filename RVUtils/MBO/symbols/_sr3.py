"""CME SR3 symbology: raw exchange symbols -> kind, legs and leg weights.

A GLBX MBO file resolved through the ``parent`` stype carries *every* listed
instrument on the SR3 complex, not just the outrights.  The leg structure lives
only in the symbol string -- the ``definition`` schema is a separate file we do
not have -- so this module is the single place that decodes it.

The forms actually present in ``glbx-mdp3-20260715`` (1,188 symbols)::

    SR3Z7                outright                             46
    SR3Z6-SR3H7          calendar spread     +1 -1           517
    SR3U6-TBF3U6         inter-commodity     (unmodelled)      7
    SR3:BF Z6-H7-M7      butterfly           +1 -2 +1        139
    SR3:CF M6U6Z6H7      condor              +1 -1 -1 +1      51
    SR3:DF Z7M8Z8M9      double butterfly    +1 -3 +3 -1      87
    SR3:AB 01Y U6        bundle              +1 x 4N         180
    SR3:SB PK Z7-Z8      bundle spread       +bundle -bundle 101
    SR3:BB Z6-Z7-Z8      bundle butterfly    +1 -2 +1 bundles  60

Note the two different separators: ``BF`` and ``BB`` dash-separate their legs,
``CF`` and ``DF`` concatenate them.  Both appear in the same file.

Weights are the *exchange's* leg ratios, which are also the ratios in which a
fill on the spread instrument delivers outright positions.  They are what the
cost arithmetic needs: a butterfly fill is 4 contracts (1+2+1), not 3, which is
the distinction behind ``reference_sr3_contract_weighting``.

Year decoding is relative to a reference year because CME single-digit years
are decade-ambiguous.  ``SR3U6`` in a 2026 file is Sep-2026; ``SR3H5`` is
Mar-2035, not Mar-2025 -- the SR3 strip runs ten years forward, never back.
"""
from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Dict, List, Optional, Sequence, Tuple

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

#: **The unit trap.**  Outrights and bundles quote in index points (96.040), but
#: every differential instrument quotes in **basis points** -- ``SR3:BF
#: Z6-H7-M7`` prints at 6.500 and ticks in 0.5, not 0.065 and 0.005.  Check it
#: on this file: SR3Z6 96.040, SR3H7 95.970, SR3M7 95.960 give a fly of
#: 96.040 - 2(95.970) + 95.960 = 0.060 index points = 6.0 bp, and the listed
#: butterfly's own close is 6.500.  Treating a fly price as index points inflates
#: every spread by 100x -- a one-tick market reads as 50 bp wide.
KINDS_QUOTED_IN_BP = frozenset(
    {"CALENDAR", "BUTTERFLY", "CONDOR", "DOUBLE_FLY", "BUNDLE_SPREAD", "BUNDLE_FLY"}
)

#: One SR3 contract is $25 per basis point.
USD_PER_BP_PER_CONTRACT = 25.0

MONTH_CODES: Dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}
QUARTERLY_CODES: Tuple[str, ...] = ("H", "M", "U", "Z")

_OUTRIGHT_RE = re.compile(r"^SR3([FGHJKMNQUVXZ])(\d)$")
_CAL_RE = re.compile(r"^SR3([FGHJKMNQUVXZ])(\d)-SR3([FGHJKMNQUVXZ])(\d)$")
_CONTRACT_RE = re.compile(r"([FGHJKMNQUVXZ])(\d)")
_BUNDLE_SIZE_RE = re.compile(r"^(?:(\d+)Y|PK)$")


@dataclasses.dataclass(frozen=True)
class ParsedSymbol:
    """A decoded exchange symbol.

    ``legs`` are outright symbols (``SR3U6``) and ``weights`` the exchange leg
    ratios, aligned by index.  ``n_contracts`` is ``sum(abs(weights))`` -- the
    number of outright contracts a one-lot fill delivers, and therefore the
    multiplier for any per-contract cost.
    """

    symbol: str
    kind: str
    legs: Tuple[str, ...]
    weights: Tuple[int, ...]
    months: Tuple[Optional[datetime.date], ...]
    label: str
    #: How many contracts move together for a one-unit move in this
    #: instrument's *price*.  1 for an outright and for every differential
    #: instrument, whose price is an integer combination of leg prices.  For a
    #: bundle the price is the leg **average**, so a 1 bp move is every one of
    #: its N legs moving 1 bp -- N times the dollars.
    unit_legs: int = 1
    #: Product root, e.g. ``"SR3"`` or ``"ZN"``.  Filled by the dispatcher in
    #: :mod:`RVUtils.MBO.symbols`, which is the only place that knows the
    #: registry; a grammar module parses one family and does not need it.
    root: str = ""

    @property
    def n_legs(self) -> int:
        return len(self.legs)

    @property
    def n_contracts(self) -> int:
        return int(sum(abs(w) for w in self.weights))

    @property
    def is_outright(self) -> bool:
        return self.kind == "OUTRIGHT"

    def _require_intrinsic_bp(self) -> None:
        """Refuse to express a price contract in basis points.

        ``KINDS_QUOTED_IN_BP`` is an SR3 fact, not a general one.  SR3 is a rate
        contract -- its price is ``100 - rate``, so a basis point is a fixed
        number of price units on every instrument in the complex.  A Treasury
        future is a *price* contract: a basis point of yield is worth whatever
        the cheapest-to-deliver DV01 says it is worth that day, and there is no
        constant to return here.

        Returning 100.0 for a Treasury calendar spread -- which is what a global
        kind set does -- is not so much a wrong answer as a meaningless one, and
        nothing downstream of it would look wrong.  So this raises and points at
        the DV01 path instead.
        """
        from RVUtils.MBO.products import PRODUCTS

        spec = PRODUCTS.get(self.root)
        if spec is not None and spec.usd_per_bp_per_lot is None:
            raise ValueError(
                f"{self.symbol!r} is a {self.root} instrument, which is quoted in "
                f"price points and has no intrinsic basis-point value: a bp of "
                f"yield depends on the cheapest-to-deliver DV01 for the day. Use "
                f"RVUtils.MBO.store.risk.dv01_for(), or ask for units='ticks', "
                f"'points' or 'usd'."
            )

    @property
    def bp_per_price_unit(self) -> float:
        """How many basis points one unit of this instrument's price is worth.

        Raises for a product with no intrinsic basis-point value.
        """
        self._require_intrinsic_bp()
        return 1.0 if self.kind in KINDS_QUOTED_IN_BP else 100.0

    @property
    def usd_per_bp_per_lot(self) -> float:
        """Dollars a one-lot position makes per basis point of *this* price.

        $25 for an outright, and also $25 for a calendar, butterfly or condor --
        the leg ratios are already inside the quoted price, so a one-lot fly
        moving 1 bp is $25 and not $100.  A bundle is the exception: its price
        is the average of N legs, so 1 bp on the bundle is 1 bp on each of N
        contracts.

        Raises for a product with no intrinsic basis-point value.
        """
        self._require_intrinsic_bp()
        return USD_PER_BP_PER_CONTRACT * self.unit_legs

    @property
    def front_month(self) -> Optional[datetime.date]:
        live = [m for m in self.months if m is not None]
        return min(live) if live else None

    def span_months(self) -> Optional[int]:
        """Calendar months between first and last leg -- the structure's reach."""
        live = [m for m in self.months if m is not None]
        if len(live) < 2:
            return None
        lo, hi = min(live), max(live)
        return (hi.year - lo.year) * 12 + (hi.month - lo.month)


def contract_month(code: str, digit: str, ref_year: int) -> datetime.date:
    """Decode ``('U', '6')`` to the contract's delivery month.

    The digit is resolved *forward* from ``ref_year``: the SR3 strip extends ten
    years ahead of the file date and never behind it, so a digit below the
    reference year's last digit rolls into the next decade.
    """
    month = MONTH_CODES[code]
    base = ref_year - ref_year % 10
    year = base + int(digit)
    if year < ref_year:
        year += 10
    return datetime.date(year, month, 1)


def quarterly_strip(start: datetime.date, n: int) -> List[datetime.date]:
    """``n`` consecutive quarterly (H/M/U/Z) months starting at ``start``."""
    out = [start]
    y, m = start.year, start.month
    for _ in range(n - 1):
        m += 3
        while m > 12:
            m -= 12
            y += 1
        out.append(datetime.date(y, m, 1))
    return out


def _sym(month: datetime.date, ref_year: int) -> str:
    code = next(c for c, m in MONTH_CODES.items() if m == month.month)
    return f"SR3{code}{month.year % 10}"


def _contracts(text: str, ref_year: int) -> List[Tuple[str, datetime.date]]:
    """Pull every ``<month><digit>`` pair out of a leg string, in order."""
    out = []
    for code, digit in _CONTRACT_RE.findall(text):
        month = contract_month(code, digit, ref_year)
        out.append((f"SR3{code}{digit}", month))
    return out


def _bundle_legs(size_token: str, start_code: str, start_digit: str, ref_year: int
                 ) -> Tuple[List[str], List[datetime.date]]:
    """Expand a bundle/pack token (``PK`` or ``03Y``) into its quarterly legs."""
    m = _BUNDLE_SIZE_RE.match(size_token)
    years = 1 if (m is None or m.group(1) is None) else int(m.group(1))
    start = contract_month(start_code, start_digit, ref_year)
    months = quarterly_strip(start, 4 * years)
    return [_sym(x, ref_year) for x in months], months


def parse_symbol(symbol: str, ref_year: int) -> ParsedSymbol:
    """Decode one exchange symbol.  Unrecognised forms come back ``kind='OTHER'``."""
    s = symbol.strip()

    m = _OUTRIGHT_RE.match(s)
    if m:
        month = contract_month(m.group(1), m.group(2), ref_year)
        return ParsedSymbol(s, "OUTRIGHT", (s,), (1,), (month,), s)

    m = _CAL_RE.match(s)
    if m:
        a = contract_month(m.group(1), m.group(2), ref_year)
        b = contract_month(m.group(3), m.group(4), ref_year)
        legs = (f"SR3{m.group(1)}{m.group(2)}", f"SR3{m.group(3)}{m.group(4)}")
        span = (b.year - a.year) * 12 + (b.month - a.month)
        return ParsedSymbol(s, "CALENDAR", legs, (1, -1), (a, b), f"{span}m calendar")

    if "-" in s and ":" not in s and s.startswith("SR3"):
        # SR3U6-TBF3U6 and friends: a real listed spread whose far leg is not an
        # SR3 outright.  Kept visible rather than silently dropped, but its legs
        # are not modelled -- nothing downstream can synthesise it.
        return ParsedSymbol(s, "INTERCOMMODITY", (), (), (), s)

    if not s.startswith("SR3:"):
        return ParsedSymbol(s, "OTHER", (), (), (), s)

    body = s[4:].strip()
    tag, _, rest = body.partition(" ")
    rest = rest.strip()

    if tag == "BF":
        legs = _contracts(rest, ref_year)
        if len(legs) != 3:
            return ParsedSymbol(s, "OTHER", (), (), (), s)
        syms = tuple(x[0] for x in legs)
        months = tuple(x[1] for x in legs)
        step = (months[1].year - months[0].year) * 12 + (months[1].month - months[0].month)
        return ParsedSymbol(s, "BUTTERFLY", syms, (1, -2, 1), months, f"{step}m fly")

    if tag == "CF":
        legs = _contracts(rest, ref_year)
        if len(legs) != 4:
            return ParsedSymbol(s, "OTHER", (), (), (), s)
        return ParsedSymbol(
            s, "CONDOR", tuple(x[0] for x in legs), (1, -1, -1, 1),
            tuple(x[1] for x in legs), "condor",
        )

    if tag == "DF":
        legs = _contracts(rest, ref_year)
        if len(legs) != 4:
            return ParsedSymbol(s, "OTHER", (), (), (), s)
        return ParsedSymbol(
            s, "DOUBLE_FLY", tuple(x[0] for x in legs), (1, -3, 3, -1),
            tuple(x[1] for x in legs), "double fly",
        )

    if tag == "AB":
        size, _, start = rest.partition(" ")
        c = _CONTRACT_RE.findall(start.strip())
        if not c:
            return ParsedSymbol(s, "OTHER", (), (), (), s)
        legs, months = _bundle_legs(size, c[0][0], c[0][1], ref_year)
        return ParsedSymbol(
            s, "BUNDLE", tuple(legs), tuple([1] * len(legs)), tuple(months),
            f"{len(legs) // 4}y bundle", unit_legs=len(legs),
        )

    if tag in ("SB", "BB"):
        size, _, tail = rest.partition(" ")
        if not _BUNDLE_SIZE_RE.match(size):        # BB carries no size token
            size, tail = "PK", rest
        starts = _CONTRACT_RE.findall(tail)
        if tag == "SB" and len(starts) != 2:
            return ParsedSymbol(s, "OTHER", (), (), (), s)
        if tag == "BB" and len(starts) != 3:
            return ParsedSymbol(s, "OTHER", (), (), (), s)
        ratios = (1, -1) if tag == "SB" else (1, -2, 1)
        legs: List[str] = []
        weights: List[int] = []
        months: List[datetime.date] = []
        for (code, digit), r in zip(starts, ratios):
            b_legs, b_months = _bundle_legs(size, code, digit, ref_year)
            legs.extend(b_legs)
            weights.extend([r] * len(b_legs))
            months.extend(b_months)
        unit = "pack" if size == "PK" else size.lower()
        kind = "BUNDLE_SPREAD" if tag == "SB" else "BUNDLE_FLY"
        return ParsedSymbol(s, kind, tuple(legs), tuple(weights), tuple(months),
                            f"{unit} {'spread' if tag == 'SB' else 'fly'}",
                            unit_legs=len(legs) // len(starts))

    return ParsedSymbol(s, "OTHER", (), (), (), s)


def parse_symbols(symbols: Sequence[str], ref_year: int) -> Dict[str, ParsedSymbol]:
    return {s: parse_symbol(s, ref_year) for s in symbols}


def bp_per_price_unit(kind: str, tick: Optional[float] = None) -> float:
    """Price-unit scale for a kind, cross-checked against the observed tick.

    The two signals are independent: the kind comes from the symbol string, the
    tick from the prices the instrument printed.  An index-point instrument
    cannot tick in 0.5 (that would be half a *point*, 50 bp) and a bp-quoted one
    cannot tick in 0.005, so a disagreement means the symbol was misparsed and
    is worth raising rather than silently scaling by 100.
    """
    from_kind = 1.0 if kind in KINDS_QUOTED_IN_BP else 100.0
    if tick is None:
        return from_kind
    from_tick = 1.0 if tick >= 0.1 else 100.0
    if from_tick != from_kind:
        raise ValueError(
            f"price unit disagreement for kind={kind!r}: the symbol implies "
            f"{from_kind:g} bp per unit but the observed tick {tick:g} implies "
            f"{from_tick:g}. One of the two is wrong -- do not guess."
        )
    return from_kind
