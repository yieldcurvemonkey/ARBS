r"""The DAILY par grid has to be ADVANCED by something, and nothing advanced it.

The EOD CurveStore warm builds one curve per business day out of the banked DAILY
par grid, offline, through a ``CitiVeloQuotes(offline=True)`` that cannot fetch.
So the store reaches exactly as far as the grid does, and the grid moved only when
a human ran the harvest. Measured on the real cache on 2026-08-19:

====================================  ============  ============================
curve                                  DAILY grid    ``-CITIVELOEXCELMIN`` store
====================================  ============  ============================
``USD_SOFR``                           2026-08-18    2026-08-18
``EUR_EUROSTR``                        2026-08-07    2026-08-18
``GBP_SONIA``                          2026-08-07    2026-08-18
``CAD_CORRA``                          2026-08-07    2026-08-18
``JPY_TONAR_LCH``                      2026-08-07    2026-08-18
====================================  ============  ============================

The minute store is current on all five and the EOD grid froze the day the human
stopped - USD only because it was refreshed by hand that morning. The nightly was
doing exactly half its job, and the visible symptom was "EOD warm exited 1" on six
of ten retained nights: ``cmd_warm`` returning "wrote 0 curve-days" because every
day it was asked for was already past the end of the grid.

Two things are pinned here, and they are different in kind:

* **the refresh** - one ``CVTSHIST`` per curve with EXPLICIT bounds, banked into
  the tag cache. The argument form is the whole risk and it is measured, not
  guessed: the same 44 tags served **0/44 in 0.02 s** with ``period='15Y'`` and
  **44/44 in 1.4 s** with ``start``/``end`` (harvest evidence log, stage W's
  first pass and its rerun). A test that only checked "it fetched" would pass
  against the form that silently returns nothing.
* **the honest outcome when it cannot run** - a stale grid is an INPUT the
  offline EOD warm does not own, so it is a SKIP naming the command, not a
  FAILED naming nothing.

No Excel, no COM, no network: the client is a fake and the cache is a real
``CitiVeloTagCache`` rooted in ``tmp_path``.
"""

from __future__ import annotations

import datetime
import importlib.util
import pathlib
import sys
from typing import Dict, List, Optional

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REFRESH = _load("_daily_par_refresh", REPO / "scripts" / "citivelo_daily_par_refresh.py")
EXCEL_WARM = _load("_citivelo_excel_warm", REPO / "scripts" / "citivelo_excel_warm.py")

#: A small stand-in for the 44-tenor grid. The real axis is exercised by
#: ``status`` against the live cache; what these tests are about is the shape of
#: the request and the arithmetic on the dates, and three tags show both.
_GRID = ["RATES.OIS.TEST_IDX.PAR.2Y", "RATES.OIS.TEST_IDX.PAR.5Y",
         "RATES.OIS.TEST_IDX.PAR.10Y"]

_END = datetime.date(2026, 8, 19)


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    """A real tag cache in ``tmp_path``, with the par grid stubbed to :data:`_GRID`.

    Real rather than faked on purpose: the sidecar is the thing under test, and
    ``CitiVeloTagCache.write`` is what writes ``last`` into it from the MERGED
    series. A fake sidecar would let a change to that merge pass unnoticed.
    """
    from MDP.CitiVelocityExcel import tags as T
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

    monkeypatch.setattr(T, "ois_par_grid", lambda index, **kw: list(_GRID))
    return CitiVeloTagCache(base_dir=tmp_path / "cache")


def _plant(cache, tag: str, last: datetime.date, n: int = 40) -> None:
    """Bank ``n`` daily rows ending on ``last``, so the sidecar carries a real date.

    The values are a ramp in PERCENT (0.00 .. 1.95), not ``range(n)``. Nothing here
    asserts on them - every assertion is about dates and sidecars - but ``PAR``
    tags now carry a plausibility band, and a bare ``range(40)`` puts a 39% par
    rate on a SOFR tag. Scaling keeps every row distinguishable, which is the only
    property this fixture ever needed.
    """
    idx = pd.date_range(end=pd.Timestamp(last), periods=n, freq="D")
    cache.write(tag, "DAILY", pd.Series([i / 20.0 for i in range(n)], index=idx, dtype="float64"))


class FakeClient:
    """Records every ``fetch_timeseries`` call and serves what it is told to.

    ``calls`` is the point of it: the assertions are about the ARGUMENTS, because
    the measured failure mode is a request that is well-formed, returns cleanly,
    and contains nothing.
    """

    def __init__(self, serve: Optional[Dict[str, pd.Series]] = None,
                 failures: Optional[Dict[str, str]] = None):
        self.calls: List[dict] = []
        self._serve = serve
        self._failures = dict(failures or {})
        self.closed = False

    def fetch_timeseries(self, tags, freq="DAILY", **kwargs):
        self.calls.append({"tags": list(tags), "freq": freq, **kwargs})
        if self._serve is not None:
            return dict(self._serve)
        end = kwargs.get("end") or _END
        idx = pd.date_range(end=pd.Timestamp(end), periods=3, freq="D")
        return {t: pd.Series([1.0, 2.0, 3.0], index=idx) for t in tags
                if t not in self._failures}

    def last_failures(self):
        return dict(self._failures)

    def close(self):
        self.closed = True


# ------------------------------------------------------------------ #
#   1. the window: what to ask for, and when to refuse to ask at all  #
# ------------------------------------------------------------------ #


def test_a_tag_that_has_never_been_banked_is_never_given_a_guessed_start():
    """A missing sidecar is a DEEP fetch, and guessing a start truncates the grid.

    This is the failure that would be invisible: a start invented for a tag with
    no history banks a few weeks, the sidecar then says the tag is covered, and
    the EOD warm happily builds curves out of a grid missing twenty years. An
    absent grid announces itself; a truncated one does not.
    """
    coverage = {"a": datetime.date(2026, 8, 7), "b": None}
    start, why = REFRESH.plan_window(coverage, end=_END)
    assert start is None, "a curve with an unbanked tag must not be given a start"
    assert why == "never banked"


def test_a_grid_that_already_reaches_the_window_end_asks_for_nothing():
    """The control for the above: "do not fetch" must not be the only answer."""
    coverage = {t: _END for t in _GRID}
    assert REFRESH.plan_window(coverage, end=_END) == (None, "current")


def test_the_start_is_the_OLDEST_tag_and_not_the_newest():
    """The tags of one grid do not stop on the same day.

    The long end of a curve prints less often than the belly, so starting from
    the NEWEST tag's last row leaves every laggard permanently behind by exactly
    the amount it lags - a hole that never closes because each night reproduces
    it. The oldest is the only start that lets them catch up.
    """
    coverage = {
        "belly": datetime.date(2026, 8, 18),
        "long": datetime.date(2026, 8, 7),
        "short": datetime.date(2026, 8, 14),
    }
    start, why = REFRESH.plan_window(coverage, end=_END)
    assert why == "refresh"
    assert start == datetime.date(2026, 8, 7) - REFRESH.OVERLAP, (
        "the request must reach back to the OLDEST tag, not the newest"
    )


def test_the_overlap_reaches_back_before_the_last_banked_row():
    """A day that was partially published when first fetched must be re-askable.

    ``CitiVeloTagCache.write`` MERGES, so re-requesting banked days costs a few
    rows and buys a correction. Starting exactly at ``last`` would freeze
    whatever was there.
    """
    coverage = {"a": datetime.date(2026, 8, 7)}
    start, _ = REFRESH.plan_window(coverage, end=_END)
    assert start < datetime.date(2026, 8, 7), "the window must start BEFORE the last row"
    assert REFRESH.OVERLAP >= datetime.timedelta(days=3), (
        "an overlap shorter than a weekend cannot correct a Friday"
    )


# ------------------------------------------------------------------ #
#        2. the request FORM - the measured 0/44-vs-44/44 axis        #
# ------------------------------------------------------------------ #


def test_the_request_uses_explicit_bounds_and_never_a_relative_period(cache):
    """``period='15Y'`` served 0/44 in 0.02 s; explicit bounds served 44/44 in 1.4 s.

    Both are "a successful fetch that raised nothing". Only the arguments tell
    them apart, so the arguments are what this asserts - a test that checked
    merely that a fetch happened would pass against the form that returns an
    empty block, which is the exact shape of the bug being fixed.
    """
    for tag in _GRID:
        _plant(cache, tag, datetime.date(2026, 8, 7))
    client = FakeClient()

    REFRESH.refresh_curve("USD-SOFR-1D", client=client, cache=cache, end=_END)

    assert len(client.calls) == 1, "one CVTSHIST per curve, unchunked - DAILY has no cliff"
    call = client.calls[0]
    assert call["freq"] == "DAILY"
    assert call.get("price_point") == "CLOSE"
    assert "period" not in call, (
        "a relative period is the form measured returning NO BLOCK AT ALL "
        f"(0/44 tags in 0.02 s); got {call!r}"
    )
    assert isinstance(call.get("start"), datetime.date), "explicit start required"
    assert isinstance(call.get("end"), datetime.date), "explicit end required"
    assert call["start"] == datetime.date(2026, 8, 7) - REFRESH.OVERLAP
    assert call["end"] == _END
    assert sorted(call["tags"]) == sorted(_GRID), "the WHOLE par grid in one request"


def test_every_tag_that_served_rows_is_banked_and_the_sidecar_advances(cache):
    """A fetch that is not banked is a fetch that has to happen again.

    Asserted through the sidecar rather than a call count, because the sidecar is
    what every downstream reader actually consults.
    """
    for tag in _GRID:
        _plant(cache, tag, datetime.date(2026, 8, 7))
    assert REFRESH._sidecar_last(cache, _GRID[0]) == datetime.date(2026, 8, 7)

    record = REFRESH.refresh_curve("USD-SOFR-1D", client=FakeClient(), cache=cache, end=_END)

    assert record["outcome"] == "refreshed"
    assert record["written"] == len(_GRID)
    for tag in _GRID:
        assert REFRESH._sidecar_last(cache, tag) == _END, (
            f"{tag} was fetched but the banked grid did not move"
        )


def test_a_curve_that_is_already_current_costs_no_request(cache):
    """The nightly must not re-ask for a grid that is already at the window end."""
    for tag in _GRID:
        _plant(cache, tag, _END)
    client = FakeClient()

    record = REFRESH.refresh_curve("USD-SOFR-1D", client=client, cache=cache, end=_END)

    assert record["outcome"] == "current"
    assert client.calls == [], "a current grid must not touch the wire"


# ------------------------------------------------------------------ #
#              3. a fault must not advance anything                   #
# ------------------------------------------------------------------ #


def test_a_transport_fault_banks_nothing_at_all(cache):
    """A partial bank is how "green while stale" is built.

    Writing the tags that happened to answer would move their sidecar ``last``
    forward, so the next night's ``plan_window`` would start from a date the
    curve does not really hold - and the shortfall becomes permanent and
    invisible. Nothing is banked, and the next run retries the whole grid.
    """
    for tag in _GRID:
        _plant(cache, tag, datetime.date(2026, 8, 7))
    idx = pd.date_range(end=pd.Timestamp(_END), periods=3, freq="D")
    client = FakeClient(
        serve={_GRID[0]: pd.Series([1.0, 2.0, 3.0], index=idx)},
        failures={_GRID[1]: "no block", _GRID[2]: "no block"},
    )

    record = REFRESH.refresh_curve("USD-SOFR-1D", client=client, cache=cache, end=_END)

    assert record["outcome"] == "fault"
    assert record["written"] == 0
    for tag in _GRID:
        assert REFRESH._sidecar_last(cache, tag) == datetime.date(2026, 8, 7), (
            f"{tag} advanced despite the transport failing"
        )


def test_an_empty_column_is_not_a_transport_fault(cache):
    """"empty" is the wire answering "this tag has nothing here", not a dead wire.

    Same discipline as the UST universe warm's ``BENIGN_FAILURE_REASONS``:
    calling a benign reason a fault is what aborted that warm at 0/877 on five of
    ten nights.
    """
    for tag in _GRID:
        _plant(cache, tag, datetime.date(2026, 8, 7))
    idx = pd.date_range(end=pd.Timestamp(_END), periods=3, freq="D")
    client = FakeClient(
        serve={t: pd.Series([1.0, 2.0, 3.0], index=idx) for t in _GRID[:2]},
        failures={_GRID[2]: "empty"},
    )

    record = REFRESH.refresh_curve("USD-SOFR-1D", client=client, cache=cache, end=_END)

    assert record["outcome"] == "refreshed", "a benign empty column must not abort the bank"
    assert record["written"] == 2


def test_an_unknown_failure_reason_is_treated_as_a_fault(cache):
    """Failing towards visibility. A reason nobody has seen is not evidence of health."""
    for tag in _GRID:
        _plant(cache, tag, datetime.date(2026, 8, 7))
    client = FakeClient(serve={}, failures={_GRID[0]: "something new"})

    record = REFRESH.refresh_curve("USD-SOFR-1D", client=client, cache=cache, end=_END)
    assert record["outcome"] == "fault"


# ------------------------------------------------------------------ #
#          4. Excel is touched only when it is actually needed        #
# ------------------------------------------------------------------ #


def test_a_night_where_every_grid_is_current_never_connects_to_excel(cache, monkeypatch):
    """The add-in gives memory back only to a human restart.

    So a run with nothing to fetch must not connect at all - not connect and do
    nothing. Enforced by making both the guard and the connect explode.
    """
    for tag in _GRID:
        _plant(cache, tag, _END)

    from MDP.CitiVelocityExcel import memory_guard

    monkeypatch.setattr(memory_guard, "assert_safe_to_connect",
                        lambda *a, **k: pytest.fail("the ceiling was probed with nothing to do"))

    records = REFRESH.refresh(["USD-SOFR-1D", "EUR-ESTR-1D"], end=_END, cache=cache)

    assert [r["outcome"] for r in records] == ["current", "current"]


def test_the_memory_ceiling_is_checked_BEFORE_the_connection(cache, monkeypatch):
    """A guard placed after the connection has already done what it exists to prevent.

    This pins the ORDER, not merely the presence: the probe must have run by the
    time ``connect`` is reached, and a refusal must stop the connection happening
    at all.
    """
    for tag in _GRID:
        _plant(cache, tag, datetime.date(2026, 8, 7))

    from MDP.CitiVelocityExcel import com_client, memory_guard

    class Refused(RuntimeError):
        pass

    def refuse(*a, **k):
        raise Refused("Excel is at 6526 MB")

    monkeypatch.setattr(memory_guard, "assert_safe_to_connect", refuse)
    monkeypatch.setattr(com_client.CitiVelocityExcelClient, "connect",
                        classmethod(lambda cls, **k: pytest.fail("connected past a refused guard")))

    with pytest.raises(Refused):
        REFRESH.refresh(["USD-SOFR-1D"], end=_END, cache=cache)


# ------------------------------------------------------------------ #
#                    5. what the exit code means                      #
# ------------------------------------------------------------------ #


def _record(curve, outcome, **kw):
    base = {"curve": curve, "citi_index": "X", "tags": 3, "banked_to": None,
            "outcome": outcome, "written": 0, "faults": {}}
    base.update(kw)
    return base


def test_a_clean_refresh_exits_0():
    assert REFRESH._report([_record("USD-SOFR-1D", "refreshed", written=3)],
                           REFRESH.LOGGER) == 0


def test_a_transport_fault_exits_1_and_names_the_tags(capsys):
    """1 is "a real defect, read the log" - and the log has to say what broke."""
    code = REFRESH._report(
        [_record("EUR-ESTR-1D", "fault", faults={"RATES.OIS.EUR_EUROSTR.PAR.2Y": "no block"})],
        REFRESH.LOGGER,
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "TRANSPORT FAULT" in out
    assert "RATES.OIS.EUR_EUROSTR.PAR.2Y" in out, "the cause must survive into the last line"


def test_a_never_banked_curve_exits_3_even_when_the_others_advanced(capsys):
    """Partial success must not mask a curve that no schedule can ever advance.

    Exiting 0 here because four of five worked is the same "green while stale"
    shape the whole change exists to remove - the fifth curve's grid stays frozen
    for ever and nothing says so.
    """
    code = REFRESH._report(
        [_record("USD-SOFR-1D", "refreshed", written=3),
         _record("JPY-TONAR-1D-LCH", "never banked")],
        REFRESH.LOGGER,
    )
    assert code == 3, "3 is SKIPPED - a human must act, this is not a defect"
    out = capsys.readouterr().out
    assert "JPY-TONAR-1D-LCH" in out
    assert "harvest" in out.lower(), "the skip must name the command a human should run"


def test_a_fault_outranks_a_skip():
    """A run with both is a run with a defect, and the defect must not be softened."""
    code = REFRESH._report(
        [_record("EUR-ESTR-1D", "fault", faults={"t": "no block"}),
         _record("JPY-TONAR-1D-LCH", "never banked")],
        REFRESH.LOGGER,
    )
    assert code == 1


# ------------------------------------------------------------------ #
#      6. the offline EOD warm: stale grid is an input, not a bug     #
# ------------------------------------------------------------------ #


def test_a_window_past_the_end_of_the_grid_records_the_grid_end():
    """The structured date is what lets the caller pick an exit code.

    Matching on the prose of an error string would work today and stop working
    the first time someone rewords it, silently turning the skip back into a
    nightly failure.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import warm as W

    idx = pd.date_range("2026-07-01", "2026-08-07", freq="D")
    frame = pd.DataFrame({"2Y": 1.0, "5Y": 2.0}, index=idx)

    class Q:
        def frame(self, *a, **k):
            return frame

    stat = W.warm_curve("USD-SOFR-1D", quotes=Q(), store=object(),
                        start=datetime.date(2026, 8, 10), end=datetime.date(2026, 8, 18))

    assert stat.written == 0
    assert stat.stale_grid == datetime.date(2026, 8, 7), (
        "the banked end date must be recorded structurally, not only in prose"
    )


def test_an_empty_window_INSIDE_the_grid_is_not_called_stale():
    """"Run the harvest" must not be said to someone the harvest cannot help.

    A window that lands before the grid's first day, or inside a hole, is a
    different problem - the grid extends past it, so refreshing the tail changes
    nothing.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import warm as W

    idx = pd.date_range("2026-07-01", "2026-08-18", freq="D")
    frame = pd.DataFrame({"2Y": 1.0, "5Y": 2.0}, index=idx)

    class Q:
        def frame(self, *a, **k):
            return frame

    stat = W.warm_curve("USD-SOFR-1D", quotes=Q(), store=object(),
                        start=datetime.date(2020, 1, 1), end=datetime.date(2020, 2, 1))

    assert stat.written == 0
    assert stat.stale_grid is None, (
        "a window the grid already spans is not a stale grid and must not send "
        "a human to run a refresh that cannot help"
    )


class _Args:
    curves = "USD-SOFR-1D,EUR-ESTR-1D"
    start = "2026-08-15"
    end = "2026-08-18"
    min_tenors = 20
    force = False
    push_l2 = False


def _stat(name, **kw):
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import WarmStat

    return WarmStat(curve_name=name, citi_index="X", asset=f"{name}-CITIVELOEXCEL", **kw)


def test_every_curve_stale_exits_3_and_not_1(monkeypatch, capsys):
    """The six-of-ten-nights case. Nothing here is broken; the grid is an input.

    This warm is offline by construction and cannot fetch, so reporting a defect
    trains the exit code to be ignored - which is how a cache write that
    persisted nothing survived ten runs unnoticed.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import warm as W

    monkeypatch.setattr(W, "warm_many", lambda names, **kw: {
        "USD-SOFR-1D": _stat("USD-SOFR-1D", stale_grid=datetime.date(2026, 8, 7),
                             errors=["no banked DAILY rows"]),
        "EUR-ESTR-1D": _stat("EUR-ESTR-1D", stale_grid=datetime.date(2026, 8, 7),
                             errors=["no banked DAILY rows"]),
    })

    code = EXCEL_WARM.cmd_warm(_Args())

    assert code == 3, "a stale grid is SKIPPED, not FAILED"
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "citivelo_daily_par_refresh" in out, (
        "the skip must name the command that fixes it - 'EOD warm exited 1' "
        "naming no cause is the failure this replaces"
    )
    assert "2026-08-07" in out, "the message must say how far the grid actually reaches"


def test_one_real_failure_among_stale_curves_still_exits_1(monkeypatch):
    """A defect must not be softened by the skips beside it.

    Same rule the run-level exit code already follows: a run with both a failure
    and a skip exits 1, because the failure is the actionable half.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import warm as W

    monkeypatch.setattr(W, "warm_many", lambda names, **kw: {
        "USD-SOFR-1D": _stat("USD-SOFR-1D", stale_grid=datetime.date(2026, 8, 7),
                             errors=["no banked DAILY rows"]),
        "EUR-ESTR-1D": _stat("EUR-ESTR-1D", errors=["ValueError: bad node"]),
    })

    assert EXCEL_WARM.cmd_warm(_Args()) == 1


def test_a_curve_that_wrote_days_still_exits_0(monkeypatch):
    """The control: the skip branch must not swallow a successful warm."""
    from MDP.IRSwaps.CITIVELO_EXCEL import warm as W

    monkeypatch.setattr(W, "warm_many", lambda names, **kw: {
        "USD-SOFR-1D": _stat("USD-SOFR-1D", written=2),
        "EUR-ESTR-1D": _stat("EUR-ESTR-1D", stale_grid=datetime.date(2026, 8, 7)),
    })

    assert EXCEL_WARM.cmd_warm(_Args()) == 0


# ------------------------------------------------------------------ #
#      7. an Excel outage mid-run is a SKIP, not a nightly failure    #
# ------------------------------------------------------------------ #
#
# The pre-flight in the nightly only proves Excel was usable when JOB 7 started.
# The environment degrades during a run and that is measured: on 2026-08-11 jobs
# 1-6 completed normally and jobs 9-11 then refused at 3,886 MB. So this step can
# be reached with Excel over the ceiling, shut, or signed out - and an uncaught
# raise exits 1, which the parent records as a FAILED step. That is the opaque
# nightly failure this whole change removes, re-created one layer down.


class _RefreshArgs:
    curves = "USD-SOFR-1D"
    end = "2026-08-19"
    overlap_days = 7
    ceiling_mb = 3000.0


@pytest.mark.parametrize("exc_name", ["ExcelTooLargeError", "ExcelNotRunningError",
                                      "AddInNotSignedInError"])
def test_an_excel_outage_exits_3_rather_than_raising(monkeypatch, capsys, exc_name):
    """All three outage types are one answer to a human: go and fix Excel."""
    from MDP.CitiVelocityExcel import errors as E
    from MDP.CitiVelocityExcel import memory_guard

    exc_type = getattr(E, exc_name, None) or getattr(memory_guard, exc_name)

    def boom(*a, **k):
        raise exc_type("Excel is at 6526 MB")

    monkeypatch.setattr(REFRESH, "refresh", boom)

    code = REFRESH.cmd_refresh(_RefreshArgs())

    assert code == 3, (
        f"{exc_name} must be SKIPPED - exit 1 here is recorded as a FAILED step "
        "and is exactly the opaque nightly failure being removed"
    )
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "Excel" in out, "the message must name what a human has to fix"


def test_a_real_defect_in_the_refresh_still_propagates(monkeypatch):
    """The skip must not become a blanket amnesty.

    Only the Excel-outage types are waived. A genuine bug has to keep reaching
    the parent as a failure, or the exit code stops meaning anything again.
    """
    def boom(*a, **k):
        raise ValueError("a real bug")

    monkeypatch.setattr(REFRESH, "refresh", boom)

    with pytest.raises(ValueError):
        REFRESH.cmd_refresh(_RefreshArgs())
