"""A job that reports its own coverage should have that reach the SUMMARY.

The runner shows a frame's shape and nothing else, so a job returning a string
had its own account of what it did dropped on the floor. Three do:

    warm_stirf_cme_session   -> "STIRF backfill: 5 days x 3 curves"
    warm_stirfo_eod          -> "STIRFO EOD: 5 days, 60 snapshots, 60 smiles"
    warm_ustf_invoice_caches -> "UST futures warm: 5 day(s)"

On the 2026-08-23 catch-up, STIRFO returned in 0.2 s and the log said
`OK (0.2s)`. That is indistinguishable from a job that did nothing — and this
whole branch exists because of jobs that reported OK while doing nothing. The
string said `5 days, 60 snapshots, 60 smiles`, which is the difference between
"it ran" and "it covered the week".
"""

import importlib.util
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def warmer():
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_report_under_test",
        os.path.join(REPO_ROOT, "scripts", "daily_cache_warmer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_string_result_reaches_the_status(warmer):
    status = warmer._job_status(12.5, "STIRFO EOD: 5 days, 60 snapshots, 60 smiles")
    assert status.startswith("OK (12.5s)")
    assert "60 snapshots" in status


def test_a_frame_still_reports_its_shape(warmer):
    frame = pd.DataFrame([[1.0, 2.0]], index=["d"], columns=["a", "b"])
    assert warmer._job_status(3.0, frame) == "OK (3.0s, 1 rows x 2 cols)"


def test_none_is_unchanged(warmer):
    assert warmer._job_status(1.0, None) == "OK (1.0s)"


def test_an_empty_string_adds_nothing(warmer):
    assert warmer._job_status(1.0, "   ") == "OK (1.0s)"


def test_a_long_string_is_clipped_so_summary_stays_readable(warmer):
    status = warmer._job_status(1.0, "x" * 5000)
    assert len(status) < 400


def test_a_frame_that_is_also_falsy_still_reports(warmer):
    """An EMPTY frame has a shape and must not be reported as a bare OK.

    (0, 0) is exactly the state that hid the GS Quant outage for a month, so it
    has to stay visible rather than being swallowed by a truthiness check.
    """
    assert warmer._job_status(2.0, pd.DataFrame()) == "OK (2.0s, 0 rows x 0 cols)"
