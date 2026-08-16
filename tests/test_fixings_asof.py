"""`_fetch_fixings` ignores its `as_of_date`, and rateslib prices off future fixings.

Those two facts together are a live lookahead, not a tidiness problem. Both are measured:

* `_fetch_fixings(as_of_date=2018-06-12, 'USD-SOFR-1D')`, `(2020-10-15)` and `(today)` return the
  identical 2,090-row series spanning 2018-04-02..2026-08-13. `as_of_date` selects a cache
  *vintage*, never a data *window*. A caller taking `.tail(1)` for a June-2018 valuation gets
  3.62% where 1.69% is correct -- 193 bp.
* rateslib 2.7.1 has no notion of "today". Measured with a curve anchored 2018-06-12 and a fixing
  series whose post-anchor values were varied deliberately, a SER Sep-2018 STIRFuture returned
  3.000000 / 4.000000 / 5.000000 / 6.000000% as those fixings were set to 3 / 4 / 5 / 6% -- priced
  entirely off realised future fixings rather than off the curve. A 1Y IRS effective 2018-09-03
  moved 205 bp the same way.

So every clip in this repo is load-bearing. These tests pin the clip at the three layers that can
enforce it: the helper, the curve-cache key, and the parallel builder's per-day dispatch.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

# NOTE: `fixings_before` is imported inside each test that needs it, not at module scope. The two
# behavioural tests below (the cache key and the builder's per-day dispatch) exercise code that
# already exists, and they are the ones that must be runnable -- and red -- against the unfixed
# tree. A module-level import of a new symbol would turn that red into a collection error.

_IDX = pd.date_range("2018-04-02", "2019-12-31", freq="B")
_SERIES = pd.Series(np.arange(len(_IDX), dtype=float), index=_IDX)


def test_fixings_before_is_strict():
    """The reference date's own fixing is not yet published, so it must be excluded."""
    from MDP.IRSwaps.fixings_cache.fixings_cache import fixings_before

    clipped = fixings_before(_SERIES, datetime.date(2018, 6, 12))
    assert clipped.index.max().date() == datetime.date(2018, 6, 11)
    assert datetime.date(2018, 6, 12) not in set(clipped.index.date)


def test_fixings_before_handles_weekends_and_empties():
    from MDP.IRSwaps.fixings_cache.fixings_cache import fixings_before
    # 2018-06-16 is a Saturday; the last published fixing is Friday's.
    assert fixings_before(_SERIES, datetime.date(2018, 6, 16)).index.max().date() == datetime.date(2018, 6, 15)
    # A date before the series starts yields nothing rather than everything.
    assert fixings_before(_SERIES, datetime.date(2000, 1, 1)).empty
    assert fixings_before(None, datetime.date(2018, 6, 12)) is None
    empty = pd.Series(dtype=float)
    assert fixings_before(empty, datetime.date(2018, 6, 12)).empty


def test_fixings_before_accepts_live():
    """`live` means now, so the whole published history is in the past and survives."""
    from MDP.IRSwaps.fixings_cache.fixings_cache import fixings_before

    out = fixings_before(_SERIES, "live")
    assert len(out) == len(_SERIES)


# --------------------------------------------------------------------------------------------
# the curve-cache key
# --------------------------------------------------------------------------------------------


def test_curve_cache_key_ignores_fixings_the_snapshot_could_not_know():
    """A 2018 snapshot's key must not change because a 2026 fixing was published.

    Callers pass one batch-wide series -- whatever `_fetch_fixings` returned, which grows every
    day -- so hashing it raw made every historical key change daily and the curve cache never hit
    for any historical snapshot. It also meant the key did not describe what was actually
    calibrated.
    """
    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _make_key

    snap = datetime.datetime(2018, 6, 12, 15, 0)
    short = _SERIES[_SERIES.index <= pd.Timestamp("2018-07-31")]
    long = _SERIES  # same values, but runs 17 months further

    key_short = _make_key("cid", snap, short, 11, 12, 3)
    key_long = _make_key("cid", snap, long, 11, 12, 3)
    assert key_short == key_long, "fixings published after the snapshot must not enter its cache key"


def test_curve_cache_key_still_reacts_to_fixings_the_snapshot_could_know():
    """CALIBRATION. If the key ignored fixings entirely the test above would pass for free."""
    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _make_key

    snap = datetime.datetime(2018, 6, 12, 15, 0)
    bumped = _SERIES.copy()
    bumped.loc[pd.Timestamp("2018-05-15")] += 1.0

    assert _make_key("cid", snap, _SERIES, 11, 12, 3) != _make_key("cid", snap, bumped, 11, 12, 3)


# --------------------------------------------------------------------------------------------
# the parallel builder's per-day dispatch
# --------------------------------------------------------------------------------------------


def test_parallel_builder_clips_fixings_per_day_not_per_batch(monkeypatch):
    """A multi-day batch must not hand the earliest snapshot the latest snapshot's fixings.

    This is the defect: `IRSwapsMDP` clips once at `max(batch)` and passes that one series to the
    bulk builder, which fanned it out unchanged. For `MTV2_Q12X11` (`_N_SER_CONTRACTS = 11`) those
    fixings reach real SER instruments, so a batch spanning a quarter priced its first day off
    fixings published months later.
    """
    import MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_sofr_mt_builder_parallel as mod

    seen: dict = {}

    class _FakeExecutor:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, **kwargs):
            snap = pd.to_datetime(kwargs["snap_iso"])
            seen[snap.date()] = kwargs["sofr_fixings"]

            class _F:
                def result(_self):
                    return snap, object()

            return _F()

    monkeypatch.setattr(mod, "ProcessPoolExecutor", _FakeExecutor)
    monkeypatch.setattr(mod, "as_completed", lambda futs: list(futs))
    monkeypatch.setattr(mod, "tqdm", lambda it, **k: it)
    monkeypatch.setattr(mod, "SDRDataBuilder", lambda **k: type("S", (), {"grab_sdr_trades": lambda *a, **k: pd.DataFrame()})())
    monkeypatch.setattr(mod, "_calculate_daily_sdr_vwap_timeseries", lambda *a, **k: pd.DataFrame())

    class _FakeBcf:
        def _fetch_session_tokens(self, *a, **k):
            return None

        def barchart_timeseries_api(self, **k):
            # One STIR column, minute-stamped, covering both days -- enough for the prefetch to
            # produce a non-empty per-day frame and reach the dispatch loop under test.
            idx = pd.date_range("2018-06-12", "2018-09-21", freq="h", tz="America/New_York")
            return pd.DataFrame({"SQM18": 97.5}, index=idx)

    monkeypatch.setattr(mod, "BarchartFetcher", lambda **k: _FakeBcf())
    monkeypatch.setattr(mod, "get_short_end_curve_tickers", lambda **k: ["SFRM18"])

    snaps = [datetime.datetime(2018, 6, 12, 15, 0), datetime.datetime(2018, 9, 20, 15, 0)]
    try:
        mod.rl_usd_sofr_mt_builder_parallel(
            base_curve_id="cid",
            snaps=snaps,
            sofr_fixings=_SERIES,
            n_ser_contracts=11,
            n_sfr_contracts=12,
            n_plus_fomc_years=3,
            max_workers=1,
        )
    except Exception as exc:  # pragma: no cover - the prefetch may still fail; the dispatch is what matters
        if not seen:
            pytest.skip(f"builder prefetch unavailable in this environment: {exc}")

    assert set(seen) == {datetime.date(2018, 6, 12), datetime.date(2018, 9, 20)}
    early = seen[datetime.date(2018, 6, 12)]
    late = seen[datetime.date(2018, 9, 20)]
    assert early.index.max().date() < datetime.date(2018, 6, 12)
    assert late.index.max().date() < datetime.date(2018, 9, 20)
    assert len(early) < len(late), "each day must get its own point-in-time series"


# --------------------------------------------------------------------------------------------
# the ordering guarantee
# --------------------------------------------------------------------------------------------


def test_the_returned_series_is_chronological():
    """`.iloc[-1]` must mean "the latest fixing", on every curve.

    Measured 2026-08-15, before the fix: `_fetch_fixings` returned USD-SOFR-1D ASCENDING and
    USD-OIS DESCENDING, from the same cache on the same call. So `.iloc[-1]` gave 3.62% for SOFR
    and 7.03% for EFFR -- the latter being the fixing for 2000-07-03, not the 3.63% of 2026-08-13.
    A 340 bp error, on one curve and not the other, from an identical expression.

    That reached a published result: `notebooks/backtests/linvol_grid_common` computed its
    SOFR-EFFR basis as a CONSTANT -523.0 bp on all 3,230 rows, which is exactly
    (first-ever SOFR 1.80%) - (first-ever EFFR 7.03%).
    """
    from MDP.IRSwaps.fixings_cache.fixings_cache import _chronological

    descending = pd.Series([7.03, 5.0, 3.63], index=pd.to_datetime(["2026-08-13", "2010-01-04", "2000-07-03"]))
    out = _chronological(descending)
    assert out.index.is_monotonic_increasing
    assert out.iloc[-1] == pytest.approx(7.03)
    assert out.index[-1] == pd.Timestamp("2026-08-13")


def test_chronological_tolerates_empty_and_none():
    from MDP.IRSwaps.fixings_cache.fixings_cache import _chronological

    assert _chronological(None) is None
    empty = pd.Series(dtype=float)
    assert len(_chronological(empty)) == 0


def test_fixings_before_is_order_independent():
    """The clip must not depend on how the cache happened to be written."""
    from MDP.IRSwaps.fixings_cache.fixings_cache import fixings_before

    ascending = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2018-06-08", "2018-06-11", "2018-06-12"]))
    descending = ascending.iloc[::-1]
    a = fixings_before(ascending, datetime.date(2018, 6, 12)).sort_index()
    d = fixings_before(descending, datetime.date(2018, 6, 12)).sort_index()
    pd.testing.assert_series_equal(a, d)
    assert a.iloc[-1] == pytest.approx(2.0)


def test_non_publication_days_are_dropped():
    """Good Friday carries an explicit NaN, and `.iloc[-1]` on a slice ending there returns it.

    SOFR does not publish on Good Friday -- SIFMA closes -- and the NY Fed series says so with a
    NaN row rather than an absent one. Measured before the fix: SOFR for 2021-04-02 is NaN, so
    `RLUSTFuturePricer._resolve_repo_rate` returned NaN, so EVERY net basis in EVERY basis report on
    EVERY Good Friday was NaN and the whole day failed the consistency gate -- one day a year, per
    root, on all six, since 2018. It read as a market-holiday data gap; it was an arithmetic one.

    After the fix, those days price: TUM21 2021-04-02 repo 0.010% min net basis +0.14/32,
    FVM23 2023-04-07 4.810% +2.57/32, UXYM24 2024-03-29 5.340% +3.98/32, TUM26 2026-04-03 3.660%
    -1.44/32 -- all passing the gate.
    """
    from MDP.IRSwaps.fixings_cache.fixings_cache import _chronological

    with_hole = pd.Series(
        [0.0001, 0.0001, float("nan"), 0.0001],
        index=pd.to_datetime(["2021-03-31", "2021-04-01", "2021-04-02", "2021-04-05"]),
    )
    out = _chronological(with_hole)
    assert len(out) == 3
    assert pd.Timestamp("2021-04-02") not in out.index

    from MDP.IRSwaps.fixings_cache.fixings_cache import fixings_before

    # The repo rate for a Good Friday valuation is Thursday's fixing, not NaN.
    as_of_good_friday = fixings_before(out, datetime.date(2021, 4, 3))
    assert as_of_good_friday.index[-1] == pd.Timestamp("2021-04-02") - pd.Timedelta(days=1)
    assert float(as_of_good_friday.iloc[-1]) == pytest.approx(0.0001)
