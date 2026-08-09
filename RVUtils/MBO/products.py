"""Per-product units, ticks and match algorithm -- the one place that knows them.

Every unit constant in ``metrics.py`` was hard-wired to SR3.  That is fine for a
single-product explorer and wrong the moment a Treasury root appears, because the
two are not the same kind of instrument:

* **SR3 is a rate contract.**  Its price is ``100 - rate``, so a basis point is a
  price move of 0.01 index points and is worth $25 on any contract, always.
* **A Treasury future is a price contract.**  It has a tick and a dollar value per
  tick, and it has no basis-point value at all until a CTD DV01 says what a basis
  point of *yield* is worth on that day.

So ``usd_per_bp_per_lot`` is ``None`` for every Treasury root, and that absence is
the point of this module rather than an omission from it.  A probe of the real
archives had the old code return ``bp_per_unit = 100.0`` for a Treasury calendar
spread, which is not so much a wrong number as a meaningless one -- and nothing
downstream would have looked wrong.

Ticks are exact :class:`~fractions.Fraction` objects.  A thirty-second is 1/32 and
a half of a thirty-second is 1/64; those happen to be exact in binary floating
point, but SR3's 0.005 is not, and one convention that is always right beats two
that are usually right.

Outright tick values below are **measured** from the archives (the gcd of price
offsets across tens of thousands of prints per contract) and agree with the
contract specifications.  Spread ticks are the specification values: a gcd taken
over a few dozen prints on a quiet session is an integer *multiple* of the true
tick, so measurement bounds them from above and cannot pin them.
"""
from __future__ import annotations

import dataclasses
from fractions import Fraction
from typing import Dict, Mapping, Optional

__all__ = [
    "PRODUCTS",
    "ProductSpec",
    "check_tick",
    "is_known_root",
    "root_of",
    "spec_for",
]


@dataclasses.dataclass(frozen=True)
class ProductSpec:
    """What a contract's prices mean."""

    root: str
    grammar: str                        # "sr3" | "ust" -- which symbol parser
    quote: str                          # "index_points" | "points_32nds"
    contract_unit: float                # notional per contract
    outright_tick: Fraction
    usd_per_tick: float                 # dollars per outright_tick per contract
    spread_tick: Mapping[str, Fraction]
    match_algo: str                     # gates the queue model in Phase 3
    usd_per_bp_per_lot: Optional[float]  # None where bp needs a DV01
    #: Several roots quote the lead contract on a finer grid than the deferreds.
    outright_tick_front: Optional[Fraction] = None

    @property
    def usd_per_point(self) -> float:
        """Dollars per one full point of price, per contract."""
        return self.usd_per_tick / float(self.outright_tick)

    def tick_for(self, kind: str) -> Fraction:
        """The finest grid this kind of instrument is permitted to quote on."""
        if kind == "OUTRIGHT":
            return self.outright_tick_front or self.outright_tick
        return self.spread_tick.get(kind, self.outright_tick)

    def usd_per_tick_for(self, kind: str) -> float:
        return self.usd_per_tick * float(self.tick_for(kind) / self.outright_tick)


def _ust(root: str, unit: float, tick: Fraction, usd_per_tick: float,
         spread_tick: Fraction) -> ProductSpec:
    """A Treasury futures root.  All of them are FIFO and none has a bp value."""
    return ProductSpec(
        root=root,
        grammar="ust",
        quote="points_32nds",
        contract_unit=unit,
        outright_tick=tick,
        usd_per_tick=usd_per_tick,
        spread_tick={
            "CALENDAR": spread_tick,
            "BUTTERFLY": spread_tick,
            "INTERCOMMODITY": spread_tick,
        },
        match_algo="FIFO",
        usd_per_bp_per_lot=None,
    )


#: SR3 differential instruments quote directly in basis points and tick in halves
#: of one.  The outright and the bundles quote in index points.
_SR3_BP_KINDS = (
    "CALENDAR", "BUTTERFLY", "CONDOR", "DOUBLE_FLY", "BUNDLE_SPREAD", "BUNDLE_FLY",
)

PRODUCTS: Dict[str, ProductSpec] = {
    "SR3": ProductSpec(
        root="SR3",
        grammar="sr3",
        quote="index_points",
        contract_unit=1_000_000.0,
        outright_tick=Fraction(1, 200),          # 0.005 index points = 0.5 bp
        usd_per_tick=12.50,
        spread_tick={
            **{k: Fraction(1, 2) for k in _SR3_BP_KINDS},
            # Bundles quote in index points, and on a quarter tick: measured at
            # 1/400 over 44,554 prints, against 1/200 for the outrights.
            "BUNDLE": Fraction(1, 400),
        },
        match_algo="FIFO",
        usd_per_bp_per_lot=25.0,
        outright_tick_front=Fraction(1, 400),    # 0.0025 on the lead contract
    ),
    # Treasury outright ticks below are measured; each is the classic
    # eighth/quarter/half/whole of one thirty-second for that maturity bucket.
    "ZT": _ust("ZT", 200_000.0, Fraction(1, 256), 7.8125, Fraction(1, 512)),
    "ZF": _ust("ZF", 100_000.0, Fraction(1, 128), 7.8125, Fraction(1, 256)),
    "ZN": _ust("ZN", 100_000.0, Fraction(1, 64), 15.625, Fraction(1, 128)),
    "TN": _ust("TN", 100_000.0, Fraction(1, 64), 15.625, Fraction(1, 128)),
    "ZB": _ust("ZB", 100_000.0, Fraction(1, 32), 31.25, Fraction(1, 128)),
    "UB": _ust("UB", 100_000.0, Fraction(1, 32), 31.25, Fraction(1, 128)),
}

#: Longest first: ``TN`` and ``ZN`` share a suffix, and a shortest-match rule
#: would silently assign one of them to the other's spec.
_ROOTS_BY_LENGTH = tuple(sorted(PRODUCTS, key=len, reverse=True))

#: Roots that appear only as the far leg of a listed inter-commodity spread.  We
#: hold no archive for them, but they must parse rather than crash.
_LEG_ONLY_ROOTS = ("MTN", "MWN", "TBF3", "MZN", "MZB", "MZF", "MZT")


def spec_for(root: str) -> ProductSpec:
    """The specification for a root, or ``KeyError``."""
    return PRODUCTS[root]


def is_known_root(root: str) -> bool:
    return root in PRODUCTS


def root_of(symbol: str) -> Optional[str]:
    """The product root a raw exchange symbol belongs to, or ``None``.

    Works on every symbol form the archives contain: ``ZNU6``, ``ZNU6-ZNZ6``,
    ``ZN:BF M6-U6-Z6``, ``SR3:AB 01Y U6``.  The root is taken from the head of the
    string -- the part before any ``:`` or ``-`` -- because in a spread symbol
    the *first* leg names the instrument's product.
    """
    s = symbol.strip()
    head = s.split(":", 1)[0].split("-", 1)[0].strip()
    for root in _ROOTS_BY_LENGTH:
        if head.startswith(root):
            return root
    for root in _ROOTS_BY_LENGTH:
        if s.startswith(root):
            return root
    return None


def check_tick(
    root: str,
    kind: str,
    observed_tick: float,
    max_ratio: int = 8,
    rel_tol: float = 1e-6,
) -> Fraction:
    """Sanity-gate the grid an instrument printed on against its specification.

    Returns the specification tick.  This is a *gate*, not the source of the
    ladder: the replay always uses the observed gcd, because that is the lattice
    the exchange actually used.  What this catches is the two signals disagreeing
    by an order of magnitude, which is the signature of a misparsed symbol being
    scaled by the wrong unit -- the failure that turns a one-tick market into a
    fifty-basis-point one without ever looking implausible.

    Commensurability, not equality, is the test, and in both directions:

    * A quiet instrument prints on a *coarser* grid than it may quote on.  A gcd
      over forty prints is an integer multiple of the true tick, so ``observed``
      being ``k`` times the spec for small ``k`` is expected and fine.
    * A spec that is too coarse shows up as ``observed`` being an integer
      *fraction* of it.  That is a bug in this table and it is allowed through
      with the ratio reported, because the ladder is right either way and
      refusing to replay would be the worse failure.

    A ratio beyond ``max_ratio`` in either direction, or one that is not close to
    a whole number, raises.
    """
    spec = spec_for(root)
    want = spec.tick_for(kind)
    w = float(want)
    if observed_tick <= 0 or w <= 0:
        raise ValueError(
            f"tick disagreement for {root} {kind}: non-positive tick "
            f"(spec {w:g}, observed {observed_tick:g})"
        )

    ratio = observed_tick / w
    n = round(ratio if ratio >= 1.0 else 1.0 / ratio)
    exact = abs((ratio if ratio >= 1.0 else 1.0 / ratio) - n) <= max(rel_tol * n, 1e-9)
    if not exact or n > max_ratio:
        raise ValueError(
            f"tick disagreement for {root} {kind}: the specification says "
            f"{w:g} but the instrument printed on a grid of {observed_tick:g} "
            f"({observed_tick / w:g}x). One of the two is wrong -- do not guess."
        )
    return want
