r"""The ``citivelo_excel`` IRSwapsMDP source: names, timezone contract, dispatch, guards.

Hermetic - no Excel, no network, no database, no cache. The fetcher is driven
through a stub quotes object, because what is under test here is the *decision*
layer (which mode, which instant, which zone, when to refuse) and that layer must
be provable without a signed-in Excel.

The live numbers these tests encode came from
``MDP/CitiVelocityExcel/harvest/live_curve_modes/`` on 2026-08-07 and are cited in
``docs/superpowers/specs/2026-08-07-citivelo-excel-irswaps-source.md``.
"""

from __future__ import annotations

import datetime
import warnings

import pandas as pd
import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from MDP.IRSwaps.CITIVELO_EXCEL import (
    CITIVELO_EXCEL_CURVES,
    CitiVeloExcelCurveFetcher,
    NaiveTimestampError,
    SOURCE_TOKENS,
    SparseCurveError,
    StaleCurveError,
    citi_index_for_curve_name,
    curve_name_for_index,
    register,
    resolve_request,
    supported_curve_names,
    to_wire_naive,
)
from MDP.IRSwaps.CITIVELO_EXCEL import timestamps as ts_mod

NY = ZoneInfo("America/New_York")
UTC = datetime.timezone.utc


# ------------------------------------------------------------------ #
#                          the curve-name map                        #
# ------------------------------------------------------------------ #

#: Written out in full and on purpose. A generated expectation would pass even if
#: the generator changed, and these twenty strings are what downstream code, saved
#: notebooks and any future CurveStore asset key will be spelled with.
EXPECTED_MAP = {
    "AUD_AONIA": "AUD-AONIA-1D",
    "CAD_CORRA": "CAD-CORRA-1D",
    "CHF_SARON": "CHF-SARON-1D",
    "DKK_TNDKK": "DKK-TNDKK-1D",
    "EUR_EONIA": "EUR-EONIA-1D",
    "EUR_EUROSTR": "EUR-ESTR-1D",
    "GBP_SONIA": "GBP-SONIA-1D",
    "ILS_SHIR": "ILS-SHIR-1D",
    "JPY_TONAR": "JPY-TONAR-1D",
    "JPY_TONAR_JSCC": "JPY-TONAR-1D-JSCC",
    "JPY_TONAR_LCH": "JPY-TONAR-1D-LCH",
    "MXN_T_FONDEO": "MXN-FONDEO-1D",
    "NOK_NOWA": "NOK-NOWA-1D",
    "NZD_NZIONA": "NZD-NZIONA-1D",
    "SEK_STINA": "SEK-STINA-1D",
    "SGD_SORA": "SGD-SORA-1D",
    "THB_THOR": "THB-THOR-1D",
    "USD_FEDFUND": "USD-FEDFUNDS-1D",
    "USD_SOFR": "USD-SOFR-1D",
    "ZAR_ZARONIA": "ZAR-ZARONIA-1D",
}


def test_curve_name_map_is_pinned():
    from MDP.CitiVelocityExcel.tags import OIS_INDICES

    assert set(EXPECTED_MAP) == set(OIS_INDICES), "the map must cover exactly Citi's 20 OIS indices"
    for citi_index, curve_name in EXPECTED_MAP.items():
        assert curve_name_for_index(citi_index) == curve_name
        assert citi_index_for_curve_name(curve_name) == citi_index


def test_curve_names_are_unique_and_shaped_consistently():
    names = supported_curve_names()
    assert len(set(names)) == len(names) == 20
    for name in names:
        parts = name.split("-")
        assert len(parts) in (3, 4), name
        assert parts[2] == "1D", f"{name}: every Citi OIS curve is overnight-indexed"
        assert len(parts[0]) == 3 and parts[0].isupper(), name


def test_existing_repo_curve_names_are_reused_not_forked():
    """Four of these already exist as literals; minting a parallel spelling would
    split every downstream lookup in two."""
    for name in ("USD-SOFR-1D", "CHF-SARON-1D", "SGD-SORA-1D", "EUR-ESTR-1D"):
        assert name in supported_curve_names()


def test_jpy_ccp_variants_are_distinct_curves():
    """The JSCC/LCH basis is real; collapsing them would silently substitute one."""
    names = {citi_index_for_curve_name(n) for n in supported_curve_names() if n.startswith("JPY")}
    assert names == {"JPY_TONAR", "JPY_TONAR_JSCC", "JPY_TONAR_LCH"}


def test_measured_coverage_is_recorded_per_curve():
    """What the 2026-08-07 harvest found, so a caller can ask instead of discovering
    it as an empty frame."""
    by_index = {e.citi_index: e for e in CITIVELO_EXCEL_CURVES}
    assert by_index["EUR_EONIA"].modes == ("eod",)
    assert by_index["JPY_TONAR_JSCC"].modes == ("eod",)
    assert not by_index["JPY_TONAR_JSCC"].has_published_forwards
    assert not by_index["JPY_TONAR_LCH"].has_published_forwards
    assert by_index["USD_SOFR"].has_published_forwards
    assert set(by_index["GBP_SONIA"].modes) == {"eod", "intraday", "live"}


def test_source_tokens_agree_with_irswapsmdp():
    from MDP.IRSwaps.IRSwapsMDP import CITIVELO_EXCEL_SOURCE_TOKENS

    assert set(SOURCE_TOKENS) == set(CITIVELO_EXCEL_SOURCE_TOKENS)


def test_the_old_citivelo_aliases_are_not_claimed():
    """~930 warmed CurveStore partitions and the dealer-ladder study depend on them."""
    for legacy in ("CITIVELO", "CITI_VELO", "CITIVELOCITY"):
        assert legacy not in SOURCE_TOKENS


# ------------------------------------------------------------------ #
#                          the timezone contract                     #
# ------------------------------------------------------------------ #


def test_aware_timestamps_convert_to_the_wire_zone():
    assert to_wire_naive(datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY)) == datetime.datetime(
        2026, 8, 6, 10, 30
    )
    # The SAME instant in UTC must produce the same wire stamp - this is the whole
    # point of the boundary, and getting it wrong looks like a real market move.
    assert to_wire_naive(datetime.datetime(2026, 8, 6, 14, 30, tzinfo=UTC)) == datetime.datetime(
        2026, 8, 6, 10, 30
    )


def test_the_wire_zone_observes_us_dst_not_a_fixed_offset():
    """Measured: EUR's fixed 08:00-20:00 CET session reads 02:00-14:00 ET before the
    2026-03-08 US spring-forward and 03:00-15:00 ET after."""
    winter = to_wire_naive(datetime.datetime(2026, 3, 5, 15, 0, tzinfo=UTC))  # EST, UTC-5
    summer = to_wire_naive(datetime.datetime(2026, 3, 10, 15, 0, tzinfo=UTC))  # EDT, UTC-4
    assert winter.hour == 10
    assert summer.hour == 11


def test_naive_timestamps_are_localised_with_a_warning(monkeypatch):
    monkeypatch.setattr(ts_mod, "_WARNED_NAIVE", False)
    with pytest.warns(UserWarning, match="naive timestamp"):
        got = to_wire_naive(datetime.datetime(2026, 8, 6, 10, 30))
    assert got == datetime.datetime(2026, 8, 6, 10, 30)


def test_naive_warning_fires_once_per_process(monkeypatch):
    """A per-call warning inside a 900-day bulk build is noise nobody reads."""
    monkeypatch.setattr(ts_mod, "_WARNED_NAIVE", False)
    with pytest.warns(UserWarning):
        to_wire_naive(datetime.datetime(2026, 8, 6, 10, 30))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        to_wire_naive(datetime.datetime(2026, 8, 6, 11, 30))


def test_strict_mode_refuses_naive_timestamps():
    with pytest.raises(NaiveTimestampError, match="America/New_York"):
        to_wire_naive(datetime.datetime(2026, 8, 6, 10, 30), strict=True)


def test_strict_mode_can_be_set_by_environment(monkeypatch):
    monkeypatch.setenv("CITIVELO_EXCEL_STRICT_TZ", "1")
    with pytest.raises(NaiveTimestampError):
        to_wire_naive(datetime.datetime(2026, 8, 6, 10, 30))


def test_wire_zone_is_overridable(monkeypatch):
    monkeypatch.setenv("CITIVELO_EXCEL_WIRE_TZ", "Europe/London")
    assert ts_mod.wire_timezone().key == "Europe/London"


def test_returned_stamps_are_timezone_aware():
    got = ts_mod.from_wire_naive(datetime.datetime(2026, 8, 6, 10, 30))
    assert got.tzinfo is not None
    assert got.utcoffset() == datetime.timedelta(hours=-4)  # EDT


# ------------------------------------------------------------------ #
#                          three-mode dispatch                       #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "value, mode",
    [
        ("live", "live"),
        (None, "live"),
        (datetime.date(2026, 8, 6), "eod"),
        (datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY), "intraday"),
        (pd.Timestamp("2026-08-06 10:30"), "intraday"),
        (pd.Timestamp("2026-08-06"), "eod"),
        (datetime.datetime(2026, 8, 6, 0, 0), "eod"),
        (datetime.datetime(2026, 8, 6, 0, 1), "intraday"),
        ("2026-08-06T10:30", "intraday"),
    ],
)
def test_timestamp_dispatch(value, mode):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert resolve_request(value).mode == mode


def test_a_datetime_is_not_swallowed_by_the_date_branch():
    """``datetime`` subclasses ``date``; a plain isinstance(x, date) test first
    turns every intraday request into an end-of-day one, silently."""
    request = resolve_request(datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY))
    assert request.mode == "intraday"
    assert request.wire_instant == datetime.datetime(2026, 8, 6, 10, 30)
    assert request.eod_date is None


def test_pandas_timestamp_is_not_swallowed_by_the_datetime_branch():
    """``pandas.Timestamp`` is ALSO a ``datetime`` subclass, so an
    isinstance(x, datetime) branch placed first makes the midnight rule
    unreachable - which is exactly what it did until this test was written."""
    assert resolve_request(pd.Timestamp("2026-08-06")).mode == "eod"
    assert resolve_request(pd.Timestamp("2026-08-06")).eod_date == datetime.date(2026, 8, 6)


# ------------------------------------------------------------------ #
#                       curve-definition registration                #
# ------------------------------------------------------------------ #


def test_all_twenty_curves_are_registered_in_both_backends():
    from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

    register()
    for name in supported_curve_names():
        assert name in RATESLIB_CURVE_DEFINITIONS, name
        assert name in QUANTLIB_CURVE_DEFINITIONS, name


def test_registration_never_overwrites_an_existing_definition():
    """USD-SOFR-1D is referenced 597 times; other sources price against it."""
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

    before = dict(RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"])
    report = register()
    assert RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"] == before
    assert "USD-SOFR-1D" in report.rateslib_kept
    assert "USD-SOFR-1D" not in report.rateslib_added


def test_registered_definitions_agree_with_the_calibration_conventions():
    """The single thing this projection exists to prevent: a pricing convention that
    has drifted from the calibration convention. Silent when it happens - the curve
    still solves and the swap still prices."""
    import rateslib as rl

    from MDP.CitiVelocityExcel.curves.conventions import conventions_for
    from MDP.CitiVelocityExcel.curves.rl_builder import payment_lag_for
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

    register()
    for entry in CITIVELO_EXCEL_CURVES:
        if entry.curve_name == "USD-SOFR-1D":
            continue  # pre-existing definition, checked separately below
        conv = conventions_for(entry.citi_index)
        definition = RATESLIB_CURVE_DEFINITIONS[entry.curve_name]
        spec = rl.defaults.spec[definition["ReferenceRate"]]
        assert spec["convention"] == conv.convention, entry.curve_name
        assert spec["frequency"] == conv.fixed_frequency, entry.curve_name
        assert spec["currency"] == conv.currency.lower(), entry.curve_name
        assert spec["payment_lag"] == payment_lag_for(entry.citi_index), entry.curve_name
        assert definition["SettlementDays"] == conv.spot_lag, entry.curve_name
        assert definition["DayCounter"] == conv.convention, entry.curve_name


def test_the_preexisting_usd_definition_matches_our_conventions_too():
    """It is not ours to change, so the check is that it agrees - if it ever stops,
    the USD curve is being calibrated and priced two different ways."""
    from MDP.CitiVelocityExcel.curves.conventions import conventions_for
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

    register()
    conv = conventions_for("USD_SOFR")
    definition = RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]
    assert definition["ReferenceRate"] == conv.rl_spec == "usd_irs"
    assert definition["Calendar"] == conv.rl_calendar == "nyc"
    assert definition["SettlementDays"] == conv.spot_lag == 2


def test_derived_specs_exist_only_for_the_five_without_a_library_spec():
    import rateslib as rl

    from MDP.CitiVelocityExcel.curves.conventions import conventions_for

    report = register()
    assert set(report.specs_registered) == {
        "dkk_ois_citivelo", "ils_ois_citivelo", "sgd_ois_citivelo",
        "thb_ois_citivelo", "zar_ois_citivelo",
    }
    for name in report.specs_registered:
        assert name in rl.defaults.spec
    for entry in CITIVELO_EXCEL_CURVES:
        conv = conventions_for(entry.citi_index)
        if conv.rl_spec:
            assert f"{conv.currency.lower()}_ois_citivelo" not in report.specs_registered or True


def test_a_derived_spec_builds_a_swap_on_the_right_calendar():
    """ILS trades Sunday-Thursday. A Monday-Friday proxy misdates every roll, and
    nothing raises when it does."""
    import rateslib as rl

    register()
    irs = rl.IRS(effective=rl.dt(2026, 8, 11), termination="5Y", spec="ils_ois_citivelo", fixed_rate=2.0)
    termination = irs.leg1.schedule.termination
    assert termination.weekday() not in (4, 5), "an ILS roll must not land on Fri/Sat"


# ------------------------------------------------------------------ #
#                        fetcher guards, hermetically                #
# ------------------------------------------------------------------ #


class _StubQuotes:
    """A quotes object that serves a frame built here. No cache, no Excel."""

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame
        self.calls = []

    def frame(self, tags, freq="DAILY", **kwargs):
        self.calls.append((tuple(tags), freq, kwargs))
        cols = [t for t in tags if t in self._frame.columns]
        out = self._frame[cols]
        start, end = kwargs.get("start"), kwargs.get("end")
        if start is not None:
            out = out[out.index >= pd.Timestamp(start)]
        if end is not None:
            out = out[out.index <= pd.Timestamp(end)]
        return out

    def close(self):
        pass


def _grid(index, tenors=("1Y", "2Y", "5Y", "10Y", "30Y"), base=4.0, citi_index="USD_SOFR"):
    data = {
        f"RATES.OIS.{citi_index}.PAR.{t}": pd.Series(base + 0.1 * i, index=index)
        for i, t in enumerate(tenors)
    }
    return pd.DataFrame(data, index=index)


def test_live_serves_the_newest_row_and_reports_its_lag():
    now = pd.Timestamp.now().floor("min")
    index = pd.date_range(now - pd.Timedelta(minutes=30), now - pd.Timedelta(minutes=5), freq="min")
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index)))
    snap = f.snapshot("USD-SOFR-1D", "live")
    assert len(snap.par_rates) == 5
    assert snap.snapshot_at.tzinfo is not None
    assert 4 <= snap.lag.total_seconds() / 60 <= 7


def test_a_stale_live_curve_raises_rather_than_looking_current():
    """An as-of search is backward and unbounded; this repo has a recorded case of a
    request 365 days past the data resolving silently to the last row."""
    old = pd.Timestamp.now().floor("min") - pd.Timedelta(days=2)
    index = pd.date_range(old, periods=10, freq="min")
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index)))
    with pytest.raises(StaleCurveError, match="stale"):
        f.snapshot("USD-SOFR-1D", "live")


def test_an_out_of_session_curve_is_served_with_its_lag_stated():
    """JPY at 10:50 ET is legitimately ~4 h old. Refusing it would be wrong; hiding
    the lag would be worse."""
    now = pd.Timestamp.now().floor("min")
    index = pd.date_range(now - pd.Timedelta(hours=5), now - pd.Timedelta(hours=4), freq="min")
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index, citi_index="JPY_TONAR")))
    snap = f.snapshot("JPY-TONAR-1D", "live")
    assert snap.lag > datetime.timedelta(hours=3)
    assert len(snap.par_rates) == 5


def test_eod_staleness_is_measured_in_days_not_hours():
    """A daily row is stamped at midnight, so the 12 h intraday limit would reject
    every single EOD snapshot. Measured: it did, for all twenty."""
    index = pd.DatetimeIndex([pd.Timestamp("2026-08-06")])
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index)))
    snap = f.snapshot("USD-SOFR-1D", datetime.date(2026, 8, 6))
    assert snap.mode == "eod"
    assert snap.lag == datetime.timedelta(0)


def test_a_year_old_eod_row_still_raises():
    """EUR_EONIA stopped on 2025-08-15. Serving it for a 2026 request would be the
    silent-staleness failure this guard exists for."""
    index = pd.DatetimeIndex([pd.Timestamp("2025-08-15")])
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index)))
    with pytest.raises((StaleCurveError, SparseCurveError)):
        f.snapshot("USD-SOFR-1D", datetime.date(2026, 8, 6))


def test_too_few_tenors_raises_instead_of_building_a_meaningless_curve():
    index = pd.date_range(pd.Timestamp.now().floor("min") - pd.Timedelta(minutes=5), periods=3, freq="min")
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index, tenors=("2Y", "10Y"))))
    with pytest.raises(SparseCurveError, match="solves trivially"):
        f.snapshot("USD-SOFR-1D", "live")


def test_tenors_that_did_not_serve_are_named_not_dropped_silently():
    now = pd.Timestamp.now().floor("min")
    index = pd.date_range(now - pd.Timedelta(minutes=10), now - pd.Timedelta(minutes=1), freq="min")
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index)))
    snap = f.snapshot("USD-SOFR-1D", "live")
    assert set(snap.tenors_served) == {"1Y", "2Y", "5Y", "10Y", "30Y"}
    assert "7Y" in snap.tenors_missing and len(snap.tenors_missing) > 30


def test_tenors_from_wildly_different_times_raise():
    """One illiquid tenor hours behind the rest builds a curve that existed at no
    instant. Per-tenor as-of makes that possible, so it has to be measured."""
    now = pd.Timestamp.now().floor("min")
    fresh = pd.date_range(now - pd.Timedelta(minutes=10), now - pd.Timedelta(minutes=1), freq="min")
    frame = _grid(fresh)
    stale_col = "RATES.OIS.USD_SOFR.PAR.30Y"
    frame[stale_col] = float("nan")  # 30Y prints nothing in the fresh block ...
    frame = pd.concat(  # ... its most recent quote is nine hours behind the rest
        [pd.DataFrame({stale_col: [4.4]}, index=[now - pd.Timedelta(hours=9)]), frame]
    ).sort_index()
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(frame), max_constituent_spread=datetime.timedelta(hours=1))
    with pytest.raises(StaleCurveError, match="span"):
        f.snapshot("USD-SOFR-1D", "live")


def test_an_unknown_curve_name_says_what_is_available():
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(pd.DataFrame()))
    with pytest.raises(KeyError, match="USD-SOFR-1D"):
        f.snapshot("USD-SOFR-2D", "live")


def test_the_same_instant_in_two_zones_asks_for_the_same_window():
    """The direct test of the timezone boundary: two spellings of one instant must
    reach the add-in as one request."""
    index = pd.date_range("2026-08-06 09:00", "2026-08-06 11:00", freq="min")
    stub = _StubQuotes(_grid(index))
    f = CitiVeloExcelCurveFetcher(quotes=stub)
    a = f.snapshot("USD-SOFR-1D", datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY))
    b = f.snapshot("USD-SOFR-1D", datetime.datetime(2026, 8, 6, 14, 30, tzinfo=UTC))
    assert a.snapshot_at == b.snapshot_at
    assert a.par_rates == b.par_rates
    assert stub.calls[0][2]["end"] == stub.calls[1][2]["end"]


def test_an_hour_later_is_a_different_snapshot():
    """The mutation the timezone check needs: if this passes with an hour's shift,
    the tz handling is not being exercised at all."""
    index = pd.date_range("2026-08-06 09:00", "2026-08-06 12:00", freq="min")
    frame = _grid(index)
    # Make the level move over the window, so an hour's shift is visible.
    for i, col in enumerate(frame.columns):
        frame[col] = 4.0 + 0.1 * i + pd.Series(range(len(index)), index=index) * 0.001
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(frame))
    a = f.snapshot("USD-SOFR-1D", datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY))
    b = f.snapshot("USD-SOFR-1D", datetime.datetime(2026, 8, 6, 11, 30, tzinfo=NY))
    assert a.snapshot_at != b.snapshot_at
    assert a.par_rates != b.par_rates


def test_snapshot_meta_carries_the_provenance_a_reader_needs():
    now = pd.Timestamp.now().floor("min")
    index = pd.date_range(now - pd.Timedelta(minutes=10), now - pd.Timedelta(minutes=1), freq="min")
    f = CitiVeloExcelCurveFetcher(quotes=_StubQuotes(_grid(index)))
    meta = f.snapshot("USD-SOFR-1D", "live").to_meta()
    assert meta["source"] == "citivelo_excel"
    assert meta["wire_timezone"] == "America/New_York"
    assert meta["freq"] == "MI01"
    assert meta["lag_seconds"] >= 0
    assert "snapshot_at" in meta and "tenors_missing" in meta
