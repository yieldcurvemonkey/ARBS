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
    # Detach the file handler this test's run adds, so handlers do not pile up
    # across tests and keep writing into deleted tmp dirs.
    before = list(module.log.handlers)
    yield module
    for h in module.log.handlers:
        if h not in before:
            h.close()
    module.log.handlers[:] = before


def _run_with(module, monkeypatch, jobs, argv=("daily_cache_warmer.py",)):
    monkeypatch.setattr(module, "JOBS", jobs)
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
    assert warmer._SUBPROCESS_FAILURES == [("intraday fetch", 3)]


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


def test_a_log_directory_that_cannot_be_created_does_not_break_the_warm(warmer, monkeypatch):
    """Logging is bookkeeping; it must never be the reason a warm does not run."""
    monkeypatch.setattr(
        warmer.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )
    code = _run_with(warmer, monkeypatch, [("fine", lambda s, e: None)])
    assert code == 0
