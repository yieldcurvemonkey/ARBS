"""The aggregation, the health monitor and the provenance record, pinned.

Three failures this file exists to make impossible, all of them silent in a
system that otherwise looks correct:

1. **Weighting DV01 by ``p`` rather than ``2p-1``.** A coin flip would load
   half a position into the ladder and nothing would look wrong.
2. **Stamping a row on execution time.** The ladder would be right and
   unusable, because every row would be dated before it could be acted on.
3. **A health monitor that rises as the mid degrades.** F-20 measured the old
   pipeline's mid biased ~0.5 bp high, which pushed 78% of `RATE_VS_MID` calls
   to one side. A naive agreement statistic scores that *higher*, not lower --
   so the monitor has to be built against the marginals, and that is pinned
   here with a known-answer case before it is trusted on real flow.
"""
from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd
import pytest
import pytz

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import health, ladder, provenance
from SDRUtils.dealer_direction import types as T

NY = pytz.timezone("America/New_York")


# --------------------------------------------------------------------------
# fixtures -- the smallest objects that exercise the real contract
# --------------------------------------------------------------------------

def _ny(y, m, d, hh, mm=0) -> pd.Timestamp:
    """A New York wall-clock instant, carried in UTC like the tape carries it."""
    return pd.Timestamp(NY.localize(datetime.datetime(y, m, d, hh, mm))).tz_convert("UTC")


def _clocks(*, execution, visibility, event=None, pricing=None) -> T.Clocks:
    return T.Clocks(
        pricing=pricing if pricing is not None else execution,
        execution=execution,
        event=event if event is not None else execution,
        visibility=visibility,
        visibility_source="APPENDIX_C_ESTIMATE",
        report_lag_seconds=0.0,
    )


def _legs(n=1, *, as_of=datetime.date(2026, 6, 10)) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_id": [f"T{i}" for i in range(n)],
            "as_of_date": [as_of] * n,
            "effective_date": [as_of] * n,
            "expiration_date": [as_of + datetime.timedelta(days=365 * 5)] * n,
            "notional": [100e6] * n,
            "fixed_rate": [0.0394] * n,
        }
    )


def _unit(unit_key, *, venue=T.VENUE_D2C, lifecycle=False, kind=conv.OUTRIGHT,
          n_legs=1, execution=None, visibility=None, event=None,
          as_of=datetime.date(2026, 6, 10), is_block=False) -> T.Unit:
    execution = execution if execution is not None else _ny(2026, 6, 10, 10, 0)
    visibility = visibility if visibility is not None else execution + pd.Timedelta(minutes=60)
    return T.Unit(
        unit_key=unit_key,
        kind=kind,
        legs=_legs(n_legs, as_of=as_of),
        package_id=None if n_legs == 1 else unit_key,
        rate_index="SOFR",
        as_of_date=as_of,
        venue_class=venue,
        clocks=_clocks(execution=execution, visibility=visibility, event=event),
        is_lifecycle=lifecycle,
        is_block=is_block,
    )


def _call(unit_key, p, *, rule=conv.RULE_RATE, dead_zone=False,
          exclusion=None, tau_bucket="SOFR_5Y") -> T.DirectionCall:
    sw = None if p is None else conv.signed_weight(p)
    return T.DirectionCall(
        unit_key=unit_key,
        rule=rule,
        deviation_bps=None if p is None else (p - 0.5) * 4.0,
        p=p,
        signed_weight=sw,
        dealer_sign=0 if p is None else (1 if p > 0.5 else (-1 if p < 0.5 else 0)),
        tau_bucket=tau_bucket,
        tau_bps=0.35,
        in_dead_zone=dead_zone,
        exclusion=exclusion,
    )


def _krd(unit_key, *, bucket="5Y", value=1000.0, space="IRS_KRD") -> pd.DataFrame:
    return pd.DataFrame(
        [{"unit_key": unit_key, "bucket_space": space,
          "bucket_key": bucket, "dv01_if_received": value}]
    )


def _no_ladder_exclusions() -> pd.DataFrame:
    """The explicit statement that the ladder threw nothing out.

    `coverage_table` has no default for this, because a caller who never makes
    the statement gets the ladder's own exclusions read as successes.
    """
    return pd.DataFrame(columns=ladder.EXCLUSION_COLUMNS)


# ==========================================================================
# 1. ladder.py -- the weight is 2p-1, not p
# ==========================================================================

def test_a_coin_flip_contributes_nothing_to_the_ladder():
    """`p`-weighting would put half a long position in the ladder at p=0.5.

    This is the aggregation-level restatement of
    `conventions.signed_weight`: it is pinned twice because the conventions
    test only proves the *function* is right, not that the ladder calls it.
    """
    rows, _ = ladder.unit_ladder_rows([_unit("U")], [_call("U", 0.5)], _krd("U"))
    assert len(rows) == 1
    assert rows["dv01_if_received"].iloc[0] == pytest.approx(1000.0)
    assert rows["delta_dv01"].iloc[0] == 0.0          # not 500.0


@pytest.mark.parametrize(("p", "expected"), [(1.0, 1000.0), (0.75, 500.0),
                                             (0.5, 0.0), (0.25, -500.0),
                                             (0.0, -1000.0)])
def test_the_ladder_contribution_is_linear_in_2p_minus_1(p, expected):
    rows, _ = ladder.unit_ladder_rows([_unit("U")], [_call("U", p)], _krd("U"))
    assert rows["delta_dv01"].iloc[0] == pytest.approx(expected)


def test_a_dealer_signed_krd_is_refused_rather_than_double_signed():
    """The single most likely arithmetic bug in this module.

    If the KRD frame is already signed by `dealer_sign`, multiplying it by
    `2p-1` -- which carries the same sign by construction -- produces
    `|2p-1| * |dv01|`, i.e. a ladder that is positive everywhere. The input
    contract is therefore the *hypothesis* profile (`dv01_if_received`), and a
    frame that looks dealer-signed is rejected, not quietly consumed.
    """
    dealer_signed = pd.DataFrame(
        [{"unit_key": "U", "bucket_space": "IRS_KRD", "bucket_key": "5Y",
          "delta_dv01": -1000.0, "dealer_sign": -1}]
    )
    with pytest.raises(ladder.DoubleSignedKRD):
        ladder.unit_ladder_rows([_unit("U")], [_call("U", 0.2)], dealer_signed)

    # ...and the documented conversion is available, exactly once.
    oriented = ladder.orient_to_received(dealer_signed)
    assert oriented["dv01_if_received"].iloc[0] == pytest.approx(1000.0)
    rows, _ = ladder.unit_ladder_rows([_unit("U")], [_call("U", 0.2)], oriented)
    assert rows["delta_dv01"].iloc[0] == pytest.approx(-600.0)


# ==========================================================================
# 2. ladder.py -- the availability clock, never execution
# ==========================================================================

def test_the_ladder_date_is_the_visibility_date_not_the_execution_date():
    """A 23:30 ET print is not actionable until the next New York day.

    Dating it on execution is lookahead of exactly the delay Part 43 grants,
    which is the whole reason `Clocks` carries three fields.
    """
    execution = _ny(2026, 6, 10, 23, 30)
    unit = _unit("LATE", execution=execution,
                 visibility=execution + pd.Timedelta(minutes=60))
    rows, _ = ladder.unit_ladder_rows([unit], [_call("LATE", 0.9)], _krd("LATE"))
    assert rows["visibility_date"].iloc[0] == datetime.date(2026, 6, 11)
    # the execution clock says the 10th, and is carried but never keyed on
    assert rows["execution_timestamp"].iloc[0] == execution


def test_the_ladder_date_is_a_new_york_date_not_a_utc_date():
    """20:30 ET is 00:30 UTC the following day.

    Bucketing on the UTC date pushes the whole US afternoon session into
    tomorrow -- the same wire-timezone error that had to be fixed in the
    citivelo minute warm.
    """
    execution = _ny(2026, 6, 10, 19, 30)
    visibility = execution + pd.Timedelta(minutes=60)          # 20:30 ET = 00:30Z
    assert visibility.date() == datetime.date(2026, 6, 11)     # the trap
    unit = _unit("EVE", execution=execution, visibility=visibility)
    rows, _ = ladder.unit_ladder_rows([unit], [_call("EVE", 0.9)], _krd("EVE"))
    assert rows["visibility_date"].iloc[0] == datetime.date(2026, 6, 10)


def test_a_date_only_event_stamp_keeps_the_day_it_was_reported_on():
    """The EOD-fallback path produces a tz-NAIVE visibility stamp.

    `universe._clocks` adds the Appendix C delay to the pricing instant, and on
    a date-only #30 that instant is a bare `datetime.date` -- so the result is a
    naive 01:00, not a UTC instant. Reading it as UTC and shifting to New York
    would date the print on the 9th: a whole day of lookahead invented by a
    timezone. Every real tape stamp is `timestamp with time zone`, so naive can
    only mean this.
    """
    naive = pd.Timestamp("2026-06-10 01:00:00")        # date-only #30 + 60 min
    assert naive.tzinfo is None
    assert ladder.visibility_date(naive) == datetime.date(2026, 6, 10)
    assert ladder.visibility_date(datetime.date(2026, 6, 10)) == datetime.date(2026, 6, 10)

    unit = _unit("EOD", execution=_ny(2026, 6, 10, 10, 0), visibility=naive)
    rows, _ = ladder.unit_ladder_rows([unit], [_call("EOD", 0.9)], _krd("EOD"))
    assert rows["visibility_date"].iloc[0] == datetime.date(2026, 6, 10)


def test_a_stale_execution_stamp_cannot_reach_the_ladder_date():
    """F-12: on a lifecycle print, field #96 is frozen at the ORIGINAL trade.

    A 2018 execution stamp on a 2026 unwind must not date the row in 2018.
    """
    unit = _unit(
        "TERM", lifecycle=True,
        execution=pd.Timestamp("2018-04-01T14:15:36Z"),
        event=_ny(2026, 6, 10, 9, 57),
        visibility=_ny(2026, 6, 10, 10, 57),
    )
    rows, _ = ladder.unit_ladder_rows([unit], [_call("TERM", 0.8)], _krd("TERM"))
    assert rows["visibility_date"].iloc[0] == datetime.date(2026, 6, 10)


# ==========================================================================
# 3. ladder.py -- the series never merge
# ==========================================================================

def test_d2c_d2d_and_venue_unknown_are_three_series_not_two():
    """Dealers recycling risk is informative; it is not inventory being loaded.

    And `VENUE_UNKNOWN` -- 51,260 XXXX legs, 28,401 XOFF, a long tail (F-7) --
    is folded into neither, because assigning it to either one manufactures
    customer flow or manufactures recycling.
    """
    units, calls, krds = [], [], []
    for key, venue in [("A", T.VENUE_D2C), ("B", T.VENUE_D2D),
                       ("C", T.VENUE_UNKNOWN)]:
        units.append(_unit(key, venue=venue))
        calls.append(_call(key, 1.0))
        krds.append(_krd(key))
    rows, _ = ladder.unit_ladder_rows(units, calls, pd.concat(krds))
    agg = ladder.aggregate(rows)

    assert len(agg) == 3, "one bucket, one date, three venue classes"
    assert set(agg["venue_class"]) == {T.VENUE_D2C, T.VENUE_D2D, T.VENUE_UNKNOWN}
    assert (agg["delta_dv01"] == 1000.0).all()
    # the customer view is a selection, never a sum over venues
    cust = ladder.customer_flow(agg)
    assert list(cust["venue_class"].unique()) == [T.VENUE_D2C]
    assert cust["delta_dv01"].sum() == pytest.approx(1000.0)
    # ...and so is the recycling view, which is what health reads: swap the two
    # and the classifier is validated against the population it produced
    inter = ladder.interdealer_flow(agg)
    assert list(inter["venue_class"].unique()) == [T.VENUE_D2D]


def test_lifecycle_prints_are_their_own_series():
    """D8: the sign is right, but it is driven by seasoned P&L, not bid-offer.

    So the confidence model does not transfer and the two must not be pooled.
    """
    units = [_unit("FLOW"), _unit("TERM", lifecycle=True)]
    calls = [_call("FLOW", 1.0), _call("TERM", 1.0)]
    rows, _ = ladder.unit_ladder_rows(units, calls,
                                      pd.concat([_krd("FLOW"), _krd("TERM")]))
    agg = ladder.aggregate(rows)
    assert len(agg) == 2
    assert set(agg["series"]) == {ladder.SERIES_FLOW, ladder.SERIES_LIFECYCLE}


def test_the_aggregation_key_is_complete():
    """Two units in the same cell add; anything differing in the key does not."""
    units = [_unit("A"), _unit("B")]
    calls = [_call("A", 1.0), _call("B", 1.0)]
    rows, _ = ladder.unit_ladder_rows(units, calls,
                                      pd.concat([_krd("A"), _krd("B")]))
    agg = ladder.aggregate(rows)
    assert len(agg) == 1
    assert agg["delta_dv01"].iloc[0] == pytest.approx(2000.0)
    assert agg["n_units"].iloc[0] == 2
    assert list(ladder.LADDER_KEYS) == [
        "bucket_space", "bucket_key", "visibility_date", "venue_class", "series"
    ]


def test_the_gross_pond_is_not_recoverable_from_the_net():
    """A net of zero over $40mm gross and a net of zero over nothing are
    different statements about the day, and only the second one means the
    ladder is empty. So `abs_dv01` sums `|dv01_if_received|`, never
    `|delta_dv01|`, and `mean_abs_signed_weight` says how much of that pond
    survived the confidence weighting.
    """
    units, calls = [_unit("A"), _unit("B")], [_call("A", 0.5), _call("B", 0.5)]
    rows, _ = ladder.unit_ladder_rows(units, calls,
                                      pd.concat([_krd("A"), _krd("B")]))
    agg = ladder.aggregate(rows)
    assert agg["delta_dv01"].iloc[0] == pytest.approx(0.0)
    assert agg["abs_dv01"].iloc[0] == pytest.approx(2000.0)          # not 0.0
    assert agg["mean_abs_signed_weight"].iloc[0] == pytest.approx(0.0)  # not 1.0


def test_a_duplicated_ladder_key_is_refused_rather_than_summed():
    """Two rows on one key means the aggregation key is incomplete, and the
    cell a consumer reads is then the sum of two series it must never pool."""
    cell = {"bucket_space": "IRS_KRD", "bucket_key": "5Y",
            "visibility_date": datetime.date(2026, 6, 10),
            "venue_class": T.VENUE_D2C, "series": ladder.SERIES_FLOW,
            "delta_dv01": 100.0, "abs_dv01": 100.0, "n_units": 1,
            "mean_abs_signed_weight": 1.0}
    ladder.assert_series_disjoint(pd.DataFrame([cell]))
    with pytest.raises(ValueError, match="duplicated ladder key"):
        ladder.assert_series_disjoint(pd.DataFrame([cell, cell]))


def test_per_unit_rows_survive_the_aggregation():
    """The consumer needs the cell; the auditor needs the print behind it."""
    units = [_unit("A"), _unit("B")]
    calls = [_call("A", 1.0), _call("B", 0.1)]
    rows, _ = ladder.unit_ladder_rows(units, calls,
                                      pd.concat([_krd("A"), _krd("B")]))
    assert set(rows["unit_key"]) == {"A", "B"}
    for col in ("p", "signed_weight", "rule", "tau_bucket", "is_block",
                "rate_index", "kind", "as_of_date"):
        assert col in rows.columns


# ==========================================================================
# 4. ladder.py -- a flow series, not an inventory
# ==========================================================================

def test_accumulation_is_never_silent():
    """F-21: compression and allocation are never publicly reported.

    So a position accumulated from tape flow carries an unbounded, monotone
    error with no offsetting print. The caller must name a decay.
    """
    agg = ladder.aggregate(
        ladder.unit_ladder_rows([_unit("A")], [_call("A", 1.0)], _krd("A"))[0]
    )
    with pytest.raises(TypeError):
        ladder.decayed_flow(agg)                       # no default half-life
    with pytest.raises(ValueError):
        ladder.decayed_flow(agg, half_life_days=0.0)
    with pytest.raises(ValueError):
        ladder.decayed_flow(agg, half_life_days=None)


def test_the_decay_is_applied_on_calendar_days_and_travels_with_the_output():
    d0, d1 = datetime.date(2026, 6, 10), datetime.date(2026, 6, 20)
    agg = pd.DataFrame([
        {"bucket_space": "IRS_KRD", "bucket_key": "5Y", "visibility_date": d,
         "venue_class": T.VENUE_D2C, "series": ladder.SERIES_FLOW,
         "delta_dv01": 100.0, "abs_dv01": 100.0, "n_units": 1,
         "mean_abs_signed_weight": 1.0}
        for d in (d0, d1)
    ])
    out = ladder.decayed_flow(agg, half_life_days=10.0)
    got = out.set_index("visibility_date")["decayed_flow_dv01"]
    assert got[d0] == pytest.approx(100.0)
    assert got[d1] == pytest.approx(150.0)             # 100 * 0.5 + 100
    assert (out["decay_half_life_days"] == 10.0).all()

    # infinity is pure accumulation, and it is allowed only by naming it
    undecayed = ladder.decayed_flow(agg, half_life_days=math.inf)
    assert undecayed.set_index("visibility_date")["decayed_flow_dv01"][d1] == 200.0


def test_the_module_says_it_is_flow_not_inventory():
    """A consumer reads the docstring, not the ledger."""
    doc = (ladder.__doc__ or "").lower()
    assert "flow" in doc and "inventory" in doc


# ==========================================================================
# 5. ladder.py -- nothing is dropped without a name
# ==========================================================================

def test_an_excluded_call_leaves_the_ladder_carrying_its_reason():
    units = [_unit("OK"), _unit("BAD")]
    calls = [_call("OK", 0.9),
             _call("BAD", None, exclusion=T.EXCL_UNORIENTABLE)]
    rows, excluded = ladder.unit_ladder_rows(units, calls, _krd("OK"))
    assert list(rows["unit_key"]) == ["OK"]
    assert dict(zip(excluded["unit_key"], excluded["failure_reason"])) == {
        "BAD": T.EXCL_UNORIENTABLE
    }


def test_a_unit_with_no_risk_row_is_excluded_not_silently_dropped():
    rows, excluded = ladder.unit_ladder_rows(
        [_unit("A"), _unit("NORISK")],
        [_call("A", 0.9), _call("NORISK", 0.9)],
        _krd("A"),
    )
    assert list(rows["unit_key"]) == ["A"]
    assert list(excluded["unit_key"]) == ["NORISK"]
    assert excluded["failure_reason"].iloc[0] == T.EXCL_PRICING_ERROR


def test_a_call_with_no_probability_and_no_reason_is_a_loud_error():
    """A missing `p` with no exclusion is a programming error, not a data one."""
    bad = T.DirectionCall(unit_key="U", rule=conv.RULE_RATE, deviation_bps=None,
                          p=None, signed_weight=None, dealer_sign=0)
    with pytest.raises(ValueError, match="no probability"):
        ladder.unit_ladder_rows([_unit("U")], [bad], _krd("U"))


def test_a_unit_with_no_direction_call_is_a_hole_in_the_accounting():
    """The complement of the above, and the reason every unit must carry a call.

    A unit skipped here reaches neither returned frame, so it is not in the
    ladder and not in any reason's DV01 share either -- and the coverage table
    still sums to 1 over what is left.
    """
    with pytest.raises(ValueError, match="no direction call"):
        ladder.unit_ladder_rows([_unit("A"), _unit("B")], [_call("A", 0.9)],
                                pd.concat([_krd("A"), _krd("B")]))


def test_a_risk_row_for_a_unit_that_is_not_in_the_population_is_loud():
    """The reverse lookup nothing performs.

    The loop runs over `units` and reads the risk frame, so a risk row whose
    unit is not in the population is read by nobody -- it lands in neither
    `rows` nor `excluded`, and the pair stops being a partition for exactly the
    class of row that carries unattributed DV01.
    """
    ghost = pd.concat([_krd("A"), _krd("GHOST", value=9_000_000.0)])
    with pytest.raises(ValueError, match=r"not in `units`"):
        ladder.unit_ladder_rows([_unit("A")], [_call("A", 0.9)], ghost)


def test_the_same_unit_passed_twice_is_loud_rather_than_double_counted():
    """`n_units` is a nunique, so it reports 1 while carrying two units' risk.

    The one column a reader would check to spot the duplication is the column
    that conceals it, which is why this is refused where the duplication is
    still visible rather than caught in the aggregate.
    """
    with pytest.raises(ValueError, match="appears twice"):
        ladder.unit_ladder_rows([_unit("A"), _unit("A")],
                                [_call("A", 0.9)], _krd("A"))


def test_the_weight_guard_is_live_on_both_calls_it_names():
    """`_assert_weight_agrees_with_side` is the module's central sign guard.

    The `_call` fixture derives `signed_weight` and `dealer_sign` from `p`
    consistently, so nothing else in this file can construct the two producer
    errors it exists to catch -- and both are silent downstream, because the
    ladder only ever reads the weight.
    """
    p_as_weight = T.DirectionCall(
        unit_key="U", rule=conv.RULE_RATE, deviation_bps=1.6, p=0.9,
        signed_weight=0.9, dealer_sign=1)          # 2p-1 would be 0.8
    with pytest.raises(ValueError, match="is not 2p-1"):
        ladder.unit_ladder_rows([_unit("U")], [p_as_weight], _krd("U"))

    flipped_side = T.DirectionCall(
        unit_key="U", rule=conv.RULE_RATE, deviation_bps=1.6, p=0.9,
        signed_weight=0.8, dealer_sign=-1)         # p > 0.5 is dealer_sign +1
    with pytest.raises(ValueError, match="disagree on the side"):
        ladder.unit_ladder_rows([_unit("U")], [flipped_side], _krd("U"))


def test_orienting_a_unit_with_no_call_is_refused_rather_than_zeroed():
    """`dealer_sign = 0` is not a side. Multiplying by it is silent: the unit
    keeps its row, its risk becomes 0.0, and it disappears into the ladder as a
    cell that contributed nothing rather than as a unit with no call."""
    no_call = pd.DataFrame(
        [{"unit_key": "U", "bucket_space": "IRS_KRD", "bucket_key": "5Y",
          "delta_dv01": -1000.0, "dealer_sign": 0}]
    )
    with pytest.raises(ValueError, match="dealer_sign=0"):
        ladder.orient_to_received(no_call)


def test_dead_zone_units_are_kept_by_default_and_droppable_on_request():
    """DESIGN 1.3: `2p-1` already makes a marginal call contribute ~nothing.

    So the dead zone is a monitoring flag and an opt-in filter, not the thing
    the aggregation depends on.
    """
    units, calls = [_unit("D")], [_call("D", 0.52, dead_zone=True)]
    rows, excluded = ladder.unit_ladder_rows(units, calls, _krd("D"))
    assert len(rows) == 1 and len(excluded) == 0
    assert rows["delta_dv01"].iloc[0] == pytest.approx(40.0)

    rows, excluded = ladder.unit_ladder_rows(units, calls, _krd("D"),
                                             drop_dead_zone=True)
    assert len(rows) == 0
    assert excluded["failure_reason"].iloc[0] == T.EXCL_DEAD_ZONE


# ==========================================================================
# 6. health.py -- the D2D recycling monitor, validated before it is trusted
# ==========================================================================

def _series(vals, start="2026-01-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D").date
    return pd.Series(list(vals), index=pd.Index(idx, name="visibility_date"))


def test_kappa_is_one_when_the_recycling_is_perfect():
    signs = [(-1.0) ** i for i in range(120)]
    d2c = _series(signs)
    d2d = _series([0.0] + signs[:-1])                  # yesterday's flow, recycled
    res = health.d2d_recycling_kappa(d2c, d2d, horizon_days=1, n_bootstrap=0)
    assert res.n_pairs > 50
    assert res.kappa == pytest.approx(1.0)
    assert res.hit_rate == pytest.approx(1.0)


def test_a_mid_biased_off_venue_scores_zero_not_one():
    """THE test. F-20: a 0.5 bp mid bias pushed 78% of calls to one side.

    That bias hits the D2C and the D2D populations identically, so a naive
    matched-sign hit rate goes UP as the mid degrades -- the monitor would
    read healthiest exactly when the ladder is worthless. Correcting for the
    marginals is what makes the statistic read the classifier instead.

    **Two cases, because the limit does not reach the arithmetic.** With every
    print one way `chance` is 1 and `_kappa` short-circuits, so that half pins
    the degenerate flag and nothing else -- a `_kappa` that returned the raw
    hit rate would still pass it. The second case is the same failure short of
    the limit, 95/5 on both populations, and it goes through the formula.
    """
    n = 200
    d2c = _series([1.0] * n)                          # everything one way
    d2d = _series([1.0] * n)
    res = health.d2d_recycling_kappa(d2c, d2d, horizon_days=1, n_bootstrap=0)
    assert res.hit_rate == pytest.approx(1.0)          # the naive statistic
    assert res.kappa == pytest.approx(0.0)             # the honest one
    assert res.degenerate is True
    assert res.status == health.ALARM

    rng = np.random.default_rng(29)
    m = 4000
    x = np.where(rng.random(m) < 0.95, 1.0, -1.0)
    y = np.where(rng.random(m) < 0.95, 1.0, -1.0)      # independent of x
    near = health.d2d_recycling_kappa(_series(x), _series(np.r_[0.0, y[:-1]]),
                                      horizon_days=1, n_bootstrap=0)
    assert near.hit_rate > 0.85                        # chance alone
    assert abs(near.kappa) < 0.10                      # and no skill in it
    assert near.degenerate is False


def test_a_one_sided_classifier_alarms_even_with_no_placebo():
    """One degenerate marginal is the F-20 state, and it does NOT make chance 1.

    `chance = px*py + (1-px)(1-py)`, so `px=1` against a balanced `py=0.5`
    gives 0.5 -- a flag conditioned on `chance == 1` only ever fires when both
    series are one-sided the same way. Kappa is exactly 0 either way, but 0.0
    alone only clears the 0.10 warn floor: on a series short enough that the
    placebo cannot be built there is no alarm level left, so a classifier that
    called every single day the same way reported WARN.
    """
    rng = np.random.default_rng(5)
    n = 40
    x = np.ones(n)                                     # every day the same call
    y = np.where(rng.random(n) < 0.5, 1.0, -1.0)
    res = health.d2d_recycling_kappa(_series(x), _series(np.r_[0.0, y[:-1]]),
                                     horizon_days=1, n_bootstrap=0,
                                     placebo_shift_days=20, min_pairs=10)
    assert res.placebo_kappa_p95 is None               # no alarm level exists
    assert res.chance_rate < 1.0                       # ...and chance is not 1
    assert res.kappa == pytest.approx(0.0)
    assert res.degenerate is True
    assert res.status == health.ALARM


def test_a_horizon_longer_than_the_history_is_no_data_not_a_crash():
    """A monitor loop that starts on two days of history must report NO_DATA."""
    res = health.d2d_recycling_kappa(_series([1.0, -1.0]), _series([1.0, -1.0]),
                                     horizon_days=10, n_bootstrap=0)
    assert res.status == health.NO_DATA


def test_a_78_22_split_on_both_sides_is_not_skill():
    """The softer version of the same failure: matched but independent marginals."""
    rng = np.random.default_rng(7)
    n = 4000
    x = np.where(rng.random(n) < 0.78, 1.0, -1.0)
    y = np.where(rng.random(n) < 0.78, 1.0, -1.0)      # independent of x
    res = health.d2d_recycling_kappa(_series(x), _series(np.r_[0.0, y[:-1]]),
                                     horizon_days=1, n_bootstrap=0)
    assert res.hit_rate > 0.60                         # chance alone clears 0.66
    assert abs(res.kappa) < 0.05


def test_the_placebo_shift_preserves_the_marginals_and_kills_the_link():
    """Same control shape as F-15's 7-day placebo, for the same reason."""
    rng = np.random.default_rng(11)
    signs = np.where(rng.random(300) < 0.5, 1.0, -1.0)
    d2c = _series(signs)
    d2d = _series(np.r_[0.0, signs[:-1]])
    res = health.d2d_recycling_kappa(d2c, d2d, horizon_days=1, n_bootstrap=0)
    assert res.kappa == pytest.approx(1.0)
    assert res.placebo_kappa_p95 is not None
    assert res.placebo_kappa_p95 < 0.5
    assert res.status == health.OK


def test_degradation_towards_the_placebo_band_is_an_alarm():
    rng = np.random.default_rng(13)
    n = 400
    x = np.where(rng.random(n) < 0.5, 1.0, -1.0)
    y = np.where(rng.random(n) < 0.5, 1.0, -1.0)       # no link at all
    res = health.d2d_recycling_kappa(_series(x), _series(np.r_[0.0, y[:-1]]),
                                     horizon_days=1, n_bootstrap=0)
    assert res.status == health.ALARM
    assert "flatten" in health.d2d_recycling_kappa.__doc__.lower()


def test_the_rolling_monitor_sees_a_classifier_that_stops_working():
    """A single number over the whole sample cannot say "worse than it was".

    Here the recycling link is perfect for 250 days and then stops. The early
    windows must score high, the late ones must alarm -- and they must alarm
    against a reference this system established itself, because no absolute
    kappa level can be set in advance for a cross-venue economic prediction.
    """
    rng = np.random.default_rng(19)
    good = np.where(rng.random(250) < 0.5, 1.0, -1.0)
    dead = np.where(rng.random(150) < 0.5, 1.0, -1.0)
    d2c = _series(np.r_[good, dead])
    d2d = _series(np.r_[[0.0], good[:-1], dead])       # the link stops at day 250

    out = health.rolling_recycling_kappa(d2c, d2d, window_days=90, step_days=10)
    assert len(out) > 20
    assert out["kappa"].iloc[0] == pytest.approx(1.0)
    assert out["status"].iloc[0] == health.OK
    assert out["kappa"].iloc[-1] < 0.3
    assert out["status"].iloc[-1] == health.ALARM
    # the benchmark never contains the window it judges
    assert pd.isna(out["reference_kappa"].iloc[0])


def test_a_halving_against_its_own_reference_alarms_before_the_link_is_gone():
    """Degradation is the alarm, not only extinction.

    Here the link survives -- the late windows are still comfortably clear of
    their own placebo band -- but they are worth half what this system measured
    for itself earlier. No absolute kappa level could catch that, which is why
    the reference is a trailing median of the windows before it.
    """
    rng = np.random.default_rng(23)
    n1, n2, acc = 250, 150, 0.70
    x = np.where(rng.random(n1 + n2) < 0.5, 1.0, -1.0)
    keep = np.ones(n1 + n2 - 1, dtype=bool)
    keep[n1:] = rng.random(n1 + n2 - 1 - n1) < acc
    y = np.r_[0.0, np.where(keep, x[:-1], -x[:-1])]

    out = health.rolling_recycling_kappa(_series(x), _series(y),
                                         window_days=90, step_days=10)
    last = out.iloc[-1]
    assert last["kappa"] > last["placebo_kappa_p95"], "the link is still there"
    assert last["kappa"] < 0.5 * last["reference_kappa"], "and it halved"
    assert last["status"] == health.ALARM


def test_the_rolling_monitor_reports_no_data_rather_than_a_missing_column():
    """A history shorter than one window closes no window at all.

    Both empty paths have to return the documented frame: the no-data one did,
    and this one returned a single `reference_kappa` column, so a monitor loop
    starting on a short history died on `out["kappa"]` instead of reading an
    empty series.
    """
    rng = np.random.default_rng(3)
    signs = np.where(rng.random(30) < 0.5, 1.0, -1.0)
    out = health.rolling_recycling_kappa(_series(signs),
                                         _series(np.r_[0.0, signs[:-1]]),
                                         window_days=90)
    assert len(out) == 0
    assert list(out.columns) == health.ROLLING_KAPPA_COLUMNS
    assert list(out["kappa"]) == []


def test_the_bootstrap_keeps_blocks_because_flow_is_autocorrelated():
    rng = np.random.default_rng(17)
    signs = np.where(rng.random(300) < 0.5, 1.0, -1.0)
    res = health.d2d_recycling_kappa(_series(signs),
                                     _series(np.r_[0.0, signs[:-1]]),
                                     horizon_days=1, n_bootstrap=100,
                                     block_length=5, seed=3)
    lo, hi = res.bootstrap_ci
    assert lo <= res.kappa <= hi
    assert res.block_length == 5


# ==========================================================================
# 7. health.py -- the coverage fractions, each with a threshold
# ==========================================================================

def test_every_metric_carries_a_rationale_and_an_action():
    """A number with no stated reason cannot be argued with when it fires."""
    calls = [_call(f"U{i}", 0.9) for i in range(10)]
    m = health.dead_zone_fraction(calls)
    assert isinstance(m.threshold, health.Threshold)
    assert len(m.threshold.rationale) > 40
    assert m.threshold.action


def test_the_dead_zone_alarm_is_two_sided():
    """A *fall* in near-mid density is the mid drifting off venue.

    F-20 measured it directly: 40.5% of on-market SOFR outrights land within
    +-0.1 bp of the citi mid against 5.43% on the barchart mid. So a shrinking
    dead zone is the failure signature, and a one-sided threshold misses it.
    """
    few = [_call(f"U{i}", 0.9, dead_zone=(i < 1)) for i in range(100)]
    m = health.dead_zone_fraction(few, reference=0.40)
    assert m.value == pytest.approx(0.01)
    assert m.status == health.ALARM

    many = [_call(f"U{i}", 0.9, dead_zone=True) for i in range(100)]
    assert health.dead_zone_fraction(many).status == health.ALARM

    # ...and with a reference supplied, the absolute limit is still enforced on
    # top of the band: 0.70 sits inside the 2x warn band around a 0.40
    # reference, and past 60% the ladder is mostly zeros however good the mid is
    mostly = [_call(f"U{i}", 0.9, dead_zone=(i < 70)) for i in range(100)]
    m = health.dead_zone_fraction(mostly, reference=0.40)
    assert m.value == pytest.approx(0.70)
    assert m.threshold.evaluate(m.value) == health.OK  # the band alone clears it
    assert m.status == health.ALARM                    # the absolute limit does not


def test_imputed_notional_fraction_is_weighted_as_well_as_counted():
    """F-7: 3.0% of legs are capped but 15.4% of the DV01 is imputed.

    Two separate escalations, so the weighted one has to be reachable when the
    count is clean -- which is the case that matters, since the whole point of
    F-7 is that the two numbers are five times apart.
    """
    prov = pd.DataFrame({
        "unit_key": ["A", "B", "C", "D"],
        "notional_imputed": [True, False, False, False],
    })
    m = health.imputed_notional_fraction(prov, weights=pd.Series(
        [700.0, 100.0, 100.0, 100.0], index=["A", "B", "C", "D"]))
    assert m.value == pytest.approx(0.25)
    assert m.detail["dv01_share"] == pytest.approx(0.70)
    assert m.status == health.ALARM                    # the count alone, here

    # 1 unit in 20 imputed -- below the 6% count warn -- carrying 35% of the
    # DV01, which is above the 30% alarm. Only the weighted branch can fire.
    keys = [f"U{i}" for i in range(20)]
    lopsided = pd.DataFrame({"unit_key": keys,
                             "notional_imputed": [True] + [False] * 19})
    w = pd.Series([700.0] + [1300.0 / 19] * 19, index=keys)
    m = health.imputed_notional_fraction(lopsided, weights=w)
    assert m.value == pytest.approx(0.05)
    assert m.threshold.evaluate(m.value) == health.OK  # the count is clean
    assert m.detail["dv01_share"] == pytest.approx(0.35)
    assert m.status == health.ALARM                    # the DV01 is not


def test_a_renamed_imputed_flag_column_is_loud_not_no_data():
    """`prov.get(col, default)` is the convenient spelling and the wrong one.

    Renamed, the unweighted path reported a clean 0.00 forever and the weighted
    path raised `IndexError: Boolean index has wrong length: 0 instead of 4`.
    """
    prov = pd.DataFrame({"unit_key": list("ABCD"),
                         "notional_imputed_flag": [True, False, False, False]})
    with pytest.raises(ValueError, match="notional_imputed"):
        health.imputed_notional_fraction(prov)
    with pytest.raises(ValueError, match="notional_imputed"):
        health.imputed_notional_fraction(
            prov, weights=pd.Series([700.0, 100.0, 100.0, 100.0],
                                    index=list("ABCD")))
    # an empty frame is still NO_DATA, not an error -- there is no column to
    # be wrong about
    assert health.imputed_notional_fraction(pd.DataFrame()).status == health.NO_DATA


def test_the_overnight_hole_is_read_off_the_policy_that_fired():
    """The served snapshot is in-session by construction -- it is the last one
    before the feed stopped. So the branch, not the served stamp, is the
    evidence.
    """
    in_sess = "method=asof max_lag=60s allow_future=False on_miss=raise"
    hole = "method=asof max_lag=7200s allow_future=False on_miss=raise"
    prov = pd.DataFrame({
        "unit_key": list("ABCD"),
        "snapshot_policy": [in_sess, in_sess, in_sess, hole],
        "snapshot_lag_seconds": [0.0, 30.0, 0.0, 4200.0],
    })
    m = health.overnight_hole_fraction(prov)
    assert m.value == pytest.approx(0.25)
    assert m.status == health.ALARM
    assert health.is_overnight_hole(hole) and not health.is_overnight_hole(in_sess)

    # ...and the hole population's own staleness is measured against the 2h
    # bound, which is the bound and not the expectation
    lag = {x.name: x for x in health.snapshot_lag_metrics(prov)}
    assert lag["overnight_hole_lag_p90_seconds"].value == pytest.approx(4200.0)
    assert lag["overnight_hole_lag_p90_seconds"].status == health.WARN


def test_a_unit_that_never_priced_is_not_an_overnight_hole():
    """The natural call is on the WHOLE provenance frame, failures included.

    `provenance.build` writes `snapshot_policy=""` for a unit that never
    reached a curve, and "not the strict in-session branch" is true of an empty
    string. Left alone, the metric re-labels the entire pricing-failure
    population as a curve-staleness problem and alarms on a day whose curves
    were fine -- the same silent conflation as a missing column, in value form.
    """
    in_sess = "method=asof max_lag=60s allow_future=False on_miss=raise"
    prov = pd.DataFrame({
        "unit_key": ["A", "B", "C", "D"],
        "snapshot_policy": [in_sess, "", "", in_sess],
        "failure_reason": [None, T.EXCL_NO_CURVE, T.EXCL_PRICING_ERROR,
                           T.EXCL_UNORIENTABLE],
        "snapshot_lag_seconds": [5.0, None, None, 7.0],
    })
    m = health.overnight_hole_fraction(prov)
    assert m.value == pytest.approx(0.0)
    assert m.n == 2                                    # denominator is the served
    assert m.detail["n_unserved"] == 2
    assert m.status == health.OK

    # D priced fine and was excluded for having no quote convention -- it IS a
    # real observation of how the curve behaved, so it stays in the denominator.
    # The criterion is "was a curve served", not "did the unit reach the ladder".
    assert list(health.served_mask(prov)) == [True, False, False, True]

    # ...and the predicate refuses to answer for a row that was never served,
    # rather than guessing the conservative-looking answer
    with pytest.raises(ValueError, match="never served"):
        health.is_overnight_hole("")

    dist = health.snapshot_lag_distribution(prov).set_index("population")
    assert dist.loc["UNSERVED", "n"] == 2              # visible, not omitted
    assert dist.loc["IN_SESSION", "n"] == 2


def test_a_bounded_future_allowing_policy_is_not_the_strict_in_session_branch():
    """A 60s window CENTRED on the print is not the 60s window BEFORE it.

    A `max_lag`-only reading passed `allow_future=True` as long as it carried a
    bound, so the guard could not fire for the property behind the 1.09% of
    legs the shipped default serves from the future -- a curve that contains
    the print the direction call is reading.

    `method` is deliberately not in the test: `select_snapshot` rejects a
    future pick outright under `allow_future=False` rather than falling back,
    so a row actually served under `nearest` came from a backward stamp inside
    the bound and IS the strict outcome.
    """
    assert health.is_overnight_hole(
        "method=asof max_lag=60s allow_future=True on_miss=raise") is True
    assert health.is_overnight_hole(
        "method=nearest max_lag=unbounded allow_future=True on_miss=none") is True
    assert health.is_overnight_hole(
        "method=asof max_lag=60s allow_future=False on_miss=raise") is False
    assert health.is_overnight_hole(
        "method=nearest max_lag=60s allow_future=False on_miss=raise") is False


def test_an_in_session_row_staler_than_its_own_policy_is_a_halt():
    """A row that is in-session by policy and staler than the 60s bound means
    the snapshot did not come from the branch the provenance says it did: 60s
    admits 0.21bp of 5Y drift at p90, 30 minutes admits 1.07bp."""
    in_sess = "method=asof max_lag=60s allow_future=False on_miss=raise"
    prov = pd.DataFrame({"unit_key": ["A", "B"],
                         "snapshot_policy": [in_sess] * 2,
                         "snapshot_lag_seconds": [10.0, 900.0]})
    metrics = {m.name: m for m in health.snapshot_lag_metrics(prov)}
    assert metrics["in_session_lag_over_policy"].value == 1
    assert metrics["in_session_lag_over_policy"].status == health.ALARM


def test_a_curve_from_the_future_is_an_immediate_alarm():
    """A curve served after the print contains the print. That is circular."""
    prov = pd.DataFrame({
        "unit_key": ["A", "B"],
        "snapshot_policy": ["method=asof max_lag=60s allow_future=False on_miss=raise"] * 2,
        "snapshot_lag_seconds": [10.0, -30.0],
    })
    metrics = {m.name: m for m in health.snapshot_lag_metrics(prov)}
    assert metrics["curve_snapshot_from_future"].value == 1
    assert metrics["curve_snapshot_from_future"].status == health.ALARM


def test_report_lag_is_never_pooled_across_the_block_flag():
    """Blocks arrive delayed; by then the dealer has partially hedged.

    A block print and an ASAP print of the same size are not the same event,
    so the function has no pooled row to read by accident.
    """
    df = pd.DataFrame({
        "is_block": [False] * 8 + [True] * 5,
        "report_lag_seconds": [0.0] * 8 + [0.0, 0.0, 0.0, 900.0, 1_352_256.0],
    })
    out = health.report_lag_by_block(df).set_index("is_block")
    assert set(out.index) == {False, True}
    assert len(out) == 2                               # no third, pooled row

    # ...and the two rows are two POPULATIONS, not one population twice: a
    # shape check alone passes a function that reads every row into both.
    assert (out.loc[False, "n"], out.loc[True, "n"]) == (8, 5)
    assert out.loc[False, "max"] == pytest.approx(0.0)
    assert out.loc[True, "max"] == pytest.approx(1_352_256.0)
    assert out.loc[True, "p50"] == pytest.approx(0.0)   # F-3: p50 = p90 = 0 for both
    assert out.loc[True, "status"] == health.ALARM      # ...and p90 here is not


def test_pricing_success_is_stratified_because_an_aggregate_hides_a_collapse():
    """T-4's single UNKNOWN was a past-start fixings error: 1 of 484 rows.

    Invisible at 99.8% overall; 0% of its stratum if the stratum is small.
    """
    as_of = datetime.date(2026, 6, 10)
    legs = pd.DataFrame({
        "as_of_date": [as_of] * 10,
        "effective_date": ([as_of] * 5 + [as_of + datetime.timedelta(days=400)] * 3
                           + [as_of - datetime.timedelta(days=400)] * 2),
        "is_capped": [False] * 10,
        "rate_index": ["SOFR"] * 10,
        "priced": [True] * 8 + [False] * 2,            # both past-start legs failed
    })
    out = health.pricing_success_by_stratum(legs).set_index("stratum")
    assert out.loc["SPOT", "success_rate"] == pytest.approx(1.0)
    assert out.loc["FORWARD_START", "success_rate"] == pytest.approx(1.0)
    assert out.loc["PAST_START", "success_rate"] == pytest.approx(0.0)
    assert out.loc["PAST_START", "status"] == health.ALARM
    assert out.loc["SPOT", "status"] == health.OK


def test_a_priced_basis_leg_is_the_alarm_not_the_success():
    """BASIS is EXCL_UNSUPPORTED_INDEX by construction, so pricing one means
    the exclusion leaked."""
    as_of = datetime.date(2026, 6, 10)
    legs = pd.DataFrame({
        "as_of_date": [as_of] * 2,
        "effective_date": [as_of] * 2,
        "is_capped": [False] * 2,
        "rate_index": ["BASIS", "BASIS"],
        "priced": [True, False],
    })
    out = health.pricing_success_by_stratum(legs).set_index("stratum")
    assert out.loc["BASIS", "status"] == health.ALARM


def test_a_renamed_index_column_cannot_silently_disable_the_basis_alarm():
    """The BASIS row is an INVERTED alarm, so its silence looks like health.

    `legs.get(col, default)` made the stratum empty, empty reports NO_DATA, and
    a renamed column therefore disabled the one alarm here that fires on
    success -- permanently, on a frame in which nothing looks wrong. CAPPED
    goes the same way for the same spelling.
    """
    as_of = datetime.date(2026, 6, 10)
    legs = pd.DataFrame({
        "as_of_date": [as_of] * 2, "effective_date": [as_of] * 2,
        "is_capped_flag": [False] * 2,             # was is_capped
        "index_name": ["BASIS", "BASIS"],          # was rate_index
        "priced": [True, True],
    })
    with pytest.raises(ValueError, match="is_capped"):
        health.pricing_success_by_stratum(legs)

    with pytest.raises(ValueError, match="rate_index_clean"):
        health.pricing_success_by_stratum(legs.rename(
            columns={"is_capped_flag": "is_capped"}))


def test_the_health_report_puts_the_alarm_first():
    """A single ALARM must not be lost in a long OK list, which is the failure
    mode of every monitoring table that sorts by name."""
    thr = health.Threshold(name="t", direction="above", warn=1, alarm=2,
                           rationale="x" * 50, action="y")
    metrics = [health.Metric("a", 0, 1, thr, health.OK),
               health.Metric("b", 0, 1, thr, health.OK),
               health.Metric("c", 9, 1, thr, health.ALARM),
               health.Metric("d", 0, 1, thr, health.WARN)]
    out = health.health_report(metrics)
    assert list(out["status"]) == [health.ALARM, health.WARN,
                                   health.OK, health.OK]
    assert out["metric"].iloc[0] == "c"


def test_the_health_report_names_flattening_as_the_response():
    doc = (health.__doc__ or "").lower()
    assert "flatten" in doc


def test_the_overnight_rationale_cites_the_measured_truncated_day_count():
    """The thresholds carry their derivation into the report, so the numbers in
    them are read by whoever the alarm wakes up. 161 truncated-end SOFR days
    and 141 Fed Funds days are what the minute-curve fidelity audit measured;
    128 is not a number that appears in any of it.
    """
    r = health._overnight_threshold().rationale
    assert "161" in r and "128" not in r


# ==========================================================================
# 8. provenance.py -- the audit trail and the extended vintage
# ==========================================================================

def test_the_vintage_sees_the_rateslib_upgrade_the_old_one_missed():
    """T-7: the 2.1.1 -> 2.7.1 upgrade repaired a row that had been UNKNOWN,
    and `stir_flow/vintage.py` cannot see it -- rateslib is not in its
    `VINTAGE_SOURCES`. Neither is the tape generation.
    """
    comp = provenance.vintage_components()
    assert comp["rateslib"]
    assert comp["tape_generation"]
    assert comp["curve_source"]
    assert comp["stir_flow"]

    base = provenance.code_vintage()
    assert base != provenance.code_vintage(curve_source="BARCHART_STIRF-RL")
    assert len(base) == 12


def test_the_vintage_changes_when_rateslib_or_the_tape_generation_changes(monkeypatch):
    base = provenance.code_vintage.__wrapped__(provenance._default_curve_source())
    monkeypatch.setattr(provenance, "_rateslib_version", lambda: "2.1.1")
    bumped = provenance.code_vintage.__wrapped__(provenance._default_curve_source())
    assert bumped != base

    monkeypatch.setattr(provenance, "_rateslib_version", lambda: "9.9.9")
    assert provenance.code_vintage.__wrapped__(provenance._default_curve_source()) != bumped


def test_the_vintage_module_says_a_matching_stamp_is_not_a_guarantee():
    src = provenance.__doc__ or ""
    assert "same vintage" in src.lower()


def test_a_provenance_row_carries_everything_needed_to_debug_a_wrong_ladder():
    unit = _unit("U")
    pricing = T.UnitPricing(
        unit_key="U", curve_name="USD-SOFR-1D",
        curve_timestamp=_ny(2026, 6, 10, 9, 59),
        snapshot_lag_seconds=41.0,
        snapshot_policy="method=asof max_lag=60s allow_future=False on_miss=raise",
        leg_mid_pct=[3.94], leg_pv01=[4500.0], structure_dv01=4500.0,
    )
    p = provenance.build(unit, pricing, _call("U", 0.9),
                         pricing_clock_field="execution_timestamp",
                         notional_imputed=True, notional_impute_factor=2.1)
    assert isinstance(p, T.Provenance)
    assert (p.curve_name, p.snapshot_lag_seconds, p.rule) == (
        "USD-SOFR-1D", 41.0, conv.RULE_RATE)
    assert p.pricing_clock_field == "execution_timestamp"
    assert p.notional_imputed and p.notional_impute_factor == 2.1
    assert p.tau_bucket == "SOFR_5Y"
    assert p.code_vintage == provenance.code_vintage()
    assert p.failure_reason is None

    frame = provenance.to_frame([p])
    assert len(frame) == 1
    assert set(frame.columns) >= {"unit_key", "curve_name", "code_vintage",
                                  "failure_reason", "pricing_clock_field"}


def test_a_failed_unit_gets_a_provenance_row_too():
    unit = _unit("U")
    p = provenance.build(unit, None, _call("U", None, exclusion=T.EXCL_NO_CURVE),
                         pricing_clock_field="event_timestamp")
    assert p.failure_reason == T.EXCL_NO_CURVE
    assert p.curve_name in ("", None) or isinstance(p.curve_name, str)


class _RenamedPricing:
    """A `UnitPricing` after an interface rename. Everything priced fine."""

    unit_key = "U"
    curve_name = "USD-SOFR-1D"
    curve_timestamp = pd.Timestamp("2026-06-10T13:59:00Z")
    lag_seconds = 41.0                       # was snapshot_lag_seconds
    policy = "method=asof max_lag=60s allow_future=False on_miss=raise"


def test_a_renamed_pricing_field_raises_instead_of_reporting_never_priced():
    """The never-priced sentinels exist for `pricing is None` and nothing else.

    Written by a `getattr` default they turn an interface rename into a
    monitoring blackout that reports clean: every row of a *successful* run
    gets `snapshot_policy=""`, `health.served_mask` reads that field and says
    UNSERVED for all of them, `overnight_hole_fraction` goes NO_DATA, and the
    day looks like one with no curve problems. Nothing raises. This is the
    `_require` doctrine attacked from the value side.
    """
    with pytest.raises(ValueError, match="snapshot_policy"):
        provenance.build(_unit("U"), _RenamedPricing(), _call("U", 0.9),
                         pricing_clock_field="execution_timestamp")


def test_a_priced_unit_with_no_recorded_policy_is_loud():
    """`""` is this function's own never-priced marker, so a producer writing
    it on a priced unit hides a served row inside the failure population."""
    priced = T.UnitPricing(
        unit_key="U", curve_name="USD-SOFR-1D",
        curve_timestamp=_ny(2026, 6, 10, 9, 59),
        snapshot_lag_seconds=41.0, snapshot_policy="",
        leg_mid_pct=[3.94], leg_pv01=[4500.0], structure_dv01=4500.0,
    )
    with pytest.raises(ValueError, match="no snapshot policy"):
        provenance.build(_unit("U"), priced, _call("U", 0.9),
                         pricing_clock_field="execution_timestamp")


# ==========================================================================
# 9. provenance.py -- the coverage accounting, and it must sum
# ==========================================================================

def test_every_unit_is_in_the_ladder_or_carries_exactly_one_reason():
    rows = [
        {"unit_key": "A", "failure_reason": None},
        {"unit_key": "B", "failure_reason": T.EXCL_UNORIENTABLE},
        {"unit_key": "C", "failure_reason": T.EXCL_NO_CURVE},
    ]
    prov = pd.DataFrame(rows)
    dv01 = pd.Series({"A": 6000.0, "B": 3000.0, "C": 1000.0})
    table = provenance.coverage_table(prov, dv01=dv01,
                                      ladder_excluded=_no_ladder_exclusions())

    assert table["dv01_share"].sum() == pytest.approx(1.0)
    assert table["n_units"].sum() == 3
    by = table.set_index("reason")["dv01_share"]
    assert by[provenance.IN_LADDER] == pytest.approx(0.6)
    assert by[T.EXCL_UNORIENTABLE] == pytest.approx(0.3)
    assert by[T.EXCL_NO_CURVE] == pytest.approx(0.1)


def test_a_unit_counted_twice_breaks_the_accounting_loudly():
    prov = pd.DataFrame([
        {"unit_key": "A", "failure_reason": None},
        {"unit_key": "A", "failure_reason": T.EXCL_NO_CURVE},
    ])
    with pytest.raises(ValueError, match="more than one"):
        provenance.coverage_table(prov, dv01=pd.Series({"A": 1.0}),
                                  ladder_excluded=_no_ladder_exclusions())


def test_a_unit_with_no_size_cannot_be_counted_as_a_zero_share():
    """The self-flattering failure: an excluded unit has no repriced DV01 by
    definition, so dropping it leaves the shares summing to 1 over exactly the
    population that did not fail.
    """
    prov = pd.DataFrame([
        {"unit_key": "A", "failure_reason": None},
        {"unit_key": "B", "failure_reason": T.EXCL_PRICING_ERROR},
    ])
    with pytest.raises(ValueError, match="no DV01"):
        provenance.coverage_table(prov, dv01=pd.Series({"A": 1000.0}),
                                  ladder_excluded=_no_ladder_exclusions())

    # ...and the fallback is a size that exists for a unit that never priced
    table = provenance.coverage_table(
        prov, dv01=pd.Series({"A": 1000.0}),
        dv01_fallback=pd.Series({"A": 900.0, "B": 1000.0}),
        ladder_excluded=_no_ladder_exclusions(),
    )
    assert table["dv01_share"].sum() == pytest.approx(1.0)
    src = table.set_index("reason")["n_fallback_dv01"]
    assert src[T.EXCL_PRICING_ERROR] == 1
    assert src[provenance.IN_LADDER] == 0


def test_the_annuity_proxy_is_the_fallback_size_and_not_a_tenor_times_1e4():
    """F-16: `tenor * 1e-4` is not the DV01 scale when 37% of legs are
    forward-starting -- the naive bound mis-flags 58% of deep forward starts.
    A forward-start 5y5y must not be sized as a 10y.
    """
    spot10 = provenance.annuity_dv01_proxy(notional=100e6, start_years=0.0,
                                           tenor_years=10.0)
    fwd5x5 = provenance.annuity_dv01_proxy(notional=100e6, start_years=5.0,
                                           tenor_years=5.0)
    spot5 = provenance.annuity_dv01_proxy(notional=100e6, start_years=0.0,
                                          tenor_years=5.0)
    assert fwd5x5 < spot5 < spot10
    assert fwd5x5 == pytest.approx(spot10 - spot5)
    naive10 = 100e6 * 10.0 * 1e-4
    assert fwd5x5 < 0.7 * naive10


def test_a_unit_the_ladder_threw_out_is_not_reported_in_ladder():
    """The written note is built from this table, so the two halves have to be
    the same population -- and `build` alone cannot make them one.

    `build` sees `call.exclusion`. `EXCL_PRICING_ERROR` and `EXCL_DEAD_ZONE`
    are minted *inside* `unit_ladder_rows`, after the record exists, and live
    only in its second return value. A null reason is read here as IN_LADDER,
    so without the join a unit the ladder threw out is reported in the ladder
    at 100% coverage: absence of a reason taken as success. Which is why
    `ladder_excluded` has no default.
    """
    units = [_unit("A"), _unit("B"), _unit("C")]
    calls = [_call("A", 0.9), _call("B", 0.9),
             _call("C", None, exclusion=T.EXCL_UNORIENTABLE)]
    rows, excluded = ladder.unit_ladder_rows(units, calls, _krd("A"))  # B: no risk
    assert set(zip(excluded["unit_key"], excluded["failure_reason"])) == {
        ("B", T.EXCL_PRICING_ERROR), ("C", T.EXCL_UNORIENTABLE)}

    # the population as `build` writes it: only C's reason is visible at all
    prov = provenance.to_frame([
        provenance.build(u, None, c, pricing_clock_field="event_timestamp")
        for u, c in zip(units, calls)])
    assert list(prov["failure_reason"]) == [None, None, T.EXCL_UNORIENTABLE]

    table = provenance.coverage_table(
        prov, dv01=pd.Series({"A": 100.0, "B": 100.0, "C": 100.0}),
        ladder_excluded=excluded).set_index("reason")
    assert table["dv01_share"].sum() == pytest.approx(1.0)
    assert table.loc[provenance.IN_LADDER, "dv01_share"] == pytest.approx(1 / 3)
    assert table.loc[T.EXCL_PRICING_ERROR, "dv01_share"] == pytest.approx(1 / 3)
    assert table.loc[T.EXCL_UNORIENTABLE, "dv01_share"] == pytest.approx(1 / 3)


def test_coverage_cannot_be_computed_without_the_ladder_exclusions():
    """No default, because the defect is a caller who never made the join."""
    prov = pd.DataFrame([{"unit_key": "A", "failure_reason": None}])
    with pytest.raises(TypeError):
        provenance.coverage_table(prov, dv01=pd.Series({"A": 1.0}))


def test_the_two_halves_of_the_join_are_reconciled_not_overwritten():
    """Re-applying the same reason is a no-op, so the join is idempotent; a
    second, different reason means the two stages saw different data, and a
    ladder exclusion for a unit outside the population means they are different
    populations. Neither is silently resolved."""
    prov = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_NO_CURVE}])
    dv01 = pd.Series({"A": 1.0})

    same = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_NO_CURVE}])
    out = provenance.coverage_table(prov, dv01=dv01, ladder_excluded=same)
    assert list(out["reason"]) == [T.EXCL_NO_CURVE]

    other = pd.DataFrame([{"unit_key": "A", "failure_reason": T.EXCL_DEAD_ZONE}])
    with pytest.raises(ValueError, match="disagree"):
        provenance.coverage_table(prov, dv01=dv01, ladder_excluded=other)

    stray = pd.DataFrame([{"unit_key": "GHOST",
                           "failure_reason": T.EXCL_DEAD_ZONE}])
    with pytest.raises(ValueError, match="not in the coverage population"):
        provenance.coverage_table(prov, dv01=dv01, ladder_excluded=stray)
