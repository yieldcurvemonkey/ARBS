"""The Citi Velocity jobs in the daily cache warmer.

Two things can break this silently and neither shows up until a scheduled run at
some unattended hour:

* a job referencing a script or flag that does not exist - argparse exits 2 and
  the warmer logs a warning nobody reads;
* the jobs running in the wrong ORDER. The value jobs read the CurveStore, and a
  date that is not warmed falls through to the LIVE Excel path. A scheduled task
  driving the user's signed-in Excel unattended is the one outcome the whole
  two-phase design exists to prevent.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WARMER = REPO / "scripts" / "daily_cache_warmer.py"


def _load():
    spec = importlib.util.spec_from_file_location("_daily_cache_warmer", WARMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def warmer():
    return _load()


def test_the_citivelo_jobs_are_registered(warmer):
    names = [job.name for job in warmer.WARM_JOBS]
    for expected in (
        "CitiVelo CurveStore (intraday + EOD)",
        "CitiVelo swaption cube",
        "CitiVelo EOD timeseries",
        "CitiVelo swaption values EOD",
        "CitiVelo intraday timeseries",
    ):
        assert expected in names, f"{expected} is not in WARM_JOBS"


def test_the_store_warms_run_before_the_value_jobs(warmer):
    """Order is load-bearing, not cosmetic.

    A value job on an unwarmed date reaches Excel. On a schedule, unattended.
    """
    names = [job.name for job in warmer.WARM_JOBS]
    store = names.index("CitiVelo CurveStore (intraday + EOD)")
    cube = names.index("CitiVelo swaption cube")
    eod = names.index("CitiVelo EOD timeseries")
    swaption_values = names.index("CitiVelo swaption values EOD")
    intraday = names.index("CitiVelo intraday timeseries")
    assert store < eod, "the curve store must be warmed before EOD values are priced"
    assert store < swaption_values, "the curve store must be warmed before swaption values are priced"
    assert cube < swaption_values, "the cube must be warmed before swaption values are priced"
    assert store < intraday, "the curve store must be warmed before intraday values"
    assert cube < eod or cube < intraday, "the cube warm belongs with the other store warms"


def test_every_script_the_citivelo_jobs_shell_out_to_exists(warmer):
    for name in (
        "citivelo_excel_intraday_warm.py",
        "citivelo_excel_warm.py",
        "citivelo_swaption_vol_warm.py",
        "citivelo_swaption_eod_warm.py",
    ):
        assert (REPO / "scripts" / name).is_file(), f"scripts/{name} is missing"


@pytest.mark.parametrize(
    "script, argv",
    [
        ("citivelo_excel_intraday_warm.py", ["fetch", "--help"]),
        ("citivelo_excel_intraday_warm.py", ["build", "--help"]),
        ("citivelo_excel_intraday_warm.py", ["status", "--help"]),
        ("citivelo_excel_warm.py", ["warm", "--help"]),
        ("citivelo_swaption_vol_warm.py", ["fetch", "--help"]),
        ("citivelo_swaption_vol_warm.py", ["build", "--help"]),
        ("citivelo_swaption_vol_warm.py", ["status", "--help"]),
    ],
)
def test_the_subcommands_the_jobs_invoke_are_real(script, argv):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / script), *argv],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    assert result.returncode == 0, f"{script} {' '.join(argv)} exited {result.returncode}"


def test_the_flags_the_jobs_pass_are_accepted():
    """argparse exits 2 on an unknown flag - catch that here, not at 3am."""
    checks = [
        ("citivelo_excel_intraday_warm.py", "fetch",
         ["--curves", "--start", "--end", "--recycle-every",
          "--memory-ceiling-mb", "--memory-abort-mb"]),
        ("citivelo_excel_intraday_warm.py", "build", ["--curves"]),
        ("citivelo_excel_warm.py", "warm", ["--curves", "--start", "--end"]),
        ("citivelo_swaption_vol_warm.py", "fetch", ["--currency", "--memory-abort-mb"]),
        ("citivelo_swaption_vol_warm.py", "build", ["--currency"]),
        ("citivelo_swaption_vol_warm.py", "status", ["--currency"]),
    ]
    for script, sub, flags in checks:
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / script), sub, "--help"],
            capture_output=True, text=True, cwd=str(REPO), timeout=300,
        )
        text = result.stdout + result.stderr
        for flag in flags:
            assert flag in text, f"{script} {sub} does not accept {flag}"


def test_the_intraday_grid_is_a_subset_not_the_whole_eod_grid(warmer):
    """The minute store holds ~1,100 points a day; pricing the full grid on a
    schedule would be a lot of numbers nobody asked for."""
    assert len(warmer._CITIVELO_INTRADAY_TENORS) < len(
        warmer._CITIVELO_EOD_OUTRIGHTS
        + warmer._CITIVELO_EOD_FORWARDS
        + warmer._CITIVELO_EOD_SPREADS
    )
    assert warmer._CITIVELO_INTRADAY_FREQ.endswith("min")


def test_only_warmed_currencies_are_scheduled(warmer):
    """The other fifteen Citi curves work live but are not warmed - pricing them
    here would drive Excel on a schedule."""
    assert set(warmer._CITIVELO_CURVES) == {
        "USD-SOFR-1D", "EUR-ESTR-1D", "GBP-SONIA-1D", "CAD-CORRA-1D", "JPY-TONAR-1D-LCH",
    }


def test_usd_sofr_forward_strip_can_synthesize_the_notebook_fly(warmer):
    tenors = warmer._citivelo_eod_tenors("USD-SOFR-1D")
    assert {"1y5y", "1y10y", "1y30y"}.issubset(tenors)


def test_swaption_value_warm_declares_both_persisted_inputs(warmer):
    job = next(j for j in warmer.WARM_JOBS if j.name == "CitiVelo swaption values EOD")
    assert set(job.requires) == {warmer._CV_CURVE_STORE, warmer._CV_SWAPTION_CUBE}


# ══════════════════════════════════════════════════════════════════════════
# The ceiling seam, and the depth pass the intraday job now carries
# ══════════════════════════════════════════════════════════════════════════


def test_the_probe_runs_for_jobs_that_only_FALL_THROUGH_to_excel(warmer):
    """``needs_excel`` is the wrong selector for "should we probe".

    Measured 2026-08-19: Excel at 12,501 MB, all three ``needs_excel`` jobs
    refused — and four jobs carrying ``needs_excel=False`` connected to the same
    Excel and wrote 382 tag parquets between 19:24 and 20:07. They do not NEED
    Excel; they need the tag cache, and reach for Excel only on a miss. A probe
    gated on ``needs_excel`` never runs for them, so the verdict they would have
    to consult does not exist.
    """
    seam = [
        job for job in warmer.WARM_JOBS
        if not job.needs_excel
        and any(str(a).startswith("CITIVELO") for a in job.requires)
    ]
    assert seam, "no fall-through job found; the selector under test is untested"
    for job in seam:
        assert any(
            str(a).startswith("CITIVELO") for a in (job.requires + job.provides)
        ), f"{job.name!r} would not trigger the pre-flight probe"


def test_a_selection_that_touches_no_velocity_asset_still_skips_the_probe(warmer):
    """The probe shells out to PowerShell against the live process.

    ``--jobs 1`` selects GSQUANT, which never touches Excel, and has no business
    paying for that — nor for anything the Velocity bridge does on the way.
    """
    offline_only = [
        job for job in warmer.WARM_JOBS
        if not job.needs_excel
        and not any(str(a).startswith("CITIVELO")
                    for a in (job.requires + job.provides))
    ]
    assert offline_only, "every job now touches Velocity; this guard is moot"
    assert any(job.name.startswith("GSQUANT") for job in offline_only)


def test_the_frb_value_job_builds_offline_when_the_preflight_refused(
    warmer, monkeypatch
):
    """The one fall-through job whose offline knob is a constructor flag.

    ``FixedRateBondsMDP`` reads ``offline`` off its constructor config, which is
    the only route a ``TimeseriesBuilder`` run has — ``TB.FixedRateBondsTB``
    calls ``bulk_get_data`` with a fixed kwarg set and forwards nothing. So on a
    night the ceiling refused the store warms, this job must build against the
    banked cache instead of opening a workbook.
    """
    seen = {}

    class _MDP:
        def __init__(self, source, **kwargs):
            # ``FixedRateBondsTB`` reads ``.source`` off the MDP it is handed, so
            # the stub carries it: a stub that does not is a test that fails for
            # a reason unrelated to what it is checking.
            self.source = source
            self.config = dict(kwargs)
            seen["source"] = source
            seen["offline"] = kwargs.get("offline")

    class _TB:
        def get_timeseries(self, **kwargs):
            seen["queries"] = len(kwargs.get("queries") or ())
            return None

    import MDP.FixedRateBonds.FixedRateBondsMDP as FRB
    import TB.TimeseriesBuilder as TBM

    monkeypatch.setattr(FRB, "FixedRateBondsMDP", _MDP)
    monkeypatch.setattr(TBM, "TimeseriesBuilder", _TB)
    monkeypatch.setattr(
        warmer, "_EXCEL_BLOCKED",
        "Excel is at 12501 MB, at or above the 3800 MB ceiling",
    )

    warmer.warm_citivelo_frb_values(None, None)

    assert seen["offline"] is True, (
        "the job connected to a live add-in on a night every guarded job refused"
    )
    assert seen["queries"], "the job did no work at all; that is not the fix"


def test_the_frb_value_job_stays_live_when_excel_is_fine(warmer, monkeypatch):
    """The control. Going offline unconditionally would write holes every night.

    Offline turns a cache miss into an empty column, which lands in the computed
    store looking exactly like a day Citi served nothing. That trade is worth
    making only when the alternative is a scheduled task opening workbooks
    against a 12.5 GB add-in.
    """
    seen = {}

    class _MDP:
        def __init__(self, source, **kwargs):
            self.source = source
            self.config = dict(kwargs)
            seen["offline"] = kwargs.get("offline")

    class _TB:
        def get_timeseries(self, **kwargs):
            return None

    import MDP.FixedRateBonds.FixedRateBondsMDP as FRB
    import TB.TimeseriesBuilder as TBM

    monkeypatch.setattr(FRB, "FixedRateBondsMDP", _MDP)
    monkeypatch.setattr(TBM, "TimeseriesBuilder", _TB)
    monkeypatch.setattr(warmer, "_EXCEL_BLOCKED", None)

    warmer.warm_citivelo_frb_values(None, None)

    assert seen["offline"] is False


def _stub_universe_warm(monkeypatch, *, forward, depth, order=None):
    import scripts.citivelo_ust_universe_warm as UW

    def _warm(*args, **kwargs):
        if order is not None:
            order.append("forward")
        return forward

    def _depth(**kwargs):
        if order is not None:
            order.append("depth")
        return depth

    monkeypatch.setattr(UW, "warm", _warm)
    monkeypatch.setattr(UW, "backfill_depth", _depth)
    return UW


_FORWARD_OK = {"stopped": False, "done": 1, "of": 1, "regressed": {}}


def test_the_intraday_job_runs_the_forward_window_before_the_depth_pass(
    warmer, monkeypatch
):
    """Order, and it is not cosmetic.

    A night that spends its whole budget walking backwards and never warmed today
    is a regression, not a feature. Depth is what the forward window structurally
    cannot do; it is not a substitute for it.
    """
    import datetime

    order = []
    _stub_universe_warm(
        monkeypatch, forward=_FORWARD_OK, order=order,
        depth={"weeks": 3, "passes": 1, "stopped": False, "reason": "",
               "deepest": None, "target": None},
    )

    warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))

    assert order == ["forward", "depth"], order


def test_a_spent_depth_budget_is_not_reported_as_a_skip(warmer, monkeypatch):
    """Running out of budget is the DESIGNED end of the backwards pass.

    It is meant to happen every night until the target is reached. Counting it as
    a skipped step would move the run's exit code to 2 permanently, which is the
    always-amber exit code this warmer's own docstring says nobody reads.
    """
    import datetime

    _stub_universe_warm(
        monkeypatch, forward=_FORWARD_OK,
        depth={"weeks": 12, "passes": 3, "stopped": True,
               "reason": "the 600s depth budget is spent (12 week(s) banked)",
               "deepest": None, "target": None},
    )

    before = len(warmer._SUBPROCESS_SKIPS)
    warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))
    assert len(warmer._SUBPROCESS_SKIPS) == before


def test_a_depth_pass_stopped_by_the_ceiling_IS_reported_as_a_skip(
    warmer, monkeypatch
):
    """The control: a stop that needs a human must reach the exit code.

    A silent stop is the "green while stale" shape this warm has been bitten by
    twice.
    """
    import datetime

    _stub_universe_warm(
        monkeypatch, forward=_FORWARD_OK,
        depth={"weeks": 2, "passes": 1, "stopped": True,
               "reason": "Excel reached 3600 MB (ceiling 3500)",
               "deepest": None, "target": None},
    )

    before = len(warmer._SUBPROCESS_SKIPS)
    try:
        warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))
        assert len(warmer._SUBPROCESS_SKIPS) == before + 1
        assert "Excel reached" in warmer._SUBPROCESS_SKIPS[-1].detail
    finally:
        del warmer._SUBPROCESS_SKIPS[before:]


def test_a_failed_forward_warm_never_reaches_the_depth_pass(warmer, monkeypatch):
    """Today comes first. A partial forward warm means today is missing.

    Spending the night's Excel budget going backwards over a cache whose current
    window did not warm is the wrong order in the only way that matters.
    """
    import datetime

    order = []
    _stub_universe_warm(
        monkeypatch, order=order,
        forward={"stopped": True, "done": 3, "of": 877,
                 "reason": "Excel reached 3600 MB", "regressed": {}},
        depth={"weeks": 0, "passes": 0, "stopped": False, "reason": "",
               "deepest": None, "target": None},
    )

    with pytest.raises(RuntimeError):
        warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))
    assert order == ["forward"], order


def test_the_depth_pass_can_be_switched_off_without_touching_code(
    warmer, monkeypatch
):
    """An env knob, because the first night after this ships is the risky one."""
    import datetime

    order = []
    _stub_universe_warm(
        monkeypatch, forward=_FORWARD_OK, order=order,
        depth={"weeks": 0, "passes": 0, "stopped": False, "reason": "",
               "deepest": None, "target": None},
    )
    monkeypatch.setenv("CITIVELO_UST_DEPTH_DAYS", "0")

    warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))
    assert order == ["forward"], "the depth pass ran with the knob at 0"


def test_excel_dying_between_the_forward_warm_and_the_depth_pass_keeps_the_alarm(
    warmer, monkeypatch
):
    """Depth may cost the run an exit code. It may not cost it the alarm.

    ``backfill_depth`` opens with its own ``assert_safe_to_connect``, and Excel
    grows without this repo touching it — 1,918 MB to 12,501 MB overnight on
    2026-08-18/19 with no cron job connected. So it can cross the ceiling in the
    seconds between the forward warm's last between-batch check and the depth
    call. Left to propagate, the runner's ``except excel_errors`` labels the
    WHOLE job SKIPPED — disowning a forward warm that already succeeded — and
    ``_report_coverage_regression`` never runs, which silences the alarm that
    exists to notice a bond that stopped updating.

    The alarm no longer RAISES for a thin regression - one bond of 877 is vendor
    noise, and raising from a STORE job disowns its asset and skips every
    consumer. It is recorded as a COVERAGE step instead. What this test pins is
    unchanged: the depth pass must not stop the alarm being reached.
    """
    import datetime

    from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError

    def _boom(**kwargs):
        raise ExcelTooLargeError("Excel is at 12501 MB, at or above the 3800 MB ceiling")

    _stub_universe_warm(
        monkeypatch,
        forward={"stopped": False, "done": 877, "of": 877,
                 "regressed": {"US91282CNG23": ["PRICE"]}},
        depth={},
    )
    import scripts.citivelo_ust_universe_warm as UW
    monkeypatch.setattr(UW, "backfill_depth", _boom)

    before = len(warmer._SUBPROCESS_SKIPS)
    try:
        warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))
        added = warmer._SUBPROCESS_SKIPS[before:]
        kinds = [s.returncode for s in added]
        assert "NOT RUN" in kinds, "the depth pass vanished without a trace"
        assert "COVERAGE" in kinds, "the coverage alarm was swallowed by the depth pass"
    finally:
        del warmer._SUBPROCESS_SKIPS[before:]


def test_a_defect_in_the_depth_pass_is_a_failure_and_still_keeps_the_alarm(
    warmer, monkeypatch
):
    """The control for the clause above: not every escape is an Excel outage.

    An unexpected exception in the backwards pass is a real defect and has to
    reach the exit code as FAILED rather than SKIPPED — but it still must not
    swallow the forward warm's coverage regression.
    """
    import datetime

    def _boom(**kwargs):
        raise ValueError("a real defect in the backwards walk")

    _stub_universe_warm(
        monkeypatch,
        forward={"stopped": False, "done": 877, "of": 877,
                 "regressed": {"US91282CNG23": ["PRICE"]}},
        depth={},
    )
    import scripts.citivelo_ust_universe_warm as UW
    monkeypatch.setattr(UW, "backfill_depth", _boom)

    before_f = len(warmer._SUBPROCESS_FAILURES)
    before_s = len(warmer._SUBPROCESS_SKIPS)
    try:
        warmer.warm_citivelo_ust_universe_intraday(None, datetime.date(2026, 8, 20))
        assert len(warmer._SUBPROCESS_FAILURES) == before_f + 1
        added = warmer._SUBPROCESS_SKIPS[before_s:]
        assert [s.returncode for s in added] == ["COVERAGE"], (
            "a defect was filed as a skip; SKIPPED means 'run the thing the "
            "message names', and nobody can act on a ValueError at 18:15 - the "
            "only skip here should be the coverage report"
        )
    finally:
        del warmer._SUBPROCESS_FAILURES[before_f:]
        del warmer._SUBPROCESS_SKIPS[before_s:]
