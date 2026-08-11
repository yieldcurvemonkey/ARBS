"""Reprice one :class:`~.types.Unit` at its snapped instant.

The output is deliberately narrow -- per-leg mid rate, per-leg PV01, the unit's
``structure_dv01``, and a payer-frame NPV when an upfront is present. No
direction, no probability: those consume this and are calibrated separately.

Three things here are not obvious and each has a measurement behind it.

**The session branch is two pricer objects, not one with a per-call policy.**
``CurvePricer._handles`` is keyed on ``(curve_name, ts)`` alone, so a per-call
policy would let the first caller's terms be reused silently for the next
caller's request for the same minute -- the cache key and the terms disagreeing,
which is the failure the per-instance ``curve_kwargs`` design was chosen to
avoid. Branching on the *object* keeps them in agreement. It is also not
decoration: on 2026-06-01 there is a 30-minute gap **inside** Citi's published
session, and a global ``max_lag=2h`` serves a probe there from a curve fifteen
minutes stale while the branch refuses it (LEDGER F-15).

**The curve source is a constructor argument.** The tie-out is two measurements
that each vary one thing (LEDGER D11): hold the Barchart curve constant and
swap old code for new, then hold the new code constant and swap Barchart for
the Citi minute curve. Baking either source in makes the first measurement
impossible. The Barchart source additionally *raises* when handed a
``snapshot_policy`` (``IRSwapsMDP.py:2004``), so the branch collapses to a
single unpoliced pricer there -- named :data:`POLICY_NONE` on every row rather
than left to be inferred.

**A null lag is a monitoring failure, not a cosmetic one.** ``RLIRSwapCurve``
exposes ``.meta()``, not ``.meta_data``; a whole strict run once reported
``lag=None`` on every row and was otherwise indistinguishable from a correct
one. On a snapshot-governed pricer a missing lag raises. On the legacy source
there is no snapshot machinery to report one, so ``None`` is the truth -- and
what makes that loud is :data:`POLICY_NONE` sitting in ``snapshot_policy``.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime
import math

import pandas as pd

from SDRUtils.dealer_direction import conventions, snapshot
from SDRUtils.dealer_direction.types import (EXCL_NO_CURVE, EXCL_NO_FIXED_RATE,
                                             EXCL_PRICING_ERROR,
                                             EXCL_RISK_IMPLAUSIBLE,
                                             EXCL_UNSUPPORTED_INDEX,
                                             UnitPricing)
from SDRUtils.stir_flow import config as legacy_config
from SDRUtils.stir_flow.pricing import CurvePricer

#: Which branch answered. Recorded on every row -- a lag of 90 s means something
#: different under each of them.
POLICY_STRICT = "STRICT_1MIN_IN_SESSION"
POLICY_HOLE = "ASOF_2H_OUT_OF_SESSION"
POLICY_NONE = "LEGACY_NO_SNAPSHOT_POLICY"

#: Leg strata for the coverage measurement. Past-start legs are 14.6% of the
#: tape (339,497) and are the only ones whose rate depends on published fixings,
#: so an aggregate success rate would hide a fixings failure completely.
START_SPOT = "SPOT"
START_FORWARD = "FORWARD_START"
START_PAST = "PAST_START"
#: A leg with no usable effective date. Named rather than defaulted: a
#: fabricated stratum label is the same silent-plausible-value failure the rest
#: of this module refuses, and it would land in whichever bucket happened to be
#: the fallback.
START_UNKNOWN = "UNKNOWN"

#: A leg starting within this many calendar days of the snap is "spot". Two
#: business days is the USD SOFR convention; three calendar days absorbs a
#: weekend without pretending to run a holiday calendar, which would be more
#: precision than a stratum label needs.
_SPOT_WINDOW_DAYS = 3

#: Non-fatal observations attached to the result rather than raised.
FLAG_NO_LAG_TELEMETRY = "NO_LAG_TELEMETRY"
FLAG_EOD_CLOCK = "EOD_CLOCK"
FLAG_LEG_FAILURE = "LEG_FAILURE"

#: The tape carries the spec's own "value not available" placeholders in band:
#: field #31 is ``Num(25,5)`` and footnote 42 accepts ``9.99...e19``; 55 legs use
#: it and 54 of those also carry ``fixed_rate = 9.9`` (=990%). Both price
#: perfectly well and produce plausible-looking nonsense, so they are refused
#: here rather than downstream. ``fixed_rate`` is a decimal fraction on this
#: tape, so anything at or beyond 100% cannot be a rate (F-8: 1,465 legs).
_NOTIONAL_SENTINEL = 1e19
_MAX_PLAUSIBLE_RATE = 1.0


class LagTelemetryMissing(RuntimeError):
    """A snapshot-governed pricer served a curve that reports no lag.

    Raised rather than recorded, because the session branch *relies* on the lag:
    without it there is no way to tell a curve served for the minute asked for
    from one served two hours earlier, and both produce sensible prices.
    """


class CircularCurve(RuntimeError):
    """The served snapshot postdates the print it is being used to classify.

    Structurally impossible under a backward-only policy, which is exactly why
    it is checked: a curve from after the print can already contain the print's
    own market impact, which biases the direction call towards whatever the
    trade actually was -- the one failure this whole exercise exists to prevent.
    """


@dataclasses.dataclass(frozen=True)
class CurveMark:
    """One curve handle plus the provenance of the snapshot it was served from."""

    policy: str
    curve_name: str
    #: The instant **asked for**, not the one served. This is the reproducible
    #: key -- re-requesting it returns the same curve -- and ``lag_seconds``
    #: recovers the served stamp exactly, so nothing is lost by recording the
    #: input rather than the output.
    requested: pd.Timestamp
    lag_seconds: float | None
    served_from_future: bool | None
    served_utc: object
    handle: object


def _finite(v) -> bool:
    """Is this a usable mark? ``None`` means "no mark", which is allowed.

    ``math.isnan`` alone is not the test. ``CurvePricer.price_leg`` returns
    ``float(vmap.apply(...))``, and that float can be ``inf`` as readily as
    ``nan`` -- an infinite PV01 puts every edge that divides by it at exactly
    zero bp, which is inside every dead zone rather than outside every
    threshold.
    """
    if v is None:
        return True
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


@dataclasses.dataclass(frozen=True)
class LegQuote:
    """One leg's marks, or the named reason it has none.

    A non-finite mark is the second of those, and the contract enforces it
    rather than trusting each construction site to remember. ``price_leg``
    returns a float, so a curve that produces a NaN rate *returns* one instead
    of raising: ``ok`` was ``failure is None`` and nothing looked at the values,
    so that leg reached the ladder with ``failure=None`` beside a
    confident-looking ``structure_dv01`` of 4,000. A NaN is worse than a missing
    answer -- ``traded - nan`` is neither above the mid nor below it, so the row
    is silently a no-call while still counting as *priced* in the stratified
    success rate the fixings strata exist to protect.

    The sibling marks are dropped with the offending one: a PV01 out of the same
    value map that produced a NaN rate is not half-trustworthy.
    """

    trade_id: object
    start_class: str
    is_capped: bool
    mid_pct: float | None = None
    pv01: float | None = None
    npv_pay: float | None = None
    failure: str | None = None
    failure_detail: str | None = None

    _MARKS = ("mid_pct", "pv01", "npv_pay")

    def __post_init__(self):
        if self.failure is not None:
            return
        bad = [n for n in self._MARKS if not _finite(getattr(self, n))]
        if not bad:
            return
        detail = ", ".join(f"{n}={getattr(self, n)!r}" for n in bad)
        # EXCL_PRICING_ERROR rather than a reason of its own: the exclusion
        # vocabulary lives in types.py so the coverage accounting adds up, and a
        # midprice-local string would be a stratum nobody else counts. The
        # field name is in the detail, which is where the specificity belongs.
        object.__setattr__(self, "failure", EXCL_PRICING_ERROR)
        object.__setattr__(self, "failure_detail", f"non-finite mark: {detail}")
        for n in self._MARKS:
            object.__setattr__(self, n, None)

    @property
    def ok(self) -> bool:
        return self.failure is None


@dataclasses.dataclass
class RepricedUnit:
    """What the pass produced for one unit, including when it produced nothing.

    ``pricing`` is always present so a caller can record provenance for a failed
    unit; ``failure`` is ``None`` only when every leg priced.
    """

    pricing: UnitPricing
    legs: list
    failure: str | None = None
    failure_detail: str | None = None
    flags: list = dataclasses.field(default_factory=list)
    #: Sum of the legs' absolute PV01. Not the structure's risk -- the legs
    #: offset -- but it is the correct denominator for a payer-frame NPV edge
    #: on a ``PKG-N``, where the internal orientation is undetermined.
    gross_pv01: float | None = None


# --------------------------------------------------------------------------
# structure_dv01
# --------------------------------------------------------------------------

def structure_dv01(kind: str, pv01s) -> float | None:
    """The dollar value of one basis point **of the unit's quoted price**.

    Not the sum of the legs' risk: the legs offset, and a fly's risk is its
    belly. ``stir_flow.classifier.structure_dv01`` already knows that for the
    three structures a quote convention exists for, and the generalisation that
    reproduces all three from one rule is

        the largest PV01 among the legs carrying the largest ``|quote weight|``.

    Outright ``q = (1,)`` -> the only leg. Curve ``q = (-1, +1)`` -> the weights
    tie, so the larger leg wins, which is ``max`` and is right for a
    DV01-neutral spread. Fly ``q = (-1, +2, -1)`` -> the belly is the unique
    largest weight, so the belly wins whatever the wings do. The rate rule's
    weights are used even when the unit will be classified by the upfront rule,
    because the quote convention is a property of the *structure*, not of which
    inference we happen to be running.

    **PKG-N (N >= 4) has no quote convention**, so there are no weights and the
    rule above has nothing to select on. It keeps the frozen classifier's
    ``sum(|pv01|) / 2``, which is defensible as the **midpoint of the range the
    unknown internal orientation permits**: the package's true DV01 is
    ``|sum(s_i * pv01_i)|`` for some unknown sign vector ``s``, which ranges
    from ~0 (perfectly offsetting) to ``sum(|pv01|)`` (all one way). It is exact
    for a two-sided balanced package and wrong by 2x at either extreme -- which
    is the honest state of knowledge, and why PKG-N is excluded from the ladder
    rather than force-classified (DESIGN 3). ``RepricedUnit.gross_pv01`` carries
    the upper end for a caller that wants the payer-frame denominator instead.

    ``None`` when any leg is unpriced, so a partially priced package cannot
    produce a confident-looking denominator. "Unpriced" includes a leg whose
    PV01 came back non-finite -- ``isnan`` alone let an ``inf`` through, and the
    leg's *mid* is covered by :class:`LegQuote`'s contract upstream, which turns
    a non-finite mark into a named failure before this is ever called.
    """
    vals = list(pv01s)
    if any(v is None or not _finite(v) for v in vals):
        return None
    a = [abs(float(v)) for v in vals]
    if not a:
        raise ValueError("structure_dv01 needs at least one leg")
    try:
        q = conventions.quote_weights(kind, len(a), conventions.RULE_RATE)
    except conventions.UnorientableUnit:
        if kind in (conventions.OUTRIGHT, conventions.CURVE, conventions.FLY):
            # A named structure with a leg count its own convention does not
            # describe -- a two-leg "FLY". That is a unit-construction bug, and
            # falling through to the PKG-N average would hide it behind a
            # plausible number.
            raise
        return sum(a) / 2.0
    top = max(abs(w) for w in q)
    return max(v for v, w in zip(a, q) if abs(w) == top)


def start_class(effective_date, instant) -> str:
    """Which coverage stratum a leg belongs to.

    Cut against the **snap**, not against ``as_of_date``: a leg is past-start
    when its accrual has begun by the instant we are pricing at, and that is
    what decides whether published fixings enter its rate.
    """
    eff = pd.Timestamp(effective_date).date()
    ref = _instant_date(instant)
    delta = (eff - ref).days
    if delta < 0:
        return START_PAST
    if delta <= _SPOT_WINDOW_DAYS:
        return START_SPOT
    return START_FORWARD


def _instant_date(instant) -> datetime.date:
    if isinstance(instant, datetime.date) and not isinstance(instant, datetime.datetime):
        return instant
    return pd.Timestamp(instant).date()


# --------------------------------------------------------------------------
# The session branch
# --------------------------------------------------------------------------

class SessionBranchPricer:
    """Strict inside Citi's session, a bounded backward ``asof`` outside it.

    Productionised from ``scratch/dd04_session_branch.py``, which demonstrated
    it on four cases: in-session mids bit-identical to a pure-strict run, 7/7
    hour-00 prints served at 1-97 minutes of lag with none from the future, the
    2026-06-01 interior gap where a global bound serves and this refuses, and a
    night after a truncated session where the 2 h bound still refuses a
    four-hour reach-back.

    The two policies are taken from :func:`snapshot.policy_for` rather than
    rebuilt, so this module cannot drift away from the one that owns the rule.
    """

    def __init__(self, *, source: str = snapshot.CURVE_SOURCE, mdp=None,
                 curve_for: dict | None = None):
        self.source = source
        self._governed = source.upper() != snapshot.LEGACY_CURVE_SOURCE.upper()
        self._curve_for = dict(curve_for) if curve_for is not None else (
            dict(snapshot.CURVE_FOR) if self._governed else dict(legacy_config.CURVE_FOR)
        )
        if mdp is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

            mdp = IRSwapsMDP(source=source)
        # One MDP, two pricers. The MDP holds no policy state -- every
        # `_get_curve` call carries its own kwargs -- so sharing it lets the two
        # branches share the underlying store reads while keeping the terms and
        # the handle cache keys in agreement, which is the whole point.
        if self._governed:
            # A probe instant is the honest way to ask snapshot.py for each of
            # its two policies without restating either one here.
            self._pricers = {
                POLICY_STRICT: CurvePricer(mdp, curve_kwargs={
                    "snapshot_policy": snapshot.policy_for(
                        self._probe_curve(), _IN_SESSION_PROBE)}),
                POLICY_HOLE: CurvePricer(mdp, curve_kwargs={
                    "snapshot_policy": snapshot.policy_for(
                        self._probe_curve(), _OUT_OF_SESSION_PROBE)}),
            }
        else:
            # BARCHART raises on a snapshot_policy (IRSwapsMDP.py:2004) and has
            # no session to branch on, so one unpoliced pricer under a name that
            # says so.
            self._pricers = {POLICY_NONE: CurvePricer(mdp)}

    def _probe_curve(self) -> str:
        return self._curve_for.get("SOFR", "USD-SOFR-1D")

    @property
    def snapshot_governed(self) -> bool:
        """Can this source report a snapshot lag at all?

        ``False`` for Barchart, whose ``.meta()`` carries only ``curve_name``,
        ``id``, ``requested_curve_name`` and ``timestamp`` -- measured, not
        assumed.
        """
        return self._governed

    @property
    def policies(self) -> tuple:
        return tuple(self._pricers)

    def pricer_for(self, policy: str) -> CurvePricer:
        return self._pricers[policy]

    def curve_for(self, rate_index: str) -> str:
        try:
            return self._curve_for[rate_index]
        except KeyError:
            raise UnsupportedIndex(rate_index) from None

    def policy_for_instant(self, curve_name: str, instant) -> str:
        if not self._governed:
            return POLICY_NONE
        return POLICY_STRICT if snapshot.in_session(curve_name, instant) else POLICY_HOLE

    def mark_curve(self, curve_name: str, instant) -> CurveMark:
        """Build (or reuse) the handle for this minute and read its provenance.

        Raises ``SnapshotMiss`` when the branch's policy refuses -- which is a
        result, not an error, and the caller turns it into ``NO_CURVE``.
        """
        policy = self.policy_for_instant(curve_name, instant)
        handle = self._pricers[policy].handle(curve_name, _as_request(instant))
        return CurveMark(
            policy=policy,
            curve_name=curve_name,
            requested=pd.Timestamp(instant),
            lag_seconds=snapshot.snapshot_lag_seconds(handle),
            served_from_future=snapshot.served_from_future(handle),
            served_utc=_served_utc(handle),
            handle=handle,
        )

    def price_leg(self, curve_name: str, instant, effective_date, maturity_date,
                  notional, fixed_rate=None):
        """One leg through ``CurvePricer`` -- and therefore through ``IRSwapQuery``.

        Deliberately not a second pricing path. ``IRSwapQuery`` is what plumbs
        published fixings into a past-start leg (``RLIRSwapCurve._fixings_kwargs``
        keeps the full series for anything effective before the curve's own
        reference date), and 14.6% of the tape needs that.
        """
        policy = self.policy_for_instant(curve_name, instant)
        return self._pricers[policy].price_leg(
            curve_name, _as_request(instant), effective_date, maturity_date,
            notional, fixed_rate=fixed_rate,
        )

    # --- per-day scope ----------------------------------------------------
    # Measured on 2026-04-01, every eligible SOFR and Fed Funds flow leg
    # (`scratch/dd18_one_full_day.py`): 4,329 legs touch **969** distinct
    # curve-minutes in one day. Nothing evicts them and an rl.Curve is not
    # small, so a single-process 610-day run would end holding ~591,000 of
    # them. With the scope it holds 969 and drops to 0 at the day boundary.

    @property
    def n_handles(self) -> int:
        return sum(len(p._handles) for p in self._pricers.values())

    def clear(self) -> None:
        for p in self._pricers.values():
            p._handles.clear()

    @contextlib.contextmanager
    def day_scope(self):
        """Drop every handle on the way out, including on the way out via a raise."""
        try:
            yield self
        finally:
            self.clear()


class UnsupportedIndex(KeyError):
    """No curve is configured for this ``rate_index`` on this source."""


# Probe instants used only to ask ``snapshot.policy_for`` for each of its two
# branches at construction time. A Wednesday afternoon and the small hours of
# the following morning: inside and outside Citi's publication session by the
# measured model (week on a UTC clock, day on a New York one).
_IN_SESSION_PROBE = pd.Timestamp("2026-04-01 14:30:00", tz=snapshot.NY)
_OUT_OF_SESSION_PROBE = pd.Timestamp("2026-04-02 00:30:00", tz=snapshot.NY)


def _as_request(instant):
    """What to hand ``CurvePricer`` -- a plain datetime, never a ``pd.Timestamp``.

    ``pd.Timestamp`` subclasses ``datetime.datetime`` subclasses
    ``datetime.date``, and the citivelo dispatch routes on the *resolved* mode
    rather than on isinstance for exactly that reason; passing the pydatetime is
    what the probes that validated this path did, so it is what ships.
    """
    if isinstance(instant, datetime.date) and not isinstance(instant, datetime.datetime):
        return instant
    return pd.Timestamp(instant).to_pydatetime()


def _served_utc(handle):
    getter = getattr(handle, "meta", None)
    meta = getter() if callable(getter) else None
    return meta.get("snapshot_served_utc") if isinstance(meta, dict) else None


# --------------------------------------------------------------------------
# The pass itself
# --------------------------------------------------------------------------

class UnitRepricer:
    """A :class:`~.types.Unit` in, a :class:`RepricedUnit` out.

    ``pricer`` is the seam, and it is exactly five members wide:
    ``snapshot_governed``, ``curve_for``, ``policy_for_instant``,
    ``mark_curve``, ``price_leg`` (plus ``clear`` for the day scope). Named in
    full because the first fake written against this class was built from a
    docstring that listed two of them and failed on the third.
    """

    def __init__(self, pricer=None, *, require_lag_telemetry: bool = True):
        self.pricer = pricer if pricer is not None else SessionBranchPricer()
        self.require_lag_telemetry = require_lag_telemetry

    @classmethod
    def for_source(cls, source: str, **kw) -> "UnitRepricer":
        return cls(SessionBranchPricer(source=source), **kw)

    def clear(self) -> None:
        self.pricer.clear()

    @contextlib.contextmanager
    def day_scope(self):
        try:
            yield self
        finally:
            self.clear()

    # ----------------------------------------------------------------------

    def price_unit(self, unit, *, instant=None) -> RepricedUnit:
        """Mid, PV01, ``structure_dv01`` and (with an upfront) the payer-frame NPV.

        ``instant`` defaults to :func:`snapshot.snap_instant` of the unit's
        pricing clock -- the T-1min rule. It is overridable so the
        snap-sensitivity study can reprice the same unit at T-5s and T-30s
        through this exact code path rather than a parallel one.
        """
        flags: list[str] = []
        snap = snapshot.snap_instant(unit.clocks.pricing) if instant is None else instant

        try:
            curve_name = self.pricer.curve_for(unit.rate_index)
        except (UnsupportedIndex, KeyError):
            return self._refused(unit, snap, EXCL_UNSUPPORTED_INDEX,
                                 f"no curve configured for rate_index={unit.rate_index!r} "
                                 f"on source {getattr(self.pricer, 'source', '?')!r}", flags)

        if isinstance(snap, datetime.date) and not isinstance(snap, datetime.datetime):
            # A date-only #30 (spec footnote 39) degrades to end-of-day, and an
            # EOD request under a minute-resolution policy is a contradiction
            # the MDP refuses outright. Refused here instead, with the reason
            # attached, so the row is countable rather than an exception.
            flags.append(FLAG_EOD_CLOCK)
            return self._refused(unit, snap, EXCL_NO_CURVE,
                                 "pricing clock is date-only; there is no intraday "
                                 "instant to snap to and an EOD curve postdates the print",
                                 flags)

        bad = _implausible(unit.legs)
        if bad is not None:
            return self._refused(unit, snap, bad[0], bad[1], flags)

        from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

        try:
            mark = self.pricer.mark_curve(curve_name, snap)
        except SnapshotMiss as exc:
            return self._refused(unit, snap, EXCL_NO_CURVE, str(exc), flags,
                                 policy=self.pricer.policy_for_instant(curve_name, snap))

        self._assert_telemetry(mark, flags)

        want_npv = unit.upfront is not None
        legs, ok = [], True
        for _, row in unit.legs.iterrows():
            q = self._price_one(curve_name, snap, row, want_npv=want_npv)
            legs.append(q)
            ok = ok and q.ok
        if not ok:
            flags.append(FLAG_LEG_FAILURE)

        mids = [q.mid_pct for q in legs]
        pv01s = [q.pv01 for q in legs]
        dv01 = structure_dv01(unit.kind, pv01s) if ok else None
        npv = sum(q.npv_pay for q in legs) if (ok and want_npv) else None

        first_fail = next((q for q in legs if not q.ok), None)
        pricing = UnitPricing(
            unit_key=unit.unit_key,
            curve_name=curve_name,
            curve_timestamp=mark.requested,
            snapshot_lag_seconds=mark.lag_seconds,
            snapshot_policy=mark.policy,
            leg_mid_pct=mids,
            leg_pv01=pv01s,
            npv_pay=npv,
            structure_dv01=dv01,
        )
        return RepricedUnit(
            pricing=pricing,
            legs=legs,
            failure=None if ok else first_fail.failure,
            failure_detail=None if ok else first_fail.failure_detail,
            flags=flags,
            gross_pv01=sum(abs(p) for p in pv01s) if ok else None,
        )

    # ----------------------------------------------------------------------

    def _assert_telemetry(self, mark: CurveMark, flags: list) -> None:
        # The flag and the sign of the lag are one fact written twice -- the MDP
        # publishes `signed = (wanted - actual)` and `from_future = signed < 0`
        # from the same line (IRSwapsMDP.py:3336). So read both: a missing
        # `snapshot_served_from_future` is falsy, and testing the boolean alone
        # waved through a mark carrying `lag_seconds = -900.0` -- the circular
        # curve this guard exists for, with the evidence already in hand.
        if mark.served_from_future or (mark.lag_seconds is not None
                                       and mark.lag_seconds < 0):
            raise CircularCurve(
                f"{mark.curve_name} at {mark.requested} was served from AFTER the "
                f"instant asked for (lag {mark.lag_seconds}s) under policy "
                f"{mark.policy}. That curve can contain the print being classified."
            )
        if mark.lag_seconds is not None:
            return
        if not getattr(self.pricer, "snapshot_governed", True):
            # The legacy source has no snapshot machinery; None is the truth and
            # POLICY_NONE on the row is what says so.
            return
        if self.require_lag_telemetry:
            raise LagTelemetryMissing(
                f"{mark.curve_name} at {mark.requested} under policy {mark.policy} "
                "reported no snapshot lag. RLIRSwapCurve exposes .meta(), not "
                ".meta_data -- a silent None here means the session branch is "
                "flying blind while the prices look fine."
            )
        flags.append(FLAG_NO_LAG_TELEMETRY)

    def _price_one(self, curve_name, snap, row, *, want_npv: bool) -> LegQuote:
        from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

        stratum = _stratum(row, snap)
        capped = bool(row.get("is_capped") or False)
        base = {"trade_id": row.get("trade_id"), "start_class": stratum,
                "is_capped": capped}

        if stratum == START_UNKNOWN:
            # Refused here rather than sent on: `start_class` used to run
            # OUTSIDE this try/except and `NaT.date() - date` raised TypeError
            # straight out of `price_unit`, so one dateless row took a whole
            # day's pass with it. A leg with no accrual start has no schedule to
            # price either, so the named failure and the named stratum agree.
            return LegQuote(**base, failure=EXCL_PRICING_ERROR,
                            failure_detail="leg carries no effective_date; there is "
                                           "no schedule to price from")

        rate = row.get("fixed_rate")
        if want_npv and (rate is None or pd.isna(rate)):
            return LegQuote(**base, failure=EXCL_NO_FIXED_RATE,
                            failure_detail="the upfront rule needs a printed rate")
        try:
            lp = self.pricer.price_leg(
                curve_name, snap, row["effective_date"], row["expiration_date"],
                float(row["notional"]),
                # Decimal in: CurvePricer passes it through and
                # RLIRSwapCurve.build_irswap does the x100 into rateslib's units.
                fixed_rate=float(rate) if want_npv else None,
            )
        except SnapshotMiss as exc:
            return LegQuote(**base, failure=EXCL_NO_CURVE, failure_detail=str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 - every failure gets a named reason
            return LegQuote(**base, failure=EXCL_PRICING_ERROR,
                            failure_detail=f"{type(exc).__name__}: {str(exc)[:200]}")
        return LegQuote(**base, mid_pct=lp.mid_pct, pv01=lp.pv01, npv_pay=lp.npv_pay)

    def _refused(self, unit, snap, reason, detail, flags, policy=None) -> RepricedUnit:
        """A unit that never reached the curve still carries its provenance."""
        n = len(unit.legs)
        curve_name = self._curve_name_or_none(unit)
        pricing = UnitPricing(
            unit_key=unit.unit_key,
            curve_name=curve_name,
            curve_timestamp=snap if isinstance(snap, datetime.date)
            and not isinstance(snap, datetime.datetime) else pd.Timestamp(snap),
            snapshot_lag_seconds=None,
            snapshot_policy=policy or self._default_policy(),
            leg_mid_pct=[None] * n,
            leg_pv01=[None] * n,
            npv_pay=None,
            structure_dv01=None,
        )
        legs = [
            LegQuote(trade_id=r.get("trade_id"), start_class=_stratum(r, snap),
                     is_capped=bool(r.get("is_capped") or False),
                     failure=reason, failure_detail=detail)
            for _, r in unit.legs.iterrows()
        ]
        if legs and FLAG_LEG_FAILURE not in flags:
            # Every leg on a refused unit carries a failure, so the flag that
            # says "a leg failed" belongs here too. Without it a health count
            # keyed on the flag reports only the units that reached a curve.
            flags.append(FLAG_LEG_FAILURE)
        return RepricedUnit(pricing=pricing, legs=legs, failure=reason,
                            failure_detail=detail, flags=flags)

    def _default_policy(self) -> str:
        """What ``snapshot_policy`` says on a row that never asked for a curve.

        :data:`POLICY_NONE` is a property of the *source*, not of the instant,
        so it is knowable even on a refusal -- and this module's docstring
        claims it is named on every row, which was false for every refused
        legacy row. A governed source genuinely has two branches and no request
        to pick between them, so the empty string stays the answer there.
        """
        return "" if getattr(self.pricer, "snapshot_governed", True) else POLICY_NONE

    def _curve_name_or_none(self, unit):
        try:
            return self.pricer.curve_for(unit.rate_index)
        except (UnsupportedIndex, KeyError):
            return ""


def _has_date(row) -> bool:
    v = row.get("effective_date")
    return v is not None and not pd.isna(v)


def _stratum(row, instant) -> str:
    """The leg's coverage stratum, total over rows that have no usable date.

    One helper for both the pricing path and the refusal path, so the same leg
    cannot be labelled two ways depending on how far it got.
    """
    return start_class(row.get("effective_date"), instant) if _has_date(row) else START_UNKNOWN


def _implausible(legs) -> tuple | None:
    """The spec's own not-available placeholders, before they reach a curve.

    ``notional = 1e20`` and ``fixed_rate = 9.9`` are field #31's ``Num(25,5)``
    sentinel and its rate twin. Both price without complaint -- the NPV comes
    back at 1e17 and the row survives to a ladder -- so they are refused here
    rather than trusted to a downstream sanity gate.
    """
    for _, r in legs.iterrows():
        n = r.get("notional")
        if n is None or pd.isna(n) or float(n) == 0.0:
            return EXCL_RISK_IMPLAUSIBLE, f"notional is {n!r}"
        if abs(float(n)) >= _NOTIONAL_SENTINEL:
            return (EXCL_RISK_IMPLAUSIBLE,
                    f"notional {float(n):.4g} is the spec's not-available sentinel "
                    "(field #31, Num(25,5), footnote 42)")
        rate = r.get("fixed_rate")
        if rate is not None and not pd.isna(rate) and abs(float(rate)) >= _MAX_PLAUSIBLE_RATE:
            return (EXCL_RISK_IMPLAUSIBLE,
                    f"fixed_rate {float(rate):.4g} is >= 100% and cannot be a rate")
    return None


__all__ = [
    "CircularCurve", "CurveMark", "FLAG_EOD_CLOCK", "FLAG_LEG_FAILURE",
    "FLAG_NO_LAG_TELEMETRY", "LagTelemetryMissing", "LegQuote", "POLICY_HOLE",
    "POLICY_NONE", "POLICY_STRICT", "RepricedUnit", "START_FORWARD",
    "START_PAST", "START_SPOT", "START_UNKNOWN", "SessionBranchPricer", "UnitRepricer",
    "UnsupportedIndex", "start_class", "structure_dv01",
]
