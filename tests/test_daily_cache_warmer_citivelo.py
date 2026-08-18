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
    names = [name for name, _ in warmer.JOBS]
    for expected in (
        "CitiVelo CurveStore (intraday + EOD)",
        "CitiVelo swaption cube",
        "CitiVelo EOD timeseries",
        "CitiVelo swaption values EOD",
        "CitiVelo intraday timeseries",
    ):
        assert expected in names, f"{expected} is not in JOBS"


def test_the_store_warms_run_before_the_value_jobs(warmer):
    """Order is load-bearing, not cosmetic.

    A value job on an unwarmed date reaches Excel. On a schedule, unattended.
    """
    names = [name for name, _ in warmer.JOBS]
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
