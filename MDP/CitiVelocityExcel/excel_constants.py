r"""Excel/COM constants and frequency vocabulary for the Citi Velocity add-in.

Everything here was established against the live add-in (v1.7.27) and is recorded
in the design spec. Two facts in particular cost real debugging time and are the
reason this module exists rather than the values being inlined:

* **Pending async values arrive as COM ints.** ``#GETTING_DATA`` is
  ``-2146826245`` and ``#N/A`` is ``-2146826246``. A poller that treats
  "non-empty" as "done" reads the sentinel as data - the first proof of concept
  did exactly that.
* **``CVTSHIST`` frequencies are exactly six values.** The desk's intraday
  workbook advertises ``SE10`` (ten-secondly) as the finest granularity for
  ``OIS`` and ``TSY.OTR``, but that describes the *streaming* feed
  (``CVSTREAM``). ``CVTSHIST`` rejects ``SE10`` outright::

      Error: Parameter 'Frequency' must be one of
      "MI01","MI10","HOURLY","DAILY","WEEKLY","MONTHLY".

  which is the ``Frequency`` ``enumValues`` in ``ExcelConfiguration.json``.
  One minute is the finest historical granularity for every family.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

__all__ = [
    "XL_ERRORS",
    "PENDING_SENTINELS",
    "GETTING_DATA_ERR",
    "NA_ERR",
    "VALUE_ERR",
    "NAME_ERR",
    "BUSY_HRESULTS",
    "FREQUENCIES",
    "INTRADAY_FREQUENCIES",
    "PRICE_POINTS",
    "ENTITLED_FUNCTIONS",
    "UNENTITLED_FUNCTIONS",
    "BAD_TAG_PREFIX",
    "EXCEL_EPOCH_ORDINAL",
]

# ------------------------------------------------------------------ #
#                        Excel error sentinels                       #
# ------------------------------------------------------------------ #

GETTING_DATA_ERR: int = -2146826245
NA_ERR: int = -2146826246
VALUE_ERR: int = -2146826273
NAME_ERR: int = -2146826259

XL_ERRORS: Dict[int, str] = {
    -2146826288: "#NULL!",
    -2146826281: "#DIV/0!",
    VALUE_ERR: "#VALUE!",
    -2146826265: "#REF!",
    NAME_ERR: "#NAME?",
    -2146826252: "#NUM!",
    NA_ERR: "#N/A",
    GETTING_DATA_ERR: "#GETTING_DATA",
}

#: Values that mean "the add-in has not answered yet", NOT "no data".
PENDING_SENTINELS: FrozenSet[int] = frozenset({GETTING_DATA_ERR, NA_ERR})

#: ``RPC_E_CALL_REJECTED`` / ``RPC_E_SERVERCALL_RETRYLATER``. Excel raises these
#: while it is busy; they are transient and must be retried, not surfaced.
BUSY_HRESULTS: FrozenSet[int] = frozenset({-2147418111, -2147417846})

#: The literal the add-in writes into a column whose tag it did not recognise.
BAD_TAG_PREFIX: str = "Bad tag"

#: ``datetime.date(1899, 12, 30).toordinal()``. Excel serial 1 is 1900-01-01 and
#: Excel wrongly believes 1900 was a leap year, so this epoch is correct for every
#: serial above 60 - i.e. every date this bridge will ever see.
EXCEL_EPOCH_ORDINAL: int = 693594


# ------------------------------------------------------------------ #
#                     CVTSHIST parameter vocabulary                  #
# ------------------------------------------------------------------ #

#: The complete, exact ``Frequency`` enum. Anything else is rejected by the
#: add-in with a parameter error, including ``SE10`` (see the module docstring).
FREQUENCIES: Tuple[str, ...] = ("MI01", "MI10", "HOURLY", "DAILY", "WEEKLY", "MONTHLY")

#: Frequencies that produce more than one observation per day. The cache keys
#: these separately from daily-and-coarser series - they are never mixed.
INTRADAY_FREQUENCIES: FrozenSet[str] = frozenset({"MI01", "MI10", "HOURLY"})

#: ``PricePoint`` values. ``OHLC`` is meaningful only for ``RATES.FUTURES`` in the
#: rates complex - every other family serves ``CLOSE`` and nothing else.
PRICE_POINTS: Tuple[str, ...] = ("CLOSE", "OPEN", "HIGH", "LOW", "OHLC")


# ------------------------------------------------------------------ #
#                            Entitlements                            #
# ------------------------------------------------------------------ #

#: Exactly what the add-in logs as "Registering functions" for this user. Scope
#: is not a preference - it is fixed by these entitlements.
ENTITLED_FUNCTIONS: FrozenSet[str] = frozenset(
    {
        "CVCURVE",
        "CVCURVEBOND",
        "CVLATEST",
        "CVMETADATA",
        "CVNOW",
        "CVSNAP",
        "CVSTREAM",
        "CVTICK",
        "CVTODAY",
        "CVTSHIST",
    }
)

#: Logged as "User does not meet entitlement requirements for functions".
#: Calling any of these returns an entitlement failure, not data - so every
#: pricer, curve stripper and analytic in this package is built in
#: rateslib/QuantLib from Citi *quotes*.
UNENTITLED_FUNCTIONS: FrozenSet[str] = frozenset(
    {
        "CVCALCDERIVATIVES",
        "CVDCAPFLOOR",
        "CVDCASH",
        "CVDCMSCAPFLOOR",
        "CVDFRA",
        "CVDINFLSWAP",
        "CVDMIDCURVE",
        "CVDSINGLELOOKSPREADOPTION",
        "CVDSWAP",
        "CVDSWAPTION",
        "CVLADDER",
        "CVSCENARIOANALYSIS",
        "CVTAG",
        "CVPORTFOLIOLIST",
        "CVPORTFOLIOFILTER",
        "CVPSNAPSHOTCONSTITUENTS",
        "CVGETPORTSCOOBY",
        "CVGETPORTDATESSCOOBY",
        "CVGETPORTLISTSCOOBY",
        "CVSAVEPORTSCOOBY",
        "CVLATESTSCOOBY",
        "CVSNAPSCOOBY",
        "CVTSHISTSCOOBY",
    }
)
