"""Tests for the 2026-08-19 CA coverage repair.

The convexity-adjustment series was sparse from ~May-2024 onward and every chart
drew a straight line through the hole. Two independent causes, and this file
pins the fixes for both plus the guards that stop them regressing:

**Cause A -- all-or-nothing date gating (code, free to fix).** A date entered the
universe only if its contiguous strip reached the depth the DEEPEST requested
pack needed, so a date holding four good front settles was discarded for *every*
rank. Measured cost: 2024 fell from 252 rank-1-quotable dates to 19; 2025 from
198 to 2; 2026 from 37 to 3.

**Cause B -- genuinely absent deferred settles (needs a fetch).** Not testable
offline and not tested here; ``scripts/warm_sr3_deferred.py`` owns it.

Plus two defects found while repairing the first:

**The universe counted keys the fetcher cannot read.** 17:00 keys stamped in the
wrong UTC offset match the key regex but miss on lookup. 51 dates scanned deeper
than they resolve -- 2026-07-09 scanned at 12 and resolves at 0.

**Un-trimming makes a latent statistics bug live.** ``rolling(252)`` counts rows,
so a "1Y" z-score could span 1,289 calendar days. That was invisible only because
``trim_to_contiguous_run`` deleted the gappy tail first.

Style follows ``test_convexity_rv_strat2_q20``: pure-logic tests always run;
data-dependent ones skip explicitly when the local store or the built panel is
absent, and assert ``network_calls_blocked()`` did not move.

MUTATION-CHECKED, 13/13 caught (2026-08-19). Each mutation below was applied to
the SOURCE, the named test was run and confirmed to FAIL, and the file was
restored byte-for-byte. Two guards on the harness itself, because a checker that
is wrong reports success and hides the thing it was built to find: a control run
with no mutation must be green first, and every mutated source is `compile()`d
before the test runs -- a mutation that does not parse makes pytest report a
collection error, which would otherwise score as a false "killed".

===================================================  ==================================
mutation                                              test that caught it
===================================================  ==================================
``min_strip_depth`` 4 -> 12                           ``..._admits_a_four_contract_date``
``depth >= floor`` -> ``instrument_count(..) >= 12``  ``..._admits_a_four_contract_date``
``_tz_readable`` always returns True                  ``..._ignores_a_key_in_the_wrong_offset``
``min_priced_contracts`` floor -> old expression      ``..._four_settles_still_yield_rank_1``
floor counts ``len(prices)``, not the contiguous run  ``..._four_settles_still_yield_rank_1``
``day_rows`` re-raises the Q20 build failure          ``..._degrades_to_settle_rows``
``ca_bp`` falls back to settle when q20 is absent     ``..._never_substitutes_one_source``
``keep="latest"`` returns the longest run             ``..._latest_keeps_the_recent_run``
``window_span_ok`` returns all-True                   ``..._masks_a_window_that_bridges``
``_apply_span_mask`` is a no-op                       ``..._works_on_a_multi_pack_panel``
``assert_settle_source`` returns without checking     ``..._rejects_the_live_quote_source``
``cache_only`` stops patching httpx                   ``..._blocks_httpx_directly``
``coverage_by_run`` collapses every run into one      ``..._reports_both_sides_of_the_hole``
===================================================  ==================================
"""
from __future__ import annotations

import datetime
import os
import pathlib
import sqlite3

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat2_q20 as Q
from RVUtils.ConvexityRV import strat2_sofr_convexity as S2
from RVUtils.ConvexityRV.listed_cache_guard import (
    CacheMissOffline, cache_only, network_calls_blocked)
from RVUtils.ConvexityRV.packs import quarterly_imm_sequence

_REPO = pathlib.Path(__file__).resolve().parents[1]
_DATA = _REPO / "notebooks" / "data" / "convexity_rv"
_PANEL = _DATA / "strat2_q20_panel.parquet"

needs_panel = pytest.mark.skipif(not _PANEL.exists(), reason="panel not built")
needs_cache = pytest.mark.skipif(
    not pathlib.Path(Q._default_cache_root()).exists(), reason="no local SR3 cache")


# ===========================================================================
# A synthetic diskcache, so the universe logic is testable without the store
# ===========================================================================
def _fake_cache(root: pathlib.Path, keys) -> pathlib.Path:
    """Write a one-shard diskcache whose ``Cache`` table holds *keys*."""
    shard = root / "000"
    shard.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(shard / "cache.db")
    con.execute("CREATE TABLE Cache (rowid INTEGER PRIMARY KEY, key TEXT)")
    con.executemany("INSERT INTO Cache (key) VALUES (?)", [(k,) for k in keys])
    con.commit()
    con.close()
    return root


def _a_priced_date(cfg):
    """A real (date, depth) the built panel already prices.

    Picking any deep date off the scan is not enough: US market holidays carry an
    SR3 EOD key while the swap store serves the previous close, and ``day_rows``
    correctly refuses those. The panel is the record of which dates cleared that.
    """
    if not _PANEL.exists():
        pytest.skip("panel not built")
    p = pd.read_parquet(_PANEL, columns=["date", "strip_depth"])
    p = p[p["strip_depth"] >= 12]
    if p.empty:
        pytest.skip("no deep dates in the panel")
    row = p.sort_values("date").iloc[len(p) // 2]
    return pd.Timestamp(row["date"]).date(), int(row["strip_depth"])


def _strip_keys(as_of: datetime.date, n: int, *, source=Q.EOD_SOURCE,
                tz=None, time="17:00:00"):
    """17:00 EOD keys for the front *n* quarterly SR3 contracts on *as_of*."""
    tz = S2.ny_utc_offset(as_of) if tz is None else tz
    return [f"{as_of.isoformat()}T{time}{tz}-{S2.futures_symbol(y, m)}-{source}"
            for y, m in quarterly_imm_sequence(as_of, n)]


# ===========================================================================
# Cause A: a four-contract date is a rank-1 date
# ===========================================================================
def test_strip_depth_admits_a_four_contract_date(tmp_path):
    """THE regression test for the whole defect.

    A date holding exactly four contiguous settles can quote pack window 1 and
    nothing else. It must appear in the universe at depth 4. Under the shipped
    rule (``instrument_count(date, depth) >= min_instruments`` with a floor of
    12) it appeared nowhere at all, and 2024 lost 233 of its 252 rank-1 dates to
    that one line.
    """
    d = datetime.date(2025, 6, 3)
    root = _fake_cache(tmp_path, _strip_keys(d, 4))
    depths = Q.strip_depth_by_date(Q.Q20Config(), cache_root=str(root))

    assert depths == {d: 4}, depths
    assert Q.max_rank_for_depth(depths[d]) == 1, "four contracts is exactly one pack"


def test_strip_depth_still_refuses_a_three_contract_date(tmp_path):
    """The floor is 4 because a pack IS four contracts -- not because 4 is small.

    Without this the "admit everything" reading of the fix would let in dates
    that cannot produce a single row, and the panel builder would pay for them.
    """
    d = datetime.date(2025, 6, 3)
    root = _fake_cache(tmp_path, _strip_keys(d, 3))
    assert Q.strip_depth_by_date(Q.Q20Config(), cache_root=str(root)) == {}
    # ...but a warm, whose whole job is to find shallow dates, must still see it.
    assert Q.strip_depth_by_date(Q.Q20Config(), cache_root=str(root),
                                 min_depth=1) == {d: 3}


def test_depth_is_contiguous_not_a_count(tmp_path):
    """A hole at rank 3 caps the strip at 2 however many later contracts exist.

    A pack is four CONSECUTIVE contracts, so "9 of the first 12 present" would
    overstate what is quotable.
    """
    d = datetime.date(2025, 6, 3)
    keys = _strip_keys(d, 12)
    del keys[2]                                      # punch out the 3rd contract
    root = _fake_cache(tmp_path, keys)
    assert Q.strip_depth_by_date(Q.Q20Config(), cache_root=str(root),
                                 min_depth=1) == {d: 2}


def test_universe_ignores_a_key_in_the_wrong_offset(tmp_path):
    """A 17:00 key stamped ``+00:00`` matches the regex and resolves to nothing.

    The store holds 1,061 such keys. Counting them inflated the universe with 51
    dates that then missed inside ``cache_only()`` and reached for the vendor --
    2026-07-09 scanned at depth 12 and resolves at 0.
    """
    d = datetime.date(2025, 6, 3)                    # EDT, so New York is -04:00
    assert S2.ny_utc_offset(d) == "-04:00"
    assert S2.ny_utc_offset(datetime.date(2025, 12, 3)) == "-05:00", "DST flip"

    keys = _strip_keys(d, 4) + _strip_keys(d, 8, tz="+00:00")[4:]
    root = _fake_cache(tmp_path, keys)
    depths = Q.strip_depth_by_date(Q.Q20Config(), cache_root=str(root))
    assert depths == {d: 4}, "the +00:00 keys must not extend the strip"


def test_local_cached_dates_strict_default_and_permissive_option(tmp_path):
    """``local_cached_dates`` keeps its all-or-nothing default; the depth-aware
    universe is opt-in, and ``local_strip_depths`` is the form new code wants."""
    d1, d2 = datetime.date(2025, 6, 3), datetime.date(2025, 6, 4)
    root = _fake_cache(tmp_path, _strip_keys(d1, 13) + _strip_keys(d2, 5))
    cfg = S2.Strat2Config(start=datetime.date(2025, 1, 1),
                          end=datetime.date(2025, 12, 31))

    assert S2.local_cached_dates(cfg, cache_root=str(root)) == [d1]
    assert S2.local_cached_dates(cfg, cache_root=str(root), min_contracts=4) == [d1, d2]
    assert S2.local_strip_depths(cfg, cache_root=str(root)) == {d1: 13, d2: 5}


# ===========================================================================
# Cause A, near-pack route: build_panel must price what the date supports
# ===========================================================================
class _FakePricer:
    """A swap curve whose matched forward rate is a constant 4.00%."""

    _rl_curve_handle = None

    def __init__(self, as_of):
        self._d = as_of

    def reference_date(self):
        return self._d

    def _curve_definition(self):
        return {"ReferenceRate": "usd_irs"}


class _FakeQuote:
    def __init__(self, px):
        self._px = px

    def price(self):
        return self._px


class _FakeFuturesMDP:
    """Resolves only the first ``n`` requested symbols -- a cold deferred end."""

    def __init__(self, n):
        self.n = n

    def get_data(self, req):
        syms = list(req["symbols"])
        return {s: [_FakeQuote(100.0 - (4.0 + 0.01 * i))]
                for i, s in enumerate(syms[:self.n])}


class _FakeSwapsMDP:
    def get_pricer(self, req):
        return _FakePricer(req["timestamp"])


def test_build_panel_four_settles_still_yield_rank_1(monkeypatch):
    """A date resolving four contracts of a thirteen-contract request yields the
    rank-1 pack, not nothing.

    ``build_panel`` demanded ``rank_start + n_packs + 2`` = 13 resolved contracts
    before it would keep ANY pack. ``ca_snapshot`` already skips the windows it
    cannot quote, so that test bought no correctness -- it only threw away the
    front packs of every date whose deferred end was cold.
    """
    monkeypatch.setattr(S2, "_swap_par_rate", lambda *a, **k: 4.00)
    cfg = S2.Strat2Config()
    assert cfg.n_contracts == 13 and cfg.min_priced_contracts == 4

    panel, rates = S2.build_panel(
        [datetime.date(2025, 6, 3)], cfg, futures_mdp=_FakeFuturesMDP(4),
        swaps_mdp=_FakeSwapsMDP(), progress=False)

    assert len(panel) == 1, f"expected exactly the rank-1 pack, got\n{panel}"
    assert int(panel["rank"].iloc[0]) == 1
    assert int(panel["strip_depth"].iloc[0]) == 4
    assert int(panel["max_rank_available"].iloc[0]) == 1
    assert np.isfinite(panel["ca_bp"].iloc[0])
    assert len(rates) == 1


def test_build_panel_records_what_a_date_could_not_do(monkeypatch):
    """Sparsity has to arrive as DATA, not as absence -- a downstream chart can
    only draw an honest hole if it can see how deep each date was."""
    monkeypatch.setattr(S2, "_swap_par_rate", lambda *a, **k: 4.00)
    cfg = S2.Strat2Config()
    panel, _ = S2.build_panel(
        [datetime.date(2025, 6, 3)], cfg, futures_mdp=_FakeFuturesMDP(8),
        swaps_mdp=_FakeSwapsMDP(), progress=False)

    assert set(panel["rank"]) == {1, 2, 3, 4, 5}, "8 contracts is 5 windows"
    for c in ("n_priced", "strip_depth", "max_rank_available"):
        assert c in panel.columns, c
    assert (panel["max_rank_available"] == 5).all()
    assert panel["rank"].max() <= panel["max_rank_available"].max()


def test_build_panel_still_refuses_a_date_that_cannot_quote_a_pack(monkeypatch):
    monkeypatch.setattr(S2, "_swap_par_rate", lambda *a, **k: 4.00)
    panel, _ = S2.build_panel(
        [datetime.date(2025, 6, 3)], S2.Strat2Config(),
        futures_mdp=_FakeFuturesMDP(3), swaps_mdp=_FakeSwapsMDP(), progress=False)
    assert panel.empty


# ===========================================================================
# The settle source can never be a live quote
# ===========================================================================
def test_config_rejects_the_live_quote_source():
    """A live intraday quote standing in for a settlement mark is a correctness
    bug, not a coverage trade-off: it re-times one leg of a difference whose
    whole magnitude is a few bp. Refused by name, in both configs.

    It buys nothing either: measured over the whole 12.7M-key local slice,
    ``BARCHART_TOS_LIVE_STIRF-RL`` reaches contiguous depth 20 on zero dates in
    every year 2018-2026.
    """
    assert S2.LIVE_SOURCE == "BARCHART_TOS_LIVE_STIRF-RL"
    for src in (S2.LIVE_SOURCE, "SOMETHING_INTRADAY", "barchart_tos_live_stirf-rl"):
        with pytest.raises(ValueError, match="intraday quote feed"):
            S2.Strat2Config(futures_source=src)
        with pytest.raises(ValueError, match="intraday quote feed"):
            Q.Q20Config(eod_source=src)

    # The settle source is accepted and returned unchanged.
    assert S2.assert_settle_source(Q.EOD_SOURCE) == Q.EOD_SOURCE
    assert S2.Strat2Config().futures_source == "BARCHART_STIRF-RL"
    assert Q.Q20Config().eod_source == "BARCHART_STIRF-RL"


@needs_panel
def test_panel_is_marked_off_settles_only():
    """The empirical half: no row of the built panel may claim a rank its own
    recorded strip depth cannot cover. A live quote could only ever enter by
    supplying a contract the settle source lacks, which would show up here."""
    p = pd.read_parquet(_PANEL)
    if "max_rank_available" not in p.columns:
        pytest.skip("panel predates the availability columns")
    assert (p["rank"] <= p["max_rank_available"]).all()
    assert (p["strip_depth"] >= p["rank"] + 3).all()


# ===========================================================================
# day_rows degrades rather than dropping the date
# ===========================================================================
@needs_cache
def test_day_rows_degrades_to_settle_rows_when_the_curve_will_not_build(monkeypatch):
    """A Q20 build failure must cost the date its q20 columns and nothing else.

    Before the repair it cost the whole date, settles included -- which is how a
    date with perfectly good settles became a hole that every chart then drew a
    straight line across.
    """
    cfg = Q.Q20Config()
    d, depth = _a_priced_date(cfg)

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    s2 = Q.deep_pack_config(rank_start=5, n_packs=13)
    builder = Q.Q20Builder(cfg)
    pricer = IRSwapsMDP(source=cfg.swap_source).get_pricer(
        {"curve_name": cfg.swap_curve, "timestamp": d, "offline": True})

    before = network_calls_blocked()
    monkeypatch.setattr(builder, "pricer",
                        lambda *a, **k: (_ for _ in ()).throw(LookupError("boom")))
    with cache_only():
        rows = Q.day_rows(d, depth, cfg=cfg, s2cfg=s2, builder=builder,
                          swap_pricer=pricer)
    assert network_calls_blocked() == before

    f = pd.DataFrame(rows)
    assert len(f), "the date must survive a Q20 build failure"
    assert not f["q20_built"].any()
    assert f["q20_error"].iloc[0] == "LookupError"
    assert f["ca_bp_q20"].isna().all(), "no q20 value may be invented"
    assert np.isfinite(f["ca_bp_settle"]).all(), "the settles are still real"
    assert not f["gate_resolved"].any() and not f["gate_ok"].any(), (
        "a row with no curve must never pass the resolution gate")


@needs_cache
def test_day_rows_never_substitutes_one_rate_source_for_the_other(monkeypatch):
    """``ca_bp`` is whatever ``cfg.rate_source`` names, always. A silent fallback
    to the settle column when the curve is missing would put two different
    quantities in one series and nothing on the row would say so."""
    cfg = Q.Q20Config()
    d, depth = _a_priced_date(cfg)

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    s2 = Q.deep_pack_config(rank_start=5, n_packs=13)
    builder = Q.Q20Builder(cfg)
    pricer = IRSwapsMDP(source=cfg.swap_source).get_pricer(
        {"curve_name": cfg.swap_curve, "timestamp": d, "offline": True})
    monkeypatch.setattr(builder, "pricer",
                        lambda *a, **k: (_ for _ in ()).throw(LookupError("boom")))

    with cache_only():
        q = pd.DataFrame(Q.day_rows(d, depth, cfg=cfg, s2cfg=s2, builder=builder,
                                    swap_pricer=pricer))
        s = pd.DataFrame(Q.day_rows(
            d, depth, cfg=Q.Q20Config(rate_source="settle"), s2cfg=s2,
            builder=builder, swap_pricer=pricer))

    assert q["ca_bp"].isna().all(), "rate_source='q20' with no curve must be NaN"
    assert np.isfinite(s["ca_bp"]).all(), "rate_source='settle' is unaffected"
    assert not q["ca_source_ok"].any() and s["ca_source_ok"].all()


# ===========================================================================
# Trimming is a choice, and it has to be an explicit one
# ===========================================================================
def _gappy_panel():
    days = pd.to_datetime(
        [f"2021-06-{i:02d}" for i in range(1, 11)] +     # 10-day block
        [f"2024-05-{i:02d}" for i in range(1, 5)])       # later 4-day block
    return (pd.DataFrame({"date": days, "rank": 1, "pack": "X",
                          "ca_bp": np.arange(len(days), dtype=float),
                          "pack_rate": 4.0}),
            pd.DataFrame({"2Y": 4.0}, index=days))


def test_trim_longest_is_the_legacy_default():
    panel, rates = _gappy_panel()
    p, r = S2.trim_to_contiguous_run(panel, rates)
    assert len(p) == 10 and p["date"].max().year == 2021
    assert len(r) == 10


def test_trim_latest_keeps_the_recent_run():
    """The measured harm of ``max(runs, key=length)``: it truncated the near-pack
    panel at 2024-05-08 -- the "~May-2024" of the complaint -- and cut the Q20
    near band from 518 dates to 301 because the longest gap-free block happened
    to sit in 2021."""
    panel, rates = _gappy_panel()
    p, r = S2.trim_to_contiguous_run(panel, rates, keep="latest")
    assert len(p) == 4 and p["date"].min().year == 2024
    assert len(r) == 4


def test_trim_none_discards_nothing():
    panel, rates = _gappy_panel()
    p, r = S2.trim_to_contiguous_run(panel, rates, keep="none")
    assert len(p) == len(panel) and len(r) == len(rates)


def test_trim_rejects_an_unknown_mode():
    panel, rates = _gappy_panel()
    with pytest.raises(ValueError, match="longest"):
        S2.trim_to_contiguous_run(panel, rates, keep="newest")


def test_coverage_by_run_reports_both_sides_of_the_hole():
    """Trimming throws data away; it must never be the only view a reader gets."""
    panel, _ = _gappy_panel()
    cov = S2.coverage_by_run(panel)
    assert len(cov) == 2
    assert list(cov["n_days"]) == [10, 4]
    assert cov["start"].iloc[1] == datetime.date(2024, 5, 1)


# ===========================================================================
# Un-trimming without a span guard would trade a truncated series for a wrong one
# ===========================================================================
def test_window_span_ok_masks_a_window_that_bridges_a_gap():
    idx = pd.DatetimeIndex(list(pd.bdate_range("2021-06-01", periods=10))
                           + list(pd.bdate_range("2024-05-01", periods=6)))
    ok = S2.window_span_ok(idx, 5, tolerance=1.5)
    # A 5-row window is nominally ~7 calendar days; 1.5x allows ~10.
    assert not ok.iloc[:4].any(), "not enough history yet"
    assert ok.iloc[4:10].all(), "clean consecutive windows survive"
    assert not ok.iloc[10:14].any(), "windows straddling the 3-year hole do not"
    assert ok.iloc[14] and ok.iloc[15], "once past the hole, windows are clean again"


def test_window_span_guard_is_off_by_default_and_on_when_asked():
    assert S2.Strat2Config().window_span_tolerance == 0.0
    assert S2.window_span_ok(pd.DatetimeIndex(["2021-01-01"]), 5, 0.0) is None

    days = pd.DatetimeIndex(list(pd.bdate_range("2021-06-01", periods=8))
                            + list(pd.bdate_range("2024-05-01", periods=8)))
    panel = pd.DataFrame({"date": list(days) * 1, "rank": 1, "pack": "X",
                          "ca_bp": np.arange(len(days), dtype=float),
                          "pack_rate": np.linspace(4.0, 4.1, len(days))})
    loose = S2.Strat2Config(z_window_3m=4, min_history_for_z1y=4, z_window_1y=4,
                            realized_window_days=4)
    tight = S2.Strat2Config(z_window_3m=4, min_history_for_z1y=4, z_window_1y=4,
                            realized_window_days=4, window_span_tolerance=1.5)

    off = S2.panel_timeseries(panel, loose)["ca_z3m"]["X"]
    on = S2.panel_timeseries(panel, tight)["ca_z3m"]["X"]
    bridging = off.index[8:11]                      # first windows past the hole
    assert off.loc[bridging].notna().any(), "unguarded, the gap is bridged silently"
    assert on.loc[bridging].isna().all(), "guarded, a bridged window is NaN"
    assert on.notna().sum() < off.notna().sum()


def test_span_guard_works_on_a_multi_pack_panel():
    """The mask is per DATE and must broadcast across every pack column.

    Caught in the rebuild, not by the single-column test above:
    ``DataFrame.where`` refuses an ``(n, 1)`` conditional against an ``(n, m)``
    frame rather than broadcasting it, so the guard raised
    ``ValueError: Array conditional must be same shape as self`` on the first
    real panel it met (nine pack labels).
    """
    days = list(pd.bdate_range("2021-06-01", periods=8)) + \
        list(pd.bdate_range("2024-05-01", periods=8))
    rows = []
    for i, d in enumerate(days):
        for r in (1, 2, 3):
            rows.append({"date": d, "rank": r, "pack": f"P{r}",
                         "ca_bp": float(i + r), "pack_rate": 4.0 + 0.01 * i})
    panel = pd.DataFrame(rows)
    cfg = S2.Strat2Config(z_window_3m=4, z_window_1y=4, min_history_for_z1y=4,
                          realized_window_days=4, window_span_tolerance=1.5)
    ts = S2.panel_timeseries(panel, cfg)
    assert ts["ca_z3m"].shape[1] == 3, "three pack columns"
    bridging = ts["ca_z3m"].index[8:11]
    assert ts["ca_z3m"].loc[bridging].isna().all().all()
    assert ts["rv"].loc[bridging].isna().all().all()


def test_span_guard_does_not_touch_a_gap_free_panel():
    """The guard must cost nothing on the dense history, or it is a coverage
    reduction dressed up as a correctness fix."""
    days = pd.bdate_range("2021-01-04", periods=120)
    panel = pd.DataFrame({"date": days, "rank": 1, "pack": "X",
                          "ca_bp": np.linspace(1.0, 5.0, len(days)),
                          "pack_rate": np.linspace(4.0, 4.4, len(days))})
    a = S2.Strat2Config(z_window_3m=63, z_window_1y=63, min_history_for_z1y=63,
                        realized_window_days=63)
    b = S2.Strat2Config(z_window_3m=63, z_window_1y=63, min_history_for_z1y=63,
                        realized_window_days=63, window_span_tolerance=1.5)
    x = S2.panel_timeseries(panel, a)["ca_z3m"]["X"]
    y = S2.panel_timeseries(panel, b)["ca_z3m"]["X"]
    pd.testing.assert_series_equal(x, y)


# ===========================================================================
# The guard that makes every "0 network calls" claim above mean something
# ===========================================================================
def test_cache_only_blocks_httpx_directly():
    """``cache_only`` used to patch ``requests`` only, while the Barchart data
    path is ``httpx.AsyncClient``. It stopped a crawl solely because the session
    token is fetched through ``requests`` first and raised there -- a guarantee
    that held by accident of ordering."""
    httpx = pytest.importorskip("httpx")

    before = network_calls_blocked()
    with cache_only():
        with pytest.raises(CacheMissOffline):
            httpx.Client().send(httpx.Request("GET", "https://example.invalid/x"))
    assert network_calls_blocked() == before + 1

    # ...and it is put back, or every later test in the process is broken.
    assert httpx.Client.send is not None
    assert "blocked" not in getattr(httpx.Client.send, "__name__", "")


def test_cache_only_restores_both_libraries():
    import requests

    httpx = pytest.importorskip("httpx")
    saved = (requests.get, requests.Session.request, httpx.Client.send,
             httpx.AsyncClient.send)
    with cache_only():
        pass
    assert (requests.get, requests.Session.request, httpx.Client.send,
            httpx.AsyncClient.send) == saved


# ===========================================================================
# End-to-end on the rebuilt artifacts
# ===========================================================================
@needs_panel
def test_rebuilt_panel_covers_the_years_the_complaint_named():
    """The complaint was "sparse from ~May-2024 to Aug-2026". Rank 1 needs four
    contracts and the store holds them on ~250 days a year throughout."""
    p = pd.read_parquet(_PANEL)
    p["date"] = pd.to_datetime(p["date"])
    p["year"] = p["date"].dt.year
    r1 = p[p["rank"] == 1]
    n = r1.groupby("year")["date"].nunique()
    for y, floor in ((2023, 240), (2024, 240), (2025, 150)):
        assert n.get(y, 0) >= floor, f"{y}: only {n.get(y, 0)} rank-1 dates"
    assert p["date"].max() >= pd.Timestamp("2026-06-01"), (
        "the series must reach the present, not stop at the last dense block")


@needs_panel
def test_rebuilt_panel_records_availability_on_every_row():
    p = pd.read_parquet(_PANEL)
    for c in ("strip_depth", "n_instruments", "max_rank_available", "q20_built",
              "q20_error", "ca_source_ok"):
        assert c in p.columns, f"missing availability column {c}"
    assert p["strip_depth"].notna().all()
    assert p["q20_built"].dtype == bool
