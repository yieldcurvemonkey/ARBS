r"""Per-index conventions for the Citi Velocity ``RATES.INFLATION`` families.

Citi quotes zero-coupon inflation swap rates as
``RATES.INFLATION.SWAP.<index>.<tenor>``, in percent, across 17 index tokens and a
17-point tenor axis (``1M 3M 6M 1Y 2Y 3Y 4Y 5Y 7Y 10Y 12Y 15Y 20Y 25Y 30Y 40Y SPOT``).
The number is a **breakeven**: the fixed rate :math:`r` such that

.. math::

    (1 + r)^N = \frac{I(T - L)}{I(S - L)}

for an :math:`N`-year swap with observation lag :math:`L`. Everything that can go
quietly wrong in inflation lives in that denominator.

The lag is the whole game
-------------------------
:math:`I(S - L)` is a **published** number, not a forecast. Pick the wrong month
and every breakeven off the curve is wrong by roughly the accrued inflation over
the misdating, annualised over the tenor. Measured on a synthetic 2.5%-flat
history (``_smoke.py``), using the latest *published* fixing (1-month
availability lag) where the USD convention wants the 3-month-lagged one moves the
breakeven by

===== ==========
tenor error (bp)
===== ==========
2Y    -19.05
5Y     -7.61
10Y    -3.81
30Y    -1.27
===== ==========

That is a two-month error. A full three-month error is worse again. Nothing about
the curve build complains: the solver converges, the swaps reprice, and the level
is wrong.

Worse, a **self-consistent** lag error is completely invisible. Rebuild the USD
curve at a 6-month lag with a 6-month-lagged base and every breakeven is unchanged
to 0.00e+00 bp with a bit-identical repricing error - the lag shifts both
observations together, so the ratio is invariant. Only the implied index LEVEL
moves (61.9 bp for three months on a 2.5% history). No round-trip test can find
this. So the lag and the interpolation method are recorded here per index, with
their source, and the builders refuse to guess.

Where the numbers come from
---------------------------
For the three flagship indices the conventions are **rateslib's own**, read out of
``rateslib.defaults.spec`` in 2.1.1 rather than typed from memory:

======================  =============  =======  ==========
Citi index              rateslib spec  lag (m)  method
======================  =============  =======  ==========
``USD_CPURNSA``         ``usd_zcis``   3        ``daily``
``EUR_CPTFEMU``         ``eur_zcis``   3        ``monthly``
``GBP_UKRPI``           ``gbp_zcis``   2        ``monthly``
======================  =============  =======  ==========

Every other index carries ``provenance="market_standard"``: 3-month lag,
non-interpolated (monthly) observation, which is the euro-area national and
Nordic/Asian convention. Those are **not** library-supplied and are not verified
against a Citi quote. :attr:`InflationIndexConvention.approximate` is True for all
of them and the builders warn once per curve.

Swaps and linkers do not share a convention
-------------------------------------------
``gbp_zcis`` is 2-month lag / monthly. ``uk_gbi`` - rateslib's own index-linked
gilt spec - is **3-month lag / daily**. They are different instruments in the same
index and mixing them misprices the linker by a full month of carry. The bond
conventions live in :data:`CITI_LINKER_CONVENTIONS`, separately, for that reason.

Quarterly indices are a structural problem, not a parameter
-----------------------------------------------------------
``AUD_AUCPI`` is **quarterly**. rateslib 2.1.1's
:meth:`Curve.index_value` interpolates with :func:`calendar.monthrange` and
``add_tenor(..., "1M", ...)`` - it has no representation of a quarterly index
period at all. QuantLib does (``ql.AUCPI(ql.Quarterly, False)``). So the rateslib
builder **raises** for quarterly indices rather than returning a monthly-shaped
answer that looks right, and the QuantLib builder handles them.

Seasonality
-----------
Every index here is a non-seasonally-adjusted consumer price index, and all of
them are strongly seasonal. That does not bite whole-year zero-coupon swaps -
start and end observations fall in the same calendar month, so the seasonal
factor cancels - but it bites everything else: off-anniversary maturities, the
sub-1Y tenors on Citi's axis, month-by-month index forecasts and any linker
settling mid-year. rateslib 2.1.1 has no seasonality object; QuantLib has
:class:`ql.MultiplicativePriceSeasonality`, exposed by the QuantLib builder. A
curve built with seasonality in one backend is **not** comparable to one built
without it in the other, and the builders say so.
"""

from __future__ import annotations

import calendar as _calendar
import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from MDP.CitiVelocityExcel.errors import UnknownTagError

__all__ = [
    "InflationIndexConvention",
    "LinkerConvention",
    "CITI_INFLATION_INDICES",
    "CITI_LINKER_CONVENTIONS",
    "CARRY_CURVE_FOR_INDEX",
    "INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX",
    "SWAPTION_INDICES",
    "CITI_ZC_TENORS",
    "DEFAULT_CALIBRATION_TENORS",
    "conventions_for",
    "describe",
    "supported_indices",
    "linker_conventions_for",
    "reference_month",
    "index_base_month",
    "required_fixing_months",
    "tenor_to_years",
    "ql_index_for",
]

_logger = logging.getLogger(__name__)

#: The tenor axis Citi serves under ``RATES.INFLATION.SWAP.<index>`` - identical
#: for every index except ``US_CPI``, which carries ``SPOT`` only.
CITI_ZC_TENORS: Tuple[str, ...] = (
    "1M", "3M", "6M", "1Y", "2Y", "3Y", "4Y", "5Y", "7Y",
    "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y",
)

#: What the curve builders calibrate on by default: whole years only.
#:
#: The sub-1Y points are excluded deliberately. A 1M/3M/6M zero-coupon inflation
#: swap maturing inside the published-fixing window is index ARITHMETIC on numbers
#: that are already printed, not curve information - it carries no forward view,
#: and including it forces the first curve segment to fit a quote whose observation
#: months the bootstrap should be reading off the fixing series instead. ``SPOT``
#: is not a tenor at all.
DEFAULT_CALIBRATION_TENORS: Tuple[str, ...] = (
    "1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y",
)

#: ``RATES.INFLATION.INF_CARRY.<curve>.<index>.<measure>`` - the carry curve token
#: that belongs to each swap index, from the harvested catalog. Six of the
#: seventeen swap indices have one.
CARRY_CURVE_FOR_INDEX: Dict[str, str] = {
    "USD_CPURNSA": "USD_CARRY",
    "GBP_UKRPI": "GBP_CARRY",
    "EUR_GRCP2000": "DEU_CARRY",
    "EUR_FRCPXTOB": "FRA_CARRY",
    "EUR_ITCPI": "ITA_CARRY",
    "AUD_AUCPI": "AUD_CARRY",
}

#: ``RATES.INFLATION.INDEX.<token>`` - the five published index levels Citi serves
#: as a timeseries, mapped onto the swap index they price. The INDEX family is the
#: only route to the published fixings the builders need for ``index_base``.
INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX: Dict[str, str] = {
    "USD_CPURNSA": "US_CPIZU",
    "GBP_UKRPI": "UK_RPI",
    "EUR_CPTFEMU": "EURO_HICPXT",
    "EUR_FRCPXTOB": "FRANCE_CPI",
    "SEK_SWCPI": "SWEDEN_CPI",
}

#: ``RATES.INFLATION.SWAPTION.<index>.ATM.{NORMAL,FWDPREMIUM}`` exists for exactly
#: these three. The level below ``NORMAL`` is a 19-point axis (1M..50Y) which the
#: Function Builder walk did not expand further, so whether it is expiry-only or
#: expiry x tail is UNVERIFIED.
SWAPTION_INDICES: Tuple[str, ...] = ("EUR_CPTFEMU", "GBP_UKRPI", "USD_CPURNSA")


# ------------------------------------------------------------------ #
#                            the records                             #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class InflationIndexConvention:
    """Everything both backends need to strip one Citi inflation curve.

    Attributes
    ----------
    citi_index
        The Velocity token under ``RATES.INFLATION.SWAP``, e.g. ``USD_CPURNSA``.
    currency
        ISO code of the swap's cash currency.
    description
        Human name of the underlying price index.
    bbg_ticker
        The Bloomberg index ticker the Citi token is built from, where it is
        recognisable. Informational only.
    rl_spec
        rateslib named ZCIS spec (``usd_zcis``/``eur_zcis``/``gbp_zcis``) or None.
    observation_lag
        Months by which the swap observes the index. **This is the number that
        moves breakevens by bp if it is wrong.**
    index_method
        rateslib spelling: ``daily`` (calendar-day interpolation between the two
        surrounding monthly fixings) or ``monthly`` (flat, the fixing for the
        reference month). Maps to ``ql.CPI.Linear`` / ``ql.CPI.Flat``.
    publication_lag
        Months from the reference month to first publication. Used to decide which
        fixings the caller can be expected to have, never to shift observations.
    frequency
        ``monthly`` or ``quarterly``. Quarterly is not representable in rateslib
        2.1.1 - see the module docstring.
    calendar
        rateslib calendar name for schedule rolls.
    spot_lag
        Business days from trade to swap effective date.
    fixed_frequency, convention
        Fixed-leg schedule and day count in rateslib spelling. ``1+`` is the
        zero-coupon compounding convention: exactly N for an N-year swap.
    ql_index_name
        A shipped QuantLib class name, when one exists for this index.
    ql_region
        ``(name, code)`` for :class:`ql.CustomRegion` when it does not.
    ql_family
        ``familyName`` for the generic :class:`ql.ZeroInflationIndex`.
    provenance
        ``rateslib_spec`` when the lag and method are read out of
        ``rateslib.defaults.spec``; ``market_standard`` when they are encoded here
        from convention and are NOT verified against a Citi quote.
    note
        What specifically is approximate or surprising.
    """

    citi_index: str
    currency: str
    description: str
    bbg_ticker: str
    rl_spec: Optional[str]
    observation_lag: int
    index_method: str
    publication_lag: int
    frequency: str
    calendar: str
    spot_lag: int
    fixed_frequency: str = "a"
    convention: str = "1+"
    ql_index_name: Optional[str] = None
    ql_region: Optional[Tuple[str, str]] = None
    ql_family: str = "CPI"
    provenance: str = "market_standard"
    note: str = ""
    seasonal: bool = True
    curve_id: str = ""

    def __post_init__(self) -> None:
        if self.index_method not in {"daily", "monthly"}:
            raise ValueError(
                f"{self.citi_index}: index_method must be 'daily' or 'monthly', "
                f"got {self.index_method!r}."
            )
        if self.frequency not in {"monthly", "quarterly"}:
            raise ValueError(
                f"{self.citi_index}: frequency must be 'monthly' or 'quarterly', "
                f"got {self.frequency!r}."
            )
        if not self.curve_id:
            object.__setattr__(
                self, "curve_id", f"{self.citi_index.replace('_', '-')}-ZC-CITIVELO"
            )

    @property
    def approximate(self) -> bool:
        """True when the lag/method are market convention rather than library-supplied."""
        return self.provenance != "rateslib_spec"

    @property
    def rl_representable(self) -> bool:
        """False for quarterly indices: rateslib 2.1.1 has no quarterly index period."""
        return self.frequency == "monthly"

    @property
    def months_per_period(self) -> int:
        """Months in one index publication period."""
        return 3 if self.frequency == "quarterly" else 1

    @property
    def ql_observation_interpolation_name(self) -> str:
        """``Linear`` or ``Flat`` - the ``CPI::InterpolationType`` member name."""
        return "Linear" if self.index_method == "daily" else "Flat"

    def ql_observation_interpolation(self) -> Any:
        """The :class:`ql.CPI` enum member matching :attr:`index_method`."""
        ql = _ql()
        return getattr(ql.CPI, self.ql_observation_interpolation_name)

    def ql_frequency(self) -> Any:
        """The QuantLib ``Frequency`` for this index's publication period."""
        ql = _ql()
        return ql.Quarterly if self.frequency == "quarterly" else ql.Monthly

    def ql_index(self, handle: Any = None) -> Any:
        """Build the QuantLib zero inflation index bound to ``handle``.

        Parameters
        ----------
        handle
            A :class:`ql.ZeroInflationTermStructureHandle`. If None an empty
            handle is used, which is fine for building helpers before the curve
            exists but not for forecasting.

        Returns
        -------
        ql.ZeroInflationIndex
        """
        ql = _ql()
        if handle is None:
            handle = ql.ZeroInflationTermStructureHandle()
        if self.ql_index_name is not None:
            cls = getattr(ql, self.ql_index_name)
            # ql.AUCPI takes (frequency, revised, handle); the monthly classes
            # take (handle) only. Verified against QuantLib 1.41 SWIG overloads -
            # calling the wrong one raises TypeError, it does not fall back.
            if self.frequency == "quarterly":
                return cls(self.ql_frequency(), False, handle)
            return cls(handle)
        if self.ql_region is None:
            raise UnknownTagError(
                f"{self.citi_index} has neither a QuantLib index class nor a region; "
                "cannot build a ql.ZeroInflationIndex."
            )
        region = ql.CustomRegion(self.ql_region[0], self.ql_region[1])
        currency = getattr(ql, f"{self.currency}Currency")()
        return ql.ZeroInflationIndex(
            self.ql_family,
            region,
            False,  # revised
            self.ql_frequency(),
            ql.Period(self.publication_lag, ql.Months),
            currency,
            handle,
        )


@dataclass(frozen=True)
class LinkerConvention:
    """Index-linked bond conventions, which are NOT the swap conventions.

    UK is the standing example: ``gbp_zcis`` is 2-month lag / monthly, while
    rateslib's own ``uk_gbi`` index-linked gilt spec is 3-month lag / daily. Using
    the swap convention on a linker misdates the index by a month.
    """

    currency: str
    citi_index: str
    rl_spec: Optional[str]
    index_lag: int
    index_method: str
    provenance: str
    note: str = ""


def _ql() -> Any:
    import QuantLib as ql  # imported lazily: QuantLib is slow to import

    return ql


# ------------------------------------------------------------------ #
#                             the table                              #
# ------------------------------------------------------------------ #

_EURO_AREA_NOTE = (
    "Euro-area national index. 3-month lag with NON-interpolated (monthly) "
    "observation is the market standard for these; it is not supplied by either "
    "library and has not been checked against a Citi quote."
)

_INDICES: Tuple[InflationIndexConvention, ...] = (
    InflationIndexConvention(
        citi_index="USD_CPURNSA",
        currency="USD",
        description="US CPI Urban Consumers, NSA",
        bbg_ticker="CPURNSA",
        rl_spec="usd_zcis",
        observation_lag=3,
        index_method="daily",
        publication_lag=1,
        frequency="monthly",
        calendar="nyc",
        spot_lag=2,
        ql_index_name="USCPI",
        provenance="rateslib_spec",
        note=(
            "Lag 3 / method 'daily' are rateslib 2.1.1's own usd_zcis spec, i.e. the "
            "TIPS-style daily-interpolated reference CPI. Some desks quote USD "
            "zero-coupon swaps on the non-interpolated reference month instead; "
            "measured on a flat 2.5% history the two differ by ~4.0 bp of INDEX LEVEL "
            "(0.04%), which is a fraction of a bp on a 10Y breakeven but material on "
            "the front. Override with index_method='monthly' if your desk quotes that way."
        ),
    ),
    InflationIndexConvention(
        citi_index="US_CPI",
        currency="USD",
        description="US CPI - Citi legacy alias, SPOT only",
        bbg_ticker="CPURNSA",
        rl_spec="usd_zcis",
        observation_lag=3,
        index_method="daily",
        publication_lag=1,
        frequency="monthly",
        calendar="nyc",
        spot_lag=2,
        ql_index_name="USCPI",
        provenance="rateslib_spec",
        note=(
            "The harvested catalog gives this token exactly one child, SPOT - there is "
            "no tenor axis under it. It cannot be calibrated; use USD_CPURNSA."
        ),
    ),
    InflationIndexConvention(
        citi_index="GBP_UKRPI",
        currency="GBP",
        description="UK Retail Prices Index",
        bbg_ticker="UKRPI",
        rl_spec="gbp_zcis",
        observation_lag=2,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="ldn",
        spot_lag=0,
        ql_index_name="UKRPI",
        provenance="rateslib_spec",
        note=(
            "TWO-month lag, not three, and non-interpolated - rateslib's gbp_zcis spec. "
            "Index-linked GILTS use 3-month lag with DAILY interpolation (rateslib's "
            "uk_gbi): see CITI_LINKER_CONVENTIONS. GBP also settles same-day (T+0)."
        ),
    ),
    InflationIndexConvention(
        citi_index="EUR_CPTFEMU",
        currency="EUR",
        description="Eurozone HICP excluding tobacco",
        bbg_ticker="CPTFEMU",
        rl_spec="eur_zcis",
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_index_name="EUHICPXT",
        provenance="rateslib_spec",
        note=(
            "The euro inflation benchmark. Lag 3 / non-interpolated from rateslib's "
            "eur_zcis spec. Note euro linkers (OATei, BTPei) observe the SAME index "
            "with daily interpolation - a swap convention is not a bond convention."
        ),
    ),
    InflationIndexConvention(
        citi_index="EUR_FRCPXTOB",
        currency="EUR",
        description="France CPI excluding tobacco",
        bbg_ticker="FRCPXTOB",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("France", "FR"),
        ql_family="CPIXT",
        note=(
            "The OATi index. NOT ql.FRHICP - that is the French HICP, a different "
            "series; a generic ql.ZeroInflationIndex on a France CustomRegion is used "
            "instead so the mismatch cannot hide behind a shipped class name. "
            + _EURO_AREA_NOTE
        ),
    ),
    InflationIndexConvention(
        citi_index="EUR_ITCPI",
        currency="EUR",
        description="Italy CPI (FOI ex-tobacco)",
        bbg_ticker="ITCPIUNR",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Italy", "IT"),
        ql_family="FOI",
        note=_EURO_AREA_NOTE,
    ),
    InflationIndexConvention(
        citi_index="EUR_GRCP2000",
        currency="EUR",
        description="Germany CPI (VPI, 2000=100)",
        bbg_ticker="GRCP20YY",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Germany", "DE"),
        ql_family="CPI",
        note=(
            "'GR' is Bloomberg for Germany, not Greece - confirmed by the catalog, "
            "which pairs RATES.INFLATION.INF_CARRY.DEU_CARRY with GRCP2000. "
            + _EURO_AREA_NOTE
        ),
    ),
    InflationIndexConvention(
        citi_index="EUR_SPIPC",
        currency="EUR",
        description="Spain CPI (IPC)",
        bbg_ticker="SPIPC",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Spain", "ES"),
        ql_family="IPC",
        note=_EURO_AREA_NOTE,
    ),
    InflationIndexConvention(
        citi_index="EUR_BECPHLTH",
        currency="EUR",
        description="Belgium health index",
        bbg_ticker="BECPHLTH",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Belgium", "BE"),
        ql_family="HEALTH",
        note=(
            "The Belgian 'health index' is a filtered CPI (tobacco, alcohol and fuel "
            "removed) used for wage indexation, not the HICP. " + _EURO_AREA_NOTE
        ),
    ),
    InflationIndexConvention(
        citi_index="EUR_NECPIND",
        currency="EUR",
        description="Netherlands CPI (derived)",
        bbg_ticker="NECPIND",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Netherlands", "NL"),
        ql_family="CPI",
        note=_EURO_AREA_NOTE,
    ),
    InflationIndexConvention(
        citi_index="EUR_IECP2006",
        currency="EUR",
        description="Ireland CPI (2006=100)",
        bbg_ticker="IECP2006",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Ireland", "IE"),
        ql_family="CPI",
        note=_EURO_AREA_NOTE,
    ),
    InflationIndexConvention(
        citi_index="EUR_DNCPINEW",
        currency="DKK",
        description="Denmark CPI",
        bbg_ticker="DNCPINEW",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Denmark", "DK"),
        ql_family="CPI",
        note=(
            "CURRENCY IS A JUDGEMENT CALL. Citi files this under the EUR_ prefix with "
            "the euro-area nationals, but DNCPINEW is the Danish CPI and the swap is "
            "almost certainly DKK-settled. The currency here affects only the QuantLib "
            "index's currency field and any FX conversion - not the breakeven. Confirm "
            "before booking. " + _EURO_AREA_NOTE
        ),
    ),
    InflationIndexConvention(
        citi_index="EUR_PLCPI",
        currency="PLN",
        description="Poland CPI",
        bbg_ticker="POCPIYOY / PLCPI",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Poland", "PL"),
        ql_family="CPI",
        note=(
            "CURRENCY IS A JUDGEMENT CALL, as for EUR_DNCPINEW: filed under EUR_ but "
            "the index is Polish. The 'tgt' calendar is a placeholder - Warsaw is not "
            "a rateslib calendar. " + _EURO_AREA_NOTE
        ),
    ),
    InflationIndexConvention(
        citi_index="SEK_SWCPI",
        currency="SEK",
        description="Sweden CPI",
        bbg_ticker="SWCPI",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="stk",
        spot_lag=2,
        ql_region=("Sweden", "SE"),
        ql_family="CPI",
        note=(
            "rateslib ships sek_iirs (a SEK inflation-linked IRS) at lag 3 / DAILY, "
            "which is the LINKER convention; the zero-coupon swap is quoted "
            "non-interpolated. QuantLib has no SECPI class. " + _EURO_AREA_NOTE
        ),
    ),
    InflationIndexConvention(
        citi_index="JPY_JCPNGENF",
        currency="JPY",
        description="Japan CPI nationwide ex-fresh food",
        bbg_ticker="JCPNGENF",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tyo",
        spot_lag=2,
        ql_region=("Japan", "JP"),
        ql_family="CPIXFF",
        note=(
            "The JGBi index (core CPI, ex fresh food). QuantLib ships no JPCPI class. "
            "Lag and observation are market standard, not library-supplied."
        ),
    ),
    InflationIndexConvention(
        citi_index="ILS_ISCPIL",
        currency="ILS",
        description="Israel CPI",
        bbg_ticker="ISCPIL",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=1,
        frequency="monthly",
        calendar="tgt",
        spot_lag=2,
        ql_region=("Israel", "IL"),
        ql_family="CPI",
        note=(
            "ILS trades SUNDAY-THURSDAY; 'tgt' is a Monday-Friday placeholder and will "
            "misdate rolls. Build a real Israel calendar with "
            "MDP.CitiVelocityExcel.curves.conventions.rl_calendar_from_quantlib("
            "ql.Israel(), weekend=(4, 5)) and pass it as `calendar` if the roll dates "
            "matter. They do not affect a whole-year breakeven, which observes months."
        ),
    ),
    InflationIndexConvention(
        citi_index="AUD_AUCPI",
        currency="AUD",
        description="Australia CPI (QUARTERLY)",
        bbg_ticker="AUCPI",
        rl_spec=None,
        observation_lag=3,
        index_method="monthly",
        publication_lag=2,
        frequency="quarterly",
        calendar="syd",
        spot_lag=2,
        ql_index_name="AUCPI",
        note=(
            "QUARTERLY index. rateslib 2.1.1 cannot represent it: Curve.index_value "
            "interpolates with calendar.monthrange and add_tenor('1M') and has no "
            "quarterly index period, so build_rl_index_curve REFUSES this index rather "
            "than return a monthly-shaped answer. QuantLib handles it natively via "
            "ql.AUCPI(ql.Quarterly, False). The 3-month observation lag recorded here "
            "is a market-standard guess and is UNVERIFIED - the Australian convention "
            "references a quarter, not a month."
        ),
    ),
)

CITI_INFLATION_INDICES: Dict[str, InflationIndexConvention] = {
    c.citi_index: c for c in _INDICES
}

#: Index-linked BOND conventions. Deliberately separate from the swap table: they
#: disagree, and the UK disagreement is a full month of index carry.
CITI_LINKER_CONVENTIONS: Dict[str, LinkerConvention] = {
    "GBP_UKRPI": LinkerConvention(
        currency="GBP",
        citi_index="GBP_UKRPI",
        rl_spec="uk_gbi",
        index_lag=3,
        index_method="daily",
        provenance="rateslib_spec",
        note=(
            "Post-2005 'new style' 3-month-lag index-linked gilt, from rateslib's "
            "uk_gbi spec. The RPI SWAP is 2-month lag / monthly - do not share a "
            "convention object between them. Pre-2005 8-month-lag linkers are a "
            "different instrument again and are not covered here."
        ),
    ),
    "USD_CPURNSA": LinkerConvention(
        currency="USD",
        citi_index="USD_CPURNSA",
        rl_spec=None,
        index_lag=3,
        index_method="daily",
        provenance="market_standard",
        note=(
            "TIPS reference CPI: 3-month lag, daily-interpolated - the same shape as "
            "the usd_zcis swap spec, so USD is the one currency where swap and linker "
            "conventions coincide. rateslib ships no us_gbi spec; use us_gb for the "
            "schedule and set index_lag/index_method explicitly."
        ),
    ),
    "EUR_CPTFEMU": LinkerConvention(
        currency="EUR",
        citi_index="EUR_CPTFEMU",
        rl_spec=None,
        index_lag=3,
        index_method="daily",
        provenance="market_standard",
        note=(
            "OATei/BTPei observe HICPxT with 3-month lag and DAILY interpolation, "
            "while the eur_zcis SWAP spec is non-interpolated. Same index, different "
            "observation."
        ),
    ),
    "SEK_SWCPI": LinkerConvention(
        currency="SEK",
        citi_index="SEK_SWCPI",
        rl_spec="sek_iirs",
        index_lag=3,
        index_method="daily",
        provenance="rateslib_spec",
        note="From rateslib's sek_iirs spec (index_lag 3, index_method 'daily').",
    ),
}


# ------------------------------------------------------------------ #
#                              lookups                               #
# ------------------------------------------------------------------ #


def supported_indices(*, rl_only: bool = False) -> List[str]:
    """Every Citi inflation swap index this package knows conventions for.

    Parameters
    ----------
    rl_only
        Restrict to indices rateslib 2.1.1 can actually represent, i.e. drop the
        quarterly ones.

    Returns
    -------
    list[str]
    """
    keys = sorted(CITI_INFLATION_INDICES)
    if rl_only:
        keys = [k for k in keys if CITI_INFLATION_INDICES[k].rl_representable]
    return keys


def conventions_for(citi_index: str) -> InflationIndexConvention:
    """Look up inflation conventions by Citi index token, case-insensitively.

    Parameters
    ----------
    citi_index
        e.g. ``USD_CPURNSA``, ``GBP_UKRPI``, ``EUR_CPTFEMU``.

    Returns
    -------
    InflationIndexConvention

    Raises
    ------
    UnknownTagError
        If the token is not one of the 17 harvested ``RATES.INFLATION.SWAP``
        children. The message lists them and offers close matches.
    """
    token = str(citi_index).strip().upper()
    if token in CITI_INFLATION_INDICES:
        return CITI_INFLATION_INDICES[token]
    import difflib

    close = difflib.get_close_matches(token, list(CITI_INFLATION_INDICES), n=3, cutoff=0.4)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise UnknownTagError(
        f"No inflation conventions for Citi index {citi_index!r}. "
        f"Known: {', '.join(supported_indices())}.{hint}"
    )


def linker_conventions_for(citi_index: str) -> LinkerConvention:
    """Index-linked BOND conventions for an index, which differ from the swap's.

    Raises
    ------
    UnknownTagError
        If no linker convention is recorded. Recorded for GBP_UKRPI, USD_CPURNSA,
        EUR_CPTFEMU and SEK_SWCPI only - guessing the rest would be exactly the
        error this table exists to prevent.
    """
    token = str(citi_index).strip().upper()
    if token in CITI_LINKER_CONVENTIONS:
        return CITI_LINKER_CONVENTIONS[token]
    raise UnknownTagError(
        f"No index-linked bond convention recorded for {citi_index!r}. "
        f"Recorded: {', '.join(sorted(CITI_LINKER_CONVENTIONS))}. "
        "Pass index_lag and index_method explicitly - do NOT reuse the swap "
        "convention, which differs by a month in GBP and by the interpolation "
        "method in EUR."
    )


def ql_index_for(citi_index: str, handle: Any = None) -> Any:
    """The QuantLib zero inflation index for a Citi index token."""
    return conventions_for(citi_index).ql_index(handle)


# ------------------------------------------------------------------ #
#                        date / lag arithmetic                       #
# ------------------------------------------------------------------ #


def _add_months(d: datetime.date, months: int) -> datetime.date:
    """Shift by whole months, clamping the day into the target month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, _calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def reference_month(
    observation_date: datetime.date | datetime.datetime,
    lag: int,
    *,
    frequency: str = "monthly",
) -> datetime.date:
    """The index period whose fixing an observation on ``observation_date`` reads.

    Parameters
    ----------
    observation_date
        The date on which the index is observed (a swap effective or maturity).
    lag
        Observation lag in months.
    frequency
        ``monthly`` or ``quarterly``. Quarterly rounds down to the start of the
        calendar quarter, which is what QuantLib's ``inflationPeriod`` does.

    Returns
    -------
    datetime.date
        The FIRST DAY of the reference period. Fixing series are keyed on this.
    """
    d = observation_date.date() if isinstance(observation_date, datetime.datetime) else observation_date
    shifted = _add_months(datetime.date(d.year, d.month, 1), -int(lag))
    if frequency == "quarterly":
        q_month = ((shifted.month - 1) // 3) * 3 + 1
        return datetime.date(shifted.year, q_month, 1)
    return shifted


def index_base_month(
    ref_date: datetime.date | datetime.datetime,
    convention: InflationIndexConvention,
) -> datetime.date:
    """The index period supplying ``index_base`` for a curve dated ``ref_date``.

    This is the number the whole curve hangs off. It is the published fixing for
    the period ``lag`` months behind the FIRST OF THE MONTH of ``ref_date`` - not
    behind ``ref_date`` itself, and not the latest published fixing.
    """
    d = ref_date.date() if isinstance(ref_date, datetime.datetime) else ref_date
    return reference_month(
        datetime.date(d.year, d.month, 1),
        convention.observation_lag,
        frequency=convention.frequency,
    )


def required_fixing_months(
    ref_date: datetime.date | datetime.datetime,
    effective: datetime.date | datetime.datetime,
    convention: InflationIndexConvention,
) -> List[datetime.date]:
    """Every published fixing period a spot-starting swap needs, oldest first.

    A ``monthly`` observation needs one fixing; a ``daily`` one needs two, because
    the base is interpolated between the reference month and the month after it.
    Missing the second is the failure QuantLib reports as
    ``Missing <index> fixing for <date>`` and rateslib reports as a UserWarning
    and a **zero index value** - which then calibrates cleanly to a wrong curve.

    Returns
    -------
    list[datetime.date]
        First-of-period dates.
    """
    eff = effective.date() if isinstance(effective, datetime.datetime) else effective
    base = index_base_month(ref_date, convention)
    months = [base]
    obs_base = reference_month(eff, convention.observation_lag, frequency=convention.frequency)
    if obs_base not in months:
        months.append(obs_base)
    if convention.index_method == "daily":
        months.append(_add_months(obs_base, convention.months_per_period))
    out: List[datetime.date] = []
    for m in sorted(months):
        if m not in out:
            out.append(m)
    return out


def tenor_to_years(tenor: str) -> float:
    """Whole-year count for a Citi ZC tenor token.

    Parameters
    ----------
    tenor
        ``1Y``..``40Y``, or ``1M``/``3M``/``6M``.

    Returns
    -------
    float
        Years. Months are returned as fractions and are NOT whole-year swaps -
        the ``1+`` compounding convention still applies but the seasonal factor no
        longer cancels between the two observations.

    Raises
    ------
    ValueError
        On anything else, including ``SPOT``.
    """
    token = str(tenor).strip().upper()
    if token.endswith("Y"):
        return float(token[:-1])
    if token.endswith("M"):
        return float(token[:-1]) / 12.0
    raise ValueError(
        f"{tenor!r} is not a zero-coupon inflation swap tenor. Expected one of "
        f"{', '.join(CITI_ZC_TENORS)} (SPOT is a level, not a tenor)."
    )


def describe(citi_index: str) -> str:
    """One-paragraph human summary of an index's conventions and their provenance."""
    c = conventions_for(citi_index)
    lines = [
        f"{c.citi_index}  ({c.currency})  {c.description}  [{c.bbg_ticker}]",
        f"  observation lag  : {c.observation_lag}M",
        f"  index method     : {c.index_method}  (QuantLib CPI.{c.ql_observation_interpolation_name})",
        f"  index frequency  : {c.frequency}"
        + ("   <- NOT representable in rateslib 2.1.1" if not c.rl_representable else ""),
        f"  publication lag  : {c.publication_lag}M",
        f"  schedule         : {c.fixed_frequency} / {c.convention} / cal {c.calendar} / T+{c.spot_lag}",
        f"  provenance       : {c.provenance}" + ("  (APPROXIMATE)" if c.approximate else ""),
    ]
    if c.note:
        lines.append(f"  note             : {c.note}")
    return "\n".join(lines)
