r"""Per-country fixed-rate government/agency bond conventions.

The ``CVCURVEBOND`` universe spans 18 countries, and the only thing Citi tells
us about a bond is ``ISIN | Description | <measure>``. Everything a pricer needs
- coupon frequency, day count, calendar, settlement lag, ex-dividend rule - has
to come from a convention table keyed on country. This is that table.

Provenance is recorded per country
----------------------------------
rateslib 2.1.1 ships named bond specs for ten currencies. Nine of the eighteen
countries in the Velocity universe have one and are marked
``provenance="rateslib_spec"``; the other nine carry ``"market_standard"`` and a
note saying exactly what is approximate. ``supported_countries()`` and
``approximate_countries()`` let a caller see the split without reading the table.

``sp_gb_10y`` is NOT a Spanish bond spec
----------------------------------------
It looks like one next to ``de_gb`` and ``it_gb``, and it is not::

    >>> rl.defaults.spec["sp_gb_10y"]
    {'calendar': 'tgt', 'currency': 'eur', 'calc_mode': 'eurex_eur',
     'nominal': 100000.0, 'coupon': 6.0}

A 100,000 nominal and a 6% notional coupon is the **Eurex 10Y Spanish bond
FUTURE**, not a cash Bono. Spain is therefore ``market_standard`` here. The same
check was run on every ``*_gb`` spec; the other ten are real bond specs.

Calendars come from QuantLib where rateslib has none
----------------------------------------------------
rateslib ships 14 calendars and none of them is Copenhagen, Mexico City, Sao
Paulo, Shanghai, Seoul or Johannesburg. Rather than substitute a proxy, those
six countries reuse
:func:`~MDP.CitiVelocityExcel.curves.conventions.rl_calendar_from_quantlib`,
exactly as the OIS curve table does.

What is NOT modelled, and would be wrong to pretend otherwise
--------------------------------------------------------------
* **MEX** - MBonos roll every 182 *days*, not semi-annually. Neither library
  expresses a 182-day schedule, so the schedule here is semi-annual and will
  drift from the traded coupon dates by a few days per coupon.
* **JPN** - JGBs under one year are quoted on a *simple* yield in the domestic
  market. Both backends here compound semi-annually, so short JGB yields will
  not tie out to a domestic screen.
* **BRA** - NTN-F yields are quoted as an annually-compounded Business/252 rate.
  The accrual day count is right (``bus252`` / ``ql.Business252(ql.Brazil())``)
  but the compounding here is semi-annual at the coupon frequency, not the
  domestic annual convention - and the two backends do not even agree with each
  other on Bus/252 accrued (see below).
* **CHN** - CGB coupon frequency varies per bond (annual and semi-annual issues
  both exist). Semi-annual is assumed; a bond whose real frequency is annual
  will price wrong.
* Ex-dividend is expressed in *business* days on both backends. ZAF and NZL
  quote their books-closed period in calendar days, so those two carry
  ``ex_div_calendar_days=True`` and get a ``NullCalendar`` on the QuantLib side.
  rateslib has no calendar-day ex-div mode, so the rateslib bond for those two
  is only correct outside the ex-div window.

None of the above is a silent approximation: every one is on the country's
``note`` and :func:`conventions_for` warns nothing, but
:attr:`BondConvention.approximate` is True and callers can refuse.

Accrual day count is NOT the yield day count
---------------------------------------------
This distinction is what closed almost every cross-backend gap. rateslib's bond
calc modes raise the discount factor to a **coupon-period fraction**; QuantLib's
``bondYield`` raises it to ``dayCounter.yearFraction(...) x frequency``. Those
agree when the day count is ActAct(ICMA) and diverge otherwise, so JPN, ZAF, MEX
and BRA accrue on Act/365F, Act/360 and Bus/252 but take their yield exponent
from ActAct(ICMA) via :attr:`BondConvention.ql_yield_day_count`. Measured before
and after, on one bond per country at 99.50 clean, settle 2026-08-06::

    country   accrual dc used for yield    ActAct(ICMA) used for yield
    JPN                  +0.19388 bp                  -0.00004 bp
    ZAF                  +1.00008 bp                  +0.00003 bp
    MEX                 +11.91768 bp                  +0.00005 bp
    BRA                  -6.06998 bp                  +0.81995 bp
    CHE                  -0.00003 bp                  -0.07836 bp   <- keeps 30E/360

Switzerland is the control: forcing ActAct there OPENS a gap, which is how one
can tell this is a real per-country convention and not a fudge factor.

The FINAL coupon period is where they really part company
----------------------------------------------------------
Built across all 2,140 live bonds in the universe at 99.50 clean, the median
absolute yield gap is 0.00003-0.00007 bp in every maturity bucket, and 2,140 of
2,140 build in both backends without a failure. The tail is entirely inside the
last coupon period, where rateslib's ``us_gb_tsy``/``it_gb``/``de_gb``/
``nl_gb``/``se_gb`` calc modes use SIMPLE interest and QuantLib compounds::

    ttm        n      median        p90         max
    <1y      255   0.00007 bp   3.08352 bp   65.80279 bp   <- BTPS 3.1 08/28/2026
    1-2y     237   0.00005 bp   0.27889 bp    1.22130 bp
    2-5y     548   0.00004 bp   0.14566 bp    2.19771 bp   <- BRL
    >5y     1100   0.00004 bp   0.01836 bp    0.98749 bp

Do not read a bond inside its final coupon period out of the QuantLib backend and
compare it with one from the rateslib backend; on a 22-day BTP that is a 66 bp
difference of convention, not of value.

Measured cross-backend residuals, after all of the above
--------------------------------------------------------
On a mid-curve bond per country (5y-20y):

    BRA   +0.820 bp     Bus/252 ACCRUED differs between the backends: 0.986025
                        (rateslib) vs 1.031746 (QuantLib) on BNTNF 10.0
                        01/01/2035. rateslib's calc mode prorates the period
                        cashflow by calendar days, QuantLib counts business days
                        directly, and NEITHER is the domestic NTN-F convention
                        (an annually compounded Bus/252 quote). BRL is
                        indicative only.
    USA   -0.094 bp     deliberate: rateslib us_gb_tsy is the Treasury street
                        convention, QuantLib is plain ICMA. See the USA note.
    ITA   -0.011 bp     residual of it_gb's annual-yield mechanics after the
                        yield_frequency fix; was 2.93 bp before it.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from MDP.CitiVelocityExcel.curves.conventions import rl_calendar_from_quantlib
from MDP.CitiVelocityExcel.errors import UnknownTagError

__all__ = [
    "BondConvention",
    "BOND_CONVENTIONS",
    "UNIVERSE_COUNTRIES",
    "conventions_for",
    "supported_countries",
    "approximate_countries",
    "country_for_currency",
]

_logger = logging.getLogger(__name__)

#: rateslib frequency letter -> (QuantLib Frequency attribute, months per period).
#: Only the four the bond table actually uses are listed; anything else raises.
_FREQUENCY_MAP: Dict[str, Tuple[str, int]] = {
    "a": ("Annual", 12),
    "s": ("Semiannual", 6),
    "q": ("Quarterly", 3),
    "m": ("Monthly", 1),
}

#: Country codes that ``CVCURVEBOND`` populates, in the order the universe lists
#: them. Kept as a constant so a caller can assert the table still covers the
#: harvested universe (``_smoke.py`` does exactly that).
UNIVERSE_COUNTRIES: Tuple[str, ...] = (
    "BRA", "CHE", "CHN", "DEU", "DNK", "ESP", "FRA", "GBR", "ITA",
    "JPN", "KOR", "MEX", "NLD", "NOR", "NZL", "SWE", "USA", "ZAF",
)


def _ql() -> Any:
    import QuantLib as ql  # imported lazily: QuantLib is slow to import

    return ql


def _cal(name: str, *args: Any) -> Callable[[], Any]:
    """A zero-argument QuantLib calendar factory, resolving string enum members."""

    def factory() -> Any:
        ql = _ql()
        cls = getattr(ql, name)
        resolved = [getattr(cls, a) if isinstance(a, str) else a for a in args]
        return cls(*resolved) if resolved else cls()

    return factory


def _dc_actact_isma() -> Callable[[Optional[Any]], Any]:
    """ActAct(ISMA), bound to the coupon schedule when one is available.

    Binding matters only for irregular (stub) periods; on a regular schedule the
    bound and unbound day counters were measured identical to 1e-12 on ytm,
    accrued, BPV, modified duration and convexity.
    """

    def factory(schedule: Optional[Any] = None) -> Any:
        ql = _ql()
        if schedule is None:
            return ql.ActualActual(ql.ActualActual.ISMA)
        return ql.ActualActual(ql.ActualActual.ISMA, schedule)

    return factory


def _dc(name: str, *args: Any) -> Callable[[Optional[Any]], Any]:
    """A schedule-independent QuantLib day counter factory."""

    def factory(schedule: Optional[Any] = None) -> Any:  # noqa: ARG001 - uniform signature
        ql = _ql()
        cls = getattr(ql, name)
        resolved = [getattr(cls, a) if isinstance(a, str) else a for a in args]
        return cls(*resolved) if resolved else cls()

    return factory


def _dc_bus252(calendar_factory: Callable[[], Any]) -> Callable[[Optional[Any]], Any]:
    """Business/252 on a national calendar - Brazil's domestic day count."""

    def factory(schedule: Optional[Any] = None) -> Any:  # noqa: ARG001 - uniform signature
        return _ql().Business252(calendar_factory())

    return factory


# ------------------------------------------------------------------ #
#                            the record                              #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class BondConvention:
    """Everything both backends need to build one country's fixed-rate bonds.

    Attributes
    ----------
    country
        ISO-3166 alpha-3, matching the ``CVCURVEBOND`` universe key.
    currency
        ISO-4217 code of the bond's own currency.
    frequency
        Coupon frequency as a rateslib letter: ``a``/``s``/``q``/``m``.
    yield_frequency
        Compounding frequency the YIELD is quoted at, which is not always the
        coupon frequency. BTPs pay semi-annually and quote an ANNUALLY
        compounded yield; measured on BTPS 3.35 09/15/2033 at 99.50 clean,
        settle 2026-08-06, that is worth 2.93 bp (semi 3.429503%, annual
        3.458907%, rateslib it_gb 3.458796%). Defaults to ``frequency``.
    convention
        Day count in rateslib spelling (``actacticma``, ``act365f``, ``30e360``,
        ``act360``, ``bus252``, ``actacticma_stub365f``).
    ql_day_count
        Factory taking an optional ``ql.Schedule`` and returning the QuantLib
        ``DayCounter`` used for ACCRUAL. The schedule argument exists because
        ActAct (ISMA) needs it to price stub periods correctly.
    ql_yield_day_count
        Factory for the day counter used in the YIELD compounding exponent, when
        that differs from the accrual day counter. It does for every country
        whose accrual is not ActAct(ICMA) but whose yield is still quoted on
        coupon-period fractions - JPN, ZAF, MEX and BRA here. Measured effect of
        getting it wrong (accrual day counter used for the yield too): JPN
        0.194 bp, ZAF 1.000 bp, MEX 11.918 bp, BRA 6.070 bp. Switzerland is the
        counter-example and deliberately keeps 30E/360 for both: forcing
        ActAct(ICMA) there *opens* a 0.078 bp gap. ``None`` means "same as
        ``ql_day_count``".
    ql_calendar
        Zero-argument factory for the QuantLib calendar.
    business_day_convention
        Name of the QuantLib ``BusinessDayConvention`` used for both schedule
        generation and coupon payment. Government bonds are ``Unadjusted``
        almost everywhere: the coupon *date* is not rolled, only the cash.
    settlement_days
        Business days from trade to settlement.
    ex_div_days
        Length of the ex-dividend / books-closed window before a coupon.
    ex_div_calendar_days
        True when that window is quoted in calendar days rather than business
        days. rateslib cannot express this, so those countries' rateslib bonds
        are only correct outside the window.
    eom
        End-of-month roll rule.
    rl_spec
        A rateslib named bond spec when one exists, else ``None`` and the
        explicit fields are used with ``rl_calc_mode``.
    rl_calc_mode
        rateslib yield/accrual calculation mode. Used when ``rl_spec`` is None.
    rl_calendar
        rateslib named calendar when one exists, else ``None`` and the calendar
        is synthesised from ``ql_calendar``'s holiday list.
    rl_stub
        rateslib stub rule for schedule generation.
    provenance
        ``rateslib_spec`` when rateslib supplies the conventions, else
        ``market_standard``.
    note
        What specifically is approximate, when anything is.
    """

    country: str
    currency: str
    frequency: str
    convention: str
    ql_day_count: Callable[[Optional[Any]], Any]
    ql_calendar: Callable[[], Any]
    business_day_convention: str
    settlement_days: int
    ex_div_days: int
    eom: bool
    rl_calc_mode: str
    rl_spec: Optional[str] = None
    rl_calendar: Optional[str] = None
    rl_stub: str = "shortfront"
    ex_div_calendar_days: bool = False
    yield_frequency: Optional[str] = None
    ql_yield_day_count: Optional[Callable[[Optional[Any]], Any]] = None
    provenance: str = "rateslib_spec"
    note: str = ""

    # -- derived --------------------------------------------------------

    @property
    def approximate(self) -> bool:
        """True when the conventions are encoded here rather than library-supplied."""
        return self.provenance != "rateslib_spec"

    @property
    def months_per_period(self) -> int:
        return _FREQUENCY_MAP[self.frequency][1]

    def ql_frequency(self) -> Any:
        """The QuantLib ``Frequency`` enum member for this coupon frequency."""
        return getattr(_ql(), _FREQUENCY_MAP[self.frequency][0])

    def ql_yield_frequency(self) -> Any:
        """The QuantLib ``Frequency`` the yield is COMPOUNDED at."""
        letter = self.yield_frequency or self.frequency
        return getattr(_ql(), _FREQUENCY_MAP[letter][0])

    def ql_yield_day_counter(self, schedule: Optional[Any] = None) -> Any:
        """The QuantLib ``DayCounter`` for the yield exponent."""
        factory = self.ql_yield_day_count or self.ql_day_count
        return factory(schedule)

    def ql_period(self) -> Any:
        """The QuantLib ``Period`` between coupons."""
        ql = _ql()
        return ql.Period(self.months_per_period, ql.Months)

    def ql_bdc(self) -> Any:
        """The QuantLib ``BusinessDayConvention`` enum member."""
        return getattr(_ql(), self.business_day_convention)

    def ql_ex_coupon_calendar(self) -> Any:
        """Calendar used to step back the ex-dividend window.

        A ``NullCalendar`` makes QuantLib count *calendar* days, which is what
        ZAF and NZL quote; every other country counts business days.
        """
        ql = _ql()
        return ql.NullCalendar() if self.ex_div_calendar_days else self.ql_calendar()

    def rl_calendar_object(self) -> Any:
        """The rateslib calendar, synthesising one from QuantLib when needed."""
        import rateslib as rl

        if self.rl_calendar:
            return rl.get_calendar(self.rl_calendar)
        return rl_calendar_from_quantlib(self.ql_calendar())


# ------------------------------------------------------------------ #
#                             the table                              #
# ------------------------------------------------------------------ #

_CONVENTIONS: Tuple[BondConvention, ...] = (
    # -- rateslib-supplied ------------------------------------------- #
    BondConvention(
        country="USA",
        currency="USD",
        frequency="s",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("UnitedStates", "GovernmentBond"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=1,
        eom=True,
        rl_calc_mode="us_gb_tsy",
        rl_spec="us_gb_tsy",
        rl_calendar="nyc",
        note=(
            "us_gb_tsy is the US Treasury STREET convention, which is not the plain ICMA "
            "compounding QuantLib's bondYield implements. Measured on T 4.25 05/31/2033 at "
            "99.50 clean, settle 2026-08-06: rateslib us_gb_tsy 4.333684%, QuantLib 4.334599%, "
            "a 0.091bp gap. rateslib's us_gb spec reproduces QuantLib to 2.8e-7 bp. The street "
            "convention is kept because that is what Citi quotes."
        ),
    ),
    BondConvention(
        country="GBR",
        currency="GBP",
        frequency="s",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("UnitedKingdom"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=7,
        eom=False,
        rl_calc_mode="uk_gb",
        rl_spec="uk_gb",
        rl_calendar="ldn",
        note="Gilts go ex-dividend 7 business days before a coupon.",
    ),
    BondConvention(
        country="DEU",
        currency="EUR",
        frequency="a",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("TARGET"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="de_gb",
        rl_spec="de_gb",
        rl_calendar="tgt",
        rl_stub="longfront",
        note="Bunds take a LONG first stub, unlike every other spec in this table.",
    ),
    BondConvention(
        country="FRA",
        currency="EUR",
        frequency="a",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("TARGET"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="fr_gb",
        rl_spec="fr_gb",
        rl_calendar="tgt",
    ),
    BondConvention(
        country="ITA",
        currency="EUR",
        frequency="s",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("TARGET"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="it_gb",
        rl_spec="it_gb",
        rl_calendar="tgt",
        yield_frequency="a",
        note=(
            "BTPs pay semi-annually but quote an ANNUALLY compounded yield - the other EUR "
            "sovereigns here pay annually. Measured on BTPS 3.35 09/15/2033 at 99.50 clean, "
            "settle 2026-08-06: semi-annual compounding gives 3.429503%, annual 3.458907%, and "
            "rateslib's it_gb 3.458796%. Getting this wrong is a 2.93bp error and a 0.10y "
            "duration error."
        ),
    ),
    BondConvention(
        country="NLD",
        currency="EUR",
        frequency="a",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("TARGET"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="nl_gb",
        rl_spec="nl_gb",
        rl_calendar="tgt",
    ),
    BondConvention(
        country="CHE",
        currency="CHF",
        frequency="a",
        convention="30e360",
        ql_day_count=_dc("Thirty360", "European"),
        ql_calendar=_cal("Switzerland"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="ch_gb",
        rl_spec="ch_gb",
        rl_calendar="zur",
        note="Swiss Confederation bonds accrue 30E/360, not ActAct - the only one here that does.",
    ),
    BondConvention(
        country="SWE",
        currency="SEK",
        frequency="a",
        convention="actacticma",
        ql_day_count=_dc("Thirty360", "European"),
        ql_calendar=_cal("Sweden"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=5,
        eom=False,
        rl_calc_mode="se_gb",
        rl_spec="se_gb",
        rl_calendar="stk",
        note=(
            "rateslib's se_gb spec declares convention='actacticma' but its CALC MODE accrues "
            "30E/360, which is the Swedish market convention. Measured on SGB 2.25 05/11/2035, "
            "settle 2026-08-06: rateslib accrued 0.537500000. QuantLib with ActAct(ISMA) gives "
            "0.542465753 (a 0.005 price-point error) and with 30E/360 gives 0.537500000 exactly, "
            "closing the ytm gap from 0.0011bp to 0.00006bp. The QuantLib day counter here is "
            "therefore 30E/360, deliberately NOT the spec's declared convention."
        ),
    ),
    BondConvention(
        country="NOR",
        currency="NOK",
        frequency="a",
        convention="actacticma_stub365f",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("Norway"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="no_gb",
        rl_spec="no_gb",
        rl_calendar="osl",
        note=(
            "rateslib's no_gb uses actacticma_stub365f (ActAct with an Act/365F stub). QuantLib "
            "has no equivalent, so ql_day_count is plain ActAct(ISMA): the two differ ONLY in a "
            "stub period."
        ),
    ),
    # -- market standard --------------------------------------------- #
    BondConvention(
        country="ESP",
        currency="EUR",
        frequency="a",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("TARGET"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="fr_gb",
        rl_spec=None,
        rl_calendar="tgt",
        provenance="market_standard",
        note=(
            "rateslib ships NO Spanish cash-bond spec. sp_gb_10y looks like one and is the Eurex "
            "10Y Bono FUTURE (nominal 100,000, notional 6% coupon, calc_mode eurex_eur). Bonos "
            "here are annual ActAct(ICMA) T+2 on TARGET with fr_gb yield mechanics."
        ),
    ),
    BondConvention(
        country="JPN",
        currency="JPY",
        frequency="s",
        convention="act365f",
        ql_day_count=_dc("Actual365Fixed"),
        ql_yield_day_count=_dc_actact_isma(),
        ql_calendar=_cal("Japan"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=0,
        eom=False,
        rl_calc_mode="us_gb",
        rl_spec=None,
        rl_calendar="tyo",
        provenance="market_standard",
        note=(
            "JGB accrual is Act/365F on a semi-annual schedule; settlement moved to T+1 in 2019. "
            "The DOMESTIC simple-yield convention used for JGBs under one year is NOT implemented "
            "- short JGB yields from this table will not match a Japanese screen."
        ),
    ),
    BondConvention(
        country="DNK",
        currency="DKK",
        frequency="a",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("Denmark"),
        business_day_convention="Unadjusted",
        settlement_days=2,
        ex_div_days=1,
        eom=False,
        rl_calc_mode="fr_gb",
        rl_spec=None,
        rl_calendar=None,
        provenance="market_standard",
        note=(
            "Danish government bonds: annual ActAct(ICMA), T+2. rateslib ships no DKK bond spec "
            "and no Copenhagen calendar, so the calendar is synthesised from QuantLib's Denmark "
            "holidays."
        ),
    ),
    BondConvention(
        country="NZL",
        currency="NZD",
        frequency="s",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("NewZealand"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=10,
        eom=False,
        rl_calc_mode="uk_gb",
        rl_spec=None,
        rl_calendar="wlg",
        ex_div_calendar_days=True,
        provenance="market_standard",
        note=(
            "NZGBs: semi-annual ActAct(ICMA), T+1, with a 10 CALENDAR-day record date. rateslib "
            "counts ex-div in business days, so the rateslib bond is right only outside the "
            "ex-div window; the QuantLib bond uses a NullCalendar and is right inside it too."
        ),
    ),
    BondConvention(
        country="MEX",
        currency="MXN",
        frequency="s",
        convention="act360",
        ql_day_count=_dc("Actual360"),
        ql_yield_day_count=_dc_actact_isma(),
        ql_calendar=_cal("Mexico"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=0,
        eom=False,
        rl_calc_mode="us_gb",
        rl_spec=None,
        rl_calendar=None,
        provenance="market_standard",
        note=(
            "MBonos roll every 182 DAYS on Act/360, which neither library expresses. The schedule "
            "here is semi-annual and drifts from the traded coupon dates by a few days per "
            "coupon; treat MXN accrued and yields as indicative, not tradeable."
        ),
    ),
    BondConvention(
        country="BRA",
        currency="BRL",
        frequency="s",
        convention="bus252",
        ql_day_count=_dc_bus252(_cal("Brazil")),
        ql_yield_day_count=_dc_actact_isma(),
        ql_calendar=_cal("Brazil"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=0,
        eom=False,
        rl_calc_mode="us_gb",
        rl_spec=None,
        rl_calendar=None,
        provenance="market_standard",
        note=(
            "NTN-F: 10% coupon paid semi-annually, Business/252 on the Brazilian calendar. The "
            "DAY COUNT is right on both backends; the COMPOUNDING is not - the domestic quote is "
            "an annually-compounded Bus/252 rate and both backends here compound semi-annually."
        ),
    ),
    BondConvention(
        country="CHN",
        currency="CNY",
        frequency="s",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("China", "IB"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=0,
        eom=False,
        rl_calc_mode="us_gb",
        rl_spec=None,
        rl_calendar=None,
        provenance="market_standard",
        note=(
            "CGB and policy-bank (SDBC/ADBCH/EXIMCH) paper. Coupon frequency VARIES PER BOND - "
            "both annual and semi-annual issues exist and the CVCURVEBOND description does not "
            "say which. Semi-annual is assumed; an annual-pay bond priced here is simply wrong. "
            "Calendar is the China inter-bank market."
        ),
    ),
    BondConvention(
        country="KOR",
        currency="KRW",
        frequency="s",
        convention="actacticma",
        ql_day_count=_dc_actact_isma(),
        ql_calendar=_cal("SouthKorea", "KRX"),
        business_day_convention="Unadjusted",
        settlement_days=1,
        ex_div_days=0,
        eom=False,
        rl_calc_mode="us_gb",
        rl_spec=None,
        rl_calendar=None,
        provenance="market_standard",
        note=(
            "KTB and MSB (KORMSB) paper: semi-annual, T+1. The Korean domestic yield convention "
            "is semi-annual compounding on ActAct, which is what is used here, but this has NOT "
            "been tied out to a Korean screen."
        ),
    ),
    BondConvention(
        country="ZAF",
        currency="ZAR",
        frequency="s",
        convention="act365f",
        ql_day_count=_dc("Actual365Fixed"),
        ql_yield_day_count=_dc_actact_isma(),
        ql_calendar=_cal("SouthAfrica"),
        business_day_convention="Unadjusted",
        settlement_days=3,
        ex_div_days=10,
        eom=False,
        rl_calc_mode="uk_gb",
        rl_spec=None,
        rl_calendar=None,
        ex_div_calendar_days=True,
        provenance="market_standard",
        note=(
            "SAGBs: semi-annual Act/365F, T+3, books closed 10 CALENDAR days before a coupon. "
            "As for NZL, rateslib counts ex-div in business days and is therefore right only "
            "outside the window."
        ),
    ),
)

BOND_CONVENTIONS: Dict[str, BondConvention] = {c.country: c for c in _CONVENTIONS}

#: Reverse index. Four countries share EUR, so a currency lookup is ambiguous for
#: the euro area and this map deliberately omits it rather than picking one.
_CURRENCY_TO_COUNTRY: Dict[str, str] = {}
for _c in _CONVENTIONS:
    _CURRENCY_TO_COUNTRY.setdefault(_c.currency, _c.country)
_EUR_COUNTRIES: List[str] = sorted(c.country for c in _CONVENTIONS if c.currency == "EUR")
_CURRENCY_TO_COUNTRY.pop("EUR", None)


def supported_countries() -> List[str]:
    """Every country this table can build bonds for."""
    return sorted(BOND_CONVENTIONS)


def approximate_countries() -> List[str]:
    """Countries whose conventions are encoded here rather than library-supplied."""
    return sorted(c.country for c in _CONVENTIONS if c.approximate)


def conventions_for(country: str) -> BondConvention:
    """Look up bond conventions by ISO-3 country code, case-insensitively.

    Parameters
    ----------
    country
        ISO-3166 alpha-3 code as it appears in the ``CVCURVEBOND`` universe key,
        e.g. ``USA``, ``DEU``, ``JPN``.

    Returns
    -------
    BondConvention

    Raises
    ------
    UnknownTagError
        When the country is not in the table, with the closest matches named.
    """
    token = str(country).strip().upper()
    if token in BOND_CONVENTIONS:
        return BOND_CONVENTIONS[token]
    close = difflib.get_close_matches(token, list(BOND_CONVENTIONS), n=3, cutoff=0.4)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise UnknownTagError(
        f"No bond conventions for country {country!r}. Known: {', '.join(supported_countries())}. "
        f"Add a BondConvention to MDP.CitiVelocityExcel.bonds.conventions to extend the table.{hint}"
    )


def country_for_currency(currency: str) -> str:
    """The country whose conventions govern a currency, where that is unique.

    Raises
    ------
    UnknownTagError
        For ``EUR``, which four countries in this table share with *different*
        coupon frequencies (BTPs semi-annual, Bunds/OATs/DSLs/Bonos annual).
        Resolving a euro bond by currency alone would silently mis-schedule it.
    """
    token = str(currency).strip().upper()
    if token == "EUR":
        raise UnknownTagError(
            "EUR does not identify a bond convention: "
            f"{', '.join(_EUR_COUNTRIES)} share it and ITA pays semi-annually while the rest pay "
            "annually. Pass the country instead."
        )
    if token in _CURRENCY_TO_COUNTRY:
        return _CURRENCY_TO_COUNTRY[token]
    raise UnknownTagError(
        f"No bond convention carries currency {currency!r}. "
        f"Known: {', '.join(sorted(_CURRENCY_TO_COUNTRY))} (+ EUR, which is ambiguous)."
    )
