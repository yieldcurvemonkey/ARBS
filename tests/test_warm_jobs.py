r"""The warm-ordering guard, and proof that it can actually fail.

The guard exists to catch a reordering that does not raise on its own: a value
job scheduled before the store warm it reads, which sends the source down its
live path — for the Velocity sources, opening Excel on an unattended 04:00
scheduled task.

So every test here is written to fail if the guard is weakened, and the
"correct order passes" tests are paired with "inverted order raises" tests. A
guard that only ever sees valid input is indistinguishable from no guard.
"""

from __future__ import annotations

import pytest

from utils.warm_jobs import (
    STORE,
    VALUE,
    WarmJob,
    WarmOrderError,
    assert_ordered,
    assert_unique_providers,
    check,
    describe,
)


def _noop(start, end):
    return None


def _store(name, *provides):
    return WarmJob(name=name, fn=_noop, kind=STORE, provides=tuple(provides))


def _value(name, *requires):
    return WarmJob(name=name, fn=_noop, kind=VALUE, requires=tuple(requires))


# ── ordering ─────────────────────────────────────────────────────────────

def test_store_before_value_is_accepted():
    assert_ordered([_store("warm A", "ASSET-A"), _value("read A", "ASSET-A")])


def test_value_before_store_raises():
    """The whole point. Invert the two lines above and it must fail."""
    with pytest.raises(WarmOrderError, match="later in the list"):
        assert_ordered([_value("read A", "ASSET-A"), _store("warm A", "ASSET-A")])


def test_the_error_names_the_consumer_the_asset_and_the_producer():
    with pytest.raises(WarmOrderError) as exc:
        assert_ordered([_value("read A", "ASSET-A"), _store("warm A", "ASSET-A")])
    msg = str(exc.value)
    assert "read A" in msg and "ASSET-A" in msg and "warm A" in msg


def test_the_error_explains_the_consequence():
    """A message that says only 'out of order' does not tell the next person why."""
    with pytest.raises(WarmOrderError, match="LIVE"):
        assert_ordered([_value("read A", "ASSET-A"), _store("warm A", "ASSET-A")])


def test_a_job_requiring_what_it_provides_raises():
    job = WarmJob(name="self", fn=_noop, kind=STORE, provides=("X",), requires=("X",))
    with pytest.raises(WarmOrderError, match="the same job"):
        assert_ordered([job])


def test_requirement_nobody_in_this_list_provides_is_allowed():
    """Value jobs legitimately read stores warmed on another schedule."""
    assert_ordered([_value("read external", "SOMEONE-ELSES-ASSET")])


def test_multiple_requirements_all_checked():
    jobs = [
        _store("warm A", "A"),
        _value("reads A and B", "A", "B"),
        _store("warm B", "B"),
    ]
    with pytest.raises(WarmOrderError, match="'B'"):
        assert_ordered(jobs)


def test_a_long_correct_chain_passes():
    jobs = [
        _store("s1", "A"),
        _store("s2", "B"),
        _value("v1", "A"),
        _value("v2", "A", "B"),
        _store("s3", "C"),
        _value("v3", "A", "B", "C"),
    ]
    assert_ordered(jobs)


def test_moving_one_store_job_down_breaks_the_chain():
    """Mutation, expressed as a test: relocate s2 after its consumer."""
    jobs = [
        _store("s1", "A"),
        _value("v1", "A"),
        _value("v2", "A", "B"),
        _store("s2", "B"),
    ]
    with pytest.raises(WarmOrderError):
        assert_ordered(jobs)


# ── unique providers (write_day replaces a whole day partition) ──────────

def test_distinct_assets_are_accepted():
    assert_unique_providers([_store("a", "A"), _store("b", "B")])


def test_two_jobs_writing_the_same_asset_raises():
    with pytest.raises(WarmOrderError, match="same store asset"):
        assert_unique_providers([_store("a", "SHARED"), _store("b", "SHARED")])


def test_the_shared_asset_error_explains_the_silent_deletion():
    with pytest.raises(WarmOrderError, match="silently delete"):
        assert_unique_providers([_store("a", "SHARED"), _store("b", "SHARED")])


def test_check_runs_both_invariants():
    with pytest.raises(WarmOrderError, match="same store asset"):
        check([_store("a", "S"), _store("b", "S")])
    with pytest.raises(WarmOrderError, match="later in the list"):
        check([_value("v", "S"), _store("a", "S")])


# ── the declaration itself must be honest ────────────────────────────────

def test_a_value_job_cannot_claim_to_provide_a_store_asset():
    """Otherwise a mislabelled job would satisfy a requirement it never writes."""
    with pytest.raises(ValueError, match="is a value job but declares provides"):
        WarmJob(name="liar", fn=_noop, kind=VALUE, provides=("A",))


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind must be"):
        WarmJob(name="x", fn=_noop, kind="whenever")


def test_as_tuple_matches_the_runner_shape():
    j = _store("a", "A")
    assert j.as_tuple() == ("a", _noop)


def test_describe_shows_the_dependency_structure():
    text = describe([_store("warm A", "ASSET-A"), _value("read A", "ASSET-A")])
    assert "[store]" in text and "[value]" in text
    assert "provides: ASSET-A" in text and "requires: ASSET-A" in text


# ── the real registry in the shipped warmer ──────────────────────────────

def test_the_shipped_warmer_registry_is_ordered_and_unique():
    """The guard is worthless if the actual job list never goes through it."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "daily_cache_warmer.py"
    spec = importlib.util.spec_from_file_location("_warmer_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    jobs = getattr(mod, "WARM_JOBS", None)
    assert jobs is not None, "daily_cache_warmer must expose WARM_JOBS"
    assert all(isinstance(j, WarmJob) for j in jobs)
    check(jobs)          # must not raise
    # and the legacy shape the runner consumes is still derivable
    assert getattr(mod, "JOBS", None) == [j.as_tuple() for j in jobs]


def test_the_shipped_registry_would_fail_the_guard_if_inverted():
    """Proves the registry actually has a dependency for the guard to protect.

    Without this, a registry where no job declares `requires` would pass
    `test_the_shipped_warmer_registry_is_ordered_and_unique` vacuously.
    """
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "daily_cache_warmer.py"
    spec = importlib.util.spec_from_file_location("_warmer_under_test2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    jobs = list(mod.WARM_JOBS)
    provided = {a for j in jobs for a in j.provides}
    consumed = {a for j in jobs for a in j.requires}
    linked = provided & consumed
    assert linked, (
        "No job in the shipped registry requires an asset another job provides, so the "
        "ordering guard is vacuous on the real list. Declare the dependency."
    )
    with pytest.raises(WarmOrderError):
        assert_ordered(list(reversed(jobs)))
