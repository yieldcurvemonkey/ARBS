r"""What Citi serves for a bond, what this repo calls it, and which one you got.

Citi Velocity publishes **46** values per bond on this tag path. That number took
three passes and the first two were wrong, in ways worth keeping:

* **8** — the inherited answer. ``validate_with_controls`` defaults to
  ``period="1W"`` and the original probe used that default against a SINGLE US
  Treasury, so "no rows in one week" was recorded as "does not exist". That is how
  ``ZSPREAD``, ``ASW``, ``CAS`` and ``ASW_4_EUR/GBP/CHF`` were all lost, and why
  this module used to state "``CAS`` serves no US Treasury" when 304 of 349 do.
* **16** — after widening to five years and ten country/asset-type universes.
  Better, and still bounded by GUESSED candidate names.
* **46** — after probing Citi's OWN 118-field dictionary against this path
  (2026-08-08). A single US Treasury serves **44**. Guesswork could never have
  produced ``PRICING_ACCRUED``, ``OISSMM_RFR`` or ``ROLLCARRY.6M``; whole families
  were invisible to it — carry/roll, the OIS-spread family, yield-yield spread,
  and every RFR variant of ASW/CAS/OAS.

Per-universe coverage lives in ``catalog/bond_values_official_sweep.json`` and the
authoritative list is :data:`MDP.CitiVelocityExcel.tags.BOND_VALUES`, which this
module reads rather than restating — a hand-copied table here was false in every
row within a day.

**56 of Citi's dictionary tags return nothing on this path**, and the pattern is
informative: the iBoxx, TRACE, CDS-basis, short-interest and equity-vol fields
belong to a CREDIT screen, not to ``RATES.BOND``. So "Citi has a field for it"
does not mean this tag serves it. Also absent: the whole ``SPREAD_BENCH.*``
family, ``ASW_C_*`` (coupon-frequency ASW, against the ``ASW_4_*`` quarterly ones
that do serve), ``PV01_CALL/MAT``, ``DOLLAR_DURATION``, ``CONVEXITY``,
``ZSPREAD_CALL/MAT``, ``YIELD_MAT`` and ``YIELD_NEXT``.

Two traps that survive validation
---------------------------------
**Six values were retired on 2025-10-03.** ``ASW``, ``ASWNP``, ``CAS``, ``OISS``,
``YYS`` and ``ZSPREAD`` each run 2021-08-09 .. 2025-10-03 and then stop, while
their ``_RFR`` counterparts run to 2026-08-07: Citi migrated the family from the
legacy swap basis to RFR. Each still returns 1,038-1,039 rows, so a coverage probe
calls it served and a backtest reads four years of it happily — only a recent date
fails, and it fails as "no rows in the window", which reads as a gap rather than a
retirement. See :data:`DISCONTINUED_2025_10_03` for the successors.

**Carry and roll lag by exactly their own horizon.** ``CARRY.1M`` ends ~1M back,
``CARRY.6M`` ~6M, ``ROLLCARRY.1Y`` ~1Y. The lag tracking the horizon that
precisely says these are REALISED over the window just ended, not forecast over
the window ahead — so "carry as of today" cannot be satisfied for any horizon, by
construction rather than by outage.

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

.. note::

   **The four readings that could have been confidently wrong are now measured**
   (calibration 2026-08-07, 7 US Treasuries chosen so accrued spans 0.095 to
   2.188 price points - on a low-accrued bond clean and dirty are the same number
   and settle nothing):

   =============  ==================  ==========================================
   value          verdict             margin
   =============  ==================  ==========================================
   ``PRICE``      **clean**, per 100  0.0186 bp median error vs Citi's own YIELD,
                                      against 57.43 bp if read as dirty
   ``YIELD``      percent, semi-ann.  reproduced to 0.0001-0.0008 bp on the four
                                      bonds that reconstruct cleanly
   ``DURATION``   **modified**        1.9e-05 yr median error, against 0.0500 yr
                                      if read as Macaulay
   ``DV01``       **per 1mm**, +long  ratio to local per-100 dv01 = 10000.06
                                      median; 9999.997-10000.09 on the clean four
   =============  ==================  ==========================================

   Each was settled by asking which reading of one Citi number reproduces
   ANOTHER Citi number - not by repricing Citi's figure with our own model and
   observing that it agrees, which is a tautology. Raw numbers and per-bond rows
   are in ``catalog/bond_calibration.json``; reproduce with
   ``scripts/citivelo_bond_calibration.py fetch build``.

   Three of the seven bonds do NOT reconstruct cleanly (yield errors -12.44,
   +25.70 and +0.62 bp). That is a per-bond reconstruction question - the coupon
   and schedule come from parsing Citi's description text, and a wrong first
   coupon shows up exactly this way - NOT a question about what the values mean:
   the three verdicts above are decided by factors of 2,600-3,000, which no
   plausible schedule error can flip. ``ASW_4_<CCY>`` remains unmeasured; which
   asset-swap variant ``_4_`` denotes is still open.

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
        verified=True,
        note=(
            "MEASURED CLEAN, per 100 face (calibration 2026-08-07, 7 US Treasuries, "
            "accrued spanning 0.095 to 2.188 price points). Read as CLEAN, the median "
            "absolute error against Citi's own published YIELD is 0.0186 bp; read as "
            "DIRTY it is 57.43 bp - a factor of ~3,000, so the reading is not in "
            "doubt. Four of the seven tie out to under 0.02 bp (0.0186, 0.0008, "
            "0.0006, 0.0001). Settled by asking which reading of PRICE reproduces "
            "Citi's YIELD, not by repricing Citi's number with our own model, which "
            "would prove nothing. See catalog/bond_calibration.json."
        ),
    ),
    ValueSpec(
        citi="YIELD",
        frb="YTM",
        unit="percent",
        verified=True,
        note=(
            "Yield to maturity in PERCENT, semi-annual compounding for USTs - "
            "measured 2026-08-07: feeding Citi's own PRICE through this package's "
            "UST conventions reproduces Citi's YIELD to a median 0.0186 bp over 7 "
            "bonds, and to 0.0001-0.0008 bp on the four that reconstruct cleanly. "
            "STILL UNVERIFIED OFF THE US CURVE: the compounding basis is per market "
            "(BTPs quote annually - conventions.py separates yield_frequency from "
            "coupon frequency for exactly that), and whether callables quote to "
            "maturity or to worst is untested because no callable was in the set."
        ),
    ),
    ValueSpec(
        citi="DURATION",
        frb="MOD_DURATION",
        unit="years",
        verified=True,
        note=(
            "MEASURED MODIFIED (calibration 2026-08-07, 7 US Treasuries). Median "
            "absolute error against locally computed MODIFIED duration is 1.9e-05 "
            "years; against MACAULAY it is 0.0500 years - a factor of ~2,600. The "
            "two differ by (1 + y/f), about 2% at current yields, which is why the "
            "tag name alone could not settle it. Compared against BOTH locally "
            "computed figures rather than assuming the name."
        ),
    ),
    ValueSpec(
        citi="DV01",
        frb="DV01",
        unit="currency_per_bp",
        verified=True,
        note=(
            "MEASURED per 1mm face, POSITIVE for a long (calibration 2026-08-07, 7 "
            "US Treasuries). Citi's DV01 divided by this package's per-100-face "
            "dv01 has median 10000.06, and lands on 9999.997 / 10000.03 / 10000.06 "
            "/ 10000.09 for the four bonds that reconstruct cleanly - i.e. exactly "
            "10,000x, so Citi quotes per 1,000,000 face where this package quotes "
            "per 100. The ratio is POSITIVE, so Citi's sign convention matches this "
            "package's (a long is positive) rather than QuantLib's raw "
            "basisPointValue, which is negative and is abs()'d once in ql_bonds. "
            "MULTIPLY a local dv01 by 10,000 to compare, or divide Citi's by 10,000."
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

#: ``ASW_4_<CCY>`` is a sparse cross-currency MATRIX rather than one value: the
#: bond asset-swapped INTO that currency, so a JPY leg on a US Treasury is a
#: cross-currency asset swap and not the bond's own spread. Measured in basis
#: points (CH0127181029 ASW_4_USD = -23.6648, GB00BMF9LG83 ASW_4_GBP = 4.12468).
#: Distinct from plain ``ASW``, which is the bond's own-currency spread.
_ASW_SPECS = tuple(
    ValueSpec(
        citi=f"ASW_4_{ccy}",
        frb="ASW_SPREAD",
        unit="basis_points",
        verified=False,
        note=(
            f"The bond asset-swapped into {ccy}, quarterly, in bp. Selected with "
            f"asw_currency='{ccy}'. UNVERIFIED which ASW variant this is - Citi's "
            "own label calls it 'Quarterly', against ASW_C_<CCY> 'Coupon Frequency' "
            "which is in the dictionary but does NOT serve on this tag path. "
            "ql_asset_swap_spread computes the par-par spread locally and is "
            "reconciled to ql.AssetSwap.fairSpread() at 4.8e-14 bp, so the "
            "comparison is one fetch away. Where the bond's currency differs from "
            "the leg currency this is a CROSS-currency asset swap and the local "
            "par-par figure is not the same quantity at all."
        ),
    )
    for ccy in ASW_CURRENCY_VALUES
)


#: The carry/roll horizons Citi publishes. Measured: all four serve on every UST.
CARRY_HORIZONS: Tuple[str, ...] = ("1M", "3M", "6M", "1Y")

#: Units by family, applied to the values that are not hand-specced above.
#: Everything spread-shaped is basis points; carry and roll are quoted the same
#: way. NONE of these is verified against Citi's own arithmetic - they are the
#: reading the label implies, and the label is Citi's own
#: (``bond_values_official_sweep.json`` carries the label for every tag).
_FAMILY_UNITS = (
    (("PRICE", "ADJ_PRICE", "PRICING_ACCRUED"), "price_points"),
    (("YIELD", "SIMPLEYIELD", "YIELD_WORST", "YIELD_MAT", "YIELD_NEXT"), "percent"),
    (("DURATION",), "years"),
    (("DV01", "PRICING_CV01"), "currency_per_bp"),
)


def _family_unit(token: str) -> str:
    for names, unit in _FAMILY_UNITS:
        if token in names:
            return unit
    # Spread-shaped by default: ASW*, ASS*, CAS*, OAS*, OISS*, YYS*, ZSPREAD,
    # SPREAD_TSY, CARRY.*, ROLL.*, ROLLCARRY.*. Basis points is the reading that
    # matches every one of those labels.
    return "basis_points"


#: Values discovered by probing Citi's own field dictionary and NOT hand-specced
#: above. Generated rather than transcribed: there are 46 and a hand-written
#: table would drift from the measurement the first time the sweep is re-run.
_MEASURED_NOTES = {
    "ASW": "Plain asset-swap spread in the bond's own currency. Distinct from "
           "ASW_4_<CCY>, which is the CROSS-currency matrix. DISCONTINUED "
           "2025-10-03 - use ASW_RFR after that date.",
    "ASWNP": "Asset-swap spread, non-par. The par/non-par distinction is Citi's; "
             "which convention each uses is UNMEASURED. DISCONTINUED 2025-10-03 - use ASSNP_RFR after that date.",
    "ASW_RFR": "Asset-swap spread against the RFR rather than the legacy IBOR leg.",
    "ASS_SOFR": "Asset-swap spread explicitly vs SOFR. Serves on 1/10 universes "
                "sampled but 116/120 US Treasuries - it is a USD field.",
    "ASSNP_RFR": "Asset-swap spread, non-par, vs RFR.",
    "CAS": "Coupon-adjusted spread to the swap curve. DISCONTINUED 2025-10-03 - use CAS_RFR after that date.",
    "CAS_RFR": "Coupon-adjusted spread vs RFR.",
    "CAS_SOFR": "Coupon-adjusted spread vs SOFR; a USD field.",
    "OAS": "Option-adjusted spread.",
    "OAS_RFR": "Option-adjusted spread vs RFR.",
    "OISS": "OIS spread. DISCONTINUED 2025-10-03 - use OISS_RFR after that date.",
    "OISS_RFR": "OIS spread vs RFR.",
    "OISS_SOFR": "OIS spread vs SOFR; a USD field.",
    "OISSMM": "OIS spread, money-market basis. Serves on 87/120 US Treasuries - "
              "the sparsest of the OIS family.",
    "OISSMM_RFR": "OIS spread, money-market basis, vs RFR.",
    "YYS": "Yield-yield spread. DISCONTINUED 2025-10-03 - use YYS_RFR after that date.",
    "YYS_RFR": "Yield-yield spread vs RFR.",
    "YYS_SOFR": "Yield-yield spread vs SOFR; a USD field.",
    "ZSPREAD": "Z-spread to WORST, per Citi's own label - not to maturity. "
               "ZSPREAD_MAT and ZSPREAD_CALL are in Citi's dictionary but are NOT "
               "addressable on this tag path. DISCONTINUED 2025-10-03 with no RFR successor observed.",
    "PRICING_ACCRUED": "Accrued interest. Citi publishes it, so the clean/dirty "
                       "question can be settled from Citi's own numbers alone.",
    "PRICING_CV01": "CV01 - the convexity analogue of DV01. Note plain CONVEXITY "
                    "is in Citi's dictionary but returns nothing on this path.",
    "SIMPLEYIELD": "Simple yield. Serves on 1/10 universes and ZERO US Treasuries.",
    "YIELD_WORST": "Yield to worst. Serves only on covered bonds in the sample, "
                   "and ZERO US Treasuries - USTs are not callable.",
}


def _generated_specs() -> Tuple[ValueSpec, ...]:
    """One :class:`ValueSpec` per measured value that is not hand-specced."""
    from MDP.CitiVelocityExcel import tags as _T

    hand = {s.citi for s in _SPECS} | {f"ASW_4_{c}" for c in ASW_CURRENCY_VALUES}
    out = []
    for token in _T.BOND_VALUES:
        if token in hand:
            continue
        base = token.split(".")[0]
        if base in ("CARRY", "ROLL", "ROLLCARRY"):
            horizon = token.split(".", 1)[1] if "." in token else ""
            kind = {"CARRY": "Carry", "ROLL": "Roll", "ROLLCARRY": "Roll and carry"}[base]
            note = (f"{kind} over {horizon}. Citi publishes all four horizons "
                    f"({', '.join(CARRY_HORIZONS)}) and every one serves on every US "
                    "Treasury measured. UNVERIFIED whether this is quoted running or "
                    "over the horizon, and against which financing rate.")
            frb = None
        else:
            note = _MEASURED_NOTES.get(token, "Measured to serve; semantics UNVERIFIED.")
            frb = None
        out.append(ValueSpec(citi=token, frb=frb, unit=_family_unit(token),
                             verified=False, note=note + _MEASURED_SUFFIX))
    return tuple(out)


#: Values Citi STOPPED publishing on 2025-10-03, measured on US912810EX29 over a
#: five-year window: each runs 2021-08-09 .. 2025-10-03 and then nothing, while
#: its ``_RFR`` counterpart runs to 2026-08-07. Citi migrated this whole family
#: from the legacy swap basis to the RFR basis and retired the originals.
#:
#: This matters more than it looks. Every one of these still VALIDATES - the tag
#: is real and returns 1,038-1,039 rows - so a coverage probe calls it served and
#: a backtest happily reads four years of it. Ask for a recent date and you get
#: "no rows in the window", which reads as a gap rather than as a discontinued
#: field. Use the ``_RFR`` variant for anything after 2025-10-03.
DISCONTINUED_2025_10_03: Mapping[str, str] = {
    "ASW": "ASW_RFR",
    "ASWNP": "ASSNP_RFR",
    "CAS": "CAS_RFR",
    "OISS": "OISS_RFR",
    "YYS": "YYS_RFR",
    "ZSPREAD": "",          # no RFR successor observed
}

#: Carry and roll are published with a lag equal to their own HORIZON, measured
#: on the same bond: CARRY.1M ends 2026-07-13 (~1M back), CARRY.6M 2026-02-12
#: (~6M), ROLL.3M 2026-05-13 (~3M), ROLLCARRY.1Y 2025-08-13 (~1Y). The lag
#: tracking the horizon that precisely says these are REALISED over the window
#: just ended, not forecast over the window ahead - so a request for "carry as of
#: today" cannot be satisfied for any horizon, by construction rather than by
#: outage. UNVERIFIED against Citi's arithmetic; the pattern is unambiguous.
CARRY_LAGS_ITS_HORIZON = True


_MEASURED_SUFFIX = (
    " Discovered 2026-08-08 by probing Citi's own 118-field dictionary against "
    "this tag path; see catalog/bond_values_official_sweep.json for the label and "
    "the per-universe coverage."
)


CITI_BOND_VALUES: Mapping[str, ValueSpec] = {
    s.citi: s for s in (_SPECS + _ASW_SPECS + _generated_specs())
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
