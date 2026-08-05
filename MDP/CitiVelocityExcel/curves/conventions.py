r"""Per-currency conventions for the 20 Citi Velocity RFR OIS curves.

Citi identifies its OIS curves by an index token that is **not guessable**:
``EUR_EUROSTR`` (not ESTR), ``USD_FEDFUND`` (singular), ``JPY_TONAR_JSCC`` and
``JPY_TONAR_LCH`` (CCP-split), ``DKK_TNDKK``, ``MXN_T_FONDEO``. This table maps
each of those tokens onto everything both backends need.

Two honesty rules are built into the table
------------------------------------------
**Provenance is recorded per curve.** rateslib 2.1.1 ships named specs for ten of
these currencies (``usd_irs``, ``eur_irs``, ``gbp_irs``, ``jpy_irs``, ``chf_irs``,
``cad_irs``, ``aud_irs``, ``nzd_irs``, ``nok_irs``, ``sek_irs``). For the other
six - DKK, ILS, MXN, SGD, THB, ZAR - the schedule conventions here are market
standard rather than library-supplied, and every one of them carries
``provenance="market_standard"`` plus a note saying what specifically is
approximate. Builders warn once per curve when they use one.

**Holiday calendars come from QuantLib, not from a proxy.** rateslib 2.1.1 ships
14 calendars (``nyc tgt ldn tyo zur tro syd wlg osl stk mum fed bus all``) and
none of them is Denmark, Israel, Mexico, Singapore, Thailand or South Africa.
Rather than silently substituting TARGET for Copenhagen, :func:`rl_calendar_from_quantlib`
builds a real :class:`rateslib.Cal` from QuantLib's holiday list for that country.
Israel matters most: it trades Sunday-Thursday, so its week mask is Friday and
Saturday, and a Monday-Friday proxy would misdate every single roll.
"""

from __future__ import annotations

import datetime
import functools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from MDP.CitiVelocityExcel.errors import UnknownTagError

__all__ = [
    "CurveConvention",
    "CITI_OIS_CONVENTIONS",
    "conventions_for",
    "supported_indices",
    "rl_calendar_from_quantlib",
    "ql_calendar_for",
    "ql_index_for",
]

_logger = logging.getLogger(__name__)

#: Span over which QuantLib holiday lists are materialised into rateslib calendars.
#: Wide enough for a 40Y tenor off a 2020 start, which is the deepest point the
#: Velocity tenor axis reaches.
_CAL_START = datetime.date(1990, 1, 1)
_CAL_END = datetime.date(2085, 12, 31)

#: Monday==0. The default weekend; overridden per curve where the week differs.
_MON_FRI_WEEKEND: Tuple[int, ...] = (5, 6)
#: Israel (and the wider Middle East convention Citi quotes ILS on).
_FRI_SAT_WEEKEND: Tuple[int, ...] = (4, 5)


@dataclass(frozen=True)
class CurveConvention:
    """Everything both backends need to strip one Citi OIS curve.

    Attributes
    ----------
    citi_index
        The Velocity token, e.g. ``USD_SOFR``. This is the identifier the tag
        grammar uses and the only one that is authoritative.
    currency
        ISO currency code.
    rl_spec
        A rateslib named spec (``usd_irs`` ...) when one exists for this
        currency, else ``None`` and the explicit fields below are used.
    fixed_frequency
        rateslib frequency letter for the fixed leg: ``a`` annual, ``s``
        semi-annual, ``q`` quarterly, ``m`` monthly.
    convention
        Fixed-leg day count in rateslib spelling (``act360``/``act365f``).
    spot_lag
        Business days from trade to effective.
    rl_calendar
        A rateslib calendar name when one exists, else ``None`` - in which case
        :func:`rl_calendar_from_quantlib` synthesises one from ``ql_calendar``.
    ql_calendar
        A zero-argument factory for the QuantLib calendar.
    ql_index
        A factory taking a ``ql.YieldTermStructureHandle`` and returning the
        QuantLib overnight index.
    provenance
        ``rateslib_spec`` when rateslib supplies the conventions,
        ``market_standard`` when they are encoded here from market convention.
    note
        What specifically is approximate, when anything is.
    stale
        True for curves that exist but are no longer maintained.
    """

    citi_index: str
    currency: str
    rl_spec: Optional[str]
    fixed_frequency: str
    convention: str
    spot_lag: int
    rl_calendar: Optional[str]
    ql_calendar: Callable[[], Any]
    ql_index: Callable[[Any], Any]
    provenance: str = "rateslib_spec"
    note: str = ""
    stale: bool = False
    weekend: Tuple[int, ...] = _MON_FRI_WEEKEND
    curve_id: str = ""

    def __post_init__(self) -> None:
        if not self.curve_id:
            object.__setattr__(self, "curve_id", f"{self.citi_index.replace('_', '-')}-CITIVELO")

    @property
    def approximate(self) -> bool:
        return self.provenance != "rateslib_spec"

    def rl_calendar_object(self) -> Any:
        """The rateslib calendar for this curve, synthesising one if needed."""
        import rateslib as rl

        if self.rl_calendar:
            return rl.get_calendar(self.rl_calendar)
        return rl_calendar_from_quantlib(self.ql_calendar(), weekend=self.weekend)


# ------------------------------------------------------------------ #
#                       QuantLib helper factories                    #
# ------------------------------------------------------------------ #


def _ql():
    import QuantLib as ql  # imported lazily: QuantLib is slow to import

    return ql


def _cal(name: str, *args: Any) -> Callable[[], Any]:
    def factory() -> Any:
        ql = _ql()
        cls = getattr(ql, name)
        resolved = [getattr(cls, a) if isinstance(a, str) else a for a in args]
        return cls(*resolved) if resolved else cls()

    return factory


def _named_index(name: str) -> Callable[[Any], Any]:
    def factory(handle: Any) -> Any:
        ql = _ql()
        return getattr(ql, name)(handle)

    return factory


def _generic_index(
    name: str,
    currency: str,
    calendar_factory: Callable[[], Any],
    day_count: str,
) -> Callable[[Any], Any]:
    """An overnight index QuantLib does not ship a class for.

    ``SORA``, ``NOWA``, ``STINA``, ``TNDKK``, ``SHIR`` and ``T_FONDEO`` have no
    QuantLib class, so they are assembled from ``ql.OvernightIndex`` directly.
    Behaviourally identical to the shipped classes - those are thin subclasses
    that only pin the name, currency, calendar and day count.
    """

    def factory(handle: Any) -> Any:
        ql = _ql()
        ccy = getattr(ql, f"{currency}Currency")()
        dc = getattr(ql, day_count)()
        return ql.OvernightIndex(name, 0, ccy, calendar_factory(), dc, handle)

    return factory


@functools.lru_cache(maxsize=32)
def rl_calendar_from_quantlib(
    ql_calendar: Any,
    *,
    weekend: Tuple[int, ...] = _MON_FRI_WEEKEND,
    start: datetime.date = _CAL_START,
    end: datetime.date = _CAL_END,
) -> Any:
    """Build a :class:`rateslib.Cal` from a QuantLib calendar's holiday list.

    rateslib 2.1.1 ships 14 calendars and none of them covers DKK, ILS, MXN, SGD,
    THB or ZAR. Substituting a proxy (TARGET for Copenhagen, say) misdates rolls
    quietly; QuantLib has the real holiday data for every one of these countries,
    so it is used as the source of truth and the calendar is materialised once.
    """
    import rateslib as rl

    ql = _ql()
    holidays: List[datetime.date] = []
    d0 = ql.Date(start.day, start.month, start.year)
    d1 = ql.Date(end.day, end.month, end.year)
    for d in ql.Calendar.holidayList(ql_calendar, d0, d1, False):
        holidays.append(datetime.date(d.year(), d.month(), d.dayOfMonth()))
    return rl.Cal([datetime.datetime(h.year, h.month, h.day) for h in holidays], list(weekend))


def ql_calendar_for(citi_index: str) -> Any:
    """The QuantLib calendar for a Citi OIS index token."""
    return conventions_for(citi_index).ql_calendar()


def ql_index_for(citi_index: str, handle: Any) -> Any:
    """The QuantLib overnight index for a Citi OIS index token."""
    return conventions_for(citi_index).ql_index(handle)


# ------------------------------------------------------------------ #
#                            the table                               #
# ------------------------------------------------------------------ #

_CONVENTIONS: Tuple[CurveConvention, ...] = (
    CurveConvention(
        citi_index="USD_SOFR",
        currency="USD",
        rl_spec="usd_irs",
        fixed_frequency="a",
        convention="act360",
        spot_lag=2,
        rl_calendar="nyc",
        ql_calendar=_cal("UnitedStates", "GovernmentBond"),
        ql_index=_named_index("Sofr"),
    ),
    CurveConvention(
        citi_index="USD_FEDFUND",
        currency="USD",
        rl_spec="usd_irs",
        fixed_frequency="a",
        convention="act360",
        spot_lag=2,
        rl_calendar="nyc",
        ql_calendar=_cal("UnitedStates", "GovernmentBond"),
        ql_index=_named_index("FedFunds"),
        note="Effective Fed Funds OIS. Same schedule conventions as SOFR; the index differs.",
    ),
    CurveConvention(
        citi_index="EUR_EUROSTR",
        currency="EUR",
        rl_spec="eur_irs",
        fixed_frequency="a",
        convention="act360",
        spot_lag=2,
        rl_calendar="tgt",
        ql_calendar=_cal("TARGET"),
        ql_index=_named_index("Estr"),
    ),
    CurveConvention(
        citi_index="EUR_EONIA",
        currency="EUR",
        rl_spec="eur_irs",
        fixed_frequency="a",
        convention="act360",
        spot_lag=2,
        rl_calendar="tgt",
        ql_calendar=_cal("TARGET"),
        ql_index=_named_index("Eonia"),
        stale=True,
        note="EONIA was discontinued; this curve stops roughly a year back. Use EUR_EUROSTR.",
    ),
    CurveConvention(
        citi_index="GBP_SONIA",
        currency="GBP",
        rl_spec="gbp_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=0,
        rl_calendar="ldn",
        ql_calendar=_cal("UnitedKingdom"),
        ql_index=_named_index("Sonia"),
        note="SONIA settles same day (T+0), unlike every other curve in this table.",
    ),
    CurveConvention(
        citi_index="JPY_TONAR",
        currency="JPY",
        rl_spec="jpy_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar="tyo",
        ql_calendar=_cal("Japan"),
        ql_index=_named_index("Tonar"),
        note="Uncleared/legacy TONAR. Citi also publishes CCP-split JPY_TONAR_JSCC and JPY_TONAR_LCH.",
    ),
    CurveConvention(
        citi_index="JPY_TONAR_JSCC",
        currency="JPY",
        rl_spec="jpy_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar="tyo",
        ql_calendar=_cal("Japan"),
        ql_index=_named_index("Tonar"),
        note="JSCC-cleared TONAR. The JSCC/LCH basis is real; do not treat the two as interchangeable.",
    ),
    CurveConvention(
        citi_index="JPY_TONAR_LCH",
        currency="JPY",
        rl_spec="jpy_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar="tyo",
        ql_calendar=_cal("Japan"),
        ql_index=_named_index("Tonar"),
        note="LCH-cleared TONAR. The JSCC/LCH basis is real; do not treat the two as interchangeable.",
    ),
    CurveConvention(
        citi_index="CHF_SARON",
        currency="CHF",
        rl_spec="chf_irs",
        fixed_frequency="a",
        convention="act360",
        spot_lag=2,
        rl_calendar="zur",
        ql_calendar=_cal("Switzerland"),
        ql_index=_named_index("Saron"),
    ),
    CurveConvention(
        citi_index="CAD_CORRA",
        currency="CAD",
        rl_spec="cad_irs",
        fixed_frequency="s",
        convention="act365f",
        spot_lag=1,
        rl_calendar="tro",
        ql_calendar=_cal("Canada"),
        ql_index=_named_index("Corra"),
        note="CORRA OIS pays SEMI-ANNUALLY, unlike the annual majors.",
    ),
    CurveConvention(
        citi_index="AUD_AONIA",
        currency="AUD",
        rl_spec="aud_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar="syd",
        ql_calendar=_cal("Australia"),
        ql_index=_named_index("Aonia"),
    ),
    CurveConvention(
        citi_index="NZD_NZIONA",
        currency="NZD",
        rl_spec="nzd_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar="wlg",
        ql_calendar=_cal("NewZealand"),
        ql_index=_named_index("Nzocr"),
        note="Citi's NZIONA maps to QuantLib's Nzocr class.",
    ),
    CurveConvention(
        citi_index="NOK_NOWA",
        currency="NOK",
        rl_spec="nok_irs",
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar="osl",
        ql_calendar=_cal("Norway"),
        ql_index=_generic_index("NOWA", "NOK", _cal("Norway"), "Actual365Fixed"),
        note="QuantLib ships no NOWA class; the index is assembled from ql.OvernightIndex.",
    ),
    CurveConvention(
        citi_index="SEK_STINA",
        currency="SEK",
        rl_spec="sek_irs",
        fixed_frequency="a",
        convention="act360",
        spot_lag=1,
        rl_calendar="stk",
        ql_calendar=_cal("Sweden"),
        ql_index=_generic_index("STINA", "SEK", _cal("Sweden"), "Actual360"),
        note=(
            "STINA references STIBOR T/N, not SWESTR. ql.Swestr is deliberately NOT used here - "
            "the two are different indices and the basis between them is real."
        ),
    ),
    CurveConvention(
        citi_index="DKK_TNDKK",
        currency="DKK",
        rl_spec=None,
        fixed_frequency="a",
        convention="act360",
        spot_lag=2,
        rl_calendar=None,
        ql_calendar=_cal("Denmark"),
        ql_index=_generic_index("TNDKK", "DKK", _cal("Denmark"), "Actual360"),
        provenance="market_standard",
        note=(
            "DKK T/N OIS. rateslib ships no DKK spec and no Copenhagen calendar, so the schedule "
            "is market standard (annual, ACT/360, T+2) and the calendar is synthesised from "
            "QuantLib's Denmark holidays. ql.Destr is not used: TNDKK is the T/N index."
        ),
    ),
    CurveConvention(
        citi_index="ILS_SHIR",
        currency="ILS",
        rl_spec=None,
        fixed_frequency="a",
        convention="act365f",
        spot_lag=2,
        rl_calendar=None,
        ql_calendar=_cal("Israel"),
        ql_index=_generic_index("SHIR", "ILS", _cal("Israel"), "Actual365Fixed"),
        provenance="market_standard",
        weekend=_FRI_SAT_WEEKEND,
        note=(
            "ILS trades SUNDAY-THURSDAY: the week mask is Friday/Saturday, not Saturday/Sunday. "
            "A Monday-Friday calendar misdates every roll on this curve. Schedule conventions "
            "are market standard, not library-supplied."
        ),
    ),
    CurveConvention(
        citi_index="MXN_T_FONDEO",
        currency="MXN",
        rl_spec=None,
        fixed_frequency="m",
        convention="act360",
        spot_lag=1,
        rl_calendar=None,
        ql_calendar=_cal("Mexico"),
        ql_index=_generic_index("TIIE_FONDEO", "MXN", _cal("Mexico"), "Actual360"),
        provenance="market_standard",
        note=(
            "MXN Fondeo swaps roll on a 28-DAY schedule, which neither rateslib nor QuantLib "
            "expresses directly; monthly is the closest available frequency and will differ from "
            "the traded schedule by a few days per coupon. Treat MXN levels as indicative."
        ),
    ),
    CurveConvention(
        citi_index="SGD_SORA",
        currency="SGD",
        rl_spec=None,
        fixed_frequency="s",
        convention="act365f",
        spot_lag=2,
        rl_calendar=None,
        ql_calendar=_cal("Singapore"),
        ql_index=_generic_index("SORA", "SGD", _cal("Singapore"), "Actual365Fixed"),
        provenance="market_standard",
        note="SGD SORA OIS pays semi-annually. Schedule conventions are market standard.",
    ),
    CurveConvention(
        citi_index="THB_THOR",
        currency="THB",
        rl_spec=None,
        fixed_frequency="s",
        convention="act365f",
        spot_lag=2,
        rl_calendar=None,
        ql_calendar=_cal("Thailand"),
        ql_index=_generic_index("THOR", "THB", _cal("Thailand"), "Actual365Fixed"),
        provenance="market_standard",
        note="THB THOR OIS. Schedule conventions are market standard, not library-supplied.",
    ),
    CurveConvention(
        citi_index="ZAR_ZARONIA",
        currency="ZAR",
        rl_spec=None,
        fixed_frequency="q",
        convention="act365f",
        spot_lag=2,
        rl_calendar=None,
        ql_calendar=_cal("SouthAfrica"),
        ql_index=_generic_index("ZARONIA", "ZAR", _cal("SouthAfrica"), "Actual365Fixed"),
        provenance="market_standard",
        note="ZAR swaps roll quarterly on ACT/365. Schedule conventions are market standard.",
    ),
)

CITI_OIS_CONVENTIONS: Dict[str, CurveConvention] = {c.citi_index: c for c in _CONVENTIONS}


def supported_indices() -> List[str]:
    """Every Citi OIS index token this package can build a curve for."""
    return sorted(CITI_OIS_CONVENTIONS)


def conventions_for(citi_index: str) -> CurveConvention:
    """Look up conventions by Citi index token, case-insensitively."""
    token = str(citi_index).strip().upper()
    if token in CITI_OIS_CONVENTIONS:
        return CITI_OIS_CONVENTIONS[token]
    import difflib

    close = difflib.get_close_matches(token, list(CITI_OIS_CONVENTIONS), n=3, cutoff=0.4)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise UnknownTagError(
        f"No curve conventions for Citi OIS index {citi_index!r}. "
        f"Known: {', '.join(supported_indices())}.{hint}"
    )
