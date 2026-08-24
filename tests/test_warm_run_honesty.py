r"""The cache warmer has to report what actually happened.

Before this, three independent things each guaranteed a scheduled run looked
successful whatever it did:

* every caller of ``_run`` discards its return code, so a warm script exiting
  non-zero was a ``log.warning`` and nothing else;
* ``main`` caught every job exception, recorded ``FAILED`` in a summary table,
  and then fell off the end - returning ``None``, so the process exited 0;
* the summary went to stderr with no file handler and the scheduled task's
  action carries no redirection, so nothing was written down. Windows' own
  ``TaskScheduler/Operational`` log is disabled on the target machine, so there
  was no second copy either.

Together those meant ``ARBS-CacheWarmer-Daily`` could report
``result=0x00000000`` for weeks while producing nothing, and the only way to
answer "did it work?" was to read the CurveStore and infer. Every test here
asserts an exit code or a file on disk - never a log line, because a log line is
what the old version already produced.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WARMER = REPO / "scripts" / "daily_cache_warmer.py"


@pytest.fixture()
def warmer(tmp_path, monkeypatch):
    """A freshly imported warmer whose logs land in ``tmp_path``.

    Imported per test rather than per module: ``_SUBPROCESS_FAILURES`` is module
    state, and a run that inherited another test's failures would pass for the
    wrong reason.
    """
    spec = importlib.util.spec_from_file_location("_warmer_honesty", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOG_DIR", str(tmp_path / "cache_warmer"))
    # Neutralise the Excel pre-flight. It shells out to PowerShell and reads the
    # USER'S live Excel, so leaving it real would make these tests both slow and
    # dependent on whether someone happens to have a workbook open. Tests that
    # care about the pre-flight patch it themselves.
    monkeypatch.setattr(module, "_excel_preflight", lambda: None)
    # The source pre-flight is neutralised for the same reason as the Excel one
    # above: these tests are not about it. Left real it parses 1,496 files of the
    # actual checkout on EVERY main() call - measured at 108 s across this file
    # and its two siblings - to re-establish a fact tests/test_warm_source_guard.py
    # already covers properly.
    monkeypatch.setattr(module, "_SOURCE_ROOTS", ())
    # Detach the file handler this test's run adds, so handlers do not pile up
    # across tests and keep writing into deleted tmp dirs.
    before = list(module.log.handlers)
    yield module
    for h in module.log.handlers:
        if h not in before:
            h.close()
    module.log.handlers[:] = before


def _run_with(module, monkeypatch, jobs, argv=("daily_cache_warmer.py",)):
    """Run the warmer over a substituted registry.

    ``jobs`` takes ``(name, fn)`` pairs for brevity or ready-made ``WarmJob``s
    when a test needs ``requires``/``provides``/``needs_excel``. The runner
    consumes ``WARM_JOBS`` directly - there is no ``(name, fn)`` projection to
    patch, on purpose, because patching a projection the runner had stopped
    reading would have silently run the seventeen REAL jobs.
    """
    from utils.warm_jobs import WarmJob

    monkeypatch.setattr(
        module, "WARM_JOBS",
        [j if isinstance(j, WarmJob) else WarmJob(*j) for j in jobs],
    )
    monkeypatch.setattr(sys, "argv", list(argv))
    return module.main()


# ------------------------------------------------------------------ #
#                            the exit code                           #
# ------------------------------------------------------------------ #


def test_a_clean_run_exits_zero(warmer, monkeypatch):
    code = _run_with(warmer, monkeypatch, [("fine", lambda s, e: None)])
    assert code == 0


def test_a_raising_job_makes_the_run_exit_nonzero(warmer, monkeypatch):
    def boom(start, end):
        raise RuntimeError("the add-in was not signed in")

    code = _run_with(warmer, monkeypatch, [("ok", lambda s, e: None), ("boom", boom)])
    assert code == 1, "a job that raised must not report success to the scheduler"


def test_a_failed_SUBPROCESS_makes_the_run_exit_nonzero(warmer, monkeypatch):
    """The exact hole: the job returns normally, having lost a step.

    ``warm_citivelo_curve_stores`` calls ``_run`` four times and ignores every
    return code by design, so an intraday fetch that died still let the job -
    and the whole warm - report success.
    """
    class _Result:
        returncode = 3

    monkeypatch.setattr(warmer.subprocess, "run", lambda *a, **k: _Result())

    def shells_out(start, end):
        warmer._run([sys.executable, "-c", "pass"], "intraday fetch")
        return None  # returns normally, exactly as the real job does

    code = _run_with(warmer, monkeypatch, [("shells out", shells_out)])
    assert code == 1
    assert [(f.label, f.returncode) for f in warmer._SUBPROCESS_FAILURES] == [
        ("intraday fetch", 3)
    ]


def test_a_lost_step_is_attributed_to_the_job_that_lost_it(warmer, monkeypatch):
    """Teeth: the failure must land on the right job, not on the whole run."""
    class _Result:
        returncode = 3

    monkeypatch.setattr(warmer.subprocess, "run", lambda *a, **k: _Result())
    seen = {}

    def bad(start, end):
        warmer._run([sys.executable, "-c", "pass"], "EOD warm")

    def good(start, end):
        seen["ran"] = True

    statuses = []
    real = warmer.log.info

    def capture(msg, *args):
        statuses.append(msg % args if args else msg)
        return real(msg, *args)

    monkeypatch.setattr(warmer.log, "info", capture)
    code = _run_with(warmer, monkeypatch, [("bad", bad), ("good", good)])

    assert code == 1
    assert seen.get("ran"), "a failing job must not stop the ones after it"
    summary = [s for s in statuses if s.strip().startswith(("bad", "good"))]
    assert any("FAILED" in s and "EOD warm exited 3" in s for s in summary), summary
    assert any(s.strip().startswith("good") and "OK" in s for s in summary), summary


def test_list_still_exits_zero(warmer, monkeypatch, capsys):
    code = _run_with(warmer, monkeypatch, [], argv=("daily_cache_warmer.py", "--list"))
    assert code == 0
    assert "Available jobs" in capsys.readouterr().out


# ------------------------------------------------------------------ #
#                            the run log                             #
# ------------------------------------------------------------------ #


def test_a_run_writes_a_log_file_naming_each_job(warmer, monkeypatch):
    _run_with(warmer, monkeypatch, [("CitiVelo CurveStore", lambda s, e: None)])

    written = sorted(pathlib.Path(warmer.LOG_DIR).glob("cache_warmer_*.log"))
    assert len(written) == 1, "a run must leave exactly one record of itself"
    text = written[0].read_text(encoding="utf-8")
    assert "SUMMARY" in text
    assert "CitiVelo CurveStore" in text


def test_the_log_records_the_failure_not_just_the_summary(warmer, monkeypatch):
    def boom(start, end):
        raise RuntimeError("Excel is not signed in")

    _run_with(warmer, monkeypatch, [("boom", boom)])
    text = sorted(pathlib.Path(warmer.LOG_DIR).glob("*.log"))[0].read_text(encoding="utf-8")
    assert "Excel is not signed in" in text
    assert "Traceback" in text, "log.exception must keep the traceback"


def test_old_run_logs_are_pruned(warmer, monkeypatch):
    directory = pathlib.Path(warmer.LOG_DIR)
    directory.mkdir(parents=True)
    for i in range(warmer.LOG_RETENTION + 5):
        (directory / f"cache_warmer_20260101_{i:06d}.log").write_text("old", encoding="utf-8")

    warmer._start_run_log(stamp="20260102_000000")

    assert len(list(directory.glob("cache_warmer_*.log"))) == warmer.LOG_RETENTION
    assert (directory / "cache_warmer_20260102_000000.log").exists()


def test_a_pruned_run_takes_its_child_output_sidecar_with_it(warmer):
    r"""The sidecar is retained in LOCKSTEP with the run log it belongs to.

    Two files per run now: the run log a human reads, and
    ``cache_warmer_<stamp>.children.txt`` carrying every subprocess's full
    output. An orphaned sidecar is worse than useless - it is the bulky half of
    the pair, and it accumulates with nothing pointing at it. The glob that
    drives the prune is deliberately ``*.log`` and not ``cache_warmer_*``, so
    that a sidecar is never counted as a run and the retention is not silently
    halved; this pins the other half of that arrangement.

    Measured for scale rather than assumed: the ten retained runs currently
    occupy 136 KB in total, so retention is a correctness property here, not a
    disk-space one.
    """
    directory = pathlib.Path(warmer.LOG_DIR)
    directory.mkdir(parents=True)
    for i in range(warmer.LOG_RETENTION + 3):
        stem = f"cache_warmer_20260101_{i:06d}"
        (directory / f"{stem}.log").write_text("old", encoding="utf-8")
        (directory / f"{stem}.children.txt").write_text("child output", encoding="utf-8")

    warmer._start_run_log(stamp="20260102_000000")

    logs = {p.stem for p in directory.glob("cache_warmer_*.log")}
    sidecars = {
        p.name[: -len(".children.txt")] for p in directory.glob("*.children.txt")
    }
    assert len(logs) == warmer.LOG_RETENTION
    assert sidecars <= logs, (
        f"orphaned sidecar(s) survived their run log: {sorted(sidecars - logs)}"
    )


def test_a_log_directory_that_cannot_be_created_does_not_break_the_warm(warmer, monkeypatch):
    """Logging is bookkeeping; it must never be the reason a warm does not run."""
    monkeypatch.setattr(
        warmer.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )
    code = _run_with(warmer, monkeypatch, [("fine", lambda s, e: None)])
    assert code == 0


# ------------------------------------------------------------------ #
#                     the STIRF wall-clock budget                    #
# ------------------------------------------------------------------ #
#
# ``warm_stirf_cme_session`` shells out once per curve with a 3,600 s cap and no
# run-level budget, so three curves could occupy three hours inside a warm whose
# whole nightly span is 2 h 45 m. Measured over the ten retained runs the job
# takes 1,275-1,648 s on a normal night; the one timeout on record (2026-08-15,
# a five-day catch-up) killed the job outright, and the two curves that had
# already succeeded were the only ones that ever ran.


class _Timeout:
    """A ``subprocess.run`` stand-in: times out on the Nth call, else exits 0."""

    def __init__(self, module, fail_on):
        self._module = module
        self._fail_on = fail_on
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw.get("timeout")))
        if len(self.calls) == self._fail_on:
            raise self._module.subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()


def test_one_timed_out_curve_does_not_cost_the_others(warmer, monkeypatch):
    """The 2026-08-15 loss, inverted: the remaining curves must still be tried."""
    import datetime

    runner = _Timeout(warmer, fail_on=1)
    monkeypatch.setattr(warmer.subprocess, "run", runner)

    day = datetime.date(2026, 8, 18)  # a Tuesday
    warmer.warm_stirf_cme_session(day, day)

    assert len(runner.calls) == 3, (
        f"a timeout on the first curve stopped the other two: {len(runner.calls)} call(s)"
    )


def test_a_timed_out_curve_still_makes_the_job_FAIL(warmer, monkeypatch):
    """Containment must not become concealment: a timeout genuinely lost work."""
    import datetime

    monkeypatch.setattr(warmer.subprocess, "run", _Timeout(warmer, fail_on=1))
    day = datetime.date(2026, 8, 18)

    def job(start, end):
        return warmer.warm_stirf_cme_session(day, day)

    code = _run_with(warmer, monkeypatch, [("STIRF CME Session", job)])

    assert code == 1, "a lost curve must not report success to the scheduler"
    assert [f.returncode for f in warmer._SUBPROCESS_FAILURES] == ["TIMEOUT"]
    rendered = warmer._describe_step_failure(warmer._SUBPROCESS_FAILURES[0])
    assert "timed out" in rendered, rendered
    assert "exited TIMEOUT" not in rendered, rendered


def test_the_shared_budget_stops_the_job_overrunning(warmer, monkeypatch):
    """A spent budget must stop the job starting curves, and say so.

    The per-curve cap bounds one child; only this bounds the job.
    """
    import datetime

    runner = _Timeout(warmer, fail_on=0)  # never times out
    monkeypatch.setattr(warmer.subprocess, "run", runner)
    monkeypatch.setattr(warmer, "_STIRF_TOTAL_BUDGET_S", 0.0)

    day = datetime.date(2026, 8, 18)
    warmer.warm_stirf_cme_session(day, day)

    assert runner.calls == [], "no curve may start once the budget is spent"
    assert [f.returncode for f in warmer._SUBPROCESS_FAILURES] == ["NOT RUN"] * 3, (
        "a curve that never ran must be recorded, not silently dropped"
    )


def test_each_curve_is_capped_by_whichever_bound_binds_first(warmer, monkeypatch):
    """The timeout handed to the child is ``min(per-curve cap, budget left)``."""
    import datetime

    runner = _Timeout(warmer, fail_on=0)
    monkeypatch.setattr(warmer.subprocess, "run", runner)
    monkeypatch.setattr(warmer, "_STIRF_TOTAL_BUDGET_S", 100.0)

    day = datetime.date(2026, 8, 18)
    warmer.warm_stirf_cme_session(day, day)

    caps = [t for _, t in runner.calls]
    assert caps, "no curve ran"
    assert all(0 < c <= 100.0 for c in caps), (
        f"a curve was given longer than the whole job's budget: {caps}"
    )
    assert all(c <= warmer._STIRF_CURVE_TIMEOUT_S for c in caps), caps
