r"""The 20-entry map between IRSwaps curve names and Citi Velocity OIS index tokens.

Citi identifies its OIS curves by tokens that are not guessable - ``EUR_EUROSTR``
(not ESTR), ``USD_FEDFUND`` (singular), ``MXN_T_FONDEO``, ``DKK_TNDKK``, and three
CCP variants of TONAR. This repo identifies curves as ``<CCY>-<INDEX>-<TENOR>``
with ``-1D`` for overnight-indexed curves. The two vocabularies are different and
neither can be derived from the other, so the mapping is a table and it is pinned
by a test.

Three naming decisions, made deliberately
-----------------------------------------
**``-1D`` on every one of the twenty.** ``USD-SOFR-1D``, ``CHF-SARON-1D``,
``SGD-SORA-1D`` and ``EUR-ESTR-1D`` already exist as literals in this repo and are
reused **exactly**. The remaining sixteen are minted in the same shape. The
alternative was to copy the CME feed's spelling for the handful it happens to
carry (``JPY-TONAR``, ``CAD-CORRA``, ``AUD-AONIA``, ``USD-FEDFUNDS`` - all without
a tenor segment), which would have produced a set that is internally inconsistent
and where ``CHF-SARON-1D`` sits next to ``AUD-AONIA``. Those CME names are one
source's ``Literal``, not a shared registry this source has to join.

**``EUR_EUROSTR`` -> ``EUR-ESTR-1D``.** Every other curve name here uses the
market's name for the index (SOFR, SONIA, SARON, CORRA, TONAR), not a vendor's
token. €STR's market name is ESTR; EUROSTR is Citi's internal spelling. And
``EUR-ESTR-1D`` already occurs in the repo, so this reuses rather than mints.

**The JPY CCP split gets a fourth segment**, ``JPY-TONAR-1D-JSCC`` and
``JPY-TONAR-1D-LCH``, with the unqualified ``JPY-TONAR-1D`` reserved for Citi's
unqualified ``JPY_TONAR``. A four-segment qualified name is the established shape
in this repo (``USD-SOFR-1D-RISK`` is a curve-definition key; ``USD-SOFR-1D-CITIVELO``
and ``USD-SOFR-1D-ERISLIVE`` are CurveStore assets). The JSCC/LCH basis is real -
measured 2026-08-06/07, the two disagree by ~2 bp at 10Y - so they must not
collapse onto one name.

What the harvest measured about these curves
--------------------------------------------
On 2026-08-07, against the live add-in (see
``MDP/CitiVelocityExcel/harvest/live_curve_modes/``):

* all twenty serve a complete 44-tenor **EOD** par grid;
* eighteen serve a complete 44-tenor **one-minute** grid. ``EUR_EONIA`` serves
  none (it stopped on 2025-08-15) and ``JPY_TONAR_JSCC`` serves none at any
  frequency finer than daily;
* ``EUR_EONIA``, ``JPY_TONAR_JSCC`` and ``JPY_TONAR_LCH`` publish no
  ``RATES.OIS.<idx>.FWD.*`` tags, so the published-forward tie-out cannot be run
  on those three.

Those are recorded per curve below as :attr:`CurveNameEntry.modes`, so a caller
can ask what a curve supports without discovering it as an empty frame.
"""

from __future__ import annotations

import dataclasses
import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "CurveNameEntry",
    "CITIVELO_EXCEL_CURVES",
    "CURVE_NAME_BY_CITI_INDEX",
    "CITI_INDEX_BY_CURVE_NAME",
    "curve_name_for_index",
    "citi_index_for_curve_name",
    "supported_curve_names",
    "is_citivelo_excel_curve",
]


@dataclass(frozen=True)
class CurveNameEntry:
    """One row of the map, with what the live harvest found the curve can serve.

    Attributes
    ----------
    citi_index
        The Velocity token, e.g. ``USD_SOFR``.
    curve_name
        The IRSwaps curve name, e.g. ``USD-SOFR-1D``.
    modes
        Which of ``eod`` / ``intraday`` / ``live`` were observed to serve a
        complete par grid on 2026-08-07. This is measurement, not policy: a mode
        absent here is a mode the add-in did not serve on that date, and the
        fetcher still attempts it and reports what it gets.
    has_published_forwards
        Whether ``RATES.OIS.<idx>.FWD.<expiry>.<tenor>`` served. This is the
        independent tie-out data; a curve without it can only be checked against
        its own calibration inputs, which is close to circular.
    note
        Anything a caller would otherwise discover as a surprise.
    """

    citi_index: str
    curve_name: str
    modes: Tuple[str, ...]
    has_published_forwards: bool
    note: str = ""
    local_timezone: str = "America/New_York"

    @property
    def currency(self) -> str:
        return self.curve_name.split("-", 1)[0]

    def supports(self, mode: str) -> bool:
        return str(mode).lower() in self.modes


_ALL = ("eod", "intraday", "live")

CITIVELO_EXCEL_CURVES: Tuple[CurveNameEntry, ...] = (
    CurveNameEntry("USD_SOFR", "USD-SOFR-1D", _ALL, True),
    CurveNameEntry(
        "USD_FEDFUND",
        "USD-FEDFUNDS-1D",
        _ALL,
        True,
        note="Effective Fed Funds OIS. The repo's CME feed spells the same curve "
        "'USD-FEDFUNDS' with no tenor segment; this source uses the -1D form for "
        "consistency with the other nineteen.",
    ),
    CurveNameEntry("EUR_EUROSTR", "EUR-ESTR-1D", _ALL, True),
    CurveNameEntry(
        "EUR_EONIA",
        "EUR-EONIA-1D",
        ("eod",),
        False,
        note="DISCONTINUED. Measured 2026-08-07: the daily series stops at "
        "2025-08-15, there is no one-minute history at all, and no FWD tags. It is "
        "mapped so that a request for it fails with a clear reason rather than an "
        "unknown-curve error. Use EUR-ESTR-1D.",
    ),
    CurveNameEntry("GBP_SONIA", "GBP-SONIA-1D", _ALL, True),
    CurveNameEntry(
        "JPY_TONAR",
        "JPY-TONAR-1D",
        _ALL,
        True,
        note="Citi's unqualified TONAR curve. See also the two CCP-qualified names.",
    ),
    CurveNameEntry(
        "JPY_TONAR_JSCC",
        "JPY-TONAR-1D-JSCC",
        ("eod",),
        False,
        note="EOD ONLY. Measured 2026-08-07: the daily grid serves all 44 tenors "
        "(one business day behind the others), but no one-minute history and no FWD "
        "tags exist. Do not silently substitute JPY-TONAR-1D - the JSCC/LCH basis is real.",
    ),
    CurveNameEntry(
        "JPY_TONAR_LCH",
        "JPY-TONAR-1D-LCH",
        _ALL,
        False,
        note="EOD and intraday serve in full; no FWD tags, so this curve cannot be "
        "tied out against a published forward.",
    ),
    CurveNameEntry("CHF_SARON", "CHF-SARON-1D", _ALL, True),
    CurveNameEntry(
        "CAD_CORRA",
        "CAD-CORRA-1D",
        _ALL,
        True,
        note="CORRA OIS pays SEMI-ANNUALLY, unlike the annual majors.",
    ),
    CurveNameEntry("AUD_AONIA", "AUD-AONIA-1D", _ALL, True),
    CurveNameEntry("NZD_NZIONA", "NZD-NZIONA-1D", _ALL, True),
    CurveNameEntry("NOK_NOWA", "NOK-NOWA-1D", _ALL, True),
    CurveNameEntry("SEK_STINA", "SEK-STINA-1D", _ALL, True),
    CurveNameEntry(
        "DKK_TNDKK",
        "DKK-TNDKK-1D",
        _ALL,
        True,
        note="Conventions are market standard, not rateslib-supplied.",
    ),
    CurveNameEntry(
        "ILS_SHIR",
        "ILS-SHIR-1D",
        _ALL,
        True,
        note="Trades SUNDAY-THURSDAY; the calendar's week mask is Friday/Saturday. "
        "Conventions are market standard, not rateslib-supplied.",
    ),
    CurveNameEntry(
        "MXN_T_FONDEO",
        "MXN-FONDEO-1D",
        _ALL,
        True,
        note="TIIE de Fondeo, the overnight index - NOT 28-day TIIE. The swaps roll "
        "on a 28-day schedule, which rateslib 2.7's mxn_irs expresses natively and "
        "QuantLib approximates as four-weekly, so the two backends legitimately "
        "differ on this curve.",
    ),
    CurveNameEntry(
        "SGD_SORA",
        "SGD-SORA-1D",
        _ALL,
        True,
        note="Pays semi-annually. Conventions are market standard, not rateslib-supplied.",
    ),
    CurveNameEntry(
        "THB_THOR",
        "THB-THOR-1D",
        _ALL,
        True,
        note="Conventions are market standard, not rateslib-supplied.",
    ),
    CurveNameEntry(
        "ZAR_ZARONIA",
        "ZAR-ZARONIA-1D",
        _ALL,
        True,
        note="Rolls quarterly on ACT/365. Conventions are market standard, not "
        "rateslib-supplied.",
    ),
)

#: The zone each curve's own market keeps its business date in.
#:
#: Needed because Citi stamps everything in America/New_York, and for the
#: Asia/Pacific curves that means one trading session straddles two ET dates.
#: Measured on JPY_TONAR, 2026-08-05/07: the session runs 19:00 ET through 06:59
#: ET the next day as one continuous block (the 23:59 print and the 00:00 print
#: are the same number), and it corresponds to Citi's DAILY row for the LATER ET
#: date - ET 08-06 19:00-23:59 last printed 2.6575 against a DAILY 08-07 of
#: 2.6500, while the DAILY 08-06 was 2.6300. Dating an intraday snapshot by its
#: ET calendar date would therefore build a JPY, AUD or NZD curve one business
#: day early for every request in their morning session.
_LOCAL_TIMEZONE: Dict[str, str] = {
    "USD_SOFR": "America/New_York",
    "USD_FEDFUND": "America/New_York",
    "EUR_EUROSTR": "Europe/Berlin",
    "EUR_EONIA": "Europe/Berlin",
    "GBP_SONIA": "Europe/London",
    "JPY_TONAR": "Asia/Tokyo",
    "JPY_TONAR_JSCC": "Asia/Tokyo",
    "JPY_TONAR_LCH": "Asia/Tokyo",
    "CHF_SARON": "Europe/Zurich",
    "CAD_CORRA": "America/Toronto",
    "AUD_AONIA": "Australia/Sydney",
    "NZD_NZIONA": "Pacific/Auckland",
    "NOK_NOWA": "Europe/Oslo",
    "SEK_STINA": "Europe/Stockholm",
    "DKK_TNDKK": "Europe/Copenhagen",
    "ILS_SHIR": "Asia/Jerusalem",
    "MXN_T_FONDEO": "America/Mexico_City",
    "SGD_SORA": "Asia/Singapore",
    "THB_THOR": "Asia/Bangkok",
    "ZAR_ZARONIA": "Africa/Johannesburg",
}

# Attached after the fact rather than repeated in twenty constructors, so the
# table above stays readable as a table and cannot fall out of step with it.
CITIVELO_EXCEL_CURVES = tuple(
    dataclasses.replace(e, local_timezone=_LOCAL_TIMEZONE[e.citi_index])
    for e in CITIVELO_EXCEL_CURVES
)

CURVE_NAME_BY_CITI_INDEX: Dict[str, str] = {e.citi_index: e.curve_name for e in CITIVELO_EXCEL_CURVES}
CITI_INDEX_BY_CURVE_NAME: Dict[str, str] = {e.curve_name: e.citi_index for e in CITIVELO_EXCEL_CURVES}
_ENTRY_BY_CURVE_NAME: Dict[str, CurveNameEntry] = {e.curve_name: e for e in CITIVELO_EXCEL_CURVES}


def supported_curve_names() -> List[str]:
    """Every curve name this source can serve, in map order."""
    return [e.curve_name for e in CITIVELO_EXCEL_CURVES]


def is_citivelo_excel_curve(curve_name: str) -> bool:
    return str(curve_name).strip().upper() in _ENTRY_BY_CURVE_NAME


def entry_for_curve_name(curve_name: str) -> CurveNameEntry:
    """The map row for a curve name, with a suggestion when it is not one of ours."""
    token = str(curve_name).strip().upper()
    entry = _ENTRY_BY_CURVE_NAME.get(token)
    if entry is not None:
        return entry
    close = difflib.get_close_matches(token, list(_ENTRY_BY_CURVE_NAME), n=3, cutoff=0.4)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise KeyError(
        f"'{curve_name}' is not a Citi Velocity Excel curve. This source serves "
        f"{len(CITIVELO_EXCEL_CURVES)} curves: {', '.join(supported_curve_names())}.{hint}"
    )


def citi_index_for_curve_name(curve_name: str) -> str:
    """``'GBP-SONIA-1D'`` -> ``'GBP_SONIA'``."""
    return entry_for_curve_name(curve_name).citi_index


def curve_name_for_index(citi_index: str) -> str:
    """``'GBP_SONIA'`` -> ``'GBP-SONIA-1D'``."""
    token = str(citi_index).strip().upper()
    name = CURVE_NAME_BY_CITI_INDEX.get(token)
    if name is not None:
        return name
    close = difflib.get_close_matches(token, list(CURVE_NAME_BY_CITI_INDEX), n=3, cutoff=0.4)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise KeyError(
        f"'{citi_index}' is not a Citi Velocity OIS index token. Known: "
        f"{', '.join(sorted(CURVE_NAME_BY_CITI_INDEX))}.{hint}"
    )
