r"""The live harvest probe, driven entirely against the hermetic Excel fake.

The probe in ``MDP/CitiVelocityExcel/harvest/harvest_curve_modes.py`` drives the
USER'S OWN signed-in Excel. Two of the three known ways to kill that process are
write-discipline mistakes, and the third is losing patience with a call that has
not settled - so every line of it is exercised here first, against
:class:`~MDP.CitiVelocityExcel.testing.FakeExcelApp`, which **raises** on the
overlapping-region trigger instead of silently taking a process down.

What this can and cannot prove
------------------------------
It proves the probe's mechanics: that it writes well-spaced formulas, parses what
comes back, persists into the cache before returning, and survives a tag that
serves nothing. It CANNOT prove anything about the wire - the fake serves data
this repo invented, and in particular its ``CVSNAP`` implements as-of semantics
because that is a *guess encoded in the fake*, not a measurement. That is exactly
what the live run is for.
"""

from __future__ import annotations

import datetime
import json

import pandas as pd
import pytest

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.CitiVelocityExcel.harvest import harvest_curve_modes as H

pytestmark = pytest.mark.filterwarnings("ignore")

# Two currencies is enough to exercise every branch and keeps the fake's pure
# python block building off the critical path of the fast gate.
PROBE_INDICES = ("USD_SOFR", "GBP_SONIA")


def _minute_index(days: int = 6, step_minutes: int = 30) -> pd.DatetimeIndex:
    """Business-day session stamps, coarse enough to keep the fake quick."""
    end = pd.Timestamp(datetime.date.today()) - pd.Timedelta(days=1)
    stamps = []
    day = end - pd.Timedelta(days=days)
    while day <= end:
        if day.weekday() < 5:
            t = day + pd.Timedelta(hours=8)
            while t <= day + pd.Timedelta(hours=17):
                stamps.append(t)
                t += pd.Timedelta(minutes=step_minutes)
        day += pd.Timedelta(days=1)
    return pd.DatetimeIndex(stamps)


@pytest.fixture()
def served() -> FakeVelocityData:
    idx = _minute_index()
    series = {}
    for n, citi_index in enumerate(PROBE_INDICES):
        for k, tenor in enumerate(_axis(citi_index)):
            tag = f"RATES.OIS.{citi_index}.PAR.{tenor}"
            base = 3.5 + 0.02 * k + 0.1 * n
            series[tag] = pd.Series(base + 0.001 * pd.Series(range(len(idx)), index=idx), index=idx)
        for expiry, tenor in H.FWD_POINTS:
            tag = f"RATES.OIS.{citi_index}.FWD.{expiry}.{tenor}"
            series[tag] = pd.Series(4.0 + 0.1 * n, index=idx)
    series["RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"] = pd.Series(80.95, index=idx)
    return FakeVelocityData(series=series)


def _axis(citi_index: str):
    return H._par_axis(citi_index)


@pytest.fixture()
def rig(served, tmp_path):
    app = FakeExcelApp(served, pending_reads=2)
    client = CitiVelocityExcelClient(app=app, poll_interval=0.0, drain_seconds=0.0)
    cache = CitiVeloTagCache(base_dir=tmp_path / "cache")
    ev = H.Evidence(tmp_path / "evidence", "test")
    return app, client, cache, ev


# ------------------------------------------------------------------ #
#                          the write discipline                      #
# ------------------------------------------------------------------ #


def test_no_stage_ever_overlaps_a_live_region(rig):
    """The fake raises on the AccessViolation trigger; a clean run means none fired."""
    app, client, cache, ev = rig
    H.stage_a(client, cache, ev)
    H.stage_d(client, cache, ev)
    H.stage_b(client, cache, ev, period="1W", only=PROBE_INDICES)
    H.stage_c(client, cache, ev, only=PROBE_INDICES)
    H.stage_e(client, cache, ev)
    H.stage_f(client, cache, ev, only=PROBE_INDICES)

    # Every block the fake accepted is non-overlapping by construction (it raises
    # otherwise), so assert the property the client is actually responsible for:
    # anchors strictly increase and never sit inside the previous block.
    by_sheet: dict[str, list[tuple[int, int, int, int]]] = {}
    for name, top, left, height, width in app.blocks:
        by_sheet.setdefault(name, []).append((top, left, height, width))
    for name, blocks in by_sheet.items():
        blocks.sort()
        for (top, _l, height, _w), (next_top, *_rest) in zip(blocks, blocks[1:]):
            assert next_top > top + height, f"{name}: block at {top} (+{height}) collides with {next_top}"


def test_anchor_is_column_b_not_a(rig):
    """The add-in writes one column LEFT of the anchor; column A would go off-sheet."""
    _app, client, cache, ev = rig
    H.stage_d(client, cache, ev)
    assert client._app.anchors(), "no formulas were written"
    assert all(a[0] == "B" for a in client._app.anchors()), client._app.anchors()


# ------------------------------------------------------------------ #
#                        banking and reporting                       #
# ------------------------------------------------------------------ #


def test_every_served_series_is_persisted_before_the_call_returns(rig):
    """A series fetched but not banked has to be re-fetched from an Excel that may be gone."""
    _app, client, cache, ev = rig
    tags = [f"RATES.OIS.USD_SOFR.PAR.{t}" for t in _axis("USD_SOFR")[:6]]
    out = H.fetch_and_bank(client, cache, ev, tags, "DAILY", label="unit", period="1W")
    assert out
    for tag in out:
        cached = cache.read(tag, "DAILY")
        assert cached is not None and len(cached) == len(out[tag])


def test_grid_report_counts_complete_rows_not_just_rows(rig, served):
    """A grid can serve 44 tenors and still never line them up on one timestamp."""
    _app, client, cache, ev = rig
    axis = _axis("USD_SOFR")
    # Punch a hole in one tenor so the frame has rows that are not complete.
    holed = f"RATES.OIS.USD_SOFR.PAR.{axis[3]}"
    s = served.series[holed]
    served.series[holed] = s.iloc[: len(s) // 2]

    tags = [f"RATES.OIS.USD_SOFR.PAR.{t}" for t in axis[:8]]
    out = H.fetch_and_bank(client, cache, ev, tags, "DAILY", label="unit", period="2W")
    frame = pd.concat(out, axis=1).sort_index()
    rep = H._grid_report("USD_SOFR", tags, out, frame)
    assert rep["n_rows"] > rep["n_complete_rows"] > 0
    assert set(rep["last_row"]) <= {t.rsplit(".", 1)[-1] for t in tags}


def test_a_tag_that_serves_nothing_is_reported_not_dropped(rig, served):
    """Per-column degradation: a bad tag costs its own column and nothing else."""
    _app, client, cache, ev = rig
    axis = _axis("USD_SOFR")
    bad = f"RATES.OIS.USD_SOFR.PAR.{axis[2]}"
    served.bad_tags.add(bad)
    tags = [f"RATES.OIS.USD_SOFR.PAR.{t}" for t in axis[:6]]
    out = H.fetch_and_bank(client, cache, ev, tags, "DAILY", label="unit", period="1W")
    assert bad not in out
    assert len(out) == len(tags) - 1
    record = [r for r in ev.records if r["event"] == "cvtshist"][-1]
    assert record["n_failed"] == 1
    assert bad in record["failures"]


def test_evidence_is_written_per_call_not_at_the_end(rig, tmp_path):
    """The log has to survive the process losing Excel mid-stage."""
    _app, client, cache, ev = rig
    H.stage_d(client, cache, ev)
    lines = [json.loads(l) for l in ev.path.read_text(encoding="utf-8").splitlines()]
    assert lines, "nothing was written to the evidence log"
    assert any(r["event"] == "cvtshist" for r in lines)
    assert all("wall_utc" in r and "wall_local" in r for r in lines)


def test_stage_summaries_are_rewritten_after_every_currency(rig, tmp_path):
    """A currency-by-currency rewrite is what makes a partial run useful."""
    _app, client, cache, ev = rig
    H.stage_b(client, cache, ev, period="1W", only=PROBE_INDICES)
    payload = json.loads((ev.dir / "stage_b_eod.json").read_text(encoding="utf-8"))
    assert set(payload) == set(PROBE_INDICES)
    for index, rep in payload.items():
        assert rep["n_served"] == rep["n_tags"], index


def test_usd_is_probed_first(rig):
    """A pipeline bug should surface on call one, not after nineteen wasted calls."""
    assert H._usd_first(T.OIS_INDICES)[0] == "USD_SOFR"
    assert sorted(H._usd_first(T.OIS_INDICES)) == sorted(T.OIS_INDICES)


def test_evaluate_formula_goes_through_the_disciplined_write_path(rig):
    """CVNOW has no typed wrapper; it must not get a second, unspaced writer."""
    app, client, cache, ev = rig
    value, rows = client.evaluate_formula("=CVNOW()")
    assert rows or value is not None
    # One anchor per call, in column B, spaced by the client's own gap rule.
    assert app.anchors() == ["B31"]


def test_last_weekday_never_returns_a_weekend():
    for offset in range(0, 40):
        day = H._last_weekday(datetime.date(2026, 8, 7) - datetime.timedelta(days=offset))
        assert day.weekday() < 5
