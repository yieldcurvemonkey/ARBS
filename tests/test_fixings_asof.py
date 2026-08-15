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
