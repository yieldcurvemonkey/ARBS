"""Precedence rules for :mod:`utils.storage_paths`.

The property that actually matters here is the *negative* one: with no
environment variable set, every store must still resolve to its historical
repo-relative path. ~60 sibling worktrees run older code against their own
copies of these directories, and a resolver that quietly answered ``D:\\...``
because a drive happened to be mounted would point them all at an empty tree --
which reads as a cold cache, not as an error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.storage_paths import DATA_ROOT_ENV, REPO_ROOT, data_root, repo_store


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Neither the shared root nor any per-store pin leaks in from the shell."""
    monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
    monkeypatch.delenv("ARBS_COMPUTED_TS_DIR", raising=False)
    monkeypatch.delenv("ARBS_TRADE_TAPE_CACHE", raising=False)
    monkeypatch.delenv("ARBS_SDR_CACHE_DIR", raising=False)


def test_unset_root_resolves_to_the_repo():
    assert data_root() is None
    assert repo_store("data", "ts") == REPO_ROOT / "data" / "ts"


def test_unset_root_ignores_a_declared_env_var():
    """Naming a variable that is not set must not change the answer."""
    assert repo_store("data", "ts", env_var="ARBS_COMPUTED_TS_DIR") == REPO_ROOT / "data" / "ts"


def test_data_root_mirrors_the_repo_relative_layout(monkeypatch):
    """The path under the root is the same path it had under the checkout.

    That mirroring is what makes a migration a plain directory move and leaves
    the two trees diffable afterwards.
    """
    monkeypatch.setenv(DATA_ROOT_ENV, r"D:\ARBS_DATA\repo")
    assert repo_store("data", "ts") == Path(r"D:\ARBS_DATA\repo") / "data" / "ts"
    assert repo_store("notebooks", "sdr", "_cache", "trade_tape") == Path(
        r"D:\ARBS_DATA\repo"
    ) / "notebooks" / "sdr" / "_cache" / "trade_tape"


def test_per_store_variable_beats_the_shared_root(monkeypatch):
    monkeypatch.setenv(DATA_ROOT_ENV, r"D:\ARBS_DATA\repo")
    monkeypatch.setenv("ARBS_COMPUTED_TS_DIR", r"E:\pinned\ts")
    assert repo_store("data", "ts", env_var="ARBS_COMPUTED_TS_DIR") == Path(r"E:\pinned\ts")
    # ... and pinning one store leaves its neighbours on the shared root.
    assert repo_store("sdr_cache", env_var="ARBS_SDR_CACHE_DIR") == Path(r"D:\ARBS_DATA\repo") / "sdr_cache"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_count_as_unset(monkeypatch, blank):
    """An exported-but-empty variable must not resolve to the drive root."""
    monkeypatch.setenv(DATA_ROOT_ENV, blank)
    monkeypatch.setenv("ARBS_COMPUTED_TS_DIR", blank)
    assert data_root() is None
    assert repo_store("data", "ts", env_var="ARBS_COMPUTED_TS_DIR") == REPO_ROOT / "data" / "ts"


@pytest.mark.parametrize("spelling", ["./data/ts", "data/ts", ".\\data\\ts"])
def test_the_default_spelled_longhand_follows_the_store_pin(monkeypatch, spelling):
    """``"./data/ts"`` is passed as a literal by ~15 call sites, not as ``None``.

    It has to land wherever the store is actually configured, which is not
    necessarily under ``ARBS_DATA_ROOT``: ``data/ts`` is pinned separately
    because its 1.92 M files cost ~3x their logical size in cluster rounding.
    Sending these call sites to the shared root would give them an empty tree,
    which reads as a cold cache rather than as an error.
    """
    import importlib

    import Caching.computed_timeseries_store as cts

    monkeypatch.setenv(DATA_ROOT_ENV, r"D:\ARBS_DATA\repo")
    monkeypatch.setenv("ARBS_COMPUTED_TS_DIR", r"C:\pinned\data\ts")
    importlib.reload(cts)
    try:
        assert cts._resolve_computed_timeseries_base_dir(spelling) == Path(r"C:\pinned\data\ts")
        assert cts._resolve_computed_timeseries_base_dir(None) == Path(r"C:\pinned\data\ts")
    finally:
        monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
        monkeypatch.delenv("ARBS_COMPUTED_TS_DIR", raising=False)
        importlib.reload(cts)


def test_other_relative_paths_follow_the_data_root(monkeypatch):
    """Only the store's own default is special-cased; everything else mirrors."""
    from Caching.computed_timeseries_store import _resolve_computed_timeseries_base_dir as res

    monkeypatch.setenv(DATA_ROOT_ENV, r"D:\ARBS_DATA\repo")
    assert res("data/ts_warm") == Path(r"D:\ARBS_DATA\repo\data\ts_warm")


def test_relative_base_dir_is_unchanged_when_no_root_is_set():
    from Caching.computed_timeseries_store import REPO_ROOT as CTS_REPO_ROOT
    from Caching.computed_timeseries_store import _resolve_computed_timeseries_base_dir as res

    assert res("./data/ts") == (CTS_REPO_ROOT / "data" / "ts").resolve()
    assert res("data/ts_warm") == (CTS_REPO_ROOT / "data" / "ts_warm").resolve()


def test_absolute_base_dir_ignores_the_data_root(monkeypatch, tmp_path):
    """Every test in the suite passes an absolute tmp_path; it must win."""
    from Caching.computed_timeseries_store import _resolve_computed_timeseries_base_dir as res

    monkeypatch.setenv(DATA_ROOT_ENV, r"D:\ARBS_DATA\repo")
    assert res(str(tmp_path)) == tmp_path


def test_callers_agree_with_the_resolver(monkeypatch):
    """The modules that were rewired read the same location the resolver names."""
    monkeypatch.setenv(DATA_ROOT_ENV, r"D:\ARBS_DATA\repo")

    import importlib

    import Caching.computed_timeseries_store as cts
    import SDRUtils.analytics.trade_tape as tt

    importlib.reload(cts)
    importlib.reload(tt)
    try:
        assert cts.DEFAULT_COMPUTED_TS_BASE_DIR == repo_store("data", "ts", env_var="ARBS_COMPUTED_TS_DIR")
        assert Path(tt.DEFAULT_CACHE_DIR) == repo_store(
            "notebooks", "sdr", "_cache", "trade_tape", env_var="ARBS_TRADE_TAPE_CACHE"
        )
    finally:
        # Module-level constants are captured at import; leave them as the rest
        # of the session expects to find them.
        monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
        importlib.reload(cts)
        importlib.reload(tt)
