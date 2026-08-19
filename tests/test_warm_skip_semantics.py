r"""SKIPPED is a third outcome, and inventing it is what makes the exit code usable.

The warmer had two words for what happened to a job, OK and FAILED, and used
FAILED for three unrelated things. Measured over the ten retained runs in
``C:/Users/chris/clee/ARBS/logs/cache_warmer``:

**1. A consumer failing on its provider's failure.** ``utils.warm_jobs`` already
declared ``provides``/``requires`` per job, and ``assert_ordered`` already proved
the LIST was ordered - correctly, and uselessly, because nothing consulted the
runtime OUTCOME. On 2026-08-17 and 08-18 the CurveStore warm's EOD step exited 1,
and ``CitiVelo swaption values EOD`` then ran anyway and reported ``No common
CurveStore/CubeStore EOD dates for USD-SOFR-1D`` - which is not a bug in the
swaption job, it is the CurveStore's failure wearing a different name. Both
nights were counted twice and the second count named the wrong module. Verified
by measurement rather than inference: CurveStore's last stored day is 2026-08-14,
exactly what the single successful EOD warm wrote, and 08-17/08-18 are absent for
all five curves.

**2. An absent or bloated Excel.** An unattended 18:15 task depends on a
human-authenticated, memory-leaking Excel that only a human restart shrinks.
2026-08-14: five jobs FAILED in 187.8 s, all of them saying "Excel is at 6526 MB"
- one fact, rediscovered five times, actionable by nobody at 18:15. 2026-08-15:
no Excel at all, five jobs, 383.2 s.

Together those turned FAILED into the normal nightly state, and an exit code that
is always 1 is an exit code nobody reads. That is not a cosmetic problem: it is
how a cache write that persisted nothing and a subprocess error with no visible
cause both survived ten runs unnoticed.

So: **OK / FAILED / SKIPPED**, and exit **0 / 1 / 2**. FAILED means a defect
someone should read the log for. SKIPPED means the machine was not in a state to
warm and there is nothing to find.

And the two do different things to the jobs downstream, which is the distinction
:func:`test_a_FAILED_provider_blocks_the_whole_chain` and
:func:`test_an_excel_SKIP_does_not_block_its_consumers` pin from both sides. A
provider that FAILED may have written half a partition, so its consumers read
something that is neither yesterday's day nor today's. A provider SKIPPED for an
unavailable Excel wrote NOTHING - the guard refuses before connecting - and its
consumers read the CUMULATIVE tag cache. Blanket propagation cost ~2,300 s of work
that had been measured succeeding on both Excel-down nights, so they run, and each
records on its own SUMMARY line which provider was missing while it did.

None of this weakens a guard. ``assert_safe_to_connect`` still runs everywhere it
ran before, and :func:`test_the_pre_connect_gate_still_refuses` pins that: the
pre-flight is an addition, because 2026-08-11 proved Excel can cross the ceiling
*during* a run (jobs 1-6 completed, then jobs 9-11 refused at 3,886 MB). Only the
word for the outcome changed.

No Excel, no COM, no network: every job here is a local callable.
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.util
import pathlib
import sys

import pytest

from utils.warm_jobs import STORE, WarmJob

REPO = pathlib.Path(__file__).resolve().parents[1]
WARMER = REPO / "scripts" / "daily_cache_warmer.py"

_ASSET = "TEST-STORE-ASSET"


@pytest.fixture()
def warmer(tmp_path, monkeypatch):
    """A freshly imported warmer, logging to ``tmp_path``, Excel pre-flight off.

    Fresh per test because ``_SUBPROCESS_FAILURES`` is module state. The
    pre-flight is neutralised by default so these tests do not shell out to
    PowerShell and do not change answer depending on whether the user happens to
    have a workbook open; the tests that are ABOUT the pre-flight patch it back.
    """
    spec = importlib.util.spec_from_file_location("_warmer_skip", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOG_DIR", str(tmp_path / "cache_warmer"))
    # Stash the real probe BEFORE neutralising it. A test that wants the genuine
    # article cannot recover it from ``module._excel_preflight`` afterwards -
    # that name is the stub by then, and re-patching it to itself silently tests
    # nothing. (It did, briefly: four probe-table cases "passed" against a
    # function that always returned None.)
    module._excel_preflight_real = module._excel_preflight
    monkeypatch.setattr(module, "_excel_preflight", lambda: None)
    before = list(module.log.handlers)
    yield module
    for h in module.log.handlers:
        if h not in before:
            h.close()
    module.log.handlers[:] = before


def _run(module, monkeypatch, jobs):
    monkeypatch.setattr(module, "WARM_JOBS", list(jobs))
    monkeypatch.setattr(sys, "argv", ["daily_cache_warmer.py"])
    return module.main()


def _summary(module, monkeypatch):
    """Capture the SUMMARY lines, so a test can assert what a human would read."""
    lines: list[str] = []
    for level in ("info", "warning", "error"):
        real = getattr(module.log, level)

        def capture(msg, *args, _real=real, **kw):
            try:
                lines.append(msg % args if args else str(msg))
            except Exception:  # noqa: BLE001 - formatting is not what is under test
                lines.append(str(msg))
            return _real(msg, *args, **kw)

        monkeypatch.setattr(module.log, level, capture)
    return lines


# ------------------------------------------------------------------ #
#     1. a consumer must not run when its provider did not deliver    #
# ------------------------------------------------------------------ #


def test_a_consumer_is_skipped_when_its_provider_FAILED(warmer, monkeypatch):
    """The 2026-08-17/18 double-count, reproduced with two local callables.

    The consumer must not be called at all. Calling it and letting it fail is
    exactly the old behaviour: a second FAILED line naming the wrong module,
    which is what buried the CurveStore's own failure.
    """
    ran = []
    lines = _summary(warmer, monkeypatch)

    def provider(start, end):
        raise RuntimeError("EOD warm exited 1")

    def consumer(start, end):
        ran.append("consumer")

    code = _run(warmer, monkeypatch, [
        WarmJob("CurveStore warm", provider, kind=STORE, provides=(_ASSET,)),
        WarmJob("swaption values EOD", consumer, requires=(_ASSET,)),
    ])

    assert ran == [], "the consumer ran against a store its provider never warmed"
    assert code == 1, "a genuine provider failure is still exit 1"
    skipped = [l for l in lines if "SKIPPED" in l]
    assert skipped, "the consumer must be reported as SKIPPED"
    assert any("CurveStore warm" in l for l in skipped), (
        f"the skip must NAME the provider that caused it, got {skipped!r}"
    )


def test_a_consumer_RUNS_when_its_provider_succeeded(warmer, monkeypatch):
    """The control. Without it, "skip the consumer" could just mean "never run it"."""
    ran = []
    code = _run(warmer, monkeypatch, [
        WarmJob("CurveStore warm", lambda s, e: ran.append("provider"),
                kind=STORE, provides=(_ASSET,)),
        WarmJob("swaption values EOD", lambda s, e: ran.append("consumer"),
                requires=(_ASSET,)),
    ])
    assert ran == ["provider", "consumer"]
    assert code == 0


def test_an_unrelated_job_still_runs_after_a_provider_fails(warmer, monkeypatch):
    """Only the jobs that DECLARE the asset are skipped, not everything after."""
    ran = []

    def provider(start, end):
        raise RuntimeError("boom")

    code = _run(warmer, monkeypatch, [
        WarmJob("provider", provider, kind=STORE, provides=(_ASSET,)),
        WarmJob("consumer", lambda s, e: ran.append("consumer"), requires=(_ASSET,)),
        WarmJob("unrelated", lambda s, e: ran.append("unrelated")),
    ])
    assert ran == ["unrelated"]
    assert code == 1


def test_a_FAILED_provider_blocks_the_whole_chain(warmer, monkeypatch):
    """A provider that FAILED may have written half a store, so nothing downstream runs.

    This is the direction that must propagate all the way: the store is in a
    state that is neither yesterday's day nor today's, and a consumer reading it
    produces numbers nobody can attribute. One hop is not enough - the derived
    store would go on to look like a legitimate provider for the value job.
    """
    ran = []
    second = "TEST-SECOND-ASSET"

    def provider(start, end):
        raise RuntimeError("EOD warm exited 1 half way through the partition")

    code = _run(warmer, monkeypatch, [
        WarmJob("tags warm", provider, kind=STORE, provides=(_ASSET,)),
        WarmJob("derived store", lambda s, e: ran.append("derived"),
                kind=STORE, provides=(second,), requires=(_ASSET,)),
        WarmJob("values", lambda s, e: ran.append("values"), requires=(second,)),
    ])

    assert ran == [], "a FAILURE must carry down the whole chain, not just one hop"
    assert code == 1


def test_a_job_that_LOST_A_STEP_blocks_its_consumers_too(warmer, monkeypatch):
    """A store warm that returned cleanly having lost a shelled-out step FAILED.

    Every caller of ``_run`` discards the exit code on purpose - a dead intraday
    fetch still leaves work for the build and EOD phases - so a job can return
    ``None`` with a partition half written. That is the FAILED half of the
    distinction, not the SKIPPED half, and it has to block downstream exactly
    like a raised exception does. Nothing pinned it before; the propagation
    could be inverted here alone and every other test still passed.
    """
    ran = []

    def loses_a_step(start, end):
        warmer._SUBPROCESS_FAILURES.append(
            warmer._StepFailure("intraday fetch", 1, "MemoryError")
        )
        return None

    code = _run(warmer, monkeypatch, [
        WarmJob("CurveStore warm", loses_a_step, kind=STORE, provides=(_ASSET,)),
        WarmJob("swaption values EOD", lambda s, e: ran.append("consumer"),
                requires=(_ASSET,)),
    ])

    assert ran == [], (
        "the consumer ran against a store whose warm lost a step - the partition "
        "may be half written, which is the FAILED case and must block"
    )
    assert code == 1


def test_an_excel_SKIP_does_not_block_its_consumers(warmer, monkeypatch):
    r"""SKIPPED and FAILED are different facts about a provider, and only one blocks.

    A provider skipped because Excel was shut, bloated or signed out wrote
    NOTHING - the guard refuses before connecting. Its consumers read the tag
    cache, which is CUMULATIVE, so they run against tags banked on earlier
    nights. Blanket propagation stopped attempting work that had already been
    measured succeeding on exactly these nights:

      2026-08-14 (Excel at 6,526 MB)  FRB values OK 23.3 s, UST timeseries OK
                                      790.8 s, swap spreads OK 16.0 s
      2026-08-15 (no Excel at all)    OK 116.5 s, OK 701.8 s, OK 653.8 s

    ~2,300 s of demonstrably successful work. The counter-argument - job 16
    builds offline, so an unbanked tag becomes a hole - is answered by the
    provenance test below, not by refusing to run.
    """
    ran = []
    second = "TEST-SECOND-ASSET"
    jobs = [
        WarmJob("tags warm", lambda s, e: ran.append("tags"),
                kind=STORE, provides=(_ASSET,), needs_excel=True),
        WarmJob("derived store", lambda s, e: ran.append("derived"),
                kind=STORE, provides=(second,), requires=(_ASSET,)),
        WarmJob("values", lambda s, e: ran.append("values"), requires=(second,)),
    ]

    # The control first: nothing blocks, all three run.
    assert _run(warmer, monkeypatch, jobs) == 0
    assert ran == ["tags", "derived", "values"]

    ran.clear()
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: "no Excel is running")
    code = _run(warmer, monkeypatch, jobs)

    assert ran == ["derived", "values"], (
        "the consumers were skipped along with their Excel-blocked provider, "
        "throwing away work that has been measured succeeding on exactly this night"
    )
    assert code == 2, "the provider's own skip is still counted, so the run is not a 0"


def test_a_consumer_that_ran_without_its_provider_records_that_in_its_result(warmer, monkeypatch):
    """Job 16's warning, honoured as provenance rather than as a refusal.

    ``CITIVELO UST timeseries values EOD`` builds OFFLINE: a tag its provider did
    not bank comes back as an empty column and writes a hole that looks like a
    day Citi served nothing. The hole is not the problem - a hole nobody can
    attribute is. So the consumer's own SUMMARY line has to say which provider
    was missing when it ran.
    """
    lines = _summary(warmer, monkeypatch)
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: "Excel is at 6526 MB")

    code = _run(warmer, monkeypatch, [
        WarmJob("CITIVELO UST universe tags EOD (store)", lambda s, e: None,
                kind=STORE, provides=(_ASSET,), needs_excel=True),
        WarmJob("CITIVELO UST timeseries values EOD", lambda s, e: None,
                requires=(_ASSET,)),
    ])

    assert code == 2
    consumer = [
        l for l in lines
        if "CITIVELO UST timeseries values EOD" in l and "OK (" in l
    ]
    assert consumer, f"the consumer did not report OK at all: {lines!r}"
    assert any("ran without" in l and _ASSET in l for l in consumer), (
        f"the consumer ran against an unwarmed provider and said nothing about it, "
        f"so its output is not attributable: {consumer!r}"
    )


def test_a_runtime_excel_skip_is_also_non_blocking(warmer, monkeypatch):
    """The pre-flight cannot cover every case, and the two skips are the same fact.

    2026-08-11: jobs 1-6 completed and Excel was over the ceiling by the time
    jobs 9-11 ran. A provider that refused mid-run refused BEFORE connecting -
    ``assert_safe_to_connect`` is a pre-connect gate - so it wrote nothing, and
    its consumers are in the same position as under a blocked pre-flight.
    """
    from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError

    ran = []

    def refuses(start, end):
        raise ExcelTooLargeError("Refusing to start: Excel is at 6526 MB")

    code = _run(warmer, monkeypatch, [
        WarmJob("tags warm", refuses, kind=STORE, provides=(_ASSET,)),
        WarmJob("values", lambda s, e: ran.append("values"), requires=(_ASSET,)),
    ])

    assert ran == ["values"], (
        "an Excel refusal mid-run wrote nothing, so its consumer must still read "
        "the banked cache"
    )
    assert code == 2


# ------------------------------------------------------------------ #
#                        2. the Excel pre-flight                     #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "probe_mb, expect_block, expect_words",
    [
        (None, True, "probe"),        # unreadable: says NOTHING about what is running
        (0.0, True, "no Excel"),      # definitively nothing to connect to
        (6526.0, True, "ceiling"),    # the measured 2026-08-14 state
        (3800.0, True, "ceiling"),    # AT the ceiling is over it - the guard is >=
        (250.0, False, ""),           # a normal, freshly opened session
    ],
)
def test_the_preflight_probe_table(warmer, monkeypatch, probe_mb, expect_block, expect_words):
    """One probe, four distinct answers, three of which need different humans.

    ``None`` is not "no Excel": ``memory_guard`` returns ``0.0`` for that and
    ``None`` only when the probe could not be read at all - and what might be
    running behind an unreadable probe is a 13 GB add-in. Collapsing the two is
    what makes a gate fail open.
    """
    import MDP.CitiVelocityExcel.memory_guard as G

    monkeypatch.setattr(G, "excel_memory_mb", lambda *a, **k: probe_mb)

    reason = warmer._excel_preflight_real()
    if not expect_block:
        assert reason is None, f"{probe_mb} MB is under the ceiling and must not block"
    else:
        assert reason, f"{probe_mb} MB must block the Excel jobs"
        assert expect_words.lower() in reason.lower(), reason


def test_the_preflight_skips_only_the_jobs_that_declare_needs_excel(warmer, monkeypatch):
    """An offline job must not be collateral damage of a shut Excel."""
    ran = []
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: "Excel is at 6526 MB")

    code = _run(warmer, monkeypatch, [
        WarmJob("UST universe tags EOD", lambda s, e: ran.append("excel"), needs_excel=True),
        WarmJob("GSQUANT USD-OIS EOD", lambda s, e: ran.append("offline")),
    ])

    assert ran == ["offline"], "an offline job must still run when Excel is unusable"
    assert code == 2


def test_a_broken_probe_does_not_take_the_whole_run_down(warmer, monkeypatch):
    """Bookkeeping must not be the reason a warm does not warm.

    An Excel job is in the selection deliberately. Without one the pre-flight is
    not asked at all (see the no-op test below), and this would pass against a
    probe that raises - a test of nothing, which is how the unguarded import in
    ``_excel_preflight`` survived.
    """
    import MDP.CitiVelocityExcel.memory_guard as G

    def explode(*a, **k):
        raise OSError("PowerShell is missing")

    monkeypatch.setattr(warmer, "_excel_preflight", warmer._excel_preflight_real)
    monkeypatch.setattr(G, "excel_memory_mb", explode)

    ran = []
    code = _run(warmer, monkeypatch, [
        WarmJob("offline", lambda s, e: ran.append("x")),
        WarmJob("velocity", lambda s, e: ran.append("velocity"), needs_excel=True),
    ])
    assert ran == ["x"], "the offline job must still run when the probe is broken"
    assert code == 2, "a broken probe blocks the Excel jobs and only those"


# ------------------------------------------------------------------ #
#     2b. a Velocity bridge that will not IMPORT (finding A)          #
# ------------------------------------------------------------------ #
#
# ``_excel_unavailable_errors`` guards its import of the same bridge and states
# the intent in its own docstring - "the eleven jobs that never touch Excel
# still warm". ``_excel_preflight`` did not: its
# ``from ...memory_guard import excel_memory_mb`` sat OUTSIDE the try, and
# ``main()`` called it unconditionally before job 1. Measured with the bridge
# poisoned out of ``sys.modules``:
#
#   _excel_unavailable_errors()  -> ()   + a warning   (degrades, as documented)
#   _excel_preflight()           -> ModuleNotFoundError
#   main(--jobs 1)               -> ModuleNotFoundError, and job 1 is GSQUANT,
#                                   which never touches Excel.
#
# Exit code 1 with a traceback, so not a false success - but all seventeen jobs
# lost to a fault that concerns five of them.


@contextlib.contextmanager
def _velocity_bridge_broken(monkeypatch):
    """Make every ``import MDP.CitiVelocityExcel.<x>`` raise, the way a real one would.

    ``None`` in ``sys.modules`` is what CPython leaves behind for a module that
    failed to initialise, and importing it raises ``ImportError``. This is the
    same stimulus the reviewer's repro used, so the two are comparable.
    """
    for name in (
        "MDP.CitiVelocityExcel.memory_guard",
        "MDP.CitiVelocityExcel.errors",
    ):
        monkeypatch.setitem(sys.modules, name, None)
    yield


def test_a_velocity_bridge_that_will_not_import_cannot_stop_a_non_excel_selection(
    warmer, monkeypatch
):
    """Finding A, at the level it actually bit: ``main()``.

    Eleven of the seventeen jobs never touch Excel. A bridge that will not import
    is a fact about the other six, and it must cost exactly those.
    """
    monkeypatch.setattr(warmer, "_excel_preflight", warmer._excel_preflight_real)
    ran = []

    with _velocity_bridge_broken(monkeypatch):
        code = _run(warmer, monkeypatch, [
            WarmJob("GSQUANT USD-OIS EOD", lambda s, e: ran.append("gsquant")),
            WarmJob("ERIS USD-SOFR-1D EOD", lambda s, e: ran.append("eris")),
        ])

    assert ran == ["gsquant", "eris"], (
        "a Velocity bridge that will not import took down a selection with no "
        "Velocity job in it"
    )
    assert code == 0


def test_a_bridge_that_will_not_import_still_refuses_the_excel_jobs(warmer, monkeypatch):
    """FAIL CLOSED. A probe that cannot be loaded says nothing about what is running.

    The one thing worse than losing the eleven offline jobs is letting a Velocity
    job connect because the guard could not be loaded - what might be running is
    the 13,884 MB add-in measured on 2026-08-08.
    """
    monkeypatch.setattr(warmer, "_excel_preflight", warmer._excel_preflight_real)
    ran = []

    with _velocity_bridge_broken(monkeypatch):
        code = _run(warmer, monkeypatch, [
            WarmJob("GSQUANT USD-OIS EOD", lambda s, e: ran.append("gsquant")),
            WarmJob("CITIVELO swap-spread tags (store)",
                    lambda s, e: ran.append("velocity"), needs_excel=True),
        ])

    assert "velocity" not in ran, (
        "a Velocity job was started while the guard that gates it could not even "
        "be imported"
    )
    assert ran == ["gsquant"]
    assert code == 2


def test_the_preflight_is_not_asked_at_all_when_nothing_selected_needs_excel(
    warmer, monkeypatch
):
    """``--jobs 1`` has no business shelling out to PowerShell against EXCEL.EXE.

    The probe is a ``Get-Process`` against the live process and drags the
    Velocity bridge in behind it. A selection with no ``needs_excel`` job gets
    neither.
    """
    asked = []
    monkeypatch.setattr(warmer, "_excel_preflight",
                        lambda: asked.append("probed") or None)

    assert _run(warmer, monkeypatch, [WarmJob("GSQUANT USD-OIS EOD", lambda s, e: None)]) == 0
    assert asked == [], "the pre-flight probed Excel for a selection that never touches it"

    # ... and it IS asked as soon as one selected job needs Excel.
    _run(warmer, monkeypatch, [
        WarmJob("GSQUANT USD-OIS EOD", lambda s, e: None),
        WarmJob("CITIVELO swap-spread tags (store)", lambda s, e: None, needs_excel=True),
    ])
    assert asked == ["probed"]


# ------------------------------------------------------------------ #
#              3. reclassifying a runtime Excel failure               #
# ------------------------------------------------------------------ #


def test_an_excel_error_raised_mid_run_is_SKIPPED_not_FAILED(warmer, monkeypatch):
    """The pre-flight cannot cover this, which is why the guards all stay.

    2026-08-11: jobs 1-6 completed normally and Excel was over the ceiling by the
    time jobs 9-11 ran. The environment degrades DURING a run, so a job's own
    ``assert_safe_to_connect`` is still the thing that refuses - this only
    changes what the refusal is called.
    """
    from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError

    def refuses(start, end):
        raise ExcelTooLargeError("Refusing to start: Excel is at 6526 MB")

    code = _run(warmer, monkeypatch, [WarmJob("UST universe tags EOD", refuses)])
    assert code == 2, "an Excel that grew mid-run is not a defect in this warm"


def test_an_unsigned_addin_is_SKIPPED_not_FAILED(warmer, monkeypatch):
    """Excel running but signed out: invisible to the probe, same human action."""
    from MDP.CitiVelocityExcel.errors import ExcelNotRunningError

    def refuses(start, end):
        raise ExcelNotRunningError()

    code = _run(warmer, monkeypatch, [WarmJob("swap-spread tags", refuses)])
    assert code == 2


def test_an_ordinary_exception_is_still_FAILED(warmer, monkeypatch):
    """Teeth. If everything became a skip, the exit code would be useless again."""
    def boom(start, end):
        raise ValueError("a real bug")

    code = _run(warmer, monkeypatch, [WarmJob("something", boom)])
    assert code == 1


# ------------------------------------------------------------------ #
#                          4. the exit code                          #
# ------------------------------------------------------------------ #


def _ok(s, e):
    return None


def _fails(s, e):
    raise RuntimeError("a real defect")


def _needs_excel(s, e):  # pragma: no cover - never called; the pre-flight skips it
    raise AssertionError("this job must not have been run")


@pytest.mark.parametrize(
    "jobs, blocked, expected, why",
    [
        ([WarmJob("a", _ok)], None, 0, "everything warmed"),
        ([WarmJob("a", _fails)], None, 1, "a real defect"),
        ([WarmJob("a", _needs_excel, needs_excel=True)], "no Excel", 2,
         "nothing broken, the machine was not ready"),
        ([WarmJob("a", _ok), WarmJob("b", _needs_excel, needs_excel=True)], "no Excel", 2,
         "a partial warm with no failure is still exit 2"),
        ([WarmJob("a", _fails), WarmJob("b", _needs_excel, needs_excel=True)], "no Excel", 1,
         "a failure alongside a skip must not be softened to 2"),
    ],
)
def test_the_exit_code_table(warmer, monkeypatch, jobs, blocked, expected, why):
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: blocked)
    assert _run(warmer, monkeypatch, jobs) == expected, why


# ------------------------------------------------------------------ #
#                    5. the guards are NOT weakened                  #
# ------------------------------------------------------------------ #


def test_the_pre_connect_gate_still_refuses(monkeypatch, tmp_path):
    r"""``warm()`` must still refuse BEFORE it constructs anything that connects.

    This is the rail the pre-flight is forbidden to replace. The check has one
    hard requirement - it must not itself connect - and an earlier version got
    that wrong by asking a *connected* client for its memory, which is a guard
    that runs after the act it exists to prevent.
    """
    import scripts.citivelo_ust_universe_warm as W
    import MDP.CitiVelocityExcel.bonds.fetcher as F
    from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError

    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(W, "MANIFEST", tmp_path / "manifest.json")

    def refuse(*a, **k):
        raise ExcelTooLargeError("Refusing to start: Excel is at 6526 MB")

    import MDP.CitiVelocityExcel.memory_guard as G
    monkeypatch.setattr(G, "assert_safe_to_connect", refuse)

    def must_not_be_built(*a, **k):
        raise AssertionError("a fetcher was constructed AFTER the ceiling was breached")

    monkeypatch.setattr(F, "CitiVeloBondFetcher", must_not_be_built)

    with pytest.raises(ExcelTooLargeError):
        W.warm("intraday", start=datetime.date(2026, 8, 16), end=datetime.date(2026, 8, 18),
               do_refresh=False)


def test_the_shipped_registry_marks_exactly_the_whole_job_excel_warms():
    """Pins WHICH jobs are Excel-only, because the split is measured, not obvious.

    Jobs 7 and 8 drive Excel in one step out of four and do real offline work in
    the others - ``citivelo_excel_warm`` states it "runs entirely offline against
    the banked tag cache". Marking them ``needs_excel`` would throw the offline
    phases away every time Excel happened to be shut, so they probe around their
    own fetch step instead.
    """
    spec = importlib.util.spec_from_file_location("_warmer_registry", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    marked = {j.name for j in module.WARM_JOBS if j.needs_excel}
    assert marked == {
        "CITIVELO UST universe tags EOD (store)",
        "CITIVELO UST universe tags INTRADAY (store)",
        "CITIVELO swap-spread tags (store)",
    }, marked


# ------------------------------------------------------------------ #
#      6. jobs 7 and 8: the pre-flight costs the FETCH, not the job    #
# ------------------------------------------------------------------ #
#
# These two are the reason ``needs_excel`` is not simply "is this a Velocity
# job". Each shells out three or four times and only ONE of those steps drives
# Excel: ``citivelo_excel_warm`` states it "runs entirely offline against the
# banked tag cache - no Excel, no network", and the swaption ``build`` assembles
# cubes from cached quotes. Skipping the whole job on a bad pre-flight would
# throw away precisely the phases that advance the CurveStore and the cube
# store - and those are the phases that were failing for their own reasons
# (H2: a stale DAILY par grid), which nobody could diagnose while the job was
# also being blamed for Excel.
#
# Neither script carried a pre-connect ceiling check of its own.
# ``citivelo_excel_intraday_warm`` tests the ceiling only inside its fetch loop
# at every 20th window, so a short fetch never tested it at all: on 2026-08-11
# that step exited 0 having connected to an Excel measured at 3,886 MB one
# minute later.


class _Recorder:
    """Records every ``subprocess.run`` command and reports success."""

    def __init__(self):
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmds.append(list(cmd))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    def steps(self):
        """The sub-command of each call, e.g. ``fetch``/``build``/``status``."""
        return [c[3] if len(c) > 3 else "" for c in self.cmds]


_TUESDAY = datetime.date(2026, 8, 18)


def test_a_blocked_preflight_costs_the_curvestore_fetch_and_nothing_else(warmer, monkeypatch):
    """Job 7's three offline phases must still run when Excel is unusable."""
    rec = _Recorder()
    monkeypatch.setattr(warmer.subprocess, "run", rec)
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: "Excel is at 6526 MB")

    warmer.warm_citivelo_curve_stores(_TUESDAY, _TUESDAY)

    assert "fetch" not in rec.steps(), (
        "the fetch drives Excel and must not start when the pre-flight refuses"
    )
    assert rec.steps() == ["build", "warm", "status"], rec.steps()
    assert warmer._SUBPROCESS_FAILURES == [], (
        "a step that was deliberately SKIPPED is not a step that FAILED"
    )


def test_an_open_preflight_still_runs_the_curvestore_fetch(warmer, monkeypatch):
    """The control: with Excel healthy, all four phases run as before."""
    rec = _Recorder()
    monkeypatch.setattr(warmer.subprocess, "run", rec)
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: None)

    warmer.warm_citivelo_curve_stores(_TUESDAY, _TUESDAY)

    assert rec.steps() == ["fetch", "build", "warm", "status"], rec.steps()


def test_a_blocked_preflight_costs_the_vol_fetch_and_nothing_else(warmer, monkeypatch):
    """Job 8, same split: ``build`` and ``status`` need no Excel."""
    rec = _Recorder()
    monkeypatch.setattr(warmer.subprocess, "run", rec)
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: "no Excel is running")

    warmer.warm_citivelo_swaption_cube(_TUESDAY, _TUESDAY)

    assert rec.steps() == ["build", "status"], rec.steps()
    assert warmer._SUBPROCESS_FAILURES == []


def test_an_open_preflight_still_runs_the_vol_fetch(warmer, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(warmer.subprocess, "run", rec)
    monkeypatch.setattr(warmer, "_excel_preflight", lambda: None)

    warmer.warm_citivelo_swaption_cube(_TUESDAY, _TUESDAY)

    assert rec.steps() == ["fetch", "build", "status"], rec.steps()
