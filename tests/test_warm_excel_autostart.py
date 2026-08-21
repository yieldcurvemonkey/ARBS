r"""The nightly may now START Excel, and the interesting cases are the refusals.

On 2026-08-20 six of seventeen jobs failed with ``ExcelNotRunningError`` because the
last process using Excel closed it, and nobody was at the machine at 18:15. Three
consecutive nights, three different causes -- a batch-0 abort, a 12,501 MB ceiling
refusal, then no Excel at all -- and only the middle one was about this repo's code.

``_repair_excel`` closes that gap, and every test here is about it doing so WITHOUT
acquiring any of the three properties that would make it worse than the outage:

* it must never destroy the user's unsaved work, so ``force=True`` is never passed;
* it must never loop, because a leaking add-in would otherwise spend the whole night
  being rescued, relaunched and re-exceeding the ceiling;
* it must never raise, because the caller's contract is "a reason string or None" and
  an exception there converts a SKIPPED Velocity block into a FAILED run -- the exact
  misreporting the SKIPPED/FAILED split was built to prevent.

The success path is one test. The other six are the ways this could go wrong.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WARMER = REPO / "scripts" / "daily_cache_warmer.py"


@pytest.fixture()
def warmer(tmp_path, monkeypatch):
    """A freshly imported warmer. Fresh per test because the one-repair-per-run
    latch (``_EXCEL_REPAIR_ATTEMPTED``) is module state, and a leaked True from an
    earlier test would make every later one pass for the wrong reason."""
    spec = importlib.util.spec_from_file_location("_warmer_autostart", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOG_DIR", str(tmp_path / "cache_warmer"))
    monkeypatch.setattr(module, "_CV_EXCEL_AUTOSTART", True)
    monkeypatch.setattr(module, "_EXCEL_REPAIR_ATTEMPTED", False)
    monkeypatch.setattr(module, "_CV_SIGNIN_TIMEOUT_S", 1.0)
    before = list(module.log.handlers)
    yield module
    for h in module.log.handlers:
        if h not in before:
            h.close()
    module.log.handlers[:] = before


class _Sup:
    """A stand-in supervisor that records exactly how it was called."""

    def __init__(self, *, launch_raises=None, restart_raises=None, client=object()):
        self.calls = []
        self.kwargs = []
        self._launch_raises = launch_raises
        self._restart_raises = restart_raises
        self._client = client

    def launch_excel(self, **kw):
        self.calls.append("launch_excel")
        self.kwargs.append(kw)
        if self._launch_raises:
            raise self._launch_raises
        return 4242

    def wait_for_addin(self, **kw):
        self.calls.append("wait_for_addin")
        self.kwargs.append(kw)
        return self._client

    def restart_excel(self, **kw):
        self.calls.append("restart_excel")
        self.kwargs.append(kw)
        if self._restart_raises:
            raise self._restart_raises
        return self._client


def _wire(monkeypatch, sup, mb_after):
    """Point the lazy imports inside ``_repair_excel`` at the stubs."""
    import MDP.CitiVelocityExcel as pkg
    import MDP.CitiVelocityExcel.memory_guard as guard

    monkeypatch.setattr(pkg, "supervisor", sup, raising=False)
    if isinstance(mb_after, Exception):
        def _boom():
            raise mb_after
        monkeypatch.setattr(guard, "excel_memory_mb", _boom)
    else:
        monkeypatch.setattr(guard, "excel_memory_mb", lambda: mb_after)


# --------------------------------------------------------------- the success path

def test_no_excel_is_started_and_signed_in(warmer, monkeypatch):
    sup = _Sup()
    _wire(monkeypatch, sup, mb_after=500.0)

    assert warmer._repair_excel("no Excel is running", over_ceiling=False) is None
    assert sup.calls == ["launch_excel", "wait_for_addin"]
    # The login pane's handler is inert for the first minutes after launch, so the
    # wait MUST be the pressing one; a plain wait never resolves in a started Excel.
    assert sup.kwargs[1]["press_login"] is True


# --------------------------------------------------------------- the refusals

def test_over_ceiling_restarts_and_never_forces(warmer, monkeypatch):
    """force=True discards the user's unsaved work. It must never be passed."""
    sup = _Sup()
    _wire(monkeypatch, sup, mb_after=400.0)

    assert warmer._repair_excel("Excel is at 12501 MB", over_ceiling=True) is None
    assert sup.calls == ["restart_excel"], "an over-ceiling Excel must be RESTARTED"
    assert "launch_excel" not in sup.calls, "a live Excel must not be launched over"
    assert sup.kwargs[0].get("force") is not True


def test_a_repair_that_relands_over_the_ceiling_still_blocks(warmer, monkeypatch):
    """wait_for_addin proves the add-in ANSWERS, not that the process is small.

    Without the re-probe this would have replaced a refusal with a connection to
    exactly the state the ceiling exists to refuse.
    """
    sup = _Sup()
    _wire(monkeypatch, sup, mb_after=warmer._CV_MEMORY_CEILING_MB + 1.0)

    why = warmer._repair_excel("Excel is at 12501 MB", over_ceiling=True)
    assert why is not None
    assert "still at or above" in why


def test_a_failed_repair_is_a_reason_not_an_exception(warmer, monkeypatch):
    sup = _Sup(launch_raises=RuntimeError("ShellExecute refused (code 2)"))
    _wire(monkeypatch, sup, mb_after=500.0)

    why = warmer._repair_excel("no Excel is running", over_ceiling=False)
    assert isinstance(why, str)
    assert "ShellExecute refused" in why


def test_only_one_repair_per_run(warmer, monkeypatch):
    """A leaking add-in must not turn the pre-flight into a restart loop."""
    sup = _Sup(restart_raises=RuntimeError("rescue failed, leaving Excel alone"))
    _wire(monkeypatch, sup, mb_after=500.0)

    first = warmer._repair_excel("Excel is at 12501 MB", over_ceiling=True)
    second = warmer._repair_excel("Excel is at 12501 MB", over_ceiling=True)

    assert first is not None and second is not None
    assert "already attempted" in second
    assert sup.calls == ["restart_excel"], "the second call must not re-enter the supervisor"


def test_autostart_off_refuses_and_never_touches_the_supervisor(warmer, monkeypatch):
    sup = _Sup()
    _wire(monkeypatch, sup, mb_after=500.0)
    monkeypatch.setattr(warmer, "_CV_EXCEL_AUTOSTART", False)

    why = warmer._repair_excel("no Excel is running", over_ceiling=False)
    assert why is not None and "autostart is off" in why
    assert sup.calls == []


def test_an_unreadable_reprobe_blocks_rather_than_assuming_success(warmer, monkeypatch):
    """None from the probe is "cannot see", never "nothing running" -- and what
    might be running is a 13 GB add-in."""
    sup = _Sup()
    _wire(monkeypatch, sup, mb_after=None)

    why = warmer._repair_excel("no Excel is running", over_ceiling=False)
    assert why is not None
    assert "cannot see a running instance" in why


# --------------------------------------------------------------- the seam

def test_preflight_routes_each_cause_to_its_own_repair(warmer, monkeypatch):
    """Absent Excel gets a launch; a bloated one gets a restart. Not interchangeable:
    launching over a live instance leaves the bloat, and restarting a machine with no
    Excel rescues nothing and wastes the run's one repair."""
    seen = []

    def _fake_repair(reason, *, over_ceiling):
        seen.append(over_ceiling)
        return None

    monkeypatch.setattr(warmer, "_repair_excel", _fake_repair)

    import MDP.CitiVelocityExcel.memory_guard as guard
    monkeypatch.setattr(guard, "excel_memory_mb", lambda: 0.0)
    assert warmer._excel_preflight() is None

    monkeypatch.setattr(guard, "excel_memory_mb",
                        lambda: warmer._CV_MEMORY_CEILING_MB + 10.0)
    assert warmer._excel_preflight() is None

    assert seen == [False, True]
