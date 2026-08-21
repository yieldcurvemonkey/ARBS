r"""The intraday depth warm, tested where it can go quietly wrong.

The job exists because Golds could not be priced intraday, and the reason turned
out to be that nothing had ever asked the vendor for ranks 18-20 -- not that the
vendor lacked them. Three things about it are worth pinning, and none of them is
"does it fetch":

* it must **target** rather than crawl, or the request count is six figures;
* it must **refuse** the live-quote window, where a fetch writes nothing under
  the key it is trying to fill and still costs a request;
* it must **fail loudly** when it wrote keys and moved no depth, because that is
  the exact shape of the silent failure the settle warm already has on record.

Every test here is offline. The probe is a set of keys.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo

import pytest

from RVUtils.ConvexityRV import ca_intraday as CI
from scripts import warm_sr3_intraday_depth as W

CT = zoneinfo.ZoneInfo(CI.TAPE_TZ_NAME)
DAY = dt.date(2026, 8, 19)


def _probe_from(keys):
    """A `key -> bool` probe over a literal key set — the local shards, faked."""
    ks = set(keys)
    return lambda k: k in ks


def _keys_for(day, symbols, minutes):
    out = []
    for m in minutes:
        ts = dt.datetime.combine(day, dt.time(m // 60, m % 60), tzinfo=CT)
        for s in symbols:
            out.extend(CI.tape_keys(ts, s))
    return out


def test_the_ladder_is_the_front_twenty_quarterlies():
    lad = W._strip_symbols(DAY, 20)
    assert len(lad) == 20 and len(set(lad)) == 20
    # a strip is contiguous quarterlies, so no month may repeat within a year
    assert all(s.startswith("SR3") for s in lad)


def test_only_the_missing_ranks_are_requested():
    """Ranks 1..17 come free from the nightly curve builds.

    Re-fetching them would multiply the vendor cost by six and buy nothing, so
    the plan's request list must start at `from_rank`, not at 1. This is the
    whole economic argument for the job being runnable at all.
    """
    probe = _probe_from([])
    p = W.plan_day(probe, DAY, depth=20, from_rank=18)
    assert len(p["missing_symbols"]) == 3
    assert p["missing_symbols"] == p["ladder"][17:20]


def test_instants_are_taken_from_the_tape_not_from_a_grid():
    """The targeting step, which is what keeps this bounded.

    A blind 07:00-16:00 one-minute grid is 541 instants. Anchoring on the
    minutes a front contract is already cached at turns that into exactly the
    minutes that can actually be completed.
    """
    lad = W._strip_symbols(DAY, 20)
    present_minutes = [8 * 60, 8 * 60 + 1, 13 * 60]
    probe = _probe_from(_keys_for(DAY, [lad[0]], present_minutes))

    got = W.instants_present(probe, DAY, lad[0])
    assert [t.hour * 60 + t.minute for t in got] == present_minutes

    # and a grid over the same window would have been two orders larger
    full = W.instants_present(lambda k: True, DAY, lad[0])
    assert len(full) > 500 and len(got) == 3


def test_an_instant_already_at_depth_is_not_refetched():
    """Idempotence is what makes this resumable, and a no-op on a warm cache."""
    lad = W._strip_symbols(DAY, 20)
    minutes = [9 * 60]
    probe = _probe_from(_keys_for(DAY, lad, minutes))       # ALL twenty present
    p = W.plan_day(probe, DAY, depth=20, from_rank=18)
    assert len(p["stamps"]) == 1
    assert p["todo"] == []
    assert p["already_deep"] == 1


def test_a_hole_below_the_target_still_counts_as_todo():
    """Contiguity, not a count.

    A date holding ranks 1..16 and 18..20 has 19 of 20 symbols and a contiguous
    depth of 16. Warming rank 18 there is right -- but the *reason* it is still
    todo has to be the contiguous measure, or a date one hole short of usable
    reads as finished.
    """
    lad = W._strip_symbols(DAY, 20)
    minutes = [9 * 60]
    have = lad[:16] + lad[17:]                              # rank 17 missing
    probe = _probe_from(_keys_for(DAY, have, minutes))
    p = W.plan_day(probe, DAY, depth=20, from_rank=18)
    assert len(p["todo"]) == 1
    assert list(p["before"].values()) == [16]


def test_the_live_quote_window_is_refused():
    """Inside the guard the MDP stops reading the cache at all.

    A fetch there writes nothing under the key this job is filling and still
    costs a request, so the acceptance measurement afterwards would read as "no
    depth gained" for a reason that has nothing to do with the vendor.
    """
    now = dt.datetime.now(dt.timezone.utc)
    just_now = now - dt.timedelta(minutes=CI.LIVE_QUOTE_GUARD_MINUTES - 5)
    ok, why = W._instant_is_warmable(just_now)
    assert not ok and "live-quote" in why

    old = now - dt.timedelta(days=2)
    ok, _ = W._instant_is_warmable(old)
    assert ok


def _summary(**kw):
    base = {
        "dry_run": False, "dates_touched": 1, "gained": 0, "unchanged": 1,
        "instants_warmed": 19, "instants_reached_depth": 0,
        "depth_before": {"2026-08-19": {"at_target": 0, "of": 19, "deepest": 17}},
        "depth_after": {"2026-08-19": {"at_target": 0, "of": 19, "deepest": 17}},
        "failures": {}, "instants_seen": 19, "instants_already_deep": 0,
        "instants_skipped_live": 0, "instants_failed": 0,
    }
    base.update(kw)
    return base


def test_a_warm_that_reaches_no_instant_exits_nonzero():
    """The silent failure this job's acceptance check exists for.

    A fetch that writes a differently-shaped key reports thousands of successful
    writes and recovers exactly nothing. Keys written is therefore not the
    criterion; instants that reached the target depth are.
    """
    assert W._report(_summary()) == 1

    reached = _summary(
        gained=1, unchanged=0, instants_reached_depth=19,
        depth_after={"2026-08-19": {"at_target": 19, "of": 19, "deepest": 20}})
    assert W._report(reached) == 0


def test_progress_is_counted_per_instant_not_by_the_days_deepest():
    """The defect a real run found, pinned so it cannot come back.

    The first version measured `max(depth over the day's instants)` before and
    after. That is not monotone in progress: one already-deep instant pins the
    max at the target, and every subsequent completion moves it by nothing. A
    run that warmed 478 instants with ZERO failures printed "NO date gained
    depth" and exited 1, because 19 instants were already at 20.

    A false negative rather than a false positive, so nothing was silently
    accepted -- but a job that reports failure while working is broken in the
    way that gets its alerts muted, and then the real failure is invisible too.
    """
    partial = _summary(
        gained=1, unchanged=0, instants_warmed=478,
        instants_reached_depth=478, instants_already_deep=19,
        instants_seen=541,
        depth_before={"2026-08-19": {"at_target": 19, "of": 541, "deepest": 20}},
        depth_after={"2026-08-19": {"at_target": 497, "of": 541, "deepest": 20}})

    # the day's DEEPEST is identical before and after -- the old measure saw
    # nothing at all here
    b = partial["depth_before"]["2026-08-19"]
    a = partial["depth_after"]["2026-08-19"]
    assert a["deepest"] == b["deepest"] == 20
    # ... and the count moved by 478, which is what actually happened
    assert a["at_target"] - b["at_target"] == 478
    assert W._report(partial) == 0


def test_nothing_to_do_is_success_not_failure():
    """A no-op on a warm cache is the daily run's normal outcome."""
    nothing = _summary(dates_touched=0, unchanged=0, instants_warmed=0,
                       instants_seen=300, instants_already_deep=300,
                       depth_before={}, depth_after={})
    assert W._report(nothing) == 0


def test_the_planning_path_cannot_reach_the_network():
    """`--dry-run` is the measurement mode, and it has to be trustworthy.

    `plan_day` and `instants_present` take a probe rather than an MDP precisely
    so this is structural: there is no client to call.

    Checked on the AST, not on the source text. The first version of this test
    grepped for the string "fetch" and failed on the word "fetching" in a
    docstring -- a check that reports on prose is not a check on behaviour.
    """
    import ast
    import inspect
    import textwrap

    FETCHERS = {"fetch_pricers_flat", "get_data", "get_pricer", "get_timeseries"}
    for fn in (W.plan_day, W.instants_present, W._instant_is_warmable,
               W._strip_symbols):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not (called & FETCHERS), (
            f"{fn.__name__} calls {called & FETCHERS}; the planning path must "
            f"be answerable from the local shards alone")


def test_the_mutation_that_would_break_it_is_caught():
    """The test above has to be able to fail, so here it is failing.

    A planning function that quietly fetched would make --dry-run a liar and
    would turn a 5-second measurement into a 541-request crawl.
    """
    import ast
    import textwrap

    leaky = textwrap.dedent("""
        def plan_day(probe, day, depth, from_rank):
            mdp.fetch_pricers_flat(["SR3U26"], timestamp=day)
            return {}
    """)
    tree = ast.parse(leaky)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "fetch_pricers_flat" in called


def test_the_source_is_the_minute_tape_and_never_the_settle():
    """One character apart in the key, and a whole different series."""
    import inspect

    src = inspect.getsource(W)
    assert "SETTLE_FUTURES_SOURCE" not in src
    assert "CI.INTRADAY_FUTURES_SOURCE" in src


@pytest.mark.parametrize("step", [1, 5, 30])
def test_the_step_only_thins_the_grid_it_does_not_move_it(step):
    """A coarser step must sample the same clock, not a shifted one.

    If it drifted, the "before" and "after" depth would be measured at different
    instants and the acceptance check would compare two different things.
    """
    lad = W._strip_symbols(DAY, 20)
    got = W.instants_present(lambda k: True, DAY, lad[0], step_minutes=step)
    assert got[0].hour == 7 and got[0].minute == 0
    assert all((t - got[0]).total_seconds() % (step * 60) == 0 for t in got)
