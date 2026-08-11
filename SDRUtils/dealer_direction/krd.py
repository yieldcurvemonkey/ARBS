"""The signed key-rate DV01 profile: one unit in, one bucketed vector out.

THE PRODUCER IS RATESLIB'S OWN DELTA LADDER
-------------------------------------------
``rl.Solver`` + ``rl.Portfolio(...).delta(solver=...)``, via
``MDP/IRSwaps/BARCHART_STIRF/risk.py::build_delta_risk_ladder``, called the way
``stir_flow/ladder.py::_project_onto_model`` calls it. Not a hand-rolled
cashflow bucketing (DESIGN 6, LEDGER D9). rateslib's delta is sensitivity to the
solver's *calibrating instruments*, so the bucket set is the instrument set and
the change of basis falls out of the calibration -- which is the transformation
a desk actually wants, and it means the buckets are things you can trade.

The zero-space alternative is a genuinely different derivative, not a different
implementation of the same one: a parallel zero shift moves par rates by about
1.02 bp, and raw zero-KRD disagrees with par delta by 1.6-44% of total DV01.
They reconcile to 0.0001-0.28% once converted through the curve's own ``ds/dz``,
which is what ``tests/test_dealer_direction_krd.py`` does as a second opinion.

THE SIGN IS ONE CONSTANT
------------------------
rateslib's solver delta is ``dNPV`` per ``+1bp`` on the instrument's own rate,
so a payer swap has POSITIVE raw delta and exactly one flip lands the persisted
convention ``+ = dealer RECEIVED fixed = long duration``:
:data:`conventions.RL_DELTA_TO_FUTURES_EQ`, **one constant for every bucket
space**. ``stir_flow/ladder.py``'s HISTORY comment records a per-space dict at
this spot that inverted three of four spaces and was caught only by a row count
in a persisted table.

The output is the **hypothesis** profile the ladder's contract names,
``dv01_if_received`` -- what the dealer would hold if the dealer received fixed.
Per-leg signs come from :func:`conventions.dealer_received_signs` with
``dealer_sign = DEALER_RECEIVED``; the actual side and the confidence arrive
later as ``2p-1``. This module deliberately never sees ``dealer_sign``, because
a profile already signed by it and then weighted by ``2p-1`` -- whose sign IS
``dealer_sign`` -- is positive in every bucket on every day and looks fine.

WHY A BLOCK AND NOT A MINUTE, AND NOT A DAY
-------------------------------------------
There are 547,338 distinct ``(rate_index, exec-minute)`` pairs in the v3 tape at
~4.25 legs per curve-minute, so a solver per curve-minute pays the build cost
essentially once per trade.

A solver per ``(rate_index, as_of_date)`` was the plan and it **fails**, measured
(``scratch/ddkrd_p11.py``, ``scratch/ddkrd_perday_*.csv``): against per-minute
solvers, a day-anchored model is wrong by up to **5.23%** of a trade's total
DV01 on the biggest intraday shape break in the store (2025-04-07) and 2.2-3.3%
on FOMC days (2024-06-12). That is the same order as the error that makes the
11Y pillar mandatory, so accepting it while mandating that pillar would be
incoherent. The per-day *Jacobian* is stable (``max|dJ| = 0.0030`` within a day);
what moves is the trade's own DV01 -- the 50Y case's total moved 8.1% across
2025-04-07 -- and pricing on a day-old curve throws that away.

So the unit is a **session block**. Measured through this module against
per-minute solvers, five test shapes at every tenth stored minute
(``scratch/ddkrd_p15.py``), as a percentage of each trade's own total DV01:

====================  =====================  =====================  =====================
max bucket err        2025-04-07 shape break  2024-06-12 FOMC        2026-06-17 FOMC
====================  =====================  =====================  =====================
15 min                0.842%  (p95 0.253%)   0.262%  (p95 0.069%)   0.346%  (p95 0.044%)
30 min                1.199%  (p95 0.393%)   0.374%  (p95 0.100%)   0.340%  (p95 0.086%)
**60 min**            1.636%  (p95 0.554%)   1.646%  (p95 0.252%)   0.574%  (p95 0.154%)
whole day             5.614%  (p95 4.638%)   2.240%  (p95 1.857%)   3.445%  (p95 3.429%)
====================  =====================  =====================  =====================

:data:`BLOCK_MINUTES` is 60 and is a constructor argument, so a caller who wants
per-minute fidelity can pass ``block_minutes=1`` and pay for it. The price of
the choice, measured on one real tape day (4,329 eligible flow legs across SOFR
and Fed Funds, 2026-04-01, all projected, ``scratch/ddkrd_p16.py``): 65.5 s and
36 solvers at 60 min -- 11.1 h over 610 days, single-process -- against 68.0 s
and 64 solvers at 30 min, which roughly halves the worst-case error above for
about 13% more wall clock.

The anchor is **the first trade in the block**, not the block boundary, so every
later trade in a block is served a curve from at or before its own instant --
backward-only falls out, and the midnight / 00:xx traps never arise because the
trade's own :func:`snapshot.snap_instant` already nudged them. Block keys carry
the New York date, so a block never spans midnight.

That only holds if the input is sorted, so :class:`LookaheadCurve` checks it.
**Sort on the pricing clock, not on ``execution_timestamp``**: a row that does
not mint a new UTI prices on field #30, and the two orders are not the same one.
Measured on 2026-04-01, sorting the day's 4,329 eligible flow legs by #96 leaves
**167 of them (3.9%)** out of pricing order -- each of which, unguarded, would
have been priced on a curve from up to an hour after its own print.

FIXINGS ARE ATTACHED TWICE, ON PURPOSE
--------------------------------------
Building the ladder from a handle carrying the curve's 7,140-row published
fixings costs **2,555 ms**; stripping them costs **300 ms**, and the two solvers
give deltas equal to ``6.1e-11`` (``scratch/ddkrd_p12.py``). But 14.6% of tape
legs start before the curve's reference date and rateslib refuses to price those
without the fixings. So the model carries two handles over the *same* calibrated
``rl.Curve``: a stripped one for the solver and for spot/forward legs, and a
twin with the full series for past-start legs. Verified equal on a past-start
leg to ``6.4e-12``.

THE FRAME IS DENSE, AND THE FLOOR THAT THINS IT IS RELATIVE
-----------------------------------------------------------
28 buckets per unit is 121,212 rows for one ordinary tape day and roughly 74M
rows over 610 -- which the writer may not want. ``dust_frac`` thins it, and it
is a fraction of the **unit's own** gross ``|DV01|`` rather than an absolute
USD/bp floor, because the absolute version is a trap: measured on 2026-04-01, a
floor of 0.05 USD/bp removes 53% of the rows and only 0.00006% of the gross,
but the worst single row it removes is **95.4% of its own unit's** risk -- the
tape has units small enough that an absolute floor deletes them entirely, and
they are exactly the units a floor is not meant to be an opinion about. The
default is 0.0, which drops exact zeros only.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime

import pandas as pd
import pytz

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import snapshot
from SDRUtils.dealer_direction.types import (EXCL_NO_CURVE, EXCL_NO_FIXED_RATE,
                                             EXCL_PRICING_ERROR,
                                             EXCL_UNORIENTABLE,
                                             EXCL_UNSUPPORTED_INDEX)

NY = pytz.timezone("America/New_York")

#: The bucket space this module writes into. Pinned by
#: ``tests/test_dealer_direction_ladder.py``'s fixture -- the ladder aggregates
#: on ``(bucket_space, bucket_key)`` and a second spelling would silently split
#: every cell in two.
BUCKET_SPACE = "IRS_KRD"

#: The frame ``ladder.unit_ladder_rows`` consumes. No ``dealer_sign`` column:
#: its presence is what ``ladder.DoubleSignedKRD`` refuses.
KRD_COLUMNS = ["unit_key", "bucket_space", "bucket_key", "dv01_if_received"]

FAILURE_COLUMNS = ["unit_key", "failure_reason", "failure_detail"]

#: The bucket set. 28 pillars, each of which earned its place on the real Citi
#: curve (``scratch/ddkrd_p14.py``, max bucket displacement vs this grid as a
#: percentage of the trade's own total DV01):
#:
#: * **11Y is mandatory.** Drop it and a spot-11Y trade is displaced by 100.0%
#:   and a 1Yx10Y by 112.2% -- the risk lands in 10Y and 12Y instead. 477,812
#:   tape legs sit in the 9-12y bin.
#: * **A >=40Y pillar is mandatory.** Cap the grid at 30Y and a 50Y trade
#:   becomes a +149,799 / -99,121 dipole across 30Y/25Y in place of 52,853 at
#:   50Y -- 283% displacement, and 4% of the total lost as well. 2,687 legs run
#:   past 35y and the tape's longest is 50.4y.
#: * 7Y / 9Y / 10Y carry the TY and UXY CTDs; 20Y / 25Y / 30Y the US and WN.
#:   The 20-30y region is three pillars wide and no finer: a consumer was told a
#:   coarse 20-30y bucket is acceptable and that is exactly what this is.
#:
#: The reduced risk curve reprices the dense curve's own par rates to a maximum
#: of 0.0046 bp (at 50Y; 0.0019 bp at 30Y, <=0.0003 bp at <=20Y), and
#: ``cond(solver.J) = 204.1`` at K=28 (66.7 at K=21), so the inversion is safe.
PILLARS = ("1M", "2M", "3M", "4M", "6M", "9M", "1Y", "15M", "18M", "21M", "2Y",
           "30M", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "11Y", "12Y",
           "15Y", "20Y", "25Y", "30Y", "40Y", "50Y")

#: Below this the grid stops being a change of basis and starts being a
#: reallocation: at K=15 the measured displacements are 100-283% on the cases
#: above. 21 is the coarsest grid on which every one of them stays under 0.03%.
MIN_PILLARS = 21

#: The solver-reuse window, minutes of New York wall clock. See the table in the
#: module docstring: 60 min costs 0.83% of total DV01 at worst on the worst day
#: in the store, against 5.23% for a whole day.
BLOCK_MINUTES = 60

#: The end-of-day block. A date-only ``event_timestamp`` (spec footnote 39)
#: has no wall clock to floor, so it gets its own key rather than being
#: fabricated into 00:00 -- which would pool it with the 00:xx hour.
_EOD_BLOCK = -1


class UnusableBucketGrid(ValueError):
    """This pillar set relocates risk rather than re-expressing it.

    Raised rather than warned. Every grid reprices, every grid produces a
    complete-looking ladder, and the only symptom of a bad one is that the
    numbers are in the wrong buckets.
    """


@dataclasses.dataclass(frozen=True)
class KrdModel:
    """One calibrated risk ladder: the solver, its two handles, and its anchor."""

    rate_index: str
    curve_name: str
    #: The instant the curve was served for -- the first trade in the block.
    anchor: object
    pillars: tuple
    solver: object
    #: Fixings stripped. The solver was built from this and spot/forward legs
    #: price on it.
    risk_handle: object
    #: The same calibrated ``rl.Curve`` with the published fixings attached, for
    #: legs effective before the curve's reference date.
    risk_handle_fixed: object
    reference_date: object
    #: The instruments the solver calibrated to. Kept because they *are* the
    #: bucket definition -- the cross-check needs their maturities and the
    #: consumer occasionally needs to know what a bucket means.
    calibrating_instruments: tuple


def validate_pillars(pillars) -> tuple:
    """The grid, or a named refusal. See :data:`PILLARS` for the measurements."""
    p = tuple(str(x).upper() for x in pillars)
    if len(set(p)) != len(p):
        raise UnusableBucketGrid(f"duplicate pillars in {p}")
    if len(p) < MIN_PILLARS:
        raise UnusableBucketGrid(
            f"{len(p)} pillars is below the floor of {MIN_PILLARS}; at K=15 the "
            "measured bucket displacement reaches 283% of a trade's total DV01"
        )
    if "11Y" not in p:
        raise UnusableBucketGrid(
            "no 11Y pillar: spot-11Y is displaced 100.0% and 1Yx10Y 112.2%, and "
            "477,812 tape legs sit in the 9-12y bin"
        )
    if not any(_years(t) >= 40.0 for t in p):
        raise UnusableBucketGrid(
            "no pillar at 40Y or beyond: a 50Y trade becomes a 30Y/25Y dipole "
            "(283% displacement) and the tape runs to 50.4y"
        )
    return p


def _years(tenor: str) -> float:
    t = str(tenor).strip().upper()
    unit, n = t[-1], t[:-1]
    try:
        v = float(n)
    except ValueError:
        return 0.0
    return {"Y": v, "M": v / 12.0, "W": v / 52.0, "D": v / 365.0}.get(unit, 0.0)


def block_key(instant, block_minutes: int = BLOCK_MINUTES):
    """``(New York date, block index)`` -- the solver cache key.

    Keyed on the **New York** date, not UTC and not the tape's ``as_of_date``:
    a UTC date would put the whole US afternoon in tomorrow's blocks, and a
    block that spanned midnight would let a 00:05 print be priced on a curve
    from the previous session.
    """
    if isinstance(instant, datetime.date) and not isinstance(instant, datetime.datetime):
        return (instant, _EOD_BLOCK)
    t = pd.Timestamp(instant)
    et = t.tz_convert(NY) if t.tzinfo is not None else t
    return (et.date(), (et.hour * 60 + et.minute) // int(block_minutes))


def received_hypothesis_signs(kind: str, n_legs: int, rule: str) -> tuple:
    """Per-leg ``received_signs`` under the hypothesis that the dealer received.

    One line, but it is the line the whole module turns on, so it is named: the
    profile is ``dv01_if_received``, so the side handed to
    :func:`conventions.dealer_received_signs` is always
    :data:`conventions.DEALER_RECEIVED` and never the call's own
    ``dealer_sign``.
    """
    return conv.dealer_received_signs(kind, n_legs, rule, conv.DEALER_RECEIVED)


class KrdProjector:
    """Units in, signed key-rate profiles out, one solver per (index, block).

    ``pricer`` is the seam and it is exactly three members wide: ``curve_for``,
    ``mark_curve``, ``clear``. Defaults to :class:`midprice.SessionBranchPricer`,
    so the curve this stage prices against is the same object, under the same
    session-branched snapshot policy, that produced the mid the direction call
    was made from.
    """

    def __init__(self, pricer=None, *, pillars=PILLARS,
                 block_minutes: int = BLOCK_MINUTES,
                 allow_reduced_grid: bool = False, dust_frac: float = 0.0):
        if pricer is None:
            from SDRUtils.dealer_direction.midprice import SessionBranchPricer

            pricer = SessionBranchPricer()
        self.pricer = pricer
        self.pillars = (tuple(str(p).upper() for p in pillars)
                        if allow_reduced_grid else validate_pillars(pillars))
        self.block_minutes = int(block_minutes)
        if not 0.0 <= float(dust_frac) < 1.0:
            raise ValueError(f"dust_frac must be in [0, 1), got {dust_frac!r}")
        self.dust_frac = float(dust_frac)
        self._models: dict = {}

    # --- the solver cache -------------------------------------------------

    @property
    def n_models(self) -> int:
        return len(self._models)

    def clear(self) -> None:
        self._models.clear()
        self.pricer.clear()

    @contextlib.contextmanager
    def day_scope(self):
        """Drop every solver on the way out, including on the way out via a raise.

        A solver holds an ``rl.Curve`` and its Jacobian and nothing evicts them.
        Measured on 2026-04-01 at 60-minute blocks: 36 solvers and 36 curve
        handles across SOFR and Fed Funds together, so a 610-day single-process
        run would end holding ~22,000 of each without the scope.

        ``clear`` also clears the **pricer's** handle cache, which matters when
        the pricer is shared with :class:`midprice.UnitRepricer` -- sharing it is
        the right thing to do (the two stages then price against the same served
        snapshots), and the day boundary is the right place to drop both.
        """
        try:
            yield self
        finally:
            self.clear()

    def model_for(self, rate_index: str, instant) -> KrdModel:
        """The block's model, built at the first instant that asks for it.

        The cached model's anchor must be at or before ``instant``, and that is
        **checked, not assumed**. Feed units out of execution order and the
        anchor is a curve from *after* an earlier print -- up to
        ``block_minutes`` of lookahead, silent, and biased towards whatever the
        trade actually was. ``midprice.CircularCurve`` guards the same failure on
        the snapshot side for a case that is structurally impossible there; here
        it takes only a mis-sorted input frame, so it is more likely, not less.
        """
        curve_name = self.pricer.curve_for(rate_index)
        key = (rate_index, curve_name) + block_key(instant, self.block_minutes)
        model = self._models.get(key)
        if model is None:
            model = self._build(rate_index, curve_name, instant)
            self._models[key] = model
        elif _lookahead_seconds(model.anchor, instant) > 0.0:
            raise LookaheadCurve(
                f"the {curve_name} model for block {key[2:]} is anchored at "
                f"{model.anchor}, which is after this unit's {instant}. Units "
                "must arrive in execution order: an anchor from after the print "
                "is a curve that can already contain it."
            )
        return model

    def _build(self, rate_index: str, curve_name: str, instant) -> KrdModel:
        from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        mark = self.pricer.mark_curve(curve_name, instant)
        handle = mark.handle
        meta = dict(_meta_of(handle))
        # `build_delta_risk_ladder` reads this key and nothing else sets it on a
        # handle that came from an MDP; without it the second pass cannot
        # re-resolve the calibrating instruments and raises a KeyError.
        meta["requested_curve_name"] = curve_name
        meta.setdefault("timestamp", pd.Timestamp(mark.requested))
        fixings = handle.index()

        stripped = RLIRSwapCurve(handle.id(), handle.handle(),
                                 fixings.iloc[0:0], meta)
        risk_handle, solver = build_delta_risk_ladder(
            list(self.pillars), stripped, timestamp=mark.requested)
        labels = tuple(str(x) for x in solver.instrument_labels)
        if labels != self.pillars:
            raise UnusableBucketGrid(
                f"the solver labelled its instruments {labels}, not {self.pillars}; "
                "the bucket keys would not be the pillars asked for"
            )
        risk_handle_fixed = RLIRSwapCurve(risk_handle.id(), risk_handle.handle(),
                                          fixings, dict(_meta_of(risk_handle)))
        return KrdModel(
            rate_index=rate_index,
            curve_name=curve_name,
            anchor=mark.requested,
            pillars=self.pillars,
            solver=solver,
            risk_handle=risk_handle,
            risk_handle_fixed=risk_handle_fixed,
            reference_date=risk_handle.reference_date(),
            # `Solver.instruments` is a tuple of `(instrument, pricing kwargs)`
            # 2-tuples, not of instruments. Unwrapped here rather than at each
            # call site, where the tuple silently has no `.leg1`.
            calibrating_instruments=tuple(
                i[0] if isinstance(i, tuple) else i for i in solver.instruments),
        )

    # --- one unit ---------------------------------------------------------

    def unit_positions(self, unit, rule: str, *, instant=None):
        """``(model, instruments)`` -- the dealer's hypothesised position, built.

        Exposed rather than inlined so a cross-check can price the *same*
        instruments by a different route. Comparing a reimplementation of the
        position against the producer's own would be checking two things at once.
        """
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery

        snap = snapshot.snap_instant(unit.clocks.pricing) if instant is None else instant
        model = self.model_for(unit.rate_index, snap)
        signs = received_hypothesis_signs(unit.kind, unit.n_legs, rule)
        ref = pd.Timestamp(model.reference_date).date()

        instruments = []
        for (_, leg), sign in zip(unit.legs.iterrows(), signs):
            effective = pd.Timestamp(leg["effective_date"]).date()
            rate = leg.get("fixed_rate")
            if rate is None or pd.isna(rate):
                raise MissingFixedRate(
                    f"leg {leg.get('trade_id')!r} of unit {unit.unit_key!r} has no "
                    "fixed rate, so there is no position to take a derivative of"
                )
            # rateslib positive notional = pays fixed, so the RECEIVED side is
            # negative. `abs` because field #31 is an unsigned amount and the
            # hypothesis owns the sign -- a signed notional would sign twice.
            notional = -int(sign) * abs(float(leg["notional"]))
            # Past-start legs are the only ones that consume published fixings,
            # and attaching the series costs ~40 ms per instrument, so they get
            # the twin handle and nothing else does.
            handle = model.risk_handle_fixed if effective < ref else model.risk_handle
            q = IRSwapQuery(
                curve=model.curve_name,
                effective_date=effective,
                maturity_date=pd.Timestamp(leg["expiration_date"]).date(),
                # Decimal in: `RLIRSwapCurve.build_irswap` does the x100 into
                # rateslib's percent. The tape's `fixed_rate` is already decimal
                # (flow median 0.0394); the probes divide by 100 because their
                # constants were written in percent.
                structure_kwargs={"notional": notional, "fixed_rate": float(rate)},
                # The model's own anchor, not the trade's minute: the instrument
                # has to be resolved against the curve it will be priced on.
            ).resolve_query(model.anchor, pricer_or_curve=handle)
            pkg, _ = q.resolve_package(pricer_or_curve=handle)
            instruments.extend(pkg)
        return model, instruments

    def unit_krd(self, unit, rule: str, *, instant=None) -> dict:
        """``{bucket: dv01_if_received}`` for one unit, summed over its legs.

        One ``Portfolio.delta`` call per unit. Not per leg and not per batch of
        units: ``Portfolio`` sums, so a batch returns one aggregate vector and
        the per-unit breakdown is gone (measured -- a two-instrument portfolio's
        delta equals the sum of the singles to 1.5e-11). The unit *is* the batch,
        which is also what the ladder wants.
        """
        import rateslib as rl

        model, instruments = self.unit_positions(unit, rule, instant=instant)
        col = rl.Portfolio(instruments).delta(solver=model.solver).iloc[:, 0]
        raw = {str(k[-1] if isinstance(k, tuple) else k): float(v)
               for k, v in col.items()}
        missing = [p for p in model.pillars if p not in raw]
        if missing:
            raise UnusableBucketGrid(
                f"the delta frame has no row for pillar(s) {missing}; the bucket "
                "keys and the solver labels have drifted apart"
            )
        return {p: conv.RL_DELTA_TO_FUTURES_EQ * raw[p] for p in model.pillars}

    # --- many units -------------------------------------------------------

    def krd_frame(self, units, calls, *, instant_for=None):
        """``(krd, failures)`` -- the ladder's risk input, and the named remainder.

        Two frames, like :func:`ladder.unit_ladder_rows`, and the caller has to
        look at both: a single frame lets a unit vanish between stages with
        nothing recording that it did, and the coverage table has to be a
        partition.

        A unit whose :class:`~.types.DirectionCall` already carries an exclusion
        is skipped and appears in **neither** frame. It is the ladder's exclusion
        to report; reporting it here as well double-counts it in the coverage
        arithmetic.

        Sort ``units`` by the **pricing clock** --
        ``snapshot.snap_instant(unit.clocks.pricing)`` -- and not by
        ``execution_timestamp``, which is a different order on every row that
        does not mint a new UTI (measured: 167 of 4,329 flow legs on
        2026-04-01). The block anchor is the first unit to ask for it, so an
        out-of-order unit would be served a curve from after its own print;
        :class:`LookaheadCurve` refuses that and it lands here as a named
        ``PRICING_ERROR`` rather than as a quietly circular row.
        """
        from SDRUtils.dealer_direction.midprice import UnsupportedIndex

        call_map: dict = {}
        for call in calls:
            if call.unit_key in call_map:
                raise ValueError(f"two direction calls for unit {call.unit_key!r}")
            call_map[call.unit_key] = call

        rows: list = []
        failures: list = []
        for unit in units:
            call = call_map.get(unit.unit_key)
            if call is None:
                raise ValueError(
                    f"unit {unit.unit_key!r} has no direction call; the rule "
                    "selects the leg orientation, so it cannot be guessed here"
                )
            if call.exclusion is not None:
                continue
            # Asked here rather than let a KeyError surface from inside
            # `model_for`: `UnsupportedIndex` IS a `KeyError`, so a catch wide
            # enough to see it also swallows every unrelated dictionary miss in
            # the pricing stack and files it under the wrong reason.
            try:
                self.pricer.curve_for(unit.rate_index)
            except (UnsupportedIndex, KeyError) as exc:
                failures.append(_failure(unit, EXCL_UNSUPPORTED_INDEX, exc))
                continue
            instant = None if instant_for is None else instant_for(unit)
            try:
                profile = self.unit_krd(unit, call.rule, instant=instant)
            except conv.UnorientableUnit as exc:
                failures.append(_failure(unit, EXCL_UNORIENTABLE, exc))
                continue
            except MissingFixedRate as exc:
                failures.append(_failure(unit, EXCL_NO_FIXED_RATE, exc))
                continue
            except Exception as exc:                            # noqa: BLE001
                failures.append(_failure(unit, _reason_for(exc), exc))
                continue
            floor = self.dust_frac * sum(abs(v) for v in profile.values())
            for bucket, value in profile.items():
                if abs(value) <= floor:
                    continue
                rows.append({"unit_key": unit.unit_key,
                             "bucket_space": BUCKET_SPACE,
                             "bucket_key": bucket,
                             "dv01_if_received": value})
        return (_frame(rows, KRD_COLUMNS), _frame(failures, FAILURE_COLUMNS))


class MissingFixedRate(ValueError):
    """A leg with no printed rate. There is no position to differentiate."""


class LookaheadCurve(RuntimeError):
    """A block's anchor postdates the unit being priced against it.

    Raised, not repaired. Re-anchoring the block would silently reprice every
    unit already served from it, and serving this one from the later curve is
    the circularity the package exists to prevent. Sort the input by execution
    time.
    """


def _lookahead_seconds(anchor, instant) -> float:
    """``anchor - instant`` in seconds; positive means the anchor is in the future.

    Both sides come from the same pipeline, so both are New York-aware or both
    are bare dates. A mixed pair is itself a bug; comparing the wall clocks is
    the reading least likely to hide one, since it cannot raise on the way to
    the guard.
    """
    a, b = pd.Timestamp(anchor), pd.Timestamp(instant)
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.tz_localize(None) if a.tzinfo is not None else a
        b = b.tz_localize(None) if b.tzinfo is not None else b
    return float((a - b).total_seconds())


def _reason_for(exc) -> str:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    return EXCL_NO_CURVE if isinstance(exc, SnapshotMiss) else EXCL_PRICING_ERROR


def _failure(unit, reason: str, exc) -> dict:
    return {"unit_key": unit.unit_key, "failure_reason": reason,
            "failure_detail": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _frame(rows, columns) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).reindex(columns=columns)


def _meta_of(handle) -> dict:
    """``RLIRSwapCurve`` exposes ``.meta()``; ``.meta_data`` does not exist.

    A ``getattr(handle, "meta_data", None)`` returns ``None`` silently, and the
    ladder builder then raises on ``requested_curve_name`` -- or worse, a
    ``setdefault`` on the empty dict produces a handle that prices and labels
    nothing correctly.
    """
    getter = getattr(handle, "meta", None)
    meta = getter() if callable(getter) else None
    if not isinstance(meta, dict):
        meta = getattr(handle, "_meta_data", None)
    return meta if isinstance(meta, dict) else {}


__all__ = [
    "BLOCK_MINUTES", "BUCKET_SPACE", "FAILURE_COLUMNS", "KRD_COLUMNS",
    "KrdModel", "KrdProjector", "LookaheadCurve", "MIN_PILLARS",
    "MissingFixedRate", "PILLARS",
    "UnusableBucketGrid", "block_key", "received_hypothesis_signs",
    "validate_pillars",
]
