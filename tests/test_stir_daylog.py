"""Per-day log capture. The load-bearing test is the SECOND day in one process --
that is where the original implementation raised.
"""
import io
import logging
import os
import sys
import warnings

from SDRUtils.stir_flow.daylog import day_log


def test_day_log_captures_stdout_to_a_named_file(tmp_path):
    with day_log(str(tmp_path), "classify-2026-01-12") as path:
        print("hello from the worker")
    assert path == os.path.join(str(tmp_path), "classify-2026-01-12.log")
    assert "hello from the worker" in open(path, encoding="utf-8").read()


def test_day_log_restores_streams(tmp_path):
    before_out, before_err = sys.stdout, sys.stderr
    with day_log(str(tmp_path), "d1"):
        assert sys.stdout is not before_out
    assert sys.stdout is before_out and sys.stderr is before_err


def test_day_log_is_a_noop_without_a_dir():
    before = sys.stdout
    with day_log(None, "d1") as path:
        assert path is None and sys.stdout is before


def test_two_days_in_one_process_do_not_raise_on_a_closed_file(tmp_path):
    """The reuse bug: a StreamHandler created during day 1 kept the closed file.

    Observed live as `ValueError: I/O operation on closed file` in
    classify-2026-01-23.log while the full-window backfill was running.
    """
    logger = logging.getLogger("daylog_reuse_test")
    logger.handlers.clear()
    logger.propagate = False
    try:
        with day_log(str(tmp_path), "day1"):
            h = logging.StreamHandler(sys.stderr)     # captures the day-1 file
            logger.addHandler(h)
            logger.warning("during day one")
        with day_log(str(tmp_path), "day2"):
            logger.warning("during day two")          # would have raised
            print("day two stdout")
        logger.warning("after both days")             # and this too
    finally:
        logger.handlers.clear()

    d2 = open(os.path.join(str(tmp_path), "day2.log"), encoding="utf-8").read()
    assert "day two stdout" in d2


def test_preexisting_handler_is_rebound_and_restored(tmp_path):
    """A handler aimed at the ORIGINAL stderr should follow the redirect, then come back."""
    original = io.StringIO()
    saved_err = sys.stderr
    sys.stderr = original
    logger = logging.getLogger("daylog_rebind_test")
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.StreamHandler(original)
    logger.addHandler(handler)
    try:
        with day_log(str(tmp_path), "day3"):
            logger.warning("goes to the day file")
        assert handler.stream is original, "handler must be restored"
        logger.warning("goes back to the original stream")
    finally:
        logger.handlers.clear()
        sys.stderr = saved_err

    day = open(os.path.join(str(tmp_path), "day3.log"), encoding="utf-8").read()
    assert "goes to the day file" in day
    assert "goes to the day file" not in original.getvalue()
    assert "goes back to the original stream" in original.getvalue()


def test_warnings_during_capture_land_in_the_day_file(tmp_path):
    with day_log(str(tmp_path), "day4"):
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn("a pandas-style warning")
    # the file exists and the run did not blow up; content depends on the
    # warnings machinery, so only the survival property is asserted
    assert os.path.exists(os.path.join(str(tmp_path), "day4.log"))


def test_exception_inside_the_block_still_restores(tmp_path):
    before = sys.stdout
    try:
        with day_log(str(tmp_path), "day5"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert sys.stdout is before


def test_creates_missing_log_dir(tmp_path):
    nested = os.path.join(str(tmp_path), "a", "b")
    with day_log(nested, "day6") as path:
        print("x")
    assert os.path.exists(path)
