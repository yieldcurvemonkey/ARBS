r"""``TimeseriesBuilder(direct=...)``: does it really bypass the cache, and does the
default really not move?

Why the stub omits one day
--------------------------
The historical defect on this path is not "no fetch happened". It is
**refetch-merge-serve-merged**: ``ignore_cache=True`` re-fetches, merges the
result into the tag parquet and then serves the MERGED file, so a day the vendor
did not return keeps its stale cached value and is returned as if live. That path
*calls the transport too*. So a test that asserts "a fresh value came back and the
transport was called" PASSES ON THE BROKEN CODE and proves nothing.

The discriminator is :data:`OMIT`. The stub transport deliberately serves no row
for that one day. Under a true bypass there is nothing to merge with, so the day
is an explicit ``NaN``; under refetch-and-merge it comes back as the poison. Every
ON-direction assertion below keys on that day.

The OFF direction is not optional either: it is what proves the harness can see a
cache hit at all. If the poisoned value does not come back with ``direct`` absent,
the fixture is not wired to the cache it claims to test and the ON direction is
meaningless.

Safety
------
No Excel, no COM, no production cache, no Supabase. Every cache is constructed
with an explicit ``base_dir=tmp_path``; ``CitiVelocityExcelClient`` is patched out
of the quotes module so a stray ``connect()`` raises instead of opening a
workbook; ``ARBS_SUPABASE_ENABLED=0``.
"""

from __future__ import annotations

import datetime
import pathlib
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import pytest

import MDP.CitiVelocityExcel.quotes as _quotes_mod
from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import tenor_years
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.mdp import CitiVelocityMDP
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from Query.CitiVelocity.CitiVeloQuery import CitiVeloQuery
from Query.CitiVelocity.CitiVeloValue import CitiVeloValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from TB.CitiVelocityTB import CitiVelocityTB
from TB.direct_mode import DirectMode, DirectModeError, parse_direct_mode
from TB.TimeseriesBuilder import TimeseriesBuilder

CURVE = "USD_SOFR"
TENOR = "10Y"
TAG = f"RATES.OIS.{CURVE}.PAR.{TENOR}"

POISON = 999.0
FRESH = 111.0

START = datetime.date(2026, 1, 5)  # Mon
END = datetime.date(2026, 1, 9)  # Fri
#: The day the stub transport refuses to serve. See the module docstring.
OMIT = pd.Timestamp("2026-01-07")
#: Far enough back to cover every lookback on this path (45d fast, 30d snapshot).
POISON_FROM = pd.Timestamp("2025-09-01")


# ------------------------------------------------------------------ #
#                            the harness                             #
# ------------------------------------------------------------------ #


class StubCitiClient:
    """Stands in for ``CitiVelocityExcelClient``; counts every wire call."""

    def __init__(
        self,
        value: float = FRESH,
        omit: Optional[pd.Timestamp] = OMIT,
        serve_from: Optional[pd.Timestamp] = None,
        value_for: Optional[Callable[[str], float]] = None,
    ):
        self.calls: List[Dict[str, Any]] = []
        self.value = value
        self.value_for = value_for
        self.omit = omit
        #: Earliest row this transport has any history for. Used to manufacture
        #: reference points with NO row at or before them, which is the only way
        #: a genuine NaN appears in a direct frame.
        self.serve_from = serve_from

    def fetch_timeseries(
        self,
        tags: Sequence[str],
        freq: str,
        *,
        period: Optional[str] = None,
        start: Optional[Any] = None,
        end: Optional[Any] = None,
        price_point: str = "CLOSE",
    ) -> Dict[str, pd.Series]:
        self.calls.append({"tags": list(tags), "freq": freq, "start": start, "end": end})
        lo = pd.Timestamp(start) if start is not None else POISON_FROM
        hi = pd.Timestamp(end) if end is not None else pd.Timestamp(END)
        if self.serve_from is not None:
            lo = max(lo, self.serve_from)
        if lo > hi:
            return {}
        idx = pd.bdate_range(lo.normalize(), hi.normalize())
        if self.omit is not None:
            idx = idx[idx != self.omit]
        if len(idx) == 0:
            return {}
        return {
            str(t): pd.Series(
                [self.value if self.value_for is None else self.value_for(str(t))] * len(idx),
                index=idx,
                name=str(t),
            )
            for t in tags
        }

    def last_failures(self) -> Dict[str, str]:
        return {}

    def close(self) -> None:  # pragma: no cover - lifecycle only
        pass


class DownClient(StubCitiClient):
    """A transport that is present but broken - the add-in is not answering."""

    def fetch_timeseries(self, *a: Any, **k: Any):  # type: ignore[override]
        self.calls.append({"tags": list(a[0]) if a else []})
        raise CitiVelocityError("Excel add-in is not responding (simulated)")


class ExplodingClient(StubCitiClient):
    """A transport that must never be reached at all."""

    def fetch_timeseries(self, *a: Any, **k: Any):  # type: ignore[override]
        raise AssertionError("the transport was reached but must not have been")


@pytest.fixture(autouse=True)
def _no_com_no_supabase(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """Make a real COM connection impossible, and pin every cache root to tmp."""

    class _NoCOM:
        @staticmethod
        def connect(**kwargs: Any):
            raise AssertionError("CitiVelocityExcelClient.connect() was called")

    monkeypatch.setattr(_quotes_mod, "CitiVelocityExcelClient", _NoCOM)
    monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path / "default_root_guard"))
    monkeypatch.setenv("ARBS_CACHE_DIR", str(tmp_path / "arbs_cache_guard"))


def _poisoned_cache(base_dir: pathlib.Path, tags: Sequence[str] = (TAG,)) -> CitiVeloTagCache:
    """A tag cache holding a value no real market number could occupy."""
    cache = CitiVeloTagCache(base_dir=base_dir)
    idx = pd.bdate_range(POISON_FROM, pd.Timestamp(END))
    for tag in tags:
        cache.write(tag, "DAILY", pd.Series([POISON] * len(idx), index=idx), price_point="CLOSE")
    return cache


def _stack(tmp_path: pathlib.Path, *, client: Optional[StubCitiClient] = None, tags=(TAG,)):
    """(client, cache, mdp) over a poisoned tmp cache. Nothing production-rooted."""
    client = client or StubCitiClient()
    cache_dir = tmp_path / "tagcache"
    cache = _poisoned_cache(cache_dir, tags)
    quotes = CitiVeloQuotes(client=client, cache=cache)
    return client, cache, CitiVelocityMDP(quotes=quotes)


def _q(value: CitiVeloValue = CitiVeloValue.QUOTE) -> CitiVeloQuery:
    return CitiVeloQuery(citi_index=CURVE, tenor=TENOR, value=value)


#: A par curve that a solver can actually strip, offset by ``level`` so a poisoned
#: grid and a live one are unmistakable after repricing. Flat 999.0 does not
#: converge, which is why the quote-only sentinels cannot be reused here.
POISON_LEVEL = 8.0
FRESH_LEVEL = 3.0


def _par(level: float, tag: str) -> float:
    years = tenor_years(tag.rsplit(".", 1)[-1])
    return level + 0.90 * (1.0 - float(np.exp(-years / 3.0)))


def _reprice_stack(tmp_path: pathlib.Path):
    """(client, cache, mdp) whose cache holds a SOLVABLE but wrong par grid."""
    grid = T.ois_par_grid(CURVE)
    cache = CitiVeloTagCache(base_dir=tmp_path / "tagcache")
    idx = pd.bdate_range(POISON_FROM, pd.Timestamp(END))
    for tag in grid:
        cache.write(
            tag, "DAILY", pd.Series([_par(POISON_LEVEL, tag)] * len(idx), index=idx)
        )
    client = StubCitiClient(value_for=lambda t: _par(FRESH_LEVEL, t))
    quotes = CitiVeloQuotes(client=client, cache=cache)
    return client, cache, CitiVelocityMDP(quotes=quotes)


def _cache_files(root: pathlib.Path) -> Dict[str, tuple]:
    """``{relpath: (size, mtime_ns)}`` - enough to catch a write that rewrites in place."""
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ------------------------------------------------------------------ #
#                       the vocabulary is closed                     #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, DirectMode.OFF),
        (False, DirectMode.OFF),
        ("off", DirectMode.OFF),
        ("cached", DirectMode.OFF),
        (True, DirectMode.LIVE),
        ("live", DirectMode.LIVE),
        ("DIRECT", DirectMode.LIVE),
    ],
)
def test_direct_vocabulary_parses(raw, expected):
    assert parse_direct_mode(raw) is expected


@pytest.mark.parametrize("raw", ["nope", "of", "no-cache", "read_write", 3])
def test_direct_vocabulary_raises_on_anything_else(raw):
    """A typo in an opt-in must not silently resolve to 'serve from cache'."""
    with pytest.raises(DirectModeError):
        parse_direct_mode(raw)


# ------------------------------------------------------------------ #
#          the poisoned-cache test, BOTH directions                  #
# ------------------------------------------------------------------ #


def test_poisoned_cache_is_served_when_direct_is_absent(tmp_path: pathlib.Path):
    """OFF direction: this is what proves the harness can detect a cache hit.

    Without this, the ON direction below proves nothing - a test that cannot see
    a cache hit cannot testify that one did not happen.
    """
    client, _cache, mdp = _stack(tmp_path)
    tbb = TimeseriesBuilder()

    df = tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp})

    assert not df.empty
    col = df.columns[0]
    assert set(df[col].dropna().unique()) == {POISON}, df
    assert client.calls == [], "a fully-cached read must not reach the transport"


def test_direct_bypasses_the_poisoned_cache(tmp_path: pathlib.Path):
    """ON direction. The OMIT day is the assertion that matters.

    ``refetch-and-merge`` would also have called the transport AND returned fresh
    values on the four served days, so "fresh values came back" proves nothing.
    On the omitted day the two paths diverge and cannot be confused:

      * a real bypass has no cached row to merge with, so ``asof`` resolves that
        day to the previous LIVE row -> ``FRESH``;
      * refetch-and-merge leaves the poisoned row in place because the vendor did
        not overwrite it, so ``asof`` finds it -> ``POISON``.
    """
    client, _cache, mdp = _stack(tmp_path)
    tbb = TimeseriesBuilder()

    df = tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live")

    assert client.calls, "direct mode must reach the transport"
    col = df.columns[0]
    assert POISON not in set(df[col].dropna().unique()), f"cached value leaked into a direct read:\n{df}"
    assert set(df[col].dropna().unique()) == {FRESH}

    # The discriminator: the one day only a merge could have filled from cache.
    assert OMIT.date() in set(df.index), "the omitted day must still be a row"
    assert df.loc[OMIT.date(), col] == FRESH, (
        "the day the transport did not serve came back with the CACHED value - the "
        f"tag cache was merged in rather than bypassed:\n{df}"
    )


def test_direct_frame_is_a_full_grid_with_explicit_nans(tmp_path: pathlib.Path):
    """One row per reference point, NaN where nothing was served - never a short frame.

    The transport here has no history before 2026-01-08, so the first three
    reference points have no row at or before them. The cached path drops those
    rows entirely; direct mode must keep them and mark them NaN.
    """
    client = StubCitiClient(omit=None, serve_from=pd.Timestamp("2026-01-08"))
    quotes = CitiVeloQuotes(client=client, cache=_poisoned_cache(tmp_path / "tagcache"))
    mdp = CitiVelocityMDP(quotes=quotes)

    df = TimeseriesBuilder().get_timeseries(
        START, END, [_q()], mdps={"CITIVELO": mdp}, direct=True
    )

    expected = [d.date() for d in pd.bdate_range(START, END)]
    assert list(df.index) == expected, f"direct mode returned a short frame:\n{df}"
    col = df.columns[0]
    assert df[col].isna().sum() == 3, df
    assert set(df[col].dropna().unique()) == {FRESH}


def test_cached_path_returns_a_short_frame_for_the_same_gap(tmp_path: pathlib.Path):
    """The contrast that makes the test above meaningful, on an unpoisoned cache."""
    client = StubCitiClient(omit=None, serve_from=pd.Timestamp("2026-01-08"))
    quotes = CitiVeloQuotes(client=client, cache=CitiVeloTagCache(base_dir=tmp_path / "cold"))
    mdp = CitiVelocityMDP(quotes=quotes)

    df = TimeseriesBuilder().get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp})

    assert len(df.index) == 2, f"expected the cached path to drop the empty rows:\n{df}"


def test_direct_bypasses_the_cache_on_the_reprice_path(tmp_path: pathlib.Path):
    """The path where ``ignore_cache`` was measured to be a COMPLETE no-op.

    A model-valued query (``RL_RATE``) reprices off the whole par grid, so the
    grid is poisoned here too. Under the old plumbing this returned the poisoned
    curve regardless of any flag.
    """
    client, _cache, mdp = _reprice_stack(tmp_path)
    tbb = TimeseriesBuilder()

    # Control: without direct, the poisoned grid is what gets repriced.
    cached_df = tbb.get_timeseries(
        START, END, [_q(CitiVeloValue.RL_RATE)], mdps={"CITIVELO": mdp}
    )
    cached = cached_df[cached_df.columns[0]].dropna()
    assert len(cached) > 0
    assert cached.min() > POISON_LEVEL, f"the control did not reprice the poison:\n{cached_df}"

    df = tbb.get_timeseries(
        START, END, [_q(CitiVeloValue.RL_RATE)], mdps={"CITIVELO": mdp}, direct="live"
    )

    assert client.calls, "the reprice path must reach the transport under direct"
    served = df[df.columns[0]].dropna()
    assert len(served) > 0
    assert served.max() < POISON_LEVEL, (
        f"the poisoned par grid reached a direct reprice:\n{df}"
    )
    assert served.min() > FRESH_LEVEL


def test_direct_makes_one_window_fetch_not_one_per_timestep(tmp_path: pathlib.Path):
    """The reprice path must DELIVER the window, not refetch it per timestep.

    With no cache underneath, a warm sweep has nowhere to leave its rows, so a
    naive implementation goes to the wire once per reference point under the
    Excel lock. Five business days here: a per-timestep implementation shows at
    least five calls.
    """
    client, _cache, mdp = _reprice_stack(tmp_path)
    tbb = TimeseriesBuilder()

    tbb.get_timeseries(
        START, END, [_q(CitiVeloValue.RL_RATE)], mdps={"CITIVELO": mdp}, direct="live"
    )

    n_ref_points = len(pd.bdate_range(START, END))
    assert len(client.calls) < n_ref_points, (
        f"{len(client.calls)} transport calls for {n_ref_points} reference points - the "
        "window is being refetched per timestep"
    )


# ------------------------------------------------------------------ #
#                       no silent fallback                           #
# ------------------------------------------------------------------ #


def test_direct_raises_when_the_transport_is_down(tmp_path: pathlib.Path):
    """The cache holds a perfectly good answer. Direct mode must refuse it anyway."""
    client, _cache, mdp = _stack(tmp_path, client=DownClient())
    tbb = TimeseriesBuilder()

    with pytest.raises(CitiVelocityError):
        tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live")

    assert client.calls, "it must have TRIED the transport before failing"


def test_direct_raises_when_offline(tmp_path: pathlib.Path):
    """``offline=True`` serves the cache silently today; under direct it must raise."""
    cache = _poisoned_cache(tmp_path / "tagcache")
    quotes = CitiVeloQuotes(cache=cache, offline=True)
    mdp = CitiVelocityMDP(quotes=quotes)
    tbb = TimeseriesBuilder()

    # Control: without direct, the cached value is served and nothing raises.
    df = tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp})
    assert set(df[df.columns[0]].dropna().unique()) == {POISON}

    with pytest.raises(CitiVelocityError) as excinfo:
        tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live")
    assert "offline" in str(excinfo.value).lower()


def test_direct_raises_naming_a_tag_the_addin_refused(tmp_path: pathlib.Path):
    """An unserved tag must be named, not silently dropped to a missing column."""
    client, _cache, mdp = _stack(tmp_path)
    # A transport that answers, but with nothing.
    client.omit = None
    client.value = FRESH

    class _EmptyClient(StubCitiClient):
        def fetch_timeseries(self, tags, freq, **k):  # type: ignore[override]
            self.calls.append({"tags": list(tags)})
            return {}

        def last_failures(self):
            return {TAG: "empty"}

    empty = _EmptyClient()
    quotes = CitiVeloQuotes(client=empty, cache=_poisoned_cache(tmp_path / "c2"))
    mdp2 = CitiVelocityMDP(quotes=quotes)

    with pytest.raises(CitiVelocityError) as excinfo:
        TimeseriesBuilder().get_timeseries(
            START, END, [_q()], mdps={"CITIVELO": mdp2}, direct="live"
        )
    message = str(excinfo.value)
    assert TAG in message, message
    assert "empty" in message, message


def test_direct_refuses_a_cache_backed_mdp(tmp_path: pathlib.Path):
    """Nobody may hand ``CitiVelocityTB`` a cached MDP and call the result live."""
    _client, _cache, mdp = _stack(tmp_path)
    router = CitiVelocityTB(mdp, show_tqdm=False)

    with pytest.raises(CitiVelocityError) as excinfo:
        router.get_timeseries(START, END, [_q()], direct="live")
    assert "cache-backed" in str(excinfo.value)


def test_direct_rejects_ignore_cache(tmp_path: pathlib.Path):
    """``ignore_cache`` means refetch-AND-PERSIST here; it must not ride along."""
    _client, _cache, mdp = _stack(tmp_path)
    with pytest.raises(ValueError):
        TimeseriesBuilder().get_timeseries(
            START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live", ignore_cache=True
        )


def test_direct_rejects_end_live(tmp_path: pathlib.Path):
    _client, _cache, mdp = _stack(tmp_path)
    with pytest.raises(NotImplementedError):
        TimeseriesBuilder().get_timeseries(
            START, "live", [_q()], mdps={"CITIVELO": mdp}, direct="live"
        )


# ------------------------------------------------------------------ #
#                          the write policy                          #
# ------------------------------------------------------------------ #


def test_direct_writes_nothing_to_the_tag_cache(tmp_path: pathlib.Path):
    """Asserted on the FILESYSTEM: same files, same sizes, same mtimes."""
    _client, cache, mdp = _stack(tmp_path)
    root = pathlib.Path(cache.base_dir)
    before = _cache_files(root)
    assert before, "the fixture must have written a poisoned cache to compare against"

    TimeseriesBuilder().get_timeseries(
        START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live"
    )

    assert _cache_files(root) == before, "a direct read touched the tag cache"


def test_direct_creates_no_cache_directory_at_all(tmp_path: pathlib.Path):
    """With no cache to begin with, a direct read must not conjure one."""
    client = StubCitiClient()
    quotes = CitiVeloQuotes(client=client, cache=CitiVeloTagCache(base_dir=tmp_path / "never"))
    mdp = CitiVelocityMDP(quotes=quotes)

    TimeseriesBuilder().get_timeseries(
        START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live"
    )

    assert not (tmp_path / "never").exists(), "direct mode created a cache root"


def test_direct_does_not_bank_the_sibling_tags_it_fetched(tmp_path: pathlib.Path):
    """A reprice pulls the whole par grid as a hint. None of it may be written."""
    _client, cache, mdp = _reprice_stack(tmp_path)
    root = pathlib.Path(cache.base_dir)
    before = _cache_files(root)
    assert len(before) >= 40, "the fixture must have banked the whole grid to compare against"

    TimeseriesBuilder().get_timeseries(
        START, END, [_q(CitiVeloValue.RL_RATE)], mdps={"CITIVELO": mdp}, direct="live"
    )

    assert _cache_files(root) == before


def test_the_cached_path_still_banks(tmp_path: pathlib.Path):
    """The control for the two tests above: writing is what NORMAL mode does."""
    client = StubCitiClient()
    root = tmp_path / "cold"
    quotes = CitiVeloQuotes(client=client, cache=CitiVeloTagCache(base_dir=root))
    mdp = CitiVelocityMDP(quotes=quotes)

    TimeseriesBuilder().get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp})

    assert _cache_files(root), "the cached path must still persist what it fetched"


# ------------------------------------------------------------------ #
#                          non-Citi products                         #
# ------------------------------------------------------------------ #


def test_direct_refuses_a_non_citi_product_before_touching_anything(tmp_path: pathlib.Path):
    """FRB has no bypass, so it must be refused rather than quietly cache-served."""
    client, cache, mdp = _stack(tmp_path)
    root = pathlib.Path(cache.base_dir)
    before = _cache_files(root)

    with pytest.raises(NotImplementedError) as excinfo:
        TimeseriesBuilder().get_timeseries(
            START,
            END,
            [_q(), FixedRateBondQuery(cusip="912810TZ1")],
            mdps={"CITIVELO": mdp},
            direct="live",
        )

    message = str(excinfo.value)
    assert "FRB" in message, message
    assert client.calls == [], "the refusal must fire before any transport call"
    assert _cache_files(root) == before, "the refusal must fire before any cache write"


def test_direct_refuses_a_lone_non_citi_product(tmp_path: pathlib.Path):
    with pytest.raises(NotImplementedError):
        TimeseriesBuilder().get_timeseries(
            START, END, [FixedRateBondQuery(cusip="912810TZ1")], mdps={}, direct=True
        )


# ------------------------------------------------------------------ #
#                        THE REGRESSION TEST                         #
# ------------------------------------------------------------------ #


def test_default_path_is_structurally_unchanged(tmp_path: pathlib.Path, monkeypatch):
    """With ``direct`` absent, the CALL SEQUENCE must be what it was.

    Asserted structurally rather than by comparing frames: a frame can match while
    the path underneath changed completely, which is exactly how a cache tier goes
    missing without anyone noticing.

    Four structural facts, all of which held before this change:
      1. ``_route_product_timeseries`` is still the entry point for CITIVELO;
      2. the route lands in ``_GenericTimeseriesTB``, because CITIVELO is NOT
         registered in ``_get_specialized_router`` - wiring it there would be a
         behaviour change in its own right (8 CVTSHIST -> 1, different call
         sequence), so this change deliberately did not;
      3. the computed-TS (L1) probe is therefore NOT reached on this product -
         it lives on the specialized-router branch. Asserting its ABSENCE locks
         the route: if CITIVELO ever gains a specialized router, this fails;
      4. ``CitiVeloTagCache.get`` is still the reader underneath, and the value
         still comes from it.
    """
    _client, _cache, mdp = _stack(tmp_path)
    tbb = TimeseriesBuilder()

    route_calls: List[str] = []
    real_route = TimeseriesBuilder._route_product_timeseries

    def _spy_route(self, **kwargs):
        route_calls.append(str(kwargs.get("product")))
        return real_route(self, **kwargs)

    monkeypatch.setattr(TimeseriesBuilder, "_route_product_timeseries", _spy_route)

    probe_calls: List[Any] = []
    real_probe = TimeseriesBuilder._probe_routed_product_computed_cache

    def _spy_probe(self, **kwargs):
        probe_calls.append(kwargs.get("product"))
        return real_probe(self, **kwargs)

    monkeypatch.setattr(TimeseriesBuilder, "_probe_routed_product_computed_cache", _spy_probe)

    cache_get_calls: List[Sequence[str]] = []
    real_get = CitiVeloTagCache.get

    def _spy_get(self, tags, *a, **k):
        cache_get_calls.append(list(tags))
        return real_get(self, tags, *a, **k)

    monkeypatch.setattr(CitiVeloTagCache, "get", _spy_get)

    df = tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp})

    # 1. the product-routing entry point still runs
    assert route_calls == ["CITIVELO"], route_calls
    # 2. routing is unchanged
    assert "CITIVELO" in tbb._generic_router_cache, (
        "CITIVELO no longer routes through _GenericTimeseriesTB - the default route moved"
    )
    assert tbb._specialized_router_cache == {}, (
        "a specialized router was registered for the default path"
    )
    # 3. the L1 probe stays on the branch CITIVELO does not take
    assert probe_calls == [], (
        f"the computed-TS probe was reached for CITIVELO ({probe_calls}); the route moved"
    )
    # 4. the tag cache is still the reader
    assert cache_get_calls, "CitiVeloTagCache.get was not called on the default path"
    assert any(TAG in tags for tags in cache_get_calls)
    # and the data still comes from it
    assert set(df[df.columns[0]].dropna().unique()) == {POISON}


def test_default_path_frame_is_unchanged_by_the_new_parameter(tmp_path: pathlib.Path):
    """Belt to the structural braces: the FRAME must be identical too.

    A frame comparison alone cannot catch a moved cache tier, which is why the
    structural test above exists - but a structural test alone cannot catch a
    changed value, so both are here.
    """
    _c1, _cache1, mdp1 = _stack(tmp_path / "a")
    _c2, _cache2, mdp2 = _stack(tmp_path / "b")

    without = TimeseriesBuilder().get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp1})
    explicit_off = TimeseriesBuilder().get_timeseries(
        START, END, [_q()], mdps={"CITIVELO": mdp2}, direct=False
    )
    pd.testing.assert_frame_equal(without, explicit_off)


def test_direct_router_never_leaks_into_the_router_caches(tmp_path: pathlib.Path):
    """A cache-less provider pinned in ``_generic_router_cache`` would poison later calls."""
    _client, _cache, mdp = _stack(tmp_path)
    tbb = TimeseriesBuilder()

    tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live")
    assert tbb._generic_router_cache == {}
    assert tbb._specialized_router_cache == {}

    # ...and a subsequent normal call still serves the cache.
    df = tbb.get_timeseries(START, END, [_q()], mdps={"CITIVELO": mdp})
    assert set(df[df.columns[0]].dropna().unique()) == {POISON}


def test_direct_reader_borrows_the_parent_client(tmp_path: pathlib.Path):
    """One logical reader must never open two COM sessions."""
    client, _cache, mdp = _stack(tmp_path)
    direct = mdp.direct_mdp()

    assert direct.quotes.is_direct
    assert direct.quotes.cache is None
    assert direct.quotes.client() is client
    direct.close()
    # Closing the sibling must not have taken the parent's client away.
    assert mdp.quotes.client() is client


def test_direct_raises_when_the_addin_fails_mid_reprice(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A transport refusal PART WAY through a reprice must raise, not become a NaN.

    This is the case a whole-frame check cannot see. The repricing loop used to catch
    every exception per (timestep, query) pair and fill the hole with NaN, and the only
    gate downstream -- ``_assert_direct_frame_usable`` -- rejects a column only when it
    is NaN at EVERY reference point. So an add-in that died on some timesteps and
    recovered produced a healthy-looking column with holes in it, indistinguishable from
    the genuine no-data NaNs that ``test_direct_frame_is_a_full_grid_with_explicit_nans``
    deliberately preserves.

    The distinction being asserted is transport-vs-pricing, not all-vs-nothing: a curve
    that will not solve because the structure did not exist yet is still a NaN.
    """
    import TB.CitiVelocityTB as _tb

    _client, _cache, mdp = _reprice_stack(tmp_path)

    real_resolve = _tb.resolve_query
    state = {"n": 0}

    def _flaky_resolve(*a: Any, **k: Any):
        state["n"] += 1
        # Succeed first, so at least one (timestep, query) pair lands -- that is the
        # precondition under which the old code filled NaN instead of raising.
        if state["n"] == 2:
            raise CitiVelocityError("Excel add-in stopped responding (simulated mid-run)")
        return real_resolve(*a, **k)

    monkeypatch.setattr(_tb, "resolve_query", _flaky_resolve)

    with pytest.raises(CitiVelocityError) as excinfo:
        TimeseriesBuilder().get_timeseries(
            START, END, [_q(CitiVeloValue.RL_RATE)], mdps={"CITIVELO": mdp}, direct="live"
        )

    msg = str(excinfo.value)
    assert "stopped responding" in msg, msg
    assert "NaN" in msg or "hole" in msg, f"the refusal must say why it refused:\n{msg}"


# ══════════════════════════════════════════════════════════════════════════
# The two guarantees the verifier found sold in the docs and tested nowhere.
# Both were proven live by mutation: the code is correct today and nothing
# stopped a future edit from regressing it.
# ══════════════════════════════════════════════════════════════════════════


def test_direct_writes_nothing_to_the_DEFAULT_cache_root_either(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """The other write-policy tests watch the PARENT reader's root, and only that.

    A direct read that banked into ``cache.default_cache_dir()`` -- in production
    %LOCALAPPDATA%/ARBS/ARBS/Cache/citivelo_excel, nowhere near the fixture's tmp_path --
    passed all of them. Verified by mutation: banking the fetched series into a freshly
    constructed ``CitiVeloTagCache()`` inside the bypass branch left the whole file green
    while writing two real files into the default root.

    The documented promise is absolute: "Nothing is written, anywhere. No tag parquet, no
    sidecar, not even a directory." So the default root is redirected somewhere empty and
    asserted to STAY empty, which is the only way to test "anywhere".
    """
    import MDP.CitiVelocityExcel.cache as C

    default_root = tmp_path / "pretend_localappdata"
    monkeypatch.setattr(C, "default_cache_dir", lambda: default_root)
    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(default_root))

    _client, cache, mdp = _stack(tmp_path)
    parent_before = _cache_files(pathlib.Path(cache.base_dir))

    TimeseriesBuilder().get_timeseries(
        START, END, [_q()], mdps={"CITIVELO": mdp}, direct="live"
    )

    assert _cache_files(pathlib.Path(cache.base_dir)) == parent_before
    assert _cache_files(default_root) == {}, (
        f"a direct read wrote into the DEFAULT cache root: "
        f"{sorted(_cache_files(default_root))}"
    )
    assert not default_root.exists(), "direct mode created the default cache root"


def test_direct_switches_off_the_pricers_absence_memo(tmp_path: pathlib.Path):
    """A tag the add-in refused must be RE-ASKED under direct, not remembered as absent.

    ``CitiVeloPricer`` keeps a ``_missing`` set so a tag that came back unserved is not
    re-requested for the rest of the run. That is a silent fallback under a direct read:
    a transient add-in failure becomes a permanent "no such tag" for the session, and the
    caller sees a gap it cannot distinguish from real absence. ``prefetch`` therefore
    skips the memo when ``direct`` is set.

    The commit message and the ``get_timeseries`` docstring both sell this as a named
    guarantee, and nothing tested it -- removing the ``if not self.direct:`` guard left
    all 35 tests green while measurably changing behaviour (2 wire calls became 1).
    """
    from MDP.CitiVelocityExcel.pricer import CitiVeloPricer

    missing_tag = "RATES.OIS.USD_SOFR.PAR.999Y"
    asked: List[List[str]] = []

    class _RefusingClient(StubCitiClient):
        def fetch_timeseries(self, tags, freq, **kw):  # type: ignore[override]
            asked.append(sorted(str(t) for t in tags))
            return {}

    quotes = CitiVeloQuotes(client=_RefusingClient(), cache=False)

    direct_pricer = CitiVeloPricer(quotes=quotes, as_of=END, direct=True)
    direct_pricer.prefetch([missing_tag])
    direct_pricer.prefetch([missing_tag])
    assert len(asked) == 2, (
        "under direct the memo must be OFF, so the second ask reaches the wire again; "
        f"saw {len(asked)} call(s)"
    )

    asked.clear()
    cached_pricer = CitiVeloPricer(quotes=quotes, as_of=END, direct=False)
    cached_pricer.prefetch([missing_tag])
    cached_pricer.prefetch([missing_tag])
    assert len(asked) == 1, (
        "the CONTROL: without direct the memo IS honoured, which is what makes the "
        f"assertion above meaningful; saw {len(asked)} call(s)"
    )
