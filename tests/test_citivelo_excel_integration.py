r"""Live tests against a real, human-logged-in Citi Velocity Excel add-in.

Every test here is ``integration``-marked and **self-skips** when no authenticated
add-in is reachable, mirroring ``tests/test_citi_velocity_intraday_curve.py``. The
fast gate (``-m "not slow and not network and not db"``) still collects them, so the
skip has to be a runtime probe rather than a marker alone.

Read this before running them
-----------------------------
These tests drive **the user's own Excel process**. There is no headless path: the
Velocity login is gated on ``CustomRibbon.onLoad`` -> portal session -> entitlements,
and spawned instances never register the UDFs. Two ``AccessViolation`` triggers were
observed during design, both of which take the whole Excel process down along with
any unsaved work:

1. writing a block that overlaps a live ``CvFunction_*`` region;
2. clearing or deleting a region while the add-in's queued ``ExcessClr``/``Format``/
   ``AutoFit`` actions against it are still outstanding.

The client's write discipline avoids both, and the hermetic suite asserts it. These
tests are deliberately SHORT - a handful of calls - because the risk is not zero and
the value of a long unattended run is low. Do not add a sweep here; put sweeps in a
script that checkpoints, and never ``Stop-Process`` a client mid-call (that wedges
the OLE server for ~15 minutes).

Opt in explicitly::

    set CITIVELO_EXCEL_LIVE_TESTS=1
    conda run -n stir python -m pytest tests/test_citivelo_excel_integration.py -m integration -q
"""

from __future__ import annotations

import datetime
import os

import pandas as pd
import pytest

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.errors import CitiVelocityError

pytestmark = pytest.mark.integration

#: Known-good tags, verified live on 2026-08-04 against the real add-in.
CONTROL_TAGS = (
    "RATES.OIS.USD_SOFR.PAR.10Y",
    "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y",
)


def _live_client():
    """Connect, or skip with the reason.

    The opt-in env var is required on top of a reachable add-in: attaching to a
    colleague's live Excel because a test happened to be collected is not
    something that should ever happen by default.
    """
    if os.environ.get("CITIVELO_EXCEL_LIVE_TESTS", "").strip() not in {"1", "true", "TRUE"}:
        pytest.skip(
            "Live Citi Velocity tests are opt-in: set CITIVELO_EXCEL_LIVE_TESTS=1. "
            "They drive the user's own Excel process."
        )
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        pytest.skip("pywin32 is not installed; the COM bridge cannot run.")

    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError, ExcelNotRunningError

    try:
        return CitiVelocityExcelClient.connect(attempts=1, readiness_timeout=60.0)
    except AddInNotSignedInError as exc:
        pytest.skip(f"Excel is running but not signed in to Velocity: {exc}")
    except ExcelNotRunningError as exc:
        pytest.skip(f"No usable Excel with the Citi Velocity add-in: {exc}")


@pytest.fixture()
def live_client():
    client = _live_client()
    try:
        yield client
    finally:
        client.close()


# ------------------------------------------------------------------ #
#                        the transport itself                        #
# ------------------------------------------------------------------ #


def test_control_tags_serve_data(live_client):
    """The controls must pass before any other live assertion is trusted.

    Two validators in the design session produced confident wrong numbers
    (``0/1673`` valid, and "13% fetchable"); running known-good tags first is what
    caught them. A failure here means the run is unusable, not that the data is bad.
    """
    verdicts = live_client.validate(list(CONTROL_TAGS))
    assert verdicts == {tag: "valid" for tag in CONTROL_TAGS}, verdicts


def test_fetch_returns_a_real_daily_history(live_client):
    series = live_client.fetch_timeseries(list(CONTROL_TAGS), "DAILY", period="1M")
    assert set(series) == set(CONTROL_TAGS)
    par = series["RATES.OIS.USD_SOFR.PAR.10Y"]
    assert len(par) >= 10
    assert par.index.is_monotonic_increasing
    assert 0.0 < float(par.iloc[-1]) < 20.0, "a USD 10y par rate should be a plausible percent"


def test_many_tags_batch_into_one_call(live_client):
    """The 44-tenor par grid is one ``CVTSHIST``, as the add-in's own export is."""
    grid = T.ois_par_grid("USD_SOFR")
    before = len(live_client.formulas if hasattr(live_client, "formulas") else [])
    calls_before = live_client.calls
    series = live_client.fetch_timeseries(grid, "DAILY", period="1W")
    assert live_client.calls - calls_before == 1
    assert len(series) >= 30, f"only {len(series)}/44 tenors served: {live_client.last_failures()}"
    _ = before


def test_a_bad_tag_costs_only_its_own_column(live_client):
    """``CVTSHIST`` degrades per column; a typo must not lose the batch."""
    bad = "RATES.OIS.USD_SOFR.PAR.999Y"
    series = live_client.fetch_timeseries(
        [CONTROL_TAGS[0], bad], "DAILY", period="1W"
    )
    assert CONTROL_TAGS[0] in series
    assert bad not in series
    assert bad in live_client.last_failures()


def test_intraday_is_one_minute_at_the_finest(live_client):
    """``MI01`` works; ``SE10`` is a streaming granularity and is rejected outright."""
    from MDP.CitiVelocityExcel.errors import FrequencyError

    series = live_client.fetch_timeseries(
        ["RATES.TSY.TSY.OTR.10Y.YIELD"], "MI01", period="1D"
    )
    if series:
        stamps = next(iter(series.values())).index
        assert stamps.is_monotonic_increasing
        if len(stamps) > 2:
            deltas = pd.Series(stamps).diff().dropna()
            assert deltas.min() >= pd.Timedelta(minutes=1)

    with pytest.raises(FrequencyError):
        live_client.fetch_timeseries(["RATES.TSY.TSY.OTR.10Y.YIELD"], "SE10")


def test_metadata_reports_history_bounds(live_client):
    rows = live_client.metadata([CONTROL_TAGS[0]])
    row = rows[CONTROL_TAGS[0]]
    assert row.ok
    assert row.history_start is not None
    assert row.history_start < datetime.datetime.now()


def test_swap_spread_serves_where_cvmetadata_says_it_does_not(live_client):
    """The reason validation goes through ``CVTSHIST``, not ``CVMETADATA``.

    ``CVMETADATA`` reports ZERO valid tenors for ``RATES.OIS.USD_SOFR.SWAP_SPREAD``
    - it hard-fails to ``#VALUE!`` on exactly the liquid ones - while ``CVTSHIST``
    serves all eleven. Trusting it would silently drop a whole family.
    """
    tenors = T.SWAP_SPREAD_LIQUID_TENORS
    spread_tags = [T.ois_swap_spread("USD_SOFR", t) for t in tenors]
    verdicts = live_client.validate(spread_tags)
    served = [t for t, v in verdicts.items() if v == "valid"]
    assert len(served) >= 8, f"only {len(served)}/{len(tenors)} SWAP_SPREAD tenors served: {verdicts}"


# ------------------------------------------------------------------ #
#                     end to end through the MDP                     #
# ------------------------------------------------------------------ #


def test_curve_builds_and_reprices_from_live_quotes(live_client, tmp_path):
    """A real Citi par grid, stripped locally, must reprice its own quotes.

    This is the only assertion in the suite that ties the analytics to live data:
    everything else in the hermetic suite is self-consistency on synthetic grids.
    """
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve, par_reprice_errors_bp
    from MDP.CitiVelocityExcel.mdp import CitiVelocityMDP
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    quotes = CitiVeloQuotes(client=live_client, cache=CitiVeloTagCache(base_dir=tmp_path))
    mdp = CitiVelocityMDP(quotes=quotes)
    pricer = mdp.get_pricer({"timestamp": "live", "citi_index": "USD_SOFR"})

    grid = pricer.par_grid("USD_SOFR")
    assert len(grid) >= 20, f"only {len(grid)} tenors served"

    rlc = build_rl_ois_curve(
        par_rates=grid, ref_date=pricer.reference_date(), citi_index="USD_SOFR"
    )
    errors = par_reprice_errors_bp(rlc)
    assert float(errors.abs().max()) < 0.05, f"worst reprice error {errors.abs().max():.4f} bp"


def test_fast_path_matches_repricing_on_live_data(live_client, tmp_path):
    """The equivalence claim, checked against real quotes rather than a fixture."""
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.mdp import CitiVelocityMDP
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
    from Query.CitiVelocity import CitiVeloQuery, CitiVeloValue
    from TB.CitiVelocityTB import CitiVelocityTB

    quotes = CitiVeloQuotes(client=live_client, cache=CitiVeloTagCache(base_dir=tmp_path))
    tb = CitiVelocityTB(CitiVelocityMDP(quotes=quotes), show_tqdm=False)

    end = datetime.date.today()
    start = end - datetime.timedelta(days=10)
    out = tb.assert_fast_path_matches(
        start,
        end,
        [CitiVeloQuery(citi_index="USD_SOFR", tenor="10Y")],
        model_value=CitiVeloValue.RL_RATE,
        tol=0.01,
        raise_on_breach=False,
    )
    worst = float(out["diff"].abs().max())
    assert worst < 0.01, f"live fast path vs reprice disagree by {worst:.6g} percent"
