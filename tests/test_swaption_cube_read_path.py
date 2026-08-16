r"""The store-backed swaption vol read path.

Before this, ``Caching/swaption_cube_store.py`` was referenced by exactly one
thing - the warm script - so ``IRSwaptionMDP``'s only route to a cube was
``fetch_cube`` -> ``CitiVelocityExcelClient.connect()``, once per date.

The tests that matter here are the ones with a **tripwire**: ``fetch_cube`` and
``connect`` are replaced with functions that raise, so a run that reaches Excel
fails rather than succeeding slowly. Asserting "a cube came back" would pass for
the behaviour being removed.

Every test builds its own store under ``tmp_path``. Nothing here touches the real
cache, the network, or Excel.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from Caching.swaption_cube_store import SwaptionCubeStore, asset_for

EXPIRIES = ("1M", "3M", "1Y", "5Y")
TENORS = ("2Y", "10Y", "30Y")
FULL_OFFSETS = (-100.0, -50.0, -25.0, 0.0, 25.0, 50.0, 100.0)


class Boom(RuntimeError):
    """Raised by every tripwire in this module."""


def make_cube_data(as_of: dt.date, offsets=FULL_OFFSETS, *, base: float = 90.0):
    """A small but genuinely valid SwaptionCubeData.

    Vols are in the plausible bp band ``assert_vol_units`` enforces, every frame
    shares the ATM axes, and nothing is NaN or non-positive - all of which
    ``validate()`` refuses.
    """
    from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData

    def frame(bump: float) -> pd.DataFrame:
        return pd.DataFrame(
            [[base + bump + 3 * i + j for j, _ in enumerate(TENORS)] for i, _ in enumerate(EXPIRIES)],
            index=list(EXPIRIES),
            columns=list(TENORS),
            dtype=float,
        )

    skew = {float(o): frame(abs(o) / 20.0) for o in offsets if float(o) != 0.0}
    return SwaptionCubeData(
        as_of=as_of,
        currency="USD",
        measure="NORMAL",
        atm=frame(0.0),
        skew=skew,
        skew_measure="NORMALABSOLUTE",
        served_unit="bp",
        vol_unit="bp",
        strike_unit="bp",
        source="test/atm_only" if len(skew) == 0 else "test/DAILY",
    ).validate()


@pytest.fixture
def store(tmp_path):
    return SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=False)


@pytest.fixture
def warm_store(store):
    """A store with three full-smile days and two ATM-only ones."""
    from MDP.IRSwaptions.CITIVELO.cube_store import clear_stored_cube_cache

    clear_stored_cube_cache()
    asset = asset_for("USD")
    full = [dt.date(2026, 8, 4), dt.date(2026, 8, 5), dt.date(2026, 8, 6)]
    atm = [dt.date(2016, 3, 1), dt.date(2016, 3, 2)]
    for d in full:
        store.write_day(asset, d, make_cube_data(d), push_l2=False)
    for d in atm:
        store.write_day(asset, d, make_cube_data(d, offsets=(0.0,)), push_l2=False)
    yield store, full, atm
    clear_stored_cube_cache()


# ── timestamp dispatch ────────────────────────────────────────────────────


class TestTimestampMode:
    """pd.Timestamp subclasses datetime subclasses date. Both orders are wrong."""

    @pytest.mark.parametrize(
        "timestamp,expected",
        [
            ("live", "live"),
            (None, "live"),
            (dt.date(2026, 8, 6), "eod"),
            (pd.Timestamp("2026-08-06"), "eod"),
            (dt.datetime(2026, 8, 6, 0, 0), "eod"),
            (dt.datetime(2026, 8, 6, 14, 30), "intraday"),
            (pd.Timestamp("2026-08-06 14:30", tz="America/New_York"), "intraday"),
        ],
    )
    def test_dispatch(self, timestamp, expected):
        from MDP.IRSwaptions.IRSwaptionMDP import resolve_timestamp_mode

        assert resolve_timestamp_mode(timestamp) == expected

    def test_a_bare_date_is_not_read_as_intraday(self):
        """`datetime` tested first would swallow this."""
        from MDP.IRSwaptions.IRSwaptionMDP import resolve_timestamp_mode

        assert resolve_timestamp_mode(dt.date(2026, 8, 6)) != "intraday"

    def test_a_midnight_timestamp_is_not_read_as_intraday(self):
        """`date` tested first would swallow every real intraday request; testing
        `datetime` first swallows THIS, which is the common spelling of 'that day'."""
        from MDP.IRSwaptions.IRSwaptionMDP import resolve_timestamp_mode

        assert resolve_timestamp_mode(pd.Timestamp("2026-08-06")) == "eod"


# ── the store layer ───────────────────────────────────────────────────────


class TestLoadStoredCubes:
    def test_loads_what_is_warm_and_reports_the_smile(self, warm_store):
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        store, full, atm = warm_store
        got = load_stored_cubes("USD", full + atm, store=store)
        assert sorted(got) == sorted(full + atm)
        assert {d: got[d].smile for d in full} == {d: "full" for d in full}
        assert {d: got[d].smile for d in atm} == {d: "atm_only" for d in atm}
        assert all(got[d].has_smile for d in full)
        assert not any(got[d].has_smile for d in atm)

    def test_offsets_are_reported_exactly(self, warm_store):
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        store, full, atm = warm_store
        got = load_stored_cubes("USD", [full[0], atm[0]], store=store)
        assert got[full[0]].offsets_bp == FULL_OFFSETS
        assert got[atm[0]].offsets_bp == (0.0,)

    def test_a_missing_day_is_absent_not_an_error(self, warm_store):
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        store, full, _ = warm_store
        got = load_stored_cubes("USD", [full[0], dt.date(1990, 1, 1)], store=store)
        assert sorted(got) == [full[0]]

    def test_a_cold_store_returns_empty_and_does_not_raise(self, tmp_path):
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        cold = SwaptionCubeStore(base_dir=tmp_path / "cold", l2=False)
        assert load_stored_cubes("USD", [dt.date(2026, 8, 6)], store=cold) == {}

    def test_results_are_memoised_for_the_same_store(self, warm_store):
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        store, full, _ = warm_store
        first = load_stored_cubes("USD", full, store=store)

        class _Exploding:
            """Same base_dir, so the memo must answer without touching read_day."""

            base_dir = store.base_dir

            def read_day(self, *a, **k):
                raise AssertionError("read_day was called; the memo did not hold")

        second = load_stored_cubes("USD", full, store=_Exploding())
        assert sorted(second) == sorted(first)
        assert second[full[0]] is first[full[0]]

    def test_the_memo_does_not_leak_between_stores(self, warm_store, tmp_path):
        """The memo key includes the base_dir.

        Without it, the first store to answer for an (asset, date) poisons every
        other store for the life of the process - so a caller that passed a
        specific ``store=`` would silently be served the DEFAULT store's cube.
        """
        from Caching.swaption_cube_store import asset_for
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        store, full, _ = warm_store
        warm = load_stored_cubes("USD", [full[0]], store=store)
        assert full[0] in warm

        # A DIFFERENT, empty store must answer "I do not have it", not hand back
        # the other store's cube.
        empty = SwaptionCubeStore(base_dir=tmp_path / "elsewhere", l2=False)
        assert load_stored_cubes("USD", [full[0]], store=empty) == {}

        # ...and one holding DIFFERENT content for the same day must serve its own.
        other = SwaptionCubeStore(base_dir=tmp_path / "other", l2=False)
        mine = make_cube_data(full[0], base=140.0)
        other.write_day(asset_for("USD"), full[0], mine, push_l2=False)
        got = load_stored_cubes("USD", [full[0]], store=other)[full[0]]
        assert float(got.data.atm.iloc[0, 0]) == float(mine.atm.iloc[0, 0])
        assert float(got.data.atm.iloc[0, 0]) != float(warm[full[0]].data.atm.iloc[0, 0])

    def test_provenance_is_a_plain_dict_for_metadata(self, warm_store):
        from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

        store, full, _ = warm_store
        prov = load_stored_cubes("USD", [full[0]], store=store)[full[0]].provenance()
        assert prov["origin"] == "swaption_cube_store"
        assert prov["smile"] == "full"
        assert prov["n_offsets"] == len(FULL_OFFSETS)
        assert prov["as_of"] == full[0].isoformat()

    def test_stored_coverage_reports_the_range(self, warm_store):
        from MDP.IRSwaptions.CITIVELO.cube_store import stored_coverage

        store, full, atm = warm_store
        cov = stored_coverage("USD", store=store)
        assert cov["n_days"] == len(full) + len(atm)
        assert cov["first"] == min(full + atm)
        assert cov["last"] == max(full + atm)


# ── the provider, with Excel wired to explode ─────────────────────────────


@pytest.fixture
def no_excel(monkeypatch):
    """Any route to Excel is a test failure, not a slow success."""
    import MDP.CitiVelocityExcel.com_client as com
    import MDP.CitiVelocityExcel.vol.cube_data as cube_data

    calls: list[str] = []

    def _connect(*a, **k):
        calls.append("connect")
        raise Boom("CitiVelocityExcelClient.connect() was called")

    def _fetch(*a, **k):
        calls.append("fetch_cube")
        raise Boom("fetch_cube() was called")

    monkeypatch.setattr(com.CitiVelocityExcelClient, "connect", staticmethod(_connect))
    monkeypatch.setattr(cube_data, "fetch_cube", _fetch)
    return calls


@pytest.fixture
def flat_ql_curve():
    """A curve object for the ``curves=`` argument.

    Its contents do not matter, because :func:`stub_build` also stubs
    ``_split_curves``. It exists so the provider's "no curve for this date" skip
    does not silently empty the result.
    """

    def _for(day: dt.date):
        class _Curve:
            def handle(self):
                return object()

            def index(self):
                return None

        return _Curve()

    return _for


@pytest.fixture
def stub_build(monkeypatch):
    """Stub the two seams BELOW the source decision, and record the cube used.

    ``_split_curves`` mirrors a rateslib curve into QuantLib, and
    ``build_citivelo_swaption_cube`` builds a real spline cube. Neither is under
    test in this class - what is under test is which SOURCE supplied the numbers
    - and leaving them real turns every test here into an integration test of the
    pricer (and makes ``engine='RL'`` reject a QuantLib stand-in curve outright).

    Note the patch target for the builder. ``provider.py`` does
    ``from ...swaption_cube import build_citivelo_swaption_cube`` **inside** the
    function, so patching the attribute on ``provider`` does nothing: the local
    import re-fetches the original. It has to be patched where it is defined.
    """
    import MDP.CitiVelocityExcel.vol.swaption_cube as sc
    from MDP.IRSwaptions.CITIVELO import provider as prov

    captured: dict = {}

    def _build(**kwargs):
        captured["cube"] = kwargs.get("cube")
        captured["backend"] = kwargs.get("backend")
        return _StubBuilt(kwargs)

    monkeypatch.setattr(sc, "build_citivelo_swaption_cube", _build)
    monkeypatch.setattr(prov, "_split_curves", lambda curve: (object(), object()))
    return captured


class TestProviderUsesTheStore:
    def test_a_warmed_date_never_reaches_excel(self, warm_store, no_excel, flat_ql_curve, stub_build):
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, full, _ = warm_store
        out = prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D",
            dates=full,
            engine="RL",
            curves={d: flat_ql_curve(d) for d in full},
            cube_store=store,
        )
        assert sorted(out) == sorted(full)
        assert no_excel == [], f"Excel was reached: {no_excel}"

    def test_provenance_says_the_store_answered(self, warm_store, no_excel, flat_ql_curve, stub_build):
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, full, _ = warm_store
        prov.clear_citivelo_cube_cache()
        prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D", dates=[full[0]], engine="RL",
            curves={full[0]: flat_ql_curve(full[0])}, cube_store=store,
        )
        got = prov.get_cached_citivelo_provenance("USD-SOFR-1D", full[0], "RL")
        assert got["origin"] == "swaption_cube_store"
        assert got["smile"] == "full"

    def test_use_cube_store_false_goes_to_excel(self, warm_store, no_excel, flat_ql_curve, stub_build):
        """The opt-out has to actually opt out, or it is decoration."""
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, full, _ = warm_store
        with pytest.raises(Boom):
            prov.get_citivelo_vol_objects(
                curve_name="USD-SOFR-1D", dates=[full[0]], engine="RL",
                curves={full[0]: flat_ql_curve(full[0])},
                cube_store=store, use_cube_store=False,
            )
        # `connect` rather than `fetch_cube`: _cube_for_date builds the client
        # first when none was passed, so that is the call the tripwire sees. What
        # matters is that it went OUTSIDE at all.
        assert no_excel, "the opt-out did not opt out; nothing reached Excel"

    def test_live_bypasses_the_store(self, warm_store, no_excel, flat_ql_curve, stub_build):
        """'live' becomes date.today() upstream, so only the MODE can stop the
        store serving this morning's close as if it were the current quote."""
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, full, _ = warm_store
        with pytest.raises(Boom):
            prov.get_citivelo_vol_objects(
                curve_name="USD-SOFR-1D", dates=[full[0]], engine="RL",
                curves={full[0]: flat_ql_curve(full[0])},
                cube_store=store, timestamp_mode="live",
            )
        assert no_excel, "a live request was served from the warmed store"

    def test_an_explicit_cube_still_outranks_the_store(self, warm_store, no_excel, flat_ql_curve, stub_build):
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, full, _ = warm_store
        captured = stub_build
        mine = make_cube_data(full[0], base=120.0)
        prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D", dates=[full[0]], engine="RL",
            curves={full[0]: flat_ql_curve(full[0])}, cube_store=store,
            cubes={full[0]: mine},
        )
        assert captured["cube"] is mine
        assert no_excel == []

    def test_a_caller_cube_is_not_attributed_to_the_store(
        self, warm_store, no_excel, flat_ql_curve, stub_build
    ):
        """The store holds this date too. Provenance must name the branch that
        actually answered, not "was this date in the store"."""
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, full, _ = warm_store
        prov.clear_citivelo_cube_cache()
        prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D", dates=[full[0]], engine="RL",
            curves={full[0]: flat_ql_curve(full[0])}, cube_store=store,
            cubes={full[0]: make_cube_data(full[0], base=120.0)},
        )
        got = prov.get_cached_citivelo_provenance("USD-SOFR-1D", full[0], "RL")
        assert got["origin"] == "caller", got

    def test_a_caller_cube_is_not_judged_by_the_stores_smile(
        self, warm_store, no_excel, flat_ql_curve, stub_build
    ):
        """An ATM-only day in the store must not block a full-smile cube the
        caller supplied for that same date - it is perfectly buildable."""
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, _, atm = warm_store
        out = prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D", dates=[atm[0]], engine="QL",
            curves={atm[0]: flat_ql_curve(atm[0])}, cube_store=store,
            cubes={atm[0]: make_cube_data(atm[0])},  # full smile
        )
        assert sorted(out) == [atm[0]]
        assert no_excel == []


class TestAtmOnlyDaysAreExplained:
    def test_a_ql_cube_on_an_atm_only_day_builds_with_atm_fallback(
        self, warm_store, no_excel, flat_ql_curve, stub_build
    ):
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, _, atm = warm_store
        out = prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D", dates=[atm[0]], engine="QL",
            curves={atm[0]: flat_ql_curve(atm[0])}, cube_store=store,
        )
        assert sorted(out) == [atm[0]]
        assert no_excel == [], f"Excel was reached: {no_excel}"

    def test_the_rateslib_backend_is_not_blocked_on_an_atm_only_day(
        self, warm_store, no_excel, flat_ql_curve, stub_build
    ):
        """The guard is about the QuantLib CUBE, which needs offsets. Blocking
        every backend would throw away 1,067 usable ATM days."""
        from MDP.IRSwaptions.CITIVELO import provider as prov

        store, _, atm = warm_store
        out = prov.get_citivelo_vol_objects(
            curve_name="USD-SOFR-1D", dates=[atm[0]], engine="RL",
            curves={atm[0]: flat_ql_curve(atm[0])}, cube_store=store,
        )
        assert sorted(out) == [atm[0]]
        assert no_excel == []


class _StubBuilt:
    """Stands in for CitiVeloSwaptionCube: the vol object's identity is not
    under test here, only which SOURCE supplied the numbers behind it."""

    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.ql_handle = object()


# ── the MDP forwards the mode ─────────────────────────────────────────────


class TestMdpPlumbing:
    def test_the_provider_is_flagged_to_receive_the_mode(self):
        from MDP.IRSwaptions.IRSwaptionMDP import _citivelo_vol_provider

        assert getattr(_citivelo_vol_provider, "wants_timestamp_mode", False) is True

    def test_build_contexts_forwards_the_mode_only_to_providers_that_want_it(self, monkeypatch):
        """MONKEYCUBE forwards **kwargs into get_sabr_vol_surfaces, where an
        unexpected keyword raises - so this must stay opt-in."""
        from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP

        seen: dict[str, dict] = {}

        def _wanting(*, curve_name, dates, surface_type, **kw):
            seen["wanting"] = kw
            return {}

        def _not_wanting(*, curve_name, dates, surface_type, **kw):
            seen["not_wanting"] = kw
            return {}

        _wanting.wants_timestamp_mode = True

        mdp = IRSwaptionMDP.__new__(IRSwaptionMDP)
        mdp.VOL_PROVIDERS = {"WANTS": _wanting, "PLAIN": _not_wanting}
        mdp.ENGINE_FACTORIES = {"QL": lambda **kw: object()}
        mdp.curve_source = "TEST"
        mdp._default_request_kwargs = {}
        mdp._runtime_cache = {}
        monkeypatch.setattr(IRSwaptionMDP, "_cache_get", lambda self, k: None)
        monkeypatch.setattr(IRSwaptionMDP, "_fetch_curve_map", lambda self, **kw: {})

        for provider, key in (("WANTS", "wanting"), ("PLAIN", "not_wanting")):
            mdp._build_contexts(
                curve_name="USD-SOFR-1D",
                dates=[dt.date(2026, 8, 6)],
                provider=provider,
                engine="QL",
                surface_type="atmf_normal",
                ignore_cache=True,
                request_kwargs={},
                timestamp_mode="live",
            )
        assert seen["wanting"].get("timestamp_mode") == "live"
        assert "timestamp_mode" not in seen["not_wanting"]

    def test_live_and_eod_do_not_share_a_context_cache_key(self):
        """The provider's live guard is defeated one layer up if they collide.

        ``request_token`` is computed from ``effective_request_kwargs`` BEFORE
        ``timestamp_mode`` is added to ``provider_kwargs``, so it cannot carry
        the mode. Without the mode in the key: build an EOD context for today
        (served from the warmed store), then ask for ``timestamp="live"`` with
        ``ignore_cache=False`` — ``_cache_get`` hits, the provider never runs,
        and the caller gets this morning's close believing it is live. Today's
        close IS in the store, so this is the common case, not a corner.
        """
        from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP

        mdp = IRSwaptionMDP.__new__(IRSwaptionMDP)
        mdp.curve_source = "TEST"
        common = dict(
            curve_name="USD-SOFR-1D",
            d=dt.date(2026, 8, 6),
            provider="CITIVELO",
            engine="RL",
            surface_type="atmf_normal",
            request_token="tok",
        )
        eod = IRSwaptionMDP._cache_key(mdp, **common, timestamp_mode="eod")
        live = IRSwaptionMDP._cache_key(mdp, **common, timestamp_mode="live")
        intraday = IRSwaptionMDP._cache_key(mdp, **common, timestamp_mode="intraday")
        assert len({eod, live, intraday}) == 3, (eod, live, intraday)

    def test_the_eod_key_is_unchanged_so_existing_caches_still_hit(self):
        """The mode is appended only when non-default; every key already on disk
        keeps its meaning rather than every cache missing once."""
        from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP

        mdp = IRSwaptionMDP.__new__(IRSwaptionMDP)
        mdp.curve_source = "TEST"
        common = dict(
            curve_name="USD-SOFR-1D",
            d=dt.date(2026, 8, 6),
            provider="CITIVELO",
            engine="RL",
            surface_type="atmf_normal",
            request_token="tok",
        )
        assert IRSwaptionMDP._cache_key(mdp, **common) == IRSwaptionMDP._cache_key(
            mdp, **common, timestamp_mode="eod"
        )
        assert "mode=" not in IRSwaptionMDP._cache_key(mdp, **common)

    def test_a_live_request_is_classified_before_to_date_flattens_it(self):
        from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP

        mdp = IRSwaptionMDP.__new__(IRSwaptionMDP)
        mdp._default_request_kwargs = {}
        mdp.source = "CITIVELO-RL"
        mdp.curve_ignore_cache = False
        parsed = IRSwaptionMDP._parse_single_request(
            mdp, {"curve_name": "USD-SOFR-1D", "timestamp": "live"}
        )
        assert parsed["timestamp_mode"] == "live"
        assert parsed["date"] == dt.date.today()  # the information that was lost

    def test_a_bulk_batch_is_only_live_when_every_entry_is(self):
        from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP

        mdp = IRSwaptionMDP.__new__(IRSwaptionMDP)
        mdp._default_request_kwargs = {}
        mdp.source = "CITIVELO-RL"
        mdp.curve_ignore_cache = False

        def parse(timestamps):
            return IRSwaptionMDP._parse_bulk_request(
                mdp, {"curve_name": "USD-SOFR-1D", "timestamps": timestamps}
            )["timestamp_mode"]

        assert parse(["live", "live"]) == "live"
        assert parse([dt.date(2026, 8, 5), dt.date(2026, 8, 6)]) == "eod"
        # one live entry must not stop the whole range reading the store
        assert parse(["live", dt.date(2026, 8, 6)]) != "live"


# ── the reshape rewrite ───────────────────────────────────────────────────


class TestCubeFromFrameReshape:
    def test_round_trips_a_full_smile_exactly(self, store):
        asset = asset_for("USD")
        day = dt.date(2026, 8, 6)
        original = make_cube_data(day)
        store.write_day(asset, day, original, push_l2=False)
        back = store.reconstruct_cube(asset, day)

        # check_names=False: a pivot names its axes, so the reconstructed frame
        # carries index.name='expiry' / columns.name='tenor' while a hand-built
        # one does not. That is UNCHANGED behaviour - the pre-rewrite code
        # pivoted too - so it is asserted explicitly below rather than hidden.
        pd.testing.assert_frame_equal(back.atm, original.atm, check_exact=True, check_names=False)
        assert back.atm.index.name == "expiry" and back.atm.columns.name == "tenor"
        assert sorted(back.skew) == sorted(original.skew)
        for off in original.skew:
            pd.testing.assert_frame_equal(
                back.skew[off], original.skew[off], check_exact=True, check_names=False
            )

    def test_round_trips_an_atm_only_day(self, store):
        asset = asset_for("USD")
        day = dt.date(2016, 3, 1)
        original = make_cube_data(day, offsets=(0.0,))
        store.write_day(asset, day, original, push_l2=False)
        back = store.reconstruct_cube(asset, day)
        pd.testing.assert_frame_equal(back.atm, original.atm, check_exact=True, check_names=False)
        assert back.skew == {}

    def test_axis_order_is_maturity_order_not_lexicographic(self, store):
        """'1M','3M','1Y','5Y' sorts lexicographically to '1M','1Y','3M','5Y'."""
        asset = asset_for("USD")
        day = dt.date(2026, 8, 6)
        store.write_day(asset, day, make_cube_data(day), push_l2=False)
        back = store.reconstruct_cube(asset, day)
        assert list(back.atm.index) == list(EXPIRIES)
        assert list(back.atm.columns) == list(TENORS)
