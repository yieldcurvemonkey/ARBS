r"""A warm step that dies must say WHY, not just that it exited non-zero.

The failure this covers ran for weeks. ``CitiVelo CurveStore (intraday + EOD)``
shells out four times; on seven of the ten retained nightly runs the log said
exactly this and nothing else::

    2026-08-18 19:15:15 [WARNING]   EOD warm exited 1
    2026-08-18 19:15:16 [ERROR]   FAILED (146.2s): 1 step(s) failed - EOD warm exited 1

The child's streams inherited the scheduled task's console, and that task's
action carries no redirection, so the child's own explanation went nowhere. Six
undiagnosed nights, and downstream jobs failing on the consequence
("No common CurveStore/CubeStore EOD dates for USD-SOFR-1D") rather than the
cause.

Two halves, tested separately because either alone leaves the bug half-fixed:

* the PARENT must capture and surface the child's last word (``_run``);
* the CHILD must actually have a last word - ``warm_curve`` filtering its banked
  grid down to nothing recorded no error at all, so capturing the output would
  have surfaced a row of zeroes.

Every test here asserts on a message a human would act on. Asserting only "exit
code is non-zero" is what the old code already satisfied.
"""

from __future__ import annotations

import datetime
import importlib.util
import pathlib
import sys
import textwrap

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WARMER = REPO / "scripts" / "daily_cache_warmer.py"


@pytest.fixture()
def warmer(tmp_path, monkeypatch):
    """A freshly imported warmer whose logs land in ``tmp_path``.

    Per test, not per module: ``_SUBPROCESS_FAILURES`` is module state.
    """
    spec = importlib.util.spec_from_file_location("_warmer_capture", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOG_DIR", str(tmp_path / "cache_warmer"))
    # Neutralise the Excel pre-flight. It shells out to PowerShell and reads the
    # USER'S live Excel, so leaving it real would make these tests both slow and
    # dependent on whether someone happens to have a workbook open. Tests that
    # care about the pre-flight patch it themselves.
    monkeypatch.setattr(module, "_excel_preflight", lambda: None)
    before = list(module.log.handlers)
    yield module
    for h in module.log.handlers:
        if h not in before:
            h.close()
    module.log.handlers[:] = before


def _child(tmp_path, body: str) -> pathlib.Path:
    """A real script on disk, so this exercises a real pipe and a real exit."""
    path = tmp_path / "fake_warm_child.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# ------------------------------------------------------------------ #
#                     the parent must surface it                     #
# ------------------------------------------------------------------ #


def test_the_run_log_carries_the_childs_own_error_lines(warmer, monkeypatch, tmp_path):
    """The whole point: a human reading the run log learns the cause."""
    script = _child(tmp_path, """
        import sys
        print("EUR-ESTR-1D  0 written  0 kept  0 sparse  0 failed")
        print("nothing written and nothing already present: the banked par grid "
              "ends 2026-08-07")
        sys.exit(1)
    """)

    warmer._start_run_log(stamp="20260818_181500")
    warmer._run([sys.executable, "-u", str(script)], "EOD warm")

    text = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.log").read_text(
        encoding="utf-8"
    )
    assert "the banked par grid ends 2026-08-07" in text, (
        "the run log must name the cause, not just the exit code:\n" + text
    )


def test_the_job_summary_names_the_cause_not_just_the_exit_code(warmer, monkeypatch, tmp_path):
    """``EOD warm exited 1`` alone is the bug. The detail must ride along."""
    script = _child(tmp_path, """
        import sys
        print("nothing written and nothing already present: grid ends 2026-08-07")
        sys.exit(1)
    """)

    def shells_out(start, end):
        warmer._run([sys.executable, "-u", str(script)], "EOD warm")

    from utils.warm_jobs import WarmJob
    monkeypatch.setattr(
        warmer, "WARM_JOBS", [WarmJob("CitiVelo CurveStore", shells_out)]
    )
    monkeypatch.setattr(sys, "argv", ["daily_cache_warmer.py"])
    assert warmer.main() == 1

    log_file = sorted(pathlib.Path(warmer.LOG_DIR).glob("cache_warmer_*.log"))[0]
    text = log_file.read_text(encoding="utf-8")
    assert "EOD warm exited 1" in text
    assert "grid ends 2026-08-07" in text, (
        "the FAILED line must carry the child's reason:\n" + text
    )


def test_the_full_child_output_lands_in_a_sidecar(warmer, tmp_path):
    """No failure should ever need a re-run to diagnose."""
    script = _child(tmp_path, """
        import sys
        for i in range(200):
            print(f"progress line {i}")
        print("BOOM the real cause", file=sys.stderr)
        sys.exit(2)
    """)

    warmer._start_run_log(stamp="20260818_181500")
    warmer._run([sys.executable, "-u", str(script)], "vol fetch")

    sidecar = pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.children.txt"
    assert sidecar.exists(), "the child's full output must be kept somewhere"
    body = sidecar.read_text(encoding="utf-8")
    assert "progress line 0" in body and "progress line 199" in body
    assert "BOOM the real cause" in body

    # ...but the RUN log must stay readable: a tail, not 200 lines.
    run_log = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.log").read_text(
        encoding="utf-8"
    )
    assert "progress line 0" not in run_log, "the run log must not swallow the whole child"
    assert run_log.count("progress line") <= warmer.CHILD_TAIL_LINES


def test_the_rateslib_banner_does_not_flood_the_run_log(warmer, tmp_path):
    """Capturing stderr must not replace one unreadable log with another.

    Every child prints ~15 lines of rateslib licence notice to stderr on a
    healthy run. Dumping a stderr tail unconditionally pushes the real cause -
    which is on stdout - off the top.
    """
    script = _child(tmp_path, """
        import sys
        for i in range(20):
            print(f"licence banner line {i}", file=sys.stderr)
        print("nothing written and nothing already present: grid ends 2026-08-07")
        sys.exit(1)
    """)

    warmer._start_run_log(stamp="20260818_181500")
    warmer._run([sys.executable, "-u", str(script)], "EOD warm")

    run_log = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.log").read_text(
        encoding="utf-8"
    )
    assert "grid ends 2026-08-07" in run_log
    assert "licence banner line" not in run_log, (
        "stderr with no traceback is banner noise; it must not bury the cause:\n" + run_log
    )


def test_stderr_is_still_shown_when_the_child_actually_raised(warmer, tmp_path):
    """Teeth for the rule above: suppressing stderr must not hide real crashes."""
    script = _child(tmp_path, """
        raise RuntimeError("Excel is at 6526 MB, above the 3800 MB ceiling")
    """)

    warmer._start_run_log(stamp="20260818_181500")
    assert warmer._run([sys.executable, "-u", str(script)], "vol fetch") != 0

    run_log = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.log").read_text(
        encoding="utf-8"
    )
    assert "Excel is at 6526 MB" in run_log, run_log
    assert "RuntimeError" in warmer._SUBPROCESS_FAILURES[0].detail


def test_record_false_still_captures_but_does_not_change_the_exit_code(warmer, tmp_path):
    """The STIRF and UST-futures call sites: better logs, same verdict.

    Both have always treated a non-zero child as a warning rather than a failed
    job. Capturing their output must not quietly promote them to failures -
    that is a semantics change, and it belongs in its own decision.
    """
    script = _child(tmp_path, """
        import sys
        print("stirf backfill: 0 of 5 days built")
        sys.exit(1)
    """)

    warmer._start_run_log(stamp="20260818_181500")
    assert warmer._run([sys.executable, "-u", str(script)], "stirf", record=False) == 1
    assert warmer._SUBPROCESS_FAILURES == [], "record=False must not fail the job"

    run_log = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.log").read_text(
        encoding="utf-8"
    )
    assert "stirf backfill: 0 of 5 days built" in run_log, (
        "...but the child's output must still be recorded:\n" + run_log
    )


def test_a_timed_out_child_still_surrenders_its_last_output(warmer, tmp_path):
    """``timed out after 3600 seconds`` is true and useless on its own."""
    import subprocess

    script = _child(tmp_path, """
        import sys, time
        print("stirf backfill: building USD-OIS-Q12xM12STIRT day 1 of 5", flush=True)
        time.sleep(30)
    """)

    warmer._start_run_log(stamp="20260818_181500")
    with pytest.raises(subprocess.TimeoutExpired):
        warmer._run([sys.executable, "-u", str(script)], "stirf", timeout=2, record=False)

    sidecar = pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.children.txt"
    assert "day 1 of 5" in sidecar.read_text(encoding="utf-8"), (
        "the timeout must not swallow what the child managed to say"
    )


def test_a_step_that_succeeds_adds_no_failure_and_no_noise(warmer, tmp_path):
    script = _child(tmp_path, """
        print("wrote 5 curve-days across 5 curve(s)")
    """)
    warmer._start_run_log(stamp="20260818_181500")
    assert warmer._run([sys.executable, "-u", str(script)], "EOD warm") == 0
    assert warmer._SUBPROCESS_FAILURES == []

    run_log = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260818_181500.log").read_text(
        encoding="utf-8"
    )
    assert "wrote 5 curve-days" not in run_log


def test_non_utf8_child_output_does_not_kill_the_parent(warmer, tmp_path):
    """The children print em-dashes; a cp1252 pipe would make capture the bug."""
    script = _child(tmp_path, """
        import sys
        print("stopped after 0/877 bonds \\u2014 the transport is not writing")
        sys.exit(1)
    """)
    warmer._start_run_log(stamp="20260818_181500")
    assert warmer._run([sys.executable, "-u", str(script)], "UST warm") == 1
    assert "877 bonds" in warmer._SUBPROCESS_FAILURES[0].detail


# ------------------------------------------------------------------ #
#                   which line is the cause                          #
# ------------------------------------------------------------------ #


def test_a_traceback_on_stderr_beats_stdout(warmer):
    """When the child RAISED, the exception line is the cause."""
    out = "fetch: group 'USD 1y' - 44 tags\nfetch: groups completed []\n"
    err = (
        "Traceback (most recent call last):\n"
        '  File "scripts/citivelo_swaption_vol_warm.py", line 140, in cmd_fetch\n'
        "MDP.CitiVelocityExcel.memory_guard.ExcelTooLargeError: Refusing to start a "
        "Citi Velocity warm: Excel is at 6526 MB\n"
    )
    assert "ExcelTooLargeError" in warmer._last_meaningful_line(out, err)


def test_the_rateslib_banner_on_stderr_never_beats_stdout(warmer):
    """Every child prints this to stderr on a HEALTHY run.

    Measured from a real ``citivelo_excel_warm.py warm`` invocation. A naive
    "prefer stderr" rule reports the licence banner as the cause of every single
    failure, which is a different flavour of the same undiagnosable log.
    """
    err = (
        "Rateslib is source-available (not open-source) software distributed under "
        "a dual-licence model.\n"
        "2026-08-19 09:25:36,529 INFO citivelo_excel curve definitions: rateslib +19\n"
    )
    out = "EUR-ESTR-1D  0 written  0 kept\nwrote 0 curve-days across 1 curve(s)\n"
    assert warmer._last_meaningful_line(out, err) == "wrote 0 curve-days across 1 curve(s)"


# ------------------------------------------------------------------ #
#              the child must have something to say                  #
# ------------------------------------------------------------------ #


class _FakeQuotes:
    """Serves a banked par grid that stops before the requested window."""

    def __init__(self, tags, last_day):
        self._tags = list(tags)
        self._last = last_day

    def frame(self, tags, freq, start=None, end=None):
        idx = pd.to_datetime([self._last - datetime.timedelta(days=n) for n in (2, 1, 0)])
        return pd.DataFrame(
            {t: [0.03, 0.031, 0.032] for t in self._tags}, index=idx
        ).sort_index()


class _FakeStore:
    """Refuses to be written to: this path must never reach ``write_day``."""

    def has_day(self, asset, day):
        return False

    def write_day(self, *a, **k):  # pragma: no cover - a write here is the failure
        raise AssertionError("warm_curve must not write when the window is empty")


def test_an_empty_window_records_why_instead_of_a_silent_row_of_zeroes():
    """The measured root cause of the seven ``EOD warm exited 1`` nights.

    The nightly warm asks for TODAY. The banked DAILY par grid is advanced only
    by a manual harvest, so on 2026-08-18 four of the five curves still ended at
    2026-08-07. ``warm_curve`` filtered the grid to nothing, returned a stat with
    every counter at zero and ``errors`` empty, and the caller turned that into
    exit 1 with no reason recorded anywhere.
    """
    from MDP.CitiVelocityExcel import tags as T
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import warm_curve

    entry = entry_for_curve_name("EUR-ESTR-1D")
    grid = T.ois_par_grid(entry.citi_index)
    banked_last = datetime.date(2026, 8, 7)
    asked_for = datetime.date(2026, 8, 18)

    stat = warm_curve(
        "EUR-ESTR-1D",
        quotes=_FakeQuotes(grid, banked_last),
        store=_FakeStore(),
        start=asked_for,
        end=asked_for,
    )

    assert stat.written == 0 and stat.skipped_existing == 0
    assert stat.errors, "a warm that did nothing must say why - this was the whole bug"
    why = stat.errors[0]
    assert "2026-08-07" in why, f"must name where the banked grid actually ends: {why}"
    assert "2026-08-18" in why, f"must name the window that was asked for: {why}"


def test_a_window_inside_the_grid_still_warms_normally():
    """Teeth: the new branch must not swallow the working case."""
    from MDP.CitiVelocityExcel import tags as T
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import warm_curve

    entry = entry_for_curve_name("EUR-ESTR-1D")
    grid = T.ois_par_grid(entry.citi_index)
    banked_last = datetime.date(2026, 8, 7)

    class _AllPresent(_FakeStore):
        def has_day(self, asset, day):
            return True  # already warmed, so no build and no write

    stat = warm_curve(
        "EUR-ESTR-1D",
        quotes=_FakeQuotes(grid, banked_last),
        store=_AllPresent(),
        start=banked_last - datetime.timedelta(days=2),
        end=banked_last,
    )

    assert stat.skipped_existing == 3
    assert not stat.errors, f"a healthy warm must record no error: {stat.errors}"


# ------------------------------------------------------------------ #
#   a child's own SKIP code is not a failed step, and stays per-site   #
# ------------------------------------------------------------------ #
#
# The EOD CurveStore warm is offline by construction: it builds curves out of the
# banked DAILY par grid and cannot fetch. When the grid ends before the window it
# has nothing to do and nothing is broken - an input it does not own has not been
# advanced. It reported that as exit 1 on six of ten retained nights, which is
# how FAILED became the normal nightly state and the exit code stopped being
# read. Exit 3 now says "a human must act" and names the command.


def test_a_declared_skip_code_is_not_recorded_as_a_failed_step(warmer, tmp_path):
    """The whole point: SKIPPED must not count towards the job's failures."""
    script = _child(tmp_path, """
        import sys
        print("SKIPPED: no banked DAILY rows; run scripts/citivelo_daily_par_refresh.py")
        sys.exit(3)
    """)

    code = warmer._run([sys.executable, "-u", str(script)], "EOD warm", skip_codes=(3,))

    assert code == 3, "the child's own code is still returned"
    assert warmer._SUBPROCESS_FAILURES == [], (
        "a stale par grid is not a defect of this warm and must not fail the job"
    )
    assert len(warmer._SUBPROCESS_SKIPS) == 1
    assert warmer._SUBPROCESS_SKIPS[0].label == "EOD warm"


def test_a_skip_carries_the_childs_last_word_so_a_human_knows_what_to_run(warmer, tmp_path):
    """"EOD warm exited 1" naming no cause is the failure this replaces.

    The actionable half is the command, and it has to survive into the record
    the SUMMARY line is built from.
    """
    script = _child(tmp_path, """
        import sys
        print("noise about licences")
        print("SKIPPED: grid ends 2026-08-07; run scripts/citivelo_daily_par_refresh.py refresh")
        sys.exit(3)
    """)

    warmer._run([sys.executable, "-u", str(script)], "EOD warm", skip_codes=(3,))

    detail = warmer._SUBPROCESS_SKIPS[0].detail
    assert "citivelo_daily_par_refresh" in detail, detail
    assert "2026-08-07" in detail, detail


def test_an_UNdeclared_code_from_the_same_child_still_fails(warmer, tmp_path):
    """Only the codes the call site declares are waived.

    A child that dies for a real reason must still be a failure, or the skip
    branch becomes a blanket amnesty and the exit code stops meaning anything
    again.
    """
    script = _child(tmp_path, """
        import sys
        print("nothing written and nothing already present: EUR-ESTR-1D: ValueError")
        sys.exit(1)
    """)

    warmer._run([sys.executable, "-u", str(script)], "EOD warm", skip_codes=(3,))

    assert warmer._SUBPROCESS_SKIPS == []
    assert len(warmer._SUBPROCESS_FAILURES) == 1


def test_the_same_code_from_a_call_site_that_did_not_declare_it_is_a_failure(warmer, tmp_path):
    """``skip_codes`` is per call site, and that is deliberate.

    3 means "stale par grid, run the refresh" to ``citivelo_excel_warm.py`` and
    "stopped at the Excel memory ceiling" to ``citivelo_excel_intraday_warm.py``.
    The second IS worth a red line, so a blanket "3 means skip" would silently
    reclassify a wedged Excel as routine.
    """
    script = _child(tmp_path, """
        import sys
        print("fetch stopped early at 12 day file(s); restart Excel")
        sys.exit(3)
    """)

    warmer._run([sys.executable, "-u", str(script)], "intraday fetch")

    assert warmer._SUBPROCESS_SKIPS == []
    assert len(warmer._SUBPROCESS_FAILURES) == 1, (
        "the memory ceiling is a real outcome and must stay visible"
    )


def test_exit_0_is_never_a_skip(warmer, tmp_path):
    """The control: a healthy child must not be recorded anywhere."""
    script = _child(tmp_path, """
        print("wrote 12 curve-days across 5 curve(s)")
    """)

    assert warmer._run([sys.executable, "-u", str(script)], "EOD warm", skip_codes=(3,)) == 0
    assert warmer._SUBPROCESS_SKIPS == []
    assert warmer._SUBPROCESS_FAILURES == []
