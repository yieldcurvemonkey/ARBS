"""The caches on the Citi Velocity read path, and what each one must not do.

These are correctness tests for an optimisation, so every one of them asserts a
COUNT or a VALUE, never a duration. A cache that looks fast because the page
cache is warm is indistinguishable from one that works, and this repo has a
recorded incident where exactly that hid a dead cache: a per-call fetcher
construction meant five requests made five HTTP round trips while the code read
as though it were cached.

Three shapes are pinned here.

1. **A cache keyed on the wrong thing is not a cache - it is a bug.** The fixings
   memo's key contains ``reference_date``. Leave it out and an entry cached for a
   later date serves fixings a historical curve cannot have known, which no
   timing benchmark can see. The test asks for the LATER date first.
2. **A cache that never revalidates serves stale data forever.** The day-window
   cache re-stats its partitions on every hit, because the intraday warmer
   appends minutes to a day that is already cached.
3. **A shortcut must be the same computation, not a similar one.** The par rate
   is now computed once instead of twice; the test pins that the swap handed back
   is still struck exactly at par.
"""

from __future__ import annotations

import datetime
import zoneinfo
from pathlib import Path

import pandas as pd
import pytest

CURVE = "USD-SOFR-1D"
ET = zoneinfo.ZoneInfo("America/New_York")


# ------------------------------------------------------------------ #
#                     1. the fixings result memo                     #
# ------------------------------------------------------------------ #


@pytest.fixture()
def fixings_module():
    from MDP.IRSwaps.CITIVELO_EXCEL import fixings as mod

    mod.reset_fixings_cache()
    yield mod
    mod.reset_fixings_cache()


@pytest.fixture()
def stub_sources(monkeypatch, fixings_module):
    """A deterministic two-source history, with the source fetch counted.

    Counting the SOURCE call is the point: the memo must remove work, and the
    only way to prove that without a stopwatch is to count the thing it removes.
    """
    calls = {"merged": 0, "uncached": 0}

    index = pd.bdate_range("2026-01-01", "2026-07-31")
    series = pd.Series([4.0 + i / 1000.0 for i in range(len(index))], index=index)

    def _merged(curve_name, citi_index, prefer_official, quotes):
        calls["merged"] += 1
        return fixings_module._MergedSources(
            official=series.copy(), citi=pd.Series(dtype="float64")
        )

    monkeypatch.setattr(fixings_module, "_merged_sources", _merged)

    real_uncached = fixings_module._fixings_for_uncached

    def _counted(*args, **kwargs):
        calls["uncached"] += 1
        return real_uncached(*args, **kwargs)

    monkeypatch.setattr(fixings_module, "_fixings_for_uncached", _counted)
    return calls, series


def test_fixings_memo_computes_once_per_distinct_reference_date(stub_sources, fixings_module):
    calls, _ = stub_sources

    a = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=datetime.date(2026, 6, 1))
    b = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=datetime.date(2026, 6, 1))
    assert calls["uncached"] == 1, "the second identical request recomputed"
    pd.testing.assert_series_equal(a.series, b.series, check_exact=True)

    fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=datetime.date(2026, 6, 2))
    assert calls["uncached"] == 2, "a different reference date must not reuse the entry"


def test_fixings_memo_does_not_leak_a_later_date_into_an_earlier_request(
    stub_sources, fixings_module
):
    """The later date is asked for FIRST - the order that exposes a shared entry."""
    later = datetime.date(2026, 7, 31)
    earlier = datetime.date(2026, 6, 1)

    warm = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=later)
    assert warm.series.index.max().date() < later

    got = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=earlier)
    assert got.series.index.max().date() < earlier, (
        "a fixing dated on or after the curve's own reference date is one the "
        "curve could not have known: fixings for D publish on D+1"
    )

    fixings_module.reset_fixings_cache()
    cold = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=earlier)
    pd.testing.assert_series_equal(got.series, cold.series, check_exact=True)


def test_fixings_memo_hands_out_a_copy(stub_sources, fixings_module):
    ref = datetime.date(2026, 6, 1)
    first = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=ref)
    first.series.iloc[0] = -999.0
    first.contributions["official"] = -1

    second = fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=ref)
    assert second.series.iloc[0] != -999.0, "the memo handed out its own object"
    assert second.contributions.get("official") != -1


def test_explicit_quotes_bypass_the_memo(stub_sources, fixings_module, monkeypatch):
    """An explicit quotes object is a caller's own tag cache: never shared."""
    calls, _ = stub_sources
    ref = datetime.date(2026, 6, 1)

    fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=ref)
    before = calls["uncached"]
    fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=ref, quotes=object())
    assert calls["uncached"] == before + 1


def test_reset_fixings_cache_clears_the_result_memo(stub_sources, fixings_module):
    calls, _ = stub_sources
    ref = datetime.date(2026, 6, 1)
    fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=ref)
    fixings_module.reset_fixings_cache()
    fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=ref)
    assert calls["uncached"] == 2, "reset must drop the result memo, not only the sources"


def test_fixings_memo_is_bounded(stub_sources, fixings_module):
    for day in pd.bdate_range("2026-01-01", periods=fixings_module._RESULT_CACHE_MAX + 40):
        fixings_module.fixings_for(CURVE, "USD_SOFR", reference_date=day.date())
    assert len(fixings_module._RESULT_CACHE) <= fixings_module._RESULT_CACHE_MAX


# ------------------------------------------------------------------ #
#                      2. the day-window cache                       #
# ------------------------------------------------------------------ #


class _FakeStore:
    """A store whose reads are counted and whose partitions are real files."""

    def __init__(self, base: Path):
        self.base_dir = base
        self.reads = 0

    def raw_partition_dir(self, asset: str, day: datetime.date) -> Path:
        return self.base_dir / "raw" / f"asset={asset}" / f"date={day.isoformat()}"

    def write(self, asset: str, day: datetime.date, stamps: list[str]) -> None:
        part = self.raw_partition_dir(asset, day)
        part.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(stamps, utc=True),
                "marker": list(range(len(stamps))),
            }
        )
        frame.to_parquet(part / "part.parquet", index=False)

    def read_raw_day(self, asset: str, day: datetime.date) -> pd.DataFrame:
        self.reads += 1
        part = self.raw_partition_dir(asset, day)
        files = sorted(part.glob("*.parquet"))
        if not files:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


@pytest.fixture()
def day_cache():
    from MDP.IRSwaps.CITIVELO_EXCEL import day_cache as mod

    mod.reset_day_cache()
    yield mod
    mod.reset_day_cache()


def test_day_window_reads_the_partition_once(tmp_path, day_cache):
    store = _FakeStore(tmp_path)
    day = datetime.date(2026, 7, 22)
    store.write("ASSET", day, ["2026-07-22T12:00:00Z", "2026-07-22T12:01:00Z"])

    for _ in range(25):
        window = day_cache.single_day(store, "ASSET", day)
        assert len(window.frame) == 2
    assert store.reads == 1, f"re-read the same partition {store.reads} times"
    assert day_cache.day_cache_stats()["hits"] == 24


def test_day_window_revalidates_when_the_partition_changes(tmp_path, day_cache):
    """The intraday warmer appends minutes to a day that is already cached."""
    store = _FakeStore(tmp_path)
    day = datetime.date(2026, 7, 22)
    store.write("ASSET", day, ["2026-07-22T12:00:00Z"])
    assert len(day_cache.single_day(store, "ASSET", day).frame) == 1

    store.write("ASSET", day, ["2026-07-22T12:00:00Z", "2026-07-22T12:01:00Z"])
    window = day_cache.single_day(store, "ASSET", day)
    assert len(window.frame) == 2, "served a truncated session from a stale entry"
    assert store.reads == 2
    assert day_cache.day_cache_stats()["revalidations"] == 1


def test_day_window_treats_a_cold_partition_as_absent(tmp_path, day_cache):
    """Same contract has_day gave: nothing warmed -> fall through, never raise."""
    store = _FakeStore(tmp_path)
    window = day_cache.single_day(store, "ASSET", datetime.date(2026, 7, 22))
    assert window.empty
    assert store.reads == 0, "a cold day must not attempt a read"


def test_day_window_preserves_the_requested_day_order(tmp_path, day_cache):
    """The nearest-snapshot search breaks ties positionally, so order is data."""
    store = _FakeStore(tmp_path)
    store.write("ASSET", datetime.date(2026, 7, 22), ["2026-07-22T12:00:00Z"])
    store.write("ASSET", datetime.date(2026, 7, 21), ["2026-07-21T12:00:00Z"])

    window = day_cache.day_window(
        store, "ASSET", (datetime.date(2026, 7, 22), datetime.date(2026, 7, 21))
    )
    assert list(window.stamps.dt.date) == [
        datetime.date(2026, 7, 22),
        datetime.date(2026, 7, 21),
    ]


def test_overlapping_windows_share_their_day_frames(tmp_path, day_cache):
    """Consecutive sessions overlap by two days; each partition is read once."""
    store = _FakeStore(tmp_path)
    days = [datetime.date(2026, 7, 20) + datetime.timedelta(days=i) for i in range(4)]
    for d in days:
        store.write("ASSET", d, [f"{d.isoformat()}T12:00:00Z"])

    for centre in days[1:3]:
        day_cache.day_window(
            store,
            "ASSET",
            tuple(centre + datetime.timedelta(days=o) for o in (0, -1, 1)),
        )
    assert store.reads == len(days), (
        f"read {store.reads} partitions for {len(days)} distinct days"
    )


def test_day_window_stamps_match_the_frame(tmp_path, day_cache):
    store = _FakeStore(tmp_path)
    day = datetime.date(2026, 7, 22)
    store.write("ASSET", day, ["2026-07-22T12:00:00Z", "2026-07-22T12:05:00Z"])
    window = day_cache.single_day(store, "ASSET", day)
    pd.testing.assert_series_equal(
        window.stamps,
        pd.to_datetime(window.frame["timestamp_utc"], utc=True),
        check_exact=True,
    )


# ------------------------------------------------------------------ #
#              3. one par-rate computation, not two                  #
# ------------------------------------------------------------------ #


def _synthetic_curve(fixings: pd.Series | None = None):
    """A small rateslib curve wrapped the way the store path wraps one."""
    import rateslib as rl

    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

    ref = datetime.datetime(2026, 7, 22)
    nodes = {
        rl.dt(2026, 7, 22): 1.0,
        rl.dt(2027, 7, 22): 0.96,
        rl.dt(2031, 7, 22): 0.82,
        rl.dt(2036, 7, 22): 0.68,
    }
    curve = rl.Curve(nodes=nodes, id=CURVE, convention="act360", calendar="nyc", modifier="mf")
    assert next(iter(curve.nodes.nodes.keys())) == ref
    return RLIRSwapCurve(
        rl_curve_id=CURVE,
        rl_curve_handle=curve,
        fixings=pd.Series(dtype="float64") if fixings is None else fixings,
        meta_data={"timestamp": ref},
    )


def test_par_rate_is_computed_once_per_built_swap(monkeypatch):
    import rateslib as rl

    curve = _synthetic_curve()
    calls = {"n": 0}
    real_rate = rl.IRS.rate

    def counted(self, *args, **kwargs):
        calls["n"] += 1
        return real_rate(self, *args, **kwargs)

    monkeypatch.setattr(rl.IRS, "rate", counted)

    swap = curve.build_irswap(fwd="0D", tenor="5Y")
    assert calls["n"] == 1, "the par strike was solved on a throwaway swap as well"

    rate = curve.fair_rate(swap)
    assert calls["n"] == 1, "reporting the rate re-solved a swap already struck at par"
    assert rate == pytest.approx(float(swap.fixed_rate) / 100.0, abs=0.0)


def test_the_swap_handed_back_is_struck_exactly_at_par():
    curve = _synthetic_curve()
    swap = curve.build_irswap(fwd="0D", tenor="5Y")
    # rl.IRS carries PERCENT; this wrapper's contract is DECIMAL.
    assert float(swap.fixed_rate) / 100.0 == curve.fair_rate(swap)
    assert abs(swap.npv(curves=curve.handle()).real) < 1e-6


def test_par_rate_cache_is_not_reused_for_a_different_curve():
    a = _synthetic_curve()
    b = _synthetic_curve()
    # Move b's 5Y point so the two curves cannot agree by accident.
    b.handle().update_node(b.handle().nodes.nodes and list(b.handle().nodes.nodes)[2], 0.80)

    swap = a.build_irswap(fwd="0D", tenor="5Y")
    assert b.fair_rate(swap) != a.fair_rate(swap), (
        "the cached par rate was served for a curve it was not computed against"
    )


def test_an_explicitly_struck_swap_keeps_its_strike():
    curve = _synthetic_curve()
    swap = curve.build_irswap(fwd="0D", tenor="5Y", fixed_rate=0.031)
    assert float(swap.fixed_rate) == pytest.approx(3.1)
    assert not hasattr(swap, "_arbs_par_rate")
    assert curve.fair_rate(swap) != pytest.approx(0.031, abs=1e-9)


def test_fixings_kwargs_resolve_once_per_wrapper(monkeypatch):
    """A fly is three legs; the fixings identifier must be derived once."""
    from Query.IRSwaps.backends.rateslib import RLIRSwapCurve as mod

    calls = {"n": 0}
    real = mod.rate_fixings_kwargs

    def counted(series):
        calls["n"] += 1
        return real(series)

    monkeypatch.setattr(mod, "rate_fixings_kwargs", counted)

    curve = _synthetic_curve(_fixing_history())
    for _ in range(6):
        curve.build_irswap(fwd="0D", tenor="5Y")
    assert calls["n"] == 1, f"re-derived the fixings identifier {calls['n']} times"


def test_fixings_kwargs_cache_follows_a_reassigned_series():
    curve = _synthetic_curve(_fixing_history())
    first = curve._fixings_kwargs(effective=datetime.date(2026, 6, 1))
    curve._fixings = pd.Series(dtype="float64")
    assert curve._fixings_kwargs(effective=datetime.date(2026, 6, 1)) != first


# ------------------------------------------------------------------ #
#          4. the opt-in "skip fixings nobody consumes" gate         #
# ------------------------------------------------------------------ #


@pytest.fixture()
def rl_curve_module():
    from Query.IRSwaps.backends.rateslib import RLIRSwapCurve as mod

    mod.set_omit_unused_fixings(None)
    yield mod
    mod.set_omit_unused_fixings(None)


def _fixing_history() -> pd.Series:
    index = pd.bdate_range("2026-01-01", "2026-07-21")
    return pd.Series([4.0] * len(index), index=index)


def test_omit_unused_fixings_is_off_unless_asked_for(monkeypatch, rl_curve_module):
    monkeypatch.delenv("ARBS_RL_OMIT_UNUSED_FIXINGS", raising=False)
    rl_curve_module.set_omit_unused_fixings(None)
    assert rl_curve_module.omit_unused_fixings() is False

    curve = _synthetic_curve(_fixing_history())
    assert curve._fixings_kwargs(effective=datetime.date(2026, 7, 24)) != {}


def test_omit_unused_fixings_drops_them_only_for_a_forward_start(rl_curve_module):
    rl_curve_module.set_omit_unused_fixings(True)
    curve = _synthetic_curve(_fixing_history())

    # starts after the curve's reference date -> no elapsed observation
    assert curve._fixings_kwargs(effective=datetime.date(2026, 7, 24)) == {}
    # starts before it -> seasoned, the fixings ARE the answer
    assert curve._fixings_kwargs(effective=datetime.date(2026, 6, 1)) != {}
    # unresolvable -> assume seasoned rather than silently drop
    assert curve._fixings_kwargs(effective=None) != {}
    assert curve._fixings_kwargs(effective="not-a-date") != {}


def test_omit_unused_fixings_leaves_a_seasoned_price_alone(rl_curve_module):
    curve = _synthetic_curve(_fixing_history())
    spec = dict(effective_date=datetime.date(2026, 6, 1), maturity_date=datetime.date(2031, 6, 1))

    rl_curve_module.set_omit_unused_fixings(False)
    base = curve.fair_rate(curve.build_irswap(**spec))
    rl_curve_module.set_omit_unused_fixings(True)
    with_gate = curve.fair_rate(curve.build_irswap(**spec))

    assert base == with_gate, "a seasoned swap lost its fixings"


def test_omit_unused_fixings_moves_a_par_rate_by_no_more_than_a_few_ulp(rl_curve_module):
    """The shortcut is off by default precisely because it is not bit-identical."""
    import math

    curve = _synthetic_curve(_fixing_history())

    rl_curve_module.set_omit_unused_fixings(False)
    base = curve.fair_rate(curve.build_irswap(fwd="0D", tenor="5Y"))
    rl_curve_module.set_omit_unused_fixings(True)
    fast = curve.fair_rate(curve.build_irswap(fwd="0D", tenor="5Y"))

    assert base == pytest.approx(fast, rel=1e-12), (
        f"the shortcut is meant to differ by rounding only: {base!r} vs {fast!r}"
    )
    assert math.isfinite(fast)


# ------------------------------------------------------------------ #
#        5. bulk_get_data agrees with get_data, on real data         #
# ------------------------------------------------------------------ #


def _warm_minute_days(curve: str = CURVE, want: int = 1) -> list[datetime.date]:
    from Caching.curve_store import CurveStore

    store = CurveStore.default()
    try:
        days = sorted(store.available_dates(f"{curve}-CITIVELOEXCELMIN"))
    except Exception:  # noqa: BLE001
        return []
    return days[-want:] if days else []


warm_store = pytest.mark.skipif(
    not _warm_minute_days(),
    reason="needs a warmed <curve>-CITIVELOEXCELMIN partition on this machine",
)


@warm_store
def test_bulk_get_data_matches_single_point_intraday():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    day = _warm_minute_days()[-1]
    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    base = datetime.datetime.combine(day, datetime.time(9, 0), tzinfo=ET)
    points = [base + datetime.timedelta(minutes=7 * i) for i in range(12)]

    bulk = mdp.bulk_get_data({"curve_name": CURVE, "timestamps": list(points)})
    assert bulk, "the batch returned nothing for a warmed session"

    for t in points:
        single = mdp.get_data({"curve_name": CURVE, "timestamp": t})
        got = bulk.get(t)
        assert (got is None) == (single is None)
        if single is None:
            continue
        assert got.meta() == single.meta()
        assert got.nodes() == single.nodes()
        pd.testing.assert_series_equal(got.index(), single.index(), check_exact=True)


@warm_store
def test_bulk_get_data_matches_single_point_eod():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import asset_for
    from Caching.curve_store import CurveStore

    days = sorted(CurveStore.default().available_dates(asset_for(CURVE)))[-6:-1]
    if not days:
        pytest.skip("no warmed EOD partitions")

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    bulk = mdp.bulk_get_data({"curve_name": CURVE, "timestamps": list(days)})
    for d in days:
        single = mdp.get_data({"curve_name": CURVE, "timestamp": d})
        got = bulk.get(d)
        assert (got is None) == (single is None)
        if single is None:
            continue
        assert got.meta() == single.meta()
        assert got.nodes() == single.nodes()


@warm_store
def test_bulk_get_data_honours_ignore_cache(monkeypatch):
    """``ignore_cache`` means "do not serve me the store" - in batch too."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    day = _warm_minute_days()[-1]
    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    seen = []

    monkeypatch.setattr(
        IRSwapsMDP,
        "_load_citivelo_excel_minute_store_point",
        lambda self, *, curve_name, timestamp: seen.append(timestamp) or None,
    )
    monkeypatch.setattr(
        IRSwapsMDP,
        "_get_citivelo_excel_fetcher",
        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("no Excel in tests")),
    )

    points = [datetime.datetime.combine(day, datetime.time(9, 0), tzinfo=ET)]
    out = mdp.bulk_get_data(
        {"curve_name": CURVE, "timestamps": points, "ignore_cache": True}
    )
    assert out == {}
    assert seen == [], "ignore_cache still reached the CurveStore fast path"
