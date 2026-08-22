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


# ══════════════════════════════════════════════════════════════════════════
# Memory is not liveness. Every branch above reads a number from Get-Process;
# none of them asks whether the add-in ANSWERS. A signed-out Excel under the
# ceiling passed all of them and then failed every Velocity job in turn -- which
# is how the swaption cube stopped writing after 2026-08-17.
# ══════════════════════════════════════════════════════════════════════════


def _wire_probe(monkeypatch, warmer, outcome, sup=None):
    """Point the liveness probe's lazy imports at a stub with the given outcome."""
    import MDP.CitiVelocityExcel.com_client as CC

    def _connect(**_k):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(CC.CitiVelocityExcelClient, "connect", staticmethod(_connect))
    if sup is not None:
        import MDP.CitiVelocityExcel as pkg
        import MDP.CitiVelocityExcel.memory_guard as guard
        monkeypatch.setattr(pkg, "supervisor", sup, raising=False)
        monkeypatch.setattr(guard, "excel_memory_mb", lambda: 500.0)


def test_a_healthy_addin_lets_the_jobs_run(warmer, monkeypatch):
    _wire_probe(monkeypatch, warmer, object())
    assert warmer._repair_addin_if_silent() is None


def test_a_signed_out_addin_presses_login_and_does_not_restart(warmer, monkeypatch):
    """The remedy differs from the memory case, and using the wrong one is expensive.

    A signed-out add-in does not need Excel restarted -- it needs the Login pane
    pressed. Restarting instead throws away a healthy session and spends ~2.8 min of
    sign-in to arrive at the same place.
    """
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError

    sup = _Sup()
    _wire_probe(monkeypatch, warmer, AddInNotSignedInError(), sup=sup)

    assert warmer._repair_addin_if_silent() is None
    assert sup.calls == ["wait_for_addin"], f"expected a Login press, saw {sup.calls}"
    assert "restart_excel" not in sup.calls, "a healthy session must not be restarted"
    assert "launch_excel" not in sup.calls, "Excel is already running"
    assert sup.kwargs[0]["press_login"] is True


def test_an_excel_outside_the_running_object_table_is_restarted(warmer, monkeypatch):
    """The memory probe sees a process and the bridge cannot bind to it. A Login press
    cannot fix that; only a restart can."""
    from MDP.CitiVelocityExcel.errors import ExcelNotRunningError

    sup = _Sup()
    _wire_probe(monkeypatch, warmer, ExcelNotRunningError(), sup=sup)

    assert warmer._repair_addin_if_silent() is None
    assert sup.calls == ["restart_excel"], f"expected a restart, saw {sup.calls}"
    assert sup.kwargs[0].get("force") is not True


def test_an_unreadable_probe_does_not_block_the_run(warmer, monkeypatch):
    """The probe is a diagnostic, not a gate. If IT breaks, the memory reading already
    said the machine was usable, and refusing on a broken probe would ground the whole
    Velocity block for a reason that has nothing to do with Excel."""
    _wire_probe(monkeypatch, warmer, RuntimeError("COM went sideways"))
    assert warmer._repair_addin_if_silent() is None


def test_a_login_press_that_does_not_take_escalates_to_a_full_restart(warmer, monkeypatch):
    """The user's requirement, stated directly: if COM is having issues, kill the
    instance and come back through the full auth path.

    A signed-out add-in gets the cheap remedy first because it keeps the session and its
    warm series cache. But "pressed Login and it did not take" is a real outcome -- the
    pane's handler is inert for minutes after a launch, and an Excel can be signed out
    AND wedged at once -- so the run must not stop there.
    """
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError

    sup = _Sup()

    def _wait_fails(**kw):
        sup.calls.append("wait_for_addin")
        sup.kwargs.append(kw)
        raise RuntimeError("the add-in did not sign in within 15 minutes")

    sup.wait_for_addin = _wait_fails
    _wire_probe(monkeypatch, warmer, AddInNotSignedInError(), sup=sup)

    assert warmer._repair_addin_if_silent() is None
    assert sup.calls == ["wait_for_addin", "restart_excel"], (
        f"expected the cheap remedy THEN the escalation, saw {sup.calls}")
    assert sup.kwargs[-1].get("force") is not True, (
        "even the escalation rescues unsaved work rather than forcing")


def test_the_escalation_is_bounded_and_never_loops(warmer, monkeypatch):
    """Two remedies inside one latched repair, and no third attempt anywhere."""
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError

    sup = _Sup()

    def _boom(**kw):
        sup.calls.append("wait_for_addin")
        raise RuntimeError("nope")

    sup.wait_for_addin = _boom
    sup._restart_raises = RuntimeError("rescue failed, leaving Excel alone")
    _wire_probe(monkeypatch, warmer, AddInNotSignedInError(), sup=sup)

    first = warmer._repair_addin_if_silent()
    assert isinstance(first, str), "a repair that exhausts both remedies must say so"
    assert sup.calls == ["wait_for_addin", "restart_excel"]

    second = warmer._repair_addin_if_silent()
    assert "already attempted" in second
    assert sup.calls == ["wait_for_addin", "restart_excel"], "the latch must hold"


def test_the_preflight_reaches_the_liveness_probe(warmer, monkeypatch):
    """End-to-end through _excel_preflight, not the probe in isolation.

    The distinction matters: the other liveness tests call _repair_addin_if_silent
    directly, so deleting its CALL SITE in the pre-flight leaves them all green. This is
    the only test that fails if the pre-flight goes back to trusting the memory reading
    alone -- which is the state that let three nights of swaption cubes go unwarmed.
    """
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError

    sup = _Sup()
    _wire_probe(monkeypatch, warmer, AddInNotSignedInError(), sup=sup)

    assert warmer._excel_preflight() is None
    assert sup.calls == ["wait_for_addin"], (
        "the pre-flight passed a healthy memory reading and never asked whether the "
        f"add-in answers; saw {sup.calls}")


# ══════════════════════════════════════════════════════════════════════════
# The GS Quant job priced nothing for at least four nights and reported OK
# each time -- "OK (68.6s, 0 rows x 0 cols)". These pin the two halves of
# the fix: the store is warmed BEFORE pricing, and an empty frame is not a
# success.
# ══════════════════════════════════════════════════════════════════════════


def _gs_stub(warmer, monkeypatch, frame, calls):
    """Stub the store warm, the MDP and the TB so the job's own logic is what is tested.

    Patched at the SOURCE modules, not on the warmer. ``warm_gsquant_ois_eod`` does its
    imports inside the function body, so every name it uses is re-resolved from its own
    module on each call and an attribute set on the warmer is simply never consulted --
    which is how the first version of these tests failed while the code was correct.
    """
    import scripts.warm_gsquant_curve_store as W
    import MDP.IRSwaps.IRSwapsMDP as MDPMOD
    import TB.IRSwapsTB as TBMOD
    import TB.TimeseriesBuilder as TBB

    monkeypatch.setattr(W, "warm", lambda **kw: calls.append(kw) or {})
    monkeypatch.setattr(MDPMOD, "IRSwapsMDP", lambda **kw: object())
    monkeypatch.setattr(TBMOD, "IRSwapsTB", lambda *a, **k: object())

    class _TB:
        def get_timeseries(self, **kw):
            calls.append("priced")
            return frame

    monkeypatch.setattr(TBB, "TimeseriesBuilder", lambda *a, **k: _TB())


def test_an_empty_gsquant_frame_is_not_a_success(warmer, monkeypatch):
    """A value job that priced nothing must read FAILED, not green.

    The runner prints whatever shape it is handed. With no guard, four consecutive
    nights of an empty read were reported as OK and nobody looked.
    """
    import datetime
    import pandas as pd

    calls = []
    _gs_stub(warmer, monkeypatch, pd.DataFrame(), calls)
    d = datetime.date(2026, 8, 20)

    with pytest.raises(RuntimeError, match="priced NOTHING"):
        warmer.warm_gsquant_ois_eod(d, d)


def test_the_curve_store_is_warmed_before_pricing(warmer, monkeypatch):
    """Order is the whole fix: the fast path READS the store and returns {} on a miss,
    so pricing first would find nothing to read."""
    import datetime
    import pandas as pd

    calls = []
    _gs_stub(warmer, monkeypatch, pd.DataFrame({"USD-OIS 10Y RATE": [4.3]}), calls)
    d = datetime.date(2026, 8, 20)

    out = warmer.warm_gsquant_ois_eod(d, d)
    assert len(out.columns) == 1
    assert calls and calls[-1] == "priced", "pricing must be the LAST thing that happens"
    assert isinstance(calls[0], dict), "the store warm must run FIRST"
    assert tuple(calls[0]["curves"]) == tuple(warmer._GSQUANT_CURVES), (
        "the warm must cover exactly the curves the job is about to price")
