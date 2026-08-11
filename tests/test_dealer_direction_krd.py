"""The signed key-rate DV01 profile, pinned.

Everything here runs on a synthetic curve built in-process. No curve store, no
Supabase, no tape -- the fast gate has to be able to run it, and a risk module
whose tests only pass against a warm minute store is a module nobody can
refactor.

Four failures this file exists to make impossible, all of them silent:

1. **The sign.** rateslib's solver delta is ``dNPV`` per ``+1bp`` on the
   instrument's own *rate*, so a payer swap comes back POSITIVE and the
   persisted convention (``+ = dealer RECEIVED = long duration``) needs exactly
   one flip. ``stir_flow/ladder.py``'s HISTORY comment records a per-space sign
   dict at this spot that inverted three of four bucket spaces and was caught
   only by a row count in a persisted table. Pinned here numerically, not by
   ``sign()``.
2. **Double-signing.** ``ladder.unit_ladder_rows`` multiplies by ``2p-1``, whose
   sign IS ``dealer_sign``; a profile already signed by the call would be signed
   twice and the ladder would be positive everywhere. The contract is the
   *hypothesis* profile, so this module never sees the actual side.
3. **A bucket grid that quietly relocates risk.** Measured on the real Citi
   curve (``scratch/ddkrd_p14.py``): dropping the 11Y pillar moves 100.0% of a
   spot-11Y trade's DV01 into the wrong buckets, and capping the grid at 30Y
   turns a 52,868 USD/bp 50Y trade into a +149,799 / -99,121 dipole across
   30Y/25Y. Both grids reprice and both look fine.
4. **A bucketed risk producer nobody checked against anything else.** The
   cross-check here re-derives the profile by bump-and-reprice in *zero* space
   and converts it through the curve's own ``ds/dz`` -- and the conversion is
   the point: raw zero-KRD and par delta are different derivatives and disagree
   by 1.6-44% of total DV01 before it.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest
import pytz
import rateslib as rl

from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import krd as K
from SDRUtils.dealer_direction import ladder
from SDRUtils.dealer_direction import types as T

NY = pytz.timezone("America/New_York")

REF = rl.dt(2026, 6, 16)
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)
CURVE_NAME = "USD-SOFR-1D"

#: A shaped curve, not a flat one. On a flat continuously-compounded curve
#: ``log DF`` is exactly linear in time, so a log-linear reduced grid reproduces
#: the dense curve exactly and every grid question answers itself.
def _zero(t_years: float) -> float:
    return 0.030 + 0.015 * (1.0 - np.exp(-t_years / 3.0))


#: A short grid used only by the cross-check, where the cost is 2K shocked
#: repricings times K par rates. The production grid is checked separately.
XCHECK_PILLARS = ("3M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")


# --------------------------------------------------------------------------
# the offline curve and the pricer seam
# --------------------------------------------------------------------------

def _synthetic_curve() -> rl.Curve:
    nodes = {REF: 1.0}
    for yrs in (0.08, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 12, 15, 20, 25, 30, 40, 51):
        d = REF + datetime.timedelta(days=int(round(yrs * 365)))
        nodes[d] = float(np.exp(-_zero(yrs) * yrs))
    return rl.Curve(nodes=nodes, convention="act360", calendar="nyc", modifier="mf",
                    interpolation="log_linear", id=CURVE_NAME)


def _synthetic_fixings() -> pd.Series:
    """Daily published fixings behind the curve, so a past-start leg can price.

    Without these rateslib raises "effective date for rate period is before the
    initial node date of the Curve", which hits 14.6% of the tape.
    """
    days = pd.bdate_range(pd.Timestamp(REF) - pd.Timedelta(days=800),
                          pd.Timestamp(REF) - pd.Timedelta(days=1))
    return pd.Series(3.90, index=days, name="rate")


def _handle(fixings=None) -> RLIRSwapCurve:
    return RLIRSwapCurve(
        rl_curve_id=CURVE_NAME,
        rl_curve_handle=_synthetic_curve(),
        fixings=_synthetic_fixings() if fixings is None else fixings,
        meta_data={"requested_curve_name": CURVE_NAME, "id": CURVE_NAME,
                   "curve_name": CURVE_NAME,
                   "timestamp": pd.Timestamp("2026-06-16 12:00"),
                   "snapshot_lag_seconds": 0.0,
                   "snapshot_served_from_future": False},
    )


class FakePricer:
    """The three seam members :class:`krd.KrdProjector` uses, and a call count.

    Named in full because the first fake written against ``UnitRepricer`` was
    built from a docstring that listed two of its five members and failed on the
    third: ``curve_for``, ``mark_curve``, ``clear``.
    """

    source = "SYNTHETIC"
    snapshot_governed = True

    def __init__(self, curve_for=None, *, miss=False):
        self._curve_for = curve_for or {"SOFR": CURVE_NAME, "FED_FUNDS": CURVE_NAME}
        self.marks: list = []
        self.miss = miss
        self._handle = _handle()

    def curve_for(self, rate_index: str) -> str:
        try:
            return self._curve_for[rate_index]
        except KeyError:
            from SDRUtils.dealer_direction.midprice import UnsupportedIndex

            raise UnsupportedIndex(rate_index) from None

    def mark_curve(self, curve_name: str, instant):
        from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss
        from SDRUtils.dealer_direction.midprice import CurveMark

        self.marks.append((curve_name, instant))
        if self.miss:
            raise SnapshotMiss(f"no snapshot for {curve_name} at {instant}")
        return CurveMark(policy="SYNTHETIC", curve_name=curve_name,
                         requested=pd.Timestamp(instant), lag_seconds=0.0,
                         served_from_future=False, served_utc=None,
                         handle=self._handle)

    def clear(self) -> None:
        pass


def _ny(hh, mm=0, day=17) -> pd.Timestamp:
    return pd.Timestamp(NY.localize(datetime.datetime(2026, 6, day, hh, mm)))


def _mat(tenor, effective=None):
    return rl.add_tenor(effective or SPOT, tenor, "MF", "nyc")


def _unit(unit_key="U", *, kind=conv.OUTRIGHT, tenors=("10Y",), notionals=(100e6,),
          rates=(0.0404,), effectives=None, rate_index="SOFR",
          instant=None) -> T.Unit:
    instant = instant if instant is not None else _ny(11)
    effectives = effectives or [SPOT] * len(tenors)
    legs = pd.DataFrame([
        {"trade_id": f"{unit_key}-{i}",
         "effective_date": pd.Timestamp(eff).date(),
         "expiration_date": pd.Timestamp(_mat(t, eff)).date(),
         "notional": float(n), "fixed_rate": float(r)}
        for i, (t, n, r, eff) in enumerate(zip(tenors, notionals, rates, effectives))
    ])
    clocks = T.Clocks(pricing=instant, execution=instant, event=instant,
                      visibility=instant + pd.Timedelta(minutes=15),
                      visibility_source="APPENDIX_C_ESTIMATE")
    return T.Unit(unit_key=unit_key, kind=kind, legs=legs,
                  package_id=None if len(legs) == 1 else unit_key,
                  rate_index=rate_index, as_of_date=datetime.date(2026, 6, 17),
                  venue_class=T.VENUE_D2C, clocks=clocks)


def _call(unit_key="U", *, p=0.9, rule=conv.RULE_RATE, exclusion=None):
    sw = None if p is None else conv.signed_weight(p)
    return T.DirectionCall(
        unit_key=unit_key, rule=rule, deviation_bps=1.0, p=p, signed_weight=sw,
        dealer_sign=0 if p is None else (1 if p > 0.5 else -1),
        tau_bucket="SOFR_5Y", tau_bps=0.35, exclusion=exclusion,
    )


@pytest.fixture()
def projector():
    return K.KrdProjector(FakePricer())


@pytest.fixture()
def small_projector():
    """The cross-check grid. ``allow_reduced_grid`` is the documented escape."""
    return K.KrdProjector(FakePricer(), pillars=XCHECK_PILLARS,
                          allow_reduced_grid=True)


def _profile(projector, unit, rule=conv.RULE_RATE) -> dict:
    return projector.unit_krd(unit, rule)


def _par(projector, *tenors, instant=None):
    """The solver's own par rates, as decimals, for the standard block.

    Off-market trades do not land at their own pillar and they are not supposed
    to: a 7Y struck 144 bp away from mid carries a large NPV whose discounting
    sensitivity spreads across the front of the grid. That is the right answer
    and it is measured elsewhere; a test about *placement* has to strike at par
    or it is testing the off-market smear instead.
    """
    model = projector.model_for("SOFR", instant if instant is not None else _ny(11))
    s = np.asarray(model.solver.s, dtype=float)
    order = list(model.pillars)
    return tuple(float(s[order.index(t)]) / 100.0 for t in tenors)


# ==========================================================================
# 1. the sign -- one flip, pinned numerically
# ==========================================================================

def test_a_received_outright_is_long_duration_and_lands_at_its_own_pillar(projector):
    """``+ = dealer RECEIVED fixed = long duration``, and the mass sits at 10Y.

    Magnitude as well as sign: a flip that also lost the notional scaling would
    pass a ``> 0`` assertion. A $100mm 10Y OIS is worth roughly $82k per bp on
    this curve, so the tolerance is wide enough to survive a curve edit and far
    too tight to survive a factor.
    """
    prof = _profile(projector, _unit(rates=_par(projector, "10Y")))
    assert prof["10Y"] > 0.0
    total = sum(prof.values())
    assert total == pytest.approx(prof["10Y"], rel=1e-3)
    assert 60_000.0 < total < 110_000.0
    assert max(abs(v) for k, v in prof.items() if k != "10Y") < 0.01 * abs(total)


def test_the_flip_is_exactly_RL_DELTA_TO_FUTURES_EQ_and_nothing_else(projector):
    """The module's output is rateslib's raw delta times one constant.

    Recomputed here from the projector's own instruments, so the test fails if
    the flip is dropped, doubled, or made per-bucket -- the three ways this line
    has actually broken.
    """
    unit = _unit()
    model, instruments = projector.unit_positions(unit, conv.RULE_RATE)
    raw = rl.Portfolio(instruments).delta(solver=model.solver).iloc[:, 0]
    raw = {str(k[-1]): float(v) for k, v in raw.items()}
    prof = _profile(projector, unit)

    assert conv.RL_DELTA_TO_FUTURES_EQ == -1.0
    for bucket, got in prof.items():
        assert got == pytest.approx(conv.RL_DELTA_TO_FUTURES_EQ * raw[bucket],
                                    rel=1e-12, abs=1e-9)
    # ...and the raw delta really is the opposite sign, i.e. a flip was needed.
    assert raw["10Y"] < 0.0 < prof["10Y"]


def test_the_hypothesis_is_the_received_side_regardless_of_the_call(projector):
    """This module never sees ``dealer_sign``; feeding it one would double-sign.

    ``ladder.orient_to_received`` owns that multiply and ``ladder.DoubleSignedKRD``
    refuses a frame that skipped it.
    """
    frame, failures = projector.krd_frame([_unit()], [_call(p=0.1)])   # dealer PAID
    assert failures.empty
    assert "dealer_sign" not in frame.columns
    # p = 0.1 is a *paid* call, but the profile is still the received hypothesis.
    assert frame.loc[frame["bucket_key"] == "10Y", "dv01_if_received"].iloc[0] > 0.0


# ==========================================================================
# 2. multi-leg orientation -- one inferred bit, the whole vector
# ==========================================================================

def test_a_curve_unit_gets_opposite_signed_legs(projector):
    """``base_orientation(CURVE) = (-1, +1)``: receive the front, pay the back.

    Under the received hypothesis the dealer holds ``+1 * o``, so the front leg
    is the PAID one (negative) and the back leg the RECEIVED one (positive).
    """
    unit = _unit("C", kind=conv.CURVE, tenors=("2Y", "10Y"),
                 notionals=(500e6, 100e6), rates=_par(projector, "2Y", "10Y"))
    prof = _profile(projector, unit)
    assert prof["2Y"] < 0.0 < prof["10Y"]
    signs = conv.dealer_received_signs(conv.CURVE, 2, conv.RULE_RATE,
                                       conv.DEALER_RECEIVED)
    assert signs == (-1, 1)


def test_a_fly_puts_the_belly_opposite_its_wings(projector):
    unit = _unit("F", kind=conv.FLY, tenors=("2Y", "5Y", "10Y"),
                 notionals=(100e6, 200e6, 100e6),
                 rates=_par(projector, "2Y", "5Y", "10Y"))
    prof = _profile(projector, unit)
    assert prof["5Y"] > 0.0
    assert prof["2Y"] < 0.0 and prof["10Y"] < 0.0


def test_the_upfront_rule_signs_every_leg_the_same_way(projector):
    """One fee cannot resolve a package's internal orientation, only its net side.

    ``base_orientation(..., RULE_UPFRONT)`` is ``(1,)*n``, so the same two legs
    that oppose each other under the rate rule are co-signed under this one.
    """
    unit = _unit("C", kind=conv.CURVE, tenors=("2Y", "10Y"),
                 notionals=(500e6, 100e6), rates=_par(projector, "2Y", "10Y"))
    prof = _profile(projector, unit, rule=conv.RULE_UPFRONT)
    assert prof["2Y"] > 0.0 and prof["10Y"] > 0.0


def test_the_notional_sign_comes_from_the_hypothesis_not_from_the_tape(projector):
    """Field #31 is an unsigned amount; a signed one would sign the leg twice."""
    a = _profile(projector, _unit("A", notionals=(100e6,)))
    b = _profile(projector, _unit("B", notionals=(-100e6,)))
    assert b["10Y"] == pytest.approx(a["10Y"], rel=1e-12)


# ==========================================================================
# 3. the frame is the contract ladder.py consumes
# ==========================================================================

def test_the_frame_feeds_the_ladder_without_being_reoriented(projector):
    units = [_unit("U")]
    calls = [_call("U", p=0.9)]
    frame, failures = projector.krd_frame(units, calls)

    assert list(frame.columns) == K.KRD_COLUMNS
    assert set(frame["bucket_space"]) == {K.BUCKET_SPACE}
    assert K.BUCKET_SPACE == "IRS_KRD"
    assert ladder.KRD_VALUE_COL in frame.columns
    assert failures.empty

    rows, excluded = ladder.unit_ladder_rows(units, calls, frame)
    assert excluded.empty
    assert len(rows) == len(frame)
    # 2p-1 = 0.8 at p = 0.9, applied once.
    teny = rows[rows["bucket_key"] == "10Y"].iloc[0]
    assert teny["delta_dv01"] == pytest.approx(0.8 * teny["dv01_if_received"])


def test_the_dust_floor_is_relative_to_the_unit_not_absolute():
    """An absolute USD/bp floor deletes small units whole.

    Measured on 2026-04-01: a 0.05 USD/bp floor drops 53% of rows and 0.00006%
    of the gross, but the worst row it drops is 95.4% of *its own unit's* risk.
    So the floor is a fraction of the unit's own gross, and two units a
    thousandfold apart in size must keep the same buckets.
    """
    big = _unit("BIG", notionals=(1e9,))
    small = _unit("SMALL", notionals=(1e6,))
    p = K.KrdProjector(FakePricer(), dust_frac=1e-3)
    frame, _ = p.krd_frame([big, small], [_call("BIG"), _call("SMALL")])
    kept = frame.groupby("unit_key")["bucket_key"].apply(set)
    assert kept["BIG"] == kept["SMALL"]
    assert 0 < len(kept["BIG"]) < len(K.PILLARS)

    lossless, _ = K.KrdProjector(FakePricer()).krd_frame(
        [big], [_call("BIG")])
    assert len(lossless) == len(K.PILLARS), "the default must drop nothing"

    with pytest.raises(ValueError, match="dust_frac"):
        K.KrdProjector(FakePricer(), dust_frac=1.5)


def test_a_unit_whose_call_is_already_excluded_is_never_priced(projector):
    """The exclusion is the ladder's to report; re-reporting it double-counts."""
    frame, failures = projector.krd_frame(
        [_unit("U")], [_call("U", p=None, exclusion=T.EXCL_STANDARD_COUPON)])
    assert frame.empty and failures.empty
    assert projector.n_models == 0, "an excluded unit must not build a solver"


# ==========================================================================
# 4. the bucket grid
# ==========================================================================

def test_the_production_grid_carries_the_pillars_the_measurement_requires():
    assert len(K.PILLARS) == 28
    assert "11Y" in K.PILLARS
    assert {"40Y", "50Y"} <= set(K.PILLARS)
    assert {"7Y", "9Y", "10Y"} <= set(K.PILLARS)      # TY / UXY CTDs
    assert {"20Y", "25Y", "30Y"} <= set(K.PILLARS)    # US / WN CTDs
    K.validate_pillars(K.PILLARS)


@pytest.mark.parametrize("bad, needle", [
    ([p for p in K.PILLARS if p != "11Y"], "11Y"),
    ([p for p in K.PILLARS if p not in ("40Y", "50Y")], "40Y"),
    (["3M", "1Y", "5Y", "10Y", "30Y", "40Y", "11Y"], "21"),
])
def test_a_grid_that_relocates_risk_is_refused(bad, needle):
    with pytest.raises(K.UnusableBucketGrid, match=needle):
        K.validate_pillars(bad)


def test_the_projector_refuses_a_bad_grid_at_construction():
    """The check has to be on the constructor, not only on the free function.

    A validator nothing calls is documentation. The reduced grid stays
    reachable, but only by asking for it in as many words.
    """
    with pytest.raises(K.UnusableBucketGrid, match="11Y"):
        K.KrdProjector(FakePricer(), pillars=[p for p in K.PILLARS if p != "11Y"])
    with pytest.raises(K.UnusableBucketGrid, match="40Y"):
        K.KrdProjector(FakePricer(),
                       pillars=[p for p in K.PILLARS if p not in ("40Y", "50Y")])
    with pytest.raises(K.UnusableBucketGrid, match="21"):
        K.KrdProjector(FakePricer(), pillars=XCHECK_PILLARS)
    assert K.KrdProjector(FakePricer(), pillars=XCHECK_PILLARS,
                          allow_reduced_grid=True).pillars == XCHECK_PILLARS


def test_every_pillar_is_a_bucket_and_the_labels_are_the_grid(projector):
    prof = _profile(projector, _unit())
    assert list(prof) == list(K.PILLARS)


def test_a_fifty_year_trade_keeps_its_risk_at_the_long_pillars(projector):
    """Without a >=40Y pillar the same trade becomes a 30Y/25Y dipole (p14)."""
    prof = _profile(projector, _unit("L", tenors=("50Y",), notionals=(25e6,),
                                     rates=_par(projector, "50Y")))
    total = sum(prof.values())
    assert prof["50Y"] / total > 0.95
    assert abs(prof["30Y"]) < 0.02 * abs(total)


def test_a_forward_starting_leg_lands_across_its_own_span(projector):
    unit = _unit("W", tenors=("10Y",), notionals=(150e6,), rates=(0.0410,),
                 effectives=[_mat("1Y")])
    prof = _profile(projector, unit)
    assert prof["11Y"] > 0.0, "1Yx10Y needs the 11Y pillar"
    assert prof["1Y"] < 0.0, "the forward start is short the front"


# ==========================================================================
# 5. one solver per block, not per curve-minute
# ==========================================================================

def test_the_solver_is_reused_across_a_block_and_rebuilt_across_blocks():
    """547,338 distinct (index, exec-minute) pairs; a per-minute solver is 6.4h.

    Per *day* was measured to fail (p11: 5.2% of total DV01 on 2025-04-07), so
    the unit is a block; the count is what proves the cache key is the block and
    not the minute.
    """
    p = K.KrdProjector(FakePricer(), block_minutes=60)
    # T-1min, so 11:05 snaps into the 11:00 block and 11:00 would snap into the
    # 10:00 one -- the rule is snapshot.snap_instant's, not this module's
    for minute in (5, 17, 59):
        p.unit_krd(_unit(f"A{minute}", instant=_ny(11, minute)), conv.RULE_RATE)
    assert p.n_models == 1
    p.unit_krd(_unit("B", instant=_ny(12, 30)), conv.RULE_RATE)
    assert p.n_models == 2
    # a different index is a different curve, so a different model
    p.unit_krd(_unit("C", instant=_ny(12, 35), rate_index="FED_FUNDS"), conv.RULE_RATE)
    assert p.n_models == 3


def test_the_block_anchor_is_the_first_trade_in_it_and_never_looks_ahead():
    p = K.KrdProjector(FakePricer(), block_minutes=60)
    late = _ny(11, 40)
    p.unit_krd(_unit("A", instant=late), conv.RULE_RATE)
    model = p.model_for("SOFR", late)
    assert pd.Timestamp(model.anchor) <= pd.Timestamp(late)
    # every later trade in the block reuses that anchor, so the curve is never
    # from after the print -- which is the one failure the package exists to stop
    for minute in (41, 55, 59):
        got = p.model_for("SOFR", _ny(11, minute))
        assert got is model


def test_an_out_of_order_unit_is_refused_rather_than_given_a_future_curve():
    """The anchor rule only holds if the input is sorted, so the module checks.

    An earlier print served from a later trade's anchor gets a curve that can
    already contain it -- up to ``block_minutes`` of lookahead, silent, and
    biased towards whatever the trade actually was. Same failure
    ``midprice.CircularCurve`` guards on the snapshot side, and here it takes
    only a mis-sorted frame.
    """
    p = K.KrdProjector(FakePricer(), block_minutes=60)
    p.unit_krd(_unit("LATE", instant=_ny(11, 50)), conv.RULE_RATE)
    with pytest.raises(K.LookaheadCurve, match="execution order"):
        p.unit_krd(_unit("EARLY", instant=_ny(11, 10)), conv.RULE_RATE)
    # and it surfaces as a named failure, not a crash, through the frame API
    q = K.KrdProjector(FakePricer(), block_minutes=60)
    frame, failures = q.krd_frame(
        [_unit("LATE", instant=_ny(11, 50)), _unit("EARLY", instant=_ny(11, 10))],
        [_call("LATE"), _call("EARLY")])
    assert set(frame["unit_key"]) == {"LATE"}
    assert failures["failure_reason"].tolist() == [T.EXCL_PRICING_ERROR]
    assert "LookaheadCurve" in failures["failure_detail"].iloc[0]


def test_a_block_never_spans_midnight():
    """Blocks are keyed on the New York date, so 23:5x and 00:0x are not one hour."""
    p = K.KrdProjector(FakePricer(), block_minutes=180)
    a = K.block_key(_ny(23, 55, day=17), 180)
    b = K.block_key(_ny(0, 5, day=18), 180)
    assert a != b
    assert a[0] == datetime.date(2026, 6, 17) and b[0] == datetime.date(2026, 6, 18)


def test_the_day_scope_drops_every_model():
    p = K.KrdProjector(FakePricer(), block_minutes=60)
    with p.day_scope():
        p.unit_krd(_unit("A", instant=_ny(11)), conv.RULE_RATE)
        assert p.n_models == 1
    assert p.n_models == 0


# ==========================================================================
# 6. named failures, never a guess and never a drop
# ==========================================================================

def test_a_four_leg_package_is_excluded_rather_than_oriented(projector):
    unit = _unit("P", kind=conv.PKG, tenors=("2Y", "5Y", "10Y", "30Y"),
                 notionals=(1e8,) * 4, rates=(0.039,) * 4)
    frame, failures = projector.krd_frame([unit], [_call("P")])
    assert frame.empty
    assert failures["failure_reason"].tolist() == [T.EXCL_UNORIENTABLE]


def test_an_index_with_no_curve_is_named_not_dropped(projector):
    unit = _unit("B", rate_index="BASIS")
    frame, failures = projector.krd_frame([unit], [_call("B")])
    assert frame.empty
    assert failures["failure_reason"].tolist() == [T.EXCL_UNSUPPORTED_INDEX]


def test_a_leg_that_cannot_price_is_named_not_dropped(projector):
    unit = _unit("X", tenors=("10Y",), notionals=(100e6,), rates=(0.0404,))
    unit.legs.loc[0, "fixed_rate"] = None
    frame, failures = projector.krd_frame([unit], [_call("X")])
    assert frame.empty
    assert failures["failure_reason"].tolist() == [T.EXCL_NO_FIXED_RATE]


def test_a_missing_snapshot_is_NO_CURVE_not_a_crash():
    """SnapshotMiss is a result, not an error: the print had no curve to price on."""
    p = K.KrdProjector(FakePricer(miss=True))
    frame, failures = p.krd_frame([_unit("M")], [_call("M")])
    assert frame.empty
    assert failures["failure_reason"].tolist() == [T.EXCL_NO_CURVE]


def test_units_and_calls_have_to_agree(projector):
    with pytest.raises(ValueError, match="no direction call"):
        projector.krd_frame([_unit("U")], [_call("OTHER")])


# ==========================================================================
# 7. past-start legs -- 14.6% of the tape, and the only ones needing fixings
# ==========================================================================

def test_a_past_starting_leg_prices_against_published_fixings(projector):
    """Without the fixings rateslib raises; with them the risk is a live stub."""
    unit = _unit("S", tenors=("5Y",), notionals=(50e6,), rates=(0.0425,),
                 effectives=[REF - datetime.timedelta(days=730)])
    prof = _profile(projector, unit)
    total = sum(prof.values())
    assert np.isfinite(total) and total > 0.0
    # ~3y of a 5y swap left: the mass belongs at the 3Y pillar, not the 5Y one.
    assert prof["3Y"] > prof["5Y"] > 0.0
    assert abs(sum(v for k, v in prof.items()
                   if k in ("10Y", "20Y", "30Y", "40Y", "50Y"))) < 0.01 * total


# ==========================================================================
# 8. the independent second opinion
# ==========================================================================

def _tent_amplitudes(curve, grid_dates):
    """Node-level tent amplitudes ``a_j(node) = w_j(u) * u`` on the curve's nodes.

    **Node-interpolated, not continuous.** The two differ by 0.378% at 30Y on
    Citi's node spacing, because the spacing jumps to 5y past 20y -- and the
    node-interpolated one is what a log-linear curve actually does under a
    shift, so it is the one that matches.
    """
    node_dates = list(curve.nodes.nodes)
    nd = np.array([(pd.Timestamp(d) - pd.Timestamp(curve.nodes.initial)).days
                   for d in node_dates], float)
    gd = np.array([(pd.Timestamp(d) - pd.Timestamp(curve.nodes.initial)).days
                   for d in grid_dates], float)
    W = np.zeros((nd.size, gd.size))
    for a, t in enumerate(nd):
        if t <= gd[0]:
            W[a, 0] = 1.0
        elif t >= gd[-1]:
            W[a, -1] = 1.0
        else:
            j = int(np.searchsorted(gd, t) - 1)
            f = (t - gd[j]) / (gd[j + 1] - gd[j])
            W[a, j], W[a, j + 1] = 1.0 - f, f
    return node_dates, W * (nd / 365.0)[:, None]


def _shocked(curve, node_dates, amps, j, bump_bp):
    tent = rl.Curve(
        nodes={d: float(np.exp(-bump_bp * 1e-4 * amps[i, j]))
               for i, d in enumerate(node_dates)},
        convention=curve.meta.convention, calendar=curve.meta.calendar,
        modifier=curve.meta.modifier, id=f"tent{j}")
    return rl.CompositeCurve([curve, tent])


def test_the_profile_survives_an_independent_zero_space_bump_and_reprice(small_projector):
    """A second opinion that shares no code with the producer.

    Bump each *zero* tent, reprice the trade and the K calibrating swaps, and
    convert the resulting zero-KRD into par space through the curve's own
    ``ds/dz``. The conversion is not optional: raw zero-KRD and par delta are
    different derivatives -- a parallel zero shift moves par rates by ~1.02bp --
    and they disagree by 1.6-44% of total DV01 until it is applied. Reported
    agreement after it, on the real curve, was 0.0001-0.28%.
    """
    unit = _unit("V", tenors=("7Y",), notionals=(250e6,), rates=(0.0250,))
    model, instruments = small_projector.unit_positions(unit, conv.RULE_RATE)
    curve = model.risk_handle.handle()
    grid = [i.leg1.schedule.termination for i in model.calibrating_instruments]
    node_dates, amps = _tent_amplitudes(curve, grid)
    n = len(grid)

    zero_krd = np.empty(n)
    dsdz = np.empty((n, n))
    for j in range(n):
        up, dn = (_shocked(curve, node_dates, amps, j, b) for b in (+1.0, -1.0))
        zero_krd[j] = 0.5 * (
            float(rl.Portfolio(instruments).npv(curves=up))
            - float(rl.Portfolio(instruments).npv(curves=dn)))
        for i, inst in enumerate(model.calibrating_instruments):
            # percent -> bp, so ds/dz is dimensionless
            dsdz[i, j] = 0.5 * 100.0 * (float(inst.rate(curves=up).real)
                                        - float(inst.rate(curves=dn).real))

    reference = conv.RL_DELTA_TO_FUTURES_EQ * np.linalg.solve(dsdz.T, zero_krd)
    got = np.array([small_projector.unit_krd(unit, conv.RULE_RATE)[p]
                    for p in model.pillars])
    total = abs(got.sum())

    # the raw zero-KRD is NOT the answer -- if it were, the conversion would be
    # decoration and this test would not be checking it
    raw = conv.RL_DELTA_TO_FUTURES_EQ * zero_krd
    assert np.abs(raw - got).max() > 0.01 * total
    assert np.abs(reference - got).max() < 0.003 * total


def test_the_bump_and_reprice_reference_agrees_with_itself_on_a_known_case(small_projector):
    """Validate the checking tool before trusting it.

    A tool that is itself wrong reports success and hides what it was built to
    find. Here the known answer is the total: the zero-KRD of a parallel shift
    of every tent must equal the trade's own DV01 to the O(h^2) of a central
    difference, whichever basis it is expressed in.
    """
    unit = _unit("V", tenors=("7Y",), notionals=(250e6,), rates=(0.0250,))
    model, instruments = small_projector.unit_positions(unit, conv.RULE_RATE)
    curve = model.risk_handle.handle()
    grid = [i.leg1.schedule.termination for i in model.calibrating_instruments]
    node_dates, amps = _tent_amplitudes(curve, grid)

    # the tents partition unity, so their sum is a parallel zero shift
    flat = rl.Curve(nodes={d: float(np.exp(-1e-4 * amps[i, :].sum()))
                           for i, d in enumerate(node_dates)},
                    convention=curve.meta.convention, calendar=curve.meta.calendar,
                    modifier=curve.meta.modifier, id="flat")
    up = float(rl.Portfolio(instruments).npv(curves=rl.CompositeCurve([curve, flat])))
    base = float(rl.Portfolio(instruments).npv(curves=curve))
    parallel = up - base

    each = 0.0
    for j in range(len(grid)):
        u = _shocked(curve, node_dates, amps, j, +1.0)
        each += float(rl.Portfolio(instruments).npv(curves=u)) - base
    assert each == pytest.approx(parallel, rel=2e-3)
