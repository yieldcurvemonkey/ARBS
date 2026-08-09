"""The deep-warm planner and its discount-source resolution.

Hermetic - no Excel, no CurveStore on disk, no network. Everything here is the
plumbing that decides *what gets fetched* and *what discounts what*, which is
where this warm's mistakes are cheap to make and expensive to notice: a wrong
answer produces a plausible curve, not an error.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import citivelo_deep_intraday_warm as D  # noqa: E402


class FakeStore:
    """A CurveStore with a hand-written day/count map and nothing else."""

    def __init__(self, days_by_asset):
        self._days = {k: dict(v) for k, v in days_by_asset.items()}

    def available_dates(self, asset):
        return sorted(self._days.get(asset, {}))

    def has_day(self, asset, day):
        return day in self._days.get(asset, {})

    def raw_partition_dir(self, asset, day):  # pragma: no cover - unused here
        return Path("/nonexistent")


@pytest.fixture
def fake_store(monkeypatch):
    def _install(days_by_asset, counts=None):
        store = FakeStore(days_by_asset)
        monkeypatch.setattr(
            "Caching.curve_store.CurveStore.default", classmethod(lambda cls: store)
        )
        if counts is not None:
            monkeypatch.setattr(
                D, "_stored_curve_count",
                lambda s, asset, day: counts.get((asset, day), 0),
            )
        return store

    return _install


# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "tenor, years",
    [("1D", 1 / 365.25), ("1W", 7 / 365.25), ("6M", 0.5), ("1Y", 1.0), ("30Y", 30.0)],
)
def test_tenor_years(tenor, years):
    assert D._tenor_years_of(tenor) == pytest.approx(years, rel=1e-9)


def test_an_unparseable_tenor_sorts_below_the_one_year_cut():
    """It must not accidentally survive the sub-1Y filter as a huge number."""
    assert D._tenor_years_of("SPOT") == 0.0
    assert D._tenor_years_of("") == 0.0


def test_eonia_is_bounded_to_where_estr_takes_over():
    """EONIA is fetched to DISCOUNT the pre-ESTR EURIBOR era, not for itself.

    Without the bound it would pay four extra Excel sessions for 2021-2025 data
    that ESTR already covers - and EONIA stopped publishing in 2025 anyway.
    """
    horizon = D.HORIZONS["EUR-EONIA-1D"]
    assert horizon.until == datetime.date(2021, 10, 1)
    assert D.HORIZONS["EUR-ESTR-1D"].until is None


def test_jpy_default_is_the_deep_curve_not_the_lch_twin():
    """JPY_TONAR reaches 2017-12; JPY_TONAR_LCH only 2024-01. Six years apart."""
    assert "JPY-TONAR-1D" in D.DEFAULT_CURVES
    assert "JPY-TONAR-1D-LCH" not in D.DEFAULT_CURVES
    assert D.HORIZONS["JPY-TONAR-1D"].start < D.HORIZONS["JPY-TONAR-1D-LCH"].start


def test_ibor_curves_route_to_their_own_tag_grid():
    tags, zone = D.tags_and_zone_for("EUR-EURIBOR-6M")
    assert zone == "Europe/Berlin"
    assert tags and all(t.startswith("RATES.SWAP_LIBOR.EUR.PAR.") for t in tags)
    # ...and an OIS curve falls through to the ordinary lookup.
    assert D.tags_and_zone_for("USD-SOFR-1D") == (None, None)


# --------------------------------------------------------------------------- #
#                        the discount source resolution                        #
# --------------------------------------------------------------------------- #


def test_discount_falls_back_to_the_store_when_the_parquet_is_absent(tmp_path, fake_store):
    """The defect this test exists for.

    The fetch planner SKIPS a day the store already holds densely, so
    EUR-ESTR-1D has no work-directory parquet for the ~500 days it is already
    warmed for. A parquet-only lookup falls through ESTR, then through EONIA
    (whose plan stops in 2021), and self-discounts the two most liquid years in
    the range with the right curve sitting in the store the whole time.
    """
    day = datetime.date(2025, 6, 11)
    fake_store({"EUR-ESTR-1D-CITIVELOEXCELMIN": {day: 1200}})
    assert D.discount_source_for("EUR-EURIBOR-6M", day, tmp_path) == ("EUR-ESTR-1D", "store")


def test_the_parquet_wins_when_both_exist(tmp_path, fake_store):
    day = datetime.date(2025, 6, 11)
    fake_store({"EUR-ESTR-1D-CITIVELOEXCELMIN": {day: 1200}})
    (tmp_path / "EUR-ESTR-1D").mkdir(parents=True)
    (tmp_path / "EUR-ESTR-1D" / f"{day.isoformat()}.parquet").write_bytes(b"")
    assert D.discount_source_for("EUR-EURIBOR-6M", day, tmp_path) == ("EUR-ESTR-1D", "parquet")


def test_eonia_discounts_the_pre_estr_era(tmp_path, fake_store):
    day = datetime.date(2019, 6, 12)
    fake_store({"EUR-EONIA-1D-CITIVELOEXCELMIN": {day: 900}})
    assert D.discount_source_for("EUR-EURIBOR-6M", day, tmp_path) == ("EUR-EONIA-1D", "store")


def test_below_every_euro_ois_floor_it_self_discounts_and_says_so(tmp_path, fake_store):
    """2016-07 -> 2017-12: EURIBOR has minute data and no euro OIS curve does."""
    fake_store({})
    assert D.discount_source_for(
        "EUR-EURIBOR-6M", datetime.date(2016, 9, 14), tmp_path
    ) == (None, "self")


def test_estr_is_not_used_before_its_measured_intraday_floor(tmp_path, fake_store):
    """ESTR the INDEX existed in 2020; Citi's intraday history for it did not.

    A discount curve that has no snapshot at the minute being priced cannot
    discount it, whatever the index's own history says.
    """
    day = datetime.date(2020, 6, 10)
    fake_store({"EUR-ESTR-1D-CITIVELOEXCELMIN": {day: 1200}})
    name, _ = D.discount_source_for("EUR-EURIBOR-6M", day, tmp_path)
    assert name != "EUR-ESTR-1D"


# --------------------------------------------------------------------------- #
#                                 the planner                                  #
# --------------------------------------------------------------------------- #


def test_a_thin_stored_day_is_refetched_and_a_dense_one_is_not(tmp_path, fake_store):
    """This is what upgrades USD-SOFR's ten-minute 2022-2023 era.

    Those days ARE in the store - about 130 curves each against ~1,250 for a real
    minute day - so a ``has_day()`` check calls them covered and they stay
    ten-minute forever.

    Asserted at CHUNK granularity, which is the unit the planner works in: a
    5-day Excel window cannot be fetched minus one day, so a chunk is issued when
    any day in it is missing. The claim being tested is that density alone
    decides whether a fully-stored stretch is skipped.
    """
    asset = "USD-SOFR-1D-CITIVELOEXCELMIN"
    dense = _bdays(datetime.date(2025, 6, 2), datetime.date(2025, 6, 14))
    thin = _bdays(datetime.date(2023, 6, 2), datetime.date(2023, 6, 14))
    fake_store(
        {asset: {d: 1 for d in dense + thin}},
        counts={**{(asset, d): 1250 for d in dense}, **{(asset, d): 132 for d in thin}},
    )

    dense_plan = D.plan_curve(
        "USD-SOFR-1D", work_dir=tmp_path,
        start=datetime.date(2025, 6, 2), end=datetime.date(2025, 6, 14),
        chunk_days=30, min_store_curves=600,
    )
    thin_plan = D.plan_curve(
        "USD-SOFR-1D", work_dir=tmp_path,
        start=datetime.date(2023, 6, 2), end=datetime.date(2023, 6, 14),
        chunk_days=30, min_store_curves=600,
    )
    assert dense_plan.chunks == [], "a fully dense stored stretch must not be refetched"
    assert thin_plan.chunks, "a ten-minute stored stretch must be refetched"


def test_the_density_threshold_does_not_apply_below_the_dense_floor(tmp_path, fake_store):
    """A sparse-era day can never reach 600 curves; a flat rule refetches forever.

    USD-FEDFUNDS publishes a few hundred prints a day before its 2018-09
    dense floor. Judging those by the dense-era threshold marks every one of them
    thin on every run, so the same Excel windows are paid for again and again and
    the backfill never converges.

    The discriminating pair: the SAME 224-curve density is "done" below the floor
    and "thin" above it.
    """
    asset = "USD-FEDFUNDS-1D-CITIVELOEXCELMIN"
    below = _bdays(datetime.date(2018, 3, 5), datetime.date(2018, 3, 16))
    above = _bdays(datetime.date(2025, 3, 3), datetime.date(2025, 3, 14))
    fake_store(
        {asset: {d: 1 for d in below + above}},
        counts={(asset, d): 224 for d in below + above},
    )

    below_plan = D.plan_curve(
        "USD-FEDFUNDS-1D", work_dir=tmp_path,
        start=datetime.date(2018, 3, 5), end=datetime.date(2018, 3, 16),
        chunk_days=30, min_store_curves=600,
    )
    above_plan = D.plan_curve(
        "USD-FEDFUNDS-1D", work_dir=tmp_path,
        start=datetime.date(2025, 3, 3), end=datetime.date(2025, 3, 14),
        chunk_days=30, min_store_curves=600,
    )
    assert below_plan.chunks == [], "sparse-era days must count as done at their own density"
    assert above_plan.chunks, "the same density in the dense era must still be refetched"


def test_a_day_already_on_disk_is_not_refetched(tmp_path, fake_store):
    fake_store({})
    day = datetime.date(2025, 6, 11)
    (tmp_path / "USD-SOFR-1D").mkdir(parents=True)
    for d in _days_in((datetime.date(2025, 6, 9), datetime.date(2025, 6, 13))):
        (tmp_path / "USD-SOFR-1D" / f"{d.isoformat()}.parquet").write_bytes(b"")
    plan = D.plan_curve(
        "USD-SOFR-1D", work_dir=tmp_path,
        start=datetime.date(2025, 6, 9), end=datetime.date(2025, 6, 13), chunk_days=5,
    )
    assert plan.chunks == []
    assert day in {datetime.date.fromisoformat(p.stem)
                   for p in (tmp_path / "USD-SOFR-1D").glob("*.parquet")}


def test_chunks_are_issued_newest_first(tmp_path, fake_store):
    """An interrupted run must leave the RECENT history behind, not a hole."""
    fake_store({})
    plan = D.plan_curve(
        "USD-SOFR-1D", work_dir=tmp_path,
        start=datetime.date(2024, 1, 1), end=datetime.date(2024, 6, 1), chunk_days=30,
    )
    starts = [c[0] for c in plan.chunks]
    assert starts == sorted(starts, reverse=True)


def _days_in(chunk):
    import pandas as pd

    start, end = chunk
    return [d.date() for d in pd.bdate_range(start, end - datetime.timedelta(days=1))]


def _bdays(start, end):
    import pandas as pd

    return [d.date() for d in pd.bdate_range(start, end - datetime.timedelta(days=1))]


# --------------------------------------------------------------------------- #
#                              the verify sampler                              #
# --------------------------------------------------------------------------- #


def test_eras_are_sampled_separately_not_uniformly():
    """A uniform sample over ten years puts almost nothing in the sparse era.

    The eras fail differently - different tenor sets, different discounting - so
    a check that pools them can pass while one whole era is wrong.
    """
    days = [datetime.date(2018, 1, 1) + datetime.timedelta(days=7 * i) for i in range(300)]
    horizon = D.HORIZONS["USD-FEDFUNDS-1D"]
    eras = D._sample_eras(days, horizon, per_era=5)
    assert set(eras) == {"dense", "sparse"}
    assert len(eras["dense"]) == 5 and len(eras["sparse"]) == 5
    assert all(d >= horizon.dense_from for d in eras["dense"])
    assert all(d < horizon.dense_from for d in eras["sparse"])


def test_a_curve_with_no_sparse_era_reports_only_the_dense_one():
    days = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(50)]
    eras = D._sample_eras(days, D.HORIZONS["USD-SOFR-1D"], per_era=3)
    assert set(eras) == {"dense"}


def test_the_sample_spreads_rather_than_clustering():
    days = [datetime.date(2022, 1, 1) + datetime.timedelta(days=i) for i in range(200)]
    picks = D._sample_eras(days, D.HORIZONS["USD-SOFR-1D"], per_era=4)["dense"]
    assert picks == sorted(picks)
    assert len(set(picks)) == 4
    assert (picks[-1] - picks[0]).days > 100


# --------------------------------------------------------------------------- #
#                              the work queue                                  #
# --------------------------------------------------------------------------- #


def _plan(curve, n):
    plan = D.CurvePlan(curve_name=curve, start=datetime.date(2020, 1, 1),
                       end=datetime.date(2026, 1, 1))
    plan.chunks = [
        (datetime.date(2026, 1, 1) - datetime.timedelta(days=60 * (i + 1)),
         datetime.date(2026, 1, 1) - datetime.timedelta(days=60 * i))
        for i in range(n)
    ]
    return plan


def test_the_queue_walks_every_curve_before_deepening_any_of_them():
    """A run cut off early must have covered all five curves, not the first two.

    At ~20 hours with a 13-25 minute Excel restart every five or six chunks, not
    finishing is the case worth designing for - and the request named five
    curves, not the two that happen to sort first.
    """
    plans = {"A": _plan("A", 3), "B": _plan("B", 5), "C": _plan("C", 1)}
    queue = D._work_queue(plans, interleave=True)
    assert [c for c, _, _ in queue[:3]] == ["A", "B", "C"]
    assert [c for c, _, _ in queue[3:5]] == ["A", "B"]
    assert len(queue) == 9


def test_interleaving_can_be_turned_off_and_then_it_is_curve_by_curve():
    plans = {"A": _plan("A", 2), "B": _plan("B", 2)}
    queue = D._work_queue(plans, interleave=False)
    assert [c for c, _, _ in queue] == ["A", "A", "B", "B"]


def test_a_curve_with_nothing_to_do_is_not_in_the_queue():
    plans = {"A": _plan("A", 2), "DONE": _plan("DONE", 0)}
    queue = D._work_queue(plans, interleave=True)
    assert {c for c, _, _ in queue} == {"A"}


def test_every_curve_keeps_its_newest_first_order_inside_the_queue():
    plans = {"A": _plan("A", 4), "B": _plan("B", 4)}
    for curve in ("A", "B"):
        starts = [s for c, s, _ in D._work_queue(plans, interleave=True) if c == curve]
        assert starts == sorted(starts, reverse=True)


# --------------------------------------------------------------------------- #
#                        the BUILD's skip, not the fetch's                     #
# --------------------------------------------------------------------------- #


def test_the_build_rebuilds_a_thin_stored_day(fake_store):
    """``has_day`` is the wrong question, and it fails silently.

    USD-SOFR's 2022-08..2023-12 days ARE in the store - as ten-minute data - so a
    has_day skip leaves the newly fetched minute parquets unsolved on disk and
    the run reports success having changed nothing. The fetch planner already
    makes this distinction; this is the build agreeing with it.
    """
    asset = "USD-SOFR-1D-CITIVELOEXCELMIN"
    thin, dense = datetime.date(2023, 6, 14), datetime.date(2025, 6, 11)
    store = fake_store(
        {asset: {thin: 1, dense: 1}},
        counts={(asset, thin): 132, (asset, dense): 1250},
    )
    assert not D._already_dense(store, asset, thin, "USD-SOFR-1D", 600)
    assert D._already_dense(store, asset, dense, "USD-SOFR-1D", 600)


def test_the_build_does_not_rebuild_a_sparse_era_day_forever(fake_store):
    asset = "USD-FEDFUNDS-1D-CITIVELOEXCELMIN"
    day = datetime.date(2018, 3, 14)
    store = fake_store({asset: {day: 1}}, counts={(asset, day): 224})
    assert D._already_dense(store, asset, day, "USD-FEDFUNDS-1D", 600)


def test_a_day_absent_from_the_store_is_never_dense(fake_store):
    asset = "USD-SOFR-1D-CITIVELOEXCELMIN"
    store = fake_store({asset: {}}, counts={})
    assert not D._already_dense(store, asset, datetime.date(2025, 6, 11), "USD-SOFR-1D", 600)
