r"""A quote that cannot be what it claims to be, refused before it prices.

Why this exists
---------------
On 2026-07-14 and 2026-07-15 Citi served, for ``US91282CQY02`` (T 4 1/8 Jun-28,
the on-the-run 2-year)::

    2026-07-13   PRICE  99.744100   YIELD     4.26150
    2026-07-14   PRICE  -0.562509   YIELD  1460.54000
    2026-07-15   PRICE  -0.553099   YIELD  1463.78000
    2026-07-16   PRICE  99.941400   YIELD     4.15558

Nothing in the stack noticed. The two days are absent from the warmed timeseries
only because rateslib's yield solver refused to converge on a negative price and
raised ``max_iter: 50 exceeded in 'ift_1dim'``, which the timeseries builder
catches per date - so the run reported "0 failed" while dropping every value for
those dates, including the quoted ones that were perfectly good.

That is the wrong kind of luck. ``US912810UV88`` was corrupted on the same two
days with ``PRICE = 7.66648`` against a 5% coupon, and 7.66648 is a number a
solver converges on happily. Absent the guard below it would have produced a
plausible-looking yield in the seventies, written it, and nothing downstream could
have told it from a quote.

What is screened, and what is not
---------------------------------
Two values, for US Treasuries only:

======  ==============  ==========================  ==========
value   band            widest legitimate value     measured
                        observed in ten years       over
======  ==============  ==========================  ==========
PRICE   15 .. 200       43.60860 .. 174.31300        811,309 cells
YIELD   -5 .. 25 %      -2.39725 .. 17.89830         803,586 cells
======  ==============  ==========================  ==========

The bands are calibrated off the tape rather than argued from first principles,
and the margin is the point: 28.6 price points below the lowest price ever served
and 25.7 above the highest, 2.6 percent below the most negative yield and 7.1
above the highest. The measured population is Citi's US bond tag cache over
2016-08-08 .. 2026-08-07 - 912828 and 91282C notes, 912810 bonds, no STRIPS - with
the fifteen known-corrupt cells excluded so they could not widen the band meant to
catch them.

**This is a possibility gate, not an accuracy check.** It catches a field carrying
a different quantity entirely, which is the failure that actually occurred. A
PRICE of 95 where the truth is 99.8 passes, and nothing here pretends otherwise.

Nothing else is screened, deliberately
--------------------------------------
``SPREAD_TSY`` legitimately reaches -1548.22 bp on the same tape and ``DV01``
reaches 3338.22, so a band drawn around either would be drawn around nothing. And
markets outside the measured population are left alone: the first version of this
scan flagged 1,027 "impossible" prices that were almost all ``BRSTNCNTF212``, a
Brazilian NTN-F, which quotes per 1,000 face and prints 800-2,000 quite correctly.
A guard that fires on good data is a guard that gets switched off, so
:func:`bands_for` returns nothing for a bond it has not characterised, and
:attr:`ScreenResult.screened` says so rather than leaving silence to be read as
approval.

What this does and does not recover
-----------------------------------
At the fetcher, a refusal is surgical: ``PRICE`` leaves the book and ``DURATION``,
``DV01``, ``SPREAD_TSY`` and the ASW legs - all of which printed correctly on both
corrupt days - stay in it.

One level up it is not, and saying so matters. Every ``FixedRateBondValue``,
quoted ones included, is read off a pricer, and a pricer cannot be built without a
price; so an MDP asking for CT2 on 2026-07-14 still loses the whole date. What
changes there is the *reason*: ``NoQuotedPriceError`` naming the vendor's number,
instead of ``max_iter: 50 exceeded in 'ift_1dim'`` from a solver handed nonsense.

The number that this actually saves is the other one. ``US912810UV88``'s 7.66648
converges, and without a guard it becomes a written yield in the seventies that
nothing distinguishes from a quote.

A rule that was tested and rejected
-----------------------------------
A clean price below par implies a yield above the coupon. That is exact for a
coupon bond, needs no pricer, and would catch corruption the bands cannot - a
PRICE of 95 against a YIELD of 4.9 on a 5% coupon, say. Measured against 719,000
paired (PRICE, YIELD, coupon) observations it fired 1,220 times at a 0.25-point /
0.05-percent dead-band, and the violations were dominated by single bonds -
``US912810TV08`` alone accounted for 187, at PRICE 96.98 / YIELD 4.9487 against a
catalogued coupon of 5.0, which is a coupon-metadata error and not a quote error.
0.17% of good data rejected is not a guard, so it is not shipped.
"""

from __future__ import annotations

import dataclasses
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "QuoteBand",
    "RejectedQuote",
    "ScreenResult",
    "US_TREASURY_BANDS",
    "bands_for",
    "is_us_treasury",
    "screen_quotes",
]


@dataclasses.dataclass(frozen=True)
class QuoteBand:
    """The range a value can possibly take, and the evidence for it.

    ``observed_lo``/``observed_hi``/``cells`` are carried so a rejection message
    can say how much room the band had, rather than asserting a bound the reader
    has to take on trust.
    """

    lo: float
    hi: float
    unit: str
    observed_lo: float
    observed_hi: float
    cells: int

    def contains(self, value: float) -> bool:
        return self.lo <= float(value) <= self.hi

    def describe(self) -> str:
        return (
            f"{self.lo:g}..{self.hi:g} {self.unit} "
            f"(widest served in {self.cells:,} cells: {self.observed_lo:g}..{self.observed_hi:g})"
        )


#: Calibrated 2026-08-08 off the DAILY/CLOSE tag cache, US ISINs, ten years.
US_TREASURY_BANDS: Mapping[str, QuoteBand] = {
    "PRICE": QuoteBand(15.0, 200.0, "price points", 43.60860, 174.31300, 811_309),
    "YIELD": QuoteBand(-5.0, 25.0, "percent", -2.39725, 17.89830, 803_586),
}


@dataclasses.dataclass(frozen=True)
class RejectedQuote:
    """One value Citi served that cannot be the quantity it is labelled as."""

    citi_value: str
    value: float
    band: QuoteBand

    @property
    def reason(self) -> str:
        return (
            f"{self.citi_value} = {self.value:g} is outside {self.band.describe()}, "
            f"so it is not a {self.citi_value.lower()}"
        )


@dataclasses.dataclass(frozen=True)
class ScreenResult:
    """What survived, what did not, and whether anything was checked at all.

    ``screened`` is the field that keeps this honest. An empty ``rejected`` means
    "nothing was refused"; it means "nothing was found wrong" only when
    ``screened`` is true. For an unrecognised market the two are very different
    statements and the caller must be able to tell them apart.
    """

    kept: Mapping[str, float]
    rejected: Mapping[str, RejectedQuote]
    screened: bool
    values_screened: Tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.rejected


def is_us_treasury(
    isin: str, *, country: str = "", currency: str = "", asset_type: str = ""
) -> bool:
    """Whether this bond is in the population the bands were measured over.

    Two routes, because the descriptor is optional. Every US Treasury CUSIP begins
    ``912``, so ``US912...`` identifies one from the ISIN alone; the universe key
    identifies one when the catalog knows the bond but the ISIN test is too narrow
    (a US agency filed under GOVT trades in the same range and was in the measured
    population - fourteen of the 811,309 cells are FHLB).
    """
    tag = str(isin or "").strip().upper()
    if tag.startswith("US912"):
        return True
    return (
        str(country or "").strip().upper() in ("USA", "US")
        and str(asset_type or "").strip().upper() == "GOVT"
        and str(currency or "USD").strip().upper() == "USD"
        and tag.startswith("US")
    )


def bands_for(
    isin: str, *, country: str = "", currency: str = "", asset_type: str = ""
) -> Mapping[str, QuoteBand]:
    """The bands that apply to this bond, or an EMPTY mapping if none do.

    Empty means uncharacterised, not clean. See the module docstring on BRL.
    """
    if is_us_treasury(isin, country=country, currency=currency, asset_type=asset_type):
        return US_TREASURY_BANDS
    return {}


def screen_quotes(
    quoted: Mapping[str, float],
    *,
    isin: str,
    country: str = "",
    currency: str = "",
    asset_type: str = "",
    bands: Optional[Mapping[str, QuoteBand]] = None,
) -> ScreenResult:
    """Split a served book into what can be a quote and what cannot.

    Values with no band pass through untouched - the result is a filter, never a
    reducer, so a caller that ignores ``rejected`` sees exactly today's behaviour
    minus the impossible numbers.
    """
    applicable = (
        bands
        if bands is not None
        else bands_for(isin, country=country, currency=currency, asset_type=asset_type)
    )
    kept: Dict[str, float] = {}
    rejected: Dict[str, RejectedQuote] = {}
    for name, raw in quoted.items():
        band = applicable.get(str(name).strip().upper())
        if band is None:
            kept[name] = raw
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            kept[name] = raw
            continue
        if band.contains(value):
            kept[name] = raw
        else:
            rejected[name] = RejectedQuote(str(name).strip().upper(), value, band)
    return ScreenResult(
        kept=kept,
        rejected=rejected,
        screened=bool(applicable),
        values_screened=tuple(sorted(applicable)),
    )
