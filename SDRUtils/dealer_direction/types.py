"""The data contract. Every module in this package produces or consumes these.

Written before the implementations so the interfaces are fixed by design
rather than by whichever module happened to be built first.
"""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd

# --- exclusion reasons ----------------------------------------------------
# One vocabulary, so the coverage accounting adds up and nothing is dropped
# without a name. Every unit that does not reach the ladder carries exactly one
# of these plus its DV01 share, which is what the written note reports.
#
# **This is not the only stratum set.** ``package_price.STRATA`` names the
# ``PKG_*`` reasons a ``PKG-N`` can fail its own recovery -- the units
# :data:`EXCL_UNORIENTABLE` used to absorb whole. They are deliberately NOT
# copied here: that module imports this one and cannot be made to import them
# back, so a copy would be two spellings free to drift, and the set has already
# grown once. A consumer tabulating exclusions must union this vocabulary with
# ``package_price.STRATA`` and read it from there rather than restating it;
# note that ``package_price.EXCL_PRICING_ERROR`` is an alias of the constant
# below and must not be counted twice.
EXCL_RISK_IMPLAUSIBLE = "RISK_IMPLAUSIBLE"        # the 1e20 / 9.9 spec sentinels
EXCL_UNORIENTABLE = "UNORIENTABLE_PKG"            # PKG-N, no quote convention
EXCL_NO_FIXED_RATE = "NO_FIXED_RATE"
EXCL_NOT_FLOW = "NOT_ECONOMIC_FLOW"
EXCL_STANDARD_COUPON = "STANDARD_COUPON"          # MAC / IMM, off-market by design
EXCL_EXERCISE_OR_NOVATION = "EXERCISE_OR_NOVATION"  # prints at strike, or D2D
EXCL_NO_CURVE = "NO_CURVE"                        # SnapshotMiss
EXCL_PRICING_ERROR = "PRICING_ERROR"
EXCL_DEAD_ZONE = "DEAD_ZONE"                      # reported, not a failure
EXCL_UNSUPPORTED_INDEX = "UNSUPPORTED_INDEX"      # BASIS / OTHER

#: Venue classes. D2D is kept as its own series and never merged into customer
#: flow -- dealers recycling risk among themselves is informative, but it is
#: not inventory being loaded.
VENUE_D2C = "D2C"
VENUE_D2D = "D2D"
VENUE_UNKNOWN = "VENUE_UNKNOWN"


@dataclasses.dataclass(frozen=True)
class Clocks:
    """The three timestamps, kept apart on purpose.

    Conflating the first two is the most dangerous modelling error available
    here, and the third exists because neither of the first two is an
    availability bound.

    **KNOWN GAP -- the pricing clock's provenance is not carried here.**
    ``universe.build_clocks`` computes which field :attr:`pricing` came from
    (one of the three ``snapshot.CLOCK_*`` values) and returns it as a second
    result, but ``universe.build_universe`` discards it (``clocks, _field =
    build_clocks(...)``), so a :class:`Unit` cannot say whether its pricing
    instant is #96, #30, or the date-only EOD degradation. ``provenance.build``
    still *requires* ``pricing_clock_field``, so any producer wiring the two
    together today has to re-derive it from the raw leg. The field belongs on
    this class -- adding it is a one-line change here and a one-line change in
    ``universe.build_universe``, and it must be made in the same commit: a
    defaulted field that only the test producers populate is worse than this
    note, because ``None`` would then mean both "unknown" and "not wired" and
    no consumer could tell them apart.
    """

    #: When the trade was struck. Drives the curve snapshot, and nothing else.
    #: **Not always field #96**: on any row that does not mint a new UTI, #96 is
    #: frozen at the ORIGINAL trade's execution and can be years stale, so the
    #: pricing clock falls back to #30. See :mod:`.snapshot`.
    #:
    #: **A bare ``datetime.date`` is a legitimate value, not a type error.**
    #: Spec footnote 39 lets #30 carry ``00:00:00`` when the time portion is
    #: unavailable; ``snapshot.pricing_timestamp`` refuses to fabricate an
    #: intraday instant for those and returns the date, which every curve
    #: source reads unambiguously as end-of-day. ``snapshot.snap_instant`` and
    #: ``krd.block_key`` both branch on exactly that, so annotating this
    #: ``pd.Timestamp`` alone told a reader the opposite of what the pipeline
    #: does.
    pricing: pd.Timestamp | datetime.date
    #: Field #96 as reported, carried verbatim for transparency.
    execution: pd.Timestamp
    #: Field #30 as reported, carried verbatim for transparency.
    event: pd.Timestamp
    #: When the print could first have been acted on. Part 43 Appendix C legal
    #: delay by default; a measured publication time where the lineage sidecar
    #: has one. Every aggregation stamps on this.
    visibility: pd.Timestamp
    #: How ``visibility`` was arrived at, so a consumer can gate on it.
    visibility_source: str
    #: ``event - execution``, the tape's own transparency column. Measured at
    #: p90 = 0, i.e. not a publication delay -- carried so that stays visible.
    report_lag_seconds: float | None = None


@dataclasses.dataclass
class Unit:
    """A classification unit: one printed package, or one outright.

    The unit -- not the leg -- is the object direction is inferred for. A
    package has one price, so it has one inferred bit; the per-leg signs and
    the per-leg key-rate profiles are *derived* from that bit via
    :mod:`.conventions`. Keeping the unit primary is also what keeps the
    tie-out join against the frozen classifier defined, since that system
    assigns one direction per unit.
    """

    unit_key: str
    kind: str                      # OUTRIGHT | CURVE | FLY | PKG
    legs: pd.DataFrame             # total-ordered (expiration, effective, trade_id)
    package_id: str | None
    rate_index: str                # SOFR | FED_FUNDS
    as_of_date: datetime.date
    venue_class: str
    clocks: Clocks
    #: Sum of the legs' other-payment amounts, unsigned, or ``None``. This --
    #: not ``is_off_market`` -- is what routes the rate rule vs the upfront
    #: rule, because ``is_off_market`` is itself a rate-outlier heuristic and
    #: disagrees with upfront presence on 524k legs.
    upfront: float | None = None
    upfront_source: str | None = None       # PTP | UFRO_SUM | UWIN_SUM
    #: True for a lifecycle print (termination / unwind). Kept as its own
    #: series: the sign is right but it is driven by seasoned P&L rather than
    #: by bid-offer, so the confidence model does not transfer.
    is_lifecycle: bool = False
    is_block: bool = False
    is_capped: bool = False

    @property
    def n_legs(self) -> int:
        return len(self.legs)


@dataclasses.dataclass
class UnitPricing:
    """Everything the repricing pass produces for one unit."""

    unit_key: str
    curve_name: str
    curve_timestamp: pd.Timestamp
    #: Realised staleness of the served snapshot, seconds. Negative would mean
    #: a curve from the future, which the strict policy forbids.
    snapshot_lag_seconds: float | None
    snapshot_policy: str
    #: Per-leg mid fixed rate, percent, ordered as ``Unit.legs``.
    leg_mid_pct: list
    #: Per-leg PV01 (dV per 1bp of the leg's own rate), positive.
    leg_pv01: list
    #: Net NPV in the fixed-payer frame, summed over legs at the printed rates.
    #: Only populated when the upfront rule applies.
    npv_pay: float | None = None
    #: The unit's own DV01, used to put an edge in bp. Never the tape's ``risk``
    #: column, which carries the spec's not-available sentinel on 55 rows.
    structure_dv01: float | None = None


@dataclasses.dataclass
class DirectionCall:
    """The inference for one unit."""

    unit_key: str
    #: One of **three** rules, not two: ``conventions.RULE_RATE``,
    #: ``conventions.RULE_UPFRONT``, ``package_price.RULE_PACKAGE_PRICE``.
    #: The third is named in ``package_price`` rather than ``conventions``
    #: because ``conventions`` is tie-out surface against the frozen
    #: predecessor, which has two. A consumer switching on this field must
    #: handle all three -- see :attr:`base_orientation`, which the third one
    #: needs and the first two do not.
    rule: str
    #: The unit's deviation from mid, bp. Signed towards "base party overpaid".
    deviation_bps: float | None
    #: p(customer paid fixed) = p(dealer received fixed).
    p: float | None
    #: ``2p - 1``. This, not ``p``, is what multiplies the DV01.
    signed_weight: float | None
    #: ``+1`` dealer received, ``-1`` dealer paid, ``0`` no call.
    dealer_sign: int
    #: Which calibration bucket supplied tau, and what it was.
    tau_bucket: str | None = None
    tau_bps: float | None = None
    #: The per-bucket mid bias that was subtracted before forming the deviation.
    mid_bias_bps: float | None = None
    in_dead_zone: bool = False
    exclusion: str | None = None
    #: ``pay_signs`` for the base party, ``+1`` = pays fixed, in the unit's own
    #: leg order -- the per-unit orientation only ``RULE_PACKAGE_PRICE`` has.
    #:
    #: ``None`` for the two conventions-driven rules, where the orientation is
    #: a property of the *structure* and ``conventions.base_orientation(kind,
    #: n_legs, rule)`` supplies it; a ``PKG-N`` has no such convention, which is
    #: the whole reason those units were excluded. ``krd`` routes on this: with
    #: ``rule == package_price.RULE_PACKAGE_PRICE`` the key-rate hypothesis
    #: comes from here via ``package_price.received_hypothesis_signs``, and
    #: without it the ``RULE_UPFRONT`` fallback would point every leg of the
    #: package the same way.
    #:
    #: **The invariant, and it is the whole contract:**
    #: ``dealer_sign * base_orientation`` must equal the per-leg
    #: ``received_signs`` the rule concluded. A producer mapping a
    #: ``package_price.PackagePriceCall`` onto this class copies both fields
    #: across **unmodified** -- no negation anywhere, including on a lifecycle
    #: unit, because ``package_price.classify`` puts the tear-up flip in
    #: ``dealer_sign`` and leaves the orientation alone (which leg pays fixed
    #: is not something a tear-up changes). Verified on both branches by
    #: ``scratch/ddseam_probe.py``. Assert the invariant in the producer rather
    #: than trusting it: it is one line, and the failure it catches -- a whole
    #: package's key-rate profile inverted -- is invisible in the output.
    base_orientation: tuple | None = None


@dataclasses.dataclass
class Provenance:
    """Per-row audit trail. Without this a consumer cannot gate on quality and
    a wrong-looking ladder cannot be debugged.
    """

    unit_key: str
    curve_name: str
    curve_timestamp: pd.Timestamp
    snapshot_lag_seconds: float | None
    snapshot_policy: str
    #: Which reported field :attr:`Clocks.pricing` came from. **Three values,
    #: not two** -- the ``snapshot.CLOCK_*`` constants:
    #: ``"execution_timestamp"`` (#96, a UTI-minting row),
    #: ``"event_timestamp"`` (#30, everything else), and
    #: ``"event_timestamp_date_only"``, the footnote-39 degradation where #30
    #: carries no time portion and the unit prices end-of-day. The third is the
    #: one a consumer gates on, so a two-value vocabulary here hid the only
    #: population this column exists to make excludable. Spelled out rather
    #: than imported: this module is the contract layer and ``snapshot``
    #: imports it.
    pricing_clock_field: str
    #: The rule that produced the call. Same three-value vocabulary as
    #: :attr:`DirectionCall.rule`; ``None`` when no call was made.
    rule: str | None
    notional_imputed: bool
    notional_impute_factor: float | None
    risk_sanity_reason: str | None
    tau_bucket: str | None
    code_vintage: str
    #: Populated when the unit did not reach the ladder. One of the ``EXCL_*``
    #: constants; the DV01 share of each is what the written note reports.
    failure_reason: str | None = None
