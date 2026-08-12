"""The daily street-positioning indicator, pinned.

The measurement this file is built around is
``docs/dealer_direction/2026-08-11-package-exclusion-skew.md``: the retained
population is a biased sample whose retention factor runs 0.761 at 0-1Y down to
0.495 at 15-20Y, a 1.54x cross-bucket scaling distortion. Everything asserted
here follows from that one fact plus the pinned sign convention.

Six failures this file exists to make impossible, every one of them silent:

1. **A cross-bucket level comparison.** ``delta_dv01`` at 0-1Y against
   ``delta_dv01`` at 15-20Y compares 76% of one bucket's tape DV01 against 50%
   of the other's. A pivot is one line of pandas, so the *object* has to refuse
   it -- a docstring does not.
2. **A z-score that is not retention-invariant.** ``z`` cancels a *constant*
   retention factor exactly, which is what makes it the one cross-bucket-safe
   view. It does not cancel a *drifting* one, and 1-2Y drifts at +5.07 pp/yr
   (t = +3.21). Both halves are pinned here with a known answer.
3. **Silent cumulation.** The tape never prints the offsetting compression, so
   a running sum has a monotone unbounded error.
4. **Stamping on execution time.** Every row dated before it could be acted on.
5. **Pooling venue classes.** "Dealers are distributing risk" is its own signal
   and merging D2D into D2C destroys it.
6. **A published number that is plausible and wrong.** 1-5 are all statements
   about the *shape* of the output -- a key, a refusal, a column name -- and a
   suite that only asserts shape lets the arithmetic inside the columns be
   anything at all. Mutation testing measured it: **15 of 25 arithmetic
   mutations survived this file at 59 tests**, and the worst of them published
   ``z_raw`` and ``z_cov_adj`` **exactly inverted** while every existing z test
   passed, because every existing z test was *comparative* and a global sign
   flip cancels inside all of them. So the numbers are now pinned against
   answers computed away from the code: see section 5 for z, and
   ``INDICATOR.md`` section 7 for the battery and the two mutations that
   survive because they are provably equivalent.
"""
from __future__ import annotations

import datetime
import re

import numpy as np
import pandas as pd
import pytest
import pytz

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import indicator as ind
from SDRUtils.dealer_direction import krd, ladder
from SDRUtils.dealer_direction import types as T

NY = pytz.timezone("America/New_York")

D0 = datetime.date(2025, 1, 2)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _dates(n, start=D0):
    """``n`` weekday dates -- the indicator is a business-day series."""
    return list(pd.bdate_range(start, periods=n).date)


def _unit_rows(records) -> pd.DataFrame:
    """Rows in ``ladder.unit_ladder_rows``' own shape.

    Built directly rather than through the whole pipeline: the indicator is a
    transformation of that frame, and a fixture that needs a curve cannot pin a
    transformation. One test below does go through ``unit_ladder_rows`` to keep
    the two shapes joined.
    """
    rows = []
    for r in records:
        p = r.get("p", 0.75)
        w = conv.signed_weight(p)
        dv01 = r["dv01_if_received"]
        vis = r.get("visibility_timestamp")
        if vis is None:
            vis = pd.Timestamp(NY.localize(
                datetime.datetime.combine(r["date"], datetime.time(11, 0)))
            ).tz_convert("UTC")
        rows.append({
            "unit_key": r["unit_key"],
            "bucket_space": r.get("bucket_space", krd.BUCKET_SPACE),
            "bucket_key": r["bucket_key"],
            "dv01_if_received": dv01,
            "delta_dv01": r.get("delta_dv01", w * dv01),
            "p": p,
            "signed_weight": r.get("signed_weight", w),
            "dealer_sign": 1 if w > 0 else (-1 if w < 0 else 0),
            "rule": conv.RULE_RATE,
            "tau_bucket": "SOFR|D2C|OUTRIGHT|5-10Y",
            "in_dead_zone": r.get("in_dead_zone", False),
            "venue_class": r.get("venue_class", T.VENUE_D2C),
            "series": r.get("series", ladder.SERIES_FLOW),
            "visibility_date": r.get("visibility_date", ladder.visibility_date(vis)),
            "visibility_timestamp": vis,
            "visibility_source": r.get("visibility_source", "APPENDIX_C_ESTIMATE"),
            "execution_timestamp": r.get("execution_timestamp", vis),
            "event_timestamp": vis,
            "pricing_timestamp": vis,
            "as_of_date": r["date"],
            "rate_index": "SOFR",
            "kind": conv.OUTRIGHT,
            "n_legs": 1,
            "is_block": r.get("is_block", False),
            "is_capped": r.get("is_capped", False),
            "code_vintage": r.get("code_vintage", "abcdef012345"),
        })
    return pd.DataFrame(rows).reindex(columns=ladder.UNIT_ROW_COLUMNS)


def _series_rows(levels, *, bucket="5-7Y", venue=T.VENUE_D2C,
                 series=ladder.SERIES_FLOW, dates=None, pillar="6Y"):
    """One unit per day carrying a chosen signed level.

    ``p`` is solved so that ``(2p-1) * dv01 == level`` with a fixed gross
    ``dv01``, which keeps the weight honest -- the fixture never writes
    ``delta_dv01`` by hand.
    """
    dates = dates if dates is not None else _dates(len(levels))
    gross = 1_000_000.0
    out = []
    for i, (d, lv) in enumerate(zip(dates, levels)):
        w = float(lv) / gross
        w = max(-1.0, min(1.0, w))
        out.append({
            "unit_key": f"{bucket}-{venue}-{series}-{i}",
            "bucket_key": pillar, "dv01_if_received": gross,
            "p": (w + 1.0) / 2.0, "date": d, "venue_class": venue,
            "series": series,
        })
    return _unit_rows(out)


def _coverage(unit_rows, *, frac=0.57, bucket_map=None, per_date=None):
    """A coverage frame matching ``unit_rows``' own cells."""
    lv = ind.daily_levels(unit_rows)
    rows = []
    for _, r in lv.iterrows():
        f = frac
        if bucket_map is not None:
            f = bucket_map.get(r["bucket_key"], frac)
        if per_date is not None:
            f = per_date(r["bucket_key"], r["visibility_date"], f)
        gross = abs(float(r["abs_dv01"])) or 1.0
        rows.append({
            "bucket_key": r["bucket_key"],
            "visibility_date": r["visibility_date"],
            "venue_class": r["venue_class"],
            "series": r["series"],
            "dv01_kept": gross,
            "dv01_total": gross / f,
        })
    return pd.DataFrame(rows)


def _build(unit_rows, **kw):
    kw.setdefault("coverage", _coverage(unit_rows))
    kw.setdefault("z_min_obs", 5)
    kw.setdefault("z_window_obs", 250)
    return ind.build(unit_rows, **kw)


# --------------------------------------------------------------------------
# 1. the bucket vocabulary -- validated against the skew doc's own convention
# --------------------------------------------------------------------------

def test_tenor_buckets_are_the_skew_documents_ten():
    assert ind.TENOR_BUCKETS == (
        "0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y", "10-15Y", "15-20Y",
        "20-30Y", "30Y+")


@pytest.mark.parametrize("years,bucket", [
    (0.25, "0-1Y"), (1.0, "0-1Y"),          # right edge inclusive: a 1Y is 0-1Y
    (1.0000001, "1-2Y"), (2.0, "1-2Y"),
    (3.0, "2-3Y"), (5.0, "3-5Y"), (7.0, "5-7Y"),
    (10.0, "7-10Y"),                         # the doc: "a 10Y spot swap is 7-10Y"
    (11.0, "10-15Y"), (15.0, "10-15Y"), (20.0, "15-20Y"),
    (30.0, "20-30Y"), (30.5, "30Y+"), (50.0, "30Y+"),
])
def test_bucket_for_years_is_right_edge_inclusive(years, bucket):
    assert ind.bucket_for_years(years) == bucket


def test_every_krd_pillar_maps_into_the_vocabulary():
    mapped = {p: ind.PILLAR_BUCKET[p] for p in krd.PILLARS}
    assert set(mapped) == set(krd.PILLARS)
    assert set(mapped.values()) <= set(ind.TENOR_BUCKETS)
    # the four the doc pins by name
    assert mapped["1Y"] == "0-1Y"
    assert mapped["2Y"] == "1-2Y"
    assert mapped["10Y"] == "7-10Y"
    assert mapped["50Y"] == "30Y+"


def test_roll_up_preserves_each_unit_s_signed_total():
    rows = _unit_rows([
        {"unit_key": "U1", "bucket_key": "9Y", "dv01_if_received": 400.0, "date": D0},
        {"unit_key": "U1", "bucket_key": "10Y", "dv01_if_received": -150.0, "date": D0},
        {"unit_key": "U1", "bucket_key": "30Y", "dv01_if_received": 900.0, "date": D0},
    ])
    out = ind.roll_up_to_tenor_buckets(rows)
    assert out["bucket_space"].unique().tolist() == [ind.BUCKET_SPACE]
    assert set(out["bucket_key"]) == {"7-10Y", "20-30Y"}
    assert out["delta_dv01"].sum() == pytest.approx(rows["delta_dv01"].sum())
    assert out.loc[out.bucket_key == "7-10Y", "dv01_if_received"].iloc[0] == pytest.approx(250.0)


def test_a_units_pillars_cannot_disagree_about_the_print():
    """The roll-up takes metadata from the first pillar row, so the rest must agree.

    A unit is one print. If its pillar rows carry two venue classes, ``.first()``
    publishes it under whichever sorted first and the other vanishes -- a
    per-unit corruption with no output column that shows it.
    """
    rows = _unit_rows([
        {"unit_key": "U1", "bucket_key": "6Y", "dv01_if_received": 100.0, "date": D0},
        {"unit_key": "U1", "bucket_key": "10Y", "dv01_if_received": 100.0,
         "date": D0, "venue_class": T.VENUE_D2D},
    ])
    with pytest.raises(ValueError) as e:
        ind.daily_levels(rows)
    assert "venue_class" in str(e.value)


def test_the_roll_up_is_idempotent_on_its_own_output():
    """Its docstring promises this and nothing checked it.

    Rows already on the reporting grid must pass through, because the natural
    caller -- roll up, look, then hand the same frame to ``daily_levels``,
    which rolls up again -- would otherwise raise ``UnknownPillar`` on a bucket
    key that is perfectly valid.
    """
    rows = _unit_rows([
        {"unit_key": "U1", "bucket_key": "9Y", "dv01_if_received": 400.0, "date": D0},
        {"unit_key": "U1", "bucket_key": "10Y", "dv01_if_received": -150.0, "date": D0},
        {"unit_key": "U2", "bucket_key": "30Y", "dv01_if_received": 900.0, "date": D0},
    ])
    once = ind.roll_up_to_tenor_buckets(rows)
    twice = ind.roll_up_to_tenor_buckets(once)
    pd.testing.assert_frame_equal(once, twice)
    assert ind.daily_levels(once).equals(ind.daily_levels(rows))


def test_roll_up_refuses_an_unknown_pillar():
    rows = _unit_rows([{"unit_key": "U1", "bucket_key": "13Y",
                        "dv01_if_received": 1.0, "date": D0}])
    with pytest.raises(ind.UnknownPillar) as e:
        ind.roll_up_to_tenor_buckets(rows)
    assert "13Y" in str(e.value)


# --------------------------------------------------------------------------
# 2. the keys -- venue, series and the availability clock
# --------------------------------------------------------------------------

def test_venue_classes_are_never_merged():
    rows = pd.concat([
        _series_rows([100.0], venue=T.VENUE_D2C),
        _series_rows([-100.0], venue=T.VENUE_D2D),
        _series_rows([50.0], venue=T.VENUE_UNKNOWN),
    ], ignore_index=True)
    lv = ind.daily_levels(rows)
    assert len(lv) == 3
    assert set(lv["venue_class"]) == {T.VENUE_D2C, T.VENUE_D2D, T.VENUE_UNKNOWN}
    assert "venue_class" in ind.INDICATOR_KEYS


def test_flow_and_lifecycle_stay_apart():
    rows = pd.concat([
        _series_rows([100.0], series=ladder.SERIES_FLOW),
        _series_rows([100.0], series=ladder.SERIES_LIFECYCLE),
    ], ignore_index=True)
    lv = ind.daily_levels(rows)
    assert len(lv) == 2
    assert "series" in ind.INDICATOR_KEYS


def test_the_row_is_stamped_on_the_availability_clock():
    """A print at 20:30 ET publishes on the same NY date; the UTC date is the next."""
    exec_ts = pd.Timestamp(NY.localize(datetime.datetime(2025, 3, 4, 20, 30))).tz_convert("UTC")
    vis = exec_ts + pd.Timedelta(minutes=15)
    rows = _unit_rows([{"unit_key": "U1", "bucket_key": "5Y",
                        "dv01_if_received": 1000.0, "date": datetime.date(2025, 3, 4),
                        "visibility_timestamp": vis, "execution_timestamp": exec_ts}])
    lv = ind.daily_levels(rows)
    assert lv["visibility_date"].iloc[0] == datetime.date(2025, 3, 4)
    assert vis.date() == datetime.date(2025, 3, 5)      # the UTC date, rejected


def test_a_frame_stamped_on_execution_is_refused():
    """The whole point of the clock, so a mis-stamped frame must not aggregate."""
    exec_ts = pd.Timestamp(NY.localize(datetime.datetime(2025, 3, 4, 23, 40))).tz_convert("UTC")
    vis = exec_ts + pd.Timedelta(minutes=40)            # crosses into 2025-03-05 NY
    rows = _unit_rows([{"unit_key": "U1", "bucket_key": "5Y",
                        "dv01_if_received": 1000.0, "date": datetime.date(2025, 3, 4),
                        "visibility_timestamp": vis, "execution_timestamp": exec_ts,
                        "visibility_date": ladder.visibility_date(exec_ts)}])
    with pytest.raises(ind.MisStampedRow) as e:
        ind.daily_levels(rows)
    msg = str(e.value).lower()
    assert "visibility" in msg and "execution" in msg


# --------------------------------------------------------------------------
# 3. the weight is 2p-1
# --------------------------------------------------------------------------

def test_a_p_weighted_row_is_refused():
    rows = _series_rows([100.0])
    rows.loc[0, "delta_dv01"] = rows.loc[0, "p"] * rows.loc[0, "dv01_if_received"]
    with pytest.raises(ValueError) as e:
        ind.daily_levels(rows)
    assert "2p" in str(e.value)


def test_the_level_is_the_signed_weight_times_the_hypothesis_risk():
    rows = _series_rows([250.0, -400.0], dates=_dates(2))
    lv = ind.daily_levels(rows).sort_values("visibility_date")
    assert lv["delta_dv01"].tolist() == pytest.approx([250.0, -400.0])
    assert lv["abs_dv01"].tolist() == pytest.approx([1e6, 1e6])


def test_a_coin_flip_contributes_nothing():
    rows = _series_rows([0.0])
    lv = ind.daily_levels(rows)
    assert lv["p"].iloc[0] if "p" in lv.columns else True
    assert lv["delta_dv01"].iloc[0] == pytest.approx(0.0)
    assert lv["abs_dv01"].iloc[0] == pytest.approx(1e6)   # the pond is still there


# --------------------------------------------------------------------------
# 4. constraint 1 -- the cross-sectional comparison is structurally refused
# --------------------------------------------------------------------------

def _two_bucket_indicator(n=40, scale_b=1.0):
    rng = np.random.default_rng(11)
    dates = _dates(n)
    a = rng.normal(0, 1000, n)
    b = rng.normal(0, 1000, n) * scale_b
    rows = pd.concat([
        _series_rows(a, bucket="5-7Y", pillar="6Y", dates=dates),
        _series_rows(b, bucket="15-20Y", pillar="20Y", dates=dates),
    ], ignore_index=True)
    return _build(rows), rows


def test_the_bucket_accessor_names_the_level_for_its_bucket():
    obj, _ = _two_bucket_indicator()
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    assert ind.level_column("5-7Y") in f.columns
    assert "delta_dv01" not in f.columns
    assert set(f["bucket_key"]) == {"5-7Y"}


def test_concatenating_two_buckets_cannot_be_pivoted_into_a_comparison():
    """The columns are disjoint by construction, so a concat is a NaN diagonal."""
    obj, _ = _two_bucket_indicator()
    a = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    b = obj.bucket("15-20Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    both = pd.concat([a, b], ignore_index=True)
    ca, cb = ind.level_column("5-7Y"), ind.level_column("15-20Y")
    assert ca != cb
    assert both[ca].isna().sum() == len(b)
    assert both[cb].isna().sum() == len(a)


def test_cross_section_raises_and_the_message_carries_the_measurement():
    obj, _ = _two_bucket_indicator()
    with pytest.raises(ind.CrossSectionalLevelComparison) as e:
        obj.cross_section(_dates(40)[10])
    msg = str(e.value)
    assert "0.761" in msg and "0.495" in msg and "1.54" in msg
    assert "package-exclusion-skew" in msg


def test_pivot_levels_raises_the_same_way():
    obj, _ = _two_bucket_indicator()
    with pytest.raises(ind.CrossSectionalLevelComparison):
        obj.pivot_levels()


def test_there_is_no_whole_frame_accessor_carrying_the_level():
    obj, _ = _two_bucket_indicator()
    for name in ("to_frame", "levels", "levels_frame", "frame", "df"):
        assert not hasattr(obj, name), (
            f"{name!r} would hand back every bucket's level in one column")


def test_rescale_for_cross_section_makes_the_caller_supply_the_factors():
    obj, _ = _two_bucket_indicator()
    with pytest.raises(TypeError):
        obj.rescale_for_cross_section()
    out = obj.rescale_for_cross_section({"5-7Y": 0.524, "15-20Y": 0.495})
    assert "tape_scaled_dv01_ASSUMES_SAME_DIRECTIONAL_MIX" in out.columns
    a = out[out.bucket_key == "5-7Y"]
    src = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    assert (a["tape_scaled_dv01_ASSUMES_SAME_DIRECTIONAL_MIX"].to_numpy()
            == pytest.approx(src[ind.level_column("5-7Y")].to_numpy() / 0.524))


def test_rescale_refuses_a_bucket_with_no_factor():
    obj, _ = _two_bucket_indicator()
    with pytest.raises(ValueError) as e:
        obj.rescale_for_cross_section({"5-7Y": 0.524})
    assert "15-20Y" in str(e.value)


# --------------------------------------------------------------------------
# 5. the z-score -- a KNOWN NUMBER first, then its invariances
#
# Everything after 5a is comparative: z under a halved retention factor against
# z under the original, z on a short window against z on a long one, z alone
# against z beside another venue class. A global sign flip cancels inside every
# one of them -- "dealers were lifted in 5y" and "dealers were hit in 5y" are
# the same test to a comparative assertion. So the value and the sign are
# pinned first, against arithmetic done away from the code.
# --------------------------------------------------------------------------

#: Five days at 1,000 / 2,000 / 3,000 / 4,000 / 5,000 DV01. On the fifth day
#: the trailing window is the whole series:
#:
#:     mean = 3,000
#:     sd(ddof=1) = sqrt(10,000,000 / 4) = 1,581.1388300841897
#:     z = (5,000 - 3,000) / 1,581.1388300841897 = +1.2649110640673518
#:
#: and the three ways to get it wrong are all distinguishable from it:
#:     ddof=0 (a population sd)  -> +1.4142135623730951
#:     the sign inverted         -> -1.2649110640673518
#:     the mirror series' answer -> -1.2649110640673518
_HAND_Z_LEVELS = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
HAND_Z = 1.2649110640673518
HAND_Z_DDOF0 = 1.4142135623730951


def _hand_z_frame(levels):
    """One cell, five days, constant coverage, so both z columns are pinnable.

    ``coverage_smooth_obs=1`` is deliberate. With the production 63 the
    smoother is all-NaN over five days, ``delta_dv01_cov_adj`` is all-NaN and
    ``z_cov_adj`` cannot be asserted at all -- which is how a sign flip in the
    *second* z column hides. At 1, with a constant coverage,
    ``smooth == ref == 0.57`` exactly, the adjusted level is the raw level, and
    ``z_cov_adj`` must be the same known number as ``z_raw``.
    """
    rows = _series_rows(levels, dates=_dates(len(levels)))
    obj = ind.build(rows, coverage=_coverage(rows, frac=0.57), z_min_obs=5,
                    z_window_obs=250, coverage_smooth_obs=1)
    return obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)


def test_5a_the_published_z_is_a_known_number_with_a_known_sign():
    """The headline pin: the VALUE of z, not its behaviour under a transform.

    A rising 1,000 -> 5,000 series is a cell taking on progressively more
    received-fixed risk, and the last day sits above its own short history. The
    published z is +1.2649110640673518 and can be nothing else. Both z columns
    are asserted because both can be inverted independently.
    """
    f = _hand_z_frame(_HAND_Z_LEVELS)
    z = f["z_raw"].to_numpy()
    assert np.isnan(z[:4]).all(), "z must not exist before z_min_obs observations"
    assert z[4] == pytest.approx(HAND_Z, rel=1e-9)
    assert z[4] > 0, "the dealer is longer than its own history; z is positive"
    # the trailing sd is a SAMPLE sd: ddof=0 would publish 1.41421356
    assert abs(z[4] - HAND_Z_DDOF0) > 0.1
    assert f["z_cov_adj"].to_numpy()[4] == pytest.approx(HAND_Z, rel=1e-9)
    # z_n_obs says how much history is behind that number, and is published
    assert f["z_n_obs"].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0])


def test_5b_the_mirror_series_publishes_the_mirrored_z():
    """Negate every day and the published z is exactly negated, not unchanged.

    Together with 5a this is what a comparative test cannot do: 5a fixes which
    end of the number line a dealer taking on risk lands on, 5b fixes that the
    other case lands on the other end.
    """
    up = _hand_z_frame(_HAND_Z_LEVELS)["z_raw"].to_numpy()[4]
    down = _hand_z_frame([-x for x in _HAND_Z_LEVELS])["z_raw"].to_numpy()[4]
    assert up == pytest.approx(HAND_Z, rel=1e-9)
    assert down == pytest.approx(-HAND_Z, rel=1e-9)
    assert down < 0 < up


def test_5c_the_sign_of_z_is_the_sign_of_the_dealers_received_fixed_risk():
    """The convention, end to end: customer pays fixed -> z > 0. And back.

    ``p`` is the probability the CUSTOMER PAID fixed, so the dealer RECEIVED
    fixed, so the dealer is long duration, so ``delta_dv01 > 0``. A day of that
    on top of a quiet history must publish a large POSITIVE z. This is the
    statement the whole indicator makes, and it is the statement an inverted
    z-score reverses while every invariance below still holds.
    """
    assert conv.signed_weight(0.70) == pytest.approx(+0.4)
    assert conv.signed_weight(0.30) == pytest.approx(-0.4)
    rng = np.random.default_rng(101)
    quiet = list(rng.normal(0.0, 1000.0, 39))
    dates = _dates(40)

    def _last(levels):
        rows = _series_rows(levels, dates=dates)
        f = ind.build(rows, coverage=_coverage(rows), z_min_obs=20,
                      coverage_smooth_obs=1).bucket(
            "5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
        return f.iloc[-1]

    # p = 0.70 on a $1mm/bp print: the dealer received fixed on 400k of DV01
    received = _last(quiet + [400_000.0])
    paid = _last([-q for q in quiet] + [-400_000.0])
    assert received[ind.level_column("5-7Y")] > 0
    assert received["z_raw"] > 3.0, "dealers were lifted; z must say so"
    assert received["z_cov_adj"] > 3.0
    assert paid[ind.level_column("5-7Y")] < 0
    assert paid["z_raw"] < -3.0, "dealers were hit; z must say so"
    assert paid["z_cov_adj"] < -3.0
    assert paid["z_raw"] == pytest.approx(-received["z_raw"], rel=1e-9)


def test_z_is_exactly_invariant_to_a_constant_retention_factor():
    """The known answer: halve one bucket's retained DV01 and z does not move.

    This is why z is the cross-bucket-safe view and the level is not.
    """
    rng = np.random.default_rng(3)
    dates = _dates(60)
    lv = rng.normal(500.0, 3000.0, 60)
    full = _series_rows(lv, dates=dates)
    half = _series_rows(lv * 0.5, dates=dates)
    za = _build(full).standardised()["z_raw"].to_numpy()
    zb = _build(half).standardised()["z_raw"].to_numpy()
    assert np.allclose(za[~np.isnan(za)], zb[~np.isnan(zb)], atol=1e-12)


def test_z_is_not_invariant_to_a_drifting_retention_factor():
    rng = np.random.default_rng(3)
    dates = _dates(300)
    lv = rng.normal(500.0, 3000.0, 300)
    drift = np.linspace(1.0, 0.5, 300)          # retention halves across the sample
    flat = _build(_series_rows(lv, dates=dates)).standardised()["z_raw"].to_numpy()
    drifted = _build(_series_rows(lv * drift, dates=dates)).standardised()["z_raw"].to_numpy()
    ok = ~np.isnan(flat) & ~np.isnan(drifted)
    assert np.nanmax(np.abs(flat[ok] - drifted[ok])) > 0.2


def test_the_drift_flag_trips_on_a_known_slope():
    """Validate the drift meter against an answer known in advance: +5 pp/yr."""
    dates = _dates(500)
    n = len(dates)
    yrs = np.array([(d - dates[0]).days / 365.25 for d in dates])
    cov = 0.55 - 0.05 * yrs                      # exclusion +5 pp/yr => coverage -5
    rows = _series_rows(np.ones(n) * 1000.0, dates=dates)
    per_date = {(r["bucket_key"], d): c for r, (d, c) in
                zip([{"bucket_key": "5-7Y"}] * n, zip(dates, cov))}
    covf = _coverage(rows, per_date=lambda b, d, f: per_date[(b, d)])
    obj = ind.build(rows, coverage=covf, z_min_obs=5)
    drift = obj.drift.set_index("bucket_key")
    assert drift.loc["5-7Y", "coverage_trend_pp_per_yr"] == pytest.approx(-5.0, abs=0.4)
    assert abs(drift.loc["5-7Y", "coverage_trend_t"]) > 5
    assert bool(drift.loc["5-7Y", "coverage_drift_flag"]) is True
    assert drift.loc["5-7Y", "coverage_drift_source"] == "MEASURED"


def test_the_drift_slope_and_its_t_stat_are_a_hand_computable_regression():
    """Four months at 50 / 51 / 52 / 56 percent coverage, worked out by hand.

    ``x = [0, 1, 2, 3] / 12`` years, ``y = [50, 51, 52, 56]`` percent::

        sxx    = 5/144
        slope  = (9.5/12) / (5/144)             = +22.8 pp per year
        resid  = [+0.6, -0.3, -1.2, +0.9], sse  = 2.70
        se     = sqrt(sse / (n-2) / sxx)        = 6.2354
        t      = 22.8 / 6.2354                  = +3.6566

    ``t`` is published as ``coverage_trend_t`` and it is what
    ``DRIFT_T_THRESHOLD`` is compared against, so the degrees of freedom are
    part of the answer: dividing by ``n`` rather than ``n - 2`` publishes
    +5.1711 for the same four numbers -- a 41% inflation on this window, and
    it would tip a genuinely flat bucket over the |t| > 2 line.

    Four months is also below ``MIN_MONTHS_FOR_DRIFT``, so the *decision* here
    is PINNED rather than MEASURED even though the trend is still published.
    """
    assert ind._ols_trend(np.array([50.0, 51.0, 52.0, 56.0]), 4) == pytest.approx(
        (22.8, 3.656551704867627), rel=1e-9)

    dates = list(pd.bdate_range("2025-01-02", "2025-04-30").date)
    by_month = {1: 0.50, 2: 0.51, 3: 0.52, 4: 0.56}
    rows = _series_rows(np.full(len(dates), 1000.0), dates=dates)
    covf = _coverage(rows, per_date=lambda b, d, f: by_month[d.month])
    obj = ind.build(rows, coverage=covf, z_min_obs=5)
    d = obj.drift.set_index("bucket_key").loc["5-7Y"]
    assert d["n_months"] == 4
    assert d["coverage_trend_pp_per_yr"] == pytest.approx(22.8, rel=1e-9)
    assert d["coverage_trend_t"] == pytest.approx(3.656551704867627, rel=1e-9)
    assert d["coverage_drift_source"] == "PINNED"
    assert bool(d["coverage_drift_flag"]) is False


def test_a_flat_coverage_does_not_trip_the_flag():
    dates = _dates(500)
    rows = _series_rows(np.ones(len(dates)) * 1000.0, dates=dates)
    obj = _build(rows)
    assert bool(obj.drift.set_index("bucket_key").loc["5-7Y", "coverage_drift_flag"]) is False


def test_the_front_end_bucket_is_flagged_even_with_no_history_to_measure():
    """A 30-day consumer cannot detect a 5 pp/yr drift; the doc's finding stands in."""
    dates = _dates(20)
    rows = _series_rows(np.ones(20) * 1000.0, dates=dates, bucket="1-2Y", pillar="2Y")
    obj = _build(rows)
    d = obj.drift.set_index("bucket_key")
    assert bool(d.loc["1-2Y", "coverage_drift_flag"]) is True
    assert d.loc["1-2Y", "coverage_drift_source"] == "PINNED"
    assert "1-2Y" in ind.PINNED_DRIFT_BUCKETS


def test_standardised_carries_no_level_at_all():
    obj, _ = _two_bucket_indicator()
    s = obj.standardised()
    leaked = [c for c in s.columns if "dv01" in c and "frac" not in c and "coverage" not in c]
    assert leaked == [], f"the level leaked into the cross-bucket view: {leaked}"
    for col in ("z_raw", "z_cov_adj", "pct_raw", "coverage_frac",
                "coverage_drift_flag", "z_n_obs"):
        assert col in s.columns


def test_z_uses_only_trailing_history():
    rng = np.random.default_rng(7)
    dates = _dates(80)
    lv = rng.normal(0, 1000, 80)
    short = _build(_series_rows(lv[:40], dates=dates[:40])).standardised()
    long_ = _build(_series_rows(lv, dates=dates)).standardised()
    a = short["z_raw"].to_numpy()
    b = long_["z_raw"].to_numpy()[:40]
    ok = ~np.isnan(a) & ~np.isnan(b)
    assert ok.sum() > 10
    assert np.allclose(a[ok], b[ok], atol=1e-12), "a later observation moved an earlier z"


def test_own_history_is_within_the_full_key_not_pooled_across_venues():
    dates = _dates(40)
    rng = np.random.default_rng(5)
    base = rng.normal(0, 100.0, 40)
    quiet = _series_rows(base, venue=T.VENUE_D2C, dates=dates)
    loud = _series_rows(base * 500.0, venue=T.VENUE_D2D, dates=dates)
    alone = _build(quiet).standardised()
    together = _build(pd.concat([quiet, loud], ignore_index=True)).standardised()
    t = together[together.venue_class == T.VENUE_D2C].reset_index(drop=True)
    ok = ~alone["z_raw"].isna().to_numpy() & ~t["z_raw"].isna().to_numpy()
    assert np.allclose(alone["z_raw"].to_numpy()[ok], t["z_raw"].to_numpy()[ok], atol=1e-12)


# -- the other own-history statistic, which is published beside z ----------

@pytest.mark.parametrize("window,expected", [
    ([10., 20., 30., 40., 50.], 1.00),   # today is above all of its history
    ([10., 20., 30., 40., 5.], 0.00),    # below all of it
    ([10., 20., 30., 40., 15.], 0.25),   # above one of four
    ([10., 20., 30., 40., 35.], 0.75),   # above three of four
])
def test_the_trailing_percentile_is_the_share_of_history_below_today(window, expected):
    """``pct_raw`` is published and only its COLUMN was asserted, never a value.

    The 0.25 and 0.75 cases are the point. A function that returns a constant
    0.5, and a function whose comparison runs the wrong way, both reproduce
    every symmetric case and both publish "this day is unremarkable" (or its
    exact opposite) for every day of every bucket.
    """
    assert ind._trailing_percentile(np.asarray(window)) == pytest.approx(expected)


def test_the_trailing_percentile_of_a_first_observation_is_not_a_number():
    """One observation has no history to sit in, and 0.5 is not "no history"."""
    assert np.isnan(ind._trailing_percentile(np.asarray([3.0])))


def test_the_published_percentile_column_carries_those_numbers():
    """End to end, on two series whose answer is 1.0 and 0.0 every single day.

    A strictly rising level is at its own trailing high every day; a strictly
    falling one is at its own low. Anything that reads 0.5, or reads the two
    the other way round, is publishing the opposite of what the tape did.
    """
    n = 12
    up_rows = _series_rows(np.arange(1, n + 1) * 1000.0, dates=_dates(n))
    down_rows = _series_rows(np.arange(n, 0, -1) * 1000.0, dates=_dates(n))

    def _pct(rows):
        return ind.build(rows, coverage=_coverage(rows), z_min_obs=2).bucket(
            "5-7Y", venue_class=T.VENUE_D2C,
            series=ladder.SERIES_FLOW)["pct_raw"].to_numpy()

    up, down = _pct(up_rows), _pct(down_rows)
    assert np.isnan(up[0]) and np.isnan(down[0])
    assert up[1:] == pytest.approx(np.ones(n - 1)), "a new high must read 1.0"
    assert down[1:] == pytest.approx(np.zeros(n - 1)), "a new low must read 0.0"


# --------------------------------------------------------------------------
# 6. coverage is required, and the two bases are both published
# --------------------------------------------------------------------------

def test_coverage_is_required_with_no_default():
    rows = _series_rows([100.0, 200.0], dates=_dates(2))
    with pytest.raises(TypeError):
        ind.build(rows)


def test_a_cell_with_no_coverage_row_is_refused():
    rows = _series_rows([100.0, 200.0, 300.0], dates=_dates(3))
    cov = _coverage(rows).iloc[:2]
    with pytest.raises(ind.CoverageGap) as e:
        ind.build(rows, coverage=cov, z_min_obs=2)
    assert "1" in str(e.value)


def test_a_duplicated_coverage_key_is_refused():
    """Two coverage rows for one cell do not average -- they DUPLICATE the cell.

    ``build`` left-joins coverage onto the levels, so a repeated
    (bucket, day, venue, series) key emits the published cell twice: the day's
    DV01 is counted twice in every trailing statistic downstream and the frame
    still looks like a well-formed daily series.
    """
    rows = _series_rows([100.0, 200.0], dates=_dates(2))
    cov = _coverage(rows)
    doubled = pd.concat([cov, cov.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError) as e:
        ind.coverage_fraction(doubled)
    assert "duplicated" in str(e.value)
    with pytest.raises(ValueError):
        ind.build(rows, coverage=doubled, z_min_obs=1)


def test_coverage_fraction_is_kept_over_total():
    rows = _series_rows([100.0], dates=_dates(1))
    cov = _coverage(rows, frac=0.4)
    obj = ind.build(rows, coverage=cov, z_min_obs=1)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    assert f["coverage_frac"].iloc[0] == pytest.approx(0.4)


def test_both_bases_are_published_and_the_basis_travels_with_the_number():
    rows = _series_rows(np.ones(80) * 1000.0, dates=_dates(80))
    obj = _build(rows)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    assert ind.level_column("5-7Y") in f.columns
    assert ind.level_column("5-7Y", basis="cov_adj") in f.columns
    assert set(f["primary_level_basis"]) == {"RAW"}


def test_the_adjustment_smooths_coverage_rather_than_dividing_by_the_day():
    """Dividing by the day's own coverage injects daily noise to fix a slow trend.

    Measured on the real tape, the day-over-day |relative| coverage move has a
    median of 13-34% depending on bucket -- the daily fraction is mostly print
    composition, not a regime. So the adjusted basis divides by a trailing mean,
    and on a constant true level it must stay nearly constant while the naive
    per-day division does not.
    """
    rng = np.random.default_rng(41)
    n = 400
    dates = _dates(n)
    lvl = np.full(n, 1000.0)                        # a perfectly constant level
    cov = np.clip(0.45 * np.exp(rng.normal(0, 0.30, n)), 0.02, 0.99)
    rows = _series_rows(lvl, dates=dates)
    lookup = dict(zip(dates, cov))
    obj = ind.build(rows, coverage=_coverage(rows, per_date=lambda b, d, f: lookup[d]),
                    z_min_obs=5)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    raw = f[ind.level_column("5-7Y")].to_numpy()
    adj = f[ind.level_column("5-7Y", basis="cov_adj")].dropna().to_numpy()
    naive = lvl * cov.mean() / cov                  # what per-day division gives

    def cv(a):
        return float(np.std(a) / np.abs(np.mean(a)))

    assert np.std(raw) == pytest.approx(0.0, abs=1e-9)
    assert cv(adj) < cv(naive) / 5.0, (
        f"the adjustment manufactured coverage noise: cv(adj)={cv(adj):.4f} "
        f"vs cv(per-day)={cv(naive):.4f}")


def test_the_adjusted_level_is_the_raw_level_when_coverage_holds_still():
    """The scale of the adjusted level, which no other test pins.

    The two tests around this one are both scale-invariant -- one compares a
    coefficient of variation, the other a ratio of slopes -- so replacing the
    reference ``mean(coverage)`` with 1.0 divides every published adjusted
    level by the coverage fraction (2.5x here) and neither notices. The known
    answer is: **constant coverage means the adjustment is the identity**, the
    factor is ``mean(coverage) / smoothed(coverage) = 1``, and it is 1 because
    the reference is a coverage, not a bare 1.0.

    The NaN prefix is the second half. The smoother must have all 63 of its
    observations before the adjusted basis exists at all -- an adjustment that
    starts on day 1 is dividing by something close to the day's own fraction,
    which is what the raw basis is primary to avoid.
    """
    n = 80
    rng = np.random.default_rng(77)
    rows = _series_rows(rng.normal(0.0, 3000.0, n), dates=_dates(n))
    obj = ind.build(rows, coverage=_coverage(rows, frac=0.4), z_min_obs=5,
                    coverage_smooth_obs=63)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    raw = f[ind.level_column("5-7Y")].to_numpy()
    adj = f[ind.level_column("5-7Y", basis="cov_adj")].to_numpy()
    assert np.isnan(adj[:62]).all(), "the smoother must fill before it divides"
    assert np.isfinite(adj[62:]).all()
    assert adj[62:] == pytest.approx(raw[62:], rel=1e-9)
    assert np.abs(raw[62:]).max() > 1000.0, "the fixture must not be all zeros"


def test_the_adjusted_level_is_mean_coverage_over_smoothed_coverage_times_the_raw():
    """A step in coverage with an adjustment factor computable by hand.

    63 days at 0.60 then 63 at 0.30. Three days where every term is known:

    ======  ==================================  ================  ==========
    row     smoothed coverage (63 obs)          mean(coverage)    adjusted
    ======  ==================================  ================  ==========
    62      0.60                                0.45              750
    80      (45*0.60 + 18*0.30)/63 = 0.5142857  0.45              875
    125     0.30                                0.45              1500
    ======  ==================================  ================  ==========

    on a raw level of 1,000 throughout. Row 80 is the one that separates the
    smoother from the day's own fraction: the day's own coverage there is 0.30
    and the smoothed value is 0.514, so a published ``coverage_smooth`` of 0.30
    would be the naive per-day division the module docstring refuses.
    """
    n = 126
    dates = _dates(n)
    cov = np.array([0.60] * 63 + [0.30] * 63)
    lookup = dict(zip(dates, cov))
    rows = _series_rows(np.full(n, 1000.0), dates=dates)
    obj = ind.build(rows, coverage=_coverage(rows, per_date=lambda b, d, x: lookup[d]),
                    z_min_obs=5, coverage_smooth_obs=63)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    smooth = f["coverage_smooth"].to_numpy()
    adj = f[ind.level_column("5-7Y", basis="cov_adj")].to_numpy()
    assert np.isnan(smooth[:62]).all()
    for row, want_smooth, want_adj in ((62, 0.60, 750.0),
                                       (80, 0.45 / 0.875, 875.0),
                                       (125, 0.30, 1500.0)):
        assert smooth[row] == pytest.approx(want_smooth, rel=1e-9), f"row {row}"
        assert adj[row] == pytest.approx(want_adj, rel=1e-9), f"row {row}"
    # and the direction: coverage fell, so the same tape DV01 means more risk
    assert adj[125] > f[ind.level_column("5-7Y")].to_numpy()[125]


def test_the_coverage_adjustment_removes_a_known_coverage_trend_from_the_level():
    """A flat true level seen through falling coverage trends down; adjusted, it does not."""
    dates = _dates(400)
    n = len(dates)
    yrs = np.array([(d - dates[0]).days / 365.25 for d in dates])
    cov = 0.55 - 0.05 * yrs
    true_level = 1000.0
    observed = true_level * (cov / cov[0])
    rows = _series_rows(observed, dates=dates)
    lookup = dict(zip(dates, cov))
    covf = _coverage(rows, per_date=lambda b, d, f: lookup[d])
    obj = ind.build(rows, coverage=covf, z_min_obs=5, coverage_smooth_obs=63)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW).dropna(
        subset=[ind.level_column("5-7Y", basis="cov_adj")])
    x = np.array([(d - dates[0]).days / 365.25 for d in f["visibility_date"]])
    raw_slope = np.polyfit(x, f[ind.level_column("5-7Y")].to_numpy(), 1)[0]
    adj_slope = np.polyfit(
        x, f[ind.level_column("5-7Y", basis="cov_adj")].to_numpy(), 1)[0]
    assert raw_slope < -50.0
    assert abs(adj_slope) < 0.25 * abs(raw_slope)


# --------------------------------------------------------------------------
# 7. constraint 3 -- it refuses to cumulate
# --------------------------------------------------------------------------

def test_cumulating_is_refused_and_points_at_the_decay():
    obj, _ = _two_bucket_indicator()
    for name in ("cumulate", "cumsum", "position", "inventory"):
        fn = getattr(obj, name, None)
        assert fn is not None, f"{name} must exist and refuse, not be absent"
        with pytest.raises(ind.CumulationRefused) as e:
            fn()
        assert "decayed_flow" in str(e.value)
        assert "half_life" in str(e.value)


def test_no_published_column_accumulates():
    obj, _ = _two_bucket_indicator()
    frames = [obj.standardised()] + [
        obj.bucket(b, venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
        for b in obj.buckets]
    for f in frames:
        bad = [c for c in f.columns
               if re.search(r"cum|running|stock|position|inventory", c, re.I)]
        assert bad == [], bad


# --------------------------------------------------------------------------
# 8. the sample floor and the provenance
# --------------------------------------------------------------------------

def test_the_pre_ingest_break_window_is_refused_by_default():
    rows = _series_rows([100.0], dates=[datetime.date(2024, 5, 2)])
    with pytest.raises(ind.SampleFloorViolation) as e:
        ind.build(rows, coverage=_coverage(rows), z_min_obs=1)
    assert "2024-07-01" in str(e.value)
    assert ind.SAMPLE_FLOOR == datetime.date(2024, 7, 1)


def test_the_floor_can_be_crossed_on_purpose():
    rows = _series_rows([100.0], dates=[datetime.date(2024, 5, 2)])
    obj = ind.build(rows, coverage=_coverage(rows), z_min_obs=1, allow_pre_floor=True)
    assert len(obj.buckets) == 1


def test_provenance_reaches_the_published_row():
    rows = pd.concat([
        _series_rows([100.0], dates=_dates(1)),
        _unit_rows([{"unit_key": "B1", "bucket_key": "6Y", "dv01_if_received": 1e6,
                     "date": D0, "is_block": True, "is_capped": True,
                     "in_dead_zone": True, "code_vintage": "999999999999",
                     "visibility_source": "MEASURED_SLICE"}]),
    ], ignore_index=True)
    obj = ind.build(rows, coverage=_coverage(rows), z_min_obs=1)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    r = f.iloc[0]
    assert r["frac_dv01_capped"] == pytest.approx(0.5)
    assert r["frac_dv01_block"] == pytest.approx(0.5)
    assert r["frac_dv01_dead_zone"] == pytest.approx(0.5)
    assert r["frac_dv01_visibility_measured"] == pytest.approx(0.5)
    assert r["code_vintage"].startswith("MIXED:")
    assert r["n_units"] == 2
    assert 0.0 <= r["mean_abs_signed_weight"] <= 1.0


def test_mean_abs_signed_weight_is_the_gross_weighted_mean_of_the_2p_minus_1s():
    """Only its BOUNDS are asserted elsewhere, and 1.0 is inside them.

    This is the column a reader uses to discount a day: it says how confident
    the direction calls behind the net level were. Published as a constant 1.0
    it claims every print in the cell was a certain call -- that the net level
    IS the gross pond -- which is the most flattering value it can take and
    the one that makes a cell of coin flips look like a conviction trade.
    """
    rows = _unit_rows([
        {"unit_key": "A", "bucket_key": "6Y", "dv01_if_received": 1e6,
         "date": D0, "p": 0.75},                       # |2p-1| = 0.50
        {"unit_key": "B", "bucket_key": "6Y", "dv01_if_received": 3e6,
         "date": D0, "p": 0.10},                       # |2p-1| = 0.80
    ])
    lv = ind.daily_levels(rows)
    # gross-weighted: (0.50*1 + 0.80*3) / 4 = 0.725
    assert lv["mean_abs_signed_weight"].iloc[0] == pytest.approx(0.725)
    assert lv["delta_dv01"].iloc[0] == pytest.approx(0.5e6 - 2.4e6)
    assert lv["abs_dv01"].iloc[0] == pytest.approx(4e6)


def test_a_cell_of_coin_flips_reports_no_confidence():
    """p = 0.5 everywhere: the net is zero and the confidence is zero, not one."""
    rows = _series_rows([0.0, 0.0], dates=_dates(2))
    lv = ind.daily_levels(rows)
    assert lv["p"].tolist() == pytest.approx([0.5, 0.5]) if "p" in lv.columns else True
    assert lv["mean_abs_signed_weight"].tolist() == pytest.approx([0.0, 0.0])
    assert lv["abs_dv01"].tolist() == pytest.approx([1e6, 1e6])


def test_a_single_vintage_is_reported_as_itself():
    rows = _series_rows([100.0], dates=_dates(1))
    obj = _build(rows)
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    assert f["code_vintage"].iloc[0] == "abcdef012345"


# --------------------------------------------------------------------------
# 9. absent days
# --------------------------------------------------------------------------

def test_absent_days_are_gaps_unless_a_calendar_is_supplied():
    dates = _dates(5)
    rows = _series_rows([100.0, 200.0], dates=[dates[0], dates[4]])
    assert len(_build(rows).standardised()) == 2
    obj = ind.build(rows, coverage=_coverage(rows), z_min_obs=1, session_dates=dates)
    s = obj.standardised()
    assert len(s) == 5
    assert s["observed"].tolist() == [True, False, False, False, True]
    f = obj.bucket("5-7Y", venue_class=T.VENUE_D2C, series=ladder.SERIES_FLOW)
    assert f[ind.level_column("5-7Y")].tolist() == pytest.approx([100.0, 0, 0, 0, 200.0])
    assert f["n_units"].tolist() == [1, 0, 0, 0, 1]


# --------------------------------------------------------------------------
# 10. the properties reporter -- validated against known answers
# --------------------------------------------------------------------------

def test_autocorrelation_recovers_a_known_ar1():
    rng = np.random.default_rng(19)
    n, phi = 4000, 0.6
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, 1)
    dates = list(pd.bdate_range(D0, periods=n).date)
    rows = _series_rows(x * 1000.0, dates=dates)
    obj = ind.build(rows, coverage=_coverage(rows), z_min_obs=20, allow_pre_floor=True)
    props = obj.properties()
    r = props.set_index(["bucket_key", "venue_class", "series"]).loc[
        ("5-7Y", T.VENUE_D2C, ladder.SERIES_FLOW)]
    assert r["ac1"] == pytest.approx(phi, abs=0.05)
    assert r["n_obs"] == n
    # AC(5) is published for ten buckets in INDICATOR.md 5.1 and nothing
    # asserted it. An AR(1) decays geometrically: phi**5 = 0.0778, not 0.6.
    assert r["ac5"] == pytest.approx(phi ** 5, abs=0.05)
    assert r["ac5"] < 0.4 * r["ac1"], (
        "the AC(5) column is reporting AC(1), so the published table claims "
        "five times the market memory the series has")


def test_autocorrelation_reads_the_lag_it_is_given():
    """The lag argument, on a series whose answer is known at every lag.

    A cosine of period 12 has autocorrelation ``cos(2*pi*k/12)``: +0.866 at
    lag 1, **-0.866** at lag 5, -1 at lag 6. A ``_autocorr`` that ignores its
    lag returns +0.866 for all three -- and both the sign and the magnitude of
    a published column are then wrong with nothing to show for it.
    """
    x = np.cos(2.0 * np.pi * np.arange(1200) / 12.0)
    assert ind._autocorr(x, 1) == pytest.approx(np.cos(2 * np.pi / 12), abs=0.01)
    assert ind._autocorr(x, 5) == pytest.approx(np.cos(10 * np.pi / 12), abs=0.01)
    assert ind._autocorr(x, 6) == pytest.approx(-1.0, abs=0.01)


def test_an_autocorrelation_from_two_points_is_not_published():
    """At ``len(x) == lag + 2`` the two lagged vectors are two points long, and
    the correlation of two points is **+1 or -1 whatever the numbers are**.

    A thin cell early in a backfill would otherwise publish AC(5) = 1.000 --
    "perfect weekly persistence" -- as an artefact of having seven days of
    history. Same family as this module's own ADF returning -1086.7: a number
    manufactured by arithmetic rather than measured.
    """
    def _two_point_corr(x, lag):
        a, b = x[:-lag], x[lag:]
        xa, xb = a - a.mean(), b - b.mean()
        return float((xa * xb).sum() / np.sqrt((xa ** 2).sum() * (xb ** 2).sum()))

    # what the guard is standing in front of: any three points, |ac1| == 1
    assert abs(_two_point_corr(np.array([1.0, 5.0, 9.0]), 1)) == pytest.approx(1.0)
    assert abs(_two_point_corr(np.array([1.0, 5.0, 2.0]), 1)) == pytest.approx(1.0)

    assert np.isnan(ind._autocorr(np.array([1.0, 5.0, 9.0]), 1)), "3 points, lag 1"
    assert np.isnan(ind._autocorr(np.arange(7.0) ** 1.3, 5)), "7 points, lag 5"
    assert np.isfinite(ind._autocorr(np.arange(8.0) ** 1.3, 5)), "8 points, lag 5"


def test_stationarity_flags_a_random_walk_and_clears_white_noise():
    rng = np.random.default_rng(23)
    n = 1500
    dates = list(pd.bdate_range(D0, periods=n).date)
    wn = rng.normal(0, 1000, n)
    rw = np.cumsum(rng.normal(0, 1000, n))
    p_wn = ind.build(_series_rows(wn, dates=dates),
                     coverage=_coverage(_series_rows(wn, dates=dates)),
                     z_min_obs=20, allow_pre_floor=True).properties()
    p_rw = ind.build(_series_rows(rw, dates=dates),
                     coverage=_coverage(_series_rows(rw, dates=dates)),
                     z_min_obs=20, allow_pre_floor=True).properties()
    assert bool(p_wn["level_stationary"].iloc[0]) is True
    assert bool(p_rw["level_stationary"].iloc[0]) is False


def test_the_adf_reproduces_statsmodels_on_five_series_with_known_answers():
    """The cross-check that lived in ``scratch/`` and therefore in no gate.

    ``_adf`` is written out so the module carries no statistics dependency, and
    this module has already caught its own ADF returning -1086.7 where the
    answer is -4.96. The **lag order is part of the statistic**: collapsing it
    to 1 changes the number on every series, leaves the scale-invariance test
    below perfectly happy, and no property of ``properties()`` looks wrong. The
    Schwert rule is written out here rather than imported from the module, so
    agreement with an independent implementation *at that lag* is evidence
    about the module's lag choice and not a restatement of it.
    """
    sm = pytest.importorskip("statsmodels.tsa.stattools")
    rng = np.random.default_rng(103)
    n = 800

    def _ar1(phi):
        x, e = np.zeros(n), rng.normal(0, 1, n)
        for i in range(1, n):
            x[i] = phi * x[i - 1] + e[i]
        return x

    # The verdicts below are the answers for THIS draw, not guarantees about the
    # processes: the test is 5% size and ~100% power at n = 800, so an
    # individual random walk is rejected one time in twenty (seed 101 draws one
    # such walk, at t = -2.94). The agreement with statsmodels is the part that
    # holds for every draw, and it is the part that pins the lag order.
    cases = {
        "white noise": (rng.normal(0, 1, n), True),
        "AR(1) phi=0.6": (_ar1(0.6), True),
        "AR(1) phi=0.98": (_ar1(0.98), None),        # -2.77: genuinely borderline
        "random walk": (np.cumsum(rng.normal(0, 1, n)), False),
        "random walk with drift": (np.cumsum(rng.normal(0.05, 1, n)), False),
    }
    lags = int(min(25, max(1, np.ceil(12.0 * (n / 100.0) ** 0.25))))
    assert lags == 21, "Schwert's rule at n=800"
    # the constant the verdict column is cut at; INDICATOR.md 5.1 reads two
    # buckets against it by name
    assert ind.ADF_CRITICAL_5PCT == pytest.approx(-2.86)
    for name, (x, expect) in cases.items():
        t_ours, stationary = ind._adf(x)
        t_sm, p_sm, *_ = sm.adfuller(x, maxlag=lags, regression="c", autolag=None)
        assert t_ours == pytest.approx(t_sm, abs=1e-8), f"{name}: t"
        assert stationary is bool(p_sm < 0.05), f"{name}: verdict"
        if expect is not None:
            assert stationary is expect, f"{name}: known answer"


def test_a_series_too_short_to_test_gets_no_stationarity_verdict():
    """``None``, never a verdict. A short series is not evidence of stability.

    The lengths here are **absolute, not written as ``MIN_ADF_OBS - 1``**. A
    forty-observation Dickey-Fuller regression is perfectly well posed
    arithmetically -- it returns a confident-looking t of -1.37 on the draw
    below -- so a floor expressed relative to itself is not a floor at all: it
    moves with the constant it is meant to pin and the published
    ``level_stationary`` column silently starts answering on two months of
    data.
    """
    assert ind.MIN_ADF_OBS == 60, "two months of business days is not a sample"
    rng = np.random.default_rng(5)
    for n_short in (20, 40, 59):
        t, verdict = ind._adf(rng.normal(0, 1, n_short))
        assert verdict is None, f"n = {n_short} must get no verdict"
        assert np.isnan(t)
    t_ok, verdict_ok = ind._adf(rng.normal(0, 1, 360))
    assert verdict_ok is not None and np.isfinite(t_ok)


def test_a_short_cell_publishes_no_stationarity_verdict():
    """And the same through the published column, not just the helper."""
    n = 40
    rng = np.random.default_rng(13)
    rows = _series_rows(rng.normal(0.0, 1000.0, n), dates=_dates(n))
    props = ind.build(rows, coverage=_coverage(rows), z_min_obs=20).properties()
    assert props["n_obs"].iloc[0] == n
    assert props["level_stationary"].iloc[0] is None
    assert np.isnan(props["adf_stat"].iloc[0])


def test_the_stationarity_meter_is_invariant_to_the_scale_of_the_level():
    """A DV01 level is ~1e7, not ~1. The statistic must not know that.

    ``t_rho`` is exactly scale- and location-invariant on paper: scaling the
    series scales the fitted rho's numerator and its standard error together.
    A design matrix carrying a column of ones beside a column of 1e7s is not,
    and the failure is silent -- measured on the real 610-day gross series it
    returned -20.98 where the well-scaled answer is -4.23, i.e. it manufactured
    a very confident 'stationary' out of arithmetic.
    """
    rng = np.random.default_rng(31)
    x = rng.normal(0.0, 1.0, 800) + 50.0
    base, _ = ind._adf(x)
    for scale in (1e3, 1e7, 1e11):
        t, _ = ind._adf(x * scale)
        assert t == pytest.approx(base, abs=1e-6), f"scale {scale:g} moved t"
    shifted, _ = ind._adf(x * 1e7 + 3.2e9)
    assert shifted == pytest.approx(base, abs=1e-6)


def test_coverage_moves_are_counted_against_the_level_s_own_noise():
    """'Enough to matter' is defined against sigma of the level, not an eyeball."""
    dates = _dates(300)
    n = len(dates)
    rng = np.random.default_rng(29)
    lv = rng.normal(0, 1000.0, n)
    cov = np.full(n, 0.57)
    cov[150:] = 0.30                      # a big, obvious step
    rows = _series_rows(lv, dates=dates)
    lookup = dict(zip(dates, cov))
    obj = ind.build(rows, coverage=_coverage(rows, per_date=lambda b, d, f: lookup[d]),
                    z_min_obs=20)
    props = obj.properties().iloc[0]
    assert props["n_coverage_moves_that_matter"] >= 1
    flat = ind.build(rows, coverage=_coverage(rows), z_min_obs=20).properties().iloc[0]
    assert flat["n_coverage_moves_that_matter"] == 0


def test_whether_a_coverage_move_matters_is_decided_by_the_level_not_the_move():
    """Identical coverage churn, opposite verdicts, and the LEVEL decides.

    The rule is ``|dc|/c`` applied to the level's typical size, against 0.25
    standard deviations of the level. Comparing ``rel * sd > 0.25 * sd``
    instead -- i.e. ``rel > 0.25``, an absolute threshold on the coverage move
    on its own -- is exactly the absolute-versus-relative confusion the
    docstring says cannot work, and it is **invisible on any zero-mean level**,
    because there ``rms == sd`` and the two rules coincide. Real bucket levels
    are not zero-mean.

    Both cells below see the same ~2% daily coverage churn. The first has a
    level of 1,000 +- 10 (rms/sd ~ 100), so a 2% measurement wobble is 20 DV01
    against a 2.5 DV01 threshold and matters every single day. The second has a
    level of 0 +- 1,000 (rms/sd ~ 1), so the same wobble is 20 DV01 against a
    250 DV01 threshold and never matters.
    """
    n = 250
    dates = _dates(n)
    rng = np.random.default_rng(83)
    cov = np.where(np.arange(n) % 2 == 0, 0.50, 0.51)
    lookup = dict(zip(dates, cov))

    def _props(level):
        rows = _series_rows(level, dates=dates)
        return ind.build(rows,
                         coverage=_coverage(rows, per_date=lambda b, d, f: lookup[d]),
                         z_min_obs=20).properties().iloc[0]

    biased = _props(1000.0 + rng.normal(0.0, 10.0, n))
    centred = _props(rng.normal(0.0, 1000.0, n))
    # the coverage path -- and therefore every relative move -- is identical
    assert biased["p95_abs_rel_coverage_move"] == pytest.approx(0.02, abs=0.002)
    assert centred["p95_abs_rel_coverage_move"] == pytest.approx(0.02, abs=0.002)
    assert biased["n_coverage_moves_that_matter"] >= 240
    assert centred["n_coverage_moves_that_matter"] == 0


def test_the_published_coverage_move_percentile_is_the_95th_not_the_median():
    """A hand-built multiset of relative moves: 80 of 1% and 20 of 20%.

    Building the coverage path multiplicatively makes each step's relative move
    exactly the number chosen for it, so the published statistic has an exact
    answer: p95 = 0.20 while the median is 0.01, two orders of magnitude apart.
    A median under a p95 heading would report the real tape's 15-20Y bucket as
    a 33% churn (INDICATOR.md 5.2) rather than the tail that actually distorts
    a day, and nothing about the number would look wrong.
    """
    steps = 100
    size = np.where(np.arange(steps) % 5 == 0, 0.20, 0.01)     # 20 big, 80 small
    sign = np.where(np.arange(steps) % 2 == 0, 1.0, -1.0)      # so it stays put
    cov = [0.60]
    for i in range(steps):
        cov.append(cov[-1] * (1.0 + sign[i] * size[i]))
    cov = np.array(cov)
    assert 0.0 < cov.min() and cov.max() <= 1.0
    dates = _dates(len(cov))
    lookup = dict(zip(dates, cov))
    rng = np.random.default_rng(59)
    rows = _series_rows(rng.normal(1000.0, 50.0, len(cov)), dates=dates)
    props = ind.build(rows, coverage=_coverage(rows, per_date=lambda b, d, f: lookup[d]),
                      z_min_obs=20).properties().iloc[0]
    assert props["p95_abs_rel_coverage_move"] == pytest.approx(0.20, abs=1e-6)


# --------------------------------------------------------------------------
# 11. the seam with the ladder, so the two shapes stay joined
# --------------------------------------------------------------------------

def _real_unit(unit_key, day, venue=T.VENUE_D2C):
    exec_ts = pd.Timestamp(NY.localize(datetime.datetime(
        day.year, day.month, day.day, 10, 0))).tz_convert("UTC")
    legs = pd.DataFrame({
        "trade_id": ["T0"], "as_of_date": [day], "effective_date": [day],
        "expiration_date": [day + datetime.timedelta(days=365 * 5)],
        "notional": [100e6], "fixed_rate": [0.0394]})
    clocks = T.Clocks(pricing=exec_ts, execution=exec_ts, event=exec_ts,
                      visibility=exec_ts + pd.Timedelta(minutes=15),
                      visibility_source="APPENDIX_C_ESTIMATE", report_lag_seconds=0.0)
    return T.Unit(unit_key=unit_key, kind=conv.OUTRIGHT, legs=legs, package_id=None,
                  rate_index="SOFR", as_of_date=day, venue_class=venue, clocks=clocks)


def test_it_consumes_what_the_ladder_emits():
    day = datetime.date(2025, 6, 10)
    units = [_real_unit("U1", day)]
    calls = [T.DirectionCall(unit_key="U1", rule=conv.RULE_RATE, deviation_bps=0.4,
                             p=0.8, signed_weight=conv.signed_weight(0.8),
                             dealer_sign=1, tau_bucket="B", tau_bps=0.5)]
    krd_rows = pd.DataFrame({"unit_key": ["U1", "U1"],
                             "bucket_space": [krd.BUCKET_SPACE] * 2,
                             "bucket_key": ["4Y", "5Y"],
                             "dv01_if_received": [1000.0, 40000.0]})
    rows, excluded = ladder.unit_ladder_rows(units, calls, krd_rows)
    assert len(rows) == 2 and excluded.empty
    lv = ind.daily_levels(rows)
    assert len(lv) == 1 and lv["bucket_key"].iloc[0] == "3-5Y"
    assert lv["delta_dv01"].iloc[0] == pytest.approx(0.6 * 41000.0)
    assert lv["visibility_date"].iloc[0] == day
