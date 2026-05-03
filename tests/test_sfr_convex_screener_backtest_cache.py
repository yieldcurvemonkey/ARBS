"""Tests for the SFR Convex Screener backtest snapshot cache."""
import datetime
from pathlib import Path

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._backtest_cache import (
    SnapshotCache,
    snapshot_cache_key,
)
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


def _trivial_snapshot(d: datetime.date) -> SFRConvexScreenerSnapshot:
    sd = StructureDef(
        structure_id="A_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("A", 1.0, 96.5, 25.0),),
    )
    metrics = PayoffMetrics(
        mean_bp=1.0, std_bp=5.0, skew=0.5, excess_kurtosis=1.0,
        p_profit=0.55, ev_given_profit_bp=4.0, ev_given_loss_bp=-3.0,
        asymmetry_ratio=1.5,
        percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.7, rank=1,
    )
    return SFRConvexScreenerSnapshot(
        as_of=d, results=(r,), config_summary={"universe_size": 4},
    )


def test_snapshot_cache_key_is_stable():
    k1 = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 12})
    k2 = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 12})
    assert k1 == k2


def test_snapshot_cache_key_depends_on_config():
    k_small = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 4})
    k_big = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 12})
    assert k_small != k_big


def test_cache_roundtrip(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    snap = _trivial_snapshot(datetime.date(2026, 4, 28))
    cfg = {"universe_size": 4}
    assert cache.get(datetime.date(2026, 4, 28), cfg) is None
    cache.put(snap, cfg)
    loaded = cache.get(datetime.date(2026, 4, 28), cfg)
    assert loaded is not None
    assert loaded.as_of == snap.as_of
    assert loaded.results[0].structure_def.structure_id == "A_OUTRIGHT"


def test_cache_miss_on_different_config(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    snap = _trivial_snapshot(datetime.date(2026, 4, 28))
    cache.put(snap, {"universe_size": 4})
    assert cache.get(datetime.date(2026, 4, 28), {"universe_size": 12}) is None


def test_load_or_build_uses_cache(tmp_path: Path):
    """If cache is hit, build_fn is NOT called."""
    from RVUtils.SFRConvexScreener._backtest_cache import (
        SnapshotCache,
        load_or_build_many,
    )

    snap = _trivial_snapshot(datetime.date(2026, 4, 28))
    cache = SnapshotCache(root=tmp_path)
    cache.put(snap, {"universe_size": 4})

    call_count = {"n": 0}

    def fake_build(d):
        call_count["n"] += 1
        return _trivial_snapshot(d)

    out = load_or_build_many(
        dates=[datetime.date(2026, 4, 28)],
        cache=cache,
        build_fn=fake_build,
        config_summary={"universe_size": 4},
    )
    assert datetime.date(2026, 4, 28) in out
    assert call_count["n"] == 0  # cache hit — no build


def test_load_or_build_falls_through_to_build(tmp_path: Path):
    from RVUtils.SFRConvexScreener._backtest_cache import (
        SnapshotCache,
        load_or_build_many,
    )

    cache = SnapshotCache(root=tmp_path)
    call_count = {"n": 0}

    def fake_build(d):
        call_count["n"] += 1
        return _trivial_snapshot(d)

    out = load_or_build_many(
        dates=[datetime.date(2026, 4, 28), datetime.date(2026, 4, 29)],
        cache=cache,
        build_fn=fake_build,
        config_summary={"universe_size": 4},
    )
    assert call_count["n"] == 2  # both built and cached
    # second pass — both cached
    out2 = load_or_build_many(
        dates=[datetime.date(2026, 4, 28), datetime.date(2026, 4, 29)],
        cache=cache,
        build_fn=fake_build,
        config_summary={"universe_size": 4},
    )
    assert call_count["n"] == 2  # no new builds
    assert len(out2) == 2
