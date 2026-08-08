r"""What Citi serves for a bond, what this repo calls it, and which one you got.

Citi Velocity publishes **thirteen** values per bond. That is not a guess: it is
the result of exhaustive ``CVTSHIST`` probing over the whole 2,162-ISIN universe,
committed as ``catalog/bond_tags_validated.json`` and ``bond_tags_validated2.json``
(16,288 validated tags in total). Coverage is per-bond and very uneven - the
counts below were re-derived from those two files:

======================  ==============  ========  ==================
Citi value              ISINs serving   of 2,162  of the 349 US GOVT
======================  ==============  ========  ==================
``PRICE``                       2,105     97.4%                  349
``YIELD``                       2,103     97.3%                  349
``DURATION``                    2,097     97.0%                  349
``SPREAD_TSY``                  1,803     83.4%                  349
``DV01``                        1,656     76.6%                  305
``OAS``                         1,401     64.8%                  304
``ASW_4_AUD``                   1,120     51.8%                  348
``ASW_4_GBP``                   1,110     51.3%                    0
``ASW_4_USD``                   1,081     50.0%                  253
``ASW_4_CHF``                     689     31.9%                    0
``ASW_4_EUR``                     418     19.3%                    0
``CAS``                           381     17.6%                    0
``ASW_4_JPY``                     324     15.0%                   56
======================  ==============  ========  ==================

The last column is why the default value set is chosen against the US universe
rather than against the whole one: ``ASW_4_AUD`` is the leg almost every US
Treasury carries and ``ASW_4_JPY`` is the rarest value Citi publishes at all.

``CAS`` serves 381 ISINs (measured ``CND1000113G9`` = 43.4983, ``KR10350172C8`` =
44.2101) but **no US Treasury**: exactly one US ISIN in the universe carries it,
``US3133EPSW68`` (FFCB 4.5 08/14/2026, asset type AGENCY). Addressable, never
assumed present.

The sweep is not complete, and that matters
-------------------------------------------
It covered **2,147 of the 2,162** ISINs. The fifteen it missed - thirteen Canadian
(``CND0000002K8`` and siblings) and two Italian (``IT0005680753``,
``IT0005707689``) - have zero validated tags, which is *not* the same statement as
"Citi serves nothing for them". Anything reading per-bond coverage has to keep the
two apart; see :func:`coverage_is_validated`.

Availability is window-dependent, not a flat boolean
----------------------------------------------------
``OAS`` returned **nothing over a one-week window and a full history over five
years** (``catalog/bond_values2.json``, ``valid_5y_only``). ``ASW_4_JPY`` behaved
the same way. So "does Citi serve V for bond I" depends on the window asked for,
which is why :class:`ValueSpec` carries a mode capability rather than a flag, and
why a value absent from a short window is reported as *absent* rather than as
*unsupported*.

Quote or compute
----------------
Velocity is a quote service - no ``CVD*`` pricer is entitled - so anything Citi
does not publish is rebuilt locally in rateslib 2.7.1 / QuantLib 1.41 from the
quote it does publish. Both routes reach the same ``FixedRateBondValue``, and
which one produced a given number is recorded on the pricer's metadata under
:data:`PROVENANCE_KEY` rather than left to be inferred from the source name.

.. warning::

   Four of the mappings below are **hypotheses, not measurements**, and are
   marked ``verified=False``. The distinctions they turn on are exactly the ones
   that produce a confident wrong number:

   * ``PRICE`` clean or dirty - worth up to 3.18 price points on the calibration
     set, which spans accrued 0.0163 to 3.1844.
   * ``DURATION`` modified or Macaulay - they differ by ``(1 + y/f)``, roughly
     2% at current yields.
   * ``DV01`` per 100 face or per million, and its sign.
   * ``ASW_4_USD`` which asset-swap variant ``_4_`` denotes - par-par, market
     value, or yield-yield.

   Settling them needs one live fetch of a ``(PRICE, YIELD, DURATION, DV01)``
   tuple for bonds whose accrued differs sharply. ``scripts/citivelo_bond_calibration.py``
   does exactly that and rewrites this table's status. Until it has run, the
   source records the interpretation it used in the provenance so a wrong
   reading is traceable rather than invisible; see
   ``docs/citivelo_bonds_and_swapspreads_decisions.md`` (D4).
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "ASW_CURRENCY_VALUES",
    "CITI_BOND_VALUES",
    "COVERAGE_KEY",
    "FAILURES_KEY",
    "PROVENANCE_KEY",
    "QUOTED_KEY",
    "NoQuotedPriceError",
    "Provenance",
    "QuoteNotServedError",
    "StalePriceError",
    "ValueSpec",
    "asw_value_for_currency",
    "computed_provenance",
    "coverage_is_validated",
    "coverage_of",
    "failures_of",
    "frb_value_for",
    "is_velocity_meta",
    "provenance_of",
    "quoted_provenance",
    "quoted_value_of",
    "require_quoted",
    "spec_for",
    "unverified_values",
]

#: Where the Velocity source stashes per-value provenance on a pricer's
#: ``meta_data``. Read it with :func:`provenance_of` rather than by key, so the
#: layout can change without breaking callers.
#:
#: The book is keyed by the **Citi value token** for a number Citi published
#: (``PRICE``, ``SPREAD_TSY``, ``ASW_4_USD``) and by the **FixedRateBondValue
#: member name** for a number this repo computed (``YTM``, ``MOD_DURATION``).
#: The two namespaces overlap only where they mean the same thing, and the
#: split is deliberate: ``YIELD`` is what Citi published and ``YTM`` is what
#: ``FRB_YTM`` returns, and on this source those are *different numbers* -
#: the pricer is built from ``PRICE`` and re-solves its own yield. Recording
#: ``YTM`` as "quoted" because ``YIELD`` happened to be in the same response
#: would be a false audit trail.
PROVENANCE_KEY = "citivelo_provenance"

#: Where the Velocity source stashes Citi's own published numbers, keyed by the
#: Citi value token exactly as it appears in ``RATES.BOND.<ISIN>.<value>``. Read
#: it with :func:`quoted_value_of` / :func:`require_quoted`.
#:
#: Every number Citi served is kept, including the ones the pricer does not use
#: (``YIELD``, ``DURATION``, ``DV01``). That is what makes
#: ``scripts/citivelo_bond_calibration.py`` possible without a second fetch, and
#: what lets a caller compare Citi's duration against the locally computed one
#: instead of taking either on faith.
QUOTED_KEY = "citivelo_quoted"

#: Where the Velocity source records what it asked for and what came back:
#: ``{"serves": [...], "requested": [...], "unavailable": [...], "empty": [...],
#: "failed": [...], "validated": bool}``, the lists keyed by Citi value token.
#: ``unavailable``, ``empty`` and ``failed`` are three different answers and are
#: never merged - see :func:`coverage_of`.
COVERAGE_KEY = "citivelo_coverage"

#: Per-value transport failure reasons, ``{citi_value: reason}``, stored beside
#: the coverage book. ``"bad tag"``, ``"#NAME?"``, ``"no column"`` and the COM
#: disconnect text all land here; "the window held no rows" does NOT, because that
#: is the market, not the transport. Read with :func:`failures_of`.
FAILURES_KEY = "citivelo_failures"


class QuoteNotServedError(ValueError):
    """A quote-only value was asked for and no Citi number backs it.

    A ``ValueError`` subclass so existing broad handlers still catch it, and its
    own type so a caller can tell "Citi did not serve this" from "you passed a
    bad argument". The causes are distinguished in the message by
    :func:`require_quoted`, because they have different fixes.
    """


class NoQuotedPriceError(ValueError):
    """This bond cannot produce an honest pricer out of this window's quotes.

    Its own type, and a narrow one, so the ``FixedRateBondsMDP`` branch can drop
    the one bond and keep the basket without also swallowing a programming error.
    ``build_pricer_args`` raises plain ``ValueError`` for an unknown backend and
    ``float()`` raises it for a non-numeric cell; catching the base class there
    presented "every bond in the basket hit a bug" as "Citi had no data".
    """


class StalePriceError(NoQuotedPriceError):
    """PRICE last printed materially before the rest of the same response.

    A subclass of :class:`NoQuotedPriceError` because the caller's options are the
    same - drop the bond, or ask for a different instant - and because a warm must
    treat the two identically. See ``build_pricer_args`` for why the default is to
    refuse rather than to price a stale number.
    """


@dataclasses.dataclass(frozen=True)
class ValueSpec:
    """One Citi bond value: what it is called here, its units, and its standing.

    Attributes
    ----------
    citi
        The tag suffix, e.g. ``SPREAD_TSY`` in ``RATES.BOND.<ISIN>.SPREAD_TSY``.
    frb
        The :class:`~Query.FixedRateBonds.FixedRateBondValue.FixedRateBondValue`
        member this maps onto. ``None`` when Citi serves something the repo has
        no home for and a new member was added.
    unit
        ``price_points``, ``percent``, ``basis_points``, ``years`` or
        ``currency_per_bp``.
    verified
        ``True`` only where the interpretation has been measured against Citi's
        own numbers. ``False`` means the mapping is the obvious reading and has
        not yet been checked - see the module warning.
    note
        What specifically is unverified, or how the reading was established.
    """

    citi: str
    frb: Optional[str]
    unit: str
    verified: bool
    note: str = ""

    @property
    def is_new(self) -> bool:
        """Whether this value needed a new ``FixedRateBondValue`` member."""
        return self.frb in _NEW_FRB_VALUES


#: FRB value members that did not exist before the Velocity source and were
#: added because Citi publishes something the repo had nowhere to put.
_NEW_FRB_VALUES = frozenset({"SPREAD_TSY", "OAS", "ASW_SPREAD", "CAS"})


_SPECS: Tuple[ValueSpec, ...] = (
    ValueSpec(
        citi="PRICE",
        frb="CLEAN_PRICE",
        unit="price_points",
        verified=False,
        note=(
            "Read as the CLEAN price per 100 face, which is how every government "
            "bond market quotes. UNVERIFIED: if it is in fact dirty, every "
            "downstream yield is wrong by the accrued interest, which on the "
            "calibration set runs from 0.0163 to 3.1844 price points. "
            "Discriminated by pricing a high-accrued and a low-accrued bond and "
            "seeing which reading reproduces Citi's own YIELD."
        ),
    ),
    ValueSpec(
        citi="YIELD",
        frb="YTM",
        unit="percent",
        verified=False,
        note=(
            "Yield to maturity in percent. UNVERIFIED in two respects: the "
            "compounding basis (street convention semi-annual for USTs, but "
            "annual for BTPs - conventions.py already separates yield_frequency "
            "from coupon frequency for exactly this reason), and whether Citi "
            "quotes yield-to-maturity or yield-to-worst on callables."
        ),
    ),
    ValueSpec(
        citi="DURATION",
        frb="MOD_DURATION",
        unit="years",
        verified=False,
        note=(
            "Read as MODIFIED duration. UNVERIFIED: Macaulay and modified differ "
            "by (1 + y/f) - about 2% at current yields - and the tag name does "
            "not say which. Both are computed locally by ql_bond_metrics "
            "('mod_duration' and 'macaulay'), so the calibration compares Citi's "
            "number against both and the closer one wins."
        ),
    ),
    ValueSpec(
        citi="DV01",
        frb="DV01",
        unit="currency_per_bp",
        verified=False,
        note=(
            "UNVERIFIED in scale and sign. This package reports bps and dv01 "
            "POSITIVE for a long on both backends (QuantLib's raw "
            "basisPointValue is negative and is abs()'d once, in ql_bonds). "
            "Citi's sign convention is not known, nor whether the notional is "
            "100 face or a million. Both are single multiplicative facts the "
            "calibration settles at once."
        ),
    ),
    ValueSpec(
        citi="SPREAD_TSY",
        frb="SPREAD_TSY",
        unit="basis_points",
        verified=False,
        note=(
            "Spread to the Treasury benchmark, in bp. NEW value - the repo had "
            "no home for it. UNVERIFIED which benchmark Citi picks "
            "(interpolated on the curve, or the nearest on-the-run), which "
            "matters most for off-the-run bonds between two benchmark points. "
            "Quote-only: not recomputed locally, because reproducing it would "
            "require reproducing Citi's benchmark choice."
        ),
    ),
    ValueSpec(
        citi="OAS",
        frb="OAS",
        unit="basis_points",
        verified=False,
        note=(
            "Option-adjusted spread in bp. NEW value. Quote-only: an OAS needs a "
            "term-structure model and a call schedule, neither of which this "
            "package carries, so there is deliberately no local fallback - a "
            "computed 'OAS' that was really a Z-spread would be worse than none. "
            "Served for 1,401 of 2,162 bonds, and window-dependent: absent over "
            "a one-week window, present over five years."
        ),
    ),
    ValueSpec(
        citi="CAS",
        frb="CAS",
        unit="basis_points",
        verified=False,
        note=(
            "NEW value. Served for 381 of the 2,162 ISINs and for no US Treasury "
            "at all - exactly one US ISIN carries it, US3133EPSW68 (an FFCB "
            "agency). Measured CND1000113G9 = 43.4983 and KR10350172C8 = 44.2101. "
            "Addressable, and must be treated as absent unless the per-bond "
            "availability says otherwise."
        ),
    ),
)

#: ``ASW_4_<CCY>`` is a sparse cross-currency matrix rather than one value: it is
#: the bond asset-swapped into that currency, so a JPY leg on a US Treasury is a
#: cross-currency asset swap and not the bond's own spread. Read as basis points -
#: an INFERENCE from the magnitudes in the harvest (CH0127181029 ASW_4_USD =
#: -23.6648, GB00BMF9LG83 ASW_4_GBP = 4.12468), not a measurement of the unit, and
#: carried as ``verified=False`` for that reason.
ASW_CURRENCY_VALUES: Tuple[str, ...] = ("USD", "EUR", "GBP", "CHF", "JPY", "AUD")

_ASW_SPECS = tuple(
    ValueSpec(
        citi=f"ASW_4_{ccy}",
        frb="ASW_SPREAD",
        unit="basis_points",
        verified=False,
        note=(
            f"The bond asset-swapped into {ccy}, in bp. NEW value, selected with "
            f"asw_currency='{ccy}'. UNVERIFIED which ASW variant '_4_' denotes - "
            "par-par, market-value or yield-yield - which is worth several bp on "
            "a bond away from par. ql_asset_swap_spread computes the par-par "
            "spread locally and is reconciled to ql.AssetSwap.fairSpread() at "
            "4.8e-14 bp, so the calibration can say which variant Citi publishes "
            "rather than assume. Where the bond's currency differs from the leg "
            "currency this is a CROSS-currency asset swap and the local par-par "
            "figure is not the same quantity at all."
        ),
    )
    for ccy in ASW_CURRENCY_VALUES
)

#: Every Citi bond value, keyed by its tag suffix.
CITI_BOND_VALUES: Mapping[str, ValueSpec] = {
    s.citi: s for s in (_SPECS + _ASW_SPECS)
}


def spec_for(citi_value: str) -> ValueSpec:
    """The :class:`ValueSpec` for a Citi value token.

    Raises
    ------
    KeyError
        With the accepted vocabulary in the message, because a typo here
        otherwise surfaces as an empty timeseries.
    """
    token = str(citi_value).strip().upper()
    try:
        return CITI_BOND_VALUES[token]
    except KeyError:
        raise KeyError(
            f"Unknown Citi bond value {citi_value!r}. Accepted: "
            f"{', '.join(sorted(CITI_BOND_VALUES))}."
        ) from None


def frb_value_for(citi_value: str) -> Optional[str]:
    """The ``FixedRateBondValue`` member name a Citi value maps onto."""
    return spec_for(citi_value).frb


@dataclasses.dataclass(frozen=True)
class Provenance:
    """Where one number came from.

    ``origin`` is ``"quoted"`` or ``"computed"``. For a quote, ``detail`` is the
    tag; for a computation, the backend function that produced it. ``verified``
    carries the :class:`ValueSpec` standing forward, so a consumer can tell a
    measured mapping from an assumed one without going back to this module.
    """

    origin: str
    detail: str
    unit: str
    verified: bool
    note: str = ""

    def __str__(self) -> str:
        mark = "" if self.verified else " (interpretation UNVERIFIED)"
        return f"{self.origin}:{self.detail} [{self.unit}]{mark}"


def quoted_provenance(citi_value: str, tag: str) -> Provenance:
    """Provenance for a number Citi published directly."""
    spec = spec_for(citi_value)
    return Provenance(
        origin="quoted", detail=tag, unit=spec.unit,
        verified=spec.verified, note=spec.note,
    )


def computed_provenance(
    backend: str,
    function: str,
    *,
    unit: str,
    inputs: str = "",
    verified: bool = True,
    note: str = "",
) -> Provenance:
    """Provenance for a number this repo built from a Citi quote.

    ``inputs`` names the quote it was built from, which is what makes a computed
    value auditable: "computed from RATES.BOND.<ISIN>.PRICE" is a claim you can
    check, "computed" is not.

    ``verified`` is an argument rather than a hardcoded ``True`` because a computed
    number **inherits the standing of the quote it was solved from**. Seven of the
    values on this source (YTM, MOD_DURATION, PV01, DV01, NPV, DIRTY_PRICE,
    CONVEXITY) are all solved from ``PRICE``, whose clean-vs-dirty reading is
    itself ``verified=False`` and worth 0.0163 to 3.1844 price points on the
    calibration set. Reporting the input as unverified and the seven outputs as
    verified inverts exactly what the field is for: a consumer filtering on
    ``verified`` kept every number carrying the uncertainty and dropped the only
    one that declared it.
    """
    detail = f"{backend}.{function}"
    if inputs:
        detail = f"{detail}<-{inputs}"
    return Provenance(
        origin="computed", detail=detail, unit=unit, verified=bool(verified), note=note
    )


def provenance_of(meta: Optional[Mapping], value: str) -> Optional[Provenance]:
    """The :class:`Provenance` recorded for ``value`` on a pricer's metadata.

    Returns ``None`` when the pricer did not come from the Velocity source, which
    is the honest answer - absence of provenance is not evidence of computation.
    """
    if not meta:
        return None
    book = meta.get(PROVENANCE_KEY) or {}
    got = book.get(str(value).strip().upper())
    if got is None:
        return None
    if isinstance(got, Provenance):
        return got
    return Provenance(**got)


def unverified_values() -> Tuple[str, ...]:
    """Citi values whose interpretation has not yet been measured.

    Exposed so a report or notebook can say which numbers carry an assumption
    instead of everyone re-reading this module.
    """
    return tuple(sorted(s.citi for s in CITI_BOND_VALUES.values() if not s.verified))


# ------------------------------------------------------------------ #
#            reading a Velocity-sourced pricer's metadata            #
# ------------------------------------------------------------------ #


def asw_value_for_currency(currency: str = "USD") -> str:
    """``'USD'`` -> ``'ASW_4_USD'``, validated against the served leg vocabulary.

    Raises
    ------
    KeyError
        Naming the six legs, because ``asw_currency='usd '`` otherwise surfaces
        as "Citi does not serve this bond's asset swap", which is a different
        and much more misleading answer.
    """
    ccy = str(currency).strip().upper()
    token = f"ASW_4_{ccy}"
    if token not in CITI_BOND_VALUES:
        raise KeyError(
            f"No asset-swap leg for currency {currency!r}. Citi's legs are: "
            f"{', '.join(ASW_CURRENCY_VALUES)}."
        )
    return token


def is_velocity_meta(meta: Optional[Mapping]) -> bool:
    """Whether this pricer's metadata came from the Velocity bond source.

    Keyed off :data:`QUOTED_KEY` rather than a source-name string, because the
    source name lives in ``FixedRateBondsMDP`` and a pricer rebuilt from the disk
    cache does not carry it.
    """
    return bool(meta) and isinstance(meta.get(QUOTED_KEY), collections.abc.Mapping)


def quoted_value_of(meta: Optional[Mapping], citi_value: str) -> Optional[float]:
    """Citi's published number for ``citi_value``, or ``None``.

    ``None`` conflates "not this source", "not served for this bond" and "served
    but empty in the requested window". Use :func:`require_quoted` where the
    distinction matters, which is everywhere a user sees the result.
    """
    if not meta:
        return None
    book = meta.get(QUOTED_KEY) or {}
    got = book.get(str(citi_value).strip().upper())
    return None if got is None else float(got)


def coverage_of(meta: Optional[Mapping]) -> Dict[str, Tuple[str, ...]]:
    """``{'serves', 'requested', 'unavailable', 'empty', 'failed'}``, each a tuple.

    ``serves``
        This bond's whole served vocabulary from the harvested validation set,
        independent of what was asked for. It is what makes "Citi does not serve
        CAS for this bond" answerable about a value nobody requested. Empty means
        the validation sweep never covered this bond - see
        :func:`coverage_is_validated` - NOT that Citi serves nothing.
    ``requested``
        What actually went out on the wire.
    ``unavailable``
        Asked for, and not served for this bond - the tag was therefore **never
        requested**. Asking again will not help.
    ``empty``
        Citi does serve it, the tag went out, and no row came back inside the
        requested window. Measured: ``OAS`` returns nothing over one week and a
        full history over five years, so this is a normal outcome and the fix is a
        wider window, not a different bond.
    ``failed``
        The tag went out and the TRANSPORT failed for it - a rejected tag, an
        unentitled one, an add-in that is not signed in, an Excel that went away.
        Nothing here is evidence about the market, and widening the window cannot
        help. Reasons are in :func:`failures_of`.

    Merging ``unavailable`` and ``empty`` would turn "widen your window" into
    "this bond has no OAS", which is false for 1,401 of the 2,162 ISINs. Merging
    ``failed`` into ``empty`` tells a caller to widen a window when Excel
    disconnected.
    """
    book = (meta or {}).get(COVERAGE_KEY) or {}
    return {
        key: tuple(str(v).strip().upper() for v in (book.get(key) or ()))
        for key in ("serves", "requested", "unavailable", "empty", "failed")
    }


def coverage_is_validated(meta: Optional[Mapping]) -> bool:
    """Whether the harvest's validation sweep ever covered this bond.

    ``False`` for the fifteen universe ISINs the sweep missed (thirteen Canadian,
    two Italian: 2,147 of 2,162 were covered). For those bonds an absent value is
    an OPEN QUESTION, not a coverage fact, and every message about them has to say
    so - the alternative is turning an incomplete sweep into a positive claim
    about what Citi serves.

    Defaults to ``True`` for a book written before the flag existed, which is the
    reading that matches how those books were built.
    """
    book = (meta or {}).get(COVERAGE_KEY) or {}
    return bool(book.get("validated", True))


def failures_of(meta: Optional[Mapping]) -> Dict[str, str]:
    """``{citi_value: transport failure reason}`` for this pricer's fetch."""
    book = (meta or {}).get(FAILURES_KEY) or {}
    return {str(k).strip().upper(): str(v) for k, v in dict(book).items()}


def require_quoted(
    meta: Optional[Mapping],
    citi_value: str,
    *,
    source_names: Tuple[str, ...] = ("USTS_CITIVELO-QL", "USTS_CITIVELO-RL"),
    subject: str = "",
) -> float:
    """Citi's published number for ``citi_value``, or a message that says why not.

    The failure modes are separated on purpose. A quote-only value that returned
    ``nan`` or ``0.0`` when the pricer simply came from another source is the exact
    shape of a silent wrong answer: ``0.0`` is a perfectly plausible spread to
    Treasuries.

    Five causes, five fixes, and ``subject`` is interpolated into every one of them
    - a message that says "this bond" leaves a caller pricing a three-leg fly with
    no way to tell which leg failed except re-running each singly.

    Raises
    ------
    QuoteNotServedError
        With the source names to switch to, or the coverage reason.
    """
    token = str(citi_value).strip().upper()
    what = subject or token
    if not is_velocity_meta(meta):
        raise QuoteNotServedError(
            f"{what} is a QUOTE-ONLY value: it is Citi Velocity's own published number and "
            f"there is no local model for it. This pricer did not come from the Velocity "
            f"source, so nothing published it. Build the pricer with "
            f"FixedRateBondsMDP(source={source_names[0]!r}) or {source_names[1]!r}. "
            f"(Returning NaN here would be indistinguishable from a real quote of NaN, and "
            f"0.0 is a plausible spread.)"
        )

    got = quoted_value_of(meta, token)
    if got is not None:
        return float(got)

    coverage = coverage_of(meta)
    # Order matters, and the transport comes first: when the fetch for this tag
    # FAILED, nothing that follows is knowable. Reporting a COM disconnect as an
    # empty window sends the caller to widen a window, which cannot work.
    if token in coverage["failed"]:
        reason = failures_of(meta).get(token, "(reason not recorded)")
        raise QuoteNotServedError(
            f"The fetch for {what} FAILED: {reason}. This is a transport failure, not a "
            f"statement about the market - Citi was never asked, or was asked and rejected "
            f"the tag. Retry once the add-in is signed in and Excel is alive; widening the "
            f"window will not help."
        )
    # "Not served for this bond" is checked against the bond's whole served
    # vocabulary rather than against what was asked for, so a value nobody
    # requested still gets the answer that is true instead of the one about the
    # request. The two have different fixes and only one of them can work.
    if not coverage_is_validated(meta):
        raise QuoteNotServedError(
            f"{what} did not come back, and this bond's coverage was NEVER VALIDATED. The "
            f"committed sweep covered 2,147 of the 2,162 ISINs; this is one of the fifteen it "
            f"missed (thirteen Canadian, two Italian), so an absent value here is an open "
            f"question rather than a fact about coverage. Requested: "
            f"{', '.join(coverage['requested']) or '(nothing)'}; empty: "
            f"{', '.join(coverage['empty']) or '(none)'}. Ask the wire over a wider window "
            f"before concluding anything."
        )
    if token in coverage["unavailable"] or (coverage["serves"] and token not in coverage["serves"]):
        raise QuoteNotServedError(
            f"Citi does not serve {what}, so it was never requested. "
            f"Per-bond coverage is uneven and is read from the harvested validation set; "
            f"this bond serves {', '.join(coverage['serves']) or '(nothing)'}."
        )
    if token in coverage["empty"]:
        raise QuoteNotServedError(
            f"Citi serves {what} but returned no rows in the window that was "
            f"fetched. This is window-dependent and measured: OAS is empty over one week and "
            f"full over five years. Widen the request rather than concluding the bond has no "
            f"{token}."
        )
    raise QuoteNotServedError(
        f"{what} was not requested for this bond, although Citi does serve it. Requested: "
        f"{', '.join(coverage['requested']) or '(nothing)'}. Pass values=[...] to the "
        f"Velocity bond fetcher to include it."
    )
