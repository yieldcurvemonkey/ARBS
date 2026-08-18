import datetime as dt

import pandas as pd

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMarketContext
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery, IRSwaptionQueryWrapper
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from TB.IRSwaptionsTB import IRSwaptionsTB


class _FakeMDP:
    def __init__(self):
        self.source = "FAKE"
        self.curve_source = "FAKE_CURVE"
        self.calls = 0

    def bulk_get_data(self, request):
        self.calls += 1
        out = {}
        for d in request["timestamps"]:
            out[d] = IRSwaptionMarketContext(
                curve_name=request["curve_name"],
                as_of_date=d,
                curve=None,
                curve_handle=None,
                swap_index=None,
                vol_handle=None,
                pricing_engine=None,
                provider="FAKE",
                engine="QL",
                surface_type="atmf_normal",
                source="FAKE-QL",
                metadata={},
            )
        return out


def test_tb_bulk_grouping_cache_and_wrapper_columns(monkeypatch):
    mdp = _FakeMDP()
    tb = IRSwaptionsTB(mdp=mdp, show_tqdm=False, use_ts_cache=False)

    monkeypatch.setattr(
        "TB.IRSwaptionsTB._build_row_for_query",
        lambda context, q, ref_dt: (ref_dt, q.col_name(), 1.0 if q.name == "A" else 2.0),
    )

    q1 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y", name="A")
    q2 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="10Y", name="B")
    w = IRSwaptionQueryWrapper([q1, q2], "A_plus_B")

    start = dt.date(2026, 3, 2)
    end = dt.date(2026, 3, 3)

    out1 = tb.get_timeseries(start, end, [q1, q2, w], ignore_cache=False)
    assert not out1.empty
    assert "A" in out1.columns
    assert "B" in out1.columns
    assert "A_plus_B" in out1.columns
    assert (out1["A_plus_B"] == 3.0).all()

    calls_after_first = mdp.calls
    out2 = tb.get_timeseries(start, end, [q1, q2, w], ignore_cache=False)
    assert not out2.empty
    assert mdp.calls == calls_after_first

    _ = tb.get_timeseries(start, end, [q1, q2], ignore_cache=True)
    assert mdp.calls > calls_after_first


def test_tb_show_tqdm_uses_progress_wrapper(monkeypatch):
    mdp = _FakeMDP()
    tb = IRSwaptionsTB(mdp=mdp, show_tqdm=True, use_ts_cache=False)
    seen = []

    def _record_tqdm(iterable, *args, **kwargs):
        seen.append({"desc": kwargs.get("desc"), "disable": kwargs.get("disable")})
        return iterable

    monkeypatch.setattr("TB.IRSwaptionsTB._build_row_for_query", lambda context, q, ref_dt: (ref_dt, q.col_name(), 1.0))
    monkeypatch.setattr("TB.IRSwaptionsTB._tqdm", _record_tqdm)

    q = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y")
    out = tb.get_timeseries(dt.date(2026, 3, 2), dt.date(2026, 3, 2), [q], ignore_cache=True)

    assert not out.empty
    assert seen
    assert any(item["disable"] is False for item in seen)


def test_tb_reuses_durable_eod_values_across_fresh_instances(monkeypatch, tmp_path):
    """A new notebook kernel must not rebuild a warmed historical value."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")
    monkeypatch.setattr(
        "TB.IRSwaptionsTB._build_row_for_query",
        lambda context, q, ref_dt: (ref_dt, q.col_name(), 12.5),
    )
    q = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y", name="named")
    day = dt.date(2024, 1, 2)

    first_mdp = _FakeMDP()
    with IRSwaptionsTB(
        first_mdp,
        cache_stem="swaption-l1-first",
        ts_base_dir=tmp_path / "values",
        use_duckdb=False,
        show_tqdm=False,
    ) as first_tb:
        first = first_tb.get_timeseries(day, day, [q])
    assert first_mdp.calls == 1
    assert first.iloc[0]["named"] == 12.5

    second_mdp = _FakeMDP()
    unnamed = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y")
    with IRSwaptionsTB(
        second_mdp,
        cache_stem="swaption-l1-second",
        ts_base_dir=tmp_path / "values",
        use_duckdb=False,
        show_tqdm=False,
    ) as second_tb:
        second = second_tb.get_timeseries(day, day, [unnamed])

    assert second_mdp.calls == 0
    assert second.iloc[0][unnamed.col_name()] == 12.5


def test_tb_prices_only_missing_query_date_pairs_after_durable_read(monkeypatch, tmp_path):
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")
    built = []

    def _row(context, q, ref_dt):
        built.append((ref_dt, q.name))
        return ref_dt, q.col_name(), 1.0

    monkeypatch.setattr("TB.IRSwaptionsTB._build_row_for_query", _row)
    q1 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y", name="A")
    q2 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="10Y", name="B")
    d1, d2 = dt.date(2024, 1, 2), dt.date(2024, 1, 3)

    # Seed exactly one pair into the durable store under a different L1 cache.
    seed_mdp = _FakeMDP()
    with IRSwaptionsTB(
        seed_mdp, cache_stem="swaption-seed", ts_base_dir=tmp_path / "values",
        use_duckdb=False, show_tqdm=False,
    ) as seed_tb:
        seed_tb.get_timeseries(d1, d1, [q1])
    built.clear()

    mdp = _FakeMDP()
    with IRSwaptionsTB(
        mdp, cache_stem="swaption-reader", ts_base_dir=tmp_path / "values",
        use_duckdb=False, show_tqdm=False,
    ) as tb:
        out = tb.get_timeseries(d1, d2, [q1, q2])

    assert not out.empty
    assert mdp.calls == 1
    # q1/d1 came from the durable store; the other three pairs were priced.
    assert sorted(built) == [(d1, "B"), (d2, "A"), (d2, "B")]


def test_tb_reads_native_citi_atmf_nvol_without_building_a_context(monkeypatch, tmp_path):
    """A new cube node is already the exact ATM normal-vol value."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")

    class _CubeData:
        def vol(self, expiry, tail, *, offset_bp):
            assert (expiry, tail, offset_bp) == ("2Y", "15Y", 0.0)
            return 87.25

    class _StoredCube:
        data = _CubeData()

    monkeypatch.setattr(
        "MDP.IRSwaptions.CITIVELO.cube_store.load_stored_cubes",
        lambda currency, dates: {day: _StoredCube() for day in dates if currency == "USD"},
    )
    mdp = _FakeMDP()
    mdp.source = "CITIVELO-RL"
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
        structure=IRSwaptionStructure.STRADDLE,
    )
    day = dt.date(2026, 8, 14)

    with IRSwaptionsTB(
        mdp, cache_stem="native-citi-node", show_tqdm=False,
        use_ts_cache=False,
    ) as tb:
        out = tb.get_timeseries(day, day, [q])

    assert mdp.calls == 0
    assert out.iloc[0][q.col_name()] == 87.25


def test_tb_reads_standard_citi_nvol_packages_without_building_a_context(monkeypatch, tmp_path):
    """Fixed-ATMF wings/packages are exact raw-smile arithmetic for NVOL."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")

    class _CubeData:
        _vols = {-25.0: 91.0, 0.0: 87.0, 25.0: 83.0}

        def vol(self, expiry, tail, *, offset_bp):
            assert (expiry, tail) == ("2Y", "15Y")
            return self._vols[float(offset_bp)]

    class _StoredCube:
        data = _CubeData()

    monkeypatch.setattr(
        "MDP.IRSwaptions.CITIVELO.cube_store.load_stored_cubes",
        lambda currency, dates: {day: _StoredCube() for day in dates if currency == "USD"},
    )
    mdp = _FakeMDP()
    mdp.source = "CITIVELO-RL"
    day = dt.date(2026, 8, 14)
    queries = [
        IRSwaptionQuery(
            name="wing", curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF+25",
            structure=IRSwaptionStructure.PAYER,
        ),
        IRSwaptionQuery(
            name="strangle", curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
            structure=IRSwaptionStructure.STRANGLE,
        ),
        IRSwaptionQuery(
            name="spread", curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
            structure=IRSwaptionStructure.PAYER_SPREAD,
        ),
        IRSwaptionQuery(
            name="fly", curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
            structure=IRSwaptionStructure.PAYER_FLY,
        ),
        IRSwaptionQuery(
            name="rr", curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
            structure=IRSwaptionStructure.RISK_REVERSAL,
        ),
    ]

    with IRSwaptionsTB(
        mdp, cache_stem="native-citi-packages", show_tqdm=False,
        use_ts_cache=False,
    ) as tb:
        out = tb.get_timeseries(day, day, queries)

    assert mdp.calls == 0
    assert out.iloc[0].to_dict() == {
        "wing": 83.0,
        "strangle": 87.0,
        "spread": 85.0,
        "fly": 87.0,
        "rr": 87.0,
    }


def test_tb_reads_costless_citi_package_without_building_a_context(monkeypatch, tmp_path):
    """A default costless 1x2 is solvable in raw-smile coordinates."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")

    class _CubeData:
        as_of = dt.date(2026, 8, 14)

    class _StoredCube:
        data = _CubeData()
        has_smile = True

    class _Smile:
        def get_from_strike(self, strike, *, f):
            _ = (strike, f)
            return type("_Point", (), {"vol": 80.0})()

    class _NativeCube:
        def get_smile(self, expiry, tail):
            assert (expiry, tail) == ("2Y", "15Y")
            return _Smile()

    monkeypatch.setattr(
        "MDP.IRSwaptions.CITIVELO.cube_store.load_stored_cubes",
        lambda currency, dates: {day: _StoredCube() for day in dates if currency == "USD"},
    )
    monkeypatch.setattr(
        IRSwaptionsTB,
        "_citivelo_native_smile_cube",
        lambda self, stored: _NativeCube(),
    )
    mdp = _FakeMDP()
    mdp.source = "CITIVELO-RL"
    day = dt.date(2026, 8, 14)
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
        structure=IRSwaptionStructure.PAYER_1x2,
    )

    with IRSwaptionsTB(
        mdp, cache_stem="native-citi-costless", show_tqdm=False,
        use_ts_cache=False,
    ) as tb:
        out = tb.get_timeseries(day, day, [q])

    assert mdp.calls == 0
    assert out.iloc[0][q.col_name()] == 80.0


def test_tb_normalizes_mixed_legacy_eod_cache_keys_before_grouping(monkeypatch, tmp_path):
    """Legacy timestamp rows and new date rows represent one EOD observation."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")

    class _CubeData:
        def vol(self, expiry, tail, *, offset_bp):
            assert (expiry, tail, offset_bp) == ("2Y", "15Y", 0.0)
            return 87.25

    class _StoredCube:
        data = _CubeData()

    monkeypatch.setattr(
        "MDP.IRSwaptions.CITIVELO.cube_store.load_stored_cubes",
        lambda currency, dates: {day: _StoredCube() for day in dates if currency == "USD"},
    )
    mdp = _FakeMDP()
    mdp.source = "CITIVELO-RL"
    day = dt.date(2026, 8, 14)
    cached = IRSwaptionQuery(curve="USD-SOFR-1D", shorthand="1Yx5Y")
    native = IRSwaptionQuery(
        curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
        structure=IRSwaptionStructure.STRADDLE,
    )

    with IRSwaptionsTB(
        mdp, cache_stem="mixed-eod-keys", show_tqdm=False,
        use_ts_cache=False,
    ) as tb:
        getattr(tb, tb._cache_attr)[tb._cache_key(day, cached.curve, cached)] = (
            dt.datetime(2026, 8, 14, 17), cached.col_name(), 10.0,
        )
        out = tb.get_timeseries(day, day, [cached, native])

    assert mdp.calls == 0
    assert len(out) == 1
    assert out.iloc[0][cached.col_name()] == 10.0
    assert out.iloc[0][native.col_name()] == 87.25


def test_tb_offline_native_citi_node_skips_missing_cube_without_pricing(monkeypatch, tmp_path):
    """An offline warmer must not fall back to Excel for a market holiday."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path / "diskcache")
    monkeypatch.setattr(
        "MDP.IRSwaptions.CITIVELO.cube_store.load_stored_cubes",
        lambda currency, dates: {},
    )
    mdp = _FakeMDP()
    mdp.source = "CITIVELO-RL"
    mdp._default_request_kwargs = {"offline_only": True}
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D", shorthand="2Yx15Y", strike="ATMF",
        structure=IRSwaptionStructure.STRADDLE,
    )
    day = dt.date(2026, 7, 3)

    with IRSwaptionsTB(
        mdp, cache_stem="native-citi-missing", show_tqdm=False,
        use_ts_cache=False,
    ) as tb:
        out = tb.get_timeseries(day, day, [q])

    assert mdp.calls == 0
    assert out.empty
