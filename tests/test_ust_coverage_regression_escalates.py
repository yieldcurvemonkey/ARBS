"""A coverage regression must reach the SCHEDULER, not just the CLI.

`citivelo_ust_universe_warm.main` exits 1 when tags newly fall silent, but the
nightly warmer never goes through `main` -- it calls `warm()` directly and, until
`_raise_on_coverage_regression` existed, read only `out["stopped"]`. Measured on
the unfixed code: fed a real regression payload the job returned `None`, the
SUMMARY line printed OK, and the run exited 0.

That is the same shape as the defect the coverage predicate was written to fix,
one layer up -- a warm that cannot fail on coverage grounds cannot be trusted to
report coverage. These tests pin the escalation at the layer the scheduler
actually runs.

The level-vs-change distinction is pinned too, because it is the part most likely
to be "helpfully" widened later: ten value families have been dead since
2025-10-03 and 2025-11-28, so escalating the LEVEL would exit non-zero every night
for something nobody can act on -- the always-failing exit code this warmer's own
docstring says teaches an operator to ignore exit codes.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts import daily_cache_warmer as W

START = dt.date(2026, 8, 18)
END = dt.date(2026, 8, 19)

CLEAN = {"stopped": False, "reason": "", "done": 877, "of": 877,
         "coverage": {}, "regressed": {}}


def _fake_warm(monkeypatch, payload):
    """Patch the module attributes -- both jobs import these inside the function.

    BOTH entry points, not just ``warm``. The intraday job runs a second pass
    after the forward window (``backfill_depth``), and while this file stubbed
    only ``warm`` that pass ran FOR REAL: on 2026-08-20 it planned the whole
    877-bond universe, fetched 794 tags from the live add-in, wrote 794 MI01
    parquets into the developer's real cache and a 397-bond ``depth`` book into
    the production manifest that tonight's cron resumes from. Nothing was
    falsified and it was all restored, but this test is about a coverage
    regression escalating to the scheduler - it has no business touching Excel.

    ``tests/conftest.py`` now also redirects the manifest for the whole session,
    so the two guards are independent: that one stops the WRITE, this one stops
    the FETCH.
    """
    import scripts.citivelo_ust_universe_warm as U
    monkeypatch.setattr(U, "warm", lambda *a, **k: payload)
    monkeypatch.setattr(U, "backfill_depth", lambda **k: {
        "weeks": 0, "passes": 0, "rows": 0, "stopped": False, "reason": "",
        "deepest": None, "target": None,
    })


@pytest.mark.parametrize("job,label", [
    (W.warm_citivelo_ust_universe_eod, "EOD"),
    (W.warm_citivelo_ust_universe_intraday, "intraday"),
])
def test_a_new_coverage_regression_fails_the_job(monkeypatch, job, label):
    _fake_warm(monkeypatch, {**CLEAN,
                             "regressed": {"US91282CNG23": ["CAS", "PRICE"]}})
    with pytest.raises(RuntimeError) as e:
        job(START, END)
    msg = str(e.value)
    assert "US91282CNG23" in msg, "the operator must be told WHICH bond"
    assert "CAS" in msg
    assert label in msg
    # It must not read as a partial run -- re-running will not clear it.
    assert "re-run" not in msg or "will not clear" in msg


@pytest.mark.parametrize("job", [
    W.warm_citivelo_ust_universe_eod,
    W.warm_citivelo_ust_universe_intraday,
])
def test_no_regression_is_not_an_alarm(monkeypatch, job):
    _fake_warm(monkeypatch, CLEAN)
    assert job(START, END) is None


@pytest.mark.parametrize("job", [
    W.warm_citivelo_ust_universe_eod,
    W.warm_citivelo_ust_universe_intraday,
])
def test_a_stopped_run_still_reports_as_a_partial_not_a_regression(monkeypatch, job):
    """Precedence: a partial run is the more actionable message, so it wins."""
    _fake_warm(monkeypatch, {**CLEAN, "stopped": True, "done": 48,
                             "reason": "no block",
                             "regressed": {"US91282CNG23": ["CAS"]}})
    with pytest.raises(RuntimeError, match="stopped after 48/877"):
        job(START, END)


def test_many_regressions_are_summarised_not_dumped():
    """A 500-bond regression must not paste 500 ISINs into the run log."""
    regressed = {f"US{i:010d}": ["CAS"] for i in range(40)}
    with pytest.raises(RuntimeError) as e:
        W._raise_on_coverage_regression({"regressed": regressed}, "EOD")
    msg = str(e.value)
    assert "40 bond(s)" in msg
    assert "and 35 more" in msg
    assert msg.count("US00000000") <= 5


def test_the_level_does_not_escalate_only_the_change():
    """A standing dead level with no NEW stall must not fail the run.

    The ten long-dead value families would otherwise exit non-zero every night.
    """
    assert W._raise_on_coverage_regression(
        {"coverage": {"stalled": 1854, "sparse": 1025}, "regressed": {}}, "EOD") is None
