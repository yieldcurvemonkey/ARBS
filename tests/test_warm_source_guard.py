r"""A running warm is safe from a source edit. Its CHILDREN are not.

The failure this covers happened on 2026-08-23, during the catch-up backfill.
``TB/TimeseriesBuilder.py`` was edited while the warm was running. The warm
itself was fine - it had imported its modules at start-up and held them in
memory - but ``scripts/daily_cache_warmer.py`` shells out, and a
``stirf_curve_service`` child imported the half-written file and died with a
``SyntaxError``. ``USD-SOFR-1D-Q12STIRT`` produced nothing for five days of
backfill.

The edit was the mistake. What made it expensive was the reporting: that call
site passes ``record=False``, so the non-zero exit stayed out of
``_SUBPROCESS_FAILURES`` and the job reported ``OK (98.7s)`` having banked two
curves of three. A curve died and the night stayed green.

Three guards, and a test per guard plus a test per thing the guard must NOT do:

1. PRE-FLIGHT   nothing runs against a tree that does not parse.
2. STABILITY    a file that changes mid-run AND stops parsing stops the child.
3. CLASSIFY     a child that could not load its code is FAILED, whatever
                ``record=`` says - and a child that failed for a DATA reason at
                the same call site is still only a warning.

Plus the accounting the whole thing exists to protect: a STIRF curve that banked
nothing is a lost curve, and a STIRF curve that banked some days is not.

Every test here asserts on the reported OUTCOME. Asserting "it logged something"
is what the old code already satisfied.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WARMER = REPO / "scripts" / "daily_cache_warmer.py"


@pytest.fixture()
def warmer(tmp_path, monkeypatch):
    """A freshly imported warmer whose logs land in ``tmp_path``.

    Per test, not per module: ``_SUBPROCESS_FAILURES`` and ``_SOURCE_SNAPSHOT``
    are both module state and both are what these tests are about.
    """
    spec = importlib.util.spec_from_file_location("_warmer_source_guard", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOG_DIR", str(tmp_path / "cache_warmer"))
    monkeypatch.setattr(module, "_excel_preflight", lambda: None)
    before = list(module.log.handlers)
    yield module
    for h in module.log.handlers:
        if h not in before:
            h.close()
    module.log.handlers[:] = before


def _tree(tmp_path, name="src", **modules):
    """A source root on disk. ``module_name=body`` writes ``module_name.py``.

    The suffix is added here rather than spelled in each call, because a file
    without it is not scanned at all - which is a way for every test in this
    module to pass against a guard that does nothing.
    """
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    for module_name, body in modules.items():
        (root / f"{module_name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return root


def _child(tmp_path, body: str, name="fake_warm_child.py") -> pathlib.Path:
    """A real script on disk, so this exercises a real pipe and a real exit."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# ------------------------------------------------------------------ #
#            guard 1 - nothing runs against a broken tree            #
# ------------------------------------------------------------------ #


def test_a_half_written_module_stops_the_run_before_any_job(warmer, tmp_path, monkeypatch):
    """The whole point: find it in seconds, not after three hours of work.

    The body is the real 2026-08-23 shape - a decorator left orphaned above a
    comment when an edit landed between two writes.
    """
    root = _tree(tmp_path, timeseries_builder="""
        @staticmethod
        # a comment where the def should be
    """)
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))

    ran = []
    from utils.warm_jobs import WarmJob
    monkeypatch.setattr(warmer, "WARM_JOBS",
                        [WarmJob("anything", lambda s, e: ran.append(1))])
    monkeypatch.setattr(sys, "argv", ["daily_cache_warmer.py"])

    assert warmer.main() == 1, "a tree that does not parse must fail the run"
    assert ran == [], "no job may run against a tree a child cannot import"

    text = sorted(pathlib.Path(warmer.LOG_DIR).glob("*.log"))[0].read_text(encoding="utf-8")
    assert "BROKEN SOURCE" in text and "timeseries_builder.py" in text, (
        "the log must NAME the file, or the guard has only replaced one "
        "undiagnosable failure with another:\n" + text
    )


def test_a_tree_that_parses_runs_normally(warmer, tmp_path, monkeypatch):
    """The guard must not be the thing that breaks the night."""
    root = _tree(tmp_path, fine="""
        def build():
            return 1
    """)
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))

    ran = []
    from utils.warm_jobs import WarmJob
    monkeypatch.setattr(warmer, "WARM_JOBS",
                        [WarmJob("anything", lambda s, e: ran.append(1))])
    monkeypatch.setattr(sys, "argv", ["daily_cache_warmer.py"])

    assert warmer.main() == 0
    assert ran == [1]


def test_the_guard_can_be_switched_off(warmer, tmp_path, monkeypatch):
    """Every behaviour change here has a switch, and this one is load-bearing.

    A broken file in a tree no child imports must not be able to brick the
    nightly with no way out at 08:00.
    """
    root = _tree(tmp_path, broken="def (:\n")
    monkeypatch.setenv("ARBS_WARM_SOURCE_GUARD", "0")
    monkeypatch.setattr(warmer, "_SOURCE_GUARD_ENABLED", False)
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))

    assert warmer._preflight_source() == [], "the switch must actually skip the scan"


# ------------------------------------------------------------------ #
#           guard 2 - the tree must not move under a child           #
# ------------------------------------------------------------------ #


def test_a_file_that_breaks_mid_run_stops_the_next_child(warmer, tmp_path, monkeypatch):
    """The curve-break stress test, at the launch decision.

    The child must not be launched at all: it would import the half-written file
    and die on it, and the run would then be diagnosing a ``SyntaxError`` in a
    module that has since been repaired.
    """
    root = _tree(tmp_path, timeseries_builder="def build():\n    return 1\n")
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))
    assert warmer._preflight_source() == []

    script = _child(tmp_path, """
        import sys
        print("this child must never run")
        sys.exit(0)
    """)
    # The edit lands between the snapshot and the launch - a decorator orphaned
    # above a comment, which is what actually happened.
    (root / "timeseries_builder.py").write_text(
        "@staticmethod\n# a comment where the def should be\n", encoding="utf-8")

    warmer._start_run_log(stamp="20260823_103100")
    rc = warmer._run([sys.executable, "-u", str(script)], "stirf USD-SOFR-1D-Q12STIRT",
                     record=False)

    assert rc == warmer._NOT_LAUNCHED
    assert len(warmer._SUBPROCESS_FAILURES) == 1, (
        "a refused child must be RECORDED - record=False covers a curve that "
        "priced badly, not one that was never allowed to start"
    )
    failure = warmer._SUBPROCESS_FAILURES[0]
    assert failure.returncode == "NOT RUN"
    assert "timeseries_builder.py" in failure.detail, (
        "the failure must name the file that changed:\n" + failure.detail
    )


def test_a_clean_edit_mid_run_is_loud_but_survivable(warmer, tmp_path, monkeypatch):
    """Someone landing a working change is legal. It is still worth knowing."""
    root = _tree(tmp_path, mod="def build():\n    return 1\n")
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))
    assert warmer._preflight_source() == []

    script = _child(tmp_path, "print('ok')\n")
    (root / "mod.py").write_text("def build():\n    return 2\n", encoding="utf-8")

    warmer._start_run_log(stamp="20260823_103100")
    rc = warmer._run([sys.executable, "-u", str(script)], "some step")

    assert rc == 0, "a file that still parses must not stop the child"
    assert warmer._SUBPROCESS_FAILURES == []
    text = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260823_103100.log").read_text(
        encoding="utf-8")
    assert "SOURCE CHANGED" in text and "mod.py" in text


def test_a_clean_edit_is_reported_once_not_before_every_child(warmer, tmp_path, monkeypatch):
    """A guard that shouts on every step for the rest of the night gets ignored."""
    root = _tree(tmp_path, mod="X = 1\n")
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))
    warmer._preflight_source()
    (root / "mod.py").write_text("X = 2\n", encoding="utf-8")

    script = _child(tmp_path, "print('ok')\n")
    warmer._start_run_log(stamp="20260823_103100")
    warmer._run([sys.executable, "-u", str(script)], "step one")
    warmer._run([sys.executable, "-u", str(script)], "step two")

    text = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260823_103100.log").read_text(
        encoding="utf-8")
    assert text.count("SOURCE CHANGED") == 1, (
        "the change must be re-baselined after it is reported:\n" + text
    )


def test_a_dirty_tree_at_run_start_does_not_fire_the_guard(warmer, tmp_path, monkeypatch):
    """A DELTA, never "the tree is dirty".

    The primary checkout is routinely dirty with in-flight work. A guard that
    fires on any uncommitted file fires every single night and gets switched
    off, which is worse than not having it.
    """
    root = _tree(tmp_path, already_edited="def build():\n    return 'uncommitted'\n")
    monkeypatch.setattr(warmer, "_SOURCE_ROOTS", (str(root),))
    warmer._preflight_source()

    script = _child(tmp_path, "print('ok')\n")
    warmer._start_run_log(stamp="20260823_103100")
    assert warmer._run([sys.executable, "-u", str(script)], "step") == 0
    assert warmer._SUBPROCESS_FAILURES == []

    text = (pathlib.Path(warmer.LOG_DIR) / "cache_warmer_20260823_103100.log").read_text(
        encoding="utf-8")
    assert "SOURCE CHANGED" not in text


# ------------------------------------------------------------------ #
#      guard 3 - a child that could not load its code is FAILED      #
# ------------------------------------------------------------------ #


def test_a_child_that_dies_importing_is_failed_even_under_record_false(warmer, tmp_path):
    """THE regression. A real child, a real corrupted import, a real exit.

    This is the 2026-08-23 loss end to end: the child imports a module that does
    not parse, dies, and the call site says a non-zero exit here is only a
    warning. It is not - the child did no work at all.
    """
    (tmp_path / "half_written.py").write_text(
        "@staticmethod\n# a comment where the def should be\n", encoding="utf-8")
    script = _child(tmp_path, f"""
        import sys
        sys.path.insert(0, {str(tmp_path)!r})
        import half_written
        print("never reached")
    """)

    warmer._start_run_log(stamp="20260823_103100")
    rc = warmer._run([sys.executable, "-u", str(script)], "stirf USD-SOFR-1D-Q12STIRT",
                     record=False)

    assert rc != 0
    assert len(warmer._SUBPROCESS_FAILURES) == 1, (
        "a child that could not load its own code must be reported as FAILED "
        "even where a non-zero exit is normally a warning"
    )
    detail = warmer._SUBPROCESS_FAILURES[0].detail
    assert "SyntaxError" in detail, (
        "the detail must name what actually happened:\n" + detail
    )


def test_a_missing_module_is_the_same_class(warmer, tmp_path):
    """``ModuleNotFoundError`` is a child that could not load its code too."""
    script = _child(tmp_path, """
        import definitely_not_a_real_module_xyz
    """)
    warmer._start_run_log(stamp="20260823_103100")
    warmer._run([sys.executable, "-u", str(script)], "stirf", record=False)

    assert len(warmer._SUBPROCESS_FAILURES) == 1
    assert "ModuleNotFoundError" in warmer._SUBPROCESS_FAILURES[0].detail


def test_a_data_failure_under_record_false_is_still_only_a_warning(warmer, tmp_path):
    """The half that must NOT change, and the reason this is not a blanket rule.

    ``record=False`` was written for a curve that priced badly. Escalating THAT
    would make the STIRF job red on nights nothing is wrong, which is how an
    exit code stops being read.
    """
    script = _child(tmp_path, """
        import sys
        print("stirf backfill: 0 of 5 days built - vendor served nothing")
        sys.exit(1)
    """)
    warmer._start_run_log(stamp="20260823_103100")
    assert warmer._run([sys.executable, "-u", str(script)], "stirf", record=False) == 1
    assert warmer._SUBPROCESS_FAILURES == [], (
        "a DATA failure at a record=False call site must stay a warning"
    )


def test_a_handled_importerror_the_child_merely_logged_is_not_fatal(warmer, tmp_path):
    """Half one: the child CAUGHT it, said so, and carried on to a data failure.

    This is what "did the child raise?" buys that the anchor cannot. The line the
    child logs is shaped exactly like a traceback's exception line - it starts
    with the exception name and a colon, because that is what ``logging`` and
    ``print(f"{type(exc).__name__}: {exc}")`` produce - and every child in this
    warm logs to stderr. The difference is that this child handled it and went
    on to fail for a reason about the DATA, which is survivable.
    """
    script = _child(tmp_path, """
        import sys
        try:
            import definitely_not_a_real_module_xyz
        except ImportError as exc:
            print(f"ImportError: {exc} - falling back to the cached grid",
                  file=sys.stderr)
        print("stirf backfill: 0 of 5 days built - vendor served nothing")
        sys.exit(1)
    """)
    warmer._start_run_log(stamp="20260823_103100")
    warmer._run([sys.executable, "-u", str(script)], "stirf", record=False)
    assert warmer._SUBPROCESS_FAILURES == [], (
        "a child that CAUGHT an ImportError and reported it is not a child that "
        "died on one; only an unhandled traceback means no work was done"
    )


def test_a_real_traceback_that_merely_mentions_importerror_is_not_fatal(warmer, tmp_path):
    """Half two, and the one the anchor exists for.

    Here the child DID raise, so "did it raise?" cannot separate the cases. The
    exception is a ``RuntimeError`` whose MESSAGE happens to contain the word -
    a vendor bridge reporting what it caught, which is a data condition and
    survivable. Only matching at the start of a traceback's exception line tells
    it apart from the child that could not load its code.
    """
    script = _child(tmp_path, """
        raise RuntimeError("vendor bridge reported ImportError and gave up")
    """)
    warmer._start_run_log(stamp="20260823_103100")
    warmer._run([sys.executable, "-u", str(script)], "stirf", record=False)
    assert warmer._SUBPROCESS_FAILURES == [], (
        "a child that raised a RuntimeError mentioning the word is not a child "
        "that failed to import; escalating it makes the STIRF job red on nights "
        "nothing is wrong"
    )


# ------------------------------------------------------------------ #
#          the accounting: a lost curve is not a slow curve          #
# ------------------------------------------------------------------ #


def test_the_real_service_summary_line_is_the_one_that_is_parsed():
    """Pinned to ``stirf_curve_service``'s actual format string.

    Copied from the ``logger.info`` call in ``_run_backfill_mode``. If that line
    is reworded, this test is the thing that says so - otherwise the accounting
    silently reads every curve as lost and every night goes red.
    """
    spec = importlib.util.spec_from_file_location("_warmer_fmt", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    real = ("2026-08-23 10:31:00 [INFO] Backfill summary for USD-SOFR-1D-Q12STIRT: "
            "windows=5 curve_partial_or_error=0 ts_partial_or_error=0")
    assert module._stirf_windows_banked(real, "") == 5
    assert module._stirf_windows_banked("", real) == 5, "the service logs to stderr"
    assert module._stirf_windows_banked("nothing like it", "") is None, (
        "a child that never printed the line must be distinguishable from one "
        "that printed windows=0"
    )
    assert module._stirf_windows_banked(
        "Backfill summary for X: windows=0 curve_partial_or_error=0 "
        "ts_partial_or_error=0", "") == 0


def _stirf_with_fake_run(warmer, monkeypatch, outcomes):
    """Drive the real STIRF job with a canned child result per curve."""
    calls = {"n": 0}

    def fake_run(cmd, label, timeout=None, record=True, skip_codes=(), on_output=None):
        rc, out = outcomes[calls["n"]]
        calls["n"] += 1
        if on_output is not None:
            on_output(out, "", rc)
        return rc

    monkeypatch.setattr(warmer, "_run", fake_run)
    import datetime
    day = datetime.date(2026, 8, 21)          # a Friday
    return warmer.warm_stirf_cme_session(day, day)


def test_a_curve_that_banked_nothing_is_a_lost_curve(warmer, monkeypatch):
    """The 2026-08-23 loss, at the job level: OK (98.7s) with a curve missing."""
    status = _stirf_with_fake_run(warmer, monkeypatch, [
        (1, ""),                                             # died on import
        (0, "Backfill summary for B: windows=1 x y"),
        (0, "Backfill summary for C: windows=1 x y"),
    ])

    assert len(warmer._SUBPROCESS_FAILURES) == 1, (
        "a curve that produced no timeseries at all must fail the job"
    )
    assert "banked no day at all" in warmer._SUBPROCESS_FAILURES[0].detail
    assert "2/3 curves banked" in status and "1 LOST" in status, (
        "the loss must be visible in the SUMMARY line too:\n" + status
    )


def test_a_curve_that_banked_some_days_is_still_only_a_warning(warmer, monkeypatch):
    """The half that must not change: a partial curve has always been survivable."""
    status = _stirf_with_fake_run(warmer, monkeypatch, [
        (1, "Backfill summary for A: windows=3 curve_partial_or_error=2 x"),
        (0, "Backfill summary for B: windows=1 x y"),
        (0, "Backfill summary for C: windows=1 x y"),
    ])

    assert warmer._SUBPROCESS_FAILURES == [], (
        "a curve that banked days exited 1 on quality, which is the case "
        "record=False was written for"
    )
    assert "3/3 curves banked" in status and "LOST" not in status


def test_all_three_curves_lost_reports_all_three(warmer, monkeypatch):
    status = _stirf_with_fake_run(warmer, monkeypatch, [(1, "")] * 3)
    assert len(warmer._SUBPROCESS_FAILURES) == 3
    assert "0/3 curves banked" in status
