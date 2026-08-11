"""The daily street-positioning indicator, pinned.

The measurement this file is built around is
``docs/dealer_direction/2026-08-11-package-exclusion-skew.md``: the retained
population is a biased sample whose retention factor runs 0.761 at 0-1Y down to
0.495 at 15-20Y, a 1.54x cross-bucket scaling distortion. Everything asserted
here follows from that one fact plus the pinned sign convention.

Five failures this file exists to make impossible, every one of them silent:

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
# 5. the z-score -- retention-invariant, and only while retention holds still
# --------------------------------------------------------------------------

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
