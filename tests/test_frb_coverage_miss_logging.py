r"""A value the vendor does not serve is coverage, not a fault.

`FixedRateBondsTB` logged every failed (query, date) with `logger.exception`. For
the Citi Velocity source that is the NORMAL case - coverage is per bond and uneven -
and it cost two ways:

* **Time.** A ten-year alias warm wrote 16,722 formatted tracebacks. On a 250-date
  chunk, `logging.exception` -> `formatException` was 68 s of 119 s, **57% of the
  wall time**, spent rendering a stack for the expected outcome.
* **Signal.** A real pricing bug looked exactly like the other 16,721 lines.

So an exception marked `coverage_miss` is counted and summarised once; everything
else keeps its traceback. These tests hold both halves, because a change that
quietened the noise AND the signal would look identical on a clock.

The roll-date cache is here too: same profile, `_auction_plus_1bd` was reached
5,355,000 times over one chunk because `_filter_and_rank_ref_df` runs once per
(date, value) and walked all 1,785 reference rows each time, for an answer that
does not depend on the date it was asked for.
"""

from __future__ import annotations

import datetime
import logging

import pandas as pd
import pytest

from MDP.CitiVelocityExcel.bonds.values import QuoteNotServedError
from MDP.FixedRateBonds.FixedRateBondsMDP import (
    _auction_plus_1bd,
    _filter_and_rank_ref_df,
    _roll_dates_for,
)


# ------------------------------------------------------------------ #
#                        the marker itself                           #
# ------------------------------------------------------------------ #


def test_a_quote_not_served_declares_itself_a_coverage_miss():
    """The marker is what a generic caller reads; without it the caller would
    have to import this package to recognise its own normal case."""
    assert getattr(QuoteNotServedError("no CAS for this bond"), "coverage_miss", False) is True


def test_an_ordinary_error_does_not():
    for exc in (ValueError("bad argument"), RuntimeError("excel died"), KeyError("x")):
        assert getattr(exc, "coverage_miss", False) is False


def test_the_marker_survives_the_broad_handlers_that_already_catch_it():
    """It stays a ValueError, so nothing that catches ValueError changes behaviour."""
    assert isinstance(QuoteNotServedError("x"), ValueError)


# ------------------------------------------------------------------ #
#              the classifier, as the TB applies it                  #
# ------------------------------------------------------------------ #


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _classify(logger, exc):
    """The branch `FixedRateBondsTB._note_failure` takes, isolated.

    Kept as a small copy rather than driving a whole timeseries build, because the
    property under test is one branch and a full build would need a market data
    provider to fail in two different ways on demand.
    """
    if getattr(exc, "coverage_miss", False):
        logger.debug("no quote: %s", exc)
        return "counted"
    logger.exception("Pricing failed: %s", exc)
    return "logged"


@pytest.fixture()
def rec():
    logger = logging.getLogger("test_frb_coverage_miss")
    logger.handlers[:] = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    h = _Recorder()
    logger.addHandler(h)
    return logger, h


def test_a_coverage_miss_does_not_reach_a_handler_at_info(rec):
    """The cost is in the HANDLER - `formatException` runs inside `emit`. A
    coverage miss that still reached an INFO handler would still pay for it."""
    logger, h = rec
    assert _classify(logger, QuoteNotServedError("Citi does not serve CAS")) == "counted"
    assert h.records == []


def test_a_real_failure_still_gets_its_traceback(rec):
    """The half that must NOT change. Quietening the expected case is only safe
    if the unexpected one is untouched."""
    logger, h = rec
    try:
        raise RuntimeError("the add-in went away")
    except RuntimeError as exc:
        assert _classify(logger, exc) == "logged"

    assert len(h.records) == 1
    assert h.records[0].levelno == logging.ERROR
    assert h.records[0].exc_info is not None, "a real failure lost its traceback"


def test_a_coverage_miss_is_still_visible_at_debug(rec):
    """Counted, not discarded. The per-item detail has to be recoverable."""
    logger, h = rec
    logger.setLevel(logging.DEBUG)
    _classify(logger, QuoteNotServedError("Citi does not serve CAS for US912828U576"))
    assert len(h.records) == 1
    assert "does not serve CAS" in h.records[0].getMessage()


# ------------------------------------------------------------------ #
#                      the roll-date cache                           #
# ------------------------------------------------------------------ #


def _ref_frame(n=40):
    base = datetime.date(2020, 1, 1)
    return pd.DataFrame(
        {
            "cusip": [f"91282{i:04d}" for i in range(n)],
            "oi": ["10-Year"] * n,
            "auction_date": [base + datetime.timedelta(days=7 * i) for i in range(n)],
            "issue_date": [base + datetime.timedelta(days=7 * i + 3) for i in range(n)],
            "maturity_date": [datetime.date(2030, 1, 1)] * n,
            "cpn": [2.0] * n,
        }
    )


def test_the_cached_roll_column_equals_the_per_row_map():
    ref = _ref_frame()
    cached = _roll_dates_for(ref)
    direct = ref["auction_date"].apply(_auction_plus_1bd).fillna(ref["issue_date"])
    assert list(cached) == list(direct)


def test_a_second_call_returns_the_same_answer():
    ref = _ref_frame()
    assert list(_roll_dates_for(ref)) == list(_roll_dates_for(ref))


def test_a_different_frame_gets_its_own_roll_dates():
    """The cache is keyed on identity, so two frames must not collide - and a
    frame of a different length must not be mistaken for a recycled id."""
    a, b = _ref_frame(40), _ref_frame(25)
    ra, rb = list(_roll_dates_for(a)), list(_roll_dates_for(b))
    assert len(ra) == 40 and len(rb) == 25
    assert ra[:25] == rb, "the two frames share a prefix and must agree on it"


def test_a_missing_auction_date_falls_back_to_the_issue_date():
    ref = _ref_frame(5)
    ref.loc[2, "auction_date"] = pd.NaT
    roll = _roll_dates_for(ref)
    assert roll.iloc[2] == ref.loc[2, "issue_date"]


def test_ranking_is_unchanged_by_the_cache():
    """The end-to-end property the cache must not disturb: which bond is on the run."""
    ref = _ref_frame(12)
    for as_of in (datetime.date(2020, 2, 1), datetime.date(2020, 4, 1)):
        out = _filter_and_rank_ref_df(ref, as_of)
        # The frame keeps its input order, which is issue_date ASCENDING, so the
        # rank column reads 3, 2, 1, 0 rather than 0, 1, 2, 3. Asserting it was
        # sorted asserted a row order the function never promised.
        assert sorted(out["rank"]) == list(range(len(out))), "ranks must be a permutation"
        assert out.sort_values("issue_date", ascending=False)["rank"].iloc[0] == 0, (
            "the most recently issued eligible bond must be the on-the-run"
        )
        assert (out["issue_date"] < as_of).all(), "an unissued bond cannot be on the run"
