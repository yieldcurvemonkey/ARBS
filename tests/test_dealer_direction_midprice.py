"""The repricing pass: a unit at its snapped instant -> mids, PV01, DV01, NPV.

Every case here is a failure that has already happened somewhere in this
programme, or one the design notes say is one edit away:

* a per-call snapshot policy served one caller's terms to another caller
  (`CurvePricer._handles` is keyed on `(curve_name, ts)` alone);
* a global `max_lag=2h` served an *in-session* probe from a curve fifteen
  minutes stale while the session branch refused it (LEDGER F-15);
* `getattr(handle, "meta_data", None)` returned `None` on every row, so a whole
  strict run reported `lag=None` and looked perfectly healthy;
* a curve stamped after the print, which contains the print;
* a pricing failure recorded as a silent NaN with no reason attached.

The fast tests here run against a fake pricer, which is legitimate because the
seam is deliberately two methods wide (`mark_curve` / `price_leg`). The one test
that reaches the real Citi minute store is marked `slow`.
"""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytest

from SDRUtils.dealer_direction import conventions, midprice, snapshot
from SDRUtils.dealer_direction.types import (Clocks, EXCL_NO_CURVE,
                                             EXCL_PRICING_ERROR,
                                             EXCL_RISK_IMPLAUSIBLE,
                                             EXCL_UNSUPPORTED_INDEX, Unit)
from SDRUtils.stir_flow import classifier as frozen_classifier
from SDRUtils.stir_flow.pricing import LegPricing

NY = "America/New_York"

# 14:30 ET on a Wednesday: inside Citi's publication session for both curves.
IN_SESSION = pd.Timestamp("2026-04-01 14:30:00", tz=NY)
# 00:30 ET: inside the nightly hole, where Citi publishes nothing.
OUT_OF_SESSION = pd.Timestamp("2026-04-02 00:30:00", tz=NY)


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class _FakeMDP:
    """Enough of ``IRSwapsMDP`` for the branch-selection tests.

    Records the kwargs it was called with, because the whole point of two
    pricer instances is that the terms reaching ``_get_curve`` differ.
    """

    def __init__(self, meta=None):
        self.calls = []
        self._meta = meta if meta is not None else {
            "snapshot_lag_signed_seconds": 0.0,
            "snapshot_served_from_future": False,
            "snapshot_served_utc": "2026-04-01T18:30:00Z",
        }

    def _get_curve(self, curve_name, timestamp, kwargs=None):
        self.calls.append((curve_name, timestamp, dict(kwargs or {})))
        return _FakeHandle(self._meta)


@dataclasses.dataclass
class _FakeHandle:
    _meta: dict

    def meta(self):
        return dict(self._meta)


class _FakePricer:
    """The repricer's seam, filled in by hand.

    ``mids`` and ``pv01s`` are consumed in leg order; a ``BaseException``
    instance in either position is raised instead of returned, which is how the
    failure-reason tests inject a ``SnapshotMiss`` or a rateslib error.
    """

    snapshot_governed = True
    source = snapshot.CURVE_SOURCE

    def __init__(self, *, mids=(0.04,), pv01s=(4_000.0,), lag=0.0,
                 from_future=False, curve_error=None, governed=True):
        self.mids, self.pv01s = list(mids), list(pv01s)
        self.lag, self.from_future = lag, from_future
        self.curve_error = curve_error
        self.snapshot_governed = governed
        self.calls, self.cleared = [], 0

    def curve_for(self, rate_index):
        return snapshot.CURVE_FOR[rate_index]

    def policy_for_instant(self, curve_name, instant):
        return midprice.POLICY_STRICT if self.snapshot_governed else midprice.POLICY_NONE

    def mark_curve(self, curve_name, instant):
        if self.curve_error is not None:
            raise self.curve_error
        return midprice.CurveMark(
            policy=midprice.POLICY_STRICT if self.snapshot_governed else midprice.POLICY_NONE,
            curve_name=curve_name,
            requested=pd.Timestamp(instant),
            lag_seconds=self.lag,
            served_from_future=self.from_future,
            served_utc="2026-04-01T18:30:00Z",
            handle=object(),
        )

    def price_leg(self, curve_name, instant, effective_date, maturity_date,
                  notional, fixed_rate=None):
        i = len(self.calls) % len(self.mids)      # cycles, so one fake serves many units
        self.calls.append((curve_name, instant, effective_date, maturity_date,
                           notional, fixed_rate))
        mid, pv01 = self.mids[i], self.pv01s[i]
        for v in (mid, pv01):
            if isinstance(v, BaseException):
                raise v
        npv = None if fixed_rate is None else (mid - float(fixed_rate)) * 1e4 * pv01
        return LegPricing(mid_pct=mid * 100.0, npv_pay=npv, pv01=pv01)

    def clear(self):
        self.cleared += 1


def _legs(rows):
    return pd.DataFrame(rows)


def _unit(kind="OUTRIGHT", legs=None, *, rate_index="SOFR", upfront=None,
          pricing_ts=IN_SESSION):
    legs = legs if legs is not None else _legs([{
        "trade_id": "T1",
        "effective_date": datetime.date(2026, 4, 3),
        "expiration_date": datetime.date(2031, 4, 3),
        "notional": 10_000_000.0,
        "fixed_rate": 0.0405,
    }])
    ts = pd.Timestamp(pricing_ts)
    return Unit(
        unit_key="U1", kind=kind, legs=legs, package_id=None,
        rate_index=rate_index, as_of_date=ts.date(), venue_class="D2C",
        clocks=Clocks(pricing=ts, execution=ts, event=ts, visibility=ts,
                      visibility_source="TEST"),
        upfront=upfront,
    )


# --------------------------------------------------------------------------
# The session branch: two pricers, not one policy.
# --------------------------------------------------------------------------

def test_session_branch_holds_two_distinct_pricers_with_different_terms():
    """One pricer with a per-call policy would be unsound, not merely untidy.

    ``CurvePricer._handles`` is keyed on ``(curve_name, ts)`` alone, so the
    first caller's terms get reused for the next caller's request for the same
    minute. Two instances is what keeps the cache key and the terms in
    agreement.
    """
    br = midprice.SessionBranchPricer(mdp=_FakeMDP())
    strict = br.pricer_for(midprice.POLICY_STRICT)
    hole = br.pricer_for(midprice.POLICY_HOLE)
    assert strict is not hole
    assert strict.curve_kwargs != hole.curve_kwargs


def test_in_session_picks_strict_and_out_of_session_picks_the_bounded_asof():
    br = midprice.SessionBranchPricer(mdp=_FakeMDP())
    assert br.policy_for_instant("USD-SOFR-1D", IN_SESSION) == midprice.POLICY_STRICT
    assert br.policy_for_instant("USD-SOFR-1D", OUT_OF_SESSION) == midprice.POLICY_HOLE


def test_the_two_policies_are_exactly_the_ones_snapshot_prescribes():
    """Pinned against ``snapshot.policy_for`` so the two cannot drift apart.

    If this module built its own strict policy and ``snapshot.py`` later
    widened the in-session tolerance, the branch would go on refusing what the
    module that owns the rule now accepts -- and nothing would say so.
    """
    br = midprice.SessionBranchPricer(mdp=_FakeMDP())
    got_strict = br.pricer_for(midprice.POLICY_STRICT).curve_kwargs["snapshot_policy"]
    got_hole = br.pricer_for(midprice.POLICY_HOLE).curve_kwargs["snapshot_policy"]
    assert got_strict == snapshot.policy_for("USD-SOFR-1D", IN_SESSION)
    assert got_hole == snapshot.policy_for("USD-SOFR-1D", OUT_OF_SESSION)


def test_the_in_session_branch_cannot_serve_a_fifteen_minute_stale_curve():
    """The measurement that justifies the branch existing (LEDGER F-15).

    On 2026-06-01 a 30-minute *in-session* gap is served by a global
    ``max_lag=2h`` from a curve 15 minutes stale, and refused by the branch. The
    property that makes that true is checked here without touching the store:
    the in-session policy's bound is a minute, not two hours.
    """
    br = midprice.SessionBranchPricer(mdp=_FakeMDP())
    strict = br.pricer_for(midprice.POLICY_STRICT).curve_kwargs["snapshot_policy"]
    assert strict.max_lag <= datetime.timedelta(minutes=1)
    assert strict.method == "asof" and strict.on_miss == "raise"
    assert not strict.allow_future
    hole = br.pricer_for(midprice.POLICY_HOLE).curve_kwargs["snapshot_policy"]
    assert hole.max_lag == snapshot.OUT_OF_SESSION_MAX_LAG
    assert not hole.allow_future


# --------------------------------------------------------------------------
# Both curve sources.
# --------------------------------------------------------------------------

def test_the_legacy_barchart_source_is_never_handed_a_snapshot_policy():
    """``IRSwapsMDP._get_curve`` raises on one, by design (IRSwapsMDP.py:2004).

    The legacy source is needed for the logic tie-out -- hold the curve
    constant, vary the code -- so it must construct, and it must construct with
    empty ``curve_kwargs``.
    """
    br = midprice.SessionBranchPricer(source=snapshot.LEGACY_CURVE_SOURCE,
                                      mdp=_FakeMDP())
    for label in br.policies:
        assert "snapshot_policy" not in br.pricer_for(label).curve_kwargs
    assert br.snapshot_governed is False
    assert br.policy_for_instant("USD-SOFR-1D-Q12xM12STIRT", IN_SESSION) == midprice.POLICY_NONE


def test_curve_name_follows_the_source_not_a_module_constant():
    citi = midprice.SessionBranchPricer(mdp=_FakeMDP())
    legacy = midprice.SessionBranchPricer(source=snapshot.LEGACY_CURVE_SOURCE,
                                          mdp=_FakeMDP())
    assert citi.curve_for("SOFR") == "USD-SOFR-1D"
    assert citi.curve_for("FED_FUNDS") == "USD-FEDFUNDS-1D"
    assert legacy.curve_for("SOFR") == "USD-SOFR-1D-Q12xM12STIRT"
    assert legacy.curve_for("FED_FUNDS") == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"


# --------------------------------------------------------------------------
# Lag telemetry -- the failure that looks like success.
# --------------------------------------------------------------------------

def test_missing_lag_telemetry_raises_on_a_snapshot_governed_pricer():
    rep = midprice.UnitRepricer(_FakePricer(lag=None))
    with pytest.raises(midprice.LagTelemetryMissing):
        rep.price_unit(_unit())


def test_missing_lag_telemetry_can_be_downgraded_to_a_loud_flag():
    rep = midprice.UnitRepricer(_FakePricer(lag=None), require_lag_telemetry=False)
    out = rep.price_unit(_unit())
    assert out.pricing.snapshot_lag_seconds is None
    assert midprice.FLAG_NO_LAG_TELEMETRY in out.flags


def test_the_legacy_source_reports_a_null_lag_as_its_policy_not_as_a_fault():
    """The one exemption, and it is named rather than silent.

    A Barchart ``RLIRSwapCurve`` carries only ``curve_name / id /
    requested_curve_name / timestamp`` in ``.meta()`` -- there is no snapshot
    machinery to report a lag from, because there is no snapshot policy. So the
    lag is legitimately ``None`` there, and what makes it loud is the policy
    string on every row.
    """
    rep = midprice.UnitRepricer(_FakePricer(lag=None, governed=False))
    out = rep.price_unit(_unit())
    assert out.pricing.snapshot_policy == midprice.POLICY_NONE
    assert out.pricing.snapshot_lag_seconds is None
    assert out.failure is None


def test_a_curve_from_the_future_is_refused_because_it_contains_the_print():
    rep = midprice.UnitRepricer(_FakePricer(lag=-120.0, from_future=True))
    with pytest.raises(midprice.CircularCurve):
        rep.price_unit(_unit())


# --------------------------------------------------------------------------
# Failures carry a reason. Never a silent NaN.
# --------------------------------------------------------------------------

def test_a_snapshot_miss_is_reported_as_no_curve():
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    rep = midprice.UnitRepricer(_FakePricer(curve_error=SnapshotMiss("nothing within 60s")))
    out = rep.price_unit(_unit())
    assert out.failure == EXCL_NO_CURVE
    assert "60s" in out.failure_detail
    assert out.pricing.leg_mid_pct == [None]
    assert out.pricing.structure_dv01 is None


def test_a_rateslib_error_is_reported_as_a_pricing_error_with_the_type_named():
    rep = midprice.UnitRepricer(_FakePricer(mids=[ValueError("bad schedule")]))
    out = rep.price_unit(_unit())
    assert out.failure == EXCL_PRICING_ERROR
    assert "ValueError" in out.failure_detail
    assert out.legs[0].failure == EXCL_PRICING_ERROR


def test_one_bad_leg_fails_the_unit_but_the_good_legs_keep_their_marks():
    """A package has one price, so a missing leg is a missing unit.

    The surviving marks are kept anyway: the stratified success rate is counted
    per LEG, and throwing them away would make the denominators disagree.
    """
    legs = _legs([
        {"trade_id": "A", "effective_date": datetime.date(2026, 4, 3),
         "expiration_date": datetime.date(2028, 4, 3), "notional": 1e7,
         "fixed_rate": 0.041},
        {"trade_id": "B", "effective_date": datetime.date(2026, 4, 3),
         "expiration_date": datetime.date(2031, 4, 3), "notional": 1e7,
         "fixed_rate": 0.040},
    ])
    rep = midprice.UnitRepricer(_FakePricer(
        mids=[0.0410, ValueError("boom")], pv01s=[1_800.0, 4_500.0]))
    out = rep.price_unit(_unit(kind="CURVE", legs=legs))
    assert out.failure == EXCL_PRICING_ERROR
    assert out.legs[0].failure is None and out.legs[0].pv01 == 1_800.0
    assert out.legs[1].failure == EXCL_PRICING_ERROR
    assert out.pricing.structure_dv01 is None


def test_the_spec_notional_sentinel_is_refused_rather_than_priced():
    """55 legs carry ``notional = 1e20`` -- footnote 42's "value not available".

    It prices perfectly well and produces a $1e17 NPV, which is exactly the kind
    of plausible nonsense that survives to a ladder.
    """
    legs = _legs([{"trade_id": "S", "effective_date": datetime.date(2026, 4, 3),
                   "expiration_date": datetime.date(2031, 4, 3),
                   "notional": 1e20, "fixed_rate": 9.9}])
    rep = midprice.UnitRepricer(_FakePricer())
    out = rep.price_unit(_unit(legs=legs))
    assert out.failure == EXCL_RISK_IMPLAUSIBLE


def test_an_index_with_no_curve_is_refused_not_defaulted_to_sofr():
    rep = midprice.UnitRepricer(_FakePricer())
    out = rep.price_unit(_unit(rate_index="BASIS"))
    assert out.failure == EXCL_UNSUPPORTED_INDEX


# --------------------------------------------------------------------------
# What the pass actually produces.
# --------------------------------------------------------------------------

def test_prices_at_the_snapped_instant_not_at_the_trade_time():
    """T-1min, floored, in New York -- ``snapshot.snap_instant``."""
    pr = _FakePricer()
    trade = pd.Timestamp("2026-04-01 14:30:41", tz=NY)
    midprice.UnitRepricer(pr).price_unit(_unit(pricing_ts=trade))
    asked = pr.calls[0][1]
    assert pd.Timestamp(asked) == pd.Timestamp("2026-04-01 14:29:00", tz=NY)


def test_an_explicit_instant_overrides_the_snap_rule_for_the_sensitivity_study():
    pr = _FakePricer()
    alt = snapshot.alternative_snaps(pd.Timestamp("2026-04-01 14:30:41", tz=NY))[5]
    midprice.UnitRepricer(pr).price_unit(_unit(), instant=alt)
    assert pd.Timestamp(pr.calls[0][1]) == pd.Timestamp("2026-04-01 14:30:36", tz=NY)


def test_mids_come_back_in_percent_in_leg_order():
    legs = _legs([
        {"trade_id": "A", "effective_date": datetime.date(2026, 4, 3),
         "expiration_date": datetime.date(2028, 4, 3), "notional": 1e7,
         "fixed_rate": 0.041},
        {"trade_id": "B", "effective_date": datetime.date(2026, 4, 3),
         "expiration_date": datetime.date(2031, 4, 3), "notional": 1e7,
         "fixed_rate": 0.040},
    ])
    rep = midprice.UnitRepricer(_FakePricer(mids=[0.0415, 0.0398],
                                            pv01s=[1_800.0, 4_500.0]))
    out = rep.price_unit(_unit(kind="CURVE", legs=legs))
    assert out.pricing.leg_mid_pct == pytest.approx([4.15, 3.98])
    assert out.pricing.leg_pv01 == pytest.approx([1_800.0, 4_500.0])
    # and the mids are in the unit that conventions.structure_price expects
    assert conventions.structure_price(
        out.pricing.leg_mid_pct, "CURVE", 2, conventions.RULE_RATE
    ) == pytest.approx((3.98 - 4.15) * 100.0)


def test_no_npv_without_an_upfront_and_an_npv_with_one():
    """D6: route on the other-payment amount, never on ``is_off_market``."""
    rep = midprice.UnitRepricer(_FakePricer())
    assert rep.price_unit(_unit()).pricing.npv_pay is None
    out = rep.price_unit(_unit(upfront=125_000.0))
    assert out.pricing.npv_pay is not None


def test_npv_is_the_fixed_payer_frame_summed_over_legs():
    """Payer frame: ``f = (mid - printed) * annuity``, so paying above mid loses.

    Pinned because the sign of this quantity is what the upfront rule consumes
    (DESIGN 2.2), and a flipped frame produces a complete, plausible, inverted
    answer.
    """
    legs = _legs([
        {"trade_id": "A", "effective_date": datetime.date(2026, 4, 3),
         "expiration_date": datetime.date(2028, 4, 3), "notional": 1e7,
         "fixed_rate": 0.0450},
        {"trade_id": "B", "effective_date": datetime.date(2026, 4, 3),
         "expiration_date": datetime.date(2031, 4, 3), "notional": 1e7,
         "fixed_rate": 0.0350},
    ])
    rep = midprice.UnitRepricer(_FakePricer(mids=[0.0400, 0.0400],
                                            pv01s=[1_800.0, 4_500.0]))
    out = rep.price_unit(_unit(kind="CURVE", legs=legs, upfront=1.0))
    # leg A pays 4.50% against a 4.00% mid over 1,800/bp -> -90,000
    # leg B pays 3.50% against a 4.00% mid over 4,500/bp -> +225,000
    assert out.pricing.npv_pay == pytest.approx(-90_000.0 + 225_000.0)
    assert out.legs[0].npv_pay < 0 < out.legs[1].npv_pay


def test_printed_rate_reaches_the_pricer_as_a_decimal():
    """``CurvePricer.price_leg`` takes ``fixed_rate`` as a decimal, not percent.

    ``RLIRSwapCurve.build_irswap`` multiplies by 100 itself; handing it percent
    strikes the swap at 100x and the NPV is wrong by roughly the notional.
    """
    pr = _FakePricer()
    midprice.UnitRepricer(pr).price_unit(_unit(upfront=1.0))
    assert pr.calls[0][5] == pytest.approx(0.0405)


# --------------------------------------------------------------------------
# structure_dv01.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind, pv01s", [
    ("OUTRIGHT", [4_100.0]),
    ("CURVE", [1_800.0, 4_500.0]),
    ("CURVE", [4_500.0, 1_800.0]),
    ("FLY", [1_800.0, 4_500.0, 8_200.0]),
    ("PKG", [1_800.0, 4_500.0, 8_200.0, 900.0]),
])
def test_structure_dv01_reproduces_the_frozen_classifier(kind, pv01s):
    """The generalisation must not move the number on the cases that exist.

    ``dealer_charge_bps`` divides by this, so a changed denominator changes a
    reported edge on every off-market unit in the tie-out.
    """
    assert midprice.structure_dv01(kind, pv01s) == pytest.approx(
        frozen_classifier.structure_dv01(kind, pv01s))


def test_structure_dv01_of_a_fly_is_the_belly_not_the_gross():
    assert midprice.structure_dv01("FLY", [1_800.0, 4_500.0, 8_200.0]) == 4_500.0


def test_structure_dv01_rejects_a_leg_count_its_convention_does_not_describe():
    with pytest.raises(ValueError):
        midprice.structure_dv01("FLY", [1_800.0, 4_500.0])


def test_structure_dv01_is_none_when_any_leg_is_unpriced():
    assert midprice.structure_dv01("CURVE", [1_800.0, None]) is None


# --------------------------------------------------------------------------
# Leg strata -- the denominators for the measured success rate.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("effective, expected", [
    (datetime.date(2026, 4, 3), midprice.START_SPOT),
    (datetime.date(2026, 4, 1), midprice.START_SPOT),
    (datetime.date(2026, 3, 20), midprice.START_PAST),
    (datetime.date(2027, 4, 5), midprice.START_FORWARD),
])
def test_start_class_splits_spot_from_forward_and_past(effective, expected):
    """14.6% of the tape (339,497 legs) starts in the past.

    The strata exist because the only leg-level success rates measured anywhere
    so far are n=34 and a pre-filtered n=200, and a fixings failure would hide
    entirely inside an aggregate.
    """
    assert midprice.start_class(effective, IN_SESSION) == expected


def test_a_leg_with_no_effective_date_gets_a_named_stratum_not_a_default():
    """A fabricated stratum label is the failure this whole module refuses."""
    legs = _legs([{"trade_id": "A", "effective_date": None,
                   "expiration_date": datetime.date(2031, 4, 3), "notional": 1e7,
                   "fixed_rate": 0.041}])
    out = midprice.UnitRepricer(_FakePricer()).price_unit(_unit(rate_index="BASIS",
                                                                legs=legs))
    assert out.legs[0].start_class == midprice.START_UNKNOWN


def test_leg_marks_carry_their_stratum_so_the_rate_can_be_cut_by_it():
    legs = _legs([
        {"trade_id": "A", "effective_date": datetime.date(2024, 6, 12),
         "expiration_date": datetime.date(2029, 6, 12), "notional": 1e7,
         "fixed_rate": 0.041, "is_capped": True},
    ])
    out = midprice.UnitRepricer(_FakePricer()).price_unit(_unit(legs=legs))
    assert out.legs[0].start_class == midprice.START_PAST
    assert out.legs[0].is_capped is True


# --------------------------------------------------------------------------
# Per-day scope -- 610 days would otherwise accumulate ~500k handles.
# --------------------------------------------------------------------------

def test_the_handle_cache_can_be_cleared_and_reports_its_size():
    br = midprice.SessionBranchPricer(mdp=_FakeMDP())
    br.mark_curve("USD-SOFR-1D", IN_SESSION)
    br.mark_curve("USD-SOFR-1D", IN_SESSION + pd.Timedelta(minutes=1))
    assert br.n_handles == 2
    br.clear()
    assert br.n_handles == 0


def test_day_scope_clears_on_exit_even_when_the_day_raises():
    br = midprice.SessionBranchPricer(mdp=_FakeMDP())
    with pytest.raises(RuntimeError):
        with br.day_scope():
            br.mark_curve("USD-SOFR-1D", IN_SESSION)
            assert br.n_handles == 1
            raise RuntimeError("a day blew up")
    assert br.n_handles == 0


def test_the_repricer_forwards_the_scope_to_its_pricer():
    pr = _FakePricer()
    with midprice.UnitRepricer(pr).day_scope():
        pass
    assert pr.cleared == 1


# --------------------------------------------------------------------------
# One end-to-end pass against the real minute store.
# --------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.network
def test_the_legacy_barchart_source_prices_the_same_unit_end_to_end():
    """The tie-out's first half: same code, old curve. Only ever run on fakes.

    The legacy branch takes a different constructor path -- no snapshot policy,
    one pricer, a ``.meta()`` with no snapshot keys -- so "it works" had to be
    demonstrated on a real curve rather than inferred. Measured on 2026-04-01
    (``scratch/dd19_legacy_source.py``): four 2Y prints priced on both sources,
    the Barchart mid 0.11-1.42 bp above the Citi one, which is F-20's level bias.

    The mids are NOT required to agree. What is required is that the row labels
    itself.
    """
    legs = _legs([{"trade_id": "L", "effective_date": datetime.date(2026, 4, 3),
                   "expiration_date": datetime.date(2028, 4, 3),
                   "notional": 1e7, "fixed_rate": 0.0363}])
    rep = midprice.UnitRepricer.for_source(snapshot.LEGACY_CURVE_SOURCE)
    out = rep.price_unit(_unit(legs=legs, pricing_ts=IN_SESSION + pd.Timedelta(minutes=1)))
    assert out.failure is None, out.failure_detail
    assert out.pricing.curve_name == "USD-SOFR-1D-Q12xM12STIRT"
    assert out.pricing.snapshot_policy == midprice.POLICY_NONE
    assert out.pricing.snapshot_lag_seconds is None
    assert midprice.FLAG_NO_LAG_TELEMETRY not in out.flags
    assert 2.0 < out.pricing.leg_mid_pct[0] < 6.0
    assert out.pricing.structure_dv01 > 0


@pytest.mark.slow
def test_a_real_sofr_outright_prices_within_a_few_basis_points_of_its_print():
    """Known answer first: a liquid on-market print sits within a bp or two.

    If the units, the schedule or the curve were wrong the error would be tens
    of basis points, not tenths -- which is the only reason the bp-scale
    statistics later in this programme mean anything.
    """
    legs = _legs([{"trade_id": "R", "effective_date": datetime.date(2026, 4, 3),
                   "expiration_date": datetime.date(2031, 4, 3),
                   "notional": 1e7, "fixed_rate": 0.0363}])
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    out = rep.price_unit(_unit(legs=legs, pricing_ts=IN_SESSION + pd.Timedelta(minutes=1)))
    assert out.failure is None, out.failure_detail
    assert out.pricing.snapshot_policy == midprice.POLICY_STRICT
    assert out.pricing.snapshot_lag_seconds is not None
    assert abs(out.pricing.leg_mid_pct[0] - 3.63) < 0.05
    assert 3_000.0 < out.pricing.structure_dv01 < 6_000.0
