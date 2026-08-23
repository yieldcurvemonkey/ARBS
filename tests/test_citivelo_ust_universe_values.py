"""What the UST universe warm asks Citi for, and when it is allowed to alarm.

Three separate things, all of which were wrong in the same job:

* INTRADAY carried PRICE and YIELD only, so the two spread reads an RV book
  watches during a session had no minute series at all.
* EOD carried the six fields Citi retired on 2025-10-03, which still validate
  and return four years of rows and then nothing - guaranteeing six permanently
  stalled tags per bond in the exact channel the coverage alarm listens to.
* The alarm treated "this manifest has never seen this bond" as "this bond had
  no stalled tags last night", so a catalog that grew from 349 to 877 ISINs made
  324 bonds regress at once. The job completed, raised anyway, and took both
  downstream value jobs down with it on three consecutive nights.

Offline throughout: the catalog and the validated-tag files are committed, so
the tag arithmetic is real rather than stubbed and no Excel is reachable.
"""

import pytest

from MDP.CitiVelocityExcel.bonds.fetcher import DEFAULT_BOND_VALUES
from MDP.CitiVelocityExcel.bonds.values import DISCONTINUED_2025_10_03
from scripts.citivelo_ust_universe_warm import (
    INTRADAY_VALUES,
    WORKING_CEILING_MB,
    eod_values,
    newly_stalled,
)


# ── the intraday value set ───────────────────────────────────────────

def test_intraday_carries_the_two_rfr_spreads():
    assert "CAS_RFR" in INTRADAY_VALUES
    assert "YYS_RFR" in INTRADAY_VALUES


def test_intraday_still_carries_what_every_bond_serves():
    assert INTRADAY_VALUES[:2] == ("PRICE", "YIELD")


def test_intraday_asks_for_the_live_names_not_the_retired_ones():
    retired = set(DISCONTINUED_2025_10_03)
    assert not (set(INTRADAY_VALUES) & retired), (
        "CAS/YYS stopped publishing on 2025-10-03 and are not a minute series"
    )


# ── the EOD value set ────────────────────────────────────────────────

def test_eod_drops_exactly_the_retired_six():
    dropped = set(DEFAULT_BOND_VALUES) - set(eod_values())
    assert dropped == set(DISCONTINUED_2025_10_03), (
        f"expected the retired set, got {sorted(dropped)}"
    )


def test_eod_keeps_every_rfr_successor():
    values = set(eod_values())
    for retired, successor in DISCONTINUED_2025_10_03.items():
        if not successor:
            continue  # ZSPREAD has none
        assert successor in values, (
            f"{retired} was dropped but its successor {successor} is not asked for"
        )


def test_eod_is_otherwise_the_whole_vocabulary():
    assert set(eod_values()) | set(DISCONTINUED_2025_10_03) == set(DEFAULT_BOND_VALUES)


# ── the marginal cost ────────────────────────────────────────────────

@pytest.mark.slow
def test_the_two_new_intraday_values_add_240_tags_not_1754():
    """plan() filters each bond's values against its validated coverage.

    This is the number the decision was made on: only 120 of the 877 catalogued
    ISINs carry CAS_RFR/YYS_RFR, so the warm goes 1,754 -> 1,994 tags, about
    +58 MB of Excel at the measured 0.24 MB/tag - not the +1.2 GB that the
    wrong transport's 1.7 MB/tag would project.
    """
    from MDP.CitiVelocityExcel.bonds.fetcher import CitiVeloBondFetcher
    from scripts.citivelo_ust_universe_warm import universe

    resolutions = universe()
    fetcher = CitiVeloBondFetcher()

    def _tags(values):
        plan = {}
        for i in range(0, len(resolutions), 50):
            plan.update(fetcher.plan(resolutions[i:i + 50], values=list(values)))
        return sum(len(entry["tags"]) for entry in plan.values())

    before = _tags(("PRICE", "YIELD"))
    after = _tags(INTRADAY_VALUES)
    assert after - before == 240, f"{before} -> {after}"


# ── the alarm ────────────────────────────────────────────────────────

def test_a_bond_with_no_baseline_cannot_regress():
    """The 2026-08-21 failure, in one line."""
    record = {"stalled": ["CAS", "YYS", "ASW", "CARRY.1Y"]}
    assert newly_stalled(None, record) == []


def test_a_tag_that_goes_quiet_after_a_baseline_exists_does_regress():
    prior = {"stalled": ["CAS"]}
    record = {"stalled": ["CAS", "PRICE"]}
    assert newly_stalled(prior, record) == ["PRICE"]


def test_a_bond_that_was_already_quiet_does_not_regress_again():
    prior = {"stalled": ["CAS", "YYS"]}
    record = {"stalled": ["CAS", "YYS"]}
    assert newly_stalled(prior, record) == []


def test_a_bond_that_recovers_does_not_regress():
    prior = {"stalled": ["CAS", "YYS"]}
    record = {"stalled": ["CAS"]}
    assert newly_stalled(prior, record) == []


def test_a_prior_entry_with_no_stalled_key_is_still_a_baseline():
    """A bond seen last night and healthy MUST be able to regress tonight."""
    assert newly_stalled({"key": "x", "tags": 12}, {"stalled": ["PRICE"]}) == ["PRICE"]


# ── the ceiling ──────────────────────────────────────────────────────

def test_the_working_ceiling_leaves_headroom_under_the_hard_one():
    from MDP.CitiVelocityExcel.memory_guard import DEFAULT_CEILING_MB

    assert WORKING_CEILING_MB < DEFAULT_CEILING_MB, (
        "the between-batch check has to stop BEFORE the hard refusal, or a batch "
        "in flight is what crosses the line"
    )


def test_the_nightly_hands_the_warm_its_working_ceiling(monkeypatch):
    """The constants being right is not the same as the caller using them.

    The nightly used to pass the HARD 3,800 MB ceiling into a between-batch
    check whose own comment sizes it for 3,500 - spending the ~20 batches of
    slack that stop a batch in flight from being what crosses the line.

    Patched on the SOURCE module, not on the warmer: the job body imports inside
    the function, so every name is re-resolved per call and a setattr on the
    warmer module is never consulted.
    """
    import datetime
    import importlib.util
    import os
    import sys

    import scripts.citivelo_ust_universe_warm as universe_warm

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_ceiling_probe",
        os.path.join(repo_root, "scripts", "daily_cache_warmer.py"),
    )
    warmer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = warmer
    spec.loader.exec_module(warmer)

    seen = {}

    def _warm(mode, *, ceiling_mb, **kwargs):
        seen[mode] = ceiling_mb
        return {"stopped": None, "regressed": {}, "done": 1, "of": 1}

    monkeypatch.setattr(universe_warm, "warm", _warm)
    monkeypatch.setattr(universe_warm, "backfill_depth",
                        lambda **kw: {"weeks": 0, "passes": 0, "stopped": None})
    monkeypatch.setenv("CITIVELO_UST_DEPTH_DAYS", "0")

    day = datetime.date(2026, 8, 21)
    warmer.warm_citivelo_ust_universe_eod(day, day)
    warmer.warm_citivelo_ust_universe_intraday(day, day)

    assert seen == {"eod": WORKING_CEILING_MB, "intraday": WORKING_CEILING_MB}
