r"""The convexity adjustment's two legs must be marked at the same instant.

Measured 2026-08-26 (scripts in the audit note, numbers in
``MDP.IRSwaps.CITIVELO_EXCEL.timestamps.EOD_SNAP_TIME`` and
``MDP.STIRFutures.STIRFutureMDP.SETTLE_SOURCE``):

* Citi's ``DAILY`` grid -- the swap leg of ``TB.IRSwapsTB.sfr_cvx_adj`` -- is
  struck at **15:00 New York**, on a New York clock, stable back to 2023;
* Barchart's ``queryeod`` daily ``Close`` is the **CME settle** (13:59:30-14:00
  CT = 15:00 ET);
* but ``BARCHART_STIRF-RL`` resolves a ``date`` to the 1-minute bar nearest 17:00
  ET -- the **Globex close** -- which is what the CA panel used to mark against a
  15:00 curve.

Every test here fails if one of those three facts is quietly undone. They are
written against behaviour, not against the constants: asserting
``EOD_SNAP_TIME == 15:00`` alone would still pass with the writer hardcoding 17.
"""
from __future__ import annotations

import datetime
import sqlite3

import pandas as pd
import pytest

from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import EOD_SNAP_TIME
from MDP.STIRFutures.STIRFutureMDP import (
    CME_SETTLE_HOUR_ET,
    GLOBEX_CLOSE_HOUR_ET,
    GLOBEX_CLOSE_SOURCE,
    SETTLE_SOURCE,
    STIRFutureMDP,
    _as_datetime,
    eod_hour_for_source,
)

NY = "America/New_York"


# ===========================================================================
# The swap leg: the Citi EOD curve's stamp
# ===========================================================================
def test_citivelo_eod_snap_is_the_measured_instant():
    assert EOD_SNAP_TIME == datetime.time(15, 0)


def test_wrap_citivelo_excel_eod_stamps_the_measured_snap(monkeypatch):
    """The served curve must SAY 15:00 -- it is the only provenance a reader gets.

    ``RLIRSwapCurve`` exposes a reference *date*; the instant lives in
    ``meta["timestamp"]`` and in ``curve_id``. A 17:00 stamp there is not a
    cosmetic slip, it is the answer to "against which mark is this curve?" and it
    was two hours late for two years.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP.__new__(IRSwapsMDP)
    mdp.source = "citivelo_excel_rl"
    monkeypatch.setattr(
        IRSwapsMDP, "_citivelo_excel_store_fixings",
        lambda self, **kw: pd.Series(dtype="float64"), raising=True)

    curve = IRSwapsMDP._wrap_citivelo_excel_eod(
        mdp,
        curve_name="USD-SOFR-1D",
        asset="USD-SOFR-1D-CITIVELOEXCEL",
        trading_date=datetime.date(2026, 8, 20),
        rl_curve_handle=object(),
    )
    meta = curve.meta() if callable(getattr(curve, "meta", None)) else curve._meta_data
    stamp = pd.Timestamp(meta["timestamp"])
    assert stamp.hour == 15 and stamp.minute == 0, meta["timestamp"]
    assert stamp.tz is not None and str(stamp.tz) == NY
    assert "T15:00:00" in meta["id"], meta["id"]


def test_warm_writes_the_measured_snap(monkeypatch, tmp_path):
    """The warm and the reader must stamp the same instant.

    They are different code paths (``warm.py`` writes the CurveStore row,
    ``IRSwapsMDP`` stamps the served object) and the repo's recorded failure mode
    is exactly two writers agreeing by coincidence until one is edited.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import warm as W

    day = datetime.date(2026, 8, 20)

    class _Handle:
        nodes = {day: 1.0, datetime.date(2027, 8, 20): 0.96}

    class _RLC:
        rl_pricing_curve = _Handle()
        meta = {"max_reprice_error_bp": 0.0}

    monkeypatch.setattr("MDP.CitiVelocityExcel.curves.rl_builder.build_rl_ois_curve",
                        lambda **kw: _RLC(), raising=True)
    monkeypatch.setattr(W, "_par_frame",
                        lambda citi_index, quotes: pd.DataFrame(
                            {f"t{i}": [0.04] for i in range(30)},
                            index=[pd.Timestamp(day)]), raising=True)

    written = []

    class _Store:
        def has_day(self, asset, day):
            return False

        def write_day(self, asset, day, snapshots, overwrite=False, push_l2=False):
            written.extend(snapshots)

    W.warm_curve("USD-SOFR-1D", quotes=object(), store=_Store(),
                 start=day, end=day, min_tenors=4)

    assert written, "the warm wrote nothing; the stamp assertion below would be vacuous"
    snap = written[0]
    ny_stamp = pd.Timestamp(snap.timestamp_utc).tz_convert(NY)
    assert (ny_stamp.hour, ny_stamp.minute) == (15, 0), ny_stamp
    assert snap.session_minute == 15 * 60, snap.session_minute


# ===========================================================================
# The futures leg: which instant a bare date means
# ===========================================================================
def test_eod_hour_is_per_source_and_the_two_differ():
    assert eod_hour_for_source(SETTLE_SOURCE) == CME_SETTLE_HOUR_ET == 15
    assert eod_hour_for_source(GLOBEX_CLOSE_SOURCE) == GLOBEX_CLOSE_HOUR_ET == 17
    assert eod_hour_for_source("WEBULL_STIRF-RL") == GLOBEX_CLOSE_HOUR_ET


def test_as_datetime_honours_the_requested_eod_hour():
    d = datetime.date(2026, 8, 20)
    assert _as_datetime(d).hour == 17, "the default must stay the historical one"
    assert _as_datetime(d, eod_hour=CME_SETTLE_HOUR_ET).hour == 15


# ---------------------------------------------------------------------------
# A fake Barchart, so the selection rules are testable without the vendor.
# ---------------------------------------------------------------------------
class _FakeFetcher:
    """Records what was asked for and serves a canned frame."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls = []

    def barchart_timeseries_api(self, *, barchart_symbols, start_date, end_date,
                                interval, **kw):
        self.calls.append({"interval": interval, "symbols": list(barchart_symbols),
                           "start": start_date, "end": end_date})
        return self.frame.copy()

    def close(self):
        pass


def _mdp_with(monkeypatch, source: str, frame: pd.DataFrame):
    mdp = STIRFutureMDP(source=source)
    fake = _FakeFetcher(frame)
    monkeypatch.setattr(STIRFutureMDP, "_get_barchart_fetcher",
                        lambda self, **kw: fake, raising=True)
    monkeypatch.setattr(STIRFutureMDP, "_fetch_barchart_eod_oi",
                        lambda self, *a, **kw: pd.DataFrame(), raising=True)
    monkeypatch.setattr(STIRFutureMDP, "_ensure_pricer_cache",
                        lambda self: None, raising=True)
    monkeypatch.setattr(STIRFutureMDP, "_threadsafe_cache_get",
                        lambda self, key: None, raising=True)
    written = {}
    monkeypatch.setattr(STIRFutureMDP, "_threadsafe_cache_put",
                        lambda self, key, value: written.__setitem__(key, value),
                        raising=True)
    # The pricer construction needs fixings and a curve; the selection rules under
    # test are upstream of it, so the args dict IS the answer here.
    monkeypatch.setattr(STIRFutureMDP, "_build_pricer_from_args",
                        lambda self, args, fixings_memo=None: args, raising=True)
    return mdp, fake, written


def _daily_frame(dates, price_by_date, column="SQU26"):
    return pd.DataFrame({column: [price_by_date.get(d) for d in dates]},
                        index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]))


DAY = datetime.date(2026, 8, 20)


def test_settle_source_asks_the_vendor_for_daily_bars(monkeypatch):
    """The whole defect in one line: an EOD request used to fetch ``interval=1``.

    ``_fetch_barchart_timeseries`` took ``interval=None`` to mean "EOD" and then
    called the vendor with ``interval=1`` regardless, so the caller picked a
    MINUTE bar nearest 17:00 and called it a settle.
    """
    frame = _daily_frame([DAY], {DAY: 96.2125})
    mdp, fake, _ = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)

    out = mdp.get_data({"symbols": ["SR3U26"], "timestamp": DAY})

    assert fake.calls, "no vendor call was made"
    assert fake.calls[0]["interval"] is None, (
        "the settle path must reach the DAILY endpoint; interval=1 is the "
        "Globex-close bug this source exists to fix")
    assert out["SR3U26"][0]["price"] == pytest.approx(96.2125)


def test_globex_source_still_asks_for_minute_bars(monkeypatch):
    """The old source must be byte-for-byte unchanged -- its cache is keyed on it."""
    idx = pd.DatetimeIndex([pd.Timestamp("2026-08-20 15:59", tz="America/Chicago")])
    frame = pd.DataFrame({"SQU26": [96.19]}, index=idx)
    mdp, fake, _ = _mdp_with(monkeypatch, GLOBEX_CLOSE_SOURCE, frame)

    out = mdp.get_data({"symbols": ["SR3U26"], "timestamp": DAY})

    assert fake.calls[0]["interval"] == 1
    assert out["SR3U26"][0]["price"] == pytest.approx(96.19)


def test_settle_source_keys_the_row_at_15_00_new_york(monkeypatch):
    frame = _daily_frame([DAY], {DAY: 96.2125})
    mdp, _, written = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)
    mdp.get_data({"symbols": ["SR3U26"], "timestamp": DAY})

    keys = [k for k in written if k.endswith(f"-{SETTLE_SOURCE}")]
    assert any("2026-08-20T15:00:00-04:00" in k for k in keys), keys
    assert not any("T17:00:00" in k for k in keys), keys


def test_settle_source_matches_the_date_and_never_the_neighbour(monkeypatch):
    """A missing settle must be ABSENT, not the adjacent session's.

    ``get_indexer(method="nearest")`` is right for a minute tape and catastrophic
    for a daily one: half of its answers come from the FUTURE.
    """
    before, after = datetime.date(2026, 8, 19), datetime.date(2026, 8, 21)
    frame = _daily_frame([before, after], {before: 96.10, after: 96.30})
    mdp, _, _ = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)

    out = mdp.get_data({"symbols": ["SR3U26"], "timestamp": DAY})
    assert not out.get("SR3U26"), (
        f"served {out!r} for a date with no settle -- that is the neighbouring "
        "session's price, and 96.30 is tomorrow's")


def test_settle_source_does_not_fill_an_absent_settle(monkeypatch):
    """No ffill/bfill on the settle path: bfill is look-ahead inside the price."""
    before = datetime.date(2026, 8, 19)
    frame = _daily_frame([before, DAY], {before: 96.10, DAY: None})
    mdp, _, _ = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)

    out = mdp.get_data({"symbols": ["SR3U26"], "timestamp": DAY})
    assert not out.get("SR3U26"), f"a NaN settle was filled from a neighbour: {out!r}"


def test_settle_source_refuses_an_instant(monkeypatch):
    frame = _daily_frame([DAY], {DAY: 96.2125})
    mdp, _, _ = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)
    with pytest.raises(ValueError, match="SETTLEMENT source"):
        mdp.get_data({"symbols": ["SR3U26"],
                      "timestamp": datetime.datetime(2026, 8, 20, 10, 30)})


def test_settle_source_refuses_a_primed_minute_session(monkeypatch):
    frame = _daily_frame([DAY], {DAY: 96.2125})
    mdp, _, _ = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)
    with pytest.raises(ValueError, match="minute session tape"):
        mdp.bulk_get_data(timestamps=[DAY], symbols=["SR3U26"],
                          primed_session_data={"x": pd.DataFrame()})


def test_warm_settles_is_refused_on_a_minute_source():
    mdp = STIRFutureMDP(source=GLOBEX_CLOSE_SOURCE)
    with pytest.raises(ValueError, match="warm_settles"):
        mdp.warm_settles(["SR3U26"], DAY, DAY)


# ===========================================================================
# The guard, and the universe scanner that has to agree with it
# ===========================================================================
def test_assert_settle_source_accepts_the_settle_and_rejects_the_close():
    from RVUtils.ConvexityRV.strat2_sofr_convexity import assert_settle_source

    assert assert_settle_source(SETTLE_SOURCE) == SETTLE_SOURCE
    with pytest.raises(ValueError, match="GLOBEX"):
        assert_settle_source(GLOBEX_CLOSE_SOURCE)
    with pytest.raises(ValueError, match="intraday"):
        assert_settle_source("BARCHART_TOS_LIVE_STIRF-RL")
    # deliberate reproduction of an old panel stays possible, and only that
    assert assert_settle_source(GLOBEX_CLOSE_SOURCE,
                                allow_globex_close=True) == GLOBEX_CLOSE_SOURCE
    with pytest.raises(ValueError, match="intraday"):
        assert_settle_source("BARCHART_TOS_LIVE_STIRF-RL", allow_globex_close=True)


def test_shipped_ca_configs_default_to_the_settle_source():
    from RVUtils.ConvexityRV.strat2_q20 import EOD_SOURCE, Q20Config
    from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config

    assert Strat2Config().futures_source == SETTLE_SOURCE
    assert EOD_SOURCE == SETTLE_SOURCE and Q20Config().eod_source == SETTLE_SOURCE
    # ...and the Q20 CURVE plumbing keeps its own token: IRSwapsMDP has no
    # dispatch for the settle source, so fusing the two strings breaks the build.
    assert Q20Config().curve_source == GLOBEX_CLOSE_SOURCE


def _write_shard(tmp_path, keys):
    shard = tmp_path / "000"
    shard.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(shard / "cache.db")
    con.execute("CREATE TABLE IF NOT EXISTS Cache (rowid INTEGER PRIMARY KEY, key TEXT)")
    con.executemany("INSERT INTO Cache (key) VALUES (?)", [(k,) for k in keys])
    con.commit()
    con.close()


@pytest.mark.parametrize("hour,source,expect_seen", [
    (15, SETTLE_SOURCE, True),
    (17, SETTLE_SOURCE, False),
])
def test_universe_scanner_reads_the_source_own_hour(tmp_path, hour, source, expect_seen):
    """A scanner left at 17:00 reports depth 0 and sends an idempotent warm to the vendor."""
    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence
    from RVUtils.ConvexityRV.strat2_sofr_convexity import (
        Strat2Config, futures_symbol, local_strip_depths, ny_utc_offset)

    day = datetime.date(2026, 7, 8)
    _write_shard(tmp_path, [
        f"{day.isoformat()}T{hour:02d}:00:00{ny_utc_offset(day)}-{futures_symbol(y, m)}-{source}"
        for y, m in quarterly_imm_sequence(day, 6)])

    cfg = Strat2Config(start=day, end=day, futures_source=source)
    depths = local_strip_depths(cfg, cache_root=str(tmp_path))
    assert (depths.get(day, 0) >= 6) is expect_seen, depths


def test_warm_settles_writes_the_key_the_read_path_probes(monkeypatch):
    """The warm and the reader must agree about the key SHAPE, not just the hour.

    ``warm_settles`` builds ``{iso}-{TICKER}-{SOURCE}`` and ``get_data`` probes a
    list of candidate spellings; they agree by parallel construction, which is
    exactly the failure this repo has recorded twice -- a warm reporting thousands
    of successful writes and recovering nothing. Only a round trip catches it, so
    the read below is run with the vendor removed entirely: any cache miss becomes
    an AssertionError instead of a silent refetch.
    """
    before = datetime.date(2026, 8, 19)
    frame = _daily_frame([before, DAY], {before: 96.10, DAY: 96.2125})
    mdp, _, written = _mdp_with(monkeypatch, SETTLE_SOURCE, frame)

    n = mdp.warm_settles(["SR3U26"], before, DAY)
    assert n == {"SR3U26": 2}, n

    monkeypatch.setattr(STIRFutureMDP, "_threadsafe_cache_get",
                        lambda self, key: written.get(key), raising=True)

    def _no_vendor(self, **kw):
        raise AssertionError(
            "the read reached the vendor: the warm's key shape and the read's "
            "candidate keys disagree")

    monkeypatch.setattr(STIRFutureMDP, "_get_barchart_fetcher", _no_vendor, raising=True)

    out = mdp.get_data({"symbols": ["SR3U26"], "timestamp": DAY})
    assert out["SR3U26"][0]["price"] == pytest.approx(96.2125)
