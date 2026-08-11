"""Which prints are in, how they group into units, and why the rest are out.

This module answers one question per leg — *can this print's direction be
inferred at all?* — and it answers it **by name**, from the ``EXCL_*``
vocabulary in :mod:`.types`, so the coverage accounting adds up and nothing
leaves the universe anonymously. A silently-dropped population is the failure
mode here: the ladder still looks complete.

WHAT CHANGED FROM ``stir_flow.trade_selection`` AND WHY
-------------------------------------------------------

**The 3.02y maturity cutoff is gone.** ``config.SUB3Y_HORIZON_DAYS = 1105``
discards **73.0% of flow legs** — 1,671,827 of 2,289,646 — measured as the
filter is actually written (``trade_selection.py:79``:
``expiration_date > as_of_date + 1105 days``), not as the ``tenor_years > 3.02``
proxy, which is a *different* 1,595,321 legs and 3.3pp smaller. It was a
short-end classifier's scope, not a data statement, and removing it is the
point of the exercise.

**The venue whitelist is extended, with evidence, and asymmetrically.** See
:data:`VENUE_EVIDENCE`.

**MAC comes back in; the asset-swap families stay out.** See
:data:`EXCLUDED_TRADE_TYPES`.

**Term SOFR is now excluded as a different index, which it is.** 32,842 legs
carry ``leg_tape_label`` containing ``"CME Term"`` while ``rate_index_clean``
reads ``'SOFR'``, so the index filter alone lets them through and the
daily-compounded ``USD-SOFR-1D`` curve then prices a Term SOFR swap. The
Term/OIS basis is tens of basis points; left in, it reads as direction,
confidently and in one direction. That 32,842 is the *pair*, counted over all
rows (32,573 over ``ECONOMIC_FLOW``); the gate at :func:`annotate_legs` fires
on the label alone without consulting the index, so what it actually removes is
**33,487** ``contributes_to_flow`` legs.

**Non-constant notional schedules are excluded eagerly.** ``schedule_row_count``
is **0 on all 2,326,781 rows** — the tape carries no amortisation schedule at
all — so a bullet repricing of an amortiser succeeds numerically and is wrong
by the schedule effect, which on an upward-sloping curve is signed. That is the
worst kind of defect: no exception, a biased answer. Gated on the structured
``upi_notional_schedule`` column (48,937 flow legs), **not** on
``config.EXCLUDED_LABEL_TOKENS``' ``"Amortizing"`` token. The reason is *not*
that the token misses amortisers — measured, it does not: ``leg_tape_label LIKE
'%Amortizing%'`` and ``upi_notional_schedule = 'Amortizing'`` select the same
35,470 flow legs, 1:1, in every population tried (35,471 over all rows, 34,656
over ``ECONOMIC_FLOW``). The reason is the two families the token has no word
for: **Custom 11,960** and **Accreting 1,507**, which are equally not bullets
and which a label filter admits and prices as one.

WHAT ``contributes_to_flow`` ADMITS, AND WHAT NO DENOMINATOR HERE COUNTS
------------------------------------------------------------------------

``EXCL_NOT_FLOW`` is ``~contributes_to_flow``, and that column is **True on two
economic classes, not one**. Measured on v3: ``ECONOMIC_FLOW`` 2,289,646 and
``ECONOMIC_UNWIND`` **36,828**, against ``ADMINISTRATIVE`` 307 — so the gate
removes 307 rows and the universe admits 2,326,474. Every other measured number
in this module is quoted over ``ECONOMIC_FLOW`` alone, so **none of them
describes what the code admits**; the 36,828 are reported separately
(``unwind_units_kept``) rather than folded into a denominator that does not
contain them.

They are also not caught by ``is_lifecycle``. An ``ECONOMIC_UNWIND`` row here is
``trade_tape.py``'s H10 rule — a ``NEWT`` whose effective date is backdated more
than about a week, i.e. a position that already started accruing — and **36,763
of the 36,828 are stamped ``lifecycle_type = 'NEW_TRADE'``**, so
``is_lifecycle = ~all_new_trade`` reads False and they enter the primary
customer-flow series.

**Re-tagging them ``is_lifecycle`` would be worse, not better, and this is the
reason it is not done here.** ``upfront.orientation`` (``upfront.py:305-315``)
returns ``-s if is_lifecycle else s``: the flag does not merely select a series,
it *inverts the inferred direction*, and it does so because on a termination the
party holding the ITM side pays to exit. A backdated ``NEWT`` is a new swap
struck today at a seasoned coupon with a balancing fee, so ``sign(-f)`` — the
new-trade branch — is the correct orientation for it. Flipping 36,763 prints to
buy a tidier series tag is exactly the silent wrong answer this module exists to
prevent.

What remains genuinely open is the *confidence* model, not the sign:
``types.Clocks``/``types.Unit`` describe the lifecycle series as one whose
deviation is driven by seasoned P&L rather than by bid-offer, and a backdated
print is that population too. Resolving it needs a third series (or an
``is_lifecycle`` split into a series tag and a sign rule), which is a
``types.py``/``ladder.py``/``upfront.py`` decision and not one this module can
make on its own. Until it is made, the population is counted and named.

THE TOTAL LEG ORDER
-------------------

``(expiration_date, effective_date, trade_id)``, with ``leg_order`` as a final
tiebreaker. ``trade_selection.py``'s own comment explains why this matters:
``expiration_date`` alone is not unique inside a package, and a partial order
lets Postgres return tied rows in whatever physical order it likes, which
varies per query — so the FLY belly and ``iloc[0]`` move between runs and
``structure_dv01`` becomes non-deterministic. Measured on v3: the triple has
**zero duplicate groups** across all 2,326,781 rows, so it is already total;
``leg_order`` is carried anyway so that a future tape which breaks the property
degrades to a *different* order rather than to a random one.

Also measured, and relied on: **no package spans more than one
``as_of_date``**, so a per-day load is complete, and **no package mixes
``platform_identifier``, ``venue`` or ``rate_index_clean``**, so those are
unambiguous unit properties. 6,028 packages *do* mix ``lifecycle_type`` and
2,323 mix ``economic_class``; both are handled explicitly below.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.analytics.filters import D2D_PLATFORMS as _SDRUTILS_D2D
from SDRUtils.dealer_direction import package_price, sanity, snapshot
from SDRUtils.dealer_direction.types import (
    EXCL_EXERCISE_OR_NOVATION,
    EXCL_NO_FIXED_RATE,
    EXCL_NOT_FLOW,
    EXCL_PRICING_ERROR,
    EXCL_RISK_IMPLAUSIBLE,
    EXCL_STANDARD_COUPON,
    EXCL_UNORIENTABLE,
    EXCL_UNSUPPORTED_INDEX,
    VENUE_D2C,
    VENUE_D2D,
    VENUE_UNKNOWN,
    Clocks,
    Unit,
)
from SDRUtils.stir_flow import config as _sf_config
from SDRUtils.stir_flow import ladder_conventions as _ladder

# ===========================================================================
# venue
# ===========================================================================

#: Evidence tiers. The tier is not decoration -- it drives an asymmetric rule.
EVIDENCE_REGISTRY = "REGISTRY"        # operator named in a public venue registry
EVIDENCE_FINGERPRINT = "FINGERPRINT"  # unnamed, but the measured mix is decisive
EVIDENCE_OFF_FACILITY = "OFF_FACILITY"  # not a venue code at all
EVIDENCE_UNRECOGNISED = "UNRECOGNISED"

#: ``platform_identifier`` -> (venue class, evidence tier).
#:
#: **The asymmetry.** A wrong ``D2D`` call costs nothing: D2D units are kept
#: and tagged as their own series, never folded into customer flow. A wrong
#: ``D2C`` call contaminates the primary series. So fingerprint evidence may
#: promote a platform to D2D and **never** to D2C; D2C requires a named
#: operator. A test pins that.
#:
#: EVIDENCE, per the brief's requirement that an extension carry both a count
#: and a registry/counterparty-class argument.
#:
#: *Registry.* ``docs/plans/2026-05-04-usd-swaps-sdr-analytics-design.md``
#: §3.5 and Appendix A carry a MIC -> operator -> D2C/D2D table compiled from
#: Clarus's public SEF-volume posts. It identifies TREU/TWEM as Tradeweb,
#: BMTF/BTFE as Bloomberg, ISWE as ICAP and GSEF as BGC. Each of those four
#: operators **already has a sibling code on this tape that is classified**:
#: TWSF (Tradeweb) and BBSF (Bloomberg) are in the incumbent D2C whitelist;
#: ISWV (ICAP) and BGCD (BGC) are in ``analytics.filters.D2D_PLATFORMS``. The
#: extension is therefore "same operator, same counterparty class", not a new
#: judgement about a new firm.
#:
#: *Counts* (ECONOMIC_FLOW legs, measured on v3): TREU 25,192 · BMTF 20,678 ·
#: RTXF 7,476 · ISWE 6,880 · TWEM 4,775 · BTFE 3,012 · GSEF 2,658. The code
#: gates on ``contributes_to_flow`` alone, which is a slightly wider
#: population (TREU 25,224 · BMTF 20,699 · TWEM 4,785 · BTFE 3,026 · GSEF
#: 2,659; RTXF/ISWE/BGCO/TRWB unchanged) — see "WHAT ``contributes_to_flow``
#: ADMITS" above. The evidence is stated on the narrower one because that is
#: the population the fingerprint table below was cut on.
#:
#: *Fingerprint.* Known-D2C and known-D2D separate cleanly on two axes:
#:
#: ===============  ========  ==============  ==========  ==========
#: population       n legs    % with upfront  % outright  % asset-sw
#: ===============  ========  ==============  ==========  ==========
#: known D2C        1901042   45.5            59.8        6.6
#: known D2D         237518    0.0            11.9        50.0
#: TREU               25192   33.6            65.1        2.3
#: TWEM                4775   26.0            70.1        5.3
#: BMTF               20678    2.9            77.4        3.7
#: BTFE                3012    1.0            83.6        4.5
#: ISWE                6880    0.0             7.5        68.9
#: GSEF                2658    0.0            35.6        38.3
#: RTXF                7476    0.0             4.2        63.6
#: XOFF               28401   25.8            72.6        10.5
#: XXXX               51260   12.7            75.1        15.0
#: ===============  ========  ==============  ==========  ==========
#:
#: TREU/TWEM match D2C on both axes. BMTF/BTFE match on structure (77-84%
#: outright against an IDB's 12%) but sit near zero on upfront presence; that
#: axis is a statement about *seasoned* business, not counterparty class, and a
#: venue doing only new on-market flow reads zero on it either way — so it is
#: not evidence against, and the registry decides. ISWE/GSEF/RTXF match D2D on
#: both axes.
#:
#: ``TRWB`` (Tradeweb UK, 7 legs) and ``BGCO`` (BGC options, 237 legs) are in
#: for consistency rather than for size: the same table names the same
#: operators, and classifying a firm's 25,192-leg code while leaving its
#: 237-leg one unclassified is arbitrary. The table's FX/NDF entries (``CBNL``,
#: ``JPCB``, ``EBSS``, ``XEBS``, ``THRE``, ``BHSF``) are deliberately **not**
#: pre-loaded: an unrecognised FX venue on a USD IRS tape is something to look
#: at rather than to silently absorb. **One of them is here** -- ``CBNL``, 2
#: legs (the other five are absent) -- so the intended consequence is live: it
#: classifies ``VENUE_UNKNOWN`` on fingerprint evidence of two rows, which is
#: none, and :func:`on_facility` returns ``None`` for it so it takes the
#: conservative +60 min delay. Two legs is below anything worth a registry
#: judgement; the number is written down so the next reader checks it against
#: the tape rather than against this sentence.
#:
#: RTXF is the only **fingerprint-tier** entry: the reference table lists
#: Refinitiv as ``RTX`` (D2D) and ``THRE`` (D2C), and a one-character-off match
#: is not an identification. Its measured mix (0.0% upfront, 63.6% asset-swap,
#: 4.2% outright) is the IDB fingerprint and nothing else's, so it goes to D2D
#: — which the asymmetry above makes a cheap call.
#:
#: **Two comments in the frozen ``stir_flow.config`` are overruled here**, on
#: purpose and with evidence: it glosses TREU as "Truenode" and BMTF as "BGC
#: MTF, likely D2D". Both are misidentifications — TREU is Tradeweb Europe and
#: BMTF is a Bloomberg trading facility — and the measured fingerprints agree
#: with the registry, not with the comments (BMTF is 3.7% asset-swap against
#: BGC's own BGCD at IDB levels).
VENUE_EVIDENCE: dict[str, tuple[str, str]] = {
    # --- incumbent D2C whitelist (stir_flow.config.D2C_PLATFORM_WHITELIST) ---
    "TWSF": (VENUE_D2C, EVIDENCE_REGISTRY),   # Tradeweb SEF
    "BBSF": (VENUE_D2C, EVIDENCE_REGISTRY),   # Bloomberg SEF
    "BILT": (VENUE_D2C, EVIDENCE_REGISTRY),   # Bloomberg bilateral (off-facility)
    # --- added D2C, registry tier -------------------------------------------
    "TREU": (VENUE_D2C, EVIDENCE_REGISTRY),   # Tradeweb Europe MTF
    "TWEM": (VENUE_D2C, EVIDENCE_REGISTRY),   # Tradeweb EM
    "BMTF": (VENUE_D2C, EVIDENCE_REGISTRY),   # Bloomberg MTF
    "BTFE": (VENUE_D2C, EVIDENCE_REGISTRY),   # Bloomberg trading facility
    "TRWB": (VENUE_D2C, EVIDENCE_REGISTRY),   # Tradeweb UK MTF (7 legs)
    # --- incumbent D2D (analytics.filters.D2D_PLATFORMS) --------------------
    "BGCD": (VENUE_D2D, EVIDENCE_REGISTRY),
    "DWSF": (VENUE_D2D, EVIDENCE_REGISTRY),
    "IGDL": (VENUE_D2D, EVIDENCE_REGISTRY),
    "ISWV": (VENUE_D2D, EVIDENCE_REGISTRY),
    "TPSE": (VENUE_D2D, EVIDENCE_REGISTRY),
    "TSEF": (VENUE_D2D, EVIDENCE_REGISTRY),
    # --- added D2D ----------------------------------------------------------
    "ISWE": (VENUE_D2D, EVIDENCE_REGISTRY),   # ICAP, sibling of ISWV
    "GSEF": (VENUE_D2D, EVIDENCE_REGISTRY),   # BGC/GFI, sibling of BGCD
    "BGCO": (VENUE_D2D, EVIDENCE_REGISTRY),   # BGC options (237 legs)
    "RTXF": (VENUE_D2D, EVIDENCE_FINGERPRINT),
    # --- not venues ---------------------------------------------------------
    "XXXX": (VENUE_UNKNOWN, EVIDENCE_OFF_FACILITY),
    "XOFF": (VENUE_UNKNOWN, EVIDENCE_OFF_FACILITY),
}

#: ``XXXX`` (51,260 flow legs) and ``XOFF`` (28,401) are **CFTC off-facility
#: codes, not venues** — the ISO 20022 MIC placeholders for an off-exchange
#: transaction. They stay :data:`~.types.VENUE_UNKNOWN`, and the line that
#: separates them from ``BILT`` (also off-facility, also unmandated, but
#: whitelisted D2C) is that BILT names an arranger and these name nobody.
#:
#: The argument that cuts the other way is real and is recorded rather than
#: acted on: a USD OIS between two swap dealers is subject to the trade
#: execution mandate, so an *off-facility* one usually has a non-dealer
#: counterparty, and 59-62% of these legs carry ``cleared = 'N'`` against
#: 0.5-4% elsewhere. That is **counterparty-class evidence, not venue
#: evidence**, it covers only part of the population, and folding 79,661 legs
#: into the primary customer series on it would be the expensive direction of
#: the asymmetry above. Their share is reported separately so the desk can
#: overrule this with one constant.
OFF_FACILITY_CODES = frozenset({"XXXX", "XOFF"})

#: Off-facility execution for Part 43 Appendix C purposes. ``BILT`` is a D2C
#: platform *and* off-facility, which is why the two concepts need separate
#: sets: venue class answers "whose flow is this", on-facility answers "which
#: legal dissemination delay applies".
OFF_FACILITY_PLATFORMS = OFF_FACILITY_CODES | {"BILT"}

D2C_PLATFORMS = frozenset(
    p for p, (c, _) in VENUE_EVIDENCE.items() if c == VENUE_D2C)
D2D_PLATFORMS = frozenset(
    p for p, (c, _) in VENUE_EVIDENCE.items() if c == VENUE_D2D)

# The incumbent sets must stay subsets: this module extends them, it does not
# reinterpret them. Asserted at import so a drift in the frozen modules is a
# loud failure rather than a quiet reclassification of live flow.
assert set(_sf_config.D2C_PLATFORM_WHITELIST) <= D2C_PLATFORMS
assert set(_SDRUTILS_D2D) <= D2D_PLATFORMS


def classify_venue(platform_identifier) -> str:
    """``VENUE_D2C`` / ``VENUE_D2D`` / ``VENUE_UNKNOWN`` for one platform code."""
    return VENUE_EVIDENCE.get(_pid(platform_identifier), (VENUE_UNKNOWN, None))[0]


def venue_evidence(platform_identifier) -> str:
    """Which tier of evidence put this platform where it is."""
    return VENUE_EVIDENCE.get(
        _pid(platform_identifier), (None, EVIDENCE_UNRECOGNISED))[1]


def on_facility(platform_identifier) -> bool | None:
    """Did this execute on a SEF/MTF? ``None`` where the code is unrecognised.

    ``None`` matters: :func:`ladder_conventions.visibility_class` tests
    ``is True`` / ``is False``, so an unrecognised platform falls to
    ``INDETERMINATE`` (+60 min) rather than borrowing a delay class it has no
    claim to.

    **This supersedes ``ladder_conventions.SEF_PLATFORM_CODES``**, which is the
    8 incumbent codes, and the deviation is listed in :data:`_RELAXATIONS`
    because it is the only one here that moves a *clock* rather than an
    admission: the 9 MTF/SEF codes added to :data:`VENUE_EVIDENCE` (~70,700
    legs) go from INDETERMINATE (+60) to their Appendix C class, which is
    shorter, and a visibility stamp that is too early is lookahead. The change
    is substantively right — they are registered MTFs and SEFs — but it errs in
    the expensive direction, so it is tested rather than assumed.
    """
    pid = _pid(platform_identifier)
    if not pid:
        return None
    if pid in OFF_FACILITY_PLATFORMS:
        return False
    if pid in VENUE_EVIDENCE:
        return True
    return None


def cleared_flag(cleared) -> bool | None:
    """The tape's ``cleared`` code as a tri-state, for Appendix C.

    Measured distribution: ``I`` 2,198,521 · ``N`` 128,035 · ``Y`` 225.
    ``I`` is *intent to clear* and it is 94.5% of the tape, because a swap
    destined for a CCP is publicly reported at execution, before clearing has
    happened. Reading ``I`` as "not cleared" would put almost the whole tape in
    the uncleared class, which is factually wrong -- so ``I`` and ``Y`` both
    map to cleared. The usual "when in doubt, be conservative" instinct picks
    the wrong answer here, which is why this is a named function and not an
    inline truthiness test.
    """
    v = _pid(cleared)
    if v in ("Y", "I"):
        return True
    if v == "N":
        return False
    return None


def _pid(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return str(v).upper().strip()


# ===========================================================================
# eligibility
# ===========================================================================

#: The only two indices with a curve behind them (``snapshot.CURVE_FOR``).
#: Measured over all rows: SOFR 2,234,429 · FED_FUNDS 70,709 · BASIS 15,259 ·
#: OTHER 6,384.
SUPPORTED_INDICES = frozenset({"SOFR", "FED_FUNDS"})

#: Term SOFR prints carry ``rate_index_clean = 'SOFR'``. See the module
#: docstring: they are a different index and the index filter misses them.
TERM_SOFR_TOKEN = "CME Term"

#: ``upi_notional_schedule`` values that are not a bullet. Measured over flow
#: legs: Constant 2,277,485 · Amortizing 35,470 · Custom 11,960 ·
#: Accreting 1,507 · NULL 52. The 52 nulls are kept -- absence of a schedule
#: label is not evidence of a schedule.
NON_CONSTANT_SCHEDULES = frozenset({"Amortizing", "Custom", "Accreting"})

#: Revisited one family at a time against
#: ``stir_flow.config.EXCLUDED_TRADE_TYPES``, which also carried ``MAC``.
#:
#: **MAC — exclusion REMOVED.** A Market Agreed Coupon swap is off-market by
#: construction, and that is precisely why it belongs: every MAC fixed rate on
#: the tape is one of seven values (3.00 / 3.25 / 3.50 / 3.75 / 4.00 / 4.25 /
#: 4.50%), and **98.85% of MAC flow legs carry an other payment**. Routing is
#: on upfront presence (LEDGER D6), so a MAC unit lands on the upfront rule by
#: itself with no new machinery — it is the cleanest upfront-rule population
#: on the tape, not a pollutant of the off-market one. 14,877 units come back;
#: the 149 MAC units with no upfront at all are excluded as
#: ``EXCL_STANDARD_COUPON``, because for those the rate rule would produce a
#: large, confident number about a coupon nobody negotiated. **This decision
#: is conditional on the routing rule** — if routing ever stops keying on
#: upfront presence, MAC has to be re-excluded.
#:
#: **IMM — was never excluded, and the measurement says keep it that way.**
#: The premise that IMM is a standard coupon does not survive contact with the
#: tape: IMM flow legs carry an upfront on 37.7% against an outright baseline
#: of 40.9% (i.e. *less* often), their fixed rates sit on a free grid, and
#: their off-market rate is 43.0% against the baseline's 44.1%. An IMM-dated
#: swap is a market-rate trade with an IMM effective date. The one place IMM
#: genuinely misbehaves is the *old* curve — LEDGER F-20 measures ``IMM_2Y`` at
#: a −6.84 bp median against Barchart — and that is a curve defect, not a
#: product defect.
#:
#: **SPREADOVER / SPREADOVER_CURVE / SPREADOVER_FLY — exclusion KEPT.** The
#: direction question is *different*, not harder. What the customer negotiated
#: is the spread to a Treasury, and the instrument on the other side of that
#: spread is not on this tape at any price. Concretely: no quote-weight vector
#: ``q`` over the printed fixed rates satisfies ``P = sum(q_i R_i)`` for the
#: package's actual price, which is exactly the condition
#: :func:`conventions.quote_weights` exists to express — hence
#: ``EXCL_UNORIENTABLE`` rather than a new code. Corroborating measurement:
#: 0.02% of SPREADOVER* legs carry an upfront, so every one of them would be
#: routed to the rate rule and answered from a swap-rate deviation that mixes
#: the dealer's charge on the package with the bond leg's own basis.
#:
#: **MATCHED_MATURITY* and INVOICE* — exclusion KEPT, same argument.** Both are
#: asset swaps; matched-maturity against a specific Treasury, invoice against
#: the CTD of a Treasury future. Same missing leg, same unformable price.
#:
#: The decisive experiment for all three families — is the swap leg of a
#: spreadover struck at the swap mid, or away from it by the package's own
#: bid-offer? — needs the repricing pass and is not available here. Until it
#: is run, the exclusion stands, and its DV01 share is reported so the size of
#: what is being given up is visible rather than assumed small.
#:
#: *Measured membership*, so the list is not read as more evidenced than it is:
#: INVOICE 32,073 · INVOICE_SWITCH 4,916 · INVOICE_CALENDAR 792 are live;
#: ``INVOICE_SWAP`` **does not exist on this tape** and is carried as a
#: defensive spelling only. ``BASIS_CURVE`` (1,150) and ``BASIS_FLY`` (210) are
#: deliberately absent from this list because they all carry
#: ``rate_index_clean = 'BASIS'`` and the index gate, which reads higher in
#: :data:`EXCLUSION_PRECEDENCE`, is the more informative answer for them.
EXCLUDED_TRADE_TYPES = (
    "SPREADOVER", "SPREADOVER_CURVE", "SPREADOVER_FLY",
    "MATCHED_MATURITY", "MATCHED_MATURITY_CURVE", "MATCHED_MATURITY_FLY",
    "INVOICE", "INVOICE_SWAP", "INVOICE_CALENDAR", "INVOICE_SWITCH",
)

#: Exclusions are tested in this order and a unit carries **exactly one**
#: reason. The order is "most informative answer first", not "cheapest test
#: first":
#:
#: 1. the tape says this is not economic flow -- nothing else about it matters;
#: 2. the print is not a negotiated customer decision at all;
#: 3. what product is this (a BASIS leg also has a NULL fixed rate, and
#:    ``UNSUPPORTED_INDEX`` is the answer that tells a reader something);
#: 4. is the question even the one this package asks;
#: 5. can a mid be formed for it;
#: 6. do its own numbers hang together;
#: 7. is there a rate to compare;
#: 8. is the coupon a negotiated one.
EXCLUSION_PRECEDENCE = (
    EXCL_NOT_FLOW,
    EXCL_EXERCISE_OR_NOVATION,
    EXCL_UNSUPPORTED_INDEX,
    EXCL_UNORIENTABLE,
    EXCL_PRICING_ERROR,
    EXCL_RISK_IMPLAUSIBLE,
    EXCL_NO_FIXED_RATE,
    EXCL_STANDARD_COUPON,
)

#: The four columns that would name a swaption exercise or a novation.
#:
#: **Measured: all four are literally ``false`` on all 2,326,781 rows** -- zero
#: TRUE, zero NULL. So are ``is_compression``, ``is_compression_spec``,
#: ``is_reset_optimization`` and ``is_clearing_termination``. The v3 enrichment
#: writes the column and never sets it, which is worse than leaving it NULL: a
#: filter on it returns cleanly and excludes nothing.
#:
#: The consequence is a **known, quantified contamination that this module
#: cannot remove**. A ``NEWT-EXER`` prints at the swaption strike, arbitrarily
#: far from mid and with no fee, so an upfront-presence test calls it
#: on-market and the rate rule answers it loudly and meaninglessly
#: (~374/week); a ``NEWT-NOVA`` (~435/week) is a dealer-to-dealer transfer
#: counted as customer flow. Against ~26,300 legs/week that is ~3.1% of the
#: universe. Nothing else on the tape names them either -- ``tape_tags`` has no
#: EXER/NOVA token, ``lc_status`` is only ACTIVE/TERMINATED/ERRORED, and
#: ``economic_class_reason`` is the same literal string for everything.
#: Recovering them means the raw-slice sidecar (LEDGER F-18).
#:
#: The gate is wired and tested against a synthetic TRUE row anyway, so it
#: starts working the day the enrichment does.
EXERCISE_NOVATION_FLAGS = (
    "is_exercise_born", "is_novation", "is_novation_born",
    "is_novation_terminated",
)

# --- upfront ---------------------------------------------------------------
UPFRONT_PTP = "PTP"
UPFRONT_UFRO = "UFRO_SUM"
UPFRONT_UWIN = "UWIN_SUM"


# ===========================================================================
# per-leg annotation -- ONE implementation, shared by the builder and the report
# ===========================================================================

_SORT_KEYS = ["_unit_group", "_exp", "_eff", "trade_id", "leg_order"]


def annotate_legs(legs: pd.DataFrame) -> pd.DataFrame:
    """Add the per-leg predicate columns and impose the total order.

    Returned sorted and re-indexed. Everything downstream -- unit
    construction *and* the coverage report -- reads these columns and nothing
    else, so the two paths cannot drift apart; a test asserts they agree on
    the same frame.
    """
    df = legs.copy()
    for col, default in (
        ("package_id", None), ("leg_order", 0), ("forward_start_years", 0.0),
        ("other_payment_ufro", 0.0), ("other_payment_uwin", 0.0),
        ("other_payment_pexh", 0.0), ("package_transaction_price", np.nan),
        ("other_payment_amount", np.nan),
        ("upi_notional_schedule", "Constant"), ("leg_tape_label", ""),
        ("special_tenor_type", None), ("is_mac", False), ("is_capped", False),
        ("is_block", False), ("cleared", None), ("platform_identifier", None),
        ("lifecycle_type", None), ("economic_class", None),
        ("event_timestamp_granularity", None), ("report_lag_seconds", np.nan),
    ):
        if col not in df.columns:
            df[col] = default
    for col in EXERCISE_NOVATION_FLAGS:
        if col not in df.columns:
            df[col] = False

    df["_unit_group"] = df["package_id"].where(
        df["package_id"].notna(), df["trade_id"])
    df["_exp"] = pd.to_datetime(df["expiration_date"], errors="coerce")
    df["_eff"] = pd.to_datetime(df["effective_date"], errors="coerce")
    df["leg_order"] = pd.to_numeric(df["leg_order"], errors="coerce").fillna(0)
    df = df.sort_values(_SORT_KEYS, kind="mergesort").reset_index(drop=True)

    df["_not_flow"] = ~df["contributes_to_flow"].fillna(False).astype(bool)
    df["_exer_nova"] = np.logical_or.reduce(
        [df[c].fillna(False).to_numpy(dtype=bool) for c in EXERCISE_NOVATION_FLAGS])
    df["_bad_index"] = ~df["rate_index_clean"].isin(SUPPORTED_INDICES)
    df["_term_sofr"] = (
        df["leg_tape_label"].fillna("").str.contains(TERM_SOFR_TOKEN, regex=False))
    df["_excluded_type"] = df["trade_type"].isin(EXCLUDED_TRADE_TYPES)
    df["_nonconstant"] = df["upi_notional_schedule"].isin(NON_CONSTANT_SCHEDULES)
    df["_no_rate"] = pd.to_numeric(df["fixed_rate"], errors="coerce").isna()

    flags = sanity.flag_risk_implausible(df)
    df["_risk_bad"] = flags["is_risk_implausible"].to_numpy(dtype=bool)
    df["_risk_reason"] = flags["reason"].to_numpy()
    df["_sentinel"] = flags["NOTIONAL_SENTINEL"].to_numpy(dtype=bool)

    # DV01 proxy for the coverage accounting only -- NEVER the tape's `risk`,
    # which carries the 1e20 sentinel, and never anything that reaches a
    # ladder. Sentinel legs contribute zero rather than 1e17, which is the only
    # way the other exclusion shares stay readable.
    dv01 = sanity.expected_dv01(
        pd.to_numeric(df["notional"], errors="coerce"),
        pd.to_numeric(df["tenor_years"], errors="coerce"),
        pd.to_numeric(df["forward_start_years"], errors="coerce"),
    )
    df["_dv01_proxy"] = np.where(
        np.isfinite(dv01) & ~df["_sentinel"].to_numpy(), np.abs(dv01), 0.0)

    df["_venue"] = [classify_venue(p) for p in df["platform_identifier"]]
    df["_is_new_trade"] = df["lifecycle_type"].astype("string").fillna("") == "NEW_TRADE"
    df["_is_unwind"] = (
        df["economic_class"].astype("string").fillna("") == "ECONOMIC_UNWIND")
    return df


def _first_where(df: pd.DataFrame, mask, col: str) -> pd.Series:
    """First value of ``col`` among the masked rows, per unit, in total order."""
    sub = df.loc[mask]
    if sub.empty:
        return pd.Series(dtype=object)
    return sub.groupby("_unit_group", sort=False)[col].first()


def unit_frame(legs: pd.DataFrame) -> pd.DataFrame:
    """One row per classification unit, with its exclusion or lack of one.

    The single source of truth for "what is in the universe". Vectorised
    because the report has to run over 610 days and 1.44M units; the ``Unit``
    objects are materialised from *these* rows, not computed a second way.
    """
    df = annotate_legs(legs)
    if df.empty:
        return pd.DataFrame(columns=[
            "unit_key", "package_id", "as_of_date", "kind", "n_legs",
            "rate_index", "venue_class", "is_lifecycle", "is_unwind",
            "is_block", "is_capped", "is_mac", "has_sentinel", "upfront",
            "upfront_source", "dv01_proxy", "exclusion", "exclusion_detail"])

    grp = df.groupby("_unit_group", sort=False)
    u = grp.agg(
        n_legs=("trade_id", "size"),
        first_trade_id=("trade_id", "first"),
        package_id=("package_id", "first"),
        as_of_date=("as_of_date", "first"),
        rate_index=("rate_index_clean", "first"),
        n_index=("rate_index_clean", "nunique"),
        n_platform=("platform_identifier", "nunique"),
        venue_class=("_venue", "first"),
        all_new_trade=("_is_new_trade", "all"),
        is_unwind=("_is_unwind", "any"),
        is_block=("is_block", "any"),
        is_capped=("is_capped", "any"),
        is_mac=("is_mac", "any"),
        has_sentinel=("_sentinel", "any"),
        dv01_proxy=("_dv01_proxy", "sum"),
        ufro_sum=("other_payment_ufro", "sum"),
        uwin_sum=("other_payment_uwin", "sum"),
        ptp=("package_transaction_price", "first"),
        not_flow=("_not_flow", "any"),
        exer_nova=("_exer_nova", "any"),
        bad_index=("_bad_index", "any"),
        term_sofr=("_term_sofr", "any"),
        excluded_type=("_excluded_type", "any"),
        nonconstant=("_nonconstant", "any"),
        risk_bad=("_risk_bad", "any"),
        no_rate=("_no_rate", "any"),
    )
    u["kind"] = u["n_legs"].map(_kind)
    u["unit_key"] = np.where(u["n_legs"] <= 1, u["first_trade_id"], u.index)
    u["is_lifecycle"] = ~u["all_new_trade"]
    # Measured zero on v3, but a package that mixed platforms would otherwise
    # inherit whichever leg sorted first, silently.
    u.loc[u["n_platform"] > 1, "venue_class"] = VENUE_UNKNOWN

    amt, src = _resolve_upfront_vec(u)
    u["upfront"], u["upfront_source"] = amt, src

    # A PKG-N has no quote convention, but it has one price -- and
    # `package_price.tape_gate` says which of them that price can orient. Only
    # the leg-count half of the gate is relaxed: `excluded_type` (asset swaps)
    # stays ahead of it, because there the missing leg is a bond that is not
    # priced on this tape at all. The gate is curve-free by design so this
    # stays vectorised over 1.44M units.
    pkg4 = u["n_legs"] >= 4
    recovered, pkg_stratum = _package_price_recovery(df, u.index[pkg4])
    recoverable = pd.Series(False, index=u.index, dtype=bool)
    if len(recovered):
        recoverable.loc[recovered.index] = recovered.to_numpy(dtype=bool)

    # --- exclusions, in the pinned precedence ------------------------------
    gates = {
        EXCL_NOT_FLOW: u["not_flow"],
        EXCL_EXERCISE_OR_NOVATION: u["exer_nova"],
        EXCL_UNSUPPORTED_INDEX: u["bad_index"] | u["term_sofr"] | (u["n_index"] > 1),
        EXCL_UNORIENTABLE: u["excluded_type"] | (pkg4 & ~recoverable),
        EXCL_PRICING_ERROR: u["nonconstant"],
        EXCL_RISK_IMPLAUSIBLE: u["risk_bad"],
        EXCL_NO_FIXED_RATE: u["no_rate"],
        EXCL_STANDARD_COUPON: u["is_mac"] & u["upfront"].isna(),
    }
    u["exclusion"] = None
    for reason in EXCLUSION_PRECEDENCE:
        hit = gates[reason] & u["exclusion"].isna()
        u.loc[hit, "exclusion"] = reason

    u["_pkg_stratum"] = pkg_stratum.reindex(u.index)
    u["exclusion_detail"] = _details(df, u, gates)
    cols = ["unit_key", "package_id", "as_of_date", "kind", "n_legs",
            "rate_index", "venue_class", "is_lifecycle", "is_unwind",
            "is_block", "is_capped", "is_mac", "has_sentinel", "upfront",
            "upfront_source", "dv01_proxy", "exclusion", "exclusion_detail"]
    return u[cols]


def _details(df: pd.DataFrame, u: pd.DataFrame, gates: dict) -> pd.Series:
    """A free-text detail beside the pinned constant.

    Needed because one constant covers several distinct populations --
    ``EXCL_UNORIENTABLE`` is both "asset swap, wrong question" and "PKG-N, no
    quote convention", and the report has to tell them apart. The constant
    stays from the ``types.py`` vocabulary so the accounting keeps adding up.
    """
    out = pd.Series([None] * len(u), index=u.index, dtype=object)

    def put(reason, values):
        m = (u["exclusion"] == reason) & out.isna()
        out.loc[m] = values.reindex(u.index[m]).to_numpy()

    put(EXCL_NOT_FLOW, _first_where(df, df["_not_flow"], "economic_class"))
    put(EXCL_UNSUPPORTED_INDEX, _first_where(
        df, df["_bad_index"], "rate_index_clean"))
    put(EXCL_UNORIENTABLE, _first_where(df, df["_excluded_type"], "trade_type"))
    put(EXCL_RISK_IMPLAUSIBLE, _first_where(df, df["_risk_bad"], "_risk_reason"))

    m = (u["exclusion"] == EXCL_UNSUPPORTED_INDEX) & out.isna()
    out.loc[m & u["term_sofr"]] = "CME_TERM_SOFR"
    out.loc[(u["exclusion"] == EXCL_UNSUPPORTED_INDEX) & out.isna()] = "MIXED_INDEX"
    # One bucket per REASON, not one per leg count: the exact count is already
    # on the unit row as `n_legs`, and a per-N detail fragments the coverage
    # table into ~90 rows that each carry a fifth of a percent. Since the
    # package-price rule now recovers part of this population, "PKG-4+" alone
    # would no longer say why the rest was given up -- the stratum does.
    m = (u["exclusion"] == EXCL_UNORIENTABLE) & out.isna()
    strat = u["_pkg_stratum"] if "_pkg_stratum" in u.columns else None
    if strat is not None:
        out.loc[m] = ("PKG-4+/" + strat.reindex(u.index[m]).astype(object)
                      .fillna("UNKNOWN")).to_numpy()
    out.loc[(u["exclusion"] == EXCL_UNORIENTABLE) & out.isna()] = "PKG-4+"
    out.loc[u["exclusion"] == EXCL_PRICING_ERROR] = "NOTIONAL_SCHEDULE_NOT_CONSTANT"
    out.loc[u["exclusion"] == EXCL_EXERCISE_OR_NOVATION] = "EXERCISE_OR_NOVATION_FLAG"
    out.loc[u["exclusion"] == EXCL_STANDARD_COUPON] = "MAC_NO_UPFRONT"
    return out


def _package_price_recovery(df: pd.DataFrame, groups) -> tuple:
    """Which ``PKG-N`` units :mod:`.package_price` can orient, and why not.

    Runs the gate on the ``PKG-4+`` groups only. Everything else on the tape is
    already orientable by quote convention, and the solver inside the gate is
    per-package work -- restricting it to the ~47k packages that need it is
    what keeps :func:`unit_frame` a whole-window call.
    """
    empty = pd.Series(dtype=bool), pd.Series(dtype=object)
    if len(groups) == 0:
        return empty
    sub = df.loc[df["_unit_group"].isin(set(groups)),
                 list(package_price.GATE_COLUMNS)]
    if sub.empty:
        return empty
    gate = package_price.tape_gate(sub)
    return gate["recoverable"], gate["stratum"]


def _kind(n_legs: int) -> str:
    return {1: "OUTRIGHT", 2: "CURVE", 3: "FLY"}.get(int(n_legs), "PKG")


# ===========================================================================
# upfront
# ===========================================================================

def _resolve_upfront_vec(u: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Unit upfront and its provenance. See :func:`resolve_upfront`."""
    ptp = pd.to_numeric(u["ptp"], errors="coerce").abs()
    ptp = ptp.where(ptp > _sf_config.PTP_USD_FLOOR)
    ufro = pd.to_numeric(u["ufro_sum"], errors="coerce").fillna(0.0).abs()
    uwin = pd.to_numeric(u["uwin_sum"], errors="coerce").fillna(0.0).abs()

    amt = pd.Series(np.nan, index=u.index, dtype=float)
    # `pd.Series(None, index=..., dtype=object)` broadcasts the scalar to NaN,
    # not to None, so an unset source reads back as the float nan and any
    # `str(...)` of it becomes the literal "nan".
    src = pd.Series([None] * len(u), index=u.index, dtype=object)
    # UWIN is taken whenever it is the only component present, and outranks
    # UFRO only on a lifecycle print, where the fee IS a settlement. Dropping
    # a UWIN just because the row says NEW_TRADE would throw away 12 real
    # settlements (up to $35.6mm) and route those units to the rate rule --
    # which is the failure this module exists to prevent.
    take = (uwin > 0) & (u["is_lifecycle"] | (ufro <= 0))
    amt.loc[take], src.loc[take] = uwin.loc[take], UPFRONT_UWIN
    take = amt.isna() & (ufro > 0)
    amt.loc[take], src.loc[take] = ufro.loc[take], UPFRONT_UFRO
    take = ptp.notna()
    amt.loc[take], src.loc[take] = ptp.loc[take], UPFRONT_PTP
    return amt, src


def resolve_upfront(legs: pd.DataFrame, *, is_lifecycle: bool) -> tuple:
    """``(amount, source)`` for one unit's legs. ``(None, None)`` when there is none.

    Three rules, and the reason each is a rule rather than a sum:

    **UWIN is routed in; on a lifecycle print it outranks UFRO.**
    ``stir_flow.classifier`` reads ``other_payment_ufro`` alone, and ``UWIN``
    is the unwind-settlement fee -- so on paper terminations had nothing to
    compare an NPV against. Measured, that story is wrong twice over:
    ``other_payment_uwin`` is non-zero on **15 legs of the entire 2.33M-row
    tape**, of which exactly **one** is a TERMINATION, while **11,587 of
    50,790 TERMINATION legs (22.8%) already carry a UFRO**. Terminations were
    never fee-less; the gap was one row, not fifty thousand. The rule is still
    right and costs nothing, and it is written down here precisely so the
    false premise is not re-derived from the code.

    The 12 UWIN legs stamped ``NEW_TRADE`` (up to $35.6mm) are taken too, on
    the grounds that a settlement fee is still a fee and the alternative is
    routing a visibly off-market print to the rate rule. Lifecycle status only
    decides *precedence* when both components are present -- which, measured,
    never happens.

    **Measured net effect of the whole change: zero.** All 15 UWIN legs resolve
    a UWIN-sourced upfront and all 15 are then excluded for an unrelated
    reason -- 13 are Term SOFR prints and 2 carry a non-constant notional
    schedule. The rule is kept because it is right, not because it does
    anything here; what it buys is that the first non-Term-SOFR unwind fee to
    appear does not silently route to the rate rule.

    **The categories are never summed.** ``core/other_payments.py`` states
    that UFRO (premium), UWIN (settlement) and PEXH (exercise) are mutually
    distinct and must not be aggregated -- they answer different questions
    about different events, so their sum is not a quantity. Measured: no row
    carries two of them, so the rule is free today; it is written down for the
    day one does.

    **PEXH is not an upfront at all.** An early-exercise settlement is not a
    fee against a printed rate. Aggregating it would hand a swaption exercise
    to the upfront rule and get a confident answer to a question the print
    does not pose. Two legs on the whole tape carry one; they end up on the
    rate rule and are reported.

    ``PTP`` keeps ``stir_flow``'s precedence -- a package transaction price
    above ``PTP_USD_FLOOR`` **in absolute value** is the package's own fee in
    dollars and outranks a leg-level sum. Below the floor the field is carrying
    a price in points, not a dollar amount.

    **The ``abs()`` on PTP is load-bearing, not defensive.** Measured on v3:
    382,815 legs carry a ``package_transaction_price`` below -500 against
    403,314 above +500, i.e. the field's sign is a direction of payment and
    roughly half the population is negative. (``other_payment_ufro``, by
    contrast, is non-negative on every row of the tape, so the ``abs()`` there
    really is defensive.) Compare a raw PTP against the floor instead and every
    one of those 382,815 reads as *no fee*: the unit silently falls through to
    the UFRO sum or to the rate rule, with a real, large, reported fee unused.
    ``Unit.upfront`` is documented unsigned and the frozen
    ``trade_selection.resolve_upfront`` takes ``abs()`` too; a test ties out
    against it on a negative price.
    """
    u = pd.DataFrame([{
        "ptp": next((v for v in legs.get(
            "package_transaction_price", pd.Series(dtype=float)) if pd.notna(v)),
            np.nan),
        "ufro_sum": pd.to_numeric(
            legs.get("other_payment_ufro"), errors="coerce").fillna(0.0).sum(),
        "uwin_sum": pd.to_numeric(
            legs.get("other_payment_uwin"), errors="coerce").fillna(0.0).sum(),
        "is_lifecycle": bool(is_lifecycle),
    }])
    amt, src = _resolve_upfront_vec(u)
    a, s = amt.iloc[0], src.iloc[0]
    return ((None if pd.isna(a) else float(a)),
            (None if s is None or pd.isna(s) else str(s)))


# ===========================================================================
# clocks
# ===========================================================================

def build_clocks(row: dict, *, lifecycle_type, is_block, is_capped,
                 cleared, platform_identifier) -> tuple[Clocks, str]:
    """The unit's four timestamps, plus which field the pricing clock came from.

    ``lifecycle_type`` is passed separately because it is a **unit** property
    and ``row`` is a leg: 6,028 packages mix it. A package is treated as
    UTI-minting only when *every* leg is, because #30 is correct for a NEWT row
    as well as a lifecycle one while #96 is correct only for the former --
    so the mixed case has one safe answer and it is #30.

    **Visibility is measured from the pricing instant, not from #96.**
    ``ladder_conventions.visibility_timestamp`` takes an execution timestamp,
    and #96 on a lifecycle row is frozen at the original trade (Appendix F
    Example 3: twenty months stale). Handing it #96 would date a termination's
    public visibility to before the termination happened -- and, like every
    other clock bug here, it would not raise.
    """
    r = dict(row)
    r["lifecycle_type"] = lifecycle_type
    instant, field = snapshot.pricing_timestamp(r)

    cls = _ladder.visibility_class(
        is_block=_pybool(is_block),
        cleared=cleared_flag(cleared),
        on_facility=on_facility(platform_identifier),
        is_capped=_pybool(is_capped),
    )
    visible = pd.Timestamp(instant) + pd.Timedelta(
        minutes=_ladder.VISIBILITY_DELAYS_MIN[cls])
    source = f"APPENDIX_C:{cls}"
    if field == snapshot.CLOCK_EOD_FALLBACK:
        source += ":EOD"

    lag = row.get("report_lag_seconds")
    return Clocks(
        pricing=instant,
        execution=_ts(row.get("execution_timestamp")),
        event=_ts(row.get("event_timestamp")),
        visibility=visible,
        visibility_source=source,
        report_lag_seconds=None if lag is None or pd.isna(lag) else float(lag),
    ), field


def _pybool(v) -> bool | None:
    """``numpy.True_ is True`` is **False**.

    ``visibility_class`` tests identity (``on_facility is True``) on purpose,
    so that a ``None`` can never satisfy a branch -- which means a numpy bool
    arriving from a DataFrame column silently falls through to
    ``INDETERMINATE`` and every print gets the 60-minute delay.
    """
    if v is None or (isinstance(v, float) and v != v):
        return None
    return bool(v)


def _ts(v):
    return None if v is None or pd.isna(v) else pd.Timestamp(v)


# ===========================================================================
# unit construction
# ===========================================================================

def build_universe(legs: pd.DataFrame) -> tuple[list[Unit], pd.DataFrame]:
    """``(kept units, excluded unit rows)``.

    Both come off the same :func:`unit_frame`, so a unit cannot be counted in
    one and missing from the other.

    ``Unit.legs`` is the annotated frame, index reset to ``0..n-1`` in the
    total order -- so ``iloc[0]`` is the front leg of a CURVE and ``iloc[1]``
    is the belly of a FLY, which is exactly what
    :func:`conventions.base_orientation` documents itself as assuming. The
    underscore-prefixed helper columns are left on deliberately: a downstream
    module that wants the sanity reason or the DV01 proxy should not have to
    recompute it.
    """
    df = annotate_legs(legs)
    u = unit_frame(legs)
    if u.empty:
        return [], u

    excluded = u[u["exclusion"].notna()].copy()
    kept_keys = u.index[u["exclusion"].isna()]
    if len(kept_keys) == 0:
        return [], excluded

    by_group = {k: v for k, v in df.groupby("_unit_group", sort=False)}
    units: list[Unit] = []
    for key in kept_keys:
        row = u.loc[key]
        unit_legs = by_group[key].reset_index(drop=True)
        head = unit_legs.iloc[0].to_dict()
        lifecycle = ("NEW_TRADE" if bool(unit_legs["_is_new_trade"].all())
                     else _first_non_new_trade(unit_legs))
        clocks, _field = build_clocks(
            head,
            lifecycle_type=lifecycle,
            is_block=row["is_block"],
            is_capped=row["is_capped"],
            cleared=head.get("cleared"),
            platform_identifier=head.get("platform_identifier"),
        )
        units.append(Unit(
            unit_key=str(row["unit_key"]),
            kind=str(row["kind"]),
            legs=unit_legs,
            package_id=(None if int(row["n_legs"]) <= 1
                        else _none_if_na(row["package_id"])),
            rate_index=str(row["rate_index"]),
            as_of_date=_as_date(row["as_of_date"]),
            venue_class=str(row["venue_class"]),
            clocks=clocks,
            upfront=(None if pd.isna(row["upfront"]) else float(row["upfront"])),
            upfront_source=_none_if_na(row["upfront_source"]),
            is_lifecycle=bool(row["is_lifecycle"]),
            is_block=bool(row["is_block"]),
            is_capped=bool(row["is_capped"]),
        ))
    return units, excluded


def build_units(legs: pd.DataFrame) -> list[Unit]:
    """The kept units only. Same call as :func:`build_universe`, first half."""
    return build_universe(legs)[0]


def _first_non_new_trade(unit_legs: pd.DataFrame):
    bad = unit_legs.loc[~unit_legs["_is_new_trade"], "lifecycle_type"]
    return None if bad.empty else bad.iloc[0]


def _none_if_na(v):
    return None if v is None or pd.isna(v) else str(v)


def _as_date(v) -> datetime.date:
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    return pd.Timestamp(v).date()


# ===========================================================================
# the measured universe
# ===========================================================================

def summarise(legs: pd.DataFrame) -> dict:
    """Coverage accounting over a legs frame. Never builds ``Unit`` objects."""
    return aggregate_units(unit_frame(legs))


def aggregate_units(u: pd.DataFrame) -> dict:
    """The coverage tables, from a unit frame.

    Separate from :func:`summarise` only so the 610-day report can reduce each
    month to unit rows and aggregate once at the end, instead of holding every
    leg of the tape in memory. It is the **same aggregation**, not a second
    one -- a report that computes its numbers a different way from the builder
    is a report that eventually disagrees with it.

    DV01 shares use the annuity proxy (:func:`sanity.expected_dv01`), never
    the tape's ``risk`` (F-4). Legs carrying the notional sentinel contribute
    **zero** proxy DV01 and are counted under ``sentinel_units``; leaving 1e20
    in the denominator would put 99.99994% of the total on 55 rows and read
    every other share as zero.
    """
    if u.empty:
        empty = pd.DataFrame()
        return {"kept_units": 0, "excluded_units": 0, "sentinel_units": 0,
                "unwind_units_kept": 0, "lifecycle_units_kept": 0,
                "dv01_proxy_total": 0.0, "dv01_proxy_kept": 0.0,
                "by_reason": empty, "by_constant": empty, "by_venue": empty,
                "by_kind": empty, "by_upfront": empty, "per_day": empty}

    kept = u[u["exclusion"].isna()]
    excl = u[u["exclusion"].notna()]
    total_dv01 = float(u["dv01_proxy"].sum())

    by_reason = (excl.assign(reason=excl["exclusion"].astype(str) + " / "
                             + excl["exclusion_detail"].astype(object).fillna("-"))
                 .groupby("reason", observed=True)
                 .agg(n_units=("n_legs", "size"), n_legs=("n_legs", "sum"),
                      dv01_proxy=("dv01_proxy", "sum"))
                 .sort_values("dv01_proxy", ascending=False))
    by_reason["dv01_share_pct"] = (
        100.0 * by_reason["dv01_proxy"] / total_dv01 if total_dv01 else np.nan)

    by_constant = (excl.groupby("exclusion", observed=True)
                   .agg(n_units=("n_legs", "size"), n_legs=("n_legs", "sum"),
                        dv01_proxy=("dv01_proxy", "sum"))
                   .sort_values("dv01_proxy", ascending=False))
    by_constant["dv01_share_pct"] = (
        100.0 * by_constant["dv01_proxy"] / total_dv01 if total_dv01 else np.nan)

    by_venue = (kept.groupby("venue_class", observed=True)
                .agg(n_units=("n_legs", "size"), n_legs=("n_legs", "sum"),
                     dv01_proxy=("dv01_proxy", "sum"),
                     n_lifecycle=("is_lifecycle", "sum"),
                     n_with_upfront=("upfront", "count"))
                .sort_values("dv01_proxy", ascending=False))
    # NOT `dv01_share_pct`: this one is a share of the KEPT total, while
    # `by_reason` and `by_constant` are shares of the whole universe. Three
    # columns under one name in one report is how two denominators get read as
    # one -- the venue lines would sum to 100% beside exclusion lines that sum
    # to the excluded share, and nothing on the page would say why.
    by_venue["dv01_share_of_kept_pct"] = (
        100.0 * by_venue["dv01_proxy"] / by_venue["dv01_proxy"].sum()
        if len(by_venue) else np.nan)

    by_kind = (kept.groupby(["kind", "rate_index"], observed=True)
               .agg(n_units=("n_legs", "size"), n_legs=("n_legs", "sum"),
                    dv01_proxy=("dv01_proxy", "sum"),
                    n_with_upfront=("upfront", "count"),
                    n_lifecycle=("is_lifecycle", "sum"))
               .sort_values("n_units", ascending=False))

    by_upfront = (kept.groupby(kept["upfront_source"].astype(object).fillna("(none)"), observed=True)
                  .agg(n_units=("n_legs", "size"),
                       dv01_proxy=("dv01_proxy", "sum"))
                  .sort_values("n_units", ascending=False))

    per_day = (u.groupby("as_of_date", observed=True)
               .agg(units=("n_legs", "size"),
                    kept=("exclusion", lambda s: int(s.isna().sum())),
                    dv01_proxy=("dv01_proxy", "sum")))
    per_day["kept_pct"] = 100.0 * per_day["kept"] / per_day["units"]

    return {
        "kept_units": int(len(kept)),
        "excluded_units": int(len(excl)),
        "sentinel_units": int(u["has_sentinel"].sum()),
        # Reported because nothing else in this module counts them and the
        # measured denominators quoted throughout it do not include them. See
        # the module docstring, "WHAT `contributes_to_flow` ADMITS".
        "unwind_units_kept": int(kept["is_unwind"].sum()),
        "lifecycle_units_kept": int(kept["is_lifecycle"].sum()),
        "dv01_proxy_total": total_dv01,
        "dv01_proxy_kept": float(kept["dv01_proxy"].sum()),
        "by_reason": by_reason,
        "by_constant": by_constant,
        "by_venue": by_venue,
        "by_kind": by_kind,
        "by_upfront": by_upfront,
        "per_day": per_day,
    }


# ===========================================================================
# loading
# ===========================================================================

#: Everything the universe, the clocks and the sanity gate need, and nothing
#: else. No ``WHERE`` beyond the date range on purpose: every eligibility test
#: has to be a *counted* exclusion, so filtering in SQL would make the
#: denominator unknowable. The packages table is not joined -- measured, the
#: legs' own ``package_transaction_price`` differs from it on 870 of 2,326,781
#: rows (0.037%), the leg count always matches ``n_package_legs``, and no
#: package spans an ``as_of_date``.
LEG_COLUMNS = (
    "trade_id", "package_id", "leg_order", "as_of_date",
    "execution_timestamp", "original_execution_timestamp", "event_timestamp",
    "event_timestamp_granularity", "report_lag_seconds", "lifecycle_type",
    "economic_class", "contributes_to_flow",
    "effective_date", "expiration_date", "tenor_years", "forward_start_years",
    "notional", "risk", "fixed_rate",
    "other_payment_amount", "other_payment_ufro", "other_payment_uwin",
    "other_payment_pexh", "package_transaction_price",
    "trade_type", "rate_index_clean", "special_tenor_type",
    "upi_notional_schedule", "leg_tape_label",
    "platform_identifier", "venue", "cleared",
    "is_mac", "is_capped", "is_block", "is_off_market",
    *EXERCISE_NOVATION_FLAGS,
)

LEGS_SQL = f"""
SELECT {", ".join(LEG_COLUMNS)}
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(start)s AND %(end)s
ORDER BY package_id, expiration_date, effective_date, trade_id, leg_order
"""


def load_legs(conn, start, end) -> pd.DataFrame:
    """Read the raw legs for a date range. Read-only; the tape is production."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(LEGS_SQL, conn, params={"start": start, "end": end})


def _report(start: str | None, end: str | None) -> int:
    import gc
    import os
    import warnings

    import psycopg2

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.max_columns", 40)

    conn = psycopg2.connect(resolve_pg_url())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bounds = pd.read_sql(
            f"SELECT min(as_of_date) lo, max(as_of_date) hi FROM {LEGS_TABLE}", conn)
    lo = pd.Timestamp(start or bounds["lo"].iloc[0])
    hi = pd.Timestamp(end or bounds["hi"].iloc[0])
    print(f"tape {lo.date()} .. {hi.date()}")

    frames, n_legs_seen = [], 0
    for chunk_lo in pd.date_range(lo, hi, freq="MS", inclusive="both").union(
            pd.DatetimeIndex([lo])):
        chunk_hi = min(chunk_lo + pd.offsets.MonthEnd(0), hi)
        if chunk_hi < chunk_lo:
            continue
        part = load_legs(conn, chunk_lo.date(), chunk_hi.date())
        n_legs_seen += len(part)
        u = _slim(unit_frame(part))
        empty = "   <- EMPTY" if len(part) == 0 else ""
        print(f"  {chunk_lo.date()}..{chunk_hi.date()}  {len(part):>8,} legs "
              f"-> {len(u):>7,} units{empty}", flush=True)
        del part
        frames.append(u)
        gc.collect()
    conn.close()
    print(f"  legs read: {n_legs_seen:,}")

    # A range that returns nothing is a failed report, not a report of nothing.
    # Without this the loop prints `0 legs -> 0 units` for every month, the
    # aggregation returns its zero dict, and the run exits 0 -- and the caller
    # cannot tell an empty tape from a wrong date range or a connection served
    # from the wrong database.
    u = pd.concat(frames, ignore_index=False) if frames else pd.DataFrame()
    if n_legs_seen == 0 or len(u) == 0:
        print(f"NO DATA: {n_legs_seen:,} legs / {len(u):,} units over "
              f"{lo.date()}..{hi.date()}. Nothing was measured; this is a "
              "failure, not an empty result.")
        return 2
    _print_report(aggregate_units(u), u)
    return 0


#: Columns :func:`aggregate_units` actually reads. The 610-day report holds
#: 1.44M unit rows at once, so it drops the identifiers it does not aggregate
#: and categorises the low-cardinality strings; that is a ~10x cut in resident
#: size and the difference between the report running and the interpreter
#: failing to allocate 485 KiB, which is what it did.
_AGG_COLUMNS = ("as_of_date", "kind", "n_legs", "rate_index", "venue_class",
                "is_lifecycle", "is_unwind", "is_capped", "is_block", "is_mac",
                "has_sentinel", "upfront", "upfront_source",
                "dv01_proxy", "exclusion", "exclusion_detail")
_AGG_CATEGORICAL = ("kind", "rate_index", "venue_class", "upfront_source",
                    "exclusion", "exclusion_detail")


def _slim(u: pd.DataFrame) -> pd.DataFrame:
    u = u[list(_AGG_COLUMNS)].copy()
    for c in _AGG_CATEGORICAL:
        u[c] = u[c].astype("category")
    return u


_RELAXATIONS = """
EVERY DEVIATION FROM THE FROZEN `stir_flow` FILTER SET, STATED UP FRONT
  REMOVED  the 1105-day maturity cutoff            (73.0% of flow legs -- 1,671,827
           of 2,289,646, measured as the filter is written; the tenor>3.02y proxy
           is a different and 3.3pp smaller 1,595,321)
  REMOVED  MAC from EXCLUDED_TRADE_TYPES           (98.85% of MAC legs carry a fee)
  ADDED    Term SOFR -> UNSUPPORTED_INDEX          (33,487 legs; gated on the label
           alone, so it is wider than the 32,842 label-and-index pair)
  ADDED    non-Constant notional -> PRICING_ERROR  (48,937 flow legs, no schedule on the tape)
  REPLACED the "Amortizing" label token with `upi_notional_schedule`
           (NOT because the token misses amortisers -- measured, the two select the
           same 35,470 legs 1:1 -- but because it has no word for Custom 11,960 or
           Accreting 1,507, which are equally not bullets)
  ADDED    D2C: TREU TWEM BMTF BTFE TRWB           (+53,664 legs, registry tier)
  ADDED    D2D: ISWE GSEF BGCO RTXF                (+17,251 legs; RTXF fingerprint tier)
  ADDED    on-facility = "in VENUE_EVIDENCE and not off-facility", superseding
           ladder_conventions.SEF_PLATFORM_CODES (the 8 incumbents). The 9 added
           MTF/SEF codes (~70,700 legs) move from INDETERMINATE (+60 min) to their
           Appendix C class -- a SHORTER availability delay, so it is the direction
           that can leak lookahead, and it is the one deviation here that changes a
           clock rather than an admission.
  ADDED    UWIN as an upfront source               (net effect: ZERO kept units --
           all 15 UWIN legs on the tape are Term SOFR or amortising and are
           excluded anyway. The brief's premise that terminations have no fee is
           false for a second reason too: 11,587 of 50,790 already carry a UFRO.)
  KEPT     SPREADOVER* / MATCHED_MATURITY* / INVOICE* excluded -- the DV01 share
           of that decision is in the table below and it is the largest single line
  UNCHANGED and UNFIXABLE: NEWT-EXER / NEWT-NOVA cannot be excluded. All four
           tape flags are literally `false` on all 2,326,781 rows. ~3.1% of legs.
  UNCHANGED and OPEN: 36,828 ECONOMIC_UNWIND legs are `contributes_to_flow` and
           36,763 of them are stamped NEW_TRADE, so they enter the PRIMARY series.
           Re-tagging them is_lifecycle would invert their sign (upfront.py:305);
           they are counted below instead. See the module docstring.
"""


def _print_report(rep: dict, u: pd.DataFrame) -> None:
    n = rep["kept_units"] + rep["excluded_units"]
    if n == 0:
        raise ValueError("nothing to report: 0 units")
    print(_RELAXATIONS)
    print()
    print("=" * 84)
    print("UNITS")
    print("=" * 84)
    print(f"  units            {n:>12,}")
    print(f"  kept             {rep['kept_units']:>12,}  "
          f"({100*rep['kept_units']/n:.2f}%)")
    print(f"  excluded         {rep['excluded_units']:>12,}")
    print(f"  notional-sentinel units (DV01 proxy forced to 0) "
          f"{rep['sentinel_units']:>6,}")
    tot = rep["dv01_proxy_total"]
    print(f"  DV01 proxy total {tot:>15,.0f}")
    print(f"  DV01 proxy kept  {rep['dv01_proxy_kept']:>15,.0f}  "
          + (f"({100*rep['dv01_proxy_kept']/tot:.2f}%)" if tot else "(n/a)"))
    p = rep["per_day"]
    print(f"  days             {len(p):>12,}   units/day "
          f"min {p['units'].min():,} · median {p['units'].median():,.0f} · "
          f"max {p['units'].max():,}")
    print(f"  kept/day         median {p['kept'].median():,.0f}  "
          f"({p['kept_pct'].median():.1f}%)")

    print()
    print("=" * 84)
    print("EXCLUSIONS by pinned constant -- DV01 share of the whole universe")
    print("=" * 84)
    print(rep["by_constant"].to_string())

    print()
    print("=" * 84)
    print("EXCLUSIONS by constant / detail")
    print("=" * 84)
    print(rep["by_reason"].to_string())

    print()
    print("=" * 84)
    print("VENUE (kept units only; D2D is kept and tagged, never customer flow)")
    print("=" * 84)
    print(rep["by_venue"].to_string())

    print()
    print("=" * 84)
    print("STRUCTURE MIX (kept units)")
    print("=" * 84)
    print(rep["by_kind"].to_string())

    print()
    print("=" * 84)
    print("UPFRONT SOURCE (kept units) -- '(none)' is what routes to the rate rule")
    print("=" * 84)
    print(rep["by_upfront"].to_string())

    print()
    print("=" * 84)
    print("TIE-OUTS -- each against a SQL measurement made before the code existed")
    print("=" * 84)
    kept0 = u[u["exclusion"].isna()]
    # 14,877 / 149 is what SQL said BEFORE the other gates existed; the 25-unit
    # gap is MAC units caught by a higher-precedence reason and it reconciles
    # exactly: 14,877 = 14,856 + 21 UNORIENTABLE, 149 = 145 + 4 UNSUPPORTED_INDEX.
    print(f"  MAC units kept                     {int(kept0['is_mac'].sum()):>9,}"
          "   (14,877 pre-gate, less 21 UNORIENTABLE)")
    print(f"  MAC units excluded (no upfront)    "
          f"{int(u.loc[u['exclusion'] == EXCL_STANDARD_COUPON, 'is_mac'].sum()):>9,}"
          "   (149 pre-gate, less 4 UNSUPPORTED_INDEX)")
    print(f"  MAC units, all reasons             {int(u['is_mac'].sum()):>9,}"
          "   (SQL said 15,026)")
    print(f"  notional-sentinel units            {rep['sentinel_units']:>9,}"
          "   (SQL said 55) -- all excluded, verified per-leg")
    print(f"  capped units kept                  {int(kept0['is_capped'].sum()):>9,}")
    print(f"  block units kept                   {int(kept0['is_block'].sum()):>9,}")

    print()
    print("=" * 84)
    print("LIFECYCLE (kept units) -- terminations are a separate series (D8)")
    print("=" * 84)
    kept = u[u["exclusion"].isna()]
    print(kept.groupby("is_lifecycle", observed=True)
          .agg(n_units=("n_legs", "size"), n_legs=("n_legs", "sum"),
               dv01_proxy=("dv01_proxy", "sum"),
               n_with_upfront=("upfront", "count")).to_string())
    print()
    print(f"  ECONOMIC_UNWIND units kept  {rep['unwind_units_kept']:>9,}"
          "   <- admitted into the PRIMARY series, not the lifecycle one")
    print(f"  of which flagged lifecycle  "
          f"{int((kept['is_unwind'] & kept['is_lifecycle']).sum()):>9,}")
    print("  These are backdated NEW_TRADEs, so `lifecycle_type` does not see")
    print("  them; see the module docstring for why re-tagging them is NOT the")
    print("  fix and what the open question actually is.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()
    if args.report:
        raise SystemExit(_report(args.start, args.end))
    print(__doc__)


__all__ = [
    "EVIDENCE_FINGERPRINT", "EVIDENCE_OFF_FACILITY", "EVIDENCE_REGISTRY",
    "EVIDENCE_UNRECOGNISED", "EXCLUDED_TRADE_TYPES", "EXCLUSION_PRECEDENCE",
    "EXERCISE_NOVATION_FLAGS", "LEGS_SQL", "LEG_COLUMNS",
    "NON_CONSTANT_SCHEDULES", "OFF_FACILITY_CODES", "OFF_FACILITY_PLATFORMS",
    "SUPPORTED_INDICES", "TERM_SOFR_TOKEN", "UPFRONT_PTP", "UPFRONT_UFRO",
    "UPFRONT_UWIN", "VENUE_EVIDENCE", "D2C_PLATFORMS", "D2D_PLATFORMS",
    "annotate_legs", "build_clocks", "build_units", "build_universe",
    "classify_venue", "cleared_flag", "load_legs", "on_facility",
    "aggregate_units", "resolve_upfront", "summarise", "unit_frame",
    "venue_evidence",
]
